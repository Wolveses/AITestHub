# -*- coding: utf-8 -*-
"""AI 性能方案推荐与接口智能挑选服务。

根据用户的性能测试方案描述，从 API 资产库 (api_assets) 中自动匹配挑选相关接口，
拓扑排序编排调用链路，提取上下文变量（如 Token、ID）并生成 JMeter 脚本。
"""

from __future__ import annotations

import json
from typing import Any, Optional

from logzero import logger

from insight_aitest.modules.api.backend.persistence.asset_database import AssetDatabase
from insight_aitest.modules.api.backend.services.flow_compose import compose_case
from insight_aitest.modules.performance.backend.services.jmx_builder import JmxGenerator

_PERF_SYSTEM_PROMPT = """你是一名资深服务端性能测试架构师。
你的任务是根据用户输入的「性能测试方案」，从给出的项目现有 API 接口资产列表中，挑选出最核心、最相关的接口，
并编排为一个具有上下文依赖关系的性能压测场景。

输入 JSON 格式：
{
  "plan_description": "用户的压测方案描述",
  "concurrency": 目标并发数,
  "assets": [
    {"id": 1, "method": "POST", "path": "/api/auth/login", "title": "登录接口", "summary": "用户鉴权"},
    {"id": 2, "method": "GET", "path": "/api/products", "title": "商品列表", "summary": "分页查询商品"},
    {"id": 3, "method": "POST", "path": "/api/orders", "title": "提交订单", "summary": "创建订单"}
  ]
}

要求：
1. 挑选与方案强相关的接口，按正常业务执行顺序（如 登录 -> 列表查询 -> 详情 -> 提交）排序；
2. 识别前置提取变量（如登录获取 token），并在后续需要鉴权的接口中声明注入方式；
3. 输出严格的 JSON 格式（不要包含 Markdown 标记）：
{
  "selected_asset_ids": [1, 2, 3],
  "reason": "选型与链路编排理由说明",
  "concurrency": 20,
  "ramp_up": 5,
  "duration": 60,
  "steps": [
    {
      "asset_id": 1,
      "name": "用户登录获取Token",
      "extract": {"token": "$.data.token"}
    },
    {
      "asset_id": 2,
      "name": "查询商品列表"
    },
    {
      "asset_id": 3,
      "name": "下单",
      "headers": {"Authorization": "Bearer ${token}"}
    }
  ]
}
"""


