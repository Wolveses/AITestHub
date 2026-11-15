# -*- coding: utf-8 -*-
"""接口资产组合成 API 流程用例。

设计要点：
- 资产是唯一来源：一个用例由多个抓包资产串联而成，每个资产对应一个 step；
- 顺序：先由「响应值被后续请求直接使用」推导依赖边并做拓扑排序，保证提供参数的接口在前；
  AI 只负责在此约束下的语义编排（失败回退规则排序：增 → 改 → 查 → 删）；
- 依赖参数：基于抓包真实响应体，自动把后续步骤中的实际值替换为 ``{{变量}}``，
  并在前序步骤写入 ``extract``（jsonpath），执行器按步骤顺序传递；
- 断言：状态码 + 关键字段 jsonpath 等于抓包期望值（不生成易误报的结构断言）；
- 全程脱敏：提示词不包含 authorization/cookie/token 等凭证。
"""

from __future__ import annotations

import json
import re
from urllib.parse import parse_qsl, urlencode

from insight_aitest.modules.api.backend.services.asset_enhance import (
    _clean_path,
    _strip_sensitive_headers,
)

_METHOD_RANK = {"POST": 0, "PUT": 1, "PATCH": 1, "GET": 2, "DELETE": 3}
_DEP_KEY_RE = re.compile(r"(id|uuid|guid|code|key|no|num)$", re.I)
_VAR_RE = re.compile(r"[^0-9A-Za-z_]+")
_MAX_STEPS = 50
_MAX_FIELD_ASSERTIONS = 4
_MAX_EXPECTED_TEXT = 40
_ASSERT_PRIORITY = {
    "code": 0,
    "errno": 1,
    "errorcode": 2,
    "status": 3,
    "success": 4,
    "ok": 5,
    "msg": 6,
    "message": 7,
    "errmsg": 8,
    "error": 9,
}

_SKIP_ASSERT_KEYS = {"total", "count", "size", "recordcount", "totalcount"}

# 业务实体 → 变量前缀：departments 的 id 命名为 dept_id，users 的 id 命名为 user_id
_RESOURCE_ALIASES = {
    "departments": "dept",
    "department": "dept",
    "depts": "dept",
    "dept": "dept",
    "users": "user",
    "user": "user",
    "roles": "role",
    "role": "role",
    "organizations": "org",
    "organization": "org",
    "orgs": "org",
    "org": "org",
    "menus": "menu",
    "menu": "menu",
    "apps": "app",
    "applications": "app",
    "application": "app",
    "groups": "group",
    "group": "group",
    "tenants": "tenant",
    "tenant": "tenant",
    "projects": "project",
    "project": "project",
    "orders": "order",
    "order": "order",
    "products": "product",
    "product": "product",
}

# 路径中的标识值：UUID / 纯数字 / 长十六进制
_ID_SEGMENT_RE = re.compile(
    r"^(?:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|\d+|[0-9a-f]{16,})$",
    re.I,
)

