# -*- coding: utf-8 -*-
"""AI 脚本生成 / 修复链路（唯一消耗 token 的环节）。

流程：环境自检 → 登录态准备 → 拉起 playwright MCP → ReAct 工具探索
→ 模型产出 pytest 脚本 → 静态校验/编译 → 本地首跑 → 失败回灌重试（≤2 轮）
→ 通过后固化（版本 +1，旧版进 history/）。

运行固化脚本完全本地（runner.py），不 import LLM、不调视觉模型。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import py_compile
import re
import shutil
import tempfile
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

from insight_aitest.modules.ui.backend.automation import concurrency, paths
from insight_aitest.modules.ui.backend.automation.deps import get_automation_db
from insight_aitest.modules.ui.backend.automation.env_service import prepare_auth, site_url
from insight_aitest.modules.ui.backend.automation.models import (
    CaseStatus,
    ErrorCategory,
    GenerationKind,
    GenerationStatus,
)
from insight_aitest.modules.ui.backend.automation.mcp_client import MCPError, PlaywrightMCPClient
from insight_aitest.modules.ui.backend.automation.runner import EnvMissingError, run_script

logger = logging.getLogger(__name__)

MAX_TOOL_CALLS = 60
MAX_SECONDS = 12 * 60
MAX_FIX_ROUNDS = 2
# 至少完成 6 次真实浏览器操作才允许首次产出脚本，避免只凭首页快照猜步骤
MIN_EXPLORE_CALLS = 6
OBS_LIMIT = 6000

SYSTEM_PROMPT = """你是资深 Playwright 测试工程师。你的任务是通过浏览器工具真实探索被测系统，然后写出可直接运行的 Python pytest 自动化脚本。

交互协议（严格执行）：
- 每次只输出一个 JSON 对象，不要输出 Markdown 代码块、不要输出多余文字。
- 探索阶段：{"thought": "为什么做这一步", "tool": "工具名", "args": {...}}
- 完成阶段：{"thought": "脚本已就绪", "tool": "finish", "args": {"script": "完整 Python 源码"}}

脚本硬性要求：
1. 同步 API：from playwright.sync_api import expect；禁止 async/await。
2. 只定义测试函数（一个或多个 def test_xxx(page):），不要写 main、不要自己 launch 浏览器；
   page fixture 由运行脚手架提供，已注入登录态（Cookie/localStorage 或请求头）。
3. 跳转统一用公共库 open_route(page, route)，内部已读取环境变量 INSIGHT_UI_BASE_URL；
   禁止硬编码主机名/IP，也不要自己拼 BASE_URL 字符串。
4. 断言用 expect(...)，覆盖「预期结果」中的关键校验；不要只截图不校验。
5. 禁止使用 ai_assert / midscene / 视觉模型相关接口；只用标准 playwright 定位（get_by_role、
   get_by_label、get_by_text、locator），定位优先用可读的 role/label/testid。
6. 如环境已注入登录态，不要重新执行登录流程；只有页面确实跳转到登录页时才按用例做登录。
7. 代码需真实反映工具探索到的页面结构，不要编造不存在的元素。
8. 探索必须走完整用例：先用浏览器工具把每一步真实操作一遍（进入目标页面、打开弹窗、填写表单、
   点击保存、看到预期结果），确认每一步的选择器都在当前页面快照中出现过，才允许输出 finish。
   只看了首页就编写后续步骤视为不合格。
9. 选择器优先用 aria snapshot 里出现的精确 role/name，但**禁止 exact=True**：
   该后台菜单/部门树的可访问名会夹带图标字符与空白（快照里形如 menuitem " 系统管理 "），
   exact=True 永远匹配不到。请用 get_by_role("menuitem", name="系统管理")、
   get_by_text("系统管理", exact=False) 这类子串匹配。
   不要用 .first + filter 猜测父子菜单，也不要对同一 locator 追加 not_to_contain_text 断言。
10. 断言只用正向校验（to_be_visible / to_have_text / to_contain_text / to_have_value 等），
    不要用否定断言来“筛选”元素。
11. BASE_URL 就是当前端入口（后台已带 /manage），跳转只写 BASE_URL + 路由路径，
    严禁再拼 "/manage"，否则会得到 /manage/manage。
12. 用例文字里的按钮名可能与实际界面不一致，以浏览器快照中的真实 accessible name 为准
    （快照是「新增」就写「新增」，不要凭用例描述创造成「新增用户」）。
13. 浏览器工具参数必须严格按 schema：点击是 {"target": "快照里的 ref，如 e125"}（可附 "element"），
    输入是 {"target": "e125", "text": "..."}，快照是 {}。ref 只用于探索，不能写进脚本。
14. 探索时留意地址栏的 hash 路由（例如点击菜单后变成 #/usm/users）。脚本里直接用
    open_route(page, "#/usm/users") 直达目标页面，再 expect 目标页关键元素可见；
    这样比逐级点菜单稳定。
15. 按钮文案干净，必须用 exact=True 避免歧义，例如 get_by_role("button", name="新增", exact=True)；
    否则「新增」会同时命中「新增API用户」触发 strict mode violation。菜单项/树节点反过来，
    不要 exact=True（可访问名带图标字符）。
16. Playwright 的 first / last 是属性不是方法：写 btn.first.click()，不要写 btn.first()。
17. 断言的文案以浏览器里真实看到的为准：用例写「有效期为永久」，但界面该列可能显示为「--」
    （无限制即永久）。不要把用例文字硬编码进 to_have_text，改用真实界面文案或校验行存在。
