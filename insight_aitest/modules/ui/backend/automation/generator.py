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
from types import SimpleNamespace

from insight_aitest.modules.ui.backend.automation import concurrency, corpus, lessons, paths
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

# 模型自己发起的探索调用上限：到量即强制 finish，避免无限确认烧 token
MAX_MODEL_CALLS = 30
# 含自动补快照/控件枚举/页面事实预取的绝对上限，防自动重试失控
MAX_TOOL_CALLS = 40
MAX_SECONDS = 20 * 60
# 首跑验证失败预算：每轮都在上一轮失败基础上迭代，给足修复机会
MAX_FIX_ROUNDS = 5
# 静态校验/补丁应用/资产写入失败单独计数，避免这类小错吃掉首跑验证的修复额度
MAX_STATIC_ROUNDS = 3
# 至少完成 6 次真实浏览器操作才允许首次产出脚本，避免只凭首页快照猜步骤
MIN_EXPLORE_CALLS = 6
OBS_LIMIT = 6000
# 页面快照给模型的预算比普通观察大：截断会把「新增」等关键按钮切掉，模型就会开始猜 ref
SNAP_LIMIT = 12000
REF_RE = re.compile(r"\[ref=(e\d+)\]")

# 会改变页面状态的工具：只有它们重复执行且页面无变化才值得判定为空转。
# snapshot/find/evaluate 是只读观察，重复取值属正常（MCP 大快照还会返回同样的文件链接文本）。
MUTATING_TOOLS = (
    "browser_navigate",
    "browser_click",
    "browser_type",
    "browser_hover",
    "browser_select_option",
    "browser_press_key",
)

# 与用例探索无关、甚至会让会话不可继续的 MCP 工具：不暴露给模型，也不允许调用
BLOCKED_TOOLS = {
    "browser_close",
    "browser_kill",
    "browser_emulate_media",
    "browser_resize",
    "browser_install",
    "browser_run_code",
}

# 弹窗出现时用 browser_evaluate 自动枚举可编辑控件：模型不需要自己摸索字段，
# 参数是否完整由系统按实测清单校验（不依赖模型自觉）。
CONTROL_INVENTORY_JS = """() => {
  const root = document.querySelector('[role=dialog]');
  if (!root) return { sig: '', items: [] };
  const shown = (el) => {
    const style = el.ownerDocument.defaultView.getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden') return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const labelOf = (el) => {
    // 取最近的一层 label：外层 label 常把「字段名 + 勾选项文案」拼在一起
    const near = el.closest('label');
    if (near) {
      const text = (near.textContent || '').trim();
      if (text) return text.slice(0, 40);
    }
    if (el.labels && el.labels.length) {
      const text = (el.labels[0].textContent || '').trim();
      if (text) return text.slice(0, 40);
    }
    const aria = el.getAttribute('aria-label');
    if (aria && aria.trim()) return aria.trim().slice(0, 40);
    let node = el;
    for (let i = 0; i < 3 && node && node !== root; i++) {
      node = node.parentElement;
      if (!node) break;
      const prev = node.previousElementSibling;
      if (prev && (prev.textContent || '').trim()) return prev.textContent.trim().slice(0, 40);
    }
    return (el.placeholder || el.getAttribute('name') || el.id || '').trim();
  };
  const items = [];
  // 按 DOM 顺序枚举，保证清单顺序与表单项顺序一致
  root.querySelectorAll('input, select, textarea, [role=combobox]').forEach((el) => {
    const isCombo = el.getAttribute('role') === 'combobox' && el.tagName !== 'SELECT';
    if (isCombo && el.querySelector('input, select')) return; // 复合控件只报外层
    const type = (el.tagName === 'SELECT' || isCombo) ? 'select' : (el.type || 'text');
    if (['button', 'submit', 'reset', 'file', 'hidden'].includes(type)) return;
    const tickable = type === 'checkbox' || type === 'radio';
    // 勾选框的 input 常被样式隐藏，不能用尺寸过滤；禁用输入（如受勾选开关控制的密码框）跳过
    if (!tickable && (el.disabled || !shown(el))) return;
    let value = '';
    let options = [];
    if (isCombo) {
      const v = el.querySelector('.ui-select-value, [class*=value]');
      value = v ? (v.textContent || '').trim() : '';
      const panel = el.querySelector('.ui-select-panel, [role=listbox]');
      if (panel) {
        options = Array.from(panel.querySelectorAll('[role=option], li'))
          .map((o) => (o.textContent || '').trim())
          .filter(Boolean);
      }
    } else if (type === 'select') {
      value = (el.value || '').trim();
      options = Array.from(el.options).map((o) => (o.textContent || '').trim()).filter(Boolean);
    } else if (type !== 'checkbox' && type !== 'radio') {
      value = el.value === undefined ? '' : el.value;
    }
    const label = labelOf(el);
    // 必填判定：原生 required / aria-required / label 里的红色星号
    const required = !!(el.required || el.getAttribute('aria-required') === 'true'
      || label.includes('*') || label.includes('＊'));
    const item = { label, type, value, options, disabled: !!el.disabled, required };
    if (tickable) item.checked = !!el.checked;
    items.push(item);
  });
  return { sig: (root.textContent || '').trim().slice(0, 60), items };
}"""

# 确定性预取：直连页面读表格表头/菜单项/字段/按钮文案，零模型 token。
# 这些正是模型最容易瞎猜的部分（用例文案与真实按钮名经常不一致）。
PAGE_FACTS_JS = """() => {
  const clean = (s) => (s || '').replace(/\\s+/g, ' ').trim();
  const cut = (s) => clean(s).slice(0, 40);
  const labelOf = (el) => {
    const near = el.closest('label');
    if (near) {
      const text = cut(near.textContent);
      if (text) return text;
    }
    const aria = el.getAttribute('aria-label');
    if (aria && aria.trim()) return cut(aria);
    return cut(el.getAttribute('placeholder') || el.getAttribute('name') || el.id || '');
  };
  const root = document.querySelector('[role=dialog]');
  const scope = root || document.body;
  const fields = [];
  scope.querySelectorAll('input, textarea, select, [role=combobox]').forEach((el) => {
    const type = (el.tagName === 'SELECT' || el.getAttribute('role') === 'combobox') ? 'select' : (el.type || 'text');
    if (['button', 'submit', 'reset', 'file', 'hidden'].includes(type)) return;
    const label = labelOf(el);
    if (label) fields.push(label);
  });
  const buttons = [];
  document.querySelectorAll('button, [role=button], input[type=submit]').forEach((el) => {
    const text = cut(el.textContent) || cut(el.value);
    if (text) buttons.push(text);
  });
  return {
    url: (location.href || '').slice(0, 160),
    menus: Array.from(document.querySelectorAll('[role=menuitem], .ui-menu-item, nav a')).map((el) => cut(el.textContent)).filter(Boolean).slice(0, 20),
    headers: Array.from(document.querySelectorAll('table thead th')).map((el) => cut(el.textContent)).filter(Boolean).slice(0, 20),
    buttons: buttons.slice(0, 20),
    fields: fields.slice(0, 20),
  };
}"""