_SYSTEM_PROMPT = """你是一名资深 HTTP 接口自动化测试工程师。
你的任务：把一组抓包得到的接口，编排成一条可重复执行、可断言、无数据残留的自动化流程，
同时负责步骤之间的参数依赖：声明每一步从响应里提取哪些变量、后续哪一步会用到它们。

输入是一个 JSON：
{
  "case_title": "用例名称，说明这条流程要验证什么",
  "assets": [
    {"index": 0, "method": "GET", "path": "/api/depts", "path_template": "/api/depts",
     "request_keys": [], "response_keys": ["code", "data"],
     "dependency_candidates": [{"path": "$[0].id", "key": "id", "sample": "d-0001"}]}
  ]
}
index 是接口编号；dependency_candidates 是该接口响应里可以提取的候选字段（path 即 jsonpath）。

只输出一个 JSON，不要 Markdown、不要解释：
{
  "steps": [
    {"index": 0, "seq": 1, "name": "获取部门列表", "extract": {"dept_id": "$[0].id"}},
    {"index": 1, "seq": 2, "name": "新增用户",
     "inject": [{"var": "dept_id", "in": "body", "field": "deptId"}],
     "extract": {"user_id": "$.id"}},
    {"index": 2, "seq": 3, "name": "查询用户详情",
     "inject": [{"var": "user_id", "in": "path"}]},
    {"index": 3, "seq": 4, "name": "修改用户",
     "inject": [{"var": "user_id", "in": "path"}]},
    {"index": 4, "seq": 5, "name": "删除用户",
     "inject": [{"var": "user_id", "in": "path"}]}
  ],
  "reason": "先查部门取 dept_id，新增后查询校验，再修改、再查询、删除后查询确认无残留"
}
- steps：每个资产一条，必须覆盖全部 index 且不重复
- seq：执行序号，从 1 开始连续递增，决定执行顺序
- name：该步骤的业务名称
- extract：本步骤成功后从响应中提取的变量，格式 {变量名: jsonpath}，jsonpath 以 $ 开头
- inject：本步骤要把变量注入到哪里，必须写清楚位置：
  * {"var": "dept_id", "in": "body", "field": "deptId"}   → JSON body 字段（field 支持嵌套，如 data.deptId）
  * {"var": "user_id", "in": "path"}                        → URL 路径里的 ID 段
  * {"var": "user_id", "in": "query", "field": "userId"}    → URL 查询参数
  * {"var": "user_id", "in": "header", "field": "X-User-Id"}→ 请求头
  变量必须来自前面 seq 步骤的 extract；只写用到的位置，不要写没用到的地方
- 变量名用业务语义加下划线：部门 id → dept_id，用户 id → user_id，不要用 id / temp1 这类泛名

编排规则：
1. 主流程按「新增 → 查询(校验新增) → 修改 → 查询(校验修改) → 删除 → 查询(确认已删除)」排列，
   每个变更操作后面紧跟一次查询，用查询结果断言变更是否成功；删除后的查询用于确认无数据残留。
2. 查询接口既可以在变更前提供依赖数据，也可以在变更后校验结果；同一资源的查询尽量复用一步。
3. 参数依赖要显式声明：新增用户需要 deptId 时，部门列表必须排在前面并 extract dept_id，
   新增用户步骤用 inject 指明 dept_id 写入哪个 body 字段；查询详情要用新创建的 id 时，
   从新增响应 extract user_id，详情步骤 inject 到 path。
4. 与用例名称无关的接口（心跳、埋点、字典预加载等）排到最后。
5. 只能使用 assets 中已有的接口，不能改请求方法，不能编造接口；jsonpath 必须来自 dependency_candidates 或响应字段，
   inject 的 field 必须来自 request_keys / body_fields / query_keys。
6. 系统会按参数依赖自动校正顺序，不必担心 seq 之外的排序细节。
"""


def _var_name(key: str, used: set[str]) -> str:
    base = _VAR_RE.sub("_", str(key or "")).strip("_").lower() or "var"
    if base[0].isdigit():
        base = f"v_{base}"
    name = base[:40]
    i = 2
    while name in used:
        name = f"{base[:36]}_{i}"
        i += 1
    used.add(name)
    return name


def _snake(text: str) -> str:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(text or ""))
    return _VAR_RE.sub("_", spaced).strip("_").lower()


def _entity_noun(asset) -> str:
    """从接口路径推导业务实体名，用于变量命名（/users → user，/departments → dept）。"""
    template = getattr(asset, "path_template", "") or getattr(asset, "path", "") or ""
    raw = template.split("?")[0]
    segments = [
        seg for seg in raw.split("/")
        if seg and "{" not in seg and not _ID_SEGMENT_RE.match(seg)
    ]
    if not segments:
        return ""
    noun = _snake(segments[-1])
    if noun in _RESOURCE_ALIASES:
        return _RESOURCE_ALIASES[noun]
    if noun.endswith("s") and len(noun) > 3:
        noun = noun[:-1]
    return noun if re.match(r"^[a-z][a-z0-9_]*$", noun) else ""


def _entity_var(key: str, asset) -> str:
    """按业务语义命名变量：id → <实体>_id，deptId → dept_id，userId → user_id。"""
    base = _snake(key or "")
    noun = _entity_noun(asset)
    norm = base.replace("_", "")
    if not norm:
        return f"{noun}_id" if noun else "value"
    if norm in {"id", "uuid", "guid"}:
        return f"{noun}_id" if noun else base
    if norm in {"code", "key", "no", "num"} and noun and not base.startswith(noun):
        return f"{noun}_{base}"
    return base


def _jsonpath(path: str, key: str) -> str:
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
        return f"{path}.{key}"
    return f"{path}['{key}']"


def _collect_scalars(node, path: str = "$", depth: int = 0) -> list[tuple[str, str, object]]:
    """从响应体收集可用于依赖匹配的标量（字段名形如 id/uuid/code 或足够长的值）。"""
    if depth >= 6:
        return []
    out: list[tuple[str, str, object]] = []
    if isinstance(node, dict):
        for key, child in node.items():
            child_path = _jsonpath(path, str(key))
            if isinstance(child, (dict, list)):
                out.extend(_collect_scalars(child, child_path, depth + 1))
            else:
                if _is_dependency_value(str(key), child):
                    out.append((child_path, str(key), child))
    elif isinstance(node, list):
        for i, child in enumerate(node[:5]):
            child_path = f"{path}[{i}]"
            if isinstance(child, (dict, list)):
                out.extend(_collect_scalars(child, child_path, depth + 1))
            elif _is_dependency_value("", child):
                out.append((child_path, "item", child))
    return out


