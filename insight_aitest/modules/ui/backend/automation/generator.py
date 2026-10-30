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
3. 站点地址必须从环境变量读取：BASE_URL = os.environ["INSIGHT_UI_BASE_URL"].rstrip("/")，
   所有跳转都用 BASE_URL + 路径，禁止硬编码主机名/IP。
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
14. 探索时留意地址栏的 hash 路由（例如点击菜单后变成 #/usm/users）。脚本里可直接用
    page.goto(BASE_URL + "/#/usm/users") 直达目标页面，再 expect 目标页关键元素可见；
    这样比逐级点菜单稳定。首次 goto 后建议 page.wait_for_load_state() 或 expect 可见元素。
15. 按钮文案干净，必须用 exact=True 避免歧义，例如 get_by_role("button", name="新增", exact=True)；
    否则「新增」会同时命中「新增API用户」触发 strict mode violation。菜单项/树节点反过来，
    不要 exact=True（可访问名带图标字符）。
16. Playwright 的 first / last 是属性不是方法：写 btn.first.click()，不要写 btn.first()。
17. 断言的文案以浏览器里真实看到的为准：用例写「有效期为永久」，但界面该列可能显示为「--」
    （无限制即永久）。不要把用例文字硬编码进 to_have_text，改用真实界面文案或校验行存在。
18. 新增类用例的输入数据要唯一，用 import time 生成，例如
    user = f"testuser{int(time.time()) % 100000}"，避免重复创建同名数据导致提交失败。
19. 该后台弹窗（role=dialog，class ui-modal）的输入框没有 id/name/placeholder，label 也未关联 input，
    所以 get_by_label、placeholder 定位、get_by_role("textbox") 的顺序猜测都会超时。
    实测 DOM 顺序固定为：input[type=text] 第 0 个 = 用户名、第 1 个 = 显示名称（第 2 个是 PIN，第 3 个是邮箱），
    联系方式是 input[type=tel]，「使用默认密码」是 checkbox，密码框存在 disabled 项不要填。脚本写法：
    dialog = page.get_by_role("dialog")
    dialog.locator('input[type="text"]').nth(0).fill(username)
    dialog.locator('input[type="text"]').nth(1).fill(display_name)
    禁止编造 placeholder（如 "请输入用户名"），该页面不存在。提交用
    dialog.get_by_role("button", name="确定", exact=True)，提交后 expect(dialog).to_be_hidden()。
20. 「使用默认密码」默认勾选时密码框是 disabled，不要填密码；也不要重复点击「新增」。
21. MCP 的 ref 只在当次快照内有效：每次点击/输入后重新 browser_snapshot 取新 ref 再操作，
    不要复用上一张快照里的 ref。
22. browser_fill_form 的 fields 必须是数组（[{"target","name","type","value"}]），上传对象会报错；
    逐字段用 browser_type 更稳。
23. 断言表格内容别猜 td 序号：表格首列往往是勾选框，序号会整体偏移。优先断言整行文本
    （row = page.get_by_role("row").filter(has_text=username); expect(row).to_contain_text("默认部门")），
    或先用 browser_evaluate 读表头 [...document.querySelectorAll('table thead th')].map(t=>t.textContent)
    核对列顺序后再写 nth 索引。
24. MCP 的 target 只接受「快照里的 ref」（如 "e346"）或标准 Playwright CSS，
    不支持 "dialog >> textbox"、"dialog >> textbox >> nth=0" 这类 role 组合写法（会报 does not match any elements）。
    填输入框前先 browser_snapshot，找到 dialog 内 textbox 的 ref 再填；同一参数连续失败两次就换思路，不要原地重复重试。
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

                concurrency.set_progress(self.case_id, "首跑验证", "本地执行脚本验证")
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
                    return self._solidify(source, ok=True)

                rounds += 1
                if rounds > MAX_FIX_ROUNDS:
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
