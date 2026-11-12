# -*- coding: utf-8 -*-
"""JMX XML 解析器：将标准 JMeter 脚本解析为标准化执行模型。

供内置轻量并发执行引擎（AsyncIO Engine）与单步在线调试调用。
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any


class JmxParser:
    """JMX 测试树与动态属性解析器。"""

    P_FUNC_RE = re.compile(r"\$\{__P\(\s*([^,\)\s]+?)(?:\s*,\s*([^,\)]*?))?\s*\)\}")
    PROPERTY_FUNC_RE = re.compile(
        r"\$\{__property\(\s*([^,\)\s]+?)(?:\s*,\s*[^,\)]*?)?(?:\s*,\s*([^,\)]*?))?\s*\)\}"
    )
    PROPS_GET_RE = re.compile(
        r"""props\.(?:get|getProperty)\(\s*["']([^"'\)\s]+?)["'](?:\s*,\s*["']([^"'\)]*?)["'])?\s*\)"""
    )
    PROPS_INDEX_RE = re.compile(r"""props\[\s*["']([^"'\s]+?)["']\s*\]""")

    @classmethod
    def extract_properties(cls, jmx_content: str) -> list[dict[str, str]]:
        """从 JMX 全文中提取所有 __P / __property / props.get 等外部参数名及其默认值。"""
        if not jmx_content:
            return []

        props_map: dict[str, str] = {}

        # 1. 匹配 ${__P(name, default)}
        for m in cls.P_FUNC_RE.finditer(jmx_content):
            name = m.group(1).strip()
            val = (m.group(2) or "").strip()
            if name and (name not in props_map or (not props_map[name] and val)):
                props_map[name] = val

        # 2. 匹配 ${__property(name, varName, default)}
        for m in cls.PROPERTY_FUNC_RE.finditer(jmx_content):
            name = m.group(1).strip()
            val = (m.group(2) or "").strip()
            if name and (name not in props_map or (not props_map[name] and val)):
                props_map[name] = val

        # 3. 匹配 props.get("name") / props.getProperty("name", "default")
        for m in cls.PROPS_GET_RE.finditer(jmx_content):
            name = m.group(1).strip()
            val = (m.group(2) or "").strip()
            if name and (name not in props_map or (not props_map[name] and val)):
                props_map[name] = val

        # 4. 匹配 props["name"]
        for m in cls.PROPS_INDEX_RE.finditer(jmx_content):
            name = m.group(1).strip()
            if name and name not in props_map:
                props_map[name] = ""

        # 5. 若整份脚本完全未定义任何外部动态属性，尝试从 ThreadGroup 原生节点中兜底提取
        if not props_map:
            try:
                root = ET.fromstring(jmx_content)
                tg = root.find(".//ThreadGroup")
                if tg is not None:
                    num_threads = tg.find("./stringProp[@name='ThreadGroup.num_threads']")
                    if num_threads is not None and num_threads.text and num_threads.text.strip():
                        val = num_threads.text.strip()
                        props_map["concurrency"] = val
                    ramp_time = tg.find("./stringProp[@name='ThreadGroup.ramp_time']")
                    if ramp_time is not None and ramp_time.text and ramp_time.text.strip():
                        val = ramp_time.text.strip()
                        props_map["ramp_up"] = val
                    duration = tg.find("./stringProp[@name='ThreadGroup.duration']")
                    if duration is not None and duration.text and duration.text.strip():
                        val = duration.text.strip()
                        props_map["duration"] = val
            except Exception:
                pass

        return [{"name": k, "default_value": v} for k, v in props_map.items()]

    @classmethod
    def parameterize_thread_group(cls, jmx_content: str) -> str:
        """若 JMX 中 ThreadGroup 仍是写死数字而非参数化表达式，将其无损转换为 __P 属性。"""
        if not jmx_content:
            return jmx_content
        try:
            root = ET.fromstring(jmx_content)
        except Exception:
            return jmx_content

        modified = False
        tg = root.find(".//ThreadGroup")
        if tg is not None:
            num_threads = tg.find("./stringProp[@name='ThreadGroup.num_threads']")
            if num_threads is not None and num_threads.text and num_threads.text.isdigit():
                num_threads.text = f"${{__P(concurrency, {num_threads.text})}}"
                modified = True

            ramp_time = tg.find("./stringProp[@name='ThreadGroup.ramp_time']")
            if ramp_time is not None and ramp_time.text and ramp_time.text.isdigit():
                ramp_time.text = f"${{__P(ramp_up, {ramp_time.text})}}"
                modified = True

            duration = tg.find("./stringProp[@name='ThreadGroup.duration']")
            if duration is not None and duration.text and duration.text.isdigit():
                duration.text = f"${{__P(duration, {duration.text})}}"
                modified = True

        if modified:
            return ET.tostring(root, encoding="utf-8").decode("utf-8")
        return jmx_content

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

        # 动态属性提取
        properties = cls.extract_properties(jmx_content)
        out["properties"] = properties

        # 智能兜底推断：若 ThreadGroup 使用了参数化表达式（非纯数字），优先提取对应属性默认值
        prop_digits = {p["name"].lower(): int(p["default_value"]) for p in properties if p["default_value"].isdigit()}
        if out["concurrency"] == 1:
            for k in ("concurrency", "threads", "num_threads", "thread_num", "vusers", "users"):
                if k in prop_digits:
                    out["concurrency"] = prop_digits[k]
                    break
        if out["duration"] == 60:
            for k in ("duration", "duration_seconds", "test_duration", "test_time", "time"):
                if k in prop_digits:
                    out["duration"] = prop_digits[k]
                    break
        if out["ramp_up"] == 0:
            for k in ("ramp_up", "ramp_up_seconds", "rampup", "warm_up"):
                if k in prop_digits:
                    out["ramp_up"] = prop_digits[k]
                    break

        # 查找 HTTP Request Defaults (ConfigTestElement guiclass="HttpDefaultsGui")
        default_domain = ""
        default_port = ""
        default_protocol = "http"
        http_defaults = root.find(".//ConfigTestElement[@guiclass='HttpDefaultsGui']")
        if http_defaults is not None:
            d_elem = http_defaults.find("./stringProp[@name='HTTPSampler.domain']")
            if d_elem is not None and d_elem.text:
                default_domain = d_elem.text.strip()
            p_elem = http_defaults.find("./stringProp[@name='HTTPSampler.port']")
            if p_elem is not None and p_elem.text:
                default_port = p_elem.text.strip()
            pr_elem = http_defaults.find("./stringProp[@name='HTTPSampler.protocol']")
            if pr_elem is not None and pr_elem.text:
                default_protocol = pr_elem.text.strip()

        # 查找所有 HTTPSamplerProxy 及其紧邻的 hashTree
        # 注意：在 JMeter hashTree 结构中，sampler 之后通常紧随对应的 hashTree 包含其子组件
        samplers = root.findall(".//HTTPSamplerProxy")
        for sampler in samplers:
            s_name = sampler.get("testname", "")
            method_elem = sampler.find("./stringProp[@name='HTTPSampler.method']")
            method = (method_elem.text if method_elem is not None and method_elem.text else "GET").upper()

            domain_elem = sampler.find("./stringProp[@name='HTTPSampler.domain']")
            domain = (domain_elem.text.strip() if domain_elem is not None and domain_elem.text else "") or default_domain

            port_elem = sampler.find("./stringProp[@name='HTTPSampler.port']")
            port = (port_elem.text.strip() if port_elem is not None and port_elem.text else "") or default_port

            proto_elem = sampler.find("./stringProp[@name='HTTPSampler.protocol']")
            protocol = (proto_elem.text.strip() if proto_elem is not None and proto_elem.text else "") or default_protocol or "http"

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
                "headers": {},
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

    @classmethod
    def override_base_url(cls, jmx_content: str, base_url: str) -> str:
        """同时覆盖 JMX 中 HTTP Request Defaults 与所有 HTTP Request 的协议、域名/IP、端口。"""
        if not base_url or not base_url.strip():
            return jmx_content

        from urllib.parse import urlparse
        import re

        clean_url = base_url.strip()
        if "://" not in clean_url:
            clean_url = f"http://{clean_url}"
        parsed_u = urlparse(clean_url)
        if not parsed_u.hostname:
            return jmx_content

        domain_val = parsed_u.hostname
        proto_val = parsed_u.scheme or "http"
        port_val = str(parsed_u.port) if parsed_u.port else ""

        def _set_prop(elem: ET.Element, prop_name: str, val: str) -> None:
            prop = elem.find(f"./stringProp[@name='{prop_name}']")
            if prop is None:
                prop = ET.SubElement(elem, "stringProp", name=prop_name)
            prop.text = val

        try:
            root = ET.fromstring(jmx_content)
            # 1. 覆盖所有 HTTP Request Defaults (ConfigTestElement guiclass="HttpDefaultsGui")
            for defaults_elem in root.findall(".//ConfigTestElement[@guiclass='HttpDefaultsGui']"):
                _set_prop(defaults_elem, "HTTPSampler.protocol", proto_val)
                _set_prop(defaults_elem, "HTTPSampler.domain", domain_val)
                _set_prop(defaults_elem, "HTTPSampler.port", port_val)

            # 2. 覆盖所有 HTTP Request (HTTPSamplerProxy)
            for sampler_elem in root.findall(".//HTTPSamplerProxy"):
                _set_prop(sampler_elem, "HTTPSampler.protocol", proto_val)
                _set_prop(sampler_elem, "HTTPSampler.domain", domain_val)
                _set_prop(sampler_elem, "HTTPSampler.port", port_val)

            xml_str = ET.tostring(root, encoding="unicode")
            if not xml_str.lstrip().startswith("<?xml"):
                xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_str
            return xml_str
        except Exception:
            # 正则兜底替换
            res = re.sub(
                r'<stringProp name="HTTPSampler\.domain">.*?</stringProp>',
                f'<stringProp name="HTTPSampler.domain">{domain_val}</stringProp>',
                jmx_content,
            )
            res = re.sub(
                r'<stringProp name="HTTPSampler\.protocol">.*?</stringProp>',
                f'<stringProp name="HTTPSampler.protocol">{proto_val}</stringProp>',
                res,
            )
            res = re.sub(
                r'<stringProp name="HTTPSampler\.port">.*?</stringProp>',
                f'<stringProp name="HTTPSampler.port">{port_val}</stringProp>',
                res,
            )
            return res

    @classmethod
    def adjust_thread_group_for_properties(
        cls, jmx_content: str, custom_properties: Optional[dict[str, Any]] = None
    ) -> str:
        """根据实际传入的动态参数自适应调整 ThreadGroup 的调度模式，防止 Invalid duration 0 异常。

        规则：
        1. 检查是否显式传入了大于 0 的有效压测时长 (duration/duration_seconds 等)；
        2. 若未传入有效时长（为空或0），而 JMX 中又开启了 ThreadGroup.scheduler 为 true，
           JMeter 会因无法获取正整数 duration 直接抛出 Invalid duration 0 并完全拒执该线程组；
        3. 此时自适应将普通 ThreadGroup 的 scheduler 设为 false，确保线程组按 LoopController 正常执行。
        """
        if not jmx_content:
            return jmx_content
        try:
            root = ET.fromstring(jmx_content)
        except Exception:
            return jmx_content

        props = custom_properties or {}
        has_valid_duration = False
        for k in ("duration", "duration_seconds", "test_duration", "test_time", "time"):
            v = str(props.get(k, "")).strip()
            if v.isdigit() and int(v) > 0:
                has_valid_duration = True
                break

        modified = False
        for tg in root.findall(".//ThreadGroup"):
            sched = tg.find("./boolProp[@name='ThreadGroup.scheduler']")
            dur_elem = tg.find("./stringProp[@name='ThreadGroup.duration']")

            if not has_valid_duration:
                dur_text = (dur_elem.text or "").strip() if dur_elem is not None else ""
                is_zero_or_empty = (
                    dur_text == ""
                    or dur_text == "0"
                    or "${__P(duration,)}" in dur_text
                    or "${__P(duration)}" in dur_text
                    or "${__P(duration,0)}" in dur_text
                )
                if is_zero_or_empty:
                    if sched is not None and sched.text != "false":
                        sched.text = "false"
                        modified = True
                    elif sched is None:
                        ET.SubElement(tg, "boolProp", name="ThreadGroup.scheduler").text = "false"
                        modified = True
            else:
                if sched is not None and sched.text != "true":
                    sched.text = "true"
                    modified = True
                elif sched is None:
                    ET.SubElement(tg, "boolProp", name="ThreadGroup.scheduler").text = "true"
                    modified = True

        if modified:
            xml_str = ET.tostring(root, encoding="utf-8").decode("utf-8")
            if not xml_str.startswith("<?xml"):
                xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_str
            return xml_str
        return jmx_content

    @classmethod
    def parse_component_tree(cls, jmx_content: str) -> list[dict[str, Any]]:
        """将 JMX 结构完整解析为层级树结构，顶级为 TestPlan (测试计划)。
        
        遵循 JMeter 标准 HashTree 结对规则：每个 Element 与紧跟其后的 hashTree 节点形成父子关系。
        """
        if not jmx_content or not jmx_content.strip():
            return []

        try:
            root = ET.fromstring(jmx_content)
        except Exception:
            return []

        # JMeter 全量官方内置组件及常用插件类型与中文名称映射表（覆盖全部 8 大类组件及 GUI 标识）
        TYPE_LABEL_MAP: dict[str, str] = {
            # 1. 测试计划与线程组 (Test Plan & Thread Groups)
            "TestPlan": "测试计划",
            "TestPlanGui": "测试计划",
            "ThreadGroup": "线程组",
            "ThreadGroupGui": "线程组",
            "SetupThreadGroup": "setUp线程组",
            "SetupThreadGroupGui": "setUp线程组",
            "PostThreadGroup": "tearDown线程组",
            "PostThreadGroupGui": "tearDown线程组",
            "OpenModelThreadGroup": "开放模型线程组",
            "OpenModelThreadGroupGui": "开放模型线程组",
            "com.blazemeter.jmeter.threads.concurrency.ConcurrencyThreadGroup": "阶梯并发线程组",
            "com.blazemeter.jmeter.threads.arrivals.ArrivalsThreadGroup": "到达率线程组",
            "com.blazemeter.jmeter.threads.freeform.FreeFormArrivalsThreadGroup": "自由形式到达率线程组",

            # 2. 取样器 (Samplers)
            "HTTPSampler": "HTTP请求",
            "HTTPSamplerProxy": "HTTP请求",
            "HttpTestSampleGui": "HTTP请求",
            "GraphQLHTTPSampler": "GraphQL HTTP请求",
            "GraphQLHTTPSamplerGui": "GraphQL HTTP请求",
            "DebugSampler": "调试取样器",
            "TestBeanGUI": "JSR223元件/测试元件",
            "JSR223Sampler": "JSR223取样器",
            "BeanShellSampler": "BeanShell取样器",
            "BeanShellSamplerGui": "BeanShell取样器",
            "BSFSampler": "BSF取样器",
            "AjpSampler": "AJP/1.3取样器",
            "AjpSamplerGui": "AJP/1.3取样器",
            "AccessLogSampler": "Access Log取样器",
            "BoltSampler": "Bolt取样器",
            "FTPSampler": "FTP请求",
            "FtpTestSamplerGui": "FTP请求",
            "JDBCSampler": "JDBC请求",
            "JMSSampler": "JMS点对点",
            "JMSSamplerGui": "JMS点对点",
            "JMSPublisher": "JMS发布者",
            "JMSPublisherGui": "JMS发布者",
            "JMSSubscriber": "JMS订阅者",
            "JMSSubscriberGui": "JMS订阅者",
            "JavaSampler": "Java请求",
            "JavaTestSamplerGui": "Java请求",
            "JUnitSampler": "JUnit请求",
            "JUnitTestSamplerGui": "JUnit请求",
            "LDAPSampler": "LDAP请求",
            "LdapTestSamplerGui": "LDAP请求",
            "LDAPExtSampler": "LDAP扩展请求",
            "LdapExtTestSamplerGui": "LDAP扩展请求",
            "MailReaderSampler": "邮件读取者取样器",
            "MailReaderSamplerGui": "邮件读取者取样器",
            "SmtpSampler": "SMTP取样器",
            "SmtpSamplerGui": "SMTP取样器",
            "SystemSampler": "OS进程/系统调用取样器",
            "SystemSamplerGui": "OS进程/系统调用取样器",
            "TCPSampler": "TCP取样器",
            "TCPSamplerGui": "TCP取样器",
            "TestAction": "测试活动(流程控制)",
            "TestActionGui": "测试活动(流程控制)",
            "TransactionSampler": "事务取样器",

            # 3. 逻辑控制器 (Logic Controllers)
            "TransactionController": "事务控制器",
            "TransactionControllerGui": "事务控制器",
            "LoopController": "循环控制器",
            "LoopControlPanel": "循环控制器",
            "IfController": "如果(If)控制器",
            "IfControllerPanel": "如果(If)控制器",
            "WhileController": "While控制器",
            "WhileControllerGui": "While控制器",
            "ForeachController": "ForEach控制器",
            "ForeachControlPanel": "ForEach控制器",
            "RandomController": "随机控制器",
            "RandomControlGui": "随机控制器",
            "RandomOrderController": "随机顺序控制器",
            "RandomOrderControllerGui": "随机顺序控制器",
            "InterleaveControl": "交替控制器",
            "InterleaveControlGui": "交替控制器",
            "OnceOnlyController": "仅一次控制器",
            "OnceOnlyControllerGui": "仅一次控制器",
            "GenericController": "简单控制器",
            "LogicControllerGui": "简单控制器",
            "CriticalSectionController": "临界区控制器",
            "CriticalSectionControllerGui": "临界区控制器",
            "SwitchController": "Switch控制器",
            "SwitchControllerGui": "Switch控制器",
            "ThroughputController": "吞吐量控制器",
            "ThroughputControllerGui": "吞吐量控制器",
            "IncludeController": "Include控制器",
            "IncludeControllerGui": "Include控制器",
            "ModuleController": "模块控制器",
            "ModuleControllerGui": "模块控制器",
            "RuntimeController": "运行时控制器",
            "RunTimeGui": "运行时控制器",
            "RecordingController": "录制控制器",
            "RecordController": "录制控制器",
            "TestFragmentController": "测试片段",
            "TestFragmentControllerGui": "测试片段",

            # 4. 配置元件 (Config Elements)
            "ConfigTestElement": "配置元件",
            "HttpDefaultsGui": "HTTP请求默认值",
            "HeaderManager": "HTTP信息头管理器",
            "HeaderPanel": "HTTP信息头管理器",
            "CookieManager": "HTTP Cookie管理器",
            "CookiePanel": "HTTP Cookie管理器",
            "CacheManager": "HTTP缓存管理器",
            "CacheManagerGui": "HTTP缓存管理器",
            "AuthManager": "HTTP授权管理器",
            "AuthPanel": "HTTP授权管理器",
            "DNSCacheManager": "DNS缓存管理器",
            "DNSCachePanel": "DNS缓存管理器",
            "Arguments": "用户定义的变量",
            "ArgumentsPanel": "用户定义的变量",
            "HTTPArgumentsPanel": "HTTP参数列表",
            "CSVDataSet": "CSV数据文件设置",
            "CounterConfig": "计数器",
            "CounterConfigGui": "计数器",
            "DataSourceElement": "JDBC连接池配置",
            "FTPConfig": "FTP默认值",
            "FtpConfigGui": "FTP默认值",
            "JavaConfig": "Java默认值",
            "JavaConfigGui": "Java默认值",
            "LDAPArguments": "LDAP参数",
            "LDAPArgumentsPanel": "LDAP参数",
            "LdapConfig": "LDAP默认值",
            "LdapConfigGui": "LDAP默认值",
            "LdapExtConfig": "LDAP扩展默认值",
            "LdapExtConfigGui": "LDAP扩展默认值",
            "LoginConfig": "登录配置",
            "LoginConfigGui": "登录配置",
            "TCPConfig": "TCP默认值",
            "TCPConfigGui": "TCP默认值",
            "KeystoreConfig": "密钥库配置",
            "RandomVariableConfig": "随机变量配置",
            "SimpleConfigGui": "简单配置",

            # 5. 前置处理器 (Pre Processors)
            "JSR223PreProcessor": "JSR223预处理程序",
            "UserParameters": "用户参数",
            "UserParametersGui": "用户参数",
            "RegExUserParameters": "正则表达式用户参数",
            "RegExUserParametersGui": "正则表达式用户参数",
            "BeanShellPreProcessor": "BeanShell预处理程序",
            "BSFPreProcessor": "BSF预处理程序",
            "JDBCPreProcessor": "JDBC预处理程序",
            "AnchorModifier": "HTML链接解析器",
            "AnchorModifierGui": "HTML链接解析器",
            "URLRewritingModifier": "HTTP URL重写修饰符",
            "URLRewritingModifierGui": "HTTP URL重写修饰符",
            "SampleTimeout": "示例超时前置处理器",
            "SampleTimeoutGui": "示例超时前置处理器",

            # 6. 后置处理器 (Post Processors)
            "JSONPostProcessor": "JSON提取器",
            "JSONPostProcessorGui": "JSON提取器",
            "RegexExtractor": "正则表达式提取器",
            "RegexExtractorGui": "正则表达式提取器",
            "BoundaryExtractor": "边界提取器",
            "BoundaryExtractorGui": "边界提取器",
            "JMESPathExtractor": "JSON JMESPath提取器",
            "JMESPathExtractorGui": "JSON JMESPath提取器",
            "HtmlExtractor": "CSS/JQuery提取器",
            "HtmlExtractorGui": "CSS/JQuery提取器",
            "XPath2Extractor": "XPath2提取器",
            "XPath2ExtractorGui": "XPath2提取器",
            "XPathExtractor": "XPath提取器",
            "XPathExtractorGui": "XPath提取器",
            "JSR223PostProcessor": "JSR223后处理程序",
            "BeanShellPostProcessor": "BeanShell后处理程序",
            "BSFPostProcessor": "BSF后处理程序",
            "JDBCPostProcessor": "JDBC后处理程序",
            "DebugPostProcessor": "调试后处理程序",
            "ResultAction": "结果动作处理器",
            "ResultActionGui": "结果动作处理器",

            # 7. 断言 (Assertions)
            "ResponseAssertion": "响应断言",
            "AssertionGui": "响应断言",
            "JSONPathAssertion": "JSON断言",
            "JSONPathAssertionGui": "JSON断言",
            "JMESPathAssertion": "JSON JMESPath断言",
            "JMESPathAssertionGui": "JSON JMESPath断言",
            "DurationAssertion": "持续时间断言",
            "DurationAssertionGui": "持续时间断言",
            "SizeAssertion": "大小断言",
            "SizeAssertionGui": "大小断言",
            "XPath2Assertion": "XPath2断言",
            "XPath2AssertionGui": "XPath2断言",
            "XPathAssertion": "XPath断言",
            "XPathAssertionGui": "XPath断言",
            "XMLAssertion": "XML断言",
            "XMLAssertionGui": "XML断言",
            "XMLSchemaAssertion": "XML Schema断言",
            "HTMLAssertion": "HTML断言",
            "HTMLAssertionGui": "HTML断言",
            "MD5HexAssertion": "MD5Hex断言",
            "SMIMEAssertion": "SMIME断言",
            "SMIMEAssertionGui": "SMIME断言",
            "CompareAssertion": "比较断言",
            "JSR223Assertion": "JSR223断言",
            "BeanShellAssertion": "BeanShell断言",
            "BeanShellAssertionGui": "BeanShell断言",
            "BSFAssertion": "BSF断言",

            # 8. 定时器 (Timers)
            "ConstantTimer": "固定定时器",
            "ConstantTimerGui": "固定定时器",
            "UniformRandomTimer": "统一随机定时器",
            "UniformRandomTimerGui": "统一随机定时器",
            "GaussianRandomTimer": "高斯随机定时器",
            "GaussianRandomTimerGui": "高斯随机定时器",
            "PoissonRandomTimer": "泊松随机定时器",
            "PoissonRandomTimerGui": "泊松随机定时器",
            "PreciseThroughputTimer": "准确吞吐量定时器",
            "ConstantThroughputTimer": "固定吞吐量定时器",
            "SyncTimer": "同步定时器(集合点)",
            "JSR223Timer": "JSR223定时器",
            "BeanShellTimer": "BeanShell定时器",
            "BSFTimer": "BSF定时器",

            # 9. 监听器 (Listeners)
            "ResultCollector": "监听器",
            "ViewResultsFullVisualizer": "察看结果树",
            "SummaryReport": "汇总报告",
            "StatVisualizer": "聚合报告",
            "StatGraphVisualizer": "汇总图",
            "TableVisualizer": "用表格察看结果",
            "RespTimeGraphVisualizer": "响应时间图",
            "GraphVisualizer": "图形结果",
            "ComparisonVisualizer": "比较断言可视化器",
            "MailerVisualizer": "邮件观察仪",
            "BackendListener": "后端监听器",
            "BackendListenerGui": "后端监听器",
            "Summariser": "生成概要结果",
            "SummariserGui": "生成概要结果",
            "ResultSaver": "保存响应到文件",
            "ResultSaverGui": "保存响应到文件",
            "BeanShellListener": "BeanShell监听器",
            "BSFListener": "BSF监听器",
            "JSR223Listener": "JSR223监听器",
        }

        def parse_hash_tree(hash_tree_elem: ET.Element) -> list[dict[str, Any]]:
            items: list[dict[str, Any]] = []
            children = list(hash_tree_elem)
            i = 0
            while i < len(children):
                elem = children[i]
                if elem.tag == "hashTree":
                    i += 1
                    continue

                tag = elem.tag
                testclass = elem.attrib.get("testclass") or tag
                guiclass = elem.attrib.get("guiclass") or ""
                raw_name = elem.attrib.get("testname") or ""

                # 优先匹配 guiclass，其次 testclass，再次 tag，兜底进行通用驼峰英文名切分解析
                type_label = (
                    TYPE_LABEL_MAP.get(guiclass)
                    or TYPE_LABEL_MAP.get(testclass)
                    or TYPE_LABEL_MAP.get(tag)
                )
                if not type_label:
                    # 兜底：如果是未知组件/第三方插件，将类名 CamelCase 转为可读名称
                    clean_name = testclass.split(".")[-1].replace("Gui", "").replace("Proxy", "")
                    # 如 KafkaSampler -> Kafka Sampler
                    type_label = re.sub(r"([a-z])([A-Z])", r"\1 \2", clean_name)

                name = raw_name if raw_name else type_label
                enabled = elem.attrib.get("enabled", "true") != "false"

                node: dict[str, Any] = {
                    "tag": tag,
                    "testclass": testclass,
                    "guiclass": guiclass,
                    "type_label": type_label,
                    "name": name,
                    "display": f"{type_label}：{name}",
                    "enabled": enabled,
                    "children": [],
                }

                # 检查下一个同级节点是否是当前元件的子树 hashTree
                if i + 1 < len(children) and children[i + 1].tag == "hashTree":
                    node["children"] = parse_hash_tree(children[i + 1])
                    i += 2
                else:
                    i += 1
                items.append(node)
            return items

        # 找到顶级 hashTree 并解析
        top_hash_tree = root.find("hashTree")
        if top_hash_tree is not None:
            return parse_hash_tree(top_hash_tree)
        return []
