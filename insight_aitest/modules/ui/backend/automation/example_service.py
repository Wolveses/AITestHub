# -*- coding: utf-8 -*-
"""example.get 的数据组装：把「硬规则 + 平台已知坑 + 项目错题库 + 同目录动作片段
+ 已知路由 + pages/common 签名 + 最小骨架」压进一个有预算上限的只读快照。

设计目标：让本地 Agent 在探索之前就知道项目既有写法，减少无效试错；
所有内容都来自本项目，输出前统一脱敏。
"""

from __future__ import annotations

import json
import re

from insight_aitest.modules.ui.backend.automation import contract, corpus, lessons, paths

TOTAL_CHAR_LIMIT = 12_000
MAX_EXAMPLES = 3
MAX_SNIPPETS = 8
SNIPPET_CHAR_LIMIT = 700
MAX_TRAPS = 8
MAX_LESSONS = 5
LESSON_CHAR_LIMIT = 700
MAX_ROUTES = 20
MAX_ASSET_FILES = 12

_ROUTE_RE = re.compile(r"""base_url\(\)\s*\+\s*["']([^"']+)["']""")


def _clip(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 10] + "\n…（截断）"


def _known_routes(case, db) -> list[str]:
    """从本项目已实现脚本里收集 base_url() + "<路由>"，去重保序。"""
    out: list[str] = []
    seen: set[str] = set()
    try:
        items, _ = db.list_cases(project_id=int(case.project_id), page_size=200)
    except Exception:  # noqa: BLE001 - 路由索引只是加速信息
        return []
    for other in items:
        rel = getattr(other, "script_rel_path", "") or ""
        if not rel or str(getattr(other, "status", "") or "") != "implemented":
            continue
        try:
            source = paths.resolve_rel(rel).read_text(encoding="utf-8")
        except OSError:
            continue
        for route in _ROUTE_RE.findall(source):
            route = route.strip()
            if not route or route in seen:
                continue
            seen.add(route)
            out.append(route)
            if len(out) >= MAX_ROUTES:
                return out
    return out


def _build_examples(case, db, max_examples: int) -> list[dict]:
    snippets = corpus.ranked_snippets(case, db, limit=MAX_SNIPPETS)
    grouped: dict[int, dict] = {}
    for item in snippets:
        source_id = int(item["source_case_id"])
        if source_id not in grouped:
            if len(grouped) >= max_examples:
                continue
            grouped[source_id] = {
                "source_case_id": source_id,
                "title": contract.redact(item["source_title"]),
                "same_folder": bool(item["same_folder"]),
                "category_path": contract.redact(item["category_path"]),
                "score": item["score"],
                "snippets": [],
            }
        grouped[source_id]["snippets"].append(
            {
                "action": item["action"],
                "code": contract.redact(_clip(item["code"], SNIPPET_CHAR_LIMIT)),
            }
        )
    out: list[dict] = []
    for item in grouped.values():
        item["match"] = (
            f"同目录({item['category_path'] or '未分类'})" if item["same_folder"] else "同端"
        ) + f" / 相似度 {item['score']}"
        item.pop("same_folder", None)
        item.pop("score", None)
        out.append(item)
    return out


def _build_lessons(case, db) -> list[dict]:
    out: list[dict] = []
    for entry in lessons.pick_lessons(case, db, limit=MAX_LESSONS):
        out.append(
            {
                "category": entry.category or "",
                "title": contract.redact(entry.title or ""),
                "content": contract.redact(_clip(entry.content, LESSON_CHAR_LIMIT)),
                "hits": int(entry.hits or 0),
                "updated_at": (entry.updated_at or "").strftime("%Y-%m-%d")
                if getattr(entry, "updated_at", None)
                else "",
            }
        )
    return out


def _template(site: str) -> str:
    route = "/#/usm/users" if site != "frontend" else "/"
    return (
        "from playwright.sync_api import expect\n"
        "from insight_aitest.modules.ui.backend.automation.env import base_url\n\n"
        "def test_xxx(page):\n"
        '    print("[步骤] 打开页面")\n'
        f'    page.goto(base_url() + "{route}")\n'
        '    print("[步骤] 等待目标元素出现（不要用 sleep）")\n'
        '    expect(page.get_by_role("button", name="新增", exact=True)).to_be_visible()\n'
        '    print("[步骤] 执行操作并断言结果")\n'
        '    expect(page.locator(".ui-form-error-tip")).to_have_count(0)\n'
        '    print("[断言] 表单错误数为 0，预期 0")\n'
        '    print("[结果] 通过")'
    )


def _shrink(payload: dict) -> bool:
    """按「跨目录来源 → 超量片段 → 资产」的顺序裁剪到预算内；返回是否发生裁剪。"""
    trimmed = False
    while len(json.dumps(payload, ensure_ascii=False)) > TOTAL_CHAR_LIMIT:
        examples = payload.get("examples") or []
        if examples:
            if len(examples) > 1 and str(examples[-1].get("match", "")).startswith("同端"):
                examples.pop()
            elif examples[-1].get("snippets"):
                examples[-1]["snippets"].pop()
                if not examples[-1]["snippets"]:
                    examples.pop()
            else:
                examples.pop()
            trimmed = True
            continue
        if payload.get("assets"):
            payload["assets"].pop()
            trimmed = True
            continue
        if payload.get("lessons"):
            payload["lessons"].pop()
            trimmed = True
            continue
        break
    return trimmed


def template(site: str = "backend") -> str:
    """对外暴露最小可运行骨架（供 MCP resources 使用）。"""
    return _template(site)


def build_example_payload(
    case, db, max_examples: int = MAX_EXAMPLES, include_assets: bool = True
) -> dict:
    """组装 example.get 返回体（不含 ok，由 MCP 层补齐）。"""
    site = str(getattr(case, "site", "") or "")
    wanted = {"any", site} if site else {"any"}
    traps = [t for t in contract.KNOWN_TRAPS if t["site"] in wanted][:MAX_TRAPS]
    payload = {
        "contract_version": contract.CONTRACT_VERSION,
        "case": {"case_id": int(case.id), "title": str(case.title or ""), "site": site},
        "hard_rules": list(contract.HARD_RULES),
        "known_traps": traps,
        "lessons": _build_lessons(case, db),
        "known_routes": _known_routes(case, db),
        "examples": _build_examples(case, db, max(1, min(5, int(max_examples or MAX_EXAMPLES)))),
        "assets": contract.asset_index(int(case.project_id))[:MAX_ASSET_FILES]
        if include_assets
        else [],
        "template": _template(site),
        "note": "项目实测 lesson 与 known_traps 冲突时以 lesson 为准；与本次浏览器快照冲突时以快照为准。",
        "stats": {},
    }
    payload["stats"] = {
        "examples": len(payload["examples"]),
        "snippets": sum(len(e["snippets"]) for e in payload["examples"]),
        "lessons": len(payload["lessons"]),
        "traps": len(payload["known_traps"]),
        "assets": len(payload["assets"]),
        "chars": 0,
        "truncated": False,
    }
    payload["stats"]["truncated"] = _shrink(payload)
    payload["stats"]["chars"] = len(json.dumps(payload, ensure_ascii=False))
    return payload
