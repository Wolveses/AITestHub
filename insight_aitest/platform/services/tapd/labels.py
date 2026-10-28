# -*- coding: utf-8 -*-
"""TAPD 缺陷枚举值的中文展示映射。

TAPD 缺陷的状态流可按工作空间自定义，这里覆盖默认工作流的常见取值；
未命中的值原样返回，保证不丢信息。库里始终存原始值，展示层再翻译。
"""

from __future__ import annotations

STATUS_LABELS = {
    "new": "新建",
    "acknowledged": "已确认",
    "in_progress": "处理中",
    "resolved": "已解决",
    "verified": "已验证",
    "closed": "已关闭",
    "rejected": "已拒绝",
    "reopened": "重新打开",
    "suspended": "已挂起",
    "postponed": "已延期",
    "fixed": "已修复",
    "duplicated": "重复",
}

PRIORITY_LABELS = {
    "urgent": "紧急",
    "high": "高",
    "middle": "中",
    "medium": "中",
    "low": "低",
}

SEVERITY_LABELS = {
    "fatal": "致命",
    "serious": "严重",
    "normal": "一般",
    "slight": "轻微",
    "poor": "较差",
    "suggest": "建议",
}

# 测试用例状态（/tcases 的 status 枚举，与缺陷状态不共用）
TCASE_STATUS_LABELS = {
    "normal": "正常",
    "updating": "待更新",
    "abandon": "已废弃",
}


def label(mapping: dict[str, str], value: str) -> str:
    """按原始值取中文展示名；空值返回空串，未知值原样返回。"""
    key = (value or "").strip()
    if not key:
        return ""
    return mapping.get(key.lower(), key)
