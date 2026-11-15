# -*- coding: utf-8 -*-
"""Android UI 控件树剪枝器：把冗长的 page_source XML 压缩为高信噪比 [ref=eN] 快照。

同时返回每个 ref 对应的真实定位器候选（accessibility_id > resource-id > text > 相对 xpath），
供 MCP 交互工具精准执行，并把推荐写法直接提示给 Agent，避免编造脆弱的绝对 XPath。
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

_BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")
_INTERACTIVE_ATTRS = ("clickable", "checkable", "scrollable", "focusable", "long-clickable")


@dataclass
class ElementRef:
    ref: str
    class_name: str
    short_class: str
    resource_id: str
    content_desc: str
    text: str
    hint: str
    bounds: tuple[int, int, int, int]
    clickable: bool
    enabled: bool
    checked: bool
    password: bool
    xpath: str

    def recommended_locator(self) -> tuple[str, str, str]:
        """返回 (strategy, value, python_snippet)。"""
        if self.content_desc:
            return (
                "accessibility_id",
                self.content_desc,
                f'driver.find_element(AppiumBy.ACCESSIBILITY_ID, {self.content_desc!r})',
            )
        if self.resource_id:
            return (
                "id",
                self.resource_id,
                f'driver.find_element(AppiumBy.ID, {self.resource_id!r})',
            )
        if self.text:
            return (
                "text",
                self.text,
                f'driver.find_element(AppiumBy.ANDROID_UIAUTOMATOR, \'new UiSelector().text({self.text!r})\')',
            )
        return (
            "xpath",
            self.xpath,
            f'driver.find_element(AppiumBy.XPATH, {self.xpath!r})',
        )


@dataclass
class PrunedSnapshot:
    text: str
    refs: dict[str, ElementRef]
    total_raw_nodes: int
    kept_nodes: int


def _parse_bounds(raw: str) -> tuple[int, int, int, int] | None:
    m = _BOUNDS_RE.match((raw or "").strip())
    if not m:
        return None
    x1, y1, x2, y2 = (int(m.group(i)) for i in range(1, 5))
    if x2 <= x1 or y2 <= y1:
        return None
    return x1, y1, x2, y2


def _bool_attr(el: ET.Element, name: str, default: bool = False) -> bool:
    val = el.attrib.get(name)
    if val is None:
        return default
    return val.strip().lower() == "true"


def _short_class(cls_name: str) -> str:
    return (cls_name or "").rsplit(".", 1)[-1] or "Node"


def _relative_xpath(el: ET.Element, short_cls: str, text: str, content_desc: str, res_id: str) -> str:
    cls_full = el.attrib.get("class") or el.tag
    if res_id:
        return f'//{cls_full}[@resource-id="{res_id}"]'
    if content_desc:
        return f'//{cls_full}[@content-desc="{content_desc}"]'
    if text:
        safe = text.replace('"', '\\"')
        return f'//{cls_full}[@text="{safe}"]'
    idx = el.attrib.get("index", "0")
    return f"//{cls_full}[@index='{idx}']"


def prune_android_xml(
    xml_text: str,
    *,
    activity: str = "",
    screen_size: tuple[int, int] | None = None,
    compact: bool = False,
    max_nodes: int = 160,
    max_chars: int = 10000,
) -> PrunedSnapshot:
    """裁剪 Android UI XML，返回文本快照 + ref_map。"""
    if not (xml_text or "").strip():
        return PrunedSnapshot(text="(空控件树)", refs={}, total_raw_nodes=0, kept_nodes=0)

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        return PrunedSnapshot(
            text=f"(控件树 XML 解析失败: {e})", refs={}, total_raw_nodes=0, kept_nodes=0
        )

    raw_count = 0
    kept: list[ElementRef] = []
    refs: dict[str, ElementRef] = {}
    seq = 0

    def walk(el: ET.Element) -> None:
        nonlocal raw_count, seq
        raw_count += 1
        if len(kept) >= max_nodes:
            return

        # 跳过显式不可见节点
        if el.attrib.get("displayed", "true").strip().lower() == "false":
            return

        bounds = _parse_bounds(el.attrib.get("bounds", ""))
        res_id = el.attrib.get("resource-id") or ""
        desc = el.attrib.get("content-desc") or ""
        text = el.attrib.get("text") or ""
        hint = (el.attrib.get("hint") or "").strip()
        cls_name = (el.attrib.get("class") or el.tag or "").strip()
        interactive = any(_bool_attr(el, a) for a in _INTERACTIVE_ATTRS)
        has_semantic = bool(text.strip() or desc.strip() or (res_id.strip() and not compact))

        # 根节点 <hierarchy> 不输出自身
        is_root = el.tag == "hierarchy"
        should_keep = (not is_root) and bounds is not None and (interactive or bool(text.strip() or desc.strip()) or (not compact and bool(res_id.strip())))
        if compact and should_keep and not interactive and not text.strip() and not desc.strip():
            should_keep = False

        if should_keep and bounds is not None:
            seq += 1
            ref_id = f"e{seq}"
            short_cls = _short_class(cls_name)
            item = ElementRef(
                ref=ref_id,
                class_name=cls_name,
                short_class=short_cls,
                resource_id=res_id,
                content_desc=desc[:80],
                text=text[:100],
                hint=hint[:60],
                bounds=bounds,
                clickable=_bool_attr(el, "clickable"),
                enabled=_bool_attr(el, "enabled", True),
                checked=_bool_attr(el, "checked"),
                password=_bool_attr(el, "password"),
                xpath=_relative_xpath(el, short_cls, text[:60], desc[:60], res_id),
            )
            kept.append(item)
            refs[ref_id] = item
        elif not is_root and bounds is None and not has_semantic:
            # 尺寸为 0 的容器一般其子节点也不可见；仅在无语义时跳过
            pass

        for child in list(el):
            walk(child)

    walk(root)

    lines: list[str] = []
    if activity:
        lines.append(f"Activity: {activity}")
    if screen_size:
        lines.append(f"Screen: {screen_size[0]}x{screen_size[1]}")

    for item in kept:
        attrs: list[str] = []
        if item.resource_id:
            attrs.append(f'id="{item.resource_id}"')
        if item.content_desc:
            attrs.append(f'desc="{item.content_desc}"')
        if item.text:
            attrs.append(f'text="{item.text}"')
        if item.hint and not compact:
            attrs.append(f'hint="{item.hint}"')
        if item.clickable:
            attrs.append("clickable")
        if item.checked:
            attrs.append("checked")
        if item.password:
            attrs.append("password")
        if not item.enabled:
            attrs.append("disabled")
        if not compact:
            b = item.bounds
            attrs.append(f"bounds=[{b[0]},{b[1]},{b[2]},{b[3]}]")
        line = f"[ref={item.ref}] {item.short_class} " + " ".join(attrs)
        if sum(len(l) + 1 for l in lines) + len(line) > max_chars:
            lines.append("... (节点已达展示上限，请缩小关注区域或滚动页面)")
            break
        lines.append(line)

    if not kept:
        lines.append("(未检测到可交互或带文本控件，建议配合 mobile_screenshot 查看画面)")

    return PrunedSnapshot(
        text="\n".join(lines),
        refs=refs,
        total_raw_nodes=raw_count,
        kept_nodes=len(kept),
    )
