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
import pprint
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
from insight_aitest.modules.ui.backend.automation import flows as flowlib
from insight_aitest.modules.ui.backend.automation.deps import get_automation_db
from insight_aitest.modules.ui.backend.automation.env_service import prepare_auth, site_url
from insight_aitest.modules.ui.backend.automation.models import (
    CaseStatus,
    ErrorCategory,
    GenerationKind,
    GenerationStatus,
    UiFlowStatus,
)
from insight_aitest.modules.ui.backend.automation.mcp_client import MCPError, PlaywrightMCPClient
from insight_aitest.modules.ui.backend.automation.runner import EnvMissingError, run_script

logger = logging.getLogger(__name__)

MAX_TOOL_CALLS = 60
MAX_SECONDS = 12 * 60
MAX_FIX_ROUNDS = 3
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
    const item = { label: labelOf(el), type, value, options, disabled: !!el.disabled };
    if (tickable) item.checked = !!el.checked;
    items.push(item);
  });
  return { sig: (root.textContent || '').trim().slice(0, 60), items };
}"""

SYSTEM_PROMPT = """你是资深 Playwright 测试工程师。你的任务是通过浏览器工具真实探索被测系统，然后写出可直接运行的 Python pytest 自动化脚本。

交互协议（严格执行）：
- 每次只输出一个 JSON 对象，不要输出 Markdown 代码块、不要输出多余文字。
- 探索阶段：{"thought": "查看当前页面结构", "tool": "browser_snapshot", "args": {}}
  （tool 必须是下面「可用工具」清单里的真实工具名；不要把示例文字原样抄回来）
- 完成阶段：{"thought": "脚本已就绪", "tool": "finish", "args": {"script": "完整 Python 源码"}}

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
    - 只允许 import：playwright、pytest、pages.*、common.*、flows.*、env，以及 time/json/re/tempfile/datetime/random/string/uuid/typing
    - 禁止 import os/sys/subprocess/pathlib/shutil/requests 等，禁止读取配置文件与环境凭证
    - 禁止调用 open/eval/exec/compile/getattr/setattr
    - 上传样例文件用 data_path("文件名")；产物落盘用 artifact_path("文件名")
30. 本次必须同时产出「流程脚本」与「用例脚本」两段代码（同目录同流程的用例要复用同一套流程）：
    - 流程脚本：把完整页面操作流程沉淀成 run(page, params)：跳转、填表、点击保存都写在这里，
      数据一律取自 params["name"]，禁止写死任何业务数据。
      流程 run() 末尾必须包含对本流程预期结果的断言，断言值一律取自 params，例如
      expect(page.get_by_role("row").filter(has_text=params["username"])).to_be_visible()；
      复用时同目录用例只换参数取值、不再写断言，所有校验都由流程承担。
      流程元数据只写在 flow 的 key/title/route/keywords/params 字段（系统会自动合成 FLOW），
      source 里不需要再写 FLOW 字面量（写了也以源码内容为准）。
      其中 params 每项为 {"name","label","type","required","default","example","desc","unique","options"}，
      type 取 str/int/bool/select；会重复冲突的数据（用户名/邮箱等）必须 unique=true。
      **参数必须覆盖完整**：流程里出现的每一个可编辑控件都要有一个参数，run() 里用 params 控制其取值：
      - 可输入控件：textbox、密码框、PIN、textarea、日期/时间输入框；
      - 可勾选控件：checkbox/radio/开关（如「使用默认密码」「登录IP限制」「系统管理员」），type=bool；
      - 下拉/选择控件：无输入框的纯下拉（如「部门」「用户等级」「有效期」）type=select，
        **真实选项由系统在弹窗出现时自动枚举并随「自动枚举控件清单」下发**（面板即使未展开
        也能从 DOM 读到），直接采用清单里的可选值写入 options（一个都不能少），
        default 填界面当前显示值；不要自己点开下拉逐个读，更不要按 Escape 收起下拉。
        既可输入又能选的下拉用 type=str，并在 desc 里列出可选值；
      - 被禁用不可编辑的输入框本身可不建参数，但控制它启用的开关必须建参数；
      - 纯展示文本与按钮不建参数。
      bool 参数 default 必须与界面初始勾选状态一致。finish 之前逐个对照快照与下拉选项核对，
      漏一个控件、少一个下拉选项都视为不合格。
    - 用例脚本：只 import 流程的 run 并传本用例参数，再补本用例独有的断言：
        from flows.<流程目录> import run
        def test_xxx(page, params):
            run(page, params)
            expect(page.get_by_role("row").filter(has_text=params["username"])).to_be_visible()
      导入路径不确定时写成 from flows.f_{目录id}.{key}_v1 import run（提示里会给出目录 id）。
      用例脚本里禁止再写页面操作，禁止出现参数值字面量（断言必须用 params["name"]）。
      参数 fixture 由运行脚手架注入（function 级 params fixture），直接用它即可。
      流程脚本源码只能放在 flow.source；不要把流程脚本（含 def run）写进 pages/ 或 common/，
      也不能 `from pages.xxx import run`。
    - finish 的 args 结构：
      {"script": "用例脚本", "flow": {"key","title","route","keywords","params","source"},
       "params": {"name": "本用例取值"}, "pages": [...]}
    - 按钮/文案以浏览器快照里真实出现的文本为准（用例步骤写「保存」时，界面按钮可能叫「确定」），
      不要照抄用例描述里的字面文案。
31. 流程 key 规则：英文小写字母开头，只含小写字母/数字/下划线，≤32 字符（如 create_user）。
32. 本用例参数取值（args.params）必须覆盖流程 params 的**全部** name（单选/勾选项用 true/false，
    下拉项取 options 中的一个），不允许只给必填项就省略其余项。
