# -*- coding: utf-8 -*-
"""环境配置服务：CRUD 辅助 + 登录换 token + storageState 生成。

安全约定：
- 密码存 ``~/.insight_eye/ui/envs.json``（与数据库分离），DB 只存 ``password_ref``；
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
        "auth_script": getattr(env, "auth_script", "") or "",
        "token_inject": getattr(env, "token_inject", "cookie") or "cookie",
        "token_name": getattr(env, "token_name", "token") or "token",
        "token_prefix": getattr(env, "token_prefix", "") or "",
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


AUTH_SCRIPT_TEMPLATES = [
    {
        "id": "json_post",
        "name": "通用 POST JSON 登录 (返回 Token 字符串)",
        "description": "向登录接口发送 JSON 格式用户名密码，直接返回 access_token 字符串",
        "code": '''import httpx

def get_token(base_url: str, username: str, password: str) -> str:
    """向登录接口发送 POST 请求，获取并返回 token 字符串。
    
    :param base_url: 环境域名地址（如 https://example.com）
    :param username: 用户名
    :param password: 密码
    :return: token 字符串
    """
    resp = httpx.post(
        f"{base_url}/api/auth/login",
        json={"username": username, "password": password},
        headers={"Content-Type": "application/json"},
        timeout=15,
        verify=False,
    )
    resp.raise_for_status()
    data = resp.json()
    # 根据响应体实际层级提取 token，如 data["token"] 或 data["data"]["token"]
    token = data.get("token") or (data.get("data") or {}).get("token")
    if not token:
        raise ValueError(f"登录响应中未找到 token 字段: {data}")
    return str(token)
''',
    },
    {
        "id": "md5_login",
        "name": "MD5 加密登录 (返回 Token 字符串)",
        "description": "将密码进行 MD5 哈希后再发送请求",
        "code": '''import hashlib
import httpx

def get_token(base_url: str, username: str, password: str) -> str:
    """密码 MD5 加密后发送登录请求。"""
    pwd_md5 = hashlib.md5(password.encode("utf-8")).hexdigest()
    resp = httpx.post(
        f"{base_url}/api/login",
        json={"username": username, "password": pwd_md5},
        timeout=15,
        verify=False,
    )
    resp.raise_for_status()
    data = resp.json()
    token = data.get("access_token") or (data.get("data") or {}).get("access_token") or data.get("token")
    if not token:
        raise ValueError(f"登录响应中未包含 access_token: {data}")
    return str(token)
''',
    },
    {
        "id": "custom_dict",
        "name": "高级自定义登录态 (返回字典)",
        "description": "返回包含 token、headers、cookies 或 localStorage 的字典结构",
        "code": '''import httpx

def get_token(base_url: str, username: str, password: str) -> dict:
    """返回复合字典，支持自定义写入 Cookie、LocalStorage 和请求头。"""
    resp = httpx.post(
        f"{base_url}/api/login",
        json={"username": username, "password": password},
        timeout=15,
        verify=False,
    )
    resp.raise_for_status()
    token = resp.json().get("data", {}).get("token", "")

    return {
        "token": token,
        "headers": {
            "Authorization": f"Bearer {token}",
        },
        "cookies": [
            {"name": "session_id", "value": token},
        ],
        "local_storage": {
            "auth_token": token,
            "user_name": username,
        },
    }
''',
    },
    {
        "id": "builtin_zone",
        "name": "项目001内置系统登录 (zoneId + 双重MD5)",
        "description": "原内置系统的完整登录逻辑（换取 zoneId，计算 MD5(MD5(username) + password)，写入 OAuth Cookie 与 localStorage）",
        "code": '''import base64
import hashlib
import json
import time
import urllib.parse
import httpx

def get_token(base_url: str, username: str, password: str) -> dict:
    """项目001 专用多步登录：zoneId -> 双重 MD5 -> 换取 Token 并写入 Cookie 与 localStorage。"""
    base = base_url.rstrip("/")
    headers = {
        "Authorization": "Basic ZGlnaWJpcmRfd2ViX2NsaWVudDpkaWdpYmlyZF93ZWJfc2VjcmV0",
        "Referer": f"{base}/login",
        "X-CLIENT-ID": "874477ff396f4df8b9cc29c37665d8e8",
    }
    with httpx.Client(timeout=30, verify=False) as client:
        # 1. 获取 zoneId
        z_resp = client.get(f"{base}/resource/api/local", params={"t": int(time.time() * 1000)}, headers=headers)
        z_resp.raise_for_status()
        z_data = z_resp.json()
        zone_id = z_data.get("id") or z_data.get("zoneId") or ""
        zone_name = str(z_data.get("name") or "")

        # 2. 密码加密 MD5(MD5(username) + password)
        md5 = lambda s: hashlib.md5(s.encode("utf-8")).hexdigest().upper()
        enc_pwd = md5(md5(username) + password)

        # 3. 登录请求
        l_headers = dict(headers)
        l_headers.update({"Content-Type": "application/json;text/html", "Origin": base})
        l_resp = client.post(
            f"{base}/usm/api/oauth/token/get",
            json={
                "grant_type": "password",
                "remember": True,
                "username": username,
                "password": enc_pwd,
                "zoneId": zone_id,
            },
            headers=l_headers,
        )
        l_resp.raise_for_status()
        payload = l_resp.json()
        token = payload.get("access_token") or payload.get("token") or ""
        expires_in = int(payload.get("expires_in") or 900)

        # 4. 组装 Cookie 与 localStorage
        token_obj = {
            "expirationTime": int(time.time() * 1000) + expires_in * 1000,
            "expires_in": expires_in,
            "access_token": token,
            "refresh_token": payload.get("refresh_token") or "",
            "scope": payload.get("scope") or "",
            "isCrossZone": bool(payload.get("isCrossZone")),
        }
        cookie_name = base64.b64encode(b"darwin_oauth_token").decode()
        cookie_val = urllib.parse.quote(json.dumps(token_obj, separators=(",", ":"), ensure_ascii=False), safe="")

        return {
            "token": token,
            "cookies": [
                {"name": cookie_name, "value": cookie_val, "expires": int(time.time()) + expires_in}
            ],
            "local_storage": {
                "local-zone-info": json.dumps({"id": zone_id, "name": zone_name}, ensure_ascii=False)
            },
        }
''',
    },
]


def _sanitize_error(text: str, password: str, token: str) -> str:
    res = text or ""
    if password and len(password) >= 3:
        res = res.replace(password, "***")
    if token and len(token) >= 4:
        res = res.replace(token, "***")
    return res


_AUTH_RUNNER_CODE = '''import sys
import json

def _run():
    raw = sys.stdin.read()
    payload = json.loads(raw)
    base_url = payload.get("base_url", "")
    username = payload.get("username", "")
    password = payload.get("password", "")
    script = payload.get("script", "")

    scope = {"__name__": "__auth_script__"}
    exec(script, scope)

    if "get_token" not in scope or not callable(scope["get_token"]):
        raise ValueError("前置脚本中未定义可调用的函数 get_token(base_url, username, password)")

    res = scope["get_token"](base_url, username, password)
    print("---AUTH_OUTPUT_START---")
    print(json.dumps(res, ensure_ascii=False))

if __name__ == "__main__":
    _run()
'''


def execute_auth_script(script: str, base_url: str, username: str, password: str, timeout: int = 30) -> tuple[bool, str, any]:
    """执行用户自定义的前置脚本，输入 base_url, username, password，输出解析后的 token 或字典。"""
    import ast
    import subprocess
    import sys

    # 1. 语法检查
    try:
        ast.parse(script)
    except SyntaxError as e:
        return False, f"脚本语法错误（第 {e.lineno} 行）: {e.msg}", None

    # 2. 子进程隔离运行
    payload = {
        "base_url": base_url,
        "username": username,
        "password": password,
        "script": script,
    }
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _AUTH_RUNNER_CODE],
            input=json.dumps(payload, ensure_ascii=False),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, f"前置脚本执行超时（超过 {timeout} 秒）", None
    except Exception as e:
        return False, f"前置脚本启动失败: {type(e).__name__}: {e}", None

    if proc.returncode != 0:
        err = proc.stderr.strip() or proc.stdout.strip() or f"进程退出码: {proc.returncode}"
        lines = [l for l in err.splitlines() if l.strip()]
        brief = "\n".join(lines[-8:]) if len(lines) > 8 else err
        clean = _sanitize_error(brief, password, "")
        return False, f"脚本执行失败:\n{clean}", None

    marker = "---AUTH_OUTPUT_START---"
    stdout = proc.stdout
    if marker not in stdout:
        return False, "前置脚本执行未产生有效输出", None

    out_part = stdout.split(marker, 1)[1].strip()
    try:
        res = json.loads(out_part)
        return True, "", res
    except Exception as e:
        return False, f"解析脚本返回值 JSON 失败: {e}", None


def _handle_script_result(env, res: any, base_url: str) -> AuthResult:
    """把脚本返回值（str 或 dict）转换为标准的 AuthResult 和 storageState。"""
    import time
    from urllib.parse import urlparse

    u = urlparse((base_url or "").rstrip("/"))
    host = u.hostname or ""
    origin = f"{u.scheme}://{u.netloc}"
    secure = u.scheme == "https"

    inject = (getattr(env, "token_inject", "") or "cookie").lower()
    token_name = getattr(env, "token_name", "") or "token"
    token_prefix = getattr(env, "token_prefix", "") or ""

    # 1. 如果返回纯字符串 token
    if isinstance(res, (str, int)):
        token = str(res).strip()
        if not token:
            return AuthResult(False, "脚本返回的 token 为空")
        val = f"{token_prefix}{token}"

        if inject == "header":
            header_name = token_name if token_name else "Authorization"
            return AuthResult(True, "登录成功，已生成请求头", token=token, headers={header_name: val})
        elif inject == "localstorage":
            state = {
                "cookies": [],
                "origins": [
                    {
                        "origin": origin,
                        "localStorage": [{"name": token_name, "value": val}],
                    }
                ],
            }
            path = _dump_state(env.project_id, env.id, state)
            return AuthResult(True, "登录成功，已生成 LocalStorage 登录态", token=token, storage_state_path=path)
        else:
            # 默认 cookie
            state = {
                "cookies": [
                    {
                        "name": token_name,
                        "value": val,
                        "domain": host,
                        "path": "/",
                        "expires": int(time.time()) + 86400,
                        "httpOnly": False,
                        "secure": secure,
                        "sameSite": "Lax",
                    }
                ],
                "origins": [],
            }
            path = _dump_state(env.project_id, env.id, state)
            return AuthResult(True, "登录成功，已生成 Cookie 登录态", token=token, storage_state_path=path)

    # 2. 如果返回字典
    if isinstance(res, dict):
        token = str(res.get("token") or res.get("access_token") or "").strip()
        headers = dict(res.get("headers") or {})

        raw_cookies = res.get("cookies")
        raw_ls = res.get("local_storage") or res.get("localStorage")
        raw_origins = res.get("origins")

        cookies = []
        if isinstance(raw_cookies, list):
            for ck in raw_cookies:
                if isinstance(ck, dict) and ck.get("name") and ck.get("value") is not None:
                    cookies.append({
                        "name": str(ck["name"]),
                        "value": str(ck["value"]),
                        "domain": ck.get("domain") or host,
                        "path": ck.get("path") or "/",
                        "expires": int(ck.get("expires") or (time.time() + 86400)),
                        "httpOnly": bool(ck.get("httpOnly", False)),
                        "secure": bool(ck.get("secure", secure)),
                        "sameSite": ck.get("sameSite", "Lax"),
                    })

        origins = []
        if isinstance(raw_origins, list):
            origins = raw_origins
        elif isinstance(raw_ls, dict):
            ls_list = [{"name": str(k), "value": str(v)} for k, v in raw_ls.items()]
            origins.append({"origin": origin, "localStorage": ls_list})
        elif isinstance(raw_ls, list):
            origins.append({"origin": origin, "localStorage": raw_ls})

        # 若既无 cookies 也无 origins，但返回了 token，按环境配置补齐
        if not cookies and not origins and token:
            val = f"{token_prefix}{token}"
            if inject == "header":
                header_name = token_name if token_name else "Authorization"
                headers.setdefault(header_name, val)
            elif inject == "localstorage":
                origins.append({"origin": origin, "localStorage": [{"name": token_name, "value": val}]})
            else:
                cookies.append({
                    "name": token_name,
                    "value": val,
                    "domain": host,
                    "path": "/",
                    "expires": int(time.time()) + 86400,
                    "httpOnly": False,
                    "secure": secure,
                    "sameSite": "Lax",
                })

        state = {"cookies": cookies, "origins": origins}
        path = _dump_state(env.project_id, env.id, state) if (cookies or origins) else ""
        return AuthResult(
            True,
            "登录成功，已生成自定义登录态",
            token=token,
            headers=headers,
            storage_state_path=path,
        )

    return AuthResult(False, f"前置脚本返回值必须为 str 或 dict，实际类型为 {type(res).__name__}")


def prepare_auth(env, override_script: str | None = None, override_password: str | None = None) -> AuthResult:
    """生成/执行前准备登录态。

    优先判断是否配置了前置脚本 auth_script：
    - 若配置了 auth_script，执行用户自定义 Python 脚本换取 token / 登录态；
    - 若未配置 auth_script，回退执行原本内置的 _login(env) 流程。
    """
    script = (override_script if override_script is not None else getattr(env, "auth_script", "")) or ""
    script = script.strip()

    if script:
        base = (env.base_url or "").rstrip("/")
        if not base:
            return AuthResult(False, "未配置环境地址 base_url")
        username = env.username or ""
        password = override_password if override_password is not None else get_password(getattr(env, "password_ref", ""))
        ok, err_msg, res = execute_auth_script(script, base, username, password)
        if not ok:
            return AuthResult(False, err_msg)
        result = _handle_script_result(env, res, base)
    else:
        result = _login(env)

    if result.storage_state_path:
        try:
            from insight_aitest.modules.ui.backend.automation.deps import get_automation_db

            rel = paths.to_rel(paths.storage_state_path(env.project_id, env.id))
            get_automation_db().update_env(env.id, storage_state_rel=rel)
        except Exception as e:
            logger.warning("回写 storage_state_rel 失败: %s", e)
    return result


def test_env(env, override_fields: dict | None = None) -> dict:
    """连通性测试：先探 base_url，再执行前置脚本/登录流程。"""
    import httpx

    overrides = override_fields or {}
    base_url = overrides.get("base_url") or env.base_url or ""
    base = base_url.rstrip("/")
    if not base:
        return {"ok": False, "message": "未配置环境地址 base_url"}
    try:
        with httpx.Client(follow_redirects=True, timeout=15, verify=False) as client:
            r = client.get(base)
        reach_msg = f"站点可访问（HTTP {r.status_code}）"
    except Exception as e:
        return {"ok": False, "message": f"站点不可访问: {type(e).__name__}: {e}"}

    override_script = overrides.get("auth_script")
    override_pwd = overrides.get("password")

    test_target = env
    if overrides:
        class _TempEnv:
            pass
        temp = _TempEnv()
        for k in ("id", "project_id", "name", "base_url", "username", "password_ref", "auth_script", "token_inject", "token_name", "token_prefix"):
            setattr(temp, k, overrides.get(k, getattr(env, k, "")))
        test_target = temp

    auth = prepare_auth(test_target, override_script=override_script, override_password=override_pwd)
    if not auth.ok:
        return {"ok": False, "message": reach_msg + "；" + auth.message}

    token_preview = ""
    if auth.token:
        tp = auth.token
        masked = tp[:6] + "***" + tp[-4:] if len(tp) > 12 else tp[:3] + "***"
        token_preview = f" (Token: {masked})"

    return {"ok": True, "message": reach_msg + "；" + auth.message + token_preview, "token": auth.token}
