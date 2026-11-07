# -*- coding: utf-8 -*-
"""JMX XML 解析器：将标准 JMeter 脚本解析为标准化执行模型。

供内置轻量并发执行引擎（AsyncIO Engine）与单步在线调试调用。
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any


class JmxParser:
    """JMX 测试树解析器。"""

    @classmethod
    def parse(cls, jmx_content: str) -> dict[str, Any]:
        """解析 JMX 内容为统一字典模型。

        返回:
        {
            "test_name": ...,
            "concurrency": 10,
            "ramp_up": 5,
            "duration": 60,
            "loops": -1,
            "global_headers": {...},
            "steps": [
                {
                    "name": ...,
                    "method": ...,
                    "url": ...,
                    "protocol": ...,
                    "domain": ...,
                    "port": ...,
                    "path": ...,
                    "headers": {...},
                    "body": ...,
                    "extract": {"token": "$.data.token"},
                    "assertions": [{"type": "status_code", "expected": 200}]
                }
            ]
        }
        """
        try:
            root = ET.fromstring(jmx_content)
        except Exception as exc:
            raise ValueError(f"JMX XML 解析失败: {exc}") from exc

        # 默认值
        out: dict[str, Any] = {
            "test_name": "Performance Plan",
            "concurrency": 1,
            "ramp_up": 0,
            "duration": 60,
            "loops": 1,
            "global_headers": {},
            "steps": [],
        }

        # 查找 TestPlan
        test_plan = root.find(".//TestPlan")
        if test_plan is not None:
            out["test_name"] = test_plan.get("testname", "Performance Plan")

        # 查找 Global HeaderManager
        global_hm = root.find(".//HeaderManager[@testname='Global HTTP Headers']")
        if global_hm is not None:
            for elem in global_hm.findall(".//elementProp"):
                name = elem.find("./stringProp[@name='Header.name']")
                val = elem.find("./stringProp[@name='Header.value']")
                if name is not None and val is not None and name.text:
                    out["global_headers"][name.text] = val.text or ""

        # 查找 ThreadGroup
        tg = root.find(".//ThreadGroup")
        if tg is not None:
            num_threads = tg.find("./stringProp[@name='ThreadGroup.num_threads']")
            if num_threads is not None and num_threads.text and num_threads.text.isdigit():
                out["concurrency"] = int(num_threads.text)
            ramp_time = tg.find("./stringProp[@name='ThreadGroup.ramp_time']")
            if ramp_time is not None and ramp_time.text and ramp_time.text.isdigit():
                out["ramp_up"] = int(ramp_time.text)
            duration = tg.find("./stringProp[@name='ThreadGroup.duration']")
            if duration is not None and duration.text and duration.text.isdigit():
                out["duration"] = int(duration.text)

            loop_ctrl = tg.find(".//elementProp[@name='ThreadGroup.main_controller']")
            if loop_ctrl is not None:
                loops = loop_ctrl.find("./stringProp[@name='LoopController.loops']")
                if loops is not None and loops.text:
                    try:
                        out["loops"] = int(loops.text)
                    except ValueError:
                        out["loops"] = 1

        # 查找所有 HTTPSamplerProxy 及其紧邻的 hashTree
        # 注意：在 JMeter hashTree 结构中，sampler 之后通常紧随对应的 hashTree 包含其子组件
        samplers = root.findall(".//HTTPSamplerProxy")
        for sampler in samplers:
            s_name = sampler.get("testname", "")
            method_elem = sampler.find("./stringProp[@name='HTTPSampler.method']")
            method = (method_elem.text if method_elem is not None and method_elem.text else "GET").upper()

            domain_elem = sampler.find("./stringProp[@name='HTTPSampler.domain']")
            domain = domain_elem.text if domain_elem is not None and domain_elem.text else ""

            port_elem = sampler.find("./stringProp[@name='HTTPSampler.port']")
            port = port_elem.text if port_elem is not None and port_elem.text else ""

            proto_elem = sampler.find("./stringProp[@name='HTTPSampler.protocol']")
            protocol = proto_elem.text if proto_elem is not None and proto_elem.text else "http"

            path_elem = sampler.find("./stringProp[@name='HTTPSampler.path']")
            path = path_elem.text if path_elem is not None and path_elem.text else ""

            # Body
            body_val = None
            arg_val_elem = sampler.find(".//elementProp[@elementType='HTTPArgument']/stringProp[@name='Argument.value']")
            if arg_val_elem is not None and arg_val_elem.text:
                body_val = arg_val_elem.text

            # 组装 url
            if domain:
                port_part = f":{port}" if port and port not in ("80", "443") else ""
                url = f"{protocol}://{domain}{port_part}{path}"
            else:
                url = path

            step_dict: dict[str, Any] = {
                "name": s_name,
                "method": method,
                "url": url,
                "protocol": protocol,
                "domain": domain,
                "port": port,
                "path": path,
                "headers": dict(out["global_headers"]),
                "body": body_val,
                "extract": {},
                "assertions": [],
            }

            # 寻找该 sampler 的子组件（在 XML 规范中，sampler 下面兄弟节点或直接子节点可能包含局部 Header/Extractors）
            out["steps"].append(step_dict)

        # 递归或遍历提取局部 Extractors 和 Assertions
        cls._enrich_sub_elements(root, out["steps"])
        return out

    @classmethod
    def _enrich_sub_elements(cls, root: ET.Element, steps: list[dict[str, Any]]) -> None:
        """从 JMX 树中抽取提取器与断言关联到对应的步骤。"""
        # 简化关联：扫描全部 JSONPostProcessor 并按 referenceNames 挂载
        post_procs = root.findall(".//JSONPostProcessor")
        for idx, pp in enumerate(post_procs):
            ref = pp.find("./stringProp[@name='JSONPostProcessor.referenceNames']")
            expr = pp.find("./stringProp[@name='JSONPostProcessor.jsonPathExprs']")
            if ref is not None and expr is not None and ref.text and expr.text:
                # 挂载到步骤中
                target_idx = min(idx, len(steps) - 1) if steps else -1
                if target_idx >= 0:
                    steps[target_idx]["extract"][ref.text] = expr.text

        # 扫描断言
        resp_assertions = root.findall(".//ResponseAssertion")
        for idx, ass in enumerate(resp_assertions):
            test_strs = ass.find(".//collectionProp[@name='Asserion.test_strings']/stringProp")
            if test_strs is not None and test_strs.text:
                target_idx = min(idx, len(steps) - 1) if steps else -1
                if target_idx >= 0:
                    try:
                        steps[target_idx]["assertions"].append(
                            {"type": "status_code", "expected": int(test_strs.text)}
                        )
                    except ValueError:
                        pass
