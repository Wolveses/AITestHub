# -*- coding: utf-8 -*-
"""环境配置服务：CRUD 辅助 + 自定义脚本前置获取 Token + 浏览器 storageState 生成与公共封装。

架构设计与浏览器登录态传递机制：
1. 固定输入契约：
   用户在页面定义 Python 脚本，固定提供函数签名：
   ``def get_token(base_url: str, username: str, password: str) -> str | dict``
   - base_url: 环境根地址（如 https://example.com）
   - username: 登录账号名
   - password: 明文密码（在子进程安全沙箱中执行，异常信息自动密码脱敏）

2. 固定输出契约：
   - 模式 1（通用/常用）：返回纯 Token 字符串（str），平台根据环境配置自动组装为 Cookie、LocalStorage 或 Header。
   - 模式 2（高级复合）：返回字典（dict），包含 token、headers、cookies 或 local_storage，平台自动规范化补齐。

3. 如何封装与传给浏览器（公共流程）：
   - 由公共封装器 ``BrowserAuthPacker`` 将 Token 与登录态打包为 Playwright 标准的 ``storageState.json``；
   - 落盘存储至 ``~/.insight_eye/ui/projects/{project_id}/envs/{env_id}/storageState.json``；
   - Playwright 执行引擎通过 ``browser.new_context(storage_state=path)`` 启动浏览器，
     无需每次通过 UI 重复点击登录，打开页面即自动处于已登录状态；
   - 测试执行子进程（pytest）自动注入环境变量 ``INSIGHT_UI_TOKEN`` 与 ``INSIGHT_UI_STORAGE_STATE``，
     供用例代码直接读取使用。
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


# ===== 仅保留唯一通用脚本模板 =====
AUTH_SCRIPT_TEMPLATES = [
    {
        "id": "generic_post",
        "name": "通用 POST JSON 登录模板",
        "description": "向系统登录接口发送 POST 请求换取 Token，支持返回 Token 字符串或复合字典",
        "code": '''import httpx

def get_token(base_url: str, username: str, password: str) -> str:
    """通用前置获取 Token 脚本。
    
    固定输入契约:
    :param base_url: 环境根地址（如 https://example.com）
    :param username: 用户名
    :param password: 明文密码
    
    固定输出契约:
    - 模式 1 (常用): 返回 Token 字符串 (str)，系统将根据环境配置自动组装为 Cookie / LocalStorage / Header 并注入浏览器
    - 模式 2 (高级): 返回复合字典 (dict)，如 {"token": "...", "cookies": [...], "local_storage": {...}, "headers": {...}}
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

    # 根据响应体实际层级提取 token（如 data["token"] 或 data["data"]["token"]）
    token = data.get("token") or (data.get("data") or {}).get("token")
    if not token:
        raise ValueError(f"登录响应中未找到 token 字段: {data}")
    return str(token)
''',
    },
]


class BrowserAuthPacker:
    """公共登录态封装器：将用户脚本输出的 Token 或复合字典标准化并封装为 Playwright 登录态。

    统一职责：
    1. 接收自定义脚本返回值（str 或 dict）；
    2. 针对 Token 字符串自动根据环境策略（Cookie/LocalStorage/Header）补齐域名、路径、过期时间等；
    3. 组装符合 Playwright 标准规范的 storageState 结构；
    4. 落盘至指定环境目录供浏览器启动时自动载入。
    """

    @classmethod
    def dump_storage_state(cls, project_id: int, env_id: int, state: dict) -> str:
        """将 storageState 写入本地文件并返回绝对路径。"""
        path = paths.storage_state_path(project_id, env_id)
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path)

    @classmethod
    def pack(cls, env, res: any, base_url: str) -> tuple[dict, str, dict]:
        """将脚本返回值封装为 (storage_state, token, headers)。

        :param env: 环境配置对象（读取 token_inject, token_name, token_prefix）
        :param res: get_token 脚本的返回值（str 或 dict）
        :param base_url: 环境域名根地址
        :return: (storage_state 字典, 主 token 字符串, headers 字典)
        """
        import time
        from urllib.parse import urlparse

        u = urlparse((base_url or "").rstrip("/"))
        host = u.hostname or ""
        origin = f"{u.scheme}://{u.netloc}"
        secure = u.scheme == "https"

        inject = (getattr(env, "token_inject", "") or "cookie").lower()
        token_name = getattr(env, "token_name", "") or "token"
        token_prefix = getattr(env, "token_prefix", "") or ""

        # 模式 1: 纯字符串 Token
        if isinstance(res, (str, int)):
            token = str(res).strip()
            if not token:
                raise ValueError("脚本返回的 Token 为空")
            val = f"{token_prefix}{token}"

            if inject == "header":
                header_name = token_name if token_name else "Authorization"
                return {"cookies": [], "origins": []}, token, {header_name: val}

            if inject == "localstorage":
                state = {
                    "cookies": [],
                    "origins": [
                        {
                            "origin": origin,
                            "localStorage": [{"name": token_name, "value": val}],
                        }
                    ],
                }
                return state, token, {}

            # 默认 cookie 注入
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
            return state, token, {}

        # 模式 2: 复合字典
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

            # 若既无 cookies 也无 origins，但包含了主 token，根据注入策略自动兜底补齐
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
            return state, token, headers

        raise TypeError(f"前置脚本返回值必须为 str 或 dict，实际类型为 {type(res).__name__}")

    @classmethod
    def process(cls, env, res: any, base_url: str) -> AuthResult:
        """执行标准的 Token 封装与 storageState 组装落盘。"""
        try:
            state, token, headers = cls.pack(env, res, base_url)
        except Exception as e:
            return AuthResult(False, f"处理登录态失败: {e}")

        # 若组装出了有效 cookies 或 origins，生成 storageState 供浏览器加载
        path = ""
        if state.get("cookies") or state.get("origins"):
            path = cls.dump_storage_state(env.project_id, env.id, state)

        return AuthResult(
            True,
            "获取 Token 成功，已生成浏览器登录态" if path else "获取 Token 成功",
            token=token,
            headers=headers,
            storage_state_path=path,
        )


def _sanitize_error(text: str, password: str, token: str) -> str:
    res = text or ""
    if password and len(password) >= 3:
        res = res.replace(password, "***")
    if token and len(token) >= 4:
        res = res.replace(token, "***")
    return res


_AUTH_RUNNER_CODE = '''import sys
import json
import traceback