def _is_dependency_value(key: str, value) -> bool:
    if isinstance(value, bool) or value is None:
        return False
    if _DEP_KEY_RE.search(key or ""):
        return bool(str(value).strip())
    if isinstance(value, int):
        return value >= 1000
    if isinstance(value, float):
        return value >= 1000
    if isinstance(value, str):
        return len(value) >= 6 and not value.startswith("http")
    return False


def _match_key(value) -> str:
    return str(value)


def _replace_path(path: str, mapping: dict[str, str]) -> str:
    """把 path / query 中与依赖值完全相等的片段替换为 {{变量}}。"""
    if not path:
        return path
    raw, _, query = path.partition("?")
    segments = raw.split("/")
    segments = [mapping.get(seg, seg) if seg else seg for seg in segments]
    new_path = "/".join(segments)
    if query:
        pairs = parse_qsl(query, keep_blank_values=True)
        pairs = [
            (key, mapping.get(value, value))
            for key, value in pairs
        ]
        new_path = f"{new_path}?{urlencode(pairs, safe='{}')}"
    return new_path


def _replace_body(node, mapping: dict[str, str]):
    """仅替换字符串值，避免把数字类型改成字符串影响业务校验。"""
    if isinstance(node, dict):
        return {k: _replace_body(v, mapping) for k, v in node.items()}
    if isinstance(node, list):
        return [_replace_body(v, mapping) for v in node]
    if isinstance(node, str) and node in mapping:
        return mapping[node]
    return node


def _collect_need(asset) -> set[str]:
    """当前步骤里可能需要被参数化的实际值：path 片段、query 值与 body 字符串值。"""
    need: set[str] = set()
    raw, _, query = (getattr(asset, "path", "") or "").partition("?")
    need.update(seg for seg in raw.split("/") if seg)
    for _, value in parse_qsl(query, keep_blank_values=True):
        if value:
            need.add(value)

    def walk(node, depth: int = 0) -> None:
        if depth >= 6:
            return
        if isinstance(node, dict):
            for child in node.values():
                walk(child, depth + 1)
        elif isinstance(node, list):
            for child in node:
                walk(child, depth + 1)
        elif isinstance(node, str) and node:
            need.add(node)

    walk(getattr(asset, "body", None))
    return need


def _extract_mapping(
    ordered: list, upto: int, need: set[str], value_vars: dict[str, str]
) -> dict[str, str]:
    """只为当前步骤真正用到的值建立「实际值 → {{变量}}」映射，并回填前序 extract。

    同一个实际值只提取一次（即使多个前序响应都包含它），后续步骤直接复用已有变量。
    """
    used: set[str] = set()
    for step in ordered:
        used.update((step.get("extract") or {}).keys())
    mapping: dict[str, str] = {}
    for src in ordered[:upto]:
        for path, key, value in src.get("_scalars") or []:
            raw = _match_key(value)
            if raw not in need:
                continue
            if raw in value_vars:
                mapping[raw] = value_vars[raw]
                continue
            name = _var_name(_entity_var(key or "value", src.get("asset")), used)
            placeholder = "{{" + name + "}}"
            value_vars[raw] = placeholder
            mapping[raw] = placeholder
            extract = src.setdefault("extract", {})
            extract[name] = path
    return mapping


def _specific_value(raw: str) -> bool:
    """判断一个值是否足够「可识别」，用于建立依赖边（避免 1/2 这类短数字误连）。"""
    text = str(raw or "")
    if not text:
        return False
    if text.isdigit():
        # 纯数字 ID：长度足够（含 0000… 这类全零 UUID）或数值较大才算具体
        return len(text) >= 6 or int(text) >= 1000
    return len(text) >= 6


def _path_statics(path: str) -> list[str]:
    """去掉查询串与路径中的标识段，得到稳定的资源路径。"""
    raw = (path or "").split("?")[0]
    return [
        seg for seg in raw.split("/")
        if seg and "{" not in seg and not _ID_SEGMENT_RE.match(seg)
    ]


def _same_resource(provider, consumer) -> bool:
    """新增/修改的资源路径与查询/删除的资源路径是否属于同一实体。"""
    p = _path_statics(getattr(provider, "path_template", "") or getattr(provider, "path", ""))
    c = _path_statics(getattr(consumer, "path_template", "") or getattr(consumer, "path", ""))
    if not p or not c:
        return False
    return c[: len(p)] == p or p[: len(c)] == c


def _id_field(body) -> tuple[str, str] | None:
    """取响应体中第一个 ID 字段的 (jsonpath, 字段名)。"""
    for path, key, _value in _collect_scalars(body):
        norm = _snake(key).replace("_", "")
        if norm == "id" or norm.endswith("id"):
            return path, key
    return None


