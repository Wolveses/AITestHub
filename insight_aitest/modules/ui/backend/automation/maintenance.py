# -*- coding: utf-8 -*-
"""工作区磁盘维护：清理生成期 MCP 临时文件与 Python 字节码缓存。

``mcp/`` 下的快照仅在生成过程中被读回（大快照写文件后必须内联给模型），
生成结束后无任何代码引用；``__pycache__`` 随脚本版本迭代不断产生，均属可回收垃圾。
"""

from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path

from insight_aitest.modules.ui.backend.automation import paths

logger = logging.getLogger(__name__)

# MCP 临时文件的保留天数（近几天内的快照/日志留作排查）
MCP_RETAIN_DAYS = 7
MCP_SUFFIXES = {".yml", ".log"}


def cleanup_mcp_temp(retain_days: int = MCP_RETAIN_DAYS, root: Path | None = None) -> int:
    """删除 mcp/ 下超过 ``retain_days`` 天的快照与 console 日志，返回删除文件数。"""
    cutoff = time.time() - retain_days * 86400
    base = root or paths.mcp_dir()
    if not base.exists():
        return 0
    removed = 0
    for f in base.iterdir():
        if not f.is_file() or f.suffix not in MCP_SUFFIXES:
            continue
        try:
            if f.stat().st_mtime >= cutoff:
                continue
            f.unlink()
            removed += 1
        except OSError:
            continue
    return removed


def cleanup_pycache(root: Path | None = None) -> int:
    """删除 scripts/、staging/ 下的 ``__pycache__``，返回删除目录数。"""
    workspace = root or paths.workspace_root()
    removed = 0
    for sub in ("scripts", "staging"):
        base = workspace / sub
        if not base.exists():
            continue
        for d in list(base.rglob("__pycache__")):
            if not d.is_dir():
                continue
            shutil.rmtree(d, ignore_errors=True)
            removed += 1
    return removed


def run_workspace_maintenance() -> None:
    """启动时执行一次：清理过期 MCP 临时文件与字节码缓存（失败不影响服务启动）。"""
    try:
        files = cleanup_mcp_temp()
        dirs = cleanup_pycache()
        if files or dirs:
            logger.info(f"工作区维护完成：清理 MCP 临时文件 {files} 个、__pycache__ {dirs} 个")
    except Exception:
        logger.warning("工作区维护失败", exc_info=True)