SYSTEM_PROMPT = """你是资深 Playwright 测试工程师。你的任务是通过浏览器工具真实探索被测系统，然后写出可直接运行的 Python pytest 自动化脚本。

交互协议（严格执行）：
- 每次只输出一个 JSON 对象，不要输出 Markdown 代码块、不要输出多余文字。
- 探索阶段：{"thought": "查看当前页面结构", "tool": "browser_snapshot", "args": {}}
  （tool 必须是下面「可用工具」清单里的真实工具名；不要把示例文字原样抄回来）
- 完成阶段（两阶段输出，避免单次 JSON 被截断）：
  1) 需要新增/更新资产时，先只提交资产：{"thought": "先落地资产", "tool": "finish", "args": {"pages": [...]}}
  2) 收到「资产已接受」后，只提交脚本：{"thought": "脚本已就绪", "tool": "finish", "args": {"script": "完整 Python 源码"}}
  脚本不引用新资产时，可一步提交 {"script": "...", "pages": [...]}。
- 修复阶段（首跑失败后）：优先输出最小补丁
  {"thought": "按报错改这一处", "tool": "finish", "args": {"patch": [{"find": "脚本中唯一出现的原文", "replace": "替换后的代码"}]}}
  find 必须在脚本里唯一命中；补丁无法表达改动时才输出完整 script。

脚本硬性要求：
1. 同步 API：from playwright.sync_api import expect；禁止 async/await。
2. 只定义测试函数（一个或多个 def test_xxx(page):），不要写 main、不要自己 launch 浏览器；
   page fixture 由运行脚手架提供，已注入登录态（Cookie/localStorage 或请求头）。
3. 站点地址从环境契约读取：from insight_aitest.modules.ui.backend.automation.env import base_url，
   跳转写 page.goto(base_url() + "/#/usm/users")；禁止硬编码主机名/IP，也不要 import os 读环境变量。
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
11. base_url() 就是当前端入口（后台已带 /manage），跳转只写 base_url() + 路由路径，
    严禁再拼 "/manage"，否则会得到 /manage/manage。
12. 用例文字里的按钮名可能与实际界面不一致，以浏览器快照中的真实 accessible name 为准
    （快照是「新增」就写「新增」，不要凭用例描述创造成「新增用户」）。
13. 浏览器工具参数必须严格按 schema：点击是 {"target": "快照里的 ref，如 e125"}，输入是 {"target": "e125", "text": "..."}。
    探索阶段 target 只能是快照里的 ref 或标准 CSS；严禁把 page.get_by_role/get_by_text 等 Playwright 表达式
    或中文描述塞进 target/element（MCP 会当 CSS 解析直接报错）。表达式只允许出现在最终脚本里。
14. 探索时留意地址栏的 hash 路由（例如点击菜单后变成 #/usm/users）。脚本里直接用
    page.goto(base_url() + "/#/usm/users") 直达目标页面，再 expect 目标页关键元素可见；
    这样比逐级点菜单稳定。
15. 按钮文案干净，必须用 exact=True 避免歧义，例如 get_by_role("button", name="新增", exact=True)；
    否则「新增」会同时命中「新增API用户」触发 strict mode violation。菜单项/树节点反过来，
    不要 exact=True（可访问名带图标字符）。
16. Playwright 的 first / last 是属性不是方法：写 btn.first.click()，不要写 btn.first()。
17. 断言的文案以浏览器里真实看到的为准：用例写「有效期为永久」，但界面该列可能显示为「--」
    （无限制即永久）。不要把用例文字硬编码进 to_have_text，改用真实界面文案或校验行存在。
18. 新增类用例的输入数据必须唯一：优先调用项目已有 common 里的 unique_name(prefix)，
    没有时用 import time 拼时间戳，禁止写死固定账号，否则重复创建会提交失败。
    需要唯一值且用户名有格式限制（只允许字母/数字/中文）时，用字母前缀 + 时间戳，不要带下划线。
    探索阶段取时间戳用 browser_evaluate 的 expression: "Date.now()"（只写单个表达式，
    不要写 const/var/语句，否则报 SyntaxError）。
19. 该后台弹窗（role=dialog，class ui-modal）的输入框没有 id/name/placeholder，label 也未关联 input，
    所以 get_by_label、placeholder 定位、get_by_role("textbox") 的顺序猜测都会超时。
    实测 DOM 顺序固定为：input[type=text] 第 0 个 = 用户名、第 1 个 = 显示名称（第 2 个是 PIN，第 3 个是邮箱），
    联系方式是 input[type=tel]，「使用默认密码」是 checkbox，密码框存在 disabled 项不要填。
    禁止编造 placeholder（如 "请输入用户名"），该页面不存在。
    字段顺序属于业务语义，必须写在页面对象（pages/<模块>_page.py）里；仓库只提供 env 契约，
    不含任何这类原语，可复用的弹窗/输入框定位逻辑应沉淀到 common/。
20. 「使用默认密码」默认勾选时密码框是 disabled，不要填密码；也不要重复点击「新增」。
    该复选框的真实 input 尺寸为 0×0（视觉由兄弟 span 绘制），check()/uncheck() 必定超时；
    切换勾选状态只能点外层包裹 label：
    dialog.locator("label.ui-checkbox-wrap").filter(has_text="使用默认密码").click()
21. MCP 的 ref 只在当次快照内有效：每次点击/输入后重新 browser_snapshot 取新 ref 再操作，
    不要复用上一张快照里的 ref。弹窗内严禁按 Escape（实测会把整个弹窗关掉、已填数据丢失），
    要收起下拉就再次点击同一个 combobox，要看当前状态用 browser_snapshot。
22. browser_fill_form 的 fields 必须是数组（[{"target","name","type","value"}]），上传对象会报错；
    逐字段用 browser_type 更稳。
23. 断言表格内容别猜 td 序号：表格首列往往是勾选框，序号会整体偏移。优先断言整行文本
    （row = page.get_by_role("row").filter(has_text=username); expect(row).to_contain_text("默认部门")），
    或先用 browser_evaluate 读表头 [...document.querySelectorAll('table thead th')].map(t=>t.textContent)
    核对列顺序后再写 nth 索引。
24. MCP 的 target 只接受「快照里的 ref」（如 "e346"）或标准 Playwright CSS，
    不支持 "dialog >> textbox"、"dialog >> textbox >> nth=0" 这类 role 组合写法（会报 does not match any elements）。
    填输入框前先 browser_snapshot，找到 dialog 内 textbox 的 ref 再填；同一参数连续失败两次就换思路，不要原地重复重试。
25. 仓库只提供环境契约（无任何 UI 结构假设），脚本里用它取地址与路径：
    from insight_aitest.modules.ui.backend.automation.env import base_url, data_path, artifact_path
    - base_url()：当前端入口（后台已含 /manage）
    - data_path("样例.xlsx")：项目 data/ 目录的只读样例文件
    - artifact_path("x.png")：本次执行的产物路径（下载/截图落盘）
    跳转、点击、输入、等待一律直接用 Playwright 原生写法：
    page.goto(base_url() + "/#/usm/users")、expect(locator).to_be_visible()、l.click()、l.fill(...)。
    不要写 click(locator)/fill(locator) 这类通用薄封装，也不要在帮助函数里做「页面级流程」。
26. 若「项目已有资产」一节列出可复用的 common 函数或页面对象类/方法，优先直接 import 调用
    （如 from common.ui import dialog_of、from pages.users_page import UsersPage），不要重复其流程。
    调用前先看签名：返回 Locator 的函数不能当下标用（不要写 text_inputs(dialog)[0]），
    需要用 dialog.locator("input[type=text]").nth(0) 这类原生定位；只有签名明确返回 list 才能下标访问。
27. 代码落位四档（先判断语义再写代码，不要混淆）：
    - Playwright 原生动作/断言/等待 → 直接写在脚本或页面对象里，不额外包装
    - 项目级通用能力（弹窗定位、输入框顺序原语、表格整行断言、toast 等待、下拉/上传/下载封装）
      → common/<主题>.py（可覆盖，系统自动备份到 common/history/），import 方式 from common.ui import xxx
    - 被测系统业务操作（页面路由、字段顺序、按钮文案、断言列）→ pages/<模块>_page.py（只增不覆盖）
    - 单用例步骤与断言 → case 脚本本身
    归属判定：同一逻辑被 ≥2 处（页面对象或用例）复用时才进 common，只服务单一页面就留在页面对象里；
    依赖方向必须单向：case → pages → common，common 不得 import pages，pages 不得 import 另一个 pages。
    需要新增或更新上述文件时，在 finish 里附带：
    {"script": "...", "pages": [{"path": "common/ui.py", "content": "完整源码"}]}
    path 必须是 pages/ 或 common/ 下的单层 .py 文件，content 需能通过 py_compile。
    这些文件会先写入生成期暂存区，首跑通过后才并入正式资产；失败自动丢弃，不会污染既有复用代码。
28. 禁止任何固定睡眠：不要写 page.wait_for_timeout / time.sleep / asyncio.sleep。
    等待一律用 expect(...) 自动轮询（to_be_visible / to_be_hidden / to_contain_text），
    或用 common 里已有的 wait_* 封装。
29. 安全边界（违反会被静态校验直接拒绝）：
    - 只允许 import：playwright、pytest、pages.*、common.*、env，以及 time/json/re/tempfile/datetime/random/string/uuid/typing
    - 禁止 import os/sys/subprocess/pathlib/shutil/requests 等，禁止读取配置文件与环境凭证
    - 禁止调用 open/eval/exec/compile/getattr/setattr
    - 上传样例文件用 data_path("文件名")；产物落盘用 artifact_path("文件名")
30. 「参考片段」是本项目同目录下已通过首跑脚本里的动作级代码（跳转/点击/输入/断言等）：
    先用它们确认页面路由、定位写法与断言风格，能直接沿用的直接沿用（同样的页面对象、
    common 函数、表格断言），减少重复探索。片段只是历史经验，与当前用例步骤冲突时
    一律以当前用例与真实快照为准，不要照抄片段里的业务数据、固定账号或断言文案。
    按钮/文案以浏览器快照里真实出现的文本为准（用例步骤写「保存」时，界面按钮可能叫「确定」），
    不要照抄用例描述里的字面文案。
31. 表单校验失败（控制台报错或字段下方出现红色提示）时，必须**在当前弹窗内直接修改该字段**，
    不要点取消/关闭再重新打开弹窗；提示里给出格式限制（如「6-32位字符，仅支持大小写字母、数字、中文、邮箱」）
    时，换成符合该限制的唯一值（例如 user + 时间戳，不要带下划线/符号），严禁重复提交同一非法值。
    同一步骤连续 2 次失败说明策略错了，换定位方式或换数据，不要原地重试。
32. 工具调用有硬预算（14 次，系统另会自动补快照/枚举控件，不占你的预算）。
    操作到「预期结果」并拿到关键选择器（路由 + 定位 + 断言点）后就应立即 finish，
    不要为了再确认一遍而反复快照；预算用尽时系统会强制你直接输出 finish。
33. ref 只能来自最近一次 browser_snapshot / browser_find 的输出。快照被截断看不到目标按钮时，
    用 browser_find(text="新增") 或再 browser_snapshot 取真实 ref，**禁止猜测或凭记忆写 e125
    这类 ref**（不存在的 ref 会被直接拒绝，反复猜会耗尽预算）。
34. 弹窗表单的 label 常常只是普通文本、没有 for/id 关联，get_by_label() 会必然超时。下拉控件
    通常是自定义 combobox（div[role=combobox]，不是原生 select，也没有 ant-select 类名）：
    按顺序用 dialog.get_by_role('combobox').nth(0/1/2…) 定位并点击，再点
    page.get_by_role('option', name=选项文案) 选择。字段控件也优先按 role + 顺序定位
    （input 用 dialog.get_by_role('textbox').nth(i)、勾选用 get_by_role('checkbox', name=文案)）。
35. 页面对象是普通类：必须 `UsersPage(page).open(dept=...)` 这样实例化后调用（方法签名里
    没有 self）；不要写成 `UsersPage.open(page, ...)`。pages/ 下已存在的文件禁止覆盖，
    提交会被拒绝；需要新能力时新建文件，或直接复用已有方法签名。
36. 「反面样本」是本项目历史失败的错题库（失败日志 + 踩过的坑 + 已验证的解决方案）：
    写脚本前先看，避免重复踩同样的坑；样本与当前页面事实冲突时以实测为准。
    若给出「本用例历史失败记录」，必须逐条避开里面已经失败过的断言/定位写法，
    每一次生成都要在上一次失败的基础上改进，不要原样重写同一段代码。
37. 若系统给出了「参数结构」（由弹窗实测控件 + 用例步骤确定性生成），测试函数必须声明 params fixture：
    def test_xxx(page, params)，表单取值一律写成 params["参数名"]，禁止写死用户名/邮箱/名称等业务数据。
    参数名必须与结构里的 name 完全一致；unique=true 的参数已由运行器自动追加运行时间后缀，
    不要再自己拼时间戳或调用 unique_name。这样生成后可在参数面板里直接修改取值并重新执行。
    与用例步骤无关的控件已由系统自动填充（必填项生成占位值、非必填留空），直接读 params 即可，
    不要为了让表单通过而改动它们的语义，也不要为它们新增参数。
    默认值为空的参数：若用例要求填写该字段，写成 params["参数名"] or "占位值"（面板有值时用面板值）；
    若用例要求留空，直接用空串即可，不要为了「看起来有值」而写死数据。
38. 该后台的校验错误不落在 input 上：错误文案在 div.ui-form-error-tip，表单项容器会加
    ui-form-item-invalid，input 自身仍是 ui-input ui-input-md ui-input-left。
    断言一律用文案（expect(dialog.get_by_text("显示名称不能为空")).to_be_visible()），
    禁止编造 ui-input-error 这类 class。密码为空的提示是「密码不能为空」，
    且需先取消勾选「使用默认密码」，否则密码框 disabled、不参与校验。
"""



def _now() -> datetime:
    return datetime.now()


def _snapshot_empty(text: str) -> bool:
    """MCP 快照只有页头、yaml 节点为空时视为空（页面未渲染）。"""
    if not text or "```yaml" not in text:
        return True
    body = text.split("```yaml", 1)[1].split("```", 1)[0].strip()
    return not body


SNAPSHOT_LINK_RE = re.compile(r"\[Snapshot\]\(\s*(.+?)\s*\)")
TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}T[\d:._-]+Z")


def _inline_snapshot_links(text: str) -> str:
    """MCP 大快照会写成文件只回链接：读回文件内容，否则模型等于看不到页面。"""
    if "[Snapshot](" not in (text or ""):
        return text

    def replace(match: re.Match) -> str:
        raw = match.group(1).strip()
        try:
            path = Path(raw)
            if not path.is_absolute():
                path = (Path.cwd() / raw).resolve()
            content = path.read_text(encoding="utf-8", errors="ignore").strip()
        except OSError:
            return match.group(0)
        return content[:OBS_LIMIT] if content else "（快照为空：页面可能还没渲染）"

    return SNAPSHOT_LINK_RE.sub(replace, text)


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
    # raw_decode 只解析第一个完整 JSON 对象，容忍模型多写的右括号/尾随说明。
    # 但模型偶尔先吐出一个代码片段对象（如脚本里的 {...}），从那里解析会得到没有
    # tool/script 的碎片，导致误判「工具名无效」；这里收集所有对象，优先取真实回复。
    found: list[dict] = []
    start = raw.find("{")
    while start >= 0:
        try:
            obj, _ = decoder.raw_decode(raw[start:])
            if isinstance(obj, dict):
                found.append(obj)
        except json.JSONDecodeError:
            pass
        start = raw.find("{", start + 1)
    for obj in found:
        if isinstance(obj.get("tool"), str) or any(
            k in obj for k in ("script", "pages", "patch", "patches")
        ):
            return obj
    # 没有一个像真实回复：说明整段 JSON 被截断（通常是输出长度打满），
    # 不要退化成脚本里的碎片对象，否则会被误判成「工具名无效」
    return None