def _semantic_links(assets: list) -> dict[int, dict]:
    """语义依赖：查询/删除「刚创建的实体」时，把路径里捕获的旧 ID 换成新增接口的 ID。

    例：新增用户返回 id → 获取用户详情路径 /users/<旧管理员ID> 改为 /users/{{user_id}}。
    """
    provides = [
        {_match_key(v) for _, _, v in _collect_scalars(getattr(a, "response_body", None))}
        for a in assets
    ]
    links: dict[int, dict] = {}
    for ci, consumer in enumerate(assets):
        method = (consumer.method or "GET").upper()
        if method not in ("GET", "DELETE", "PUT", "PATCH"):
            continue
        raw = (consumer.path or "").split("?")[0]
        segments = raw.split("/")
        positions = [
            i for i, seg in enumerate(segments)
            if seg and _ID_SEGMENT_RE.match(seg)
        ]
        if not positions:
            continue
        others = set()
        for k in range(len(assets)):
            if k != ci:
                others |= provides[k]
        if {segments[i] for i in positions} & others:
            continue  # 捕获 ID 已由前序响应提供，交给「值匹配」处理
        for pi, provider in enumerate(assets):
            if pi == ci or (provider.method or "GET").upper() not in ("POST", "PUT", "PATCH"):
                continue
            if not _same_resource(provider, consumer):
                continue
            field = _id_field(getattr(provider, "response_body", None))
            if not field or not _entity_noun(consumer):
                continue
            links[ci] = {"provider": pi, "position": positions[-1], "field": field}
            break
    return links


def _dependency_edges(assets: list, links: dict | None = None) -> list[set[int]]:
    """provider → consumer 依赖边：值被直接引用，或语义上查询刚创建的实体。"""
    needs = [_collect_need(a) for a in assets]
    provides = [
        {_match_key(v) for _, _, v in _collect_scalars(getattr(a, "response_body", None))}
        for a in assets
    ]
    edges = [set() for _ in assets]
    for i in range(len(assets)):
        for j in range(len(assets)):
            if i == j:
                continue
            shared = {v for v in (provides[i] & needs[j]) if _specific_value(v)}
            if shared:
                edges[i].add(j)
    for ci, link in (links or {}).items():
        edges[link["provider"]].add(ci)
    return edges


def _topo_order(assets: list, priority: list[int], links: dict | None = None) -> list[int]:
    """在依赖约束下按 priority（越小越靠前）做拓扑排序；有环时按 priority 补齐。"""
    n = len(assets)
    edges = _dependency_edges(assets, links)
    indeg = [0] * n
    for i in range(n):
        for j in edges[i]:
            indeg[j] += 1
    rank = {idx: pos for pos, idx in enumerate(priority)}
    available = [i for i in range(n) if indeg[i] == 0]
    out: list[int] = []
    while available:
        available.sort(key=lambda i: rank.get(i, n))
        cur = available.pop(0)
        out.append(cur)
        for j in edges[cur]:
            indeg[j] -= 1
            if indeg[j] == 0:
                available.append(j)
    if len(out) < n:
        # 存在环（多个响应都带同一个值）时，按方法优先级补齐：查询/删除不会被压到变更前面
        remaining = [i for i in range(n) if i not in out]
        remaining.sort(
            key=lambda i: (
                _METHOD_RANK.get((assets[i].method or "GET").upper(), 2),
                rank.get(i, n),
            )
        )
        out.extend(remaining)
    return out


def _rule_order(assets: list) -> list[int]:
    return [
        idx
        for idx, _ in sorted(
            enumerate(assets),
            key=lambda item: (_METHOD_RANK.get((item[1].method or "GET").upper(), 2), item[0]),
        )
    ]


def _asset_summary(asset, idx: int) -> dict:
    body = getattr(asset, "body", None)
    response = getattr(asset, "response_body", None)
    meta = getattr(asset, "ai_meta", None) or {}

    def keys(value) -> list[str]:
        if isinstance(value, dict):
            return [str(k) for k in list(value.keys())[:20]]
        return []

    def field_paths(node, prefix: str = "", depth: int = 0) -> list[str]:
        """body 里可注入的字段路径（支持嵌套，如 data.deptId）。"""
        if depth >= 3:
            return []
        out: list[str] = []
        if isinstance(node, dict):
            for key, child in node.items():
                path = f"{prefix}.{key}" if prefix else str(key)
                if isinstance(child, (dict, list)):
                    out.extend(field_paths(child, path, depth + 1))
                else:
                    out.append(path)
        elif isinstance(node, list) and node:
            out.extend(field_paths(node[0], f"{prefix}[0]" if prefix else "[0]", depth + 1))
        return out

    raw_path, _, query = (getattr(asset, "path", "") or "").partition("?")

    return {
        "index": idx,
        "method": (asset.method or "GET").upper(),
        "title": getattr(asset, "title", "") or "",
        "summary": str(meta.get("summary") or "") if isinstance(meta, dict) else "",
        "path": _clean_path(getattr(asset, "path", "") or ""),
        "path_template": _clean_path(getattr(asset, "path_template", "") or ""),
        "request_keys": keys(body),
        "body_fields": field_paths(body)[:24],
        "query_keys": [k for k, _ in parse_qsl(query, keep_blank_values=True)][:12],
        "response_status": int(getattr(asset, "response_status", 0) or 0),
        "response_keys": keys(response),
        "dependency_candidates": [
            {"path": path, "key": str(key), "sample": str(value)[:40]}
            for path, key, value in _collect_scalars(response)[:12]
        ],
    }


