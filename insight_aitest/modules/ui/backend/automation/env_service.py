# -*- coding: utf-8 -*-
"""环境配置服务：CRUD 辅助 + 登录换 token + storageState 生成。

安全约定：
- 密码存 ``~/.insight_eye/ui_envs.json``（与数据库分离），DB 只存 ``password_ref``；
- 接口/日志/异常消息都不输出密码与 token 明文。

token 注入三态：
- cookie：登录响应 Cookie → storageState（MCP 与脚本共用）；
- localStorage：用 playwright 打开站点写入 token → storageState；
- header：登录响应 token 作为请求头，脚本执行时注入（MCP 探索场景首版不保证支持）。
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field

from insight_aitest.modules.ui.backend.automation import paths

logger = logging.getLogger(__name__)

_SECRET_LOCK = threading.Lock()

# 后台入口相对路径：前台为根路径，后台为 base_url + 该路径
BACKEND_PATH = "/manage"

# ===== 项目001 被测系统的登录协议（写死，仅 base_url/用户名/密码 可变） =====
_BASIC_AUTH = "Basic ZGlnaWJpcmRfd2ViX2NsaWVudDpkaWdpYmlyZF93ZWJfc2VjcmV0"
_CLIENT_ID = "874477ff396f4df8b9cc29c37665d8e8"
_ZONE_API = "/resource/api/local"
_LOGIN_API = "/usm/api/oauth/token/get"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36"
)
# 实测该接口返回 {"id": "...", "name": "..."}，zoneId 即顶层 id
_ZONE_KEYS = ("zoneid", "zone_id", "zone", "id")


def _login_headers(base: str) -> dict:
    return {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Authorization": _BASIC_AUTH,
        "Client-Timezone-Offset": "GMT+0800",
        "Connection": "keep-alive",
        "Referer": f"{base}/login",
        "User-Agent": _USER_AGENT,
        "X-CLIENT-ID": _CLIENT_ID,
    }


def encrypt_password(user: str, password: str) -> str:
    """被测系统登录密码加密，与线上前端一致：MD5(MD5(用户名) + 明文密码)。

    依据：前端 vendor 的 MD5 包装为 `SparkMD5.hash(str).toUpperCase()`，
    登录调用为 `password: MD5(MD5(username) + password)`。
    """
    import hashlib

    md5 = lambda s: hashlib.md5(s.encode("utf-8")).hexdigest().upper()  # noqa: E731
    return md5(md5(user) + password)


def _error_message(resp) -> str:
    """从错误响应里取服务端提示（只可能是账号错误等提示，不含凭证明文）。"""
    try:
        body = resp.json()
    except ValueError:
        return ""
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])
        if body.get("message"):
            return str(body["message"])
    return ""


def _find_value(data, keys: tuple[str, ...]) -> str:
    """在 JSON 里按 keys 优先级递归找第一个命中的标量值（键名不区分大小写）。"""
    if isinstance(data, dict):
        lowered = {str(k).lower(): v for k, v in data.items()}
        for key in keys:
            v = lowered.get(key)
            if isinstance(v, (str, int)) and str(v).strip():
                return str(v)
        for v in data.values():
            found = _find_value(v, keys)
            if found:
                return found
    elif isinstance(data, list):
        for item in data:
            found = _find_value(item, keys)
            if found:
                return found
    return ""


def site_url(env, site: str) -> str:
    """按用例所属端计算入口地址（后台追加 /manage；前台/后台共用同一登录态）。"""
    base = (getattr(env, "base_url", "") or "").rstrip("/")
    if not base:
        return ""
    if site == "backend":
        return f"{base}{BACKEND_PATH}"
    return base


def _read_secrets() -> dict:
    p = paths.env_secrets_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _write_secrets(data: dict) -> None:
    p = paths.env_secrets_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        p.chmod(0o600)
    except OSError:
        pass


def get_password(ref: str) -> str:
    if not ref:
        return ""
    with _SECRET_LOCK:
        return str(_read_secrets().get(ref, ""))


def set_password(ref: str, password: str) -> None:
    if not ref:
        return
    with _SECRET_LOCK:
        data = _read_secrets()
        data[ref] = password
        _write_secrets(data)


def delete_password(ref: str) -> None:
    if not ref:
        return
    with _SECRET_LOCK:
        data = _read_secrets()
        if ref in data:
            data.pop(ref)
            _write_secrets(data)


def env_public(env) -> dict:
    """环境配置的可回显字段（绝不包含密码/token 明文）。"""
    return {
        "id": env.id,
        "project_id": env.project_id,
        "name": env.name,
        "base_url": env.base_url,
        "username": env.username,
        "password_set": bool(env.password_ref and get_password(env.password_ref)),
        "is_default": bool(env.is_default),
        "has_storage_state": bool(env.storage_state_rel),
    }


@dataclass
class AuthResult:
    ok: bool
    message: str = ""
    token: str = ""
    headers: dict = field(default_factory=dict)
    storage_state_path: str = ""


def _dig(data: dict, path: str):
    cur = data
    for key in [p for p in path.split(".") if p]:
        if isinstance(cur, dict) and key in cur:
            cur = cur[key]
        elif isinstance(cur, list) and key.isdigit():
            cur = cur[int(key)]
        else:
            return None
    return cur


def _extract_token(payload, token_path: str) -> str:
    if not isinstance(payload, dict):
        return ""
    if token_path:
        v = _dig(payload, token_path)
        return str(v) if isinstance(v, (str, int)) else ""
    for path in ("access_token", "token", "data.token", "data.access_token", "result.token"):
        v = _dig(payload, path)
        if isinstance(v, (str, int)) and str(v):
            return str(v)
    return ""


def _pick(payload, *keys):
    """按顶层 → data/result 的顺序取字段。"""
    for key in keys:
        for path in (key, f"data.{key}", f"result.{key}"):
            v = _dig(payload, path)
            if v is not None:
                return v
    return None


def _build_storage_state(env, payload, token: str, zone_id: str, zone_name: str) -> dict:
    """按线上前端的做法合成登录态：登录 Cookie + local-zone-info localStorage。

    前端逻辑（static/usm/index.js）：
    - Cookie 名 = btoa("darwin_oauth_token")，值 = encodeURIComponent(JSON.stringify({...token})),
      domain = 当前 hostname，path = "/"；
    - localStorage["local-zone-info"] = {id, name}，SPA 依赖它判断所属 zone。
    """
    import base64
    import time
    import urllib.parse
    from urllib.parse import urlparse

    u = urlparse((env.base_url or "").rstrip("/"))
    host = u.hostname or ""
    origin = f"{u.scheme}://{u.netloc}"
    secure = u.scheme == "https"
    expires_in = int(_pick(payload, "expires_in") or 900)
    now_ms = int(time.time() * 1000)
    token_obj = {
        "expirationTime": now_ms + expires_in * 1000,
        "expires_in": expires_in,
        "access_token": token,
        "refresh_token": _pick(payload, "refresh_token") or "",
        "scope": _pick(payload, "scope") or "",
        "isCrossZone": bool(_pick(payload, "isCrossZone")),
    }
    cookie_name = base64.b64encode(b"darwin_oauth_token").decode()
    cookie_value = urllib.parse.quote(
        json.dumps(token_obj, separators=(",", ":"), ensure_ascii=False), safe=""
    )
    zone = json.dumps({"id": zone_id, "name": zone_name}, ensure_ascii=False)
    return {
        "cookies": [
            {
                "name": cookie_name,
                "value": cookie_value,
                "domain": host,
                "path": "/",
                "expires": int(time.time()) + expires_in,
                "httpOnly": False,
                "secure": secure,
                "sameSite": "Lax",
            }
        ],
        "origins": [
            {
                "origin": origin,
                "localStorage": [{"name": "local-zone-info", "value": zone}],
            }
        ],
    }


def _dump_state(project_id: int, env_id: int, state: dict) -> str:
    path = paths.storage_state_path(project_id, env_id)
    path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    return str(path)


def _login(env) -> AuthResult:
    """项目001 登录流程：获取 zoneId → 加密密码 → 换取 token。

    接口、请求头、加密算法全部写死，环境里只保留 base_url/用户名/密码。
    不输出密码与 token 明文，异常只抛状态码或异常类型。
    """
    import time

    import httpx

    base = (env.base_url or "").rstrip("/")
    if not base:
        return AuthResult(False, "未配置环境地址 base_url")
    username = env.username or ""
    password = get_password(env.password_ref)
    if not username or not password:
        return AuthResult(False, "环境用户名/密码未配置")

    headers = _login_headers(base)
    try:
        # 内部系统常见自签证书，跳过校验
        with httpx.Client(follow_redirects=True, timeout=30, verify=False) as client:
            resp = client.get(
                f"{base}{_ZONE_API}", params={"t": int(time.time() * 1000)}, headers=headers
            )
            if resp.status_code >= 400:
                return AuthResult(False, f"获取 zoneId 接口返回 HTTP {resp.status_code}")
            try:
                zone_payload = resp.json()
            except ValueError:
                return AuthResult(False, "获取 zoneId 接口返回的不是 JSON")

            zone_id = _find_value(zone_payload, _ZONE_KEYS)
            zone_name = str(zone_payload.get("name") or "") if isinstance(zone_payload, dict) else ""
            if not zone_id:
                return AuthResult(False, "获取 zoneId 失败：响应中未找到 zoneId")

            login_headers = dict(headers)
            login_headers.update(
                {"Content-Type": "application/json;text/html", "Origin": base}
            )
            login_resp = client.post(
                f"{base}{_LOGIN_API}",
                json={
                    "grant_type": "password",
                    "remember": True,
                    "username": username,
                    "password": encrypt_password(username, password),
                    "zoneId": zone_id,
                },
                headers=login_headers,
            )
            if login_resp.status_code >= 400:
                # 该接口用 HTTP 500 + error.message 表达「账号或密码错误」，把原因带出来
                reason = _error_message(login_resp)
                return AuthResult(
                    False,
                    f"登录接口返回 HTTP {login_resp.status_code}" + (f"：{reason}" if reason else ""),
                )
            try:
                payload = login_resp.json()
            except ValueError:
                return AuthResult(False, "登录接口返回的不是 JSON")

            token = _extract_token(payload, "")
            if not token:
                return AuthResult(False, "登录接口未返回 access_token")
            # 该系统的登录态由前端自己写入 Cookie + localStorage，服务端不下发 Cookie，
            # 因此按前端格式合成 storageState，供 MCP 浏览器与本地脚本共用
            state = _build_storage_state(env, payload, token, zone_id, zone_name)
            path = _dump_state(env.project_id, env.id, state)
            return AuthResult(
                True, "登录成功，已生成 Cookie 登录态", token=token, storage_state_path=path
            )
    except Exception as e:
        return AuthResult(False, f"登录请求失败: {type(e).__name__}: {e}")


def prepare_auth(env) -> AuthResult:
    """生成/执行前准备登录态。

    登录协议固定（项目001），结果只有两种：
    - Cookie：返回 storageState 绝对路径，并回写 env.storage_state_rel；
    - 仅有 token：返回 Bearer 请求头（MCP 探索可用，本地脚本同样注入）。
    """
    result = _login(env)
    if result.storage_state_path:
        try:
            from insight_aitest.modules.ui.backend.automation.deps import get_automation_db

            rel = paths.to_rel(paths.storage_state_path(env.project_id, env.id))
            get_automation_db().update_env(env.id, storage_state_rel=rel)
        except Exception as e:
            logger.warning("回写 storage_state_rel 失败: %s", e)
    return result


def test_env(env) -> dict:
    """连通性测试：先探 base_url，再执行固定登录流程。"""
    import httpx

    base = (env.base_url or "").rstrip("/")
    if not base:
        return {"ok": False, "message": "未配置环境地址 base_url"}
    try:
        with httpx.Client(follow_redirects=True, timeout=15, verify=False) as client:
            r = client.get(base)
        reach_msg = f"站点可访问（HTTP {r.status_code}）"
    except Exception as e:
        return {"ok": False, "message": f"站点不可访问: {type(e).__name__}: {e}"}

    auth = prepare_auth(env)
    if not auth.ok:
        return {"ok": False, "message": reach_msg + "；" + auth.message}
    return {"ok": True, "message": reach_msg + "；" + auth.message}