CHAT_MAX_TOKENS = 8192


def _chat(llm, messages: list[dict], **kwargs) -> str:
    """统一模型调用：显式给足输出预算。

    finish 一轮要吐完整用例脚本（含 pages），模型默认输出上限常把 JSON 截断成非法内容。
    注意：只有端点明确拒绝 max_tokens 时才去掉参数重试；超时/限流等错误由 LLMClient
    内部重试处理，这里若整轮再来一遍会把「等模型响应」的时间直接翻倍。
    """
    kwargs.setdefault("max_tokens", CHAT_MAX_TOKENS)
    try:
        return llm.chat(_trim_messages(messages), **kwargs)
    except Exception as e:
        msg = str(e).lower()
        if "max_tokens" not in msg and "max output" not in msg:
            raise
        # 个别端点不接受 max_tokens 参数时退回默认预算
        kwargs.pop("max_tokens", None)
        return llm.chat(_trim_messages(messages), **kwargs)


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
    if re.search(r"(BASE_URL|base_url\(\))[^\n]{0,20}/manage", source):
        return "base_url() 已包含端入口（后台为 /manage），不要再拼接 /manage"
    return _check_sandbox(source, kind="脚本")


# 允许导入的模块白名单：playwright / pytest / 环境契约 / 项目资产（pages、common）/ 少量纯计算标准库
_ALLOWED_IMPORTS = {
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
_ALLOWED_ENV_PREFIX = "insight_aitest.modules.ui.backend.automation.env"
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
                if root not in _ALLOWED_IMPORTS and not alias.name.startswith(_ALLOWED_ENV_PREFIX):
                    return f"{kind}禁止导入 {alias.name}（仅允许 playwright/pytest/env/pages/common 与少量标准库）"
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            root = module.split(".")[0]
            if root not in _ALLOWED_IMPORTS and not module.startswith(_ALLOWED_ENV_PREFIX):
                return f"{kind}禁止导入 {module or '相对模块'}（仅允许 playwright/pytest/env/pages/common 与少量标准库）"
        elif isinstance(node, ast.Call):
            func = node.func
            # 只拦截直接调用（open/eval/exec...），避免误伤页面对象里同名的合法方法
            if isinstance(func, ast.Name) and func.id in _BANNED_CALLS:
                return f"{kind}禁止调用 {func.id}（脚本不得读写任意文件或动态执行代码）"
            attr = getattr(func, "attr", "")
            if attr == "wait_for_timeout" or attr == "sleep":
                return f"{kind}禁止固定睡眠（{attr}），请改用 expect 轮询或 common 里的 wait_*"
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
        # 浏览器由脚手架托管，close/emulate/resize 等无关工具不暴露给模型，避免空转
        if name in BLOCKED_TOOLS:
            continue
        desc = (tool.get("description") or "").split("\n")[0][:180]
        schema = tool.get("inputSchema") or {}
        required = schema.get("required") or []
        props = list((schema.get("properties") or {}).keys())
        hint = f" 参数: {', '.join(props)}" if props else ""
        req = f" 必填: {', '.join(required)}" if required else ""
        lines.append(f"- {name}: {desc}{hint}{req}")
    return "\n".join(lines)


def _normalize_tool_name(name: str) -> str:
    """模型常把工具名写成空格/短横线分隔或带引号，统一成 browser_xxx 形式。"""
    raw = (name or "").strip().strip("`'\"“”").strip()
    return re.sub(r"[\s\-]+", "_", raw).lower()


def _closest_tool(name: str, candidates: list[str]) -> str:
    """把模型自造的工具名（拼写/分隔符差异）纠正到真实工具名。"""
    import difflib

    if not name or not candidates:
        return ""
    found = difflib.get_close_matches(name, candidates, n=1, cutoff=0.75)
    return found[0] if found else ""


def _dump_controls(client) -> tuple[list[dict], str]:
    """枚举当前弹窗里所有可编辑控件（真实 DOM，不消耗模型额度）。

    返回 ``(items, sig)``：sig 是弹窗正文摘要，用于识别「换了一个弹窗」——
    例如误点导入弹窗后又打开新增弹窗，两份清单不能混在一起。
    """
    try:
        text, is_error = client.call_tool(
            "browser_evaluate", {"function": CONTROL_INVENTORY_JS}, timeout=40
        )
    except Exception:  # noqa: BLE001 - 枚举失败不影响主链路
        return [], ""
    if is_error or not text:
        return [], ""
    start = text.find("{")
    if start < 0:
        return [], ""
    try:
        data, _ = json.JSONDecoder(strict=False).raw_decode(text[start:])
    except (ValueError, TypeError):
        return [], ""
    if isinstance(data, list):  # 兼容旧结构
        return _normalize_items(data), ""
    if not isinstance(data, dict):
        return [], ""
    sig = str(data.get("sig") or "").strip()[:60]
    raw_items = data.get("items")
    return _normalize_items(raw_items if isinstance(raw_items, list) else []), sig


def _normalize_items(data: list) -> list[dict]:
    items: list[dict] = []
    for index, raw in enumerate(data, 1):
        if not isinstance(raw, dict):
            continue
        label = str(raw.get("label") or "").strip() or f"控件{index}"
        item = {"label": label[:40], "type": str(raw.get("type") or "text")}
        value = raw.get("value")
        if value not in (None, ""):
            item["value"] = str(value)[:60]
        options = raw.get("options")
        if isinstance(options, list) and options:
            item["options"] = [str(o)[:40] for o in options][:60]
        if raw.get("checked") is not None:
            item["checked"] = bool(raw.get("checked"))
        if raw.get("required"):
            item["required"] = True
        items.append(item)
    return items


def _format_inventory(items: list[dict]) -> str:
    """把控件清单转成给模型看的逐条说明。"""
    kind_map = {
        "select": "下拉",
        "checkbox": "勾选",
        "radio": "单选",
        "password": "密码输入",
        "textarea": "多行输入",
    }
    lines: list[str] = []
    combo_index = -1
    for index, item in enumerate(items, 1):
        kind = kind_map.get(str(item.get("type") or ""), "输入")
        label = item.get("label") or f"控件{index}"
        if kind in ("勾选", "单选"):
            extra = "，默认勾选" if item.get("checked") else "，默认未勾选"
        else:
            value = item.get("value")
            extra = f"，当前值={value}" if value not in (None, "") else ""
        if item.get("options"):
            extra += "，可选值：" + "、".join(str(o) for o in item["options"])
        if kind == "下拉":
            # 下拉按 DOM 顺序编号，脚本里用 dialog.get_by_role('combobox').nth(n) 定位
            combo_index += 1
            extra += f"（combobox 顺序 #{combo_index}）"
        lines.append(f"{index}. {kind}「{label}」{extra}")
    if combo_index >= 0:
        lines.append(
            "下拉控件的定位方式：表单 label 通常未与控件关联，禁止用 get_by_label()；"
            "用 dialog.get_by_role('combobox').nth(上面的 combobox 顺序) 展开，"
            "再点 get_by_role('option', name=选项文案) 选择。"
        )
    return "\n".join(lines)


def _merge_inventory(inventory: list[dict], items: list[dict]) -> bool:
    """按 label+type 合并控件清单，返回是否有新增（下拉选项变多也算）。"""
    seen = {(item.get("label"), item.get("type")) for item in inventory}
    changed = False
    for item in items:
        key = (item.get("label"), item.get("type"))
        if key in seen:
            for existing in inventory:
                if (existing.get("label"), existing.get("type")) != key:
                    continue
                # 选项可能异步加载，保留更完整的一份
                if len(item.get("options") or []) > len(existing.get("options") or []):
                    existing["options"] = item["options"]
                    changed = True
            continue
        inventory.append(item)
        seen.add(key)
        changed = True
    return changed


_PARAM_TYPE_MAP = {
    "select": "select",
    "checkbox": "bool",
    "radio": "bool",
    "password": "str",
    "textarea": "str",
}
# 这些 label 对应的文本字段重复提交会冲突（用户名/邮箱/手机号等），运行器自动追加时间后缀
_UNIQUE_HINTS = (
    "用户名",
    "账号",
    "邮箱",
    "手机",
    "电话",
    "编号",
    "编码",
    "username",
    "email",
    "phone",
    "account",
    "code",
)
_GENERIC_LABEL_RE = re.compile(r"^控件\d+$")
# 与用例步骤无关、但实测为必填的控件：按 label 生成符合常见校验规则的占位值
_AUTO_VALUE_RULES = (
    (("邮箱", "邮件"), "auto@example.com"),
    (("手机", "电话", "联系方式"), "13800000000"),
    (("密码", "口令"), "Aa123456!"),
    (("pin",), "123456"),
    (("编号", "编码"), "A0001"),
)
# 用例文案里常用「账号」「昵称」等同义说法，用于把控件和步骤对上
_LABEL_ALIASES = {
    "用户名": ("用户名", "账号", "登录名", "用户账号"),
    "账号": ("账号", "用户名", "登录名"),
    "登录名": ("登录名", "用户名", "账号"),
    "密码": ("密码", "口令"),
    "显示名称": ("显示名称", "昵称"),
    "昵称": ("昵称", "显示名称"),
    "邮箱": ("邮箱", "邮件", "电子邮箱"),
    "手机": ("手机", "手机号", "手机号码"),
    "电话": ("电话", "联系方式", "手机"),
    "联系方式": ("联系方式", "手机", "电话"),
    "用户等级": ("用户等级", "等级"),
    "部门": ("部门", "所属部门"),
    "职位": ("职位", "职务"),
    "有效期": ("有效期", "期限"),
}
_LABEL_SPLIT_RE = re.compile(r"[（(\[{<，,；;/|]")
_LABEL_NOISE_RE = re.compile(r"(请输入|请选择|输入|选择|必填项|必填|选填)")


def _label_core(label: str) -> str:
    """去掉括号说明、必填星号与「请输入」等噪声，得到控件主词。"""
    text = _LABEL_SPLIT_RE.split(str(label or ""), 1)[0]
    text = text.replace("*", "").replace("＊", "")
    return _LABEL_NOISE_RE.sub("", text).strip()


def _text_norm(text: str) -> str:
    return re.sub(r"[^\w]", "", str(text or "").lower())


def _case_text(case) -> str:
    """用例全文（标题/前置/步骤/预期），用于判定哪些控件与用例步骤相关。"""
    steps = "；".join(str(s) for s in (getattr(case, "steps", None) or []))
    return "\n".join(
        [
            str(getattr(case, "title", "") or ""),
            str(getattr(case, "precondition", "") or ""),
            steps,
            str(getattr(case, "expected", "") or ""),
        ]
    )


HISTORY_MAX_GENS = 8
HISTORY_MAX_EVENTS = 3
HISTORY_ITEM_CHARS = 220
HISTORY_MAX_CHARS = 2000


def _case_failure_history(case, db) -> str:
    """本用例历次生成真实失败的事实，供新一轮生成直接基于失败迭代。

    只读该用例自己的生成记录：优先取日志里的首跑验证/静态校验/补丁失败消息，
    没有日志时退回该轮最终错误。体积控制：最多 8 轮、每轮 ≤3 条、
    单条 ≤220 字、总量 ≤2000 字。
    """
    try:
        gens = db.list_generations(int(getattr(case, "id")), HISTORY_MAX_GENS)
    except Exception:  # noqa: BLE001 - 历史仅供参考，读失败不影响本次生成
        return ""

    def brief(text: str) -> str:
        return re.sub(r"\s+", " ", (text or "")).strip()[:HISTORY_ITEM_CHARS]

    seen: set[str] = set()
    blocks: list[str] = []
    used = 0
    for gen in gens:
        if (getattr(gen, "status", "") or "") == GenerationStatus.SUCCESS:
            continue
        items: list[str] = []

        def add(label: str, text: str) -> None:
            text = brief(text)
            if not text:
                return
            key = text[:60]
            if key in seen:
                return
            seen.add(key)
            items.append(f"  - {label}：{text}")

        log_rel = getattr(gen, "log_rel_path", "") or ""
        if log_rel:
            try:
                log_path = paths.resolve_rel(log_rel)
                if log_path.exists():
                    with log_path.open(encoding="utf-8") as f:
                        for line in f:
                            if len(items) >= HISTORY_MAX_EVENTS:
                                break
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                evt = json.loads(line)
                            except Exception:
                                continue
                            etype = evt.get("type")
                            if etype == "validate" and evt.get("status") == "failed":
                                add("首跑验证失败", evt.get("message") or "")
                            elif etype == "script_invalid":
                                add("脚本静态校验失败", evt.get("message") or "")
                            elif etype in ("patch_invalid", "pages_invalid"):
                                add("补丁/资产未应用", evt.get("message") or "")
                            elif etype == "llm_error":
                                add("模型调用失败", evt.get("error") or "")
            except Exception:  # noqa: BLE001
                pass
        if not items:
            add("最终失败", getattr(gen, "error_message", "") or "")
        if not items:
            continue
        block = f"- 第 {getattr(gen, 'id', '?')} 次生成：\n" + "\n".join(items)
        if used + len(block) > HISTORY_MAX_CHARS:
            break
        used += len(block)
        blocks.append(block)
    return "\n".join(blocks)


def _is_related(label: str, text_norm: str) -> bool:
    """控件主词（或同义说法）是否出现在用例文案里。"""
    core = _label_core(label)
    core_norm = _text_norm(core)
    if len(core_norm) >= 2 and core_norm in text_norm:
        return True
    for alias in _LABEL_ALIASES.get(core, ()):
        alias_norm = _text_norm(alias)
        if len(alias_norm) >= 2 and alias_norm in text_norm:
            return True
    return False


def _auto_value(label: str, kind: str, options: list[str], current: str) -> str:
    """无关必填控件的占位值（下拉沿用界面默认，文本按字段语义生成）。"""
    if kind == "select":
        return current or (options[0] if options else "")
    lowered = label.lower()
    for hints, value in _AUTO_VALUE_RULES:
        if any(h.lower() in lowered for h in hints):
            return value
    return "auto"


def _param_name(label: str, index: int, used: set[str]) -> str:
    """由控件 label 推导参数名：保留中文/字母数字，重名追加序号。"""
    cleaned = re.sub(r"[^\w]", "", label or "", flags=re.UNICODE)[:12]
    base = cleaned if cleaned and not _GENERIC_LABEL_RE.match(label or "") else f"f{index}"
    name = base
    suffix = 2
    while name in used:
        name = f"{base}{suffix}"
        suffix += 1
    return name


def _inventory_schema(inventory: list[dict], case_text: str = "") -> list[dict]:
    """把实测控件清单确定性转换成参数结构（零模型 token）。

    只把与用例步骤相关的控件提取为可编辑参数（related=True）；其余控件
    （related=False）由系统自动处理：必填项生成占位值注入，非必填项留空，
    避免无关参数挤占面板、增加生成与维护成本。
    """
    text_norm = _text_norm(case_text)
    schema: list[dict] = []
    used: set[str] = set()
    for index, item in enumerate(inventory, 1):
        raw_label = str(item.get("label") or f"控件{index}").strip()[:40]
        label = _label_core(raw_label) or raw_label
        kind = _PARAM_TYPE_MAP.get(str(item.get("type") or "text"), "str")
        options = [str(o).strip()[:40] for o in item.get("options") or [] if str(o).strip()][:60]
        unique = kind == "str" and any(h in raw_label.lower() for h in _UNIQUE_HINTS)
        # 用例文案为空（极少见）时退回全量，避免参数面板空白无从调整
        related = _is_related(raw_label, text_norm) if text_norm else True
        if kind == "bool":
            default = bool(item.get("checked"))
            desc = "勾选控件，默认" + ("勾选" if default else "未勾选")
            required = False
        elif kind == "select":
            default = str(item.get("value") or "").strip() or (options[0] if options else "")
            desc = "下拉控件" + ("，可选值：" + "、".join(options) if options else "")
            required = bool(options)
        else:
            required = bool(item.get("required")) or unique
            if related:
                # 相关控件保留弹窗里的真实值；空值可能是用例要验证的点，不强制非空
                default = str(item.get("value") or "").strip()
                desc = "输入控件" + (f"，当前值 {default}" if default else "（弹窗内为空）")
                required = False
            else:
                default = _auto_value(label, kind, options, "") if required else ""
                desc = "输入控件，" + ("必填，已由系统自动填写" if required else "非必填，留空")
        if unique and not default:
            default = "auto@example.com" if ("邮箱" in raw_label or "email" in raw_label.lower()) else "auto"
        if not related:
            desc += "（未在用例步骤中提到，由系统自动处理）"
        name = _param_name(label, index, used)
        used.add(name)
        entry = {
            "name": name,
            "label": label,
            "type": kind,
            "required": required,
            "default": default,
            "desc": desc,
            "unique": unique,
            "related": related,
            "auto": not related,
        }
        if options:
            entry["options"] = options
        schema.append(entry)
    return schema


def _format_params(schema: list[dict]) -> str:
    """把参数结构转成给模型看的说明：相关参数逐条列出，其余压成一行自动值。"""
    related = [item for item in schema if item.get("related", True)]
    auto = [item for item in schema if not item.get("related", True)]
    lines: list[str] = []
    if related:
        lines.append("与本用例步骤相关的参数（可在参数面板查看/修改，脚本必须从这里取值）：")
        for item in related:
            default = item.get("default")
            extra = f"，默认值={default}" if default not in (None, "") else "，默认空"
            if item.get("options"):
                extra += "，可选值：" + "、".join(str(o) for o in item["options"])
            if item.get("unique"):
                extra += "，每次运行自动追加唯一后缀"
            lines.append(f'- params["{item["name"]}"] ← 「{item["label"]}」（{item["type"]}{extra}）')
    else:
        lines.append("本用例没有需要人工调整的参数，表单数据由系统自动处理。")
    if auto:
        pairs = []
        for item in auto:
            value = item.get("default")
            pairs.append(f"{item['name']}={'空' if value in (None, '') else value}")
        lines.append("其余控件由系统自动填充（必填项生成占位值、非必填留空），可直接读取但不要修改：")
        lines.append("、".join(pairs))
    return "\n".join(lines)


def _used_params(tree) -> set[str]:
    """收集源码里 ``params["x"]`` 与 ``params.get("x")`` 形式的参数引用。"""
    import ast

    used: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript):
            value = node.value
            key = node.slice
            if (
                isinstance(value, ast.Name)
                and value.id == "params"
                and isinstance(key, ast.Constant)
                and isinstance(key.value, str)
            ):
                used.add(key.value)
        elif isinstance(node, ast.Call):
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "get"
                and isinstance(func.value, ast.Name)
                and func.value.id == "params"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                used.add(node.args[0].value)
    return used


