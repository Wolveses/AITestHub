# -*- coding: utf-8 -*-
"""Mobile MCP Server（JSON-RPC 2.0 协议实现）。

支持：
1. HTTP Streamable / JSON-RPC 端点（挂载在 /api/modules/mobile/mcp），供开发者本机 Agent 直连；
2. 进程内直接调用 dispatch_mcp_message(payload, session_token) 便于测试与同机桥接。
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any

from insight_aitest.modules.mobile.backend.automation import session_manager as sm
from insight_aitest.modules.mobile.backend.deps import get_mobile_db

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = "2024-11-05"

TOOLS_SPEC: list[dict[str, Any]] = [
    {
        "name": "get_case_context",
        "description": "获取当前手机自动化用例详情、App 环境、已有 pages 页面对象索引、错题经验与脚手架规则。",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "mobile_launch_app",
        "description": "在平台主机直连设备上启动被测 App（可选择清数据冷启动）。",
        "inputSchema": {
            "type": "object",
            "properties": {"clear_data": {"type": "boolean", "default": False}},
        },
    },
    {
        "name": "mobile_snapshot",
        "description": "获取当前手机界面裁剪后的控件树文本及短引用 [ref=eN]。",
        "inputSchema": {
            "type": "object",
            "properties": {"compact": {"type": "boolean", "default": False}},
        },
    },
    {
        "name": "mobile_screenshot",
        "description": "截取当前手机屏幕图像并返回，同时同步保存过程截图供平台前端实时预览。",
        "inputSchema": {
            "type": "object",
            "properties": {"label": {"type": "string", "default": ""}},
        },
    },
    {
        "name": "mobile_tap",
        "description": "点击 mobile_snapshot 返回的指定 ref 控件，并返回推荐的 Appium 定位写法。",
        "inputSchema": {
            "type": "object",
            "properties": {"ref": {"type": "string"}},
            "required": ["ref"],
        },
    },
    {
        "name": "mobile_input",
        "description": "向指定 ref 输入框输入文本，并返回推荐的 Appium 定位写法。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ref": {"type": "string"},
                "text": {"type": "string"},
                "clear_first": {"type": "boolean", "default": True},
                "hide_keyboard": {"type": "boolean", "default": False},
            },
            "required": ["ref", "text"],
        },
    },
    {
        "name": "mobile_swipe",
        "description": "按屏幕比例向指定方向滑动（up/down/left/right）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "direction": {"type": "string", "enum": ["up", "down", "left", "right"]},
                "distance_ratio": {"type": "number", "default": 0.5},
            },
            "required": ["direction"],
        },
    },
    {
        "name": "mobile_back",
        "description": "按下 Android 返回键。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "mobile_handle_alert",
        "description": "处理系统权限或确认弹窗（accept 或 dismiss）。",
        "inputSchema": {
            "type": "object",
            "properties": {"action": {"type": "string", "enum": ["accept", "dismiss"], "default": "accept"}},
        },
    },
    {
        "name": "read_staging_file",
        "description": "读取当前暂存区文件（case.py 或 pages/*.py）。",
        "inputSchema": {
            "type": "object",
            "properties": {"rel_path": {"type": "string"}},
            "required": ["rel_path"],
        },
    },
    {
        "name": "write_staging_file",
        "description": "写入当前暂存区文件（仅允许 case.py 或 pages/*.py）。",
        "inputSchema": {
            "type": "object",
            "properties": {"rel_path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["rel_path", "content"],
        },
    },
    {
        "name": "run_server_dry_run",
        "description": "在平台主机对暂存区 case.py 执行静态校验 + 真实 pytest 试跑，返回日志与结果。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "commit_staging_script",
        "description": "在服务端试跑通过后，将暂存区脚本与页面对象正式固化入库并释放设备锁。",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def _text_result(data: Any) -> dict[str, Any]:
    text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, indent=2)
    return {"content": [{"type": "text", "text": text}], "isError": False}


def _error_result(msg: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": msg}], "isError": True}


def execute_mcp_tool(rt: sm.SessionRuntime, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """执行单个 MCP 工具并记录调用次数与事件日志。"""
    args = arguments or {}
    with rt.lock:
        rt.tool_calls += 1
        get_mobile_db().update_generation(rt.generation_id, tool_calls=rt.tool_calls)
        sm.append_event(rt.case_id, rt.generation_id, "tool_call", tool=name, args=args)

        try:
            if name == "get_case_context":
                return _text_result(sm.tool_get_case_context(rt))
            if name == "mobile_launch_app":
                drv = sm._ensure_driver(rt, clear_data=bool(args.get("clear_data", False)))
                app = get_mobile_db().get_app(rt.app_id)
                if app and app.app_package:
                    try:
                        if drv.current_package != app.app_package:
                            drv.activate_app(app.app_package)
                    except Exception:
                        pass
                return _text_result({"ok": True, "device_id": rt.device_id})
            if name == "mobile_snapshot":
                return _text_result(sm.tool_snapshot(rt, compact=bool(args.get("compact", False))))
            if name == "mobile_screenshot":
                png_bytes, filename = sm.tool_screenshot(rt, label=str(args.get("label") or ""))
                b64 = base64.b64encode(png_bytes).decode("ascii")
                return {
                    "content": [
                        {"type": "text", "text": f"已保存过程截图: {filename}"},
                        {"type": "image", "data": b64, "mimeType": "image/png"},
                    ],
                    "isError": False,
                }
            if name == "mobile_tap":
                return _text_result(sm.tool_tap(rt, str(args.get("ref") or "")))
            if name == "mobile_input":
                return _text_result(
                    sm.tool_input(
                        rt,
                        str(args.get("ref") or ""),
                        str(args.get("text") or ""),
                        clear_first=bool(args.get("clear_first", True)),
                        hide_keyboard=bool(args.get("hide_keyboard", False)),
                    )
                )
            if name == "mobile_swipe":
                return _text_result(
                    sm.tool_swipe(
                        rt,
                        direction=str(args.get("direction") or "up"),
                        distance_ratio=float(args.get("distance_ratio") or 0.5),
                    )
                )
            if name == "mobile_back":
                drv = sm._ensure_driver(rt)
                drv.back()
                return _text_result({"ok": True})
            if name == "mobile_handle_alert":
                drv = sm._ensure_driver(rt)
                act = str(args.get("action") or "accept")
                if act == "dismiss":
                    drv.switch_to.alert.dismiss()
                else:
                    drv.switch_to.alert.accept()
                return _text_result({"ok": True, "action": act})
            if name == "read_staging_file":
                return _text_result(sm.tool_read_staging_file(rt, str(args.get("rel_path") or "")))
            if name == "write_staging_file":
                return _text_result(
                    sm.tool_write_staging_file(
                        rt, str(args.get("rel_path") or ""), str(args.get("content") or "")
                    )
                )
            if name == "run_server_dry_run":
                return _text_result(sm.tool_run_server_dry_run(rt))
            if name == "commit_staging_script":
                return _text_result(sm.tool_commit_staging_script(rt))
            return _error_result(f"未知工具: {name}")
        except Exception as e:
            sm.append_event(rt.case_id, rt.generation_id, "tool_error", tool=name, error=str(e))
            return _error_result(f"{type(e).__name__}: {e}")


def dispatch_mcp_message(payload: dict[str, Any], session_token: str) -> dict[str, Any] | None:
    """处理一条 JSON-RPC 2.0 MCP 消息；通知类消息返回 None。"""
    req_id = payload.get("id")
    method = payload.get("method", "")
    params = payload.get("params") or {}

    if method == "notifications/initialized" or req_id is None:
        return None

    if method == "initialize":
        # 允许初始化阶段先验证 Token 有效性
        sm.authenticate_session(session_token)
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "insight-mobile-mcp", "version": "1.0.0"},
            },
        }

    rt, _ = sm.authenticate_session(session_token)

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS_SPEC}}

    if method == "tools/call":
        name = str(params.get("name") or "")
        arguments = params.get("arguments") or {}
        result = execute_mcp_tool(rt, name, arguments)
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }
