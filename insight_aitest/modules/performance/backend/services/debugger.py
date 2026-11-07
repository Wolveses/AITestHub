# -*- coding: utf-8 -*-
"""单步 / 单次 JMeter 脚本在线调试执行器。

以单线程、1次循环在沙箱环境中真实执行步骤，回显每个 Sampler 的请求与响应、变量提取与断言结果。
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

import httpx

from insight_aitest.modules.performance.backend.services.jmx_parser import JmxParser


class ScriptDebugger:
    """脚本沙箱调试执行器。"""

    @classmethod
    async def debug(
        cls,
        jmx_content: str,
        env_base_url: str = "",
        global_vars: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """在线调试运行一次 JMX 脚本中定义的 Sampler。"""
        parsed = JmxParser.parse(jmx_content)
        steps = parsed.get("steps", [])

        context_vars: dict[str, Any] = dict(global_vars or {})
        step_results = []
        all_passed = True
        total_time_ms = 0

        async with httpx.AsyncClient(verify=False, timeout=15.0) as client:
            for idx, step in enumerate(steps):
                step_name = step.get("name") or f"Step {idx + 1}"
                method = step.get("method", "GET").upper()

                # URL 处理：支持环境变量注入
                url = step.get("url") or ""
                if env_base_url and step.get("path"):
                    url = f"{env_base_url.rstrip('/')}/{step.get('path').lstrip('/')}"
                elif not url.startswith("http://") and not url.startswith("https://"):
                    if env_base_url:
                        url = f"{env_base_url.rstrip('/')}/{url.lstrip('/')}"
                    else:
                        url = f"http://{url}"

                # 替换占位符 ${var}
                url = cls._replace_vars(url, context_vars)
                headers = {
                    k: cls._replace_vars(str(v), context_vars)
                    for k, v in step.get("headers", {}).items()
                }

                body_val = step.get("body")
                content = None
                if body_val is not None and body_val != "":
                    if isinstance(body_val, (dict, list)):
                        body_str = json.dumps(body_val, ensure_ascii=False)
                    else:
                        body_str = str(body_val)
                    body_str = cls._replace_vars(body_str, context_vars)
                    content = body_str.encode("utf-8")
                    if not any(k.lower() == "content-type" for k in headers):
                        headers["Content-Type"] = "application/json"

                started = time.perf_counter()
                status_code = 0
                resp_text = ""
                error_msg = None

                try:
                    resp = await client.request(
                        method=method,
                        url=url,
                        headers=headers,
                        content=content,
                    )
                    elapsed_ms = int((time.perf_counter() - started) * 1000)
                    status_code = resp.status_code
                    resp_text = resp.text[:4096]  # 截断展示
                except Exception as exc:
                    elapsed_ms = int((time.perf_counter() - started) * 1000)
                    error_msg = str(exc)
                    all_passed = False

                total_time_ms += elapsed_ms

                # 执行 JSONPath 提取
                extracted_vars = {}
                if status_code and not error_msg:
                    extract_cfg = step.get("extract", {})
                    for var_name, jp_expr in extract_cfg.items():
                        extracted = cls._extract_jsonpath(resp_text, jp_expr)
                        if extracted is not None:
                            extracted_vars[var_name] = extracted
                            context_vars[var_name] = extracted

                # 断言校验
                assertions = step.get("assertions", [])
                assert_results = []
                for ass in assertions:
                    if ass.get("type") == "status_code":
                        exp = int(ass.get("expected", 200))
                        passed = status_code == exp
                        if not passed:
                            all_passed = False
                        assert_results.append(
                            {
                                "type": "status_code",
                                "expected": exp,
                                "actual": status_code,
                                "passed": passed,
                            }
                        )

                step_results.append(
                    {
                        "step_index": idx,
                        "name": step_name,
                        "method": method,
                        "url": url,
                        "headers": headers,
                        "body": body_val,
                        "status_code": status_code,
                        "elapsed_ms": elapsed_ms,
                        "response_body": resp_text,
                        "extracted": extracted_vars,
                        "assertions": assert_results,
                        "error": error_msg,
                    }
                )

        return {
            "all_passed": all_passed,
            "total_time_ms": total_time_ms,
            "context_vars": context_vars,
            "steps": step_results,
        }

    @staticmethod
    def _replace_vars(text: str, variables: dict[str, Any]) -> str:
        """替换 ${var} 或 {{var}} 形式的变量。"""
        if not text:
            return text

        def repl(match):
            key = match.group(1) or match.group(2)
            return str(variables.get(key, match.group(0)))

        return re.sub(r"\$\{([^}]+)\}|\{\{([^}]+)\}\}", repl, text)

    @staticmethod
    def _extract_jsonpath(text: str, expr: str) -> Any:
        try:
            from jsonpath_ng import parse

            data = json.loads(text)
            matches = [m.value for m in parse(expr).find(data)]
            return matches[0] if matches else None
        except Exception:
            return None
