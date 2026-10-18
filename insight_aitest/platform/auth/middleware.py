# -*- coding: utf-8 -*-
"""操作审计日志中间件。

自动拦截 POST / PUT / PATCH / DELETE 等写操作（CRUD），
提取客户端真实 IP（优先 X-Forwarded-For）、当前操作用户，
并将接口请求翻译解析为易于理解的业务操作描述（如“新建项目：xxx”、“重置用户密码”等）。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from insight_aitest.platform.auth.deps import get_user_db
from insight_aitest.platform.auth.security import decode_access_token

logger = logging.getLogger(__name__)

# 免记白名单或只读/高频探针
SKIP_PATHS = {
    "/docs",
    "/openapi.json",
    "/redoc",
    "/api/platform/auth/audit-logs",
}


def _get_client_ip(request: Request) -> str:
    """提取客户端真实 IP 地址，优先尊重反向代理头。"""
    x_forwarded_for = request.headers.get("x-forwarded-for")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    x_real_ip = request.headers.get("x-real-ip")
    if x_real_ip:
        return x_real_ip.strip()
    if request.client and request.client.host:
        return request.client.host
    return "127.0.0.1"


def _format_business_detail(
    method: str,
    path: str,
    query_params: dict[str, str],
    body_data: dict[str, Any] | None,
    username: str,
) -> tuple[str, str, str, str]:
    """根据业务接口语义解析出可读的业务操作。

    返回: (action, target_type, target_id, detail_desc)
    """
    parts = [p for p in path.strip("/").split("/") if p]
    body = body_data or {}

    # 1. 认证与用户管理平台接口 (/api/platform/auth/...)
    if "auth" in parts:
        if "login" in parts:
            req_user = body.get("username", username)
            return (
                "LOGIN",
                "用户认证",
                req_user,
                f"用户登录系统: {req_user}",
            )
        if "register" in parts:
            reg_user = body.get("username", "")
            disp = body.get("display_name", "")
            return (
                "REGISTER",
                "用户",
                reg_user,
                f"注册新用户: {reg_user} (显示名称: {disp})",
            )
        if "change-password" in parts:
            return (
                "UPDATE",
                "用户安全",
                username,
                f"用户修改个人登录密码",
            )
        if "reset-password" in parts:
            target_id = ""
            try:
                idx = parts.index("users")
                target_id = parts[idx + 1]
            except Exception:
                pass
            return (
                "UPDATE",
                "用户",
                target_id,
                f"管理员重置用户(ID={target_id})的登录密码",
            )
        if "toggle-active" in parts:
            target_id = ""
            try:
                idx = parts.index("users")
                target_id = parts[idx + 1]
            except Exception:
                pass
            is_active = query_params.get("active")
            action_desc = "启用" if is_active in ("true", "True", "1") else "停用"
            return (
                "UPDATE",
                "用户",
                target_id,
                f"管理员{action_desc}用户账号(ID={target_id})",
            )
        if path.endswith("/me"):
            disp = body.get("display_name", "")
            return (
                "UPDATE",
                "个人设置",
                username,
                f"修改个人显示名称为: {disp}",
            )

    # 2. 项目分类管理 (/api/platform/projects/...)
    if "projects" in parts:
        proj_id = ""
        try:
            idx = parts.index("projects")
            if idx + 1 < len(parts):
                proj_id = parts[idx + 1]
        except Exception:
            pass

        if method == "POST":
            name = body.get("name", "")
            desc = body.get("description", "")
            return (
                "CREATE",
                "项目",
                name,
                f"创建新项目: {name}" + (f" ({desc})" if desc else ""),
            )
        if method == "PUT":
            name = body.get("name", "")
            return (
                "UPDATE",
                "项目",
                proj_id,
                f"更新项目信息(ID={proj_id}): {name}" if name else f"更新项目信息(ID={proj_id})",
            )
        if method == "DELETE":
            return (
                "DELETE",
                "项目",
                proj_id,
                f"删除项目(ID={proj_id})",
            )

    # 3. AI 会话相关 (/api/modules/ai/conversations/...)
    if "conversations" in parts:
        conv_id = ""
        try:
            idx = parts.index("conversations")
            if idx + 1 < len(parts):
                conv_id = parts[idx + 1]
        except Exception:
            pass

        if method == "POST":
            title = body.get("title", "新会话")
            return (
                "CREATE",
                "AI会话",
                title,
                f"发起新对话会话: {title}",
            )
        if method == "PUT" or method == "PATCH":
            title = body.get("title", "")
            return (
                "UPDATE",
                "AI会话",
                conv_id,
                f"更新会话(ID={conv_id})标题: {title}" if title else f"更新会话(ID={conv_id})配置",
            )
        if method == "DELETE":
            return (
                "DELETE",
                "AI会话",
                conv_id,
                f"删除会话(ID={conv_id})",
            )

    # 4. AI 任务管理 (/api/modules/ai/tasks/...)
    if "tasks" in parts:
        task_id = ""
        try:
            idx = parts.index("tasks")
            if idx + 1 < len(parts):
                task_id = parts[idx + 1]
        except Exception:
            pass

        if "select" in parts:
            strategy = body.get("strategy_id") or body.get("strategy", "")
            return (
                "UPDATE",
                "测试任务",
                task_id,
                f"选定测试策略执行(TaskID={task_id}): {strategy}",
            )
        if "upload" in parts:
            return (
                "CREATE",
                "测试任务",
                "",
                "上传测试任务参考附件文档",
            )
        if method == "POST":
            intent = body.get("intent", "")
            brief = intent[:40] + ("..." if len(intent) > 40 else "") if intent else "新测试任务"
            return (
                "CREATE",
                "测试任务",
                "",
                f"创建自主测试任务: {brief}",
            )
        if method == "DELETE":
            return (
                "DELETE",
                "测试任务",
                task_id,
                f"取消/删除测试任务(TaskID={task_id})",
            )

    # 5. 知识库相关 (/api/modules/kb/...)
    if "kb" in parts or "documents" in parts:
        if method == "POST":
            title = body.get("title") or body.get("name", "")
            return (
                "CREATE",
                "知识库",
                title,
                f"导入知识库文档: {title}" if title else "上传/创建知识库文档",
            )
        if method == "DELETE":
            doc_id = parts[-1] if parts else ""
            return (
                "DELETE",
                "知识库",
                doc_id,
                f"删除知识库文档(ID={doc_id})",
            )

    # 6. 通用回退推导
    method_action_map = {
        "POST": ("CREATE", "创建业务数据"),
        "PUT": ("UPDATE", "更新业务数据"),
        "PATCH": ("UPDATE", "修改业务数据"),
        "DELETE": ("DELETE", "删除业务数据"),
    }
    action, action_label = method_action_map.get(method, (method, "操作业务数据"))
    target_type = parts[-2] if len(parts) >= 2 else (parts[0] if parts else "系统")
    target_id = parts[-1] if len(parts) >= 2 else ""

    return (
        action,
        target_type,
        target_id,
        f"{action_label}: {target_type} (ID={target_id})" if target_id else f"{action_label}: {target_type}",
    )


class AuditLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        method = request.method.upper()
        path = request.url.path

        # 仅针对写操作（CRUD）进行审计记录：POST, PUT, PATCH, DELETE
        # GET、OPTIONS、HEAD 等只读/预检请求不记录
        should_audit = method in ("POST", "PUT", "PATCH", "DELETE") and not any(
            path.startswith(p) for p in SKIP_PATHS
        )

        # 尝试从请求头中提取认证身份
        user_id = None
        username = "anonymous"
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
            payload = decode_access_token(token)
            if payload:
                user_id = payload.get("sub")
                username = payload.get("username", "anonymous")

        client_ip = _get_client_ip(request)

        # 尝试读取请求体并保留可重复读
        body_data: dict[str, Any] | None = None
        if should_audit:
            content_type = request.headers.get("content-type", "")
            if "application/json" in content_type:
                try:
                    body_bytes = await request.body()
                    if body_bytes:
                        body_data = json.loads(body_bytes.decode("utf-8"))
                except Exception:
                    pass

        # 执行真实请求
        response = await call_next(request)

        # 记录审计日志
        if should_audit:
            try:
                # 若请求为登录，且此前未带 token，解析登录提交的用户名
                if path.endswith("/login") and body_data and "username" in body_data:
                    username = body_data["username"]

                query_params = dict(request.query_params)
                action, target_type, target_id, detail = _format_business_detail(
                    method=method,
                    path=path,
                    query_params=query_params,
                    body_data=body_data,
                    username=username,
                )

                db = get_user_db()
                db.log_action(
                    action=action,
                    user_id=user_id,
                    username=username,
                    target_type=target_type,
                    target_id=target_id,
                    detail=detail,
                    client_ip=client_ip,
                    status_code=response.status_code,
                )
            except Exception as e:
                logger.warning("审计日志记录失败（非致命）: %s", e)

        return response
