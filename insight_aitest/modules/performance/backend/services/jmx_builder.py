# -*- coding: utf-8 -*-
"""JMeter 5.x 测试计划 (JMX XML) 生成器。

将结构化的压测场景编排配置（包含线程组设置、HTTP Sampler、提取器与断言）转换为工业级标准 JMX XML。
可直接在官方 JMeter 5.x GUI 中打开或供命令行施压引擎调度。
"""

from __future__ import annotations

import html
import json
import xml.etree.ElementTree as ET
from typing import Any, Optional


class JmxGenerator:
    """标准 JMeter JMX 生成器。"""

    @classmethod
    def generate(
        cls,
        test_name: str,
        steps: list[dict[str, Any]],
        concurrency: int = 10,
        ramp_up: int = 5,
        duration: int = 60,
        loops: int = -1,  # -1 表示按持续时长循环
        base_url: str = "",
    ) -> str:
        """根据配置生成完整的 JMX XML 字符串。

        :param test_name: 计划名称
        :param steps: 接口步骤列表，包含 method, path, headers, body, extract, assertions
        :param concurrency: 并发线程数
        :param ramp_up: 预热时间（秒）
        :param duration: 持续时间（秒）
        :param loops: 循环次数，-1 为持续循环
        :param base_url: 基础地址
        """
        # 1. 拆分 base_url 的 domain 和 port、protocol
        protocol = "http"
        domain = ""
        port = ""
        if base_url:
            clean_url = base_url.strip()
            if "://" in clean_url:
                proto_part, rest = clean_url.split("://", 1)
                protocol = proto_part.lower()
            else:
                rest = clean_url
            if "/" in rest:
                rest = rest.split("/", 1)[0]
            if ":" in rest:
                domain, port = rest.split(":", 1)
            else:
                domain = rest

        root = ET.Element("jmeterTestPlan", version="1.2", properties="5.0", jmeter="5.6.3")
        tree_root = ET.SubElement(root, "hashTree")

        # TestPlan
        test_plan = ET.SubElement(
            tree_root,
            "TestPlan",
            guiclass="TestPlanGui",
            testclass="TestPlan",
            testname=test_name or "Performance Test Plan",
            enabled="true",
        )
        ET.SubElement(test_plan, "boolProp", name="TestPlan.functional_mode").text = "false"
        ET.SubElement(test_plan, "boolProp", name="TestPlan.tearDown_on_shutdown").text = "true"
        args_elem = ET.SubElement(
            test_plan, "elementProp", name="TestPlan.user_defined_variables", elementType="Arguments"
        )
        ET.SubElement(args_elem, "collectionProp", name="Arguments.arguments")

        plan_hash_tree = ET.SubElement(tree_root, "hashTree")

        # Global HeaderManager
        header_mgr = ET.SubElement(
            plan_hash_tree,
            "HeaderManager",
            guiclass="HeaderPanel",
            testclass="HeaderManager",
            testname="Global HTTP Headers",
            enabled="true",
        )
        headers_coll = ET.SubElement(header_mgr, "collectionProp", name="HeaderManager.headers")
        h_elem = ET.SubElement(headers_coll, "elementProp", name="", elementType="Header")
        ET.SubElement(h_elem, "stringProp", name="Header.name").text = "Content-Type"
        ET.SubElement(h_elem, "stringProp", name="Header.value").text = "application/json"
        ET.SubElement(plan_hash_tree, "hashTree")

        # ThreadGroup
        thread_group = ET.SubElement(
            plan_hash_tree,
            "ThreadGroup",
            guiclass="ThreadGroupGui",
            testclass="ThreadGroup",
            testname="Performance Thread Group",
            enabled="true",
        )
        ET.SubElement(thread_group, "stringProp", name="ThreadGroup.num_threads").text = str(concurrency)
        ET.SubElement(thread_group, "stringProp", name="ThreadGroup.ramp_time").text = str(ramp_up)

        loop_ctrl = ET.SubElement(
            thread_group,
            "elementProp",
            name="ThreadGroup.main_controller",
            elementType="LoopController",
            guiclass="LoopControlPanel",
            testclass="LoopController",
            testname="Loop Controller",
            enabled="true",
        )
        if loops > 0:
            ET.SubElement(loop_ctrl, "boolProp", name="LoopController.continue_forever").text = "false"
            ET.SubElement(loop_ctrl, "stringProp", name="LoopController.loops").text = str(loops)
            ET.SubElement(thread_group, "boolProp", name="ThreadGroup.scheduler").text = "false"
        else:
            ET.SubElement(loop_ctrl, "boolProp", name="LoopController.continue_forever").text = "false"
            ET.SubElement(loop_ctrl, "intProp", name="LoopController.loops").text = "-1"
            ET.SubElement(thread_group, "boolProp", name="ThreadGroup.scheduler").text = "true"
            ET.SubElement(thread_group, "stringProp", name="ThreadGroup.duration").text = str(duration)

        thread_hash_tree = ET.SubElement(plan_hash_tree, "hashTree")

        # 遍历步骤生成 HTTP Sampler
        for step in steps:
            s_name = step.get("name") or f"{step.get('method', 'GET')} {step.get('path', '')}"
            sampler = ET.SubElement(
                thread_hash_tree,
                "HTTPSamplerProxy",
                guiclass="HttpTestSampleGui",
                testclass="HTTPSamplerProxy",
                testname=s_name,
                enabled="true",
            )
            if domain:
                ET.SubElement(sampler, "stringProp", name="HTTPSampler.domain").text = domain
            if port:
                ET.SubElement(sampler, "stringProp", name="HTTPSampler.port").text = str(port)
            ET.SubElement(sampler, "stringProp", name="HTTPSampler.protocol").text = protocol
            ET.SubElement(sampler, "stringProp", name="HTTPSampler.path").text = step.get("path", "")
            ET.SubElement(sampler, "stringProp", name="HTTPSampler.method").text = (
                step.get("method", "GET").upper()
            )
            ET.SubElement(sampler, "boolProp", name="HTTPSampler.follow_redirects").text = "true"
            ET.SubElement(sampler, "boolProp", name="HTTPSampler.auto_redirects").text = "false"
            ET.SubElement(sampler, "boolProp", name="HTTPSampler.use_keepalive").text = "true"

            # Body 处理
            body = step.get("body")
            sampler_args = ET.SubElement(
                sampler, "elementProp", name="HTTPsampler.Arguments", elementType="Arguments"
            )
            sampler_args_coll = ET.SubElement(sampler_args, "collectionProp", name="Arguments.arguments")
            if body is not None and body != "":
                ET.SubElement(sampler, "boolProp", name="HTTPSampler.postBodyRaw").text = "true"
                body_str = json.dumps(body, ensure_ascii=False) if isinstance(body, (dict, list)) else str(body)
                arg_elem = ET.SubElement(sampler_args_coll, "elementProp", name="", elementType="HTTPArgument")
                ET.SubElement(arg_elem, "boolProp", name="HTTPArgument.always_encode").text = "false"
                ET.SubElement(arg_elem, "stringProp", name="Argument.value").text = body_str

            sampler_hash_tree = ET.SubElement(thread_hash_tree, "hashTree")

            # 局部请求头（例如携带 Authorization: Bearer ${token}）
            step_headers = step.get("headers") or {}
            if step_headers:
                s_header_mgr = ET.SubElement(
                    sampler_hash_tree,
                    "HeaderManager",
                    guiclass="HeaderPanel",
                    testclass="HeaderManager",
                    testname="Headers",
                    enabled="true",
                )
                s_headers_coll = ET.SubElement(s_header_mgr, "collectionProp", name="HeaderManager.headers")
                for hk, hv in step_headers.items():
                    elem = ET.SubElement(s_headers_coll, "elementProp", name="", elementType="Header")
                    ET.SubElement(elem, "stringProp", name="Header.name").text = str(hk)
                    ET.SubElement(elem, "stringProp", name="Header.value").text = str(hv)
                ET.SubElement(sampler_hash_tree, "hashTree")

            # 提取器 (JSON PostProcessor)
            extract = step.get("extract") or {}
            for var_name, jp_expr in extract.items():
                post_proc = ET.SubElement(
                    sampler_hash_tree,
                    "JSONPostProcessor",
                    guiclass="JSONPostProcessorGui",
                    testclass="JSONPostProcessor",
                    testname=f"Extract {var_name}",
                    enabled="true",
                )
                ET.SubElement(post_proc, "stringProp", name="JSONPostProcessor.referenceNames").text = var_name
                ET.SubElement(post_proc, "stringProp", name="JSONPostProcessor.jsonPathExprs").text = jp_expr
                ET.SubElement(post_proc, "stringProp", name="JSONPostProcessor.match_numbers").text = "1"
                ET.SubElement(post_proc, "stringProp", name="JSONPostProcessor.defaultValues").text = ""
                ET.SubElement(sampler_hash_tree, "hashTree")

            # 断言 (Response Assertion)
            assertions = step.get("assertions") or []
            for ass in assertions:
                if ass.get("type") == "status_code":
                    exp_status = str(ass.get("expected", 200))
                    resp_ass = ET.SubElement(
                        sampler_hash_tree,
                        "ResponseAssertion",
                        guiclass="AssertionGui",
                        testclass="ResponseAssertion",
                        testname=f"Assert Status {exp_status}",
                        enabled="true",
                    )
                    ET.SubElement(resp_ass, "stringProp", name="Assertion.test_field").text = (
                        "Assertion.response_code"
                    )
                    ET.SubElement(resp_ass, "intProp", name="Assertion.test_type").text = "8"  # Equals
                    patterns = ET.SubElement(resp_ass, "collectionProp", name="Asserion.test_strings")
                    ET.SubElement(patterns, "stringProp", name="").text = exp_status
                    ET.SubElement(sampler_hash_tree, "hashTree")

        # 格式化输出为 XML 字符串
        xml_bytes = ET.tostring(root, encoding="utf-8")
        from xml.dom import minidom

        parsed = minidom.parseString(xml_bytes)
        return parsed.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")
