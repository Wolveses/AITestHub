# -*- coding: utf-8 -*-
"""测试用例生成提示词模板（spec D §3.5）。

代入资深测试工程师视角：分析提示词提取可测点，生成提示词按测试设计方法约束。
"""

from __future__ import annotations


def _format_refs(chunks: list[tuple[str, str]]) -> str:
    """把检索片段格式化为编号参考资料。"""
    if not chunks:
        return "（无参考资料）"
    parts = []
    for i, (doc, text) in enumerate(chunks, 1):
        parts.append(f"[{i}] （来源：{doc}）\n{text}")
    return "\n\n".join(parts)


def build_analyze_prompt(
    query: str,
    chunks: list[tuple[str, str]],
    documents_text: str = "",
) -> str:
    """分析提示词：要求 LLM 从当前上传文档全文和知识库参考资料中提取可测点，输出 JSON 数组。

    支持双重注入：
    1. documents_text: 当前上传文档的全文（完整需求）
    2. chunks: 知识库 RAG 检索召回的相关文档片段（跨文档背景、规范、配置等）
    """
    materials = []
    if documents_text and documents_text.strip():
        materials.append(f"【当前上传的需求文档原文】\n{documents_text.strip()}")

    if chunks:
        refs_text = _format_refs(chunks)
        materials.append(f"【知识库参考资料】\n{refs_text}")

    if not materials:
        materials.append(f"【分析主题】\n{query}")

    combined_info = "\n\n".join(materials)

    return f"""你是一名资深测试工程师。请根据下面的需求材料全面分析并提取「可测点」（值得测试的功能、接口、交互与异常场景）。

【核心提取要求】：
1. 综合参考：必须同时深度结合【当前上传的需求文档原文】与【知识库参考资料】！
   - 以【当前上传的需求文档原文】作为核心被测对象，全面覆盖其中所有明确提到的功能模块、参数范围、交互入口与业务规则；
   - 充分吸收【知识库参考资料】中的信息、重视与系统其他功能的交互场景，严禁忽视参考资料。
2. 规范输出：输出严格的 JSON 数组，格式：
[{{"id":"tp-1","summary":"测试点简述","suggested_type":"functional","suggested_design":"positive","rationale":"提取依据与设计思路"}}]
3. 字段说明：
   - id：形如 tp-1, tp-2；
   - summary：一句话清晰定义被测功能与验证场景，尽量指出关键参数或前置状态；
   - suggested_type：必须是 functional / api / performance / ui 之一；
   - suggested_design：必须是 positive（正向）/ negative（反向异常）/ boundary（边界值）/ edge（极端/容错）之一；
   - rationale：必须具体指出本条测试点是源自当前上传文档的哪项功能，以及如何结合了知识库参考资料中的系统背景/规格推导而来。
4. 真实严谨：基于材料内容提取与推导，严禁空想完全脱离材料的内容。
5. 不要输出 JSON 以外的任何文本或解释说明。

材料：
{combined_info}"""


_DESIGN_HINTS = {
    "positive": "正向测试：使用合法输入与正常流程，验证功能正确生效、预期结果达成。",
    "negative": "异常/反向测试：使用非法输入、边界外的值或错误操作，验证系统正确拒绝并给出合理提示。",
    "boundary": "边界值测试：针对输入范围的边界与临界值（最小、最大、刚好越界），验证系统行为。",
    "edge": "极端场景测试：异常环境、并发、超时、空数据等极端情况下的系统行为。",
}

_TYPE_SCHEMA = {
    "functional": '{"steps":[{"no":1,"action":"操作描述","data":"测试数据"}],"expected":"预期结果"}',
    # api：对齐 api/engine/executor.py 的真实消费字段
    #   单步：method/path/headers/body/assertions/extract
    #   assertion.type ∈ status_code|header|jsonpath|response_time|json_schema|contains
    #   extract：{变量名: "$..jsonpath"}，提取后供后续步 {{变量名}} 引用
    "api": '{"base_url":"https://...","steps":[{"method":"POST","path":"/api/login","headers":{{"Content-Type":"application/json"}},"body":{{"username":"test","password":"123456"}},"assertions":[{{"type":"status_code","expected":200}},{{"type":"jsonpath","path":"$.code","expected":0}}],"extract":{{"token":"$.data.token"}}}}]}',
    "performance": '{"app_package":"...","platform":"android","scenario":"...","duration_sec":30,"thresholds":{{"cpu_max":40}}}',
    # ui：对齐 ui/engine/executor.py 的真实消费字段
    #   必须有 base_url；每步 kind ∈ action|assert|extract
    #   action：自然语言操作描述；assert：自然语言断言；extract：自然语言提取
    "ui": '{"base_url":"https://...","steps":[{{"kind":"action","action":"在登录页输入用户名 admin 和密码 123456，点击登录按钮"}},{{"kind":"assert","assert":"页面显示用户头像或欢迎语"}},{{"kind":"extract","extract":{{"userName":"页面右上角的用户名"}}}}]}}',
}


