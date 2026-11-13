# -*- coding: utf-8 -*-
"""本地 Agent 编写脚本的契约与静态校验（L1 / L2）。

契约以「文件集合」为单位：``case.py`` 必填，``pages/*.py``、``common/*.py`` 可选。
所有工具（MCP 与 REST）都用同一套规则，保证本地实现与平台校验一致。

校验分级：
- L1：AST 解析 + 白名单 import + 危险调用 + 硬编码主机 + 源码内 token（毫秒级）；
- L2：``pytest --collect-only``，提前暴露 import 失败 / fixture 缺失（秒级）；
- L3：``script.dry_run`` 在 staging 目录真实执行（分钟级，由 authoring_service 负责）。
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from insight_aitest.modules.ui.backend.automation import paths
from insight_aitest.modules.ui.backend.automation.env_service import site_url

CONTRACT_VERSION = "1.0"

CASE_FILE = "case.py"
ASSET_DIRS = ("pages", "common")
MAX_FILES = 20
MAX_FILE_BYTES = 512 * 1024

# 仓库根目录：L2 子进程要 import 脚手架插件与平台 env 契约
REPO_ROOT = Path(__file__).resolve().parents[5]

# 允许导入的模块白名单（与平台内生成保持同源）
ALLOWED_IMPORTS = {
    "__future__",
    "playwright",
    "pytest",
    "pages",
    "common",
    "time",
    "json",
    "re",
    "tempfile",
    "datetime",
    "random",
    "string",
    "uuid",
    "typing",
}
ALLOWED_ENV_PREFIX = "insight_aitest.modules.ui.backend.automation.env"
BANNED_CALLS = {"open", "eval", "exec", "compile", "__import__", "getattr", "setattr", "execfile"}

# 错误码 → 修复建议（原文回给本地 Agent，便于它自己闭环）
ERROR_FIX = {
    "SYNTAX": "修正语法错误后重新调用 script.validate",
    "NO_TEST_FUNC": "case.py 至少定义一个 def test_xxx(page): 测试函数",
    "ASYNC_NOT_ALLOWED": "使用 playwright 同步 API，删除 async/await",
    "FORBIDDEN_VISION": "删除 ai_assert/midscene 等视觉断言，改用 expect 断言",
    "LAUNCH_BROWSER": "不要自行 launch 浏览器，直接使用 page fixture",
    "NO_PAGE_FIXTURE": "测试函数参数必须是 page（来自运行脚手架）",
    "MANAGE_DOUBLE": "base_url() 已是当前端入口，不要再拼 /manage",
    "FORBIDDEN_CALL": "改用 Playwright/public API，不要读写任意文件或动态执行代码",
    "FIXED_SLEEP": "删除 wait_for_timeout/sleep，改用 expect 轮询或 common 里的 wait_*",
    "BAD_PATH": "只允许 case.py、pages/<name>.py、common/<name>.py（单层、.py 结尾）",
    "FILE_TOO_LARGE": "单文件不超过 512KB，拆分为资产文件",
    "TOO_MANY_FILES": "一次最多提交 20 个文件",
    "IMPORT_NOT_ALLOWED": "仅允许 playwright/pytest/pages/common/平台 env 与少量标准库",
    "IMPORT_ERROR": "补齐缺失的 pages/common 文件，或修正 import 路径",
    "FIXTURE_MISS": "只使用平台提供的 page/params fixture，不要自定义 fixture",
    "HARDCODE_HOST": "站点地址统一用 base_url()，不要硬编码主机名/IP",
    "TOKEN_IN_SOURCE": "脚本内不要写死 token/Authorization，运行时平台自动注入登录态",
    "HASH_MISMATCH": "提交的 files 与 source_hash 不一致；请用 script.validate 返回的最新 source_hash",
    "VALIDATION_REQUIRED": "先调用 script.validate（必要时再 script.dry_run），再提交",
    "STALE_CASE": "用例内容已被修改，请重新调用 case.get 获取最新 case_rev 后重新生成",
    "SCRIPT_CONFLICT": "平台脚本版本已变化，请重新调用 case.get 获取最新 script_version",
    "ASSET_CONFLICT": "资产文件内容与平台不一致；确认覆盖后传 force_assets=true，或复用现有资产",
    "BUSY": "同一用例同时只允许一个本地 Agent 操作，请稍后重试",
    "CASE_NOT_FOUND": "检查 case_id 是否属于当前项目",
    "ENV_NOT_CONFIGURED": "请在平台「环境管理」中新增并测试通过环境",
    "ENV_NOT_ALLOWED": "该环境已关闭「允许本地 Agent 获取认证信息」，请在环境管理中开启",
    "ENV_INVALID": "环境登录态获取失败，请先在平台环境管理中测试通过",
    "PERMISSION_DENIED": "Token 无效或已过期，请重新生成文案获取新 Token",
    "TIMEOUT": "试跑超时，检查等待策略（expect 轮询）并缩短流程",
    "SELECTOR_NOT_FOUND": "定位器未命中，回到浏览器确认真实 accessible name / role",
    "SCRIPT_ERROR": "查看 log_tail 与失败截图，修正断言/定位后重新 dry_run",
}

_IMPORT_FROM_ASSET = re.compile(r"^(?:from\s+(pages|common)\.([A-Za-z0-9_]+)\s+import|import\s+(pages|common)\.([A-Za-z0-9_]+))", re.M)


def violation(code: str, message: str, file: str = CASE_FILE, line: int | None = None) -> dict:
    return {
        "code": code,
        "message": message,
        "file": file,
        "line": line,
        "fix": ERROR_FIX.get(code, ""),
    }


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def case_rev(case) -> str:
    """用例可编辑内容的版本指纹（标题/前置/步骤/预期/端），用于 STALE_CASE 守卫。"""
    payload = {
        "title": getattr(case, "title", "") or "",
        "precondition": getattr(case, "precondition", "") or "",
        "steps": list(getattr(case, "steps", None) or []),
        "expected": getattr(case, "expected", "") or "",
        "site": getattr(case, "site", "") or "",
    }
    return _sha(json.dumps(payload, ensure_ascii=False, sort_keys=True))[:16]


def source_hash(files: dict[str, str]) -> str:
    """文件集合的稳定哈希（按路径排序后拼接，与提交顺序无关）。"""
    h = hashlib.sha256()
    for path in sorted(files):
        h.update(path.encode("utf-8"))
        h.update(b"\0")
        h.update(files[path].encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()


def normalize_files(files) -> tuple[dict[str, str], list[dict]]:
    """校验文件路径/体积并返回 {path: content}；不合规文件不参与后续校验。"""
    if not isinstance(files, list) or not files:
        return {}, [violation("BAD_PATH", "files 必须是非空数组：[{path, content}]")]
    if len(files) > MAX_FILES:
        return {}, [violation("TOO_MANY_FILES", f"提交了 {len(files)} 个文件，上限 {MAX_FILES}")]

    out: dict[str, str] = {}
    problems: list[dict] = []
    for item in files:
        if not isinstance(item, dict):
            problems.append(violation("BAD_PATH", "files 元素必须是 {path, content} 对象"))
            continue
        raw = str(item.get("path") or "").strip().replace("\\", "/")
        content = item.get("content")
        if not isinstance(content, str):
            problems.append(violation("BAD_PATH", f"{raw or '(空路径)'} 的 content 必须是字符串", raw))
            continue
        if raw.startswith("/") or ".." in raw.split("/"):
            problems.append(violation("BAD_PATH", f"非法路径：{raw}", raw))
            continue
        parts = raw.split("/")
        ok = (len(parts) == 1 and parts[0] == CASE_FILE) or (
            len(parts) == 2
            and parts[0] in ASSET_DIRS
            and parts[1].endswith(".py")
            and parts[1] not in ("__init__.py", "")
        )
        if not ok:
            problems.append(violation("BAD_PATH", f"非法路径：{raw}", raw))
            continue
        if raw in out:
            problems.append(violation("BAD_PATH", f"路径重复：{raw}", raw))
            continue
        if len(content.encode("utf-8")) > MAX_FILE_BYTES:
            problems.append(violation("FILE_TOO_LARGE", f"{raw} 超过 512KB", raw))
            continue
        out[raw] = content
    return out, problems


def _lint_case(case_source: str) -> list[dict]:
    low = case_source.lower()
    out: list[dict] = []
    if not case_source.strip():
        return [violation("SYNTAX", "case.py 内容为空")]
    if "def test_" not in case_source:
        out.append(violation("NO_TEST_FUNC", "缺少 def test_ 测试函数"))
    if "async def" in low or "await " in low:
        out.append(violation("ASYNC_NOT_ALLOWED", "使用了 async/await"))
    if "ai_assert" in low or "midscene" in low:
        out.append(violation("FORBIDDEN_VISION", "使用了 ai_assert/midscene"))
    if "sync_playwright()" in low or "launch(" in low:
        out.append(violation("LAUNCH_BROWSER", "脚本自行启动了浏览器"))
    if "page" not in low:
        out.append(violation("NO_PAGE_FIXTURE", "未使用 page fixture"))
    if re.search(r"(base_url\(\)|BASE_URL)[^\n]{0,24}/manage", case_source):
        out.append(violation("MANAGE_DOUBLE", "base_url() 后又拼接了 /manage"))
    for m in re.finditer(r"https?://[^\s\"'`)]+", case_source):
        url = m.group(0)
        if re.match(r"https?://(localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\])", url):
            continue
        if "{" in url or "$" in url:
            continue
        out.append(violation("HARDCODE_HOST", f"硬编码主机地址：{url}", CASE_FILE, case_source[: m.start()].count("\n") + 1))
    if re.search(r"Bearer\s+[A-Za-z0-9._\-]{16,}", case_source) or re.search(
        r"token\s*=\s*['\"][A-Za-z0-9._\-]{24,}['\"]", case_source, re.I
    ):
        out.append(violation("TOKEN_IN_SOURCE", "源码中出现疑似真实 token"))
    return out


def _lint_ast(source: str, name: str) -> list[dict]:
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return [violation("SYNTAX", f"语法错误：{e.msg}", name, e.lineno)]
    out: list[dict] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root not in ALLOWED_IMPORTS and not alias.name.startswith(ALLOWED_ENV_PREFIX):
                    out.append(violation("IMPORT_NOT_ALLOWED", f"禁止导入 {alias.name}", name, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            root = module.split(".")[0]
            if root not in ALLOWED_IMPORTS and not module.startswith(ALLOWED_ENV_PREFIX):
                out.append(violation("IMPORT_NOT_ALLOWED", f"禁止导入 {module or '相对模块'}", name, node.lineno))
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in BANNED_CALLS:
                out.append(violation("FORBIDDEN_CALL", f"禁止调用 {func.id}", name, node.lineno))
            attr = getattr(func, "attr", "")
            if attr in ("wait_for_timeout", "sleep"):
                out.append(violation("FIXED_SLEEP", f"禁止固定睡眠（{attr}）", name, node.lineno))
    return out


def _missing_assets(files: dict[str, str], project_id: int, case_source: str) -> list[dict]:
    """L1 快速检查 pages/common 引用是否存在（提交文件或项目现有资产）。"""
    out: list[dict] = []
    for m in _IMPORT_FROM_ASSET.finditer(case_source):
        package = m.group(1) or m.group(3)
        stem = m.group(2) or m.group(4)
        rel = f"{package}/{stem}.py"
        if rel in files:
            continue
        root = paths.project_scripts_dir(project_id) / package
        if not (root / f"{stem}.py").exists():
            out.append(
                violation("IMPORT_ERROR", f"引用了不存在的资产 {rel}", CASE_FILE)
            )
    return out


def lint_files(files: dict[str, str], project_id: int) -> list[dict]:
    """L1：纯静态检查（不执行任何用户代码）。"""
    problems: list[dict] = []
    case_source = files.get(CASE_FILE, "")
    if not case_source:
        problems.append(violation("BAD_PATH", "缺少 case.py"))
    else:
        problems.extend(_lint_case(case_source))
    for name, source in files.items():
        if name == CASE_FILE:
            problems.extend(_lint_ast(source, name))
        else:
            problems.extend(_lint_ast(source, name))
    problems.extend(_missing_assets(files, project_id, case_source))
    return problems


def collect_only(files: dict[str, str], project_id: int, timeout: int = 90) -> dict | None:
    """L2：写入临时目录后 ``pytest --collect-only``；通过返回 None，否则返回违规项。"""
    tmp = Path(tempfile.mkdtemp(prefix="ui-agent-"))
    try:
        for rel, content in files.items():
            target = tmp / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(
            p
            for p in (
                str(tmp),
                str(paths.project_scripts_dir(project_id)),
                str(REPO_ROOT),
                env.get("PYTHONPATH") or "",
            )
            if p
        )
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "--collect-only",
                "-q",
                "-p",
                "no:cacheprovider",
                str(tmp / CASE_FILE),
            ],
            cwd=str(tmp),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        if proc.returncode == 0:
            return None
        output = (proc.stdout or "") + "\n" + (proc.stderr or "")
        code = "FIXTURE_MISS" if "fixture" in output.lower() and "not found" in output.lower() else "IMPORT_ERROR"
        tail = output.strip()[-3000:]
        return violation(code, f"pytest 收集用例失败：{tail}")
    except subprocess.TimeoutExpired:
        return violation("TIMEOUT", "pytest --collect-only 超时")
    finally:
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)


def validate_source(files: dict[str, str], project_id: int, run_l2: bool = True) -> dict:
    """L1 + L2 校验，返回统一结构。"""
    digest = source_hash(files)
    problems = lint_files(files, project_id)
    stage = "L1"
    if not problems and run_l2:
        stage = "L2"
        l2 = collect_only(files, project_id)
        if l2:
            problems = [l2]
    return {
        "ok": not problems,
        "stage": stage,
        "violations": problems,
        "source_hash": digest,
        "file_count": len(files),
        "files": sorted(files),
    }


def asset_catalog(project_id: int) -> list[dict]:
    """项目现有 pages/common 资产清单（供本地 Agent 复用，避免重复造轮子）。"""
    out: list[dict] = []
    for package in ASSET_DIRS:
        root = paths.pages_dir(project_id) if package == "pages" else paths.common_dir(project_id)
        for file in sorted(root.glob("*.py")):
            if file.name == "__init__.py":
                continue
            try:
                text = file.read_text(encoding="utf-8")
            except OSError:
                continue
            out.append(
                {
                    "path": f"{package}/{file.name}",
                    "sha256": _sha(text),
                    "size": len(text.encode("utf-8")),
                    "content": text,
                }
            )
    return out


def contract_rules() -> dict:
    """回给本地 Agent 的硬约束（与校验器同源，改规则只需改这里）。"""
    return {
        "contract_version": CONTRACT_VERSION,
        "files": {
            "required": [CASE_FILE],
            "optional": ["pages/<name>.py", "common/<name>.py"],
            "max_files": MAX_FILES,
            "max_file_bytes": MAX_FILE_BYTES,
            "note": "只提交相对路径；pages/common 只能单层 .py；不要提交 __init__.py",
        },
        "case": {
            "must_use": "def test_xxx(page):",
            "base_url": "from insight_aitest.modules.ui.backend.automation.env import base_url, data_path, artifact_path",
            "sync_only": True,
            "forbidden": ["async/await", "ai_assert", "midscene", "sync_playwright()", "launch(", "os.environ", "wait_for_timeout", "sleep"],
        },
        "imports": {
            "allowed_roots": sorted(ALLOWED_IMPORTS) + [ALLOWED_ENV_PREFIX],
            "asset_import_style": "from pages.users_page import UsersPage / from common.ui import dialog_of",
        },
        "flow": ["example.get", "script.validate", "script.dry_run", "script.submit"],
        "error_codes": ERROR_FIX,
    }


def current_script_source(case) -> str:
    """已有脚本源码（供本地 Agent 参考/增量修改）；无脚本或读取失败返回空串。"""
    rel = (getattr(case, "script_rel_path", "") or "").strip()
    if not rel:
        return ""
    try:
        p = paths.resolve_rel(rel)
        if not p.is_file():
            return ""
        text = p.read_text(encoding="utf-8")
        return text[:200_000]
    except OSError:
        return ""


def contract_payload(case, env) -> dict:
    """单用例的完整契约快照（contract.get 的返回体）。"""
    project_id = int(case.project_id)
    script = {
        "path": getattr(case, "script_rel_path", "") or "",
        "version": int(getattr(case, "script_version", 0) or 0),
        "hash": getattr(case, "script_hash", "") or "",
        "exists": bool(getattr(case, "script_rel_path", "")),
        "content": current_script_source(case),
    }
    payload = {
        "contract_version": CONTRACT_VERSION,
        "generated_at": datetime.now().isoformat(),
        "case": {
            "case_id": int(case.id),
            "project_id": project_id,
            "title": case.title,
            "precondition": case.precondition or "",
            "steps": list(case.steps or []),
            "expected": case.expected or "",
            "site": case.site,
            "case_rev": case_rev(case),
            "params_schema": list(getattr(case, "params_schema_json", None) or []),
        },
        "script": script,
        "env": _env_summary(env, case) if env is not None else None,
        "assets": asset_catalog(project_id),
        "rules": contract_rules(),
    }
    return payload


def _env_summary(env, case) -> dict:
    return {
        "env_id": int(env.id),
        "name": env.name or "",
        "base_url": env.base_url or "",
        "entry_url": site_url(env, getattr(case, "site", "") or ""),
        "auth_mode": getattr(env, "token_inject", "cookie") or "cookie",
        "allow_local_agent": bool(getattr(env, "allow_local_agent", 1)),
    }


# ===== 本地 Agent 范例库（example.get）=====

# 只保留「违反后必被 lint / 首跑拒绝」的硬约束，细节规则仍在 contract.get
HARD_RULES = [
    "只定义同步测试函数：def test_xxx(page) 或 def test_xxx(page, params)；禁止 async/await",
    "禁止 ai_assert / midscene 视觉断言，禁止 sync_playwright() / launch() 自建浏览器",
    "禁止 page.wait_for_timeout / time.sleep；等待一律用 expect(...) 轮询，条件满足即继续",
    "禁止 os.environ、禁止在源码里写 token/密码；认证信息由平台通过环境注入",
    "禁止硬编码主机名或 IP：页面地址一律 base_url() + 路由",
    "只允许 case.py、pages/<name>.py、common/<name>.py；import 必须命中白名单",
    "禁止 manage_browser_sync()/manageBrowser 等双开浏览器调用，page 由平台注入",
    "引用的 pages/common 资产必须同时出现在 files 里，否则首跑必失败",
]

# 平台已验证的通用坑（项目实测 lesson 优先于这里；二者冲突以实际快照为准）
KNOWN_TRAPS = [
    {
        "id": "modal-input-no-id",
        "site": "backend",
        "trap": "ui-modal 弹窗内 input 没有 id/name/placeholder，get_by_label 会超时",
        "workaround": "dialog.get_by_role('textbox').nth(i) 按 DOM 顺序定位，或 get_by_placeholder 兜底",
    },
    {
        "id": "checkbox-zero-size",
        "site": "backend",
        "trap": "复选框 input 实际尺寸 0×0，直接 check() 必超时",
        "workaround": "点它外层的 label 包裹元素，不要直接点 input",
    },
    {
        "id": "error-tip-class",
        "site": "backend",
        "trap": "错误提示不是 role=alert，而是 div.ui-form-error-tip",
        "workaround": "expect(page.locator('.ui-form-error-tip')).to_contain_text('...')",
    },
    {
        "id": "menu-name-with-icon",
        "site": "backend",
        "trap": "侧边菜单 menuitem 的文本含图标空白，exact=True 永远匹配不到",
        "workaround": "菜单/树节点用非 exact 匹配；按钮才用 exact=True 避免命中更长的同名按钮",
    },
    {
        "id": "button-exact",
        "site": "any",
        "trap": "「新增」会命中「新增API用户」等更长的按钮，导致点错",
        "workaround": "按钮统一 get_by_role('button', name='新增', exact=True)",
    },
    {
        "id": "modal-escape-loses-data",
        "site": "backend",
        "trap": "弹窗内按 Esc 会直接关闭并丢弃已填内容，断言失败后无法继续",
        "workaround": "关闭弹窗只点「取消」按钮，不要用 keyboard.press('Escape')",
    },
    {
        "id": "hash-route",
        "site": "backend",
        "trap": "后台是 hash 路由，用 base_url() + '/users' 会 404",
        "workaround": "用 base_url() + '/#/usm/users' 这类完整 hash 路由直达",
    },
    {
        "id": "disabled-password",
        "site": "backend",
        "trap": "勾选「使用默认密码」后密码框被禁用，继续 fill() 会超时",
        "workaround": "先判断 is_disabled()，或直接不填密码，走默认密码分支",
    },
    {
        "id": "wait-after-submit",
        "site": "any",
        "trap": "提交后立刻断言列表，接口还没返回，必然偶发失败",
        "workaround": "用 expect(locator).to_contain_text(...) 轮询目标行出现，不要固定 sleep",
    },
]

_REDACT_PATTERNS = (
    (re.compile(r"ins_agent_[A-Za-z0-9_\-]+"), "ins_agent_***"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]+"), "Bearer ***"),
    (re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"), "***@***"),
    (re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "1**********"),
    (re.compile(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?(?!\d)"), "***.***.***.***"),
    (re.compile(r"(?i)\b(password|passwd|pwd)\s*=\s*[\"'][^\"']*[\"']"), r'\1="***"'),
    (re.compile(r"(?i)\badmin/[^\s\"']+"), "admin/***"),
)


def redact(text: str) -> str:
    """范例输出前脱敏：凭证、邮箱、手机号、IP、admin 口令。"""
    out = text or ""
    for pattern, repl in _REDACT_PATTERNS:
        out = pattern.sub(repl, out)
    return out


def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    try:
        return f"({ast.unparse(node.args)})"
    except Exception:  # noqa: BLE001 - 签名渲染失败不应影响范例输出
        return "(...)"


def asset_index(project_id: int) -> list[dict]:
    """pages/common 的签名索引（只给类名/方法签名/docstring 首行，不给实现）。"""
    out: list[dict] = []
    for package in ASSET_DIRS:
        root = paths.pages_dir(project_id) if package == "pages" else paths.common_dir(project_id)
        for file in sorted(root.glob("*.py")):
            if file.name == "__init__.py":
                continue
            try:
                tree = ast.parse(file.read_text(encoding="utf-8"))
            except (OSError, SyntaxError):
                continue
            classes: list[dict] = []
            functions: list[dict] = []
            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    methods = [
                        {
                            "name": child.name,
                            "sig": _signature(child),
                            "doc": (ast.get_docstring(child) or "").splitlines()[0][:120]
                            if ast.get_docstring(child)
                            else "",
                        }
                        for child in node.body
                        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and not child.name.startswith("_")
                    ][:10]
                    classes.append({"name": node.name, "methods": methods})
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.name.startswith("_"):
                        continue
                    doc = ast.get_docstring(node) or ""
                    functions.append(
                        {
                            "name": node.name,
                            "sig": _signature(node),
                            "doc": doc.splitlines()[0][:120] if doc else "",
                        }
                    )
            if classes or functions:
                out.append(
                    {"path": f"{package}/{file.name}", "classes": classes, "functions": functions[:10]}
                )
    return out