def _parse_json(text: str) -> dict:
    raw = (text or "").strip()
    decoder = json.JSONDecoder(strict=False)
    start = raw.find("{")
    if start < 0:
        raise ValueError("模型未返回 JSON 对象")
    data, _ = decoder.raw_decode(raw[start:])
    if not isinstance(data, dict):
        raise ValueError("模型返回的不是 JSON 对象")
    return data


def _ai_plan(assets: list, case_title: str, llm) -> dict | None:
    """调用模型产出「步骤 + seq + extract/uses」计划。任何异常都返回 None，由规则兜底。"""
    if llm is None or len(assets) > _MAX_STEPS:
        return None
    payload = {
        "case_title": case_title,
        "assets": [_asset_summary(a, i) for i, a in enumerate(assets)],
    }
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": "请编排以下接口资产生成 API 流程用例：\n"
            + json.dumps(payload, ensure_ascii=False, default=str),
        },
    ]
    data = _parse_json(llm.chat(messages, temperature=0, max_tokens=1200))
    raw_steps = data.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise ValueError("模型未返回 steps")

    steps: list[dict] = []
    seen: set[int] = set()
    for raw in raw_steps:
        if not isinstance(raw, dict):
            continue
        try:
            idx = int(raw.get("index"))
            seq = int(raw.get("seq"))
        except (TypeError, ValueError):
            continue
        if idx < 0 or idx >= len(assets) or idx in seen:
            continue
        seen.add(idx)
        extract: dict[str, str] = {}
        for var, jp in (raw.get("extract") or {}).items():
            name = _var_name(_snake(var), set()) if _snake(var) else ""
            if name and isinstance(jp, str) and jp.strip().startswith("$"):
                extract[name] = jp.strip()
        uses = [_snake(v) for v in (raw.get("uses") or []) if _snake(v)]
        inject: list[dict] = []
        for target in raw.get("inject") or []:
            if not isinstance(target, dict):
                continue
            var = _snake(target.get("var"))
            where = str(target.get("in") or "").strip().lower()
            field = str(target.get("field") or "").strip()
            if var and where in {"path", "query", "body", "header"}:
                inject.append({"var": var, "in": where, "field": field})
        steps.append(
            {
                "index": idx,
                "seq": seq,
                "name": str(raw.get("name") or "").strip()[:80],
                "extract": extract,
                "uses": uses,
                "inject": inject,
            }
        )

    if seen != set(range(len(assets))):
        raise ValueError("steps 未覆盖全部资产")
    seqs = sorted(s["seq"] for s in steps)
    if seqs != list(range(1, len(steps) + 1)):
        raise ValueError("seq 必须从 1 开始连续递增")

    # 变量必须先由更早的步骤提取；否则丢弃该引用（避免执行期未定义变量）
    defined: set[str] = set()
    for step in steps:
        step["uses"] = [v for v in step["uses"] if v in defined]
        step["inject"] = [t for t in step["inject"] if t["var"] in defined]
        defined.update(step["extract"].keys())

    steps.sort(key=lambda s: s["seq"])
    return {"steps": steps, "reason": str(data.get("reason") or "")[:200]}


def _read_jsonpath(data, path: str):
    """最小 jsonpath 读取：支持 $.a.b、$.a[0].b、$[0].id（组合用例时解析候选值）。"""
    if not isinstance(path, str) or not path.strip().startswith("$"):
        return None
    rest = path.strip()[1:]
    node = data
    i = 0
    while i < len(rest):
        if rest[i] == ".":
            i += 1
            continue
        if rest[i] == "[":
            end = rest.find("]", i)
            if end < 0:
                return None
            key = rest[i + 1 : end].strip().strip("'\"")
            i = end + 1
        else:
            j = i
            while j < len(rest) and rest[j] not in ".[":
                j += 1
            key = rest[i:j]
            i = j
        if isinstance(node, dict):
            node = node.get(key)
        elif isinstance(node, list) and str(key).isdigit():
            pos = int(key)
            node = node[pos] if 0 <= pos < len(node) else None
        else:
            return None
        if node is None:
            return None
    return node