_TYPE_INSTRUCTION = {
    "functional": ("functional 用例：步骤必须具体可操作，expected 必须可验证。"),
    "api": (
        "api 用例：base_url 必填。每步给出 method/path/headers/body。"
        "assertions 至少包含 status_code 断言；对返回 JSON 的关键字段用 jsonpath 断言（path 形如 $.data.id）。"
        '如需跨步骤传值，用 extract 提取（{变量名: "$.jsonpath"}），后续步骤用 {{变量名}} 引用。'
    ),
    "performance": (
        "performance 用例：需 app_package/platform/scenario/duration_sec/thresholds。"
        "（注意：性能执行器尚未就绪，生成后需人工确认阈值合理性）"
    ),
    "ui": (
        "ui 用例：base_url 必填。每步用 kind 区分：kind=action 为自然语言操作描述，"
        "kind=assert 为自然语言验证断言，kind=extract 为自然语言数据提取（extract 用 {变量名: 描述}）。"
        "描述要清晰定位页面元素，便于视觉模型理解。"
    ),
}


def build_generate_prompt(
    case_type: str,
    test_design: str,
    point_summary: str,
    chunks: list[tuple[str, str]],
    documents_text: str = "",
) -> str:
    """生成提示词：为单个可测点生成一条用例，按类型/设计方法约束。

    支持双重注入：当前上传文档全文 + 知识库参考资料。
    """
    schema_hint = _TYPE_SCHEMA.get(case_type, _TYPE_SCHEMA["functional"])
    design_hint = _DESIGN_HINTS.get(test_design, _DESIGN_HINTS["positive"])
    type_hint = _TYPE_INSTRUCTION.get(case_type, _TYPE_INSTRUCTION["functional"])

    materials = []
    if documents_text and documents_text.strip():
        materials.append(f"【当前上传的需求文档原文】\n{documents_text.strip()}")

    if chunks:
        refs_text = _format_refs(chunks)
        materials.append(f"【知识库参考资料】\n{refs_text}")

    combined_materials = ("\n\n" + "\n\n".join(materials)) if materials else "\n（无额外参考材料）"

    return f"""你是一名资深测试工程师。请根据可测点和给出的需求与参考材料，生成一条高质量的测试用例。

测试设计方法：{test_design} —— {design_hint}
用例类型约束：{type_hint}

【核心生成要求】：
1. 综合参考：必须同时结合【当前上传的需求文档原文】与【知识库参考资料】！
   - 以【当前上传的需求文档原文】作为本次测试的核心功能与参数依据；
   - 充分吸收【知识库参考资料】中信息，将它们深度融入到该用例的「preconditions（前置条件）」、「steps（测试操作与测试数据）」以及「expected（校验断言）」中，严禁忽视参考资料。
2. 规范输出：输出严格的 JSON，格式：{{"title":"用例标题","description":"目的","preconditions":"前置条件","content":{schema_hint}}}
3. 严禁空洞：description 必须明确说明本条用例的测试目的与核心验证点。preconditions 明确环境依赖与配置（无前置条件时写"无"）。
4. 可执行与可验证：步骤必须包含具体的测试参数或操作路径，预期结果必须清晰、明确、可验证（严禁出现"系统正常"、"功能符合预期"等空泛描述）。
5. 真实严谨：基于材料内容进行推导与设计；若参考材料中仍有缺失的关键细节，用【待确认】明确标注，切勿凭空编造。
6. 不要输出 JSON 以外的任何文本或解释说明。
{combined_materials}

可测点：{point_summary}"""


def build_generate_from_image_prompt(base_url: str, point_summary: str = "") -> str:
    """截图→UI 用例生成提示词。

    复用 UI schema + instruction，针对截图场景定制。
    不传 RAG chunks（截图本身是信息源）。
    """
    schema_hint = _TYPE_SCHEMA["ui"]
    type_hint = _TYPE_INSTRUCTION["ui"]
    summary_line = f"\n测试重点：{point_summary}" if point_summary else ""
    return f"""你是一名资深测试工程师。请根据提供的 UI 截图，生成一条 UI 自动化测试用例。

这些截图按顺序表示一个操作流程，请看图理解后生成对应的测试步骤。
{summary_line}

base_url：{base_url}（请直接填入 content.base_url）
用例类型约束：{type_hint}

要求：
1. 输出严格的 JSON，格式：{{"title":"用例标题","description":"目的","preconditions":"前置条件","content":{schema_hint}}}
2. 每步用 kind 区分：kind=action（操作）、kind=assert（断言）、kind=extract（提取）
3. 描述要清晰定位页面元素（按钮名称、输入框位置、导航路径），便于视觉模型理解。
4. 步骤必须基于截图内容，不要编造截图中没有的元素。
5. 不要输出 JSON 以外的内容。"""