def _check_params(source: str, schema: list[dict]) -> str:
    """参数化静态校验：声明 params fixture、使用真实参数名、不引用结构外 key。"""
    import ast

    if not schema:
        return ""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ""
    tests = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    ]
    args = [a.arg for fn in tests for a in fn.args.args + fn.args.kwonlyargs]
    used = _used_params(tree)
    names = [str(item.get("name")) for item in schema if item.get("name")]
    unknown = sorted(used - set(names))
    if unknown:
        return (
            "脚本引用了参数结构外的 key："
            + "、".join(unknown)
            + "。可用参数名："
            + "、".join(names)
        )
    # 既没有相关参数、也没有需要自动注入的值时（如纯点击取消类用例），不强制使用 params
    needs_params = any(
        item.get("related", True) or item.get("default") not in (None, "") for item in schema
    )
    if not needs_params:
        return ""
    if "params" not in args:
        return (
            "弹窗内存在与用例步骤相关的控件，测试函数必须声明 params fixture"
            "（def test_xxx(page, params)），表单取值一律从 params 读取。"
        )
    if not used:
        return (
            "脚本没有使用 params fixture 取值；表单里的业务数据（用户名/邮箱/名称等）"
            '必须写成 params["参数名"]，禁止写死。可用参数名：' + "、".join(names)
        )
    return ""


PAGE_FACTS_LIMIT = 1200


def _dump_page_facts(client) -> str:
    """直连页面读取表格表头/菜单/字段/按钮文案（零模型 token）。

    返回给模型看的紧凑文本；读失败返回空串，不影响主链路。
    """
    try:
        text, is_error = client.call_tool(
            "browser_evaluate", {"function": PAGE_FACTS_JS}, timeout=40
        )
    except Exception:  # noqa: BLE001 - 预取失败不影响主链路
        return ""
    if is_error or not text:
        return ""
    start = text.find("{")
    if start < 0:
        return ""
    try:
        data, _ = json.JSONDecoder(strict=False).raw_decode(text[start:])
    except (ValueError, TypeError):
        return ""
    if not isinstance(data, dict):
        return ""

    lines: list[str] = []
    url = str(data.get("url") or "").strip()
    if url:
        lines.append(f"当前地址：{url}")
    for key, title in (
        ("menus", "菜单项"),
        ("headers", "表格表头"),
        ("buttons", "按钮文案"),
        ("fields", "表单字段"),
    ):
        values = data.get(key)
        if isinstance(values, list) and values:
            lines.append(f"{title}：" + "、".join(str(v) for v in values if str(v).strip()))
    return _truncate("\n".join(lines), PAGE_FACTS_LIMIT)


