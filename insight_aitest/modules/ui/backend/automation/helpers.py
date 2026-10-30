# -*- coding: utf-8 -*-
"""自动化脚本公共函数库（随代码版本发布，函数签名保持稳定）。

生成脚本必须优先复用这里的函数，脚本本体只保留「本用例独有的步骤与断言」。
旧脚本只要不修改这些函数签名就始终可用；新增能力只追加、不重命名。
"""

from __future__ import annotations

import os
import time

from playwright.sync_api import expect


def base_url() -> str:
    """被测端入口地址（后台已含 /manage，由运行器按用例 site 注入）。"""
    url = (os.environ.get("INSIGHT_UI_BASE_URL") or "").rstrip("/")
    if not url:
        raise RuntimeError("未注入 INSIGHT_UI_BASE_URL，请通过平台执行脚本（不要在 IDE 里直接跑）")
    return url


def _app_ready(page, timeout: int) -> bool:
    """等待 SPA 真正挂载：body 有可见文本且网络空闲。"""
    try:
        page.wait_for_function(
            "() => document.body && document.body.innerText.trim().length > 0",
            timeout=timeout,
        )
        page.wait_for_load_state("networkidle", timeout=timeout)
        return True
    except Exception:
        return False


def open_route(page, route: str = "", wait: bool = True, timeout: int = 20000):
    """跳转到 BASE_URL + route；hash 路由直接传 "#/usm/users"。

    该后台 SPA 冷启动偶发只渲染出壳页面（body 为空、表格不存在），
    直接断言会超时。这里等应用挂载；未挂载时先回首页让 SPA 启动，再进深链重试一次。
    """
    url = base_url() + ("/" + route.lstrip("/") if route else "")
    resp = page.goto(url)
    if not wait:
        return resp
    if _app_ready(page, timeout):
        return resp
    page.goto(base_url())
    _app_ready(page, timeout)
    resp = page.goto(url)
    _app_ready(page, timeout)
    return resp


def dialog_of(page, timeout: int = 15000):
    """等待并返回当前弹窗（Ant Design 弹窗）。"""
    dlg = page.get_by_role("dialog")
    dlg.wait_for(state="visible", timeout=timeout)
    return dlg


def text_inputs(container):
    """容器内的文本输入框：该后台弹窗的 input 没有 id/name/placeholder，只能按顺序取。"""
    return container.locator('input[type="text"]')


def fill_text_fields(dialog, *values: str):
    """按顺序填弹窗内的文本输入框，返回已填充的输入框 locator 列表。"""
    inputs = text_inputs(dialog)
    filled = []
    for index, value in enumerate(values):
        box = inputs.nth(index)
        box.fill(value)
        filled.append(box)
    return filled


def confirm_dialog(dialog, name: str = "确定"):
    """点击弹窗确认按钮并等待弹窗关闭。"""
    dialog.get_by_role("button", name=name, exact=True).click()
    expect(dialog).to_be_hidden()


def cancel_dialog(dialog, name: str = "取消"):
    """点击弹窗取消按钮并等待弹窗关闭。"""
    dialog.get_by_role("button", name=name, exact=True).click()
    expect(dialog).to_be_hidden()


def row_by_text(page, *texts: str):
    """按整行文本定位表格行；首列常是勾选框会导致 td 序号偏移，不要用 nth。"""
    row = page.get_by_role("row")
    for text in texts:
        row = row.filter(has_text=text)
    return row


def assert_row_contains(page, *texts: str):
    """断言存在一行同时包含所有给定文本，返回该行 locator。"""
    row = row_by_text(page, *texts).first
    expect(row).to_be_visible()
    for text in texts:
        expect(row).to_contain_text(text)
    return row


def unique_name(prefix: str = "test") -> str:
    """唯一测试数据名（毫秒时间戳后缀），避免重复创建同名数据导致提交失败。"""
    return f"{prefix}{int(time.time() * 1000) % 10 ** 9}"
