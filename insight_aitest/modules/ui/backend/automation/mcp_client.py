# -*- coding: utf-8 -*-
"""轻量 MCP stdio 客户端（JSON-RPC 2.0，行分隔）。

只实现本项目需要的子集：initialize / tools/list / tools/call。
用于拉起 ``npx @playwright/mcp``，让大模型通过浏览器真实探索页面后再写脚本。
"""

from __future__ import annotations

import json
import logging
import os
import queue
import shutil
import subprocess
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)


class MCPError(RuntimeError):
    pass


class MCPTimeout(MCPError):
    pass


class PlaywrightMCPClient:
    def __init__(
        self,
        *,
        storage_state: str = "",
        output_dir: str = "",
        headless: bool = True,
        startup_timeout: int = 180,
        call_timeout: int = 90,
    ) -> None:
        self.storage_state = storage_state
        self.output_dir = output_dir
        self.headless = headless
        self.startup_timeout = startup_timeout
        self.call_timeout = call_timeout
        self._proc: subprocess.Popen | None = None
        self._queue: queue.Queue = queue.Queue()
        self._reader: threading.Thread | None = None
        self._next_id = 0
        # 终止标记：外部（如用户终止生成）关闭客户端时，正在等待响应的 request 立即退出
        self._closed = threading.Event()

    # ===== 生命周期 =====

    @staticmethod
    def _local_chromium() -> str:
        """本机 playwright 已下载的 chromium 可执行文件（MCP 自带版本不同，直接复用）。"""
        import glob

        roots = [Path.home() / "AppData" / "Local" / "ms-playwright"]
        if os.name != "nt":
            roots.append(Path.home() / ".cache" / "ms-playwright")
        patterns = (
            "chromium-*/chrome-win64/chrome.exe",
            "chromium-*/chrome-linux/chrome",
            "chromium-*/chrome-mac/Chromium.app/Contents/MacOS/Chromium",
        )
        for root in roots:
            for pat in patterns:
                hits = sorted(glob.glob(str(root / pat)))
                if hits:
                    return hits[-1]
        return ""

    def _build_cmd(self) -> list[str]:
        exe = self._local_chromium()
        args = ["-y", "@playwright/mcp@latest"]
        if exe:
            args += ["--executable-path", exe]
        else:
            args += ["--browser", "chrome"]
        if self.headless:
            args.append("--headless")
        if self.output_dir:
            Path(self.output_dir).mkdir(parents=True, exist_ok=True)
            args += ["--output-dir", self.output_dir]
        if self.storage_state and os.path.exists(self.storage_state):
            # MCP 的 --storage-state 只对 isolated 会话生效；默认持久化 profile 会忽略该文件
            args += ["--isolated", "--storage-state", self.storage_state]
        npx = shutil.which("npx") or "npx"
        if os.name == "nt":
            return ["cmd", "/c", npx, *args]
        return [npx, *args]

    def start(self) -> None:
        self._closed.clear()
        self._proc = subprocess.Popen(
            self._build_cmd(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        self._reader = threading.Thread(target=self._read_stdout, daemon=True)
        self._reader.start()
        threading.Thread(target=self._drain_stderr, args=(self._proc,), daemon=True).start()

        self.request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "insight-aitest", "version": "1.0.0"},
            },
            timeout=self.startup_timeout,
        )
        self.notify("notifications/initialized", {})

    def close(self) -> None:
        proc = self._proc
        self._proc = None
        self._closed.set()
        if proc is None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.close()

    # ===== 协议 =====

    def _read_stdout(self) -> None:
        assert self._proc and self._proc.stdout
        for line in self._proc.stdout:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                self._queue.put(json.loads(line))
            except json.JSONDecodeError:
                continue

    @staticmethod
    def _drain_stderr(proc: subprocess.Popen) -> None:
        """持续消费 stderr，避免管道写满导致 MCP 进程阻塞（内容不入日志）。"""
        if proc.stderr is None:
            return
        for _line in proc.stderr:
            pass

    def _send(self, payload: dict) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise MCPError("MCP 进程未启动")
        self._proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self._proc.stdin.flush()

    def notify(self, method: str, params: dict) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def request(self, method: str, params: dict | None = None, timeout: int | None = None) -> dict:
        self._next_id += 1
        req_id = self._next_id
        self._send(
            {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}}
        )
        deadline = time.time() + (timeout or self.call_timeout)
        while True:
            if self._closed.is_set():
                raise MCPError("MCP 连接已关闭（任务被终止）")
            remain = deadline - time.time()
            if remain <= 0:
                raise MCPTimeout(f"MCP 请求 {method} 超时")
            try:
                msg = self._queue.get(timeout=min(remain, 1.0))
            except queue.Empty:
                continue
            if msg.get("id") != req_id:
                continue  # 通知/别的响应，忽略
            if "error" in msg:
                raise MCPError(f"MCP {method} 失败: {msg['error']}")
            return msg.get("result") or {}

    def list_tools(self) -> list[dict]:
        return self.request("tools/list").get("tools") or []

    def call_tool(self, name: str, args: dict, timeout: int | None = None) -> tuple[str, bool]:
        """调用工具，返回 (观察文本, 是否错误)。"""
        result = self.request(
            "tools/call", {"name": name, "arguments": args or {}}, timeout=timeout
        )
        parts = []
        for item in result.get("content") or []:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
        return "\n".join(parts), bool(result.get("isError"))