def _inject_body_key(node, var: str, placeholder: str):
    """body 中字段名与变量同名（deptId ↔ dept_id）时替换为 {{var}}。"""
    if isinstance(node, dict):
        out: dict = {}
        hit = False
        for key, value in node.items():
            if _snake(key) == var:
                out[key] = placeholder
                hit = True
            else:
                new_value, sub = _inject_body_key(value, var, placeholder)
                out[key] = new_value
                hit = hit or sub
        return out, hit
    if isinstance(node, list):
        items: list = []
        hit = False
        for value in node:
            new_value, sub = _inject_body_key(value, var, placeholder)
            items.append(new_value)
            hit = hit or sub
        return items, hit
    return node, False


def _set_body_field(node, field: str, placeholder: str):
    """按 a.b / items[0].id 形式把 body 字段改写为 {{var}}。"""
    parts = re.findall(r"[^.\[\]]+", field)
    if not parts:
        return node

    def walk(current, rest):
        if not rest:
            return placeholder
        head, tail = rest[0], rest[1:]
        if isinstance(current, list):
            if not head.isdigit():
                return current
            pos = int(head)
            if pos >= len(current):
                return current
            items = list(current)
            items[pos] = walk(items[pos], tail)
            return items
        if isinstance(current, dict) and head in current:
            out = dict(current)
            out[head] = walk(current[head], tail)
            return out
        return current

    return walk(node, parts)


def _inject_query_param(path: str, field: str, placeholder: str) -> tuple[str, bool]:
    """把 URL 查询参数的值改写为 {{var}}；参数不存在则不新增。"""
    raw, _, query = path.partition("?")
    pairs = parse_qsl(query, keep_blank_values=True)
    if not field or not any(key == field for key, _ in pairs):
        return path, False
    pairs = [(key, placeholder if key == field else value) for key, value in pairs]
    return f"{raw}?{urlencode(pairs, safe='{}')}", True


def _inject_path_segment(path: str, field: str, placeholder: str) -> tuple[str, bool]:
    """把 URL 路径里的 ID 段改写为 {{var}}；field 命中具体段时优先用它。"""
    raw, _, query = path.partition("?")
    segments = raw.split("/")
    target = -1
    if field:
        target = next((i for i, seg in enumerate(segments) if seg == field), -1)
    if target < 0:
        ids = [
            i for i, seg in enumerate(segments)
            if seg and not seg.startswith("{{") and _ID_SEGMENT_RE.match(seg)
        ]
        if not ids:
            return path, False
        target = ids[-1]
    segments[target] = placeholder
    new_path = "/".join(segments)
    if query:
        new_path = f"{new_path}?{query}"
    return new_path, True


def _apply_ai_links(projected: list, order: list[int], plan: dict) -> None:
    """按模型声明的 inject 目标（body 字段 / query / path / header）注入变量。"""
    positions = {idx: pos for pos, idx in enumerate(order)}
    var_sources: dict[str, tuple[int, str]] = {}
    for step in plan["steps"]:
        for var, jp in step["extract"].items():
            var_sources[var] = (step["index"], jp)

    for pos, item in enumerate(projected):
        asset = item["asset"]
        idx = order[pos]
        step = next((s for s in plan["steps"] if s["index"] == idx), {})
        item.setdefault("path", asset.path or "")
        item.setdefault("body", getattr(asset, "body", None))
        item.setdefault("headers", dict(getattr(asset, "headers", {}) or {}))

        targets = list(step.get("inject") or [])
        # 旧版 uses 兼容：未声明位置时按同名 body 字段 + 实际值兜底
        targets += [{"var": v, "in": "auto", "field": ""} for v in step.get("uses") or []]

        for target in targets:
            source = var_sources.get(target["var"])
            if not source:
                continue
            provider_pos = positions.get(source[0])
            if provider_pos is None or provider_pos >= pos:
                continue
            var = target["var"]
            placeholder = "{{" + var + "}}"
            where = target["in"]
            field = target.get("field") or ""

            if where == "body" and field:
                item["body"] = _set_body_field(item["body"], field, placeholder)
            elif where == "query" and field:
                item["path"], _ = _inject_query_param(item["path"], field, placeholder)
            elif where == "header" and field:
                item["headers"] = {**item["headers"], field: placeholder}
            elif where == "path":
                item["path"], hit = _inject_path_segment(item["path"], field, placeholder)
                if hit:
                    id_field = _id_field(getattr(asset, "response_body", None))
                    if id_field:
                        item["expect_id"] = (id_field[1], placeholder)
            elif where == "auto":
                body, hit = _inject_body_key(item["body"], var, placeholder)
                if hit:
                    item["body"] = body
                actual = _read_jsonpath(
                    getattr(projected[provider_pos]["asset"], "response_body", None), source[1]
                )
                raw = "" if actual is None else str(actual)
                if raw:
                    mapping = {raw: placeholder}
                    new_path = _replace_path(item["path"], mapping)
                    new_body = _replace_body(item["body"], mapping)
                    if new_path != item["path"]:
                        item["path"] = new_path
                    if new_body != item["body"]:
                        item["body"] = new_body
                if (
                    placeholder not in item["path"]
                    and "id" in var
                    and _same_resource(projected[provider_pos]["asset"], asset)
                ):
                    item["path"], hit = _inject_path_segment(item["path"], "", placeholder)
                    if hit:
                        id_field = _id_field(getattr(asset, "response_body", None))
                        if id_field:
                            item["expect_id"] = (id_field[1], placeholder)

    # 兜底：模型声明了 extract 却漏写 inject 时，仍按实际值在后续请求里替换
    for pos, item in enumerate(projected):
        for var, (src_idx, jp) in var_sources.items():
            provider_pos = positions.get(src_idx)
            if provider_pos is None or provider_pos >= pos:
                continue
            actual = _read_jsonpath(
                getattr(projected[provider_pos]["asset"], "response_body", None), jp
            )
            if actual is None or not str(actual):
                continue
            mapping = {str(actual): "{{" + var + "}}"}
            new_path = _replace_path(item.get("path") or "", mapping)
            new_body = _replace_body(item.get("body"), mapping)
            if new_path != item.get("path") or new_body != item.get("body"):
                item["path"] = new_path
                item["body"] = new_body