ERROR_MARKER = "---AUTH_ERROR_START---"


def _friendly(e):
    """把异常整理成可读提示；HTTP 错误带上服务端返回的错误信息。

    被测系统常用 HTTP 500 + body.error.message 表达「账号或密码错误」，
    只抛出状态码会让用户无从判断，这里补上 body 里的提示。
    """
    try:
        import httpx
    except Exception:
        httpx = None
    if httpx is not None and isinstance(e, httpx.HTTPStatusError):
        resp = e.response
        detail = ""
        try:
            body = resp.json()
        except Exception:
            body = None
        if isinstance(body, dict):
            err = body.get("error")
            if isinstance(err, dict):
                detail = str(err.get("message") or err.get("code") or "")
            detail = detail or str(body.get("message") or "")
        if not detail:
            detail = (resp.text or "").strip()[:300]
        req = resp.request
        return "请求 %s %s 返回 HTTP %s%s" % (
            req.method,
            req.url,
            resp.status_code,
            ("：" + detail) if detail else "",
        )
    return "%s: %s" % (type(e).__name__, e)


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

    try:
        res = scope["get_token"](base_url, username, password)
    except Exception as e:
        # 保留完整堆栈供排查，同时输出一行可读原因供前端直接展示
        traceback.print_exc()
        print(ERROR_MARKER)
        print(json.dumps({"message": _friendly(e)}, ensure_ascii=False))
        sys.exit(1)

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
        # 优先用子进程给出的可读原因（含 HTTP 错误的服务端提示），
        # 堆栈只保留最后几行作为补充，避免前端只看到裸状态码
        friendly = ""
        err_marker = "---AUTH_ERROR_START---"
        if err_marker in proc.stdout:
            try:
                payload_err = json.loads(proc.stdout.split(err_marker, 1)[1].strip())
                friendly = str(payload_err.get("message") or "")
            except Exception:
                friendly = ""
        err = proc.stderr.strip() or proc.stdout.strip() or f"进程退出码: {proc.returncode}"
        lines = [l for l in err.splitlines() if l.strip()]
        brief = "\n".join(lines[-6:]) if len(lines) > 6 else err
        clean = _sanitize_error(friendly or brief, password, "")
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


def get_project_auth_script(project_id: int) -> str:
    """获取项目级统一前置获取 Token 脚本内容。若未配置，返回空字符串。"""
    if not project_id:
        return ""
    p = paths.project_auth_script_path(project_id)
    if p.exists():
        try:
            return p.read_text(encoding="utf-8")
        except OSError:
            pass
    return ""


def set_project_auth_script(project_id: int, script: str) -> None:
    """保存项目级统一前置获取 Token 脚本。"""
    if not project_id:
        return
    p = paths.project_auth_script_path(project_id)
    p.write_text(script or "", encoding="utf-8")


def prepare_auth(env, override_script: str | None = None, override_password: str | None = None) -> AuthResult:
    """生成/执行前准备登录态。

    优先级：
    1. 显式传入的 override_script；
    2. 项目级统一前置脚本（paths.project_auth_script_path(env.project_id)）；
    3. 环境自带的 auth_script（兼容历史老数据）。
    """
    script = override_script
    project_id = getattr(env, "project_id", 0) or 0
    if script is None and project_id:
        script = get_project_auth_script(project_id)
    if not script:
        script = getattr(env, "auth_script", "") or ""
    script = script.strip()

    if not script:
        username = getattr(env, "username", "") or ""
        password = override_password if override_password is not None else get_password(getattr(env, "password_ref", ""))
        if not username and not password:
            return AuthResult(True, "未配置认证信息，跳过登录态生成")
        return AuthResult(False, "该项目尚未配置前置获取 Token 脚本，请在环境管理中编写项目 get_token 脚本")

    base = (getattr(env, "base_url", "") or "").rstrip("/")
    if not base:
        return AuthResult(False, "未配置环境地址 base_url")

    username = getattr(env, "username", "") or ""
    password = override_password if override_password is not None else get_password(getattr(env, "password_ref", ""))

    ok, err_msg, res = execute_auth_script(script, base, username, password)
    if not ok:
        return AuthResult(False, err_msg)

    result = BrowserAuthPacker.process(env, res, base)
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
    # 密码留空 = 不修改，测试时沿用环境里已保存的密码（与保存接口语义一致）
    override_pwd = overrides.get("password")
    if isinstance(override_pwd, str) and not override_pwd.strip():
        override_pwd = None

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


# 兼容性别名
_handle_script_result = BrowserAuthPacker.process