18. 新增类用例的输入数据要唯一，用公共库 unique_name("testuser") 生成账号，
    避免重复创建同名数据导致提交失败。
19. 该后台弹窗（role=dialog，class ui-modal）的输入框没有 id/name/placeholder，label 也未关联 input，
    所以 get_by_label、placeholder 定位、get_by_role("textbox") 的顺序猜测都会超时。
    实测 DOM 顺序固定为：input[type=text] 第 0 个 = 用户名、第 1 个 = 显示名称（第 2 个是 PIN，第 3 个是邮箱），
    联系方式是 input[type=tel]，「使用默认密码」是 checkbox，密码框存在 disabled 项不要填。
    禁止编造 placeholder（如 "请输入用户名"），该页面不存在。
    字段顺序属于业务语义，必须写在页面对象（pages/<模块>_page.py）里；仓库 helpers 只提供
    text_inputs(container) 这类原语，不提供「按第几个字段填什么」的封装。
20. 「使用默认密码」默认勾选时密码框是 disabled，不要填密码；也不要重复点击「新增」。
21. MCP 的 ref 只在当次快照内有效：每次点击/输入后重新 browser_snapshot 取新 ref 再操作，
    不要复用上一张快照里的 ref。
22. browser_fill_form 的 fields 必须是数组（[{"target","name","type","value"}]），上传对象会报错；
    逐字段用 browser_type 更稳。
23. 断言表格内容别猜 td 序号：表格首列往往是勾选框，序号会整体偏移。优先用公共库
    assert_row_contains(page, username, "默认部门")（按整行文本断言），
    或先用 browser_evaluate 读表头 [...document.querySelectorAll('table thead th')].map(t=>t.textContent)
    核对列顺序后再写 nth 索引。
24. MCP 的 target 只接受「快照里的 ref」（如 "e346"）或标准 Playwright CSS，
    不支持 "dialog >> textbox"、"dialog >> textbox >> nth=0" 这类 role 组合写法（会报 does not match any elements）。
    填输入框前先 browser_snapshot，找到 dialog 内 textbox 的 ref 再填；同一参数连续失败两次就换思路，不要原地重复重试。
25. 必须复用公共函数库（随代码发布、签名稳定），禁止在脚本里重复实现等价逻辑：
    from insight_aitest.modules.ui.backend.automation.helpers import (
        open_route, dialog_of, text_inputs, confirm_dialog, cancel_dialog,
        row_by_text, assert_row_contains, unique_name,
        wait_visible, wait_hidden, wait_row, wait_toast,
        choose_option, upload_files, frame_of, new_tab, download_file,
        data_path, artifact_path,
    )
    - open_route(page, "#/usm/users")：直达页面并等待加载
    - dialog = dialog_of(page)：等待弹窗出现
    - text_inputs(dialog)：弹窗内文本输入框集合，业务代码里按字段顺序取值填写
    - confirm_dialog(dialog) / cancel_dialog(dialog)：点击并等待弹窗关闭
    - assert_row_contains(page, 用户名, "默认部门")：整行文本断言
    - unique_name("testuser")：唯一测试数据名
    - wait_visible(locator) / wait_hidden(locator)：显式等待元素出现/消失
    - wait_row(page, 用户名)：等待目标表格行出现
    - wait_toast(page, "添加成功")：等待提示条出现并消失
    - choose_option(page, 下拉控件, "选项文案")：下拉/combobox 选择
    - upload_files(dialog, data_path("样例.xlsx"))：上传项目测试数据
    - frame_of(page, name=...) / new_tab(page, 触发控件) / download_file(...)：iframe、新窗口、下载
    - artifact_path("x.png")：本次执行的产物路径（下载或截图落盘用）
    自己拼 BASE_URL、在页面对象之外逐个 nth 填写业务字段、自己拼时间戳造唯一名，都视为不合格。
26. 若「项目已有页面对象」一节列出可用的类/方法，优先直接 import 调用（如
    from pages.users_page import UsersPage），不要重复其流程。
27. 代码落位三档（先判断语义再写代码，不要混淆）：
    - 机制类能力（跳转、弹窗、输入框、表格行、唯一数据、等待、下拉、上传、下载、iframe、新窗口）→ 仓库 helpers（规则 25），脚本内禁止重写
    - 项目内通用但非业务、helpers 未覆盖的能力（特定轮询刷新、通用格式化）→ pages/_utils.py，
      该文件允许覆盖（系统会自动备份到 pages/history/），import 方式 from pages._utils import xxx
    - 被测系统业务操作（菜单、字段顺序、按钮文案、断言列）→ pages/<模块>_page.py，只能新增不可覆盖
    需要新增或更新上述 pages 文件时，在 finish 里附带：
    {"script": "...", "pages": [{"path": "pages/_utils.py", "content": "完整源码"}]}
    path 必须是 pages/ 下单层 .py 文件，content 需能通过 py_compile。
    页面对象会先写入生成期暂存区，首跑通过后才并入正式资产；失败自动丢弃，不会污染既有复用代码。
28. 禁止任何固定睡眠：不要写 page.wait_for_timeout / time.sleep / asyncio.sleep。
    等待一律用 helpers 的 wait_visible / wait_hidden / wait_row / wait_toast，
    或 expect(...) 自动轮询（to_be_visible / to_be_hidden / to_contain_text 等）。