class PerfAIService:
    """性能测试 AI 编排服务。"""

    @classmethod
    def generate_script_from_plan(
        cls,
        project_id: int,
        plan_description: str,
        asset_db: AssetDatabase,
        llm: Any = None,
        target_concurrency: int = 10,
        ramp_up_seconds: int = 5,
        duration_seconds: int = 60,
    ) -> dict[str, Any]:
        """根据方案描述自动检索接口资产并生成 JMX 脚本与配置。"""
        # 1. 查询当前项目的全部有效接口资产
        all_assets, total = asset_db.list_assets(
            project_id=project_id, hide_noise=True, page=1, page_size=200
        )
        if not all_assets:
            # 降级：如果项目还没有资产，抛出清晰提示
            raise ValueError("当前项目下暂无接口资产，请先在「API 自动化」或「UI 抓包」中录入接口")

        # 2. 准备候选资产摘要
        asset_candidates = []
        for a in all_assets:
            meta = a.ai_meta or {}
            summary = meta.get("summary", "") if isinstance(meta, dict) else ""
            asset_candidates.append(
                {
                    "id": a.id,
                    "method": a.method,
                    "path": a.path or a.path_template,
                    "title": a.title or f"{a.method} {a.path}",
                    "summary": summary,
                }
            )

        selected_asset_ids = []
        reason = ""
        steps_config = []

        # 3. 如果配置了 LLM 且平台自动化辅助开关开启，则由大模型智能挑选与编排
        from insight_aitest.platform.services.kb.deps import is_ai_assist_enabled

        if llm is not None and is_ai_assist_enabled():
            try:
                payload = {
                    "plan_description": plan_description,
                    "concurrency": target_concurrency,
                    "assets": asset_candidates[:80],  # 控制上下文体积
                }
                messages = [
                    {"role": "system", "content": _PERF_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": "请根据此性能方案挑选相关接口并编排压测场景：\n"
                        + json.dumps(payload, ensure_ascii=False),
                    },
                ]
                resp = llm.chat(messages, temperature=0, max_tokens=1500)
                data = cls._parse_json(resp)
                selected_asset_ids = [int(i) for i in data.get("selected_asset_ids", [])]
                reason = data.get("reason", "AI 智能挑选完成")
                steps_config = data.get("steps", [])
            except Exception as exc:
                logger.warning(f"AI 挑选性能接口失败，回退规则匹配: {exc}")
                selected_asset_ids = []

        # 4. 规则兜底匹配（若无模型或模型失败）
        if not selected_asset_ids:
            # 简单关键词相关度打分
            kw = (plan_description or "").lower()
            scored = []
            for a in all_assets:
                text = f"{a.title} {a.path} {a.method}".lower()
                score = sum(1 for word in kw.split() if word and word in text)
                scored.append((score, a))
            scored.sort(key=lambda x: x[0], reverse=True)
            # 取 top 5 个接口（优先非 noise）
            top_assets = [item[1] for item in scored[:5] if item[0] > 0]
            if not top_assets:
                top_assets = all_assets[:3]
            selected_asset_ids = [a.id for a in top_assets]
            reason = "根据接口路径与标题关键词规则匹配挑选"

        # 5. 根据选中的 asset_ids 组装真实步骤详情
        assets_map = {a.id: a for a in all_assets}
        selected_assets = [assets_map[aid] for aid in selected_asset_ids if aid in assets_map]
        if not selected_assets:
            selected_assets = all_assets[:1]
            selected_asset_ids = [selected_assets[0].id]

        base_url = selected_assets[0].base_url or ""
        try:
            from insight_aitest.modules.ui.backend.automation.deps import get_automation_db

            auto_db = get_automation_db()
            env_list = auto_db.list_envs(project_id) or auto_db.list_envs(None)
            if env_list:
                default_env = next((e for e in env_list if getattr(e, "is_default", False)), env_list[0])
                if getattr(default_env, "base_url", ""):
                    base_url = default_env.base_url
        except Exception as exc:
            logger.debug(f"读取 UI 自动化默认环境失败，使用资产自带 base_url: {exc}")
        assembled_steps = []

        for idx, a in enumerate(selected_assets):
            # 查找 steps_config 中是否有 extract / inject
            cfg = next((s for s in steps_config if s.get("asset_id") == a.id), {})
            step_extract = cfg.get("extract", {})
            step_headers = dict(a.headers or {})
            if "headers" in cfg:
                step_headers.update(cfg["headers"])

            # 默认断言：状态码 200
            assertions = [{"type": "status_code", "expected": a.response_status or 200}]

            assembled_steps.append(
                {
                    "asset_id": a.id,
                    "name": cfg.get("name") or a.title or f"{a.method} {a.path}",
                    "method": a.method,
                    "path": a.path,
                    "headers": step_headers,
                    "body": a.body,
                    "extract": step_extract,
                    "assertions": assertions,
                }
            )

        # 6. 调用 JmxGenerator 生成完整 JMX XML
        jmx_content = JmxGenerator.generate(
            test_name=f"Perf_{plan_description[:30]}",
            steps=assembled_steps,
            concurrency=target_concurrency,
            ramp_up=ramp_up_seconds,
            duration=duration_seconds,
            base_url=base_url,
        )

        return {
            "name": f"压测脚本 - {plan_description[:20]}",
            "description": f"基于性能方案自动生成：{plan_description}",
            "plan_description": plan_description,
            "reason": reason,
            "selected_asset_ids": selected_asset_ids,
            "concurrency": target_concurrency,
            "ramp_up": ramp_up_seconds,
            "duration": duration_seconds,
            "base_url": base_url,
            "steps": assembled_steps,
            "jmx_content": jmx_content,
        }

    @staticmethod
    def _parse_json(text: str) -> dict:
        raw = (text or "").strip()
        decoder = json.JSONDecoder(strict=False)
        start = raw.find("{")
        if start < 0:
            raise ValueError("未找到有效 JSON")
        data, _ = decoder.raw_decode(raw[start:])
        return data if isinstance(data, dict) else {}