def _pick_assertions(body, *, envelope_only: bool = False) -> list[tuple[str, object]]:
    """从响应体挑选稳定的关键字段（code/msg/total 等），用于 jsonpath 对比断言。"""
    if not isinstance(body, dict):
        return []
    cands: list[tuple[int, str, object]] = []

    def walk(node, path: str, depth: int) -> None:
        if depth > 2 or not isinstance(node, dict):
            return
        for key, value in node.items():
            key_path = _jsonpath(path, str(key))
            if isinstance(value, dict):
                walk(value, key_path, depth + 1)
                continue
            if isinstance(value, (list, tuple)) or value is None:
                continue
            if str(key).lower() in _SKIP_ASSERT_KEYS:
                continue  # 列表总数随数据变化，不适合等值断言
            if isinstance(value, str) and (not value.strip() or len(value) > _MAX_EXPECTED_TEXT):
                continue
            # 动态 ID / 编号在下次执行时必然变化，不做等值断言
            if _DEP_KEY_RE.search(str(key)) and (
                (isinstance(value, str) and len(value) >= 6)
                or (isinstance(value, (int, float)) and value >= 1000)
            ):
                continue
            score = _ASSERT_PRIORITY.get(str(key).lower(), 50)
            if envelope_only and score >= 50:
                continue  # 详情查询的实体字段已被新数据替换，只保留响应信封字段
            cands.append((score, key_path, value))

    walk(body, "$", 0)
    cands.sort(key=lambda item: (item[0], len(item[1])))
    picked: list[tuple[str, object]] = []
    seen: set[str] = set()
    for _, path, value in cands:
        if path in seen:
            continue
        seen.add(path)
        picked.append((path, value))
        if len(picked) >= _MAX_FIELD_ASSERTIONS:
            break
    return picked


def _assertions_for(asset, *, envelope_only: bool = False) -> list[dict]:
    assertions: list[dict] = [
        {"type": "status_code", "expected": int(getattr(asset, "response_status", 0) or 200)}
    ]
    for path, expected in _pick_assertions(
        getattr(asset, "response_body", None), envelope_only=envelope_only
    ):
        assertions.append({"type": "jsonpath", "path": path, "expected": expected})
    return assertions


def _expect_id_assertion(asset, key: str, placeholder: str) -> dict | None:
    """断言详情查询返回的 ID 与新增步骤提取的变量一致。"""
    for path, field_key, _value in _collect_scalars(getattr(asset, "response_body", None)):
        if _snake(field_key) == _snake(key):
            return {"type": "jsonpath", "path": path, "expected": placeholder}
    return None