29. 安全边界（违反会被静态校验直接拒绝）：
    - 只允许 import：playwright、pytest、pages.*、helpers、以及 time/json/re/tempfile/datetime/random/string/uuid/typing
    - 禁止 import os/sys/subprocess/pathlib/shutil/requests 等，禁止读取配置文件与环境凭证
    - 禁止调用 open/eval/exec/compile/getattr/setattr
    - 上传样例文件用 data_path("文件名")（项目 data/ 目录只读资产）；产物落盘用 artifact_path("文件名")
"""


def _now() -> datetime:
    return datetime.now()


def _truncate(text: str, limit: int = OBS_LIMIT) -> str:
    """超长观察保留首尾：弹窗/表单等关键内容通常出现在快照末尾。"""
    text = text or ""
    if len(text) <= limit:
        return text
    head = limit // 3
    tail = limit - head
    return text[:head] + "\n...[前面内容已截断，以下为页面末尾]...\n" + text[-tail:]


# 模型输入端有硬上限（如 qwen-max 输入 ≤30720 token），按字符预算滚动裁剪历史
MAX_PROMPT_CHARS = 20000


def _trim_messages(messages: list[dict], budget: int = MAX_PROMPT_CHARS, keep_recent: int = 8) -> list[dict]:
    """保留系统提示 + 任务说明 + 最近若干条观察，丢弃更早的探索记录。"""
    head = messages[:2]
    used = sum(len(m.get("content") or "") for m in head)
    tail: list[dict] = []
    for m in reversed(messages[2:]):
        size = len(m.get("content") or "")
        if len(tail) >= keep_recent and used + size > budget:
            break
        tail.append(m)
        used += size
    tail.reverse()
    dropped = len(messages) - 2 - len(tail)
    if dropped <= 0:
        return messages
    note = {
        "role": "user",
        "content": f"（已省略更早的 {dropped} 条探索记录；请以最新页面快照为准，需要时重新 browser_snapshot。）",
    }
    return head + [note] + tail


def _parse_json_reply(content: str) -> dict | None:
    raw = (content or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw[raw.find("\n") + 1 :] if "\n" in raw else raw
    decoder = json.JSONDecoder(strict=False)
    # raw_decode 只解析第一个完整 JSON 对象，容忍模型多写的右括号/尾随说明
    start = raw.find("{")
    while start >= 0:
        try:
            obj, _ = decoder.raw_decode(raw[start:])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
        start = raw.find("{", start + 1)
    return None


def _clean_script(text: str) -> str:
    s = (text or "").strip()
    if s.startswith("```"):
        s = s.strip("`")
        if "\n" in s:
            s = s[s.find("\n") + 1 :]
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
    return s.strip() + "\n"


def _check_script(source: str) -> str:
    """返回错误信息；空串表示通过。"""
    low = source.lower()
    if not source.strip():
        return "脚本为空"
    if "def test_" not in source:
        return "脚本缺少 def test_ 测试函数"
    if "async def" in low or "await " in low:
        return "脚本必须使用 playwright 同步 API，禁止 async/await"
    if "ai_assert" in low or "midscene" in low:
        return "生成脚本禁止使用 ai_assert/midscene 视觉断言"
    if "sync_playwright()" in low or "launch(" in low:
        return "脚本不要自行启动浏览器，直接使用 page fixture"
    if "page" not in low:
        return "脚本未使用 page fixture"
    # BASE_URL 已是当前端入口（后台已含 /manage），再拼接会造成 /manage/manage
    if re.search(r"BASE_URL[^\n]{0,16}/manage", source):
        return "BASE_URL 已包含端入口（后台为 /manage），不要再拼接 /manage"
    return _check_sandbox(source, kind="脚本")


# 允许导入的模块白名单：playwright / pytest / 公共函数库 / 项目页面对象 / 少量纯计算标准库
_ALLOWED_IMPORTS = {
    "playwright",
    "pytest",
    "pages",
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
_ALLOWED_HELPERS_PREFIX = "insight_aitest.modules.ui.backend.automation.helpers"
# 禁止调用的危险函数（防止脚本读密钥文件或绕过静态检查）
_BANNED_CALLS = {"open", "eval", "exec", "compile", "__import__", "getattr", "setattr", "execfile"}


def _check_sandbox(source: str, kind: str) -> str:
    """AST 级安全校验：import 白名单 + 危险调用 + 固定睡眠。"""
    import ast

    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return f"{kind}语法错误: {e.msg}"

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root not in _ALLOWED_IMPORTS and not alias.name.startswith(_ALLOWED_HELPERS_PREFIX):
                    return f"{kind}禁止导入 {alias.name}（仅允许 playwright/pytest/pages/helpers 与少量标准库）"
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            root = module.split(".")[0]
            if root not in _ALLOWED_IMPORTS and not module.startswith(_ALLOWED_HELPERS_PREFIX):
                return f"{kind}禁止导入 {module or '相对模块'}（仅允许 playwright/pytest/pages/helpers 与少量标准库）"
        elif isinstance(node, ast.Call):
            func = node.func
            # 只拦截直接调用（open/eval/exec...），避免误伤页面对象里同名的合法方法
            if isinstance(func, ast.Name) and func.id in _BANNED_CALLS:
                return f"{kind}禁止调用 {func.id}（脚本不得读写任意文件或动态执行代码）"
            attr = getattr(func, "attr", "")
            if attr == "wait_for_timeout" or attr == "sleep":
                return f"{kind}禁止固定睡眠（{attr}），请改用 helpers 的 wait_* 或 expect"
    return ""


def _compile(source: str) -> str:
    """py_compile 校验，返回错误信息（空串为通过）。"""
    fd, tmp = tempfile.mkstemp(suffix=".py", dir=str(paths.workspace_root()))
    os.close(fd)
    try:
        Path(tmp).write_text(source, encoding="utf-8")
        py_compile.compile(tmp, doraise=True)
        return ""
    except py_compile.PyCompileError as e:
        return f"语法错误: {e.msg}"
    except Exception as e:
        return f"编译失败: {type(e).__name__}: {e}"
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _chromium_installed() -> bool:
    home = Path.home()
    candidates = [
        home / "AppData" / "Local" / "ms-playwright",
        home / ".cache" / "ms-playwright",
        home / "Library" / "Caches" / "ms-playwright",
    ]
    return any(p.exists() and any(p.glob("chromium*")) for p in candidates)


def doctor(env) -> str:
    """环境自检，返回错误信息；空串表示通过。"""
    if env is None:
        return "项目未配置环境，请先在「环境管理」中新增"
    if not (env.base_url or "").strip():
        return "环境未配置被测系统地址 base_url"

    from insight_aitest.platform.services.kb.deps import get_llm_config

    cfg = get_llm_config()
    if not cfg.llm_api_key:
        return "未配置 LLM API Key，无法生成脚本"
    if shutil.which("npx") is None:
        return "未检测到 Node.js/npx，playwright MCP 无法启动（请安装 Node 18+）"
    if not _chromium_installed():
        return "未安装 playwright chromium 浏览器，请执行 python -m playwright install chromium"
    return ""


def _tool_catalog(client: PlaywrightMCPClient) -> str:
    """把 MCP 工具清单压缩成提示词文本。"""
    lines = []
    for tool in client.list_tools():
        name = tool.get("name", "")
        if not name.startswith("browser_"):
            continue
        desc = (tool.get("description") or "").split("\n")[0][:180]
        schema = tool.get("inputSchema") or {}
        required = schema.get("required") or []
        props = list((schema.get("properties") or {}).keys())
        hint = f" 参数: {', '.join(props)}" if props else ""
        req = f" 必填: {', '.join(required)}" if required else ""
        lines.append(f"- {name}: {desc}{hint}{req}")
    return "\n".join(lines)


def _case_brief(case) -> str:
    steps = "\n".join(f"{i}. {s}" for i, s in enumerate(case.steps or [], 1)) or "（无）"
    return (
        f"用例标题：{case.title}\n"
        f"前置条件：{case.precondition or '（无）'}\n"
        f"测试步骤：\n{steps}\n"
        f"预期结果：{case.expected or '（无）'}"
    )


PAGES_CATALOG_LIMIT = 8000
# 项目级通用扩展文件：允许生成期覆盖（覆盖前自动备份到 pages/history/）
UTILS_FILE = "_utils.py"


def _signature(node) -> str:
    """函数签名参数列表（去掉 self/cls）。"""
    args = [a.arg for a in node.args.args if a.arg not in ("self", "cls")]
    if node.args.vararg is not None:
        args.append("*" + node.args.vararg.arg)
    return ", ".join(args)


def pages_catalog(project_id: int) -> str:
    """项目已有页面对象的类/方法签名，供模型直接复用。"""
    import ast

    root = paths.pages_dir(project_id)
    lines: list[str] = []
    for file in sorted(root.glob("*.py")):
        if file.name == "__init__.py":
            continue
        try:
            tree = ast.parse(file.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        module = f"pages.{file.stem}"
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                doc = (ast.get_docstring(node) or "").split("\n")[0].strip()
                lines.append(f"- {module}.{node.name}" + (f"：{doc}" if doc else ""))
                for sub in node.body:
                    if isinstance(sub, ast.FunctionDef) and not sub.name.startswith("_"):
                        sub_doc = (ast.get_docstring(sub) or "").split("\n")[0].strip()
                        lines.append(
                            f"    · {sub.name}({_signature(sub)})" + (f"  # {sub_doc}" if sub_doc else "")
                        )
            elif isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
                doc = (ast.get_docstring(node) or "").split("\n")[0].strip()
                lines.append(
                    f"- {module}.{node.name}({_signature(node)})" + (f"  # {doc}" if doc else "")
                )
    text = "\n".join(lines)
    if len(text) <= PAGES_CATALOG_LIMIT:
        return text
    return (
        text[:PAGES_CATALOG_LIMIT]
        + "\n…（页面对象清单已截断，其余文件请按需复用：先看 pages/ 目录，再决定是否新建）"
    )


def stage_pages(project_id: int, case_id: int, payload) -> tuple[str, Path | None]:
    """校验页面对象并写入生成期暂存目录，返回 (错误信息, 暂存根目录)。

    暂存目录里是正式 pages/ 的副本 + 本次提交内容，首跑使用它，
    避免未验证的页面对象污染正式资产；通过后由 adopt_pages 并入正式目录。

    落位规则：
    - ``pages/_utils.py``（项目级通用扩展）允许覆盖，并入时备份旧版到 pages/history/；
    - 其余页面对象只允许新增，避免一次生成破坏既有复用资产。
    """
    if not isinstance(payload, list) or not payload:
        return "", None
    staging = paths.staging_root(project_id, case_id)
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)
    shutil.copytree(paths.pages_dir(project_id), staging / "pages")
    for item in payload:
        if not isinstance(item, dict):
            return "pages 必须是对象数组：[{\"path\": \"pages/x.py\", \"content\": \"...\"}]", None
        rel = str(item.get("path") or "").strip().replace("\\", "/")
        content = str(item.get("content") or "")
        if rel.count("/") != 1 or not rel.startswith("pages/") or not rel.endswith(".py"):
            return f"页面对象路径必须形如 pages/xxx.py（单层文件），收到：{rel}", None
        name = rel.split("/", 1)[1]
        if name == "__init__.py":
            return f"页面对象文件名不合法：{rel}", None
        if (paths.pages_dir(project_id) / name).exists() and name != UTILS_FILE:
            return f"页面对象 {rel} 已存在，不能覆盖；请直接复用它的方法或换新文件名", None
        problem = _compile(content)
        if not problem:
            problem = _check_sandbox(content, kind=f"页面对象 {rel} ")
        if problem:
            return f"页面对象 {rel} 校验失败：{problem}", None
        (staging / rel).write_text(content, encoding="utf-8")
    return "", staging


def adopt_pages(project_id: int, staging: Path | None) -> None:
    """首跑通过后，把暂存页面对象并入正式 pages/（_utils.py 覆盖前备份）。"""
    if staging is None:
        return
    staged = staging / "pages"
    if not staged.exists():
        return
    real = paths.pages_dir(project_id)
    for file in sorted(staged.glob("*.py")):
        name = file.name
        if name == "__init__.py":
            continue
        content = file.read_text(encoding="utf-8")
        target = real / name
        if target.exists():
            if target.read_text(encoding="utf-8") == content:
                continue
            if name != UTILS_FILE:
                # 非 _utils 文件不覆盖（生成期已校验存在性，这里兜底）
                continue
            backup = real / "history" / f"{target.stem}_{datetime.now():%Y%m%d-%H%M%S-%f}.py"
            backup.parent.mkdir(parents=True, exist_ok=True)
            backup.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
        target.write_text(content, encoding="utf-8")


def discard_pages(staging: Path | None) -> None:
    """丢弃暂存（生成失败时调用，保证资产零污染）。"""
    if staging is not None:
        shutil.rmtree(staging, ignore_errors=True)


class GenerationJob:
    """一次生成/修复任务（后台线程执行）。"""

    def __init__(self, case_id: int, kind: str) -> None:
        self.case_id = case_id
        self.kind = kind
        self.db = get_automation_db()
        self.case = self.db.get_case(case_id)
        self.env = self.db.default_env(self.case.project_id) if self.case else None
        # 任务失败时恢复到进入前的状态（修复失败仍算已实现，首次生成失败回到未实现）
        self.prev_status = self.case.status if self.case else CaseStatus.NOT_IMPLEMENTED
        self.gen_id = 0
        self.started = time.time()
        self.tool_calls = 0
        self.model_name = ""
        self._log = None
        self._staged_pages: Path | None = None

    # ===== 日志 =====

    def _write_log(self, event: dict) -> None:
        if self._log is None:
            return
        event["ts"] = _now().isoformat()
        try:
            self._log.write(json.dumps(event, ensure_ascii=False) + "\n")
            self._log.flush()
        except OSError:
            pass

    # ===== 主流程 =====

    def run(self) -> None:
        case = self.case
        if case is None:
            return
        project_id = int(case.project_id)
        is_fix = self.kind == GenerationKind.FIX
        self.db.update_case(
            self.case_id,
            status=CaseStatus.FIXING if is_fix else CaseStatus.GENERATING,
            last_error_category=None,
            last_error_message=None,
        )
        concurrency.set_progress(self.case_id, "开始", "正在准备生成环境")
        self.gen_id = self.db.create_generation(
            ui_case_id=self.case_id,
            kind=self.kind,
            attempt=1,
            status=GenerationStatus.RUNNING,
            model="",
        )
        try:
            self._log = open(paths.generation_log(self.case_id, self.gen_id), "a", encoding="utf-8")
        except OSError:
            self._log = None

        outcome = {"status": GenerationStatus.FAILED, "error_category": ErrorCategory.MODEL}
        try:
            outcome = self._execute(is_fix)
        except Exception as e:
            logger.exception("生成任务异常 case=%s", self.case_id)
            outcome = {
                "status": GenerationStatus.FAILED,
                "error_category": ErrorCategory.MODEL,
                "message": f"生成任务异常：{type(e).__name__}: {e}",
                "detail": traceback.format_exc()[-2000:],
            }
        finally:
            self._finalize(outcome)
            # 无论成功失败都清理生成期暂存，正式资产只保留已验证版本
            discard_pages(self._staged_pages)
            self._staged_pages = None
            if self._log is not None:
                try:
                    self._log.close()
                except OSError:
                    pass
            concurrency.release(project_id)

    def _execute(self, is_fix: bool) -> dict:
        case = self.case
        if not (case.steps or case.expected):
            return {
                "status": GenerationStatus.FAILED,
                "error_category": ErrorCategory.CASE,
                "message": "用例缺少测试步骤/预期结果，请补充用例信息后重试",
            }

        concurrency.set_progress(self.case_id, "自检", "检查 Node/浏览器/模型配置")
        problem = doctor(self.env)
        if problem:
            return {
                "status": GenerationStatus.FAILED,
                "error_category": ErrorCategory.ENV,
                "message": problem,
            }

        concurrency.set_progress(self.case_id, "登录态", "请求环境登录接口")
        auth = prepare_auth(self.env)
        if not auth.ok:
            return {
                "status": GenerationStatus.FAILED,
                "error_category": ErrorCategory.ENV,
                "message": f"登录态准备失败：{auth.message}",
            }

        from insight_aitest.platform.services.kb.deps import get_llm, get_llm_config

        llm = get_llm()
        self.model_name = get_llm_config().chat_model

        client = PlaywrightMCPClient(
            storage_state=auth.storage_state_path,
            output_dir=str(paths.mcp_dir()),
        )
        concurrency.set_progress(self.case_id, "启动 MCP", "拉起 playwright MCP（首次较慢）")
        try:
            client.start()
        except Exception as e:
            client.close()
            return {
                "status": GenerationStatus.FAILED,
                "error_category": ErrorCategory.ENV,
                "message": f"playwright MCP 启动失败：{type(e).__name__}: {e}",
            }

        try:
            return self._react_loop(client, llm, self.model_name, auth, is_fix)
        finally:
            client.close()

    def _react_loop(self, client, llm, model_name: str, auth, is_fix: bool) -> dict:
        case = self.case
        catalog = _tool_catalog(client)
        if not catalog:
            return {
                "status": GenerationStatus.FAILED,
                "error_category": ErrorCategory.ENV,
                "message": "playwright MCP 未提供 browser_* 工具，请检查 @playwright/mcp 安装",
            }

        header_task = (
            "修复现有脚本"
            if is_fix
            else "为下面用例从零生成脚本。先用浏览器工具打开站点、按步骤真实操作一遍，确认选择器与预期结果，再输出脚本。"
        )
        site = getattr(case, "site", "") or ""
        target_url = site_url(self.env, site)
        site_label = "后台管理端" if site == "backend" else "前台用户端"
        user_parts = [
            f"任务：{header_task}",
            f"当前端：{site_label}（入口地址必须用下面的地址，不要访问另一端的路径）",
            f"被测系统地址：{target_url}",
            f"登录态：{'已由前置登录代码注入 Cookie，前后台共用，不要重复登录' if auth.storage_state_path else '已由前置登录代码注入 Bearer 请求头，不要重复登录'}",
            "可用工具：\n" + catalog,
            "用例信息：\n" + _case_brief(case),
        ]
        catalog_pages = pages_catalog(int(case.project_id))
        if catalog_pages:
            user_parts.append(
                "项目已有页面对象（优先复用，import 路径 pages.xxx）：\n" + catalog_pages
            )
        else:
            user_parts.append(
                "项目暂无页面对象；如本用例确实需要沉淀公共流程，可按规则 27 在 finish 中提交新的 pages 文件。"
            )
        if is_fix:
            current = paths.case_script(int(case.project_id), int(case.id))
            if current.exists():
                user_parts.append("当前脚本：\n```python\n" + current.read_text(encoding="utf-8") + "\n```")
            if case.last_error_message:
                user_parts.append(
                    f"上次执行失败（{case.last_error_category or '未知'}）：\n{case.last_error_message[:4000]}"
                )
            user_parts.append("请先复现失败，再输出修复后的完整脚本。")

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "\n\n".join(user_parts)},
        ]

        rounds = 0
        bad_json = 0
        early_finish = 0
        pages_rounds = 0
        last_sig = ""
        repeat = 0
        while True:
            if time.time() - self.started > MAX_SECONDS:
                return {
                    "status": GenerationStatus.FAILED,
                    "error_category": ErrorCategory.MODEL,
                    "message": "生成超时（超过 8 分钟），已终止。可稍后重试或简化用例",
                }
            if self.tool_calls > MAX_TOOL_CALLS:
                return {
                    "status": GenerationStatus.FAILED,
                    "error_category": ErrorCategory.MODEL,
                    "message": f"工具调用次数超过 {MAX_TOOL_CALLS} 次上限，已终止",
                }

            concurrency.set_progress(self.case_id, "模型思考", f"已调用工具 {self.tool_calls} 次")
            try:
                reply = llm.chat(_trim_messages(messages), temperature=0.2)
            except Exception as e:
                return {
                    "status": GenerationStatus.FAILED,
                    "error_category": ErrorCategory.MODEL,
                    "message": f"模型调用失败：{type(e).__name__}: {e}",
                }

            parsed = _parse_json_reply(reply)
            if parsed is None:
                bad_json += 1
                self._write_log({"type": "bad_json", "content": _truncate(reply)})
                if bad_json >= 3:
                    return {
                        "status": GenerationStatus.FAILED,
                        "error_category": ErrorCategory.MODEL,
                        "message": "模型连续输出非 JSON，无法解析",
                    }
                messages.append({"role": "assistant", "content": reply})
                messages.append(
                    {
                        "role": "user",
                        "content": '输出不是合法 JSON。请只输出 JSON 对象：{"thought": "...", "tool": "...", "args": {...}}，完成时用 tool="finish"。',
                    }
                )
                continue

            thought = str(parsed.get("thought") or "")[:500]
            tool = str(parsed.get("tool") or "").strip()
            args = parsed.get("args") or {}
            if not isinstance(args, dict):
                args = {}
            self._write_log({"type": "assistant", "thought": thought, "tool": tool, "args": args})

            if tool == "finish":
                # 探索不足就产出脚本，多半是凭首页快照猜后续步骤；先要求补足真实操作
                if self.tool_calls < MIN_EXPLORE_CALLS and early_finish < 2 and not is_fix:
                    early_finish += 1
                    self._write_log(
                        {"type": "finish_too_early", "tool_calls": self.tool_calls}
                    )
                    messages.append({"role": "assistant", "content": reply})
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                f"探索不足：当前仅调用工具 {self.tool_calls} 次。"
                                "请继续用 browser_click / browser_type / browser_snapshot 等工具"
                                "把用例步骤真实操作到「预期结果」，确认每个选择器都出现过，再 finish。"
                            ),
                        }
                    )
                    continue
                source = _clean_script(str(args.get("script") or ""))
                problem = _check_script(source)
                if not problem:
                    problem = _compile(source)
                if problem:
                    rounds += 1
                    self._write_log({"type": "script_invalid", "message": problem})
                    if rounds > MAX_FIX_ROUNDS:
                        return {
                            "status": GenerationStatus.FAILED,
                            "error_category": ErrorCategory.SCRIPT,
                            "message": f"模型产出脚本不可用：{problem}",
                        }
                    messages.append({"role": "assistant", "content": reply})
                    messages.append(
                        {
                            "role": "user",
                            "content": f"脚本未通过校验：{problem}\n请修正后重新输出 finish JSON（完整脚本）。",
                        }
                    )
                    continue

                pages_problem, staged = stage_pages(
                    int(self.case.project_id), int(self.case.id), args.get("pages")
                )
                if pages_problem:
                    pages_rounds += 1
                    self._write_log({"type": "pages_invalid", "message": pages_problem})
                    if pages_rounds > MAX_FIX_ROUNDS:
                        discard_pages(staged)
                        return {
                            "status": GenerationStatus.FAILED,
                            "error_category": ErrorCategory.SCRIPT,
                            "message": f"页面对象写入失败：{pages_problem}",
                        }
                    messages.append({"role": "assistant", "content": reply})
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                f"页面对象未通过校验：{pages_problem}\n"
                                "请修正后重新输出完整 finish JSON（script + pages）。"
                            ),
                        }
                    )
                    continue
                self._staged_pages = staged
                if staged is not None:
                    self._write_log(
                        {"type": "pages_staged", "count": len(args.get("pages") or [])}
                    )

                concurrency.set_progress(self.case_id, "首跑验证", "本地执行脚本验证")
                # 首跑用暂存 pages，通过后才并入正式资产
                result = self._validate(source, auth)
                self._write_log(
                    {
                        "type": "validate",
                        "status": result.get("run_status"),
                        "category": result.get("error_category"),
                        "message": _truncate(result.get("error_message") or ""),
                    }
                )
                if result.get("run_status") == "passed":
                    adopt_pages(int(self.case.project_id), self._staged_pages)
                    self._staged_pages = None
                    return self._solidify(source, ok=True)

                rounds += 1
                if rounds > MAX_FIX_ROUNDS:
                    discard_pages(self._staged_pages)
                    self._staged_pages = None
                    self._solidify(source, ok=False)
                    return {
                        "status": GenerationStatus.FAILED,
                        "error_category": result.get("error_category") or ErrorCategory.SCRIPT,
                        "message": "脚本首跑未通过：" + (result.get("error_message") or "未知错误"),
                        "script_saved": True,
                    }
                messages.append({"role": "assistant", "content": reply})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "脚本已写入但本地首跑失败。请先用浏览器工具回到失败步骤复现并确认正确选择器，"
                            "再修复脚本并重新输出完整 finish JSON；不要原地猜测改动。\n"
                            "提示：element(s) not found 多半是可访问名带图标字符，去掉 exact=True 改用子串匹配；"
                            "get_by_label 超时说明 label 未关联 input；get_by_role(\"textbox\") 序号错位或命中 disabled 密码框时，"
                            "先用 browser_evaluate 枚举 [role=dialog] input 的 type/placeholder/disabled，再按 placeholder 等属性定位；"
                            "strict mode violation 是文案前缀撞车，按钮改用 exact=True；"
                            "形如 [Snapshot](...) 的观察说明快照已存文件，可改用不带 filename 的 browser_snapshot 直接看内容。\n"
                            f"失败分类：{result.get('error_category')}\n"
                            f"失败信息：\n{(result.get('error_message') or '')[:4000]}"
                        ),
                    }
                )
                continue

            # 工具调用
            self.tool_calls += 1
            concurrency.set_progress(
                self.case_id, "浏览器探索", f"{tool}（第 {self.tool_calls} 次）"
            )
            if tool in ("browser_snapshot", "browser_find", "browser_evaluate"):
                # 模型若把结果写文件，就看不到内容；强制返回文本
                args.pop("filename", None)
            try:
                observation, is_error = client.call_tool(tool, args)
            except MCPError as e:
                return {
                    "status": GenerationStatus.FAILED,
                    "error_category": ErrorCategory.ENV,
                    "message": f"浏览器工具调用失败：{e}",
                }
            except Exception as e:
                return {
                    "status": GenerationStatus.FAILED,
                    "error_category": ErrorCategory.ENV,
                    "message": f"浏览器工具异常：{type(e).__name__}: {e}",
                }
            # ref 过期时模型常原地反复重试：直接补一张新快照回灌，省掉一轮无效调用
            if is_error and "not found in the current page snapshot" in (observation or "").lower():
                try:
                    self.tool_calls += 1
                    snap, _ = client.call_tool("browser_snapshot", {})
                    if snap:
                        observation = (
                            f"{observation}\n\n（已自动重新获取当前页面快照，请使用下面这些新 ref）\n{snap}"
                        )
                except Exception:
                    pass
            self._write_log(
                {
                    "type": "tool",
                    "tool": tool,
                    "args": args,
                    "is_error": is_error,
                    "observation": _truncate(observation),
                }
            )
            messages.append({"role": "assistant", "content": reply})
            messages.append(
                {
                    "role": "user",
                    "content": f"Observation（工具 {tool}{'，返回错误' if is_error else ''}）：\n{_truncate(observation)}",
                }
            )
            # 同参数连续失败会快速烧掉工具预算：第二次就提示换思路，第四次直接终止
            sig = f"{tool}|{json.dumps(args, ensure_ascii=False, sort_keys=True)}"
            if is_error and sig == last_sig:
                repeat += 1
            else:
                last_sig, repeat = sig, 1 if is_error else 0
            if is_error and repeat >= 2:
                if repeat >= 4:
                    return {
                        "status": GenerationStatus.FAILED,
                        "error_category": ErrorCategory.MODEL,
                        "message": f"同一工具参数连续失败 {repeat} 次（{tool}），已终止以免继续消耗配额",
                    }
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "同一参数已连续失败，不要再重复。请先 browser_snapshot 看当前页面，"
                            "改用快照里新出现的 ref（target 只接受 ref 或标准 CSS，不支持 dialog >> textbox 这类写法）。"
                        ),
                    }
                )

    # ===== 落盘 =====

    def _validate(self, source: str, auth) -> dict:
        project_id = int(self.case.project_id)
        case_dir = paths.case_dir(project_id, int(self.case.id))
        case_dir.mkdir(parents=True, exist_ok=True)
        tmp = case_dir / "case_candidate.py"
        tmp.write_text(source, encoding="utf-8")
        try:
            return run_script(
                self.case,
                self.env,
                script_path=tmp,
                run_dir=paths.new_run_dir(project_id, int(self.case.id)) / "validate",
                auth=auth,
                pages_root=self._staged_pages,
            )
        except EnvMissingError as e:
            return {"run_status": "error", "error_category": ErrorCategory.ENV, "error_message": str(e)}
        except Exception as e:
            return {
                "run_status": "error",
                "error_category": ErrorCategory.SCRIPT,
                "error_message": f"{type(e).__name__}: {e}",
            }

    def _solidify(self, source: str, ok: bool) -> dict:
        """写入正式脚本并更新用例状态（版本自增，旧版归档）。"""
        case = self.case
        project_id = int(case.project_id)
        case_id = int(case.id)
        target = paths.case_script(project_id, case_id)
        target.parent.mkdir(parents=True, exist_ok=True)

        old_version = int(case.script_version or 0)
        if target.exists() and old_version >= 1:
            archive = paths.case_history_path(project_id, case_id, old_version)
            archive.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, archive)

        new_version = old_version + 1
        target.write_text(source, encoding="utf-8")
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        rel = paths.to_rel(target)

        fields = {
            "script_rel_path": rel,
            "script_version": new_version,
            "script_hash": digest,
            "last_generated_at": _now(),
        }
        if ok:
            fields.update(
                status=CaseStatus.IMPLEMENTED,
                last_error_category=None,
                last_error_message=None,
            )
        else:
            fields.update(status=self.prev_status or CaseStatus.NOT_IMPLEMENTED)
        self.db.update_case(case_id, **fields)
        self.case = self.db.get_case(case_id)
        if ok:
            return {"status": GenerationStatus.SUCCESS, "script_version": new_version}
        return {
            "status": GenerationStatus.FAILED,
            "error_category": ErrorCategory.SCRIPT,
            "message": "脚本已保存但未通过验证，请查看执行记录后手动修复",
        }

    def _finalize(self, outcome: dict) -> None:
        status = outcome.get("status", GenerationStatus.FAILED)
        log_rel = paths.to_rel(paths.generation_log(self.case_id, self.gen_id))
        if status == GenerationStatus.SUCCESS:
            concurrency.set_progress(self.case_id, "完成", "脚本已固化")
            self.db.finish_generation(
                self.gen_id,
                status=GenerationStatus.SUCCESS,
                tool_calls=self.tool_calls,
                model=self.model_name,
                log_rel_path=log_rel,
            )
            return

        category = outcome.get("error_category") or ErrorCategory.MODEL
        message = outcome.get("message") or "生成失败"
        fallback = self.prev_status or CaseStatus.NOT_IMPLEMENTED
        self.db.update_case(
            self.case_id,
            status=fallback,
            last_error_category=category,
            last_error_message=message[:4000],
        )
        concurrency.set_progress(self.case_id, "失败", message)
        self.db.finish_generation(
            self.gen_id,
            status=GenerationStatus.FAILED,
            error_category=category,
            error_message=message[:4000],
            tool_calls=self.tool_calls,
            model=self.model_name,
            log_rel_path=log_rel,
        )


def start_job(case_id: int, kind: str) -> None:
    """在后台线程启动生成/修复（调用方需已通过 acquire 抢到项目锁）。"""
    job = GenerationJob(case_id, kind)
    threading.Thread(target=job.run, daemon=True, name=f"ui-gen-{case_id}").start()