def _apply_patches(source: str, payload) -> tuple[str, str]:
    """按 find/replace 应用最小补丁；任一段找不到或不唯一即整体失败。

    返回 ``(新源码, 错误信息)``；错误信息为空表示补丁成功。
    """
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list) or not payload:
        return source, "patch 必须是非空数组：[{\"find\": \"...\", \"replace\": \"...\"}]"
    if len(payload) > 12:
        return source, "单次补丁最多 12 段，请拆成更小的改动"
    result = source
    for index, item in enumerate(payload, 1):
        if not isinstance(item, dict):
            return source, f"第 {index} 段补丁不是对象"
        find = item.get("find")
        replace = item.get("replace")
        if not isinstance(find, str) or not find:
            return source, f"第 {index} 段补丁缺少 find"
        if not isinstance(replace, str):
            replace = "" if replace is None else str(replace)
        count = result.count(find)
        if count == 0:
            return source, f"第 {index} 段补丁的 find 在脚本中不存在（可能上一段补丁已改动这段代码）"
        if count > 1:
            return source, f"第 {index} 段补丁的 find 命中 {count} 处，请补充上下文保证唯一"
        result = result.replace(find, replace, 1)
    return result, ""


def _case_brief(case) -> str:
    steps = "\n".join(f"{i}. {s}" for i, s in enumerate(case.steps or [], 1)) or "（无）"
    return (
        f"用例标题：{case.title}\n"
        f"前置条件：{case.precondition or '（无）'}\n"
        f"测试步骤：\n{steps}\n"
        f"预期结果：{case.expected or '（无）'}"
    )


PAGES_CATALOG_LIMIT = 8000
# 项目级资产目录：common 可覆盖（写前备份），pages 只增不覆盖
ASSET_DIRS = ("common", "pages")


def _signature(node) -> str:
    """函数签名参数列表（去掉 self/cls）。"""
    args = [a.arg for a in node.args.args if a.arg not in ("self", "cls")]
    if node.args.vararg is not None:
        args.append("*" + node.args.vararg.arg)
    return ", ".join(args)


def _asset_root(project_id: int, package: str) -> Path:
    return paths.common_dir(project_id) if package == "common" else paths.pages_dir(project_id)