33. 表单校验失败（控制台报错或字段下方出现红色提示）时，必须**在当前弹窗内直接修改该字段**，
    不要点取消/关闭再重新打开弹窗；提示里给出格式限制（如「6-32位字符，仅支持大小写字母、数字、中文、邮箱」）
    时，换成符合该限制的唯一值（例如 user + 时间戳，不要带下划线/符号），严禁重复提交同一非法值。
    同一步骤连续 2 次失败说明策略错了，换定位方式或换数据，不要原地重试。
34. 工具调用有硬预算（60 次，含自动补快照），用尽即判定本次生成失败。
    操作到「预期结果」并拿到关键选择器后就应立即 finish，不要为了再确认一遍而反复快照。
35. ref 只能来自最近一次 browser_snapshot / browser_find 的输出。快照被截断看不到目标按钮时，
    用 browser_find(text="新增") 或再 browser_snapshot 取真实 ref，**禁止猜测或凭记忆写 e125
    这类 ref**（不存在的 ref 会被直接拒绝，反复猜会耗尽预算）。
36. 弹窗表单的 label 常常只是普通文本、没有 for/id 关联，get_by_label() 会必然超时。下拉控件
    通常是自定义 combobox（div[role=combobox]，不是原生 select，也没有 ant-select 类名）：
    按顺序用 dialog.get_by_role('combobox').nth(0/1/2…) 定位并点击，再点
    page.get_by_role('option', name=选项文案) 选择。字段控件也优先按 role + 顺序定位
    （input 用 dialog.get_by_role('textbox').nth(i)、勾选用 get_by_role('checkbox', name=文案)）。
37. 页面对象是普通类：必须 `UsersPage(page).open(dept=...)` 这样实例化后调用（方法签名里
    没有 self）；不要写成 `UsersPage.open(page, ...)`。pages/ 下已存在的文件禁止覆盖，
    提交会被拒绝；需要新能力时新建文件，或直接复用已有方法签名。
"""

# 复用已有流程时的提示词：不探索页面、不调用浏览器工具，一次产出用例脚本 + 参数取值
REUSE_SYSTEM_PROMPT = """你是资深 Playwright 测试工程师。当前用例所在目录已有可复用的流程脚本，
你的任务不是重新探索页面，而是为该用例生成「薄用例脚本 + 参数取值」。
交互协议：每次只输出一个 JSON 对象，不要输出 Markdown 代码块、不要输出多余文字。
完成阶段：{"thought": "脚本已就绪", "tool": "finish", "args": {"script": "用例脚本", "params": {"name": "取值"}}}

硬性要求：
1. 绝对不要调用任何浏览器工具，你也没有工具；直接输出 finish。
2. 用例脚本必须 from <给出的流程模块> import run，并在测试函数里调用 run(page, params)；
   本用例独有的断言写在 run 之后，断言值一律取自 params["name"]，禁止出现参数值字面量。
3. 只定义 def test_xxx(page, params) 函数，不要写 main、不要 launch 浏览器、禁止 async/await。
4. 禁止固定睡眠（page.wait_for_timeout / time.sleep）；断言只用 expect(...) 正向校验。
5. 只允许 import：playwright、pytest、pages.*、common.*、flows.*、env 与少量标准库；
   禁止 import os/sys/subprocess/pathlib/shutil/requests，禁止 open/eval/exec/compile/getattr/setattr。
6. args.params 必须覆盖流程 params 的**全部** name（含 bool 勾选项与 select 下拉项），
   不允许只给必填项；unique 参数给稳定基准值（运行器会自动追加时间后缀）。
7. 流程脚本已存在且被验证过，不要修改流程脚本本身，也不要提交 pages。
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
        if isinstance(obj.get("tool"), str) or "script" in obj or "flow" in obj:
            return obj
    # 没有一个像真实回复：说明整段 JSON 被截断（通常是输出长度打满），
    # 不要退化成脚本里的碎片对象，否则会被误判成「工具名无效」
    return None


CHAT_MAX_TOKENS = 8192


def _chat(llm, messages: list[dict], **kwargs) -> str:
    """统一模型调用：显式给足输出预算。

    finish 一轮要吐完整流程脚本 + 用例脚本，模型默认输出上限常把 JSON 截断成非法内容。
    """
    kwargs.setdefault("max_tokens", CHAT_MAX_TOKENS)
    try:
        return llm.chat(_trim_messages(messages), **kwargs)
    except Exception:
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
    "flows",
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


