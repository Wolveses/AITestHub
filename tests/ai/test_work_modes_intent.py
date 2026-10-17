# -*- coding: utf-8 -*-
"""工作模式与意图识别测试。

验证：
1. 任务模式下输入"你好"等问候/空内容：
   - planner.understand 识别出 intent_type='greeting_or_empty', is_actionable=False
   - 不生成任何测试策略（propose_strategies 返回 []）
   - API /tasks/stream 推送 guidance 事件，不生成用例
2. 对话模式：
   - /tasks/chat 支持纯会话 conversation_id（无需 task_id）
   - 保持多轮对话记忆与 assistant 消息持久化
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock
from fastapi.testclient import TestClient

from insight_aitest.modules.ai.backend.agent.planner import Planner
from insight_aitest.modules.ai.backend.persistence.models import TaskStatus, Role


def test_planner_understand_greeting_intent():
    """测试 planner 面对纯问候语时的意图识别与非可执行判定。"""
    fake_llm = MagicMock()
    # 模拟 LLM 返回 greeting_or_empty
    fake_llm.chat.return_value = json.dumps({
        "intent_type": "greeting_or_empty",
        "is_actionable": False,
        "guidance": "您好！当前处于任务模式。请提供具体的功能需求，我将为您生成用例。",
        "summary": "用户打招呼",
        "scope": [],
    })
    planner = Planner(fake_llm, MagicMock())

    result = planner.understand("你好", [])
    assert result["intent_type"] == "greeting_or_empty"
    assert result["is_actionable"] is False
    assert "任务模式" in result["guidance"]
    assert result["scope"] == []

    # 验证 propose_strategies 直接跳过策略生成
    strategies = planner.propose_strategies(result)
    assert strategies == []


def test_planner_rule_defense_greeting():
    """即使模型返回非空 dict 但用户输入为极短打招呼且无文档，Python 规则层强制判定为 greeting_or_empty。"""
    fake_llm = MagicMock()
    fake_llm.chat.return_value = json.dumps({
        "intent_type": "case_generate",
        "is_actionable": True,
        "summary": "测试用例生成",
        "scope": ["测试"],
    })
    planner = Planner(fake_llm, MagicMock())

    result = planner.understand("你好", [])
    assert result["intent_type"] == "greeting_or_empty"
    assert result["is_actionable"] is False
    assert len(result["guidance"]) > 0


def test_planner_understand_actual_requirement():
    """测试真实测试需求时正常判定为可执行。"""
    fake_llm = MagicMock()
    fake_llm.chat.return_value = json.dumps({
        "intent_type": "case_generate",
        "is_actionable": True,
        "summary": "登录功能测试，覆盖账号密码和验证码登录",
        "scope": ["账号密码登录", "短信验证码登录"],
    })
    planner = Planner(fake_llm, MagicMock())

    result = planner.understand("测试登录功能，包括账密登录和验证码登录", [])
    assert result["intent_type"] == "case_generate"
    assert result["is_actionable"] is True
    assert len(result["scope"]) == 2