def _catalog_section(root: Path, package: str) -> list[str]:
    """扫描单个资产目录的类/函数签名。"""
    import ast

    lines: list[str] = []
    for file in sorted(root.glob("*.py")):
        if file.name == "__init__.py":
            continue
        try:
            tree = ast.parse(file.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        module = f"{package}.{file.stem}"
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                doc = (ast.get_docstring(node) or "").split("\n")[0].strip()
                lines.append(f"- {module}.{node.name}" + (f"：{doc}" if doc else ""))
                lines.append(
                    f"    · 用法：{node.name}(page).方法名(...)；方法签名已去掉 self，"
                    f"不要再把 page 当第一个实参传（{node.name}.method(page, ...) 会报错）"
                )
                for sub in node.body:
                    if isinstance(sub, ast.FunctionDef) and not sub.name.startswith("_"):
                        sub_doc = (ast.get_docstring(sub) or "").split("\n")[0].strip()
                        lines.append(
                            f"    · {sub.name}({_signature(sub)})" + (f"  # {sub_doc}" if sub_doc else "")
                        )
            elif isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
                doc = (ast.get_docstring(node) or "").split("\n")[0].strip()
                lines.append(f"- {module}.{node.name}({_signature(node)})" + (f"  # {doc}" if doc else ""))
    return lines


def pages_catalog(project_id: int) -> str:
    """项目已有资产（common 通用能力 + pages 页面对象）的签名，供模型直接复用。"""
    sections: list[str] = []
    for package, title in (
        ("common", "项目通用能力（common/，被 ≥2 处复用的非业务逻辑）"),
        ("pages", "页面对象（pages/，业务操作）"),
    ):
        lines = _catalog_section(_asset_root(project_id, package), package)
        if lines:
            sections.append(f"【{title}】\n" + "\n".join(lines))
    text = "\n\n".join(sections)
    if len(text) <= PAGES_CATALOG_LIMIT:
        return text
    return (
        text[:PAGES_CATALOG_LIMIT]
        + "\n…（资产清单已截断，其余文件请按需复用：先看 common/ 与 pages/ 目录，再决定是否新建）"
    )


def _copy_assets(src: Path, dst: Path) -> None:
    """把正式资产目录复制进暂存目录（目录不存在时补空包）。"""
    dst.mkdir(parents=True, exist_ok=True)
    if src.exists():
        shutil.copytree(src, dst, dirs_exist_ok=True)
    init = dst / "__init__.py"
    if not init.exists():
        init.write_text("# -*- coding: utf-8 -*-\n", encoding="utf-8")


def _prepare_staging(project_id: int, case_id: int, reuse: bool = False) -> Path:
    """重建暂存目录：正式 common/pages 的副本，首跑用它（已验证才并入正式目录）。

    reuse=True 用于两阶段输出：第一步已暂存资产，第二步在此基础上继续追加。
    """
    staging = paths.staging_root(project_id, case_id)
    if reuse and (staging / "common").exists():
        return staging
    shutil.rmtree(staging, ignore_errors=True)
    for package in ASSET_DIRS:
        _copy_assets(_asset_root(project_id, package), staging / package)
    return staging


def stage_pages(
    project_id: int, case_id: int, payload, reuse_staging: bool = False
) -> tuple[str, Path | None]:
    """校验资产提交并写入生成期暂存目录，返回 (错误信息, 暂存根目录)。

    暂存目录是正式 common/ + pages/ 的副本，首跑用它，
    避免未验证的资产污染正式目录；通过后由 adopt_pages 并入。

    落位规则：
    - ``common/xxx.py``：项目级通用代码，允许覆盖，并入时备份旧版到 common/history/；
    - ``pages/xxx.py``：页面对象，只允许新增，避免一次生成破坏既有复用资产。
    """
    if not isinstance(payload, list) or not payload:
        return "", None
    staging = _prepare_staging(project_id, case_id, reuse=reuse_staging)

    for item in payload:
        if not isinstance(item, dict):
            return "pages 必须是对象数组：[{\"path\": \"common/x.py\" 或 \"pages/x.py\", \"content\": \"...\"}]", None
        rel = str(item.get("path") or "").strip().replace("\\", "/")
        content = str(item.get("content") or "")
        parts = rel.split("/")
        if len(parts) != 2 or parts[0] not in ASSET_DIRS or not parts[1].endswith(".py"):
            return f"资产路径必须形如 common/xxx.py 或 pages/xxx.py（单层文件），收到：{rel}", None
        package, name = parts
        if name == "__init__.py":
            return f"资产文件名不合法：{rel}", None
        if package == "pages" and (_asset_root(project_id, "pages") / name).exists():
            return f"页面对象 {rel} 已存在，不能覆盖；请直接复用它的方法或换新文件名", None
        problem = _compile(content)
        if not problem:
            problem = _check_sandbox(content, kind=f"资产 {rel} ")
        if problem:
            return f"资产 {rel} 校验失败：{problem}", None
        (staging / rel).write_text(content, encoding="utf-8")
    return "", staging


def adopt_pages(project_id: int, staging: Path | None) -> None:
    """首跑通过后，把暂存资产并入正式目录（common 覆盖前备份，pages 只增）。"""
    if staging is None:
        return
    for package in ASSET_DIRS:
        staged = staging / package
        if not staged.exists():
            continue
        real = _asset_root(project_id, package)
        for file in sorted(staged.glob("*.py")):
            name = file.name
            if name == "__init__.py":
                continue
            content = file.read_text(encoding="utf-8")
            target = real / name
            if target.exists():
                if target.read_text(encoding="utf-8") == content:
                    continue
                if package == "pages":
                    # 页面对象不覆盖（生成期已校验存在性，这里兜底）
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
        # 模型自己发起的调用（不含自动补快照/控件枚举），用于探索预算约束
        self.model_calls = 0
        self.model_name = ""
        # 可观测指标：语料命中字符、输入/输出字符、修复轮次
        self.corpus_chars = 0
        self.prompt_chars = 0
        self.completion_chars = 0
        self.fix_rounds = 0
        # 首次失败快照与采用的修复方式，成功时沉淀「踩坑 + 解决方案」样本
        self.first_failure = ""
        self.fix_mode = ""
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
            log_path = paths.generation_log(self.case_id, self.gen_id)
            # 日志路径先落库：生成中前端就能按 generation id 拉取过程日志
            self.db.update_generation(self.gen_id, log_rel_path=paths.to_rel(log_path))
            self._log = open(log_path, "a", encoding="utf-8")
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

        from insight_aitest.platform.services.kb.deps import get_llm, get_llm_config

        llm = get_llm()
        self.model_name = get_llm_config().chat_model

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
        known_tools = {
            str(tool.get("name") or "") for tool in client.list_tools()
            if str(tool.get("name") or "").startswith("browser_")
        } - BLOCKED_TOOLS

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
        corpus_text = corpus.reference_snippets(case, self.db)
        if corpus_text:
            user_parts.append(
                "同目录参考片段（同项目同目录下已通过首跑的脚本动作片段，优先沿用其中的路由、定位与断言写法）：\n"
                + corpus_text
            )
        lesson_text = lessons.relevant_lessons(case, self.db)
        if lesson_text:
            user_parts.append(
                "反面样本（本项目历史失败的错题库，含踩过的坑与已验证的解决方案，"
                "写脚本前先看，避免重复踩坑）：\n"
                + lesson_text
            )
        history_text = _case_failure_history(case, self.db)
        if history_text:
            user_parts.append(
                "本用例历史失败记录（此前各轮生成在本地首跑/校验阶段真实失败的事实，"
                "逐条核对，不要重复同样的定位与断言写法；与当前实测冲突时以实测为准）：\n"
                + history_text
            )
        self.corpus_chars = len(corpus_text) + len(lesson_text) + len(history_text)
        if not is_fix:
            user_parts.append(
                "弹窗打开后，系统会自动用 browser_evaluate 枚举其中的可编辑控件并以"
                "「自动枚举控件清单」发给你；脚本必须逐个覆盖清单里的控件，不要漏项。"
            )
        catalog_pages = pages_catalog(int(case.project_id))
        if catalog_pages:
            user_parts.append(
                "项目已有资产（优先复用，通用能力 import common.xxx、页面对象 import pages.xxx）：\n"
                + catalog_pages
            )
        else:
            user_parts.append(
                "项目暂无公共资产；如本用例确实需要沉淀可复用代码，按规则 27 在 finish 中提交 common/ 或 pages/ 文件。"
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

        # 确定性预取：直连页面读真实文案（表格表头/菜单/字段/按钮），零模型 token。
        # 最多 3 次（首屏 + 弹窗），内容不变不重复注入。
        facts_state = {"sig": "", "count": 0}

        def push_facts(prefix: str = "") -> None:
            if facts_state["count"] >= 3:
                return
            facts_state["count"] += 1
            text = _dump_page_facts(client)
            if not text or text == facts_state["sig"]:
                return
            facts_state["sig"] = text
            self._write_log({"type": "page_facts", "text": text})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"【页面实测事实{prefix}】系统已直连页面读取以下真实文案，"
                        "不需要再为确认按钮/菜单/表头而反复快照：\n" + text
                    ),
                }
            )

        # 先自动打开目标页面并回灌快照：模型拿到真实 ref 后才不会拿 Playwright 表达式/中文描述当 target
        snap = ""
        try:
            self.tool_calls += 2
            concurrency.set_progress(self.case_id, "打开页面", "导航到目标页面并获取快照")
            nav_obs, nav_err = client.call_tool("browser_navigate", {"url": target_url})
            snap = ""
            # SPA 首屏渲染有延迟，快照常是空的；等一下重试几次，拿到真实节点再交给模型
            for _ in range(3):
                time.sleep(1.5)
                snap, _ = client.call_tool("browser_snapshot", {})
                if snap and not _snapshot_empty(snap):
                    break
            self._write_log(
                {
                    "type": "auto_open",
                    "url": target_url,
                    "nav_error": nav_err,
                    "empty_snapshot": _snapshot_empty(snap),
                    "snap": _truncate(snap),
                }
            )
            if snap and not _snapshot_empty(snap):
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"已自动打开 {target_url}，下面是当前页面快照。\n"
                            "后续 browser_click / browser_type 的 target 只能取自下面的 ref（形如 e125），"
                            "禁止使用 get_by_role 表达式或中文描述。\n\n" + _truncate(snap, SNAP_LIMIT)
                        ),
                    }
                )
            else:
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"已自动打开 {target_url}，但快照是空的（页面可能还在渲染或登录态失效）。"
                            "请先 browser_snapshot 重试直到出现节点，严禁凭空编造 e125 这类 ref。"
                        ),
                    }
                )
        except Exception as e:
            self._write_log({"type": "auto_open_error", "error": f"{type(e).__name__}: {e}"})

        push_facts("（首屏）")

        rounds = 0
        bad_json = 0
        early_finish = 0
        static_rounds = 0
        last_source = ""
        budget_notice = False
        finish_nudged = False
        locators_seen = 0
        recent_calls: list[tuple[str, str]] = []
        bad_targets: dict[str, int] = {}
        unknown_replies: dict[str, int] = {}
        blocked_closes = 0
        inventory: list[dict] = []
        inventory_notices = 0
        inventory_empty_logged = False
        inventory_probes = 0
        inventory_sig = ""
        bad_refs: dict[str, int] = {}
        last_refs: set[str] = set(REF_RE.findall(snap or ""))
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
            if self.model_calls > MAX_MODEL_CALLS and not budget_notice:
                budget_notice = True
                self._write_log({"type": "budget_exhausted", "model_calls": self.model_calls})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"探索预算已用尽（你已发起 {self.model_calls} 次工具调用，上限 {MAX_MODEL_CALLS}）。"
                            "不要再调用任何浏览器工具，立即基于已确认的页面事实输出 finish JSON："
                            '{"thought": "脚本已就绪", "tool": "finish", "args": {"script": "完整脚本"}}'
                            "（若第一步已提交资产，则只提交 script）。"
                        ),
                    }
                )

            concurrency.set_progress(self.case_id, "模型思考", f"已调用工具 {self.tool_calls} 次")
            # 记录本轮请求规模：卡住时能直接从过程日志判断是模型端慢/超时，而不是无感空转
            trimmed = _trim_messages(messages)
            self._write_log(
                {
                    "type": "llm_request",
                    "model": model_name,
                    "messages": len(trimmed),
                    "chars": sum(len(str(m.get("content") or "")) for m in trimmed),
                }
            )
            try:
                reply = _chat(llm, messages, temperature=0.2)
            except Exception as e:
                self._write_log(
                    {
                        "type": "llm_error",
                        "sizes": [len(str(m.get("content") or "")) for m in messages],
                        "total": sum(len(str(m.get("content") or "")) for m in messages),
                        "model": model_name,
                        "error": f"{type(e).__name__}: {e}"[:400],
                    }
                )
                return {
                    "status": GenerationStatus.FAILED,
                    "error_category": ErrorCategory.MODEL,
                    "message": f"模型调用失败：{type(e).__name__}: {e}",
                }
            # 指标：按实际发送（裁剪后）与模型回复估算字符消耗
            self.prompt_chars += sum(
                len(str(m.get("content") or "")) for m in _trim_messages(messages)
            )
            self.completion_chars += len(reply or "")

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
                        "content": "输出不是合法 JSON（也可能是输出被长度上限截断了）。请只输出一个 JSON 对象，"
                        "不要解释段落、不要用 ``` 包裹、不要在 JSON 前后写文字；"
                        "字符串内换行写成 \\n，双引号转义为 \\\"，代码整体作为脚本字符串值。"
                        "内容过长时不要重复贴已有公共代码，只给本次新增/修改部分。"
                        '每轮形如 {"thought": "查看页面结构", "tool": "browser_snapshot", "args": {}}。',
                    }
                )
                continue

            thought = str(parsed.get("thought") or "")[:500]
            raw_tool = str(parsed.get("tool") or "").strip()
            args = parsed.get("args") or {}
            if not isinstance(args, dict):
                args = {}
            # 模型常省略 thought/tool，直接给出 finish 内容（script/pages/patch）：按 finish 处理
            if not raw_tool and any(k in parsed for k in ("script", "pages", "patch", "patches")):
                raw_tool = "finish"
                args = parsed
            elif not raw_tool and "script" in args:
                raw_tool = "finish"
            tool = _normalize_tool_name(raw_tool)
            if tool not in ("finish", "browser_close", "browser_kill") and tool not in known_tools:
                # 模型会把工具名写成「browser emulate media」这种空格分隔形式或拼错，
                # 能纠正的就地纠正；否则一个分隔符就会白白烧掉一整轮工具预算
                fixed = _closest_tool(tool, sorted(known_tools))
                if fixed:
                    self._write_log({"type": "tool_alias", "from": raw_tool, "to": fixed})
                    tool = fixed
            self._write_log({"type": "assistant", "thought": thought, "tool": tool, "args": args})
            if budget_notice and tool != "finish":
                return {
                    "status": GenerationStatus.FAILED,
                    "error_category": ErrorCategory.MODEL,
                    "message": f"探索预算用尽（{MAX_MODEL_CALLS} 次）后仍未产出脚本，已终止以节省配额",
                }

            if tool in ("browser_close", "browser_kill"):
                # 浏览器/标签页由脚手架管理：关闭后没有标签页，模型会陷入「反复 close」空转
                blocked_closes += 1
                self.tool_calls += 1
                self.model_calls += 1
                self._write_log({"type": "blocked_tool", "tool": tool})
                if blocked_closes >= 3 or self.model_calls > MAX_MODEL_CALLS:
                    return {
                        "status": GenerationStatus.FAILED,
                        "error_category": ErrorCategory.MODEL,
                        "message": "模型反复关闭浏览器导致无法继续探索，已终止",
                    }
                messages.append({"role": "assistant", "content": reply})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "不要调用 browser_close：浏览器与标签页由运行脚手架管理，关闭后就没有页面可用了。"
                            "请用 browser_navigate 重新打开目标页，再继续 browser_snapshot / browser_click。"
                        ),
                    }
                )
                continue

            if tool != "finish" and tool not in known_tools:
                # 未知/空/被禁用工具名不能送 MCP（会报 Tool "" not found），提示按协议重来
                self.tool_calls += 1
                self.model_calls += 1
                if self.model_calls > MAX_MODEL_CALLS:
                    return {
                        "status": GenerationStatus.FAILED,
                        "error_category": ErrorCategory.MODEL,
                        "message": f"探索预算用尽（{MAX_MODEL_CALLS} 次）仍未给出有效工具名，已终止",
                    }
                self._write_log({"type": "unknown_tool", "tool": tool, "reply": _truncate(reply, 800)})
                sig = (reply or "").strip()[:400]
                unknown_replies[sig] = unknown_replies.get(sig, 0) + 1
                if unknown_replies[sig] >= 3:
                    # 模型反复输出同样缺 tool 的回复，继续提示只会空转耗预算
                    return {
                        "status": GenerationStatus.FAILED,
                        "error_category": ErrorCategory.MODEL,
                        "message": "模型连续 3 次未给出有效工具名或完成内容（finish），已终止",
                    }
                messages.append({"role": "assistant", "content": reply})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"工具名「{tool or '（空）'}」不可用。只能用下面清单里的工具：\n"
                            + "、".join(sorted(known_tools))
                            + "\n请只输出 JSON 对象：探索阶段用 "
                            '{"thought": "查看页面结构", "tool": "browser_snapshot", "args": {}}；'
                            '完成阶段用 {"thought": "...", "tool": "finish", "args": {"script": "...", "pages": [...]}}。'
                        ),
                    }
                )
                continue

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
                raw_script = str(args.get("script") or "")
                pages_payload = args.get("pages")
                patch_payload = args.get("patch") or args.get("patches")

                # 两阶段输出第一步：只提交资产（pages），回灌后再单独出 case.py，
                # 避免一次 JSON 同时塞资产与脚本被输出上限截断。
                if (
                    not raw_script.strip()
                    and isinstance(pages_payload, list)
                    and pages_payload
                    and not patch_payload
                    and not last_source
                ):
                    # 资产阶段本身也计入轮次，防止模型反复只交 pages 空转
                    static_rounds += 1
                    if static_rounds > MAX_STATIC_ROUNDS:
                        return {
                            "status": GenerationStatus.FAILED,
                            "error_category": ErrorCategory.SCRIPT,
                            "message": "模型反复提交资产而不输出脚本，已终止",
                        }
                    if self._staged_pages is not None:
                        messages.append({"role": "assistant", "content": reply})
                        messages.append(
                            {
                                "role": "user",
                                "content": (
                                    "资产已经暂存好了。请直接输出 case.py 脚本："
                                    '{"thought": "脚本已就绪", "tool": "finish", "args": {"script": "完整 Python 源码"}}。'
                                ),
                            }
                        )
                        continue
                    pages_problem, staged = stage_pages(
                        int(self.case.project_id), int(self.case.id), pages_payload
                    )
                    if pages_problem:
                        self._write_log({"type": "pages_invalid", "message": pages_problem})
                        if static_rounds > MAX_STATIC_ROUNDS:
                            discard_pages(staged)
                            return {
                                "status": GenerationStatus.FAILED,
                                "error_category": ErrorCategory.SCRIPT,
                                "message": f"资产写入失败：{pages_problem}",
                            }
                        messages.append({"role": "assistant", "content": reply})
                        messages.append(
                            {
                                "role": "user",
                                "content": f"资产未通过校验：{pages_problem}\n请修正后只提交 pages 数组。",
                            }
                        )
                        continue
                    self._staged_pages = staged
                    self._write_log({"type": "pages_staged", "count": len(pages_payload)})
                    messages.append({"role": "assistant", "content": reply})
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "【资产已接受】系统已校验并暂存 pages/common 文件。"
                                "现在不要再探索，只输出 case.py 脚本："
                                '{"thought": "脚本已就绪", "tool": "finish", "args": {"script": "完整 Python 源码"}}。'
                                "脚本可直接 import 刚提交的资产。"
                            ),
                        }
                    )
                    continue

                # 首跑失败后优先走最小补丁：只回 find/replace，应用失败再退回整份重写
                if patch_payload:
                    if not last_source:
                        messages.append({"role": "assistant", "content": reply})
                        messages.append(
                            {
                                "role": "user",
                                "content": (
                                    "当前还没有可打补丁的脚本版本，请直接输出完整 finish JSON："
                                    '{"tool": "finish", "args": {"script": "完整脚本"}}。'
                                ),
                            }
                        )
                        continue
                    source, patch_problem = _apply_patches(last_source, patch_payload)
                    if patch_problem:
                        static_rounds += 1
                        self.fix_rounds += 1
                        self._write_log({"type": "patch_invalid", "message": patch_problem})
                        if static_rounds > MAX_STATIC_ROUNDS:
                            return {
                                "status": GenerationStatus.FAILED,
                                "error_category": ErrorCategory.SCRIPT,
                                "message": f"补丁无法应用到脚本：{patch_problem}",
                            }
                        messages.append({"role": "assistant", "content": reply})
                        messages.append(
                            {
                                "role": "user",
                                "content": (
                                    f"补丁未应用：{patch_problem}\n"
                                    "请重新给出在脚本中唯一命中的 find 片段；"
                                    "若改动无法用补丁表达，直接输出完整 script。"
                                ),
                            }
                        )
                        continue
                    self.fix_mode = "patch"
                    self._write_log({"type": "patch_applied", "count": len(patch_payload)})
                else:
                    source = _clean_script(raw_script)
                    if self.fix_rounds:
                        self.fix_mode = "rewrite"

                problem = _check_script(source)
                if not problem:
                    problem = _compile(source)
                # 生成期按实测控件结构要求脚本使用 params fixture（修复期沿用既有参数，不重提取）
                param_schema = (
                    _inventory_schema(inventory, _case_text(self.case))
                    if (not is_fix and inventory)
                    else []
                )
                param_values = {item["name"]: item.get("default") for item in param_schema}
                if not problem and not is_fix:
                    problem = _check_params(source, param_schema)
                if problem:
                    static_rounds += 1
                    self.fix_rounds += 1
                    self._write_log({"type": "script_invalid", "message": problem})
                    if static_rounds > MAX_STATIC_ROUNDS:
                        return {
                            "status": GenerationStatus.FAILED,
                            "error_category": ErrorCategory.SCRIPT,
                            "message": f"模型产出脚本不可用：{problem}",
                        }
                    messages.append({"role": "assistant", "content": reply})
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                f"脚本未通过校验：{problem}\n"
                                "请优先输出最小补丁"
                                '{"tool": "finish", "args": {"patch": [{"find": "唯一命中的原文", "replace": "改后代码"}]}}；'
                                "补丁无法表达时才输出完整 script。"
                            ),
                        }
                    )
                    continue

                pages_problem, staged = stage_pages(
                    int(self.case.project_id),
                    int(self.case.id),
                    pages_payload,
                    reuse_staging=self._staged_pages is not None,
                )
                if pages_problem:
                    static_rounds += 1
                    self._write_log({"type": "pages_invalid", "message": pages_problem})
                    if static_rounds > MAX_STATIC_ROUNDS:
                        discard_pages(staged)
                        return {
                            "status": GenerationStatus.FAILED,
                            "error_category": ErrorCategory.SCRIPT,
                            "message": f"资产写入失败：{pages_problem}",
                        }
                    messages.append({"role": "assistant", "content": reply})
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                f"资产未通过校验：{pages_problem}\n"
                                "请修正后重新输出完整 finish JSON（script + pages）。"
                            ),
                        }
                    )
                    continue
                if staged is not None:
                    self._staged_pages = staged
                    self._write_log(
                        {"type": "pages_staged", "count": len(pages_payload or [])}
                    )

                last_source = source
                concurrency.set_progress(self.case_id, "首跑验证", "本地执行脚本验证")
                # 首跑用暂存资产，通过后才并入正式目录；同时注入待固化的参数默认值
                result = self._validate(
                    source,
                    auth,
                    pages_root=self._staged_pages,
                    params_schema=param_schema,
                    params_values=param_values,
                )
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
                    return self._solidify(
                        source,
                        ok=True,
                        params=None if is_fix else param_values,
                        schema=None if is_fix else param_schema,
                    )

                rounds += 1
                self.fix_rounds += 1
                failure_text = result.get("error_message") or ""
                if not self.first_failure:
                    self.first_failure = failure_text
                if rounds > MAX_FIX_ROUNDS:
                    discard_pages(self._staged_pages)
                    self._staged_pages = None
                    # 失败脚本不落正式目录，避免留下不可执行的半成品；
                    # 修复场景保留失败版本供人工查看。
                    if is_fix:
                        self._solidify(source, ok=False)
                    return {
                        "status": GenerationStatus.FAILED,
                        "error_category": result.get("error_category") or ErrorCategory.SCRIPT,
                        "message": "脚本首跑未通过：" + (result.get("error_message") or "未知错误"),
                        "script_saved": bool(is_fix),
                    }
                code_error = any(
                    k in failure_text
                    for k in (
                        "TypeError",
                        "ImportError",
                        "ModuleNotFoundError",
                        "NameError",
                        "AttributeError",
                        "not subscriptable",
                        "unexpected keyword",
                    )
                )
                messages.append({"role": "assistant", "content": reply})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "脚本已写入但本地首跑失败。"
                            + (
                                "这是纯代码/API 用法错误，不需要重新探索页面：直接按报错打补丁。\n"
                                if code_error
                                else "可以先回看快照确认真实按钮文案与字段，再打补丁。\n"
                            )
                            + "请优先输出最小补丁"
                            '{"tool": "finish", "args": {"patch": [{"find": "脚本中唯一命中的原文", "replace": "改后代码"}]}}；'
                            "补丁无法表达时才输出完整 script。\n"
                            "提示：按钮文案必须与快照里实际出现的文本一致（用例写「保存」，界面可能是「确定」）；"
                            "element(s) not found 多半是可访问名带图标字符，去掉 exact=True 改用子串匹配；"
                            "get_by_label 超时说明 label 未关联 input；get_by_role(\"textbox\") 序号错位或命中 disabled 密码框时，"
                            "先用 browser_evaluate 枚举 [role=dialog] input 的 type/placeholder/disabled，再按 placeholder 等属性定位；"
                            "strict mode violation 是文案前缀撞车，按钮改用 exact=True；"
                            "common 函数返回 Locator 时不要下标访问，用 .nth(i)。\n"
                            f"失败分类：{result.get('error_category')}\n"
                            f"失败信息：\n{failure_text[:4000]}"
                        ),
                    }
                )
                continue

            # 工具调用
            self.tool_calls += 1
            self.model_calls += 1
            concurrency.set_progress(
                self.case_id, "浏览器探索", f"{tool}（第 {self.tool_calls} 次）"
            )
            if tool in ("browser_snapshot", "browser_find", "browser_evaluate"):
                # 模型若把结果写文件，就看不到内容；强制返回文本
                args.pop("filename", None)
            # 模型常把 element（人类可读描述）或 Playwright 表达式当选择器传，缺 target 会被 MCP 拒绝
            invalid_target = ""
            if tool in (
                "browser_click",
                "browser_type",
                "browser_hover",
                "browser_select_option",
                "browser_press_key",
            ) and not str(args.get("target") or "").strip():
                for k in ("element", "selector", "ref", "name"):
                    v = args.get(k)
                    if not (isinstance(v, str) and v.strip()):
                        continue
                    v = v.strip()
                    if "get_by_" in v or "(" in v:
                        invalid_target = v
                        break
                    args = {**args, "target": v}
                    break
            if invalid_target:
                # 表达式不是 MCP 的 target，直接纠正，不浪费一次浏览器调用
                self.tool_calls += 1
                self.model_calls += 1
                if self.model_calls > MAX_MODEL_CALLS:
                    return {
                        "status": GenerationStatus.FAILED,
                        "error_category": ErrorCategory.MODEL,
                        "message": f"探索预算用尽（{MAX_MODEL_CALLS} 次）仍未给出合法 target，已终止",
                    }
                self._write_log({"type": "bad_target", "tool": tool, "value": invalid_target})
                bad_targets[invalid_target] = bad_targets.get(invalid_target, 0) + 1
                if bad_targets[invalid_target] >= 3:
                    return {
                        "status": GenerationStatus.FAILED,
                        "error_category": ErrorCategory.MODEL,
                        "message": (
                            f"模型反复使用同一 Playwright 表达式作为 target（{invalid_target}），"
                            "已终止以免继续消耗配额"
                        ),
                    }
                messages.append({"role": "assistant", "content": reply})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f'target 收到了 Playwright 表达式「{invalid_target}」，MCP 不接受这种写法。'
                            "请直接看最近一次快照，把 target 写成快照里的 ref（形如 e125），"
                            "或能唯一定位的标准 CSS（如 [role=dialog] input）；"
                            "脚本里才用 page.get_by_role(...)，探索阶段必须用 ref。"
                        ),
                    }
                )
                continue
            # 实测：弹窗内按 Escape 会把整个 dialog 一起关掉。模型据此误判「弹窗已关闭」，
            # 于是重复点「新增」，既空转又丢弃已填数据。直接拦截并给出替代做法。
            if (
                tool == "browser_press_key"
                and str(args.get("key") or "").strip().lower() == "escape"
                and inventory
            ):
                self.tool_calls += 1
                self.model_calls += 1
                blocked_closes += 1
                self._write_log({"type": "blocked_escape", "count": blocked_closes})
                messages.append({"role": "assistant", "content": reply})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "【拦截】弹窗内按 Escape 会关闭整个新增弹窗（实测行为），不要用它收起下拉。"
                            "要收起下拉就再次点击同一个 combobox；要看当前状态用 browser_snapshot。"
                        ),
                    }
                )
                if blocked_closes >= 3:
                    return {
                        "status": GenerationStatus.FAILED,
                        "error_category": ErrorCategory.MODEL,
                        "message": "模型反复尝试用 Escape 关闭弹窗（会丢失已填数据），已终止",
                    }
                continue
            # ref 真实性校验：快照被截断时模型会凭记忆臆造 e125 之类的 ref，
            # 不拦的话每次都要等浏览器报错、模型再猜，几轮就把预算烧光。
            ref_match = re.fullmatch(
                r"(?:ref=)?(e\d+)", str(args.get("target") or "").strip()
            )
            if ref_match and last_refs and ref_match.group(1) not in last_refs:
                ref = ref_match.group(1)
                self.tool_calls += 1
                self.model_calls += 1
                if self.model_calls > MAX_MODEL_CALLS:
                    return {
                        "status": GenerationStatus.FAILED,
                        "error_category": ErrorCategory.MODEL,
                        "message": f"探索预算用尽（{MAX_MODEL_CALLS} 次）仍未给出合法 ref，已终止",
                    }
                bad_refs[ref] = bad_refs.get(ref, 0) + 1
                self._write_log({"type": "bad_ref", "tool": tool, "ref": ref})
                if bad_refs[ref] >= 3:
                    return {
                        "status": GenerationStatus.FAILED,
                        "error_category": ErrorCategory.MODEL,
                        "message": (
                            f"模型反复使用快照中不存在的 ref（{ref}），"
                            "已终止以免继续消耗配额"
                        ),
                    }
                messages.append({"role": "assistant", "content": reply})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"ref「{ref}」不在最新一次快照里（不存在或已过期）。不要猜 ref："
                            '先用 browser_snapshot 重新取快照，或用 browser_find(text="目标按钮文案") '
                            "搜到真实 ref 再操作。"
                        ),
                    }
                )
                continue
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
            # 大快照会被 MCP 写成 .yml 只回链接，必须读回内容，否则模型看不到页面就会反复导航
            linked = "[Snapshot](" in (observation or "")
            if not is_error:
                observation = _inline_snapshot_links(observation)
                # 成功交互一次说明已拿到可用定位：凑够 2 个定位 + 路由即可判定三件套齐
                if tool in ("browser_click", "browser_type", "browser_select_option"):
                    locators_seen += 1
            blank = _snapshot_empty(observation) or "（快照为空：页面可能还没渲染）" in observation
            # 快照为空（SPA 还没渲染完）时直接重试，别把空快照喂给模型让它瞎猜 ref
            if not is_error and blank and (tool == "browser_snapshot" or linked):
                for _ in range(2):
                    time.sleep(1.5)
                    self.tool_calls += 1
                    retry, retry_error = client.call_tool("browser_snapshot", {})
                    if retry_error:
                        continue
                    retry = _inline_snapshot_links(retry)
                    if retry and not _snapshot_empty(retry):
                        observation = retry
                        break
            if (
                not is_error
                and tool in ("browser_navigate", "browser_snapshot")
                and _snapshot_empty(observation)
            ):
                observation += (
                    "\n\n（当前页面快照为空：页面未渲染或地址不对。请改用用例步骤里的真实页面路由"
                    "（base 后面带 #/xxx，例如 /manage#/usm/users），不要反复刷新同一个地址。）"
                )
            # ref 过期/参数缺失时模型常原地反复重试：直接补一张新快照回灌，省掉一轮无效调用
            low = (observation or "").lower()
            if is_error and (
                "not found in the current page snapshot" in low
                or "invalid arguments" in low
                or "expected string" in low
            ):
                try:
                    self.tool_calls += 1
                    snap, _ = client.call_tool("browser_snapshot", {})
                    if snap:
                        observation = (
                            f"{observation}\n\n（已自动重新获取当前页面快照。browser_click/browser_type 的 target "
                            "必须是下面快照里的 ref（如 e125），element 只是人类可读描述、不是选择器）\n"
                            f"{snap}"
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
            limit = SNAP_LIMIT if "```yaml" in (observation or "") else OBS_LIMIT
            messages.append(
                {
                    "role": "user",
                    "content": f"Observation（工具 {tool}{'，返回错误' if is_error else ''}）：\n{_truncate(observation, limit)}",
                }
            )
            refs_now = set(REF_RE.findall(observation or ""))
            if refs_now:
                last_refs = refs_now
            # 弹窗出现时用真实 DOM 自动枚举可编辑控件：模型不必自己逐个摸底，
            # 参数完整性也由系统按实测清单校验，而不是靠模型自觉。
            # 注意弹窗常在 browser_click（点「新增」）后立刻出现，该次观察并非 browser_snapshot，
            # 因此不能只对 snapshot/find 触发，否则错过最佳时机——模型只能自己点下拉读选项，
            # 而按 Escape 收起下拉会把整个弹窗关掉（实测），进而误判为要重新点「新增」并空转。
            if (
                not is_fix
                and not is_error
                and ("dialog" in low or "combobox" in low)
                and len(inventory) < 40
                and inventory_probes < 3
            ):
                inventory_probes += 1
                items, sig = _dump_controls(client)
                # 没枚举到控件（弹窗还没出现）不占用探测次数，等弹窗真正出现时再枚举
                if not items:
                    inventory_probes -= 1
                elif sig and sig != inventory_sig:
                    # 换了一个弹窗（如误点导入弹窗后又打开新增弹窗）：旧清单整体作废，
                    # 否则导入弹窗里那 1 个控件会污染参数完整性校验
                    inventory.clear()
                    inventory_sig = sig
                    inventory_notices = 0
                if not items and not inventory_empty_logged and "dialog" in low:
                    inventory_empty_logged = True
                    self._write_log(
                        {
                            "type": "controls_empty",
                            "tool": tool,
                            "has_dialog_text": "dialog" in low,
                        }
                    )
                if items:
                    push_facts("（弹窗）")
                if items and _merge_inventory(inventory, items) and inventory_notices < 3:
                    inventory_notices += 1
                    self._write_log({"type": "controls", "items": inventory})
                    param_schema = _inventory_schema(inventory, _case_text(self.case))
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "【自动枚举控件清单】系统已在弹窗内实测以下可编辑控件，"
                                "脚本里必须逐个覆盖这些控件（下拉用真实可选值，"
                                "勾选项的初始状态以实测为准）：\n"
                                + _format_inventory(inventory)
                                + "\n\n【参数结构】系统按实测控件与用例步骤提取了参数："
                                "与步骤相关的控件是可编辑参数，其余控件由系统自动填充"
                                "（必填项生成占位值、非必填留空）。测试函数必须声明 params fixture："
                                "def test_xxx(page, params)，控件的业务取值一律写成 params[\"参数名\"]，"
                                "禁止写死；参数名必须原样使用：\n"
                                + _format_params(param_schema)
                                + "\nunique=true 的参数由运行器自动追加运行时间后缀，不要自己再拼时间戳。"
                                "清单之外的控件不要凭空编造。"
                                "下拉的真实可选值已由系统读好（面板未展开时也能读到），"
                                "不要再自己点开下拉逐个读；弹窗内严禁按 Escape（实测会关闭整个弹窗）。"
                            ),
                        }
                    )
            # 会改页面的工具+参数反复调用且页面无变化（中间夹 find/snapshot 也算）都会烧掉预算：
            # 只统计 MUTATING_TOOLS，用最近 12 次做滑动窗口计数，第 2 次提醒，第 3 次直接终止
            sig = f"{tool}|{json.dumps(args, ensure_ascii=False, sort_keys=True)}"
            obs_head = TIMESTAMP_RE.sub("", (observation or "")[:400])
            if tool in MUTATING_TOOLS:
                recent_calls.append((sig, obs_head))
            if len(recent_calls) > 12:
                recent_calls.pop(0)
            same = sum(1 for item in recent_calls if item == (sig, obs_head))
            if same >= 2:
                # 重复点击「新增」这类动作，多半是模型误判弹窗已关闭。系统已实测到弹窗内控件，
                # 直接告诉它弹窗还开着，比让它再点第三次更省配额。
                if inventory and tool == "browser_click":
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                f"【弹窗仍然打开】系统实测弹窗内仍有 {len(inventory)} 个可编辑控件，"
                                "说明「新增」早已生效，不要再点它。请在弹窗内继续操作（browser_type 填字段），"
                                "或直接 finish 输出脚本。"
                            ),
                        }
                    )
                else:
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "这个调用刚才已经做过且结果相同，不要再重复。请先 browser_snapshot 看当前页面，"
                                "target 只接受快照里的 ref（如 e125）或标准 CSS，element 只是描述不是选择器；"
                                "如果是表单校验失败，就地修改该字段的值，不要关闭重开弹窗。"
                            ),
                        }
                    )
                if same >= 4:
                    return {
                        "status": GenerationStatus.FAILED,
                        "error_category": ErrorCategory.MODEL,
                        "message": f"同一工具参数已重复 {same} 次且页面无变化（{tool}），已终止以免继续消耗配额",
                    }
            if (
                not finish_nudged
                and not is_fix
                and locators_seen >= 2
                and self.tool_calls >= MIN_EXPLORE_CALLS
            ):
                finish_nudged = True
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "路由、定位、断言点已齐（已确认目标页面、真实控件与预期结果）。"
                            "请立即 finish 输出脚本，不要再为二次确认反复快照。"
                        ),
                    }
                )

    # ===== 落盘 =====

    def _case_view(self, schema: list[dict] | None, values: dict | None):
        """构造带参数取值的只读用例视图，供首跑注入 params.json。

        首跑时参数还没固化到数据库，用视图代替 ORM 对象；runner 只读这几个字段。
        """
        return SimpleNamespace(
            id=int(self.case.id),
            project_id=int(self.case.project_id),
            site=getattr(self.case, "site", "") or "",
            title=getattr(self.case, "title", "") or "",
            params_schema_json=list(schema or []),
            params_json=dict(values or {}),
        )

    def _validate(
        self,
        source: str,
        auth,
        pages_root: Path | None = None,
        params_schema: list[dict] | None = None,
        params_values: dict | None = None,
    ) -> dict:
        project_id = int(self.case.project_id)
        case_dir = paths.case_dir(project_id, int(self.case.id))
        case_dir.mkdir(parents=True, exist_ok=True)
        tmp = case_dir / "case_candidate.py"
        tmp.write_text(source, encoding="utf-8")
        try:
            return run_script(
                self._case_view(params_schema, params_values),
                self.env,
                script_path=tmp,
                run_dir=paths.new_run_dir(project_id, int(self.case.id)) / "validate",
                auth=auth,
                pages_root=pages_root if pages_root is not None else self._staged_pages,
            )
        except EnvMissingError as e:
            return {"run_status": "error", "error_category": ErrorCategory.ENV, "error_message": str(e)}
        except Exception as e:
            return {
                "run_status": "error",
                "error_category": ErrorCategory.SCRIPT,
                "error_message": f"{type(e).__name__}: {e}",
            }

    def _solidify(
        self,
        source: str,
        ok: bool,
        params: dict | None = None,
        schema: list[dict] | None = None,
    ) -> dict:
        """写入正式脚本并更新用例状态（版本自增，旧版归档）。

        schema 非 None 表示本次生成重新提取了参数结构：同步落库参数默认值，
        前端参数面板即可展示/编辑，执行时由 runner 注入 params.json。
        schema 为 None（修复场景）时保留已有参数不变。
        """
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
        if schema is not None:
            # 参数结构随脚本一起固化：空列表表示本次未观察到弹窗控件（清掉旧参数）
            fields.update(
                params_schema_json=list(schema),
                params_json=dict(params or {}),
                params_updated_at=_now(),
            )
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
        metrics = {
            "tool_calls": self.tool_calls,
            "model": self.model_name,
            "log_rel_path": log_rel,
            "corpus_chars": self.corpus_chars,
            "prompt_chars": self.prompt_chars,
            "completion_chars": self.completion_chars,
            "fix_rounds": self.fix_rounds,
        }
        if status == GenerationStatus.SUCCESS:
            concurrency.set_progress(self.case_id, "完成", "脚本已固化")
            self.db.finish_generation(
                self.gen_id,
                status=GenerationStatus.SUCCESS,
                **metrics,
            )
            # 失败后修复通过：把「踩的坑 + 解决方案」沉淀成反面样本（成功样本）
            if self.first_failure:
                solution = {
                    "patch": "按报错输出最小补丁（find/replace）并在本地应用，补丁不唯一时回退整份重写",
                    "rewrite": "按首次失败信息重写整份脚本（复看真实快照与控件清单后修正定位/断言）",
                }.get(self.fix_mode, "按首次失败信息修正脚本")
                lessons.record_solution(
                    self.db, self.case, ErrorCategory.SCRIPT, self.first_failure, solution
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
            **metrics,
        )
        # 失败日志沉淀为反面样本，后续同类用例生成时注入提示词
        lessons.record_failure(self.db, self.case, category, message)


def start_job(case_id: int, kind: str) -> None:
    """在后台线程启动生成/修复（调用方需已通过 acquire 抢到项目锁）。"""
    job = GenerationJob(case_id, kind)
    threading.Thread(target=job.run, daemon=True, name=f"ui-gen-{case_id}").start()