def _check_flow_source(source: str) -> tuple[str, dict | None]:
    """流程脚本静态校验：FLOW 字面量 + run(page, params) + 沙箱。"""
    import ast

    src = _clean_script(source)
    if not src.strip():
        return "流程脚本为空", None
    meta = flowlib.read_flow_meta(src)
    if meta is None:
        got = (src.strip().splitlines() or [""])[0][:120]
        try:
            ast.parse(src)
        except SyntaxError as e:
            return (
                f"流程脚本语法错误：{e.msg}（第 {e.lineno} 行）。"
                "常见原因是字符串里出现真实换行/未转义引号，请保证 source 是可直接编译的 Python 源码。"
                f"首行：{got}",
                None,
            )
        return (
            "flow.source 必须是完整流程脚本源码（模块级 FLOW = {...} + def run(page, params)），"
            f"不能是函数名或标题；流程脚本也不要放进 pages/。当前收到：{got}",
            None,
        )
    problem = flowlib.validate_flow_key(meta["key"])
    if problem:
        return problem, None
    if not meta["title"]:
        return "流程缺少 title（如「新增用户」）", None
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return f"流程脚本语法错误: {e.msg}", None
    run_fn = next(
        (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run"), None
    )
    if run_fn is None:
        return "流程脚本必须定义 run(page, params)", None
    if len(run_fn.args.args) < 2:
        return "流程入口必须是 run(page, params)（两个参数）", None
    problem = _check_sandbox(src, kind="流程脚本 ")
    if problem:
        return problem, None
    if "get_by_label(" in src:
        return (
            "流程脚本里用了 get_by_label()：被测表单的 label 往往没有与控件关联，这行必然超时。"
            "下拉改用 dialog.get_by_role('combobox').nth(n) 展开后点 get_by_role('option', "
            "name=选项文案)；输入框用 get_by_role('textbox').nth(i) 或 dialog.locator('input[type=...]').nth(i)。",
            None,
        )
    if re.search(r"\w+Page\.\w+\s*\(\s*page\b", src):
        return (
            "流程脚本把页面对象的实例方法当成静态方法调用了（XxxPage.method(page, ...)）。"
            "正确写法是 XxxPage(page).method(...)，页面对象构造时已经接收了 page。",
            None,
        )
    empty_options = [
        p["name"] for p in meta["params"] if p["type"] == "select" and not p["options"]
    ]
    if empty_options:
        return (
            "以下下拉参数缺少 options："
            + "、".join(empty_options)
            + "。纯下拉控件必须先用浏览器工具展开下拉、读取真实选项文本后写进 options，"
            "不能留空或凭空编造。",
            None,
        )
    unused = sorted({p["name"] for p in meta["params"]} - _used_params(tree))
    if unused:
        return (
            "以下流程参数已声明但没有在 run() 中使用："
            + "、".join(unused)
            + "。每个参数都必须在 run() 里真正驱动对应控件（params[\"name\"]），"
            "不能只用一部分；确实不需要的参数请删掉，不要为了凑数量声明。",
            None,
        )
    return "", meta


_FLOW_IMPORT_RE = re.compile(r"from\s+flows\.[A-Za-z0-9_.]*\s+import\s+run")


def _rewrite_flow_import(source: str, module: str) -> str:
    """把用例脚本里的 flows.* import 改写为实际模块路径。

    模型不知道真实的 ``f_<目录id>.<key>_v1`` 路径，常猜成 flows.f_usm；
    这里直接改写而不是报错重试，避免把生成轮次浪费在路径猜测上。
    """
    fixed, replaced = _FLOW_IMPORT_RE.subn(f"from {module} import run", source)
    return fixed if replaced else source


def _check_case_flow_source(source: str, module: str, schema: list) -> str:
    """复用例脚本校验：必须 import 流程 run、使用 params、且参数 key 在 schema 内。"""
    import ast

    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return f"用例脚本语法错误: {e.msg}"
    imported = False
    used: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "") == module:
            if any(alias.name == "run" for alias in node.names):
                imported = True
        elif isinstance(node, ast.Subscript):
            value = node.value
            if isinstance(value, ast.Name) and value.id == "params":
                key = node.slice
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    used.add(key.value)
    if not imported:
        return f"用例脚本必须 `from {module} import run`，页面操作全部收敛在流程脚本里"
    names = {p["name"] for p in flowlib.normalize_params(schema)}
    unknown = sorted(used - names)
    if unknown:
        return f"用例脚本引用了流程参数结构外的 key：{', '.join(unknown)}"
    # 流程复用约定：断言写在流程 run() 里，用例脚本只负责把 params 传给 run，
    # 因此用例侧不强制出现 params 下标访问。
    return _check_sandbox(source, kind="用例脚本 ")


def _case_template(case, module: str) -> str:
    """复用流程时的用例脚本模板：只有 import + run(page, params)，不含任何页面操作。"""
    title = str(getattr(case, "title", "") or "").strip().replace('"""', "'''")
    case_id = int(getattr(case, "id", 0) or 0)
    return (
        f"from {module} import run\n\n\n"
        f"def test_case_{case_id}(page, params):\n"
        f'    """{title}"""\n'
        "    run(page, params)\n"
    )


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


def doctor(env, need_mcp: bool = True) -> str:
    """环境自检，返回错误信息；空串表示通过。

    need_mcp=False 时（复用已有流程）不要求 Node/npx，因为不启动 playwright MCP。
    """
    if env is None:
        return "项目未配置环境，请先在「环境管理」中新增"
    if not (env.base_url or "").strip():
        return "环境未配置被测系统地址 base_url"

    from insight_aitest.platform.services.kb.deps import get_llm_config

    cfg = get_llm_config()
    if not cfg.llm_api_key:
        return "未配置 LLM API Key，无法生成脚本"
    if need_mcp and shutil.which("npx") is None:
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


def _real_flows_dir(project_id: int) -> Path:
    return paths.project_scripts_dir(project_id) / "flows"


def _prepare_staging(project_id: int, case_id: int) -> Path:
    """重建暂存目录：正式 common/pages/flows 的副本，首跑用它（已验证才并入正式目录）。"""
    staging = paths.staging_root(project_id, case_id)
    shutil.rmtree(staging, ignore_errors=True)
    for package in ASSET_DIRS:
        _copy_assets(_asset_root(project_id, package), staging / package)
    # 复用路径要在暂存目录里 import 已存在的流程，必须一并复制 flows/
    _copy_assets(_real_flows_dir(project_id), staging / "flows")
    return staging


def stage_pages(project_id: int, case_id: int, payload) -> tuple[str, Path | None]:
    """校验资产提交并写入生成期暂存目录，返回 (错误信息, 暂存根目录)。

    暂存目录是正式 common/ + pages/ 的副本，首跑用它，
    避免未验证的资产污染正式目录；通过后由 adopt_pages 并入。

    落位规则：
    - ``common/xxx.py``：项目级通用代码，允许覆盖，并入时备份旧版到 common/history/；
    - ``pages/xxx.py``：页面对象，只允许新增，避免一次生成破坏既有复用资产。
    """
    if not isinstance(payload, list) or not payload:
        return "", None
    staging = _prepare_staging(project_id, case_id)

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


