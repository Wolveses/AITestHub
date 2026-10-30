# -*- coding: utf-8 -*-
"""运行环境契约（仓库内唯一允许脚本依赖的公共模块）。

只负责读取运行器注入的环境变量并拼路径，**不含任何被测系统结构假设**。
页面怎么定位、字段顺序、按钮文案、等待策略一律由项目资产决定：

- ``common/``：项目级通用代码（可覆盖，写前备份）
- ``pages/``：页面对象（只增不覆盖）
- ``<case>/case.py``：用例步骤与断言

这样被测系统改版时只需改用户目录资产，仓库代码无需变动。
"""

from __future__ import annotations

import os
from pathlib import Path


def base_url() -> str:
    """被测端入口地址（后台已含 /manage，由运行器按用例 site 注入）。"""
    url = (os.environ.get("INSIGHT_UI_BASE_URL") or "").rstrip("/")
    if not url:
        raise RuntimeError("未注入 INSIGHT_UI_BASE_URL，请通过平台执行脚本（不要在 IDE 里直接跑）")
    return url


def data_path(*parts: str) -> Path:
    """项目级测试数据文件路径（只读资产，位于 scripts/<project>/data/）。"""
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