def compose_case(assets: list, title: str, llm=None) -> dict:
    """把资产编排为一条 API 用例内容（纯计算 + 可选一次模型调用）。"""
    if not assets:
        raise ValueError("至少选择一个接口资产")
    if len(assets) > _MAX_STEPS:
        raise ValueError(f"单个用例最多组合 {_MAX_STEPS} 个接口资产")

    ai_used = False
    ai_reason = ""
    plan = None
    try:
        plan = _ai_plan(assets, title, llm)
    except Exception:
        plan = None
    if plan:
        base_order = [step["index"] for step in plan["steps"]]
        names = {step["index"]: step["name"] for step in plan["steps"] if step["name"]}
        ai_used = True
        ai_reason = plan.get("reason") or ""
    else:
        base_order = _rule_order(assets)
        names = {}

    # 语义依赖（查询刚创建实体）既参与排序，也作为模型漏声明 uses 时的兜底替换
    links = _semantic_links(assets)
    order = _topo_order(assets, base_order, links)
    if order != base_order:
        note = "已按接口参数依赖自动校正顺序"
        ai_reason = f"{ai_reason}；{note}" if ai_reason else note

    ai_extract = {
        step["index"]: dict(step["extract"]) for step in (plan["steps"] if plan else [])
    }
    projected: list[dict] = []
    for idx in order:
        asset = assets[idx]
        projected.append(
            {
                "asset": asset,
                "name": names.get(idx)
                or getattr(asset, "title", "")
                or f"{asset.method} {asset.path_template or asset.path}",
                "extract": dict(ai_extract.get(idx) or {}),
                "_scalars": _collect_scalars(getattr(asset, "response_body", None)),
            }
        )

    if plan:
        _apply_ai_links(projected, order, plan)
    else:
        value_vars: dict[str, str] = {}
        for pos in range(len(projected)):
            asset = projected[pos]["asset"]
            mapping = _extract_mapping(projected, pos, _collect_need(asset), value_vars)
            if not mapping:
                continue
            projected[pos]["path"] = _replace_path(asset.path or "", mapping)
            projected[pos]["body"] = _replace_body(getattr(asset, "body", None), mapping)

    # 语义依赖兜底：路径里仍是抓包时的旧 ID 时，换成新增步骤提取出的 {{<实体>_id}}
    positions = {idx: pos for pos, idx in enumerate(order)}
    for pos, item in enumerate(projected):
        idx = order[pos]
        link = links.get(idx)
        if not link:
            continue
        provider_pos = positions.get(link["provider"])
        if provider_pos is None or provider_pos >= pos:
            continue
        if "{{" in (item.get("path") or ""):
            continue  # 已由模型或值匹配完成替换
        used = {name for p in projected for name in (p.get("extract") or {})}
        name = _var_name(_entity_var(link["field"][1], item["asset"]), used)
        placeholder = "{{" + name + "}}"
        projected[provider_pos].setdefault("extract", {})[name] = link["field"][0]
        full_path = item["asset"].path or ""
        raw, _, query = full_path.partition("?")
        segments = raw.split("/")
        if link["position"] < len(segments):
            segments[link["position"]] = placeholder
        new_path = "/".join(segments)
        if query:
            new_path = f"{new_path}?{query}"
        item["path"] = new_path
        item["expect_id"] = (link["field"][1], placeholder)

    steps: list[dict] = []
    for item in projected:
        asset = item["asset"]
        expect = item.get("expect_id")
        assertions = _assertions_for(asset, envelope_only=bool(expect))
        if expect:
            extra = _expect_id_assertion(asset, expect[0], expect[1])
            if extra:
                assertions.append(extra)
        steps.append(
            {
                "name": item["name"][:120],
                "method": (asset.method or "GET").upper(),
                "path": item.get("path", asset.path or ""),
                "headers": _strip_sensitive_headers(
                    item.get("headers", getattr(asset, "headers", {}))
                ),
                "body": item.get("body", getattr(asset, "body", None)),
                "assertions": assertions,
                "extract": item.get("extract") or {},
                "asset_id": asset.id,
            }
        )

    asset_ids = [s["asset_id"] for s in steps]
    has_delete = any(s["method"] == "DELETE" for s in steps)
    sequence = " → ".join(f"{s['method']} {s['name']}" for s in steps)
    description_lines = [
        "由接口资产组合生成。",
        f"涉及资产：{', '.join(str(i) for i in asset_ids)}。",
        f"执行顺序：{sequence}。",
    ]
    if not has_delete:
        description_lines.append(
            "注意：当前组合不包含 DELETE 接口，重复执行可能残留测试数据，建议补充清理步骤。"
        )
    if ai_used and ai_reason:
        description_lines.append(f"编排依据：{ai_reason}")

    dependencies = [
        {"asset_id": item["asset"].id, "extract": item["extract"]}
        for item in projected
        if item.get("extract")
    ]

    return {
        "title": (title or "接口资产组合流程")[:120],
        "description": "\n".join(description_lines),
        "content": {
            "base_url": assets[0].base_url or "",
            "steps": steps,
            "asset_ids": asset_ids,
        },
        "ai_used": ai_used,
        "dependencies": dependencies,
    }