def _ensure_flow_meta(source: str, payload: dict) -> str:
    """模型常把流程元数据只填在 flow.key/title/... 里，source 只写 run()。

    源码缺少模块级 ``FLOW`` 时用 payload 元数据补出合法字面量（追加在文件末尾，
    避免破坏可能存在的 __future__ 导入），保证流程文件可被 AST 读取与复用匹配。
    """
    if flowlib.read_flow_meta(source) is not None:
        return source
    meta = {
        "key": str(payload.get("key") or "").strip(),
        "title": str(payload.get("title") or "").strip(),
        "route": str(payload.get("route") or "").strip(),
        "keywords": [str(k).strip() for k in (payload.get("keywords") or []) if str(k).strip()],
        "params": flowlib.normalize_params(payload.get("params")),
    }
    if not meta["key"] or not meta["title"]:
        return source
    return source.rstrip() + "\n\n\nFLOW = " + pprint.pformat(meta, width=100, sort_dicts=False) + "\n"


def stage_flow(db, project_id: int, case_id: int, payload, case) -> tuple[str, Path | None, dict | None]:
    """校验并暂存新流程脚本（首跑通过后才由 adopt_flow 落正式目录 + 建库）。

    返回 (错误信息, 暂存根目录, 流程信息)。
    """
    if not isinstance(payload, dict) or not payload:
        return "", None, None
    folder_id = int(getattr(case, "kb_folder_id", None) or 0)
    source = _ensure_flow_meta(str(payload.get("source") or ""), payload)
    problem, meta = _check_flow_source(source)
    if problem:
        return problem, None, None
    key = meta["key"]
    # 同 key 重新生成（force_new_flow）走版本递增，而不是报冲突逼模型改名：
    # 否则同一目录会散落多个近似流程，参数结构也随之分裂。
    existing = db.get_flow_by_key(project_id, folder_id, key)
    version = int(existing.version or 1) + 1 if existing is not None else 1
    staging = paths.staging_root(project_id, case_id)
    # staging_root 自带 mkdir，exists() 恒为真；必须确认 common/pages 包已复制，
    # 否则暂存目录只有 flows，首跑会报 ModuleNotFoundError: No module named 'common'
    if not all((staging / pkg / "__init__.py").exists() for pkg in ASSET_DIRS):
        staging = _prepare_staging(project_id, case_id)
    target = staging / "flows" / f"f_{folder_id}" / f"{key}_v{version}.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    init = target.parent / "__init__.py"
    if not init.exists():
        init.write_text("# -*- coding: utf-8 -*-\n", encoding="utf-8")
    target.write_text(_clean_script(source), encoding="utf-8")
    info = {
        "meta": meta,
        "module": paths.flow_module(folder_id, key, version),
        "folder_id": folder_id,
        "version": version,
        "file": target,
    }
    return "", staging, info


