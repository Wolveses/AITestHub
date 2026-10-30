# -*- coding: utf-8 -*-
"""自动化脚本公共函数库（随代码版本发布，函数签名保持稳定）。

生成脚本必须优先复用这里的函数，脚本本体只保留「本用例独有的步骤与断言」。
旧脚本只要不修改这些函数签名就始终可用；新增能力只追加、不重命名。
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from playwright.sync_api import expect

# 与 scaffold 注入的默认超时保持一致；所有显式等待都用它，不要写固定 sleep
DEFAULT_TIMEOUT = 15000


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


def dialog_of(page, timeout: int = DEFAULT_TIMEOUT):
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


def wait_visible(locator, timeout: int = DEFAULT_TIMEOUT):
    """等待元素可见（显式等待），返回同一 locator，便于链式使用。"""
    locator.wait_for(state="visible", timeout=timeout)
    return locator


def wait_hidden(locator, timeout: int = DEFAULT_TIMEOUT):
    """等待元素隐藏或从 DOM 移除（如弹窗关闭、toast 消失）。"""
    locator.wait_for(state="hidden", timeout=timeout)
    return locator


def wait_row(page, *texts: str, timeout: int = DEFAULT_TIMEOUT):
    """等待包含指定文本的表格行出现，返回该行 locator。"""
    row = row_by_text(page, *texts).first
    row.wait_for(state="visible", timeout=timeout)
    return row


def wait_toast(page, text: str, disappear: bool = True, timeout: int = DEFAULT_TIMEOUT):
    """等待提示条出现；disappear=True 时再等待其消失（替代固定 sleep）。"""
    toast = page.get_by_text(text, exact=False).first
    toast.wait_for(state="visible", timeout=timeout)
    if disappear:
        toast.wait_for(state="hidden", timeout=timeout)
    return toast


def data_path(*parts: str) -> Path:
    """项目级测试数据文件路径（只读资产，禁止写入仓库）。"""
    root = os.environ.get("INSIGHT_UI_DATA_DIR") or ""
    if not root:
        raise RuntimeError("缺少 INSIGHT_UI_DATA_DIR，请在平台内执行脚本")
    p = Path(root).joinpath(*parts)
    if not p.exists():
        raise FileNotFoundError(f"测试数据文件不存在：{p}")
    return p


def artifact_path(name: str) -> Path:
    """本次执行的产物路径（截图、下载文件等），目录由运行器提供。"""
    root = os.environ.get("INSIGHT_UI_ARTIFACTS") or ""
    if not root:
        raise RuntimeError("缺少 INSIGHT_UI_ARTIFACTS，请在平台内执行脚本")
    d = Path(root)
    d.mkdir(parents=True, exist_ok=True)
    return d / name


def choose_option(page, trigger, label: str, timeout: int = DEFAULT_TIMEOUT):
    """下拉选择：点击触发控件后在弹出层中选择指定选项（Ant Design select/combobox）。"""
    trigger.click()
    option = page.get_by_role("option", name=label).first
    option.wait_for(state="visible", timeout=timeout)
    option.click()
    return option


def upload_files(target, *files) -> None:
    """文件上传：target 可以是 input[type=file] locator，也可以是页面/弹窗容器。"""
    paths_ = [str(f) for f in files]
    if hasattr(target, "set_input_files"):
        try:
            target.set_input_files(paths_)
            return
        except Exception:
            pass
    target.locator('input[type="file"]').first.set_input_files(paths_)


def frame_of(page, name=None, url=None):
    """iframe 定位包装；传 name 或 url。"""
    if name is not None:
        return page.frame_locator(f'iframe[name="{name}"]')
    if url is not None:
        return page.frame_locator(f'iframe[src*="{url}"]')
    return page.frame_locator("iframe").first


def new_tab(page, trigger, timeout: int = DEFAULT_TIMEOUT):
    """点击会打开新窗口的控件，返回新 page（自动等待 popup）。"""
    with page.expect_popup(timeout=timeout) as info:
        trigger.click()
    popup = info.value
    popup.wait_for_load_state()
    return popup


def download_file(page, trigger, name: str, timeout: int = DEFAULT_TIMEOUT) -> Path:
    """触发下载并保存到本次执行的产物目录，返回文件路径。"""
    with page.expect_download(timeout=timeout) as info:
        trigger.click()
    target = artifact_path(name)
    info.value.save_as(str(target))
    return target