def adopt_flow(db, project_id: int, info: dict | None) -> int | None:
    """首跑通过后把流程脚本写入正式 flows/ 目录并建库（文件只增不覆盖）。"""
    if not info:
        return None
    meta = info["meta"]
    folder_id = int(info["folder_id"])
    version = int(info.get("version") or 1)
    target = paths.flow_script(project_id, folder_id, meta["key"], version)
    source = info["file"].read_text(encoding="utf-8")
    if target.exists() and target.read_text(encoding="utf-8") != source:
        # 仅可能来自失败任务遗留的孤儿文件（库里无记录），覆盖即可
        logger.warning("流程脚本已存在且内容不同，按新版本内容覆盖：%s", target)
    target.write_text(source, encoding="utf-8")
    existing = db.get_flow_by_key(project_id, folder_id, meta["key"])
    if existing is not None:
        # 同 key 重新生成：更新原流程记录到新版本（旧版本脚本文件保留，可回溯）
        db.update_flow(
            int(existing.id),
            title=meta.get("title") or meta["key"],
            route=meta.get("route") or "",
            keywords=meta.get("keywords") or [],
            params_schema=meta.get("params") or [],
            module=info["module"],
            script_rel_path=paths.to_rel(target),
            version=version,
            status=UiFlowStatus.ACTIVE,
        )
        return int(existing.id)
    return flowlib.create_flow_record(
        db,
        project_id=project_id,
        folder_id=folder_id,
        meta=meta,
        module=info["module"],
        script_rel_path=paths.to_rel(target),
        version=version,
    )


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

    def __init__(
        self,
        case_id: int,
        kind: str,
        reuse_flow_id: int | None = None,
        force_new_flow: bool = False,
    ) -> None:
        self.case_id = case_id
        self.kind = kind
        self.reuse_flow_id = reuse_flow_id
        self.force_new_flow = force_new_flow
        self.db = get_automation_db()
        self.case = self.db.get_case(case_id)
        self.env = self.db.default_env(self.case.project_id) if self.case else None
        # 任务失败时恢复到进入前的状态（修复失败仍算已实现，首次生成失败回到未实现）
        self.prev_status = self.case.status if self.case else CaseStatus.NOT_IMPLEMENTED
        self.gen_id = 0
        self.started = time.time()
        self.tool_calls = 0
        self.model_name = ""
        self.flow = None
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

        # 复用判定在启动 MCP 之前完成：命中则完全跳过浏览器探索
        concurrency.set_progress(self.case_id, "匹配流程", "查找同目录可复用流程")
        flow, flow_error = self._resolve_flow(llm, is_fix)
        if flow_error:
            return {
                "status": GenerationStatus.FAILED,
                "error_category": ErrorCategory.CASE,
                "message": flow_error,
            }
        self.flow = flow

        concurrency.set_progress(self.case_id, "自检", "检查 Node/浏览器/模型配置")
        problem = doctor(self.env, need_mcp=flow is None)
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

        if flow is not None:
            return self._reuse_generate(flow, llm, auth, is_fix)

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

    # ===== 流程复用 =====

    def _resolve_flow(self, llm, is_fix: bool) -> tuple[object | None, str]:
        """确定本次生成复用的流程；返回 (flow, 错误信息)。"""
        case = self.case
        project_id = int(case.project_id)
        if self.reuse_flow_id is not None:
            flow = self.db.get_flow(int(self.reuse_flow_id))
            if flow is None or int(flow.project_id) != project_id:
                return None, "指定的复用流程不存在或不属于当前项目"
            if flow.status != UiFlowStatus.ACTIVE:
                return None, "指定的复用流程已归档，无法复用"
            return flow, ""
        if self.force_new_flow:
            return None, ""
        # 修复 & 已挂流程的用例：沿用原流程，不再匹配到别的流程
        if is_fix or case.flow_id:
            if case.flow_id:
                flow = self.db.get_flow(int(case.flow_id))
                if flow is not None and flow.status == UiFlowStatus.ACTIVE:
                    return flow, ""
            if is_fix:
                return None, ""
            # 原流程已归档/删除：继续按同目录匹配，匹配不到再新建

        candidates = flowlib.match_candidates(self.db, case)
        if not candidates:
            return None, ""
        best_flow, best_score, detail = candidates[0]
        if best_score >= flowlib.AUTO_THRESHOLD:
            self._write_log(
                {"type": "flow_auto_match", "flow_id": best_flow.id, "score": best_score, "detail": detail}
            )
            return best_flow, ""
        if best_score >= flowlib.GRAY_LOW:
            chosen = flowlib.classify_match(llm, case, candidates[:3])
            self._write_log(
                {
                    "type": "flow_classify",
                    "score": best_score,
                    "detail": detail,
                    "chosen": chosen.id if chosen is not None else None,
                }
            )
            return chosen, ""
        return None, ""

    def _reuse_generate(self, flow, llm, auth, is_fix: bool) -> dict:
        """复用已有流程：不启动 MCP、不探索页面，单次产出用例脚本 + 参数取值。"""
        case = self.case
        project_id = int(case.project_id)
        case_id = int(case.id)
        schema = flowlib.normalize_params(flow.params_schema)
        module = flow.module or paths.flow_module(flow.folder_id, flow.flow_key, flow.version)
        flow_path = paths.resolve_rel(flow.script_rel_path)
        if not flow_path.exists():
            return {
                "status": GenerationStatus.FAILED,
                "error_category": ErrorCategory.SCRIPT,
                "message": f"流程脚本文件不存在：{flow.script_rel_path}",
            }
        flow_source = flow_path.read_text(encoding="utf-8")
        concurrency.set_progress(
            self.case_id, "复用流程", f"复用「{flow.title}」，跳过浏览器探索"
        )
        self._write_log(
            {"type": "reuse_flow", "flow_id": flow.id, "module": module, "version": flow.version}
        )

        # 约定：复用=全部复用（流程脚本、页面对象、common 一并沿用），用例只靠参数取值区分，
        # 因此非修复场景完全不调用模型，直接套模板 + 参数首跑。
        if not is_fix:
            return self._reuse_parameterized(flow, module, schema, auth)

        site = getattr(case, "site", "") or ""
        site_label = "后台管理端" if site == "backend" else "前台用户端"
        parts = [
            f"任务：{'修复' if is_fix else '生成'}下面的用例脚本，直接复用已有流程，不要重新探索页面。",
            f"当前端：{site_label}",
            f"流程模块：{module}（用例脚本必须 `from {module} import run`，运行脚手架已注入 page 与 params fixture）",
            f"流程标题：{flow.title}\n流程路由：{flow.route or '（未记录）'}",
            "流程参数结构：\n" + json.dumps(schema, ensure_ascii=False, indent=2),
            f"本用例当前参数取值：\n{json.dumps(dict(case.params_json or {}), ensure_ascii=False)}",
            "流程脚本源码：\n```python\n" + flow_source + "\n```",
            "用例信息：\n" + _case_brief(case),
        ]
        if is_fix and case.last_error_message:
            parts.append(
                f"上次执行失败（{case.last_error_category or '未知'}）：\n{case.last_error_message[:4000]}"
            )
        if is_fix:
            current = paths.case_script(project_id, case_id)
            if current.exists():
                parts.append(
                    "当前用例脚本：\n```python\n" + current.read_text(encoding="utf-8") + "\n```"
                )
            parts.append("请先分析失败原因，再输出修复后的完整用例脚本。")

        messages = [
            {"role": "system", "content": REUSE_SYSTEM_PROMPT},
            {"role": "user", "content": "\n\n".join(parts)},
        ]

        rounds = 0
        bad_json = 0
        while True:
            if time.time() - self.started > MAX_SECONDS:
                return {
                    "status": GenerationStatus.FAILED,
                    "error_category": ErrorCategory.MODEL,
                    "message": "生成超时，已终止。可稍后重试",
                }
            concurrency.set_progress(self.case_id, "模型思考", "复用流程，生成用例脚本")
            try:
                reply = _chat(llm, messages, temperature=0.2)
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
                        "content": (
                            "输出不是合法 JSON（也可能是输出被长度上限截断了）。请只输出一个 JSON 对象，"
                            "不要任何解释段落、不要用 ``` 包裹、不要在 JSON 前后写文字；"
                            "字符串内部换行必须写成 \\n，双引号必须转义为 \\\"，"
                            "代码整体作为 script / flow.source 的字符串值。"
                            "如果内容太长，请删掉重复贴的已有公共代码，只输出本次真正新增/修改的部分。"
                            '只输出 {"thought": "...", "tool": "browser_snapshot" 或 "finish", "args": {...}}。'
                        ),
                    }
                )
                continue

            self._write_log({"type": "assistant", "content": reply})
            tool = str(parsed.get("tool") or "").strip()
            args = parsed.get("args") or {}
            if not isinstance(args, dict):
                args = {}
            if tool != "finish":
                messages.append({"role": "assistant", "content": reply})
                messages.append(
                    {
                        "role": "user",
                        "content": "当前没有浏览器工具可用，请不要输出工具调用，直接输出 finish JSON（script + params）。",
                    }
                )
                continue

            source = _clean_script(str(args.get("script") or ""))
            values = self._merge_values(schema, args.get("params"))
            problem = _check_script(source)
            if not problem:
                problem = _compile(source)
            if not problem:
                problem = _check_case_flow_source(source, module, schema)
            if not problem:
                missing = [
                    p["name"]
                    for p in schema
                    if p.get("required") and values.get(p["name"]) in (None, "")
                ]
                if missing:
                    problem = f"必填参数缺少取值：{', '.join(missing)}"
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
                        "content": (
                            f"用例脚本未通过校验：{problem}\n"
                            "请修正后重新输出完整 finish JSON（script + params）。"
                        ),
                    }
                )
                continue

            concurrency.set_progress(self.case_id, "首跑验证", "本地执行脚本验证")
            result = self._validate(
                source, auth, case_override=self._case_with_params(values, schema)
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
                return self._solidify(
                    source,
                    ok=True,
                    extra_fields={
                        "flow_id": flow.id,
                        "flow_version": int(flow.version or 1),
                        "params_json": values,
                        "params_schema_json": schema,
                        "params_updated_at": _now(),
                    },
                )
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
                        "用例脚本已写入但本地首跑失败。请分析失败信息，修正断言或参数取值后重新输出完整 finish JSON。\n"
                        f"失败分类：{result.get('error_category')}\n"
                        f"失败信息：\n{(result.get('error_message') or '')[:4000]}"
                    ),
                }
            )
            continue

    def _reuse_parameterized(self, flow, module: str, schema: list, auth) -> dict:
        """全部复用：不重新生成流程/页面对象/公共函数，用例脚本模板化，仅参数取值不同。"""
        raw = dict(getattr(self.case, "params_json", None) or {})
        values = self._merge_values(schema, raw)
        for item in schema:
            name = item["name"]
            if values.get(name) in ("", None):
                values[name] = item.get("example") or item.get("default") or ""
        missing = [
            p["name"]
            for p in schema
            if p.get("required") and values.get(p["name"]) in ("", None)
        ]
        if missing:
            return {
                "status": GenerationStatus.FAILED,
                "error_category": ErrorCategory.CASE,
                "message": "复用流程缺少必填参数取值："
                + "、".join(missing)
                + "，请在参数页补充后重新生成",
            }
        source = _case_template(self.case, module)
        problem = (
            _check_script(source)
            or _compile(source)
            or _check_case_flow_source(source, module, schema)
        )
        if problem:
            return {
                "status": GenerationStatus.FAILED,
                "error_category": ErrorCategory.SCRIPT,
                "message": f"复用用例脚本模板不可用：{problem}",
            }
        concurrency.set_progress(self.case_id, "首跑验证", "复用流程 + 参数取值，本地执行验证")
        result = self._validate(
            source, auth, case_override=self._case_with_params(values, schema)
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
            return self._solidify(
                source,
                ok=True,
                extra_fields={
                    "flow_id": flow.id,
                    "flow_version": int(flow.version or 1),
                    "params_json": values,
                    "params_schema_json": schema,
                    "params_updated_at": _now(),
                },
            )
        return {
            "status": GenerationStatus.FAILED,
            "error_category": result.get("error_category") or ErrorCategory.SCRIPT,
            "message": "复用流程首跑未通过："
            + (result.get("error_message") or "未知错误")
            + "\n未消耗模型额度，仅调参数取值或修复流程后重试",
        }

    def _merge_values(self, schema: list, raw) -> dict:
        """schema 默认值 ← 模型给的取值（丢弃 schema 之外的 key）。"""
        values: dict = {}
        raw = raw if isinstance(raw, dict) else {}
        for item in schema:
            name = item["name"]
            value = raw.get(name)
            if value is None or value == "":
                value = item.get("default")
            values[name] = "" if value is None else value
        return values

    def _case_with_params(self, values: dict, schema: list):
        """首跑用的只读用例视图（带上本次参数，不写库）。"""
        import types

        case = self.case
        return types.SimpleNamespace(
            id=case.id,
            project_id=case.project_id,
            title=case.title,
            precondition=case.precondition,
            steps=list(case.steps or []),
            expected=case.expected,
            site=case.site,
            params_json=dict(values or {}),
            params_schema_json=list(schema or []),
            script_version=case.script_version,
            kb_folder_id=case.kb_folder_id,
            flow_id=case.flow_id,
        )

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
        if not is_fix:
            folder_id = int(getattr(case, "kb_folder_id", None) or 0)
            user_parts.append(
                f"流程模块导入路径固定为：from flows.f_{folder_id}.<流程key>_v1 import run "
                f"（当前用例目录 id = {folder_id}，路径只用这个数字，禁止用目录名/拼音拼路径）。"
            )
            user_parts.append(
                "弹窗打开后，系统会自动用 browser_evaluate 枚举其中的可编辑控件并以"
                "「自动枚举控件清单」发给你；流程参数必须与该清单逐条对应，不要漏项。"
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

        rounds = 0
        bad_json = 0
        early_finish = 0
        pages_rounds = 0
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

            concurrency.set_progress(self.case_id, "模型思考", f"已调用工具 {self.tool_calls} 次")
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
            # 模型常省略 thought/tool，直接给出 finish 内容（script/flow/params）：按 finish 处理
            if not raw_tool and any(k in parsed for k in ("script", "flow", "params")):
                raw_tool = "finish"
                args = parsed
            elif not raw_tool and any(k in args for k in ("script", "flow")):
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

            if tool in ("browser_close", "browser_kill"):
                # 浏览器/标签页由脚手架管理：关闭后没有标签页，模型会陷入「反复 close」空转
                blocked_closes += 1
                self.tool_calls += 1
                self._write_log({"type": "blocked_tool", "tool": tool})
                if blocked_closes >= 3 or self.tool_calls > MAX_TOOL_CALLS:
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
                if self.tool_calls > MAX_TOOL_CALLS:
                    return {
                        "status": GenerationStatus.FAILED,
                        "error_category": ErrorCategory.MODEL,
                        "message": f"工具调用次数超过 {MAX_TOOL_CALLS} 次上限，已终止",
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
                            '完成阶段用 {"thought": "...", "tool": "finish", "args": {"script": "...", "flow": {...}, "params": {...}}}。'
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
                if not pages_problem:
                    misplaced = [
                        str(item.get("path") or "")
                        for item in (args.get("pages") or [])
                        if isinstance(item, dict) and "FLOW = {" in str(item.get("content") or "")
                    ]
                    if misplaced:
                        pages_problem = (
                            f"流程脚本不允许写进 pages/common（发现 {', '.join(misplaced)}），"
                            "完整流程源码必须放在 flow.source"
                        )
                        discard_pages(staged)
                        staged = None
                if pages_problem:
                    pages_rounds += 1
                    self._write_log({"type": "pages_invalid", "message": pages_problem})
                    if pages_rounds > MAX_FIX_ROUNDS:
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
                self._staged_pages = staged
                if staged is not None:
                    self._write_log(
                        {"type": "pages_staged", "count": len(args.get("pages") or [])}
                    )

                # 新流程：暂存流程脚本，并要求用例脚本确实复用它（参数化差异）
                flow_info = None
                schema: list = []
                values: dict = {}
                case_for_run = self.case
                if not is_fix:
                    flow_payload = args.get("flow")
                    declared = [
                        str(item.get("name") or "")
                        for item in (flow_payload.get("params") if isinstance(flow_payload, dict) else []) or []
                        if isinstance(item, dict)
                    ]
                    # 参数完整性以弹窗内真实 DOM 枚举结果为准，不依赖模型自述
                    if inventory and len(declared) < len(inventory):
                        rounds += 1
                        self._write_log(
                            {"type": "params_incomplete", "declared": declared, "controls": inventory}
                        )
                        if rounds > MAX_FIX_ROUNDS:
                            discard_pages(self._staged_pages)
                            self._staged_pages = None
                            return {
                                "status": GenerationStatus.FAILED,
                                "error_category": ErrorCategory.SCRIPT,
                                "message": (
                                    f"流程参数不完整：弹窗内实测 {len(inventory)} 个可编辑控件，"
                                    f"但 flow.params 只声明了 {len(declared)} 个，已终止以免固化残缺流程"
                                ),
                            }
                        messages.append({"role": "assistant", "content": reply})
                        messages.append(
                            {
                                "role": "user",
                                "content": (
                                    f"参数不完整：弹窗内实测 {len(inventory)} 个可编辑控件，"
                                    f"当前 flow.params 只有 {len(declared)} 个。每个控件都必须建参数并在 run() 中使用：\n"
                                    + _format_inventory(inventory)
                                    + "\n请重新输出完整 finish JSON（script + flow + params）。"
                                ),
                            }
                        )
                        continue
                    flow_problem, flow_staging, flow_info = stage_flow(
                        self.db,
                        int(self.case.project_id),
                        int(self.case.id),
                        args.get("flow"),
                        self.case,
                    )
                    if flow_problem:
                        rounds += 1
                        self._write_log({"type": "flow_invalid", "message": flow_problem})
                        if rounds > MAX_FIX_ROUNDS:
                            discard_pages(self._staged_pages)
                            self._staged_pages = None
                            return {
                                "status": GenerationStatus.FAILED,
                                "error_category": ErrorCategory.SCRIPT,
                                "message": f"流程脚本不可用：{flow_problem}",
                            }
                        messages.append({"role": "assistant", "content": reply})
                        messages.append(
                            {
                                "role": "user",
                                "content": (
                                    f"流程脚本未通过校验：{flow_problem}\n"
                                    "请把完整流程源码写进 flow.source（只需 def run(page, params)，"
                                    "FLOW 元数据由 flow 字段自动合成）；"
                                    "用例脚本从 flows 模块 import run；重新输出完整 finish JSON（script + flow + params）。"
                                ),
                            }
                        )
                        continue
                    if flow_staging is not None:
                        self._staged_pages = flow_staging
                    if flow_info is None:
                        rounds += 1
                        if rounds > MAX_FIX_ROUNDS:
                            discard_pages(self._staged_pages)
                            self._staged_pages = None
                            return {
                                "status": GenerationStatus.FAILED,
                                "error_category": ErrorCategory.SCRIPT,
                                "message": "未提交流程脚本（flow），无法沉淀可复用流程",
                            }
                        messages.append({"role": "assistant", "content": reply})
                        messages.append(
                            {
                                "role": "user",
                                "content": (
                                    "finish 缺少 flow 字段。请按规则 30 同时提交流程脚本：\n"
                                    '{"script": "用例脚本", "flow": {"key","title","route","keywords","params","source"}, '
                                    '"params": {...}, "pages": [...]}'
                                ),
                            }
                        )
                        continue
                    schema = list(flow_info["meta"]["params"])
                    values = self._merge_values(schema, args.get("params"))
                    # 模型常把目录名/拼音当包名（如 flows.f_usm），这里统一改写为实际模块路径
                    source = _rewrite_flow_import(source, flow_info["module"])
                    problem = _check_case_flow_source(source, flow_info["module"], schema)
                    if not problem:
                        missing = [
                            p["name"]
                            for p in schema
                            if p.get("required") and values.get(p["name"]) in (None, "")
                        ]
                        if missing:
                            problem = f"必填参数缺少取值：{', '.join(missing)}"
                    if problem:
                        rounds += 1
                        self._write_log({"type": "script_invalid", "message": problem})
                        if rounds > MAX_FIX_ROUNDS:
                            discard_pages(self._staged_pages)
                            self._staged_pages = None
                            return {
                                "status": GenerationStatus.FAILED,
                                "error_category": ErrorCategory.SCRIPT,
                                "message": f"用例脚本不可用：{problem}",
                            }
                        messages.append({"role": "assistant", "content": reply})
                        messages.append(
                            {
                                "role": "user",
                                "content": (
                                    f"用例脚本未通过校验：{problem}\n"
                                    "请修正后重新输出完整 finish JSON（script + flow + params）。"
                                ),
                            }
                        )
                        continue
                    case_for_run = self._case_with_params(values, schema)

                concurrency.set_progress(self.case_id, "首跑验证", "本地执行脚本验证")
                # 首跑用暂存资产，通过后才并入正式目录
                result = self._validate(
                    source, auth, case_override=case_for_run, pages_root=self._staged_pages
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
                    if flow_info is not None:
                        flow_id = adopt_flow(self.db, int(self.case.project_id), flow_info)
                        self.flow = self.db.get_flow(flow_id) if flow_id else None
                        return self._solidify(
                            source,
                            ok=True,
                            extra_fields={
                                "flow_id": flow_id,
                                "flow_version": int(flow_info["version"]),
                                "params_json": values,
                                "params_schema_json": schema,
                                "params_updated_at": _now(),
                            },
                        )
                    return self._solidify(source, ok=True)

                rounds += 1
                if rounds > MAX_FIX_ROUNDS:
                    discard_pages(self._staged_pages)
                    self._staged_pages = None
                    # 失败脚本不落正式目录：它引用尚未 adopt 的 flows 模块，会变成不可执行脚本。
                    # 修复流程不涉及 flows，可保留失败版本供人工查看。
                    if is_fix:
                        self._solidify(source, ok=False)
                    return {
                        "status": GenerationStatus.FAILED,
                        "error_category": result.get("error_category") or ErrorCategory.SCRIPT,
                        "message": "脚本首跑未通过：" + (result.get("error_message") or "未知错误"),
                        "script_saved": bool(is_fix),
                    }
                failure_text = result.get("error_message") or ""
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
                                "这是纯代码/API 用法错误，不需要重新探索页面：直接按报错修脚本，"
                                "再输出完整 finish JSON。\n"
                                if code_error
                                else "可以先回看快照确认真实按钮文案与字段，再修复脚本并输出完整 finish JSON。\n"
                            )
                            + "提示：按钮文案必须与快照里实际出现的文本一致（用例写「保存」，界面可能是「确定」）；"
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
                if self.tool_calls > MAX_TOOL_CALLS:
                    return {
                        "status": GenerationStatus.FAILED,
                        "error_category": ErrorCategory.MODEL,
                        "message": f"工具调用次数超过 {MAX_TOOL_CALLS} 次上限，已终止",
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
                if self.tool_calls > MAX_TOOL_CALLS:
                    return {
                        "status": GenerationStatus.FAILED,
                        "error_category": ErrorCategory.MODEL,
                        "message": f"工具调用次数超过 {MAX_TOOL_CALLS} 次上限，已终止",
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
                if items and _merge_inventory(inventory, items) and inventory_notices < 3:
                    inventory_notices += 1
                    self._write_log({"type": "controls", "items": inventory})
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "【自动枚举控件清单】系统已在弹窗内实测以下可编辑控件，"
                                "流程参数必须逐条覆盖（每个控件一个参数，下拉写真实可选值，"
                                "勾选项用 bool 且默认值与实测一致）：\n"
                                + _format_inventory(inventory)
                                + "\n清单之外的控件不要凭空编造。"
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
            if self.tool_calls >= 45:
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"已用工具 {self.tool_calls}/{MAX_TOOL_CALLS} 次。请基于已确认的页面事实尽快 finish，"
                            "不要再为二次确认反复快照。"
                        ),
                    }
                )

    # ===== 落盘 =====

    def _validate(self, source: str, auth, case_override=None, pages_root: Path | None = None) -> dict:
        project_id = int(self.case.project_id)
        case_dir = paths.case_dir(project_id, int(self.case.id))
        case_dir.mkdir(parents=True, exist_ok=True)
        tmp = case_dir / "case_candidate.py"
        tmp.write_text(source, encoding="utf-8")
        try:
            return run_script(
                case_override or self.case,
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

    def _solidify(self, source: str, ok: bool, extra_fields: dict | None = None) -> dict:
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
        if extra_fields:
            fields.update(extra_fields)
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


def start_job(
    case_id: int,
    kind: str,
    reuse_flow_id: int | None = None,
    force_new_flow: bool = False,
) -> None:
    """在后台线程启动生成/修复（调用方需已通过 acquire 抢到项目锁）。"""
    job = GenerationJob(case_id, kind, reuse_flow_id=reuse_flow_id, force_new_flow=force_new_flow)
    threading.Thread(target=job.run, daemon=True, name=f"ui-gen-{case_id}").start()
