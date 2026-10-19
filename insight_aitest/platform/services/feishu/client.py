# -*- coding: utf-8 -*-
"""飞书开放平台客户端封装。

处理 tenant_access_token 获取与缓存、知识库空间/节点遍历、文档与表格内容拉取/导出。
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

FEISHU_API_BASE = "https://open.feishu.cn/open-apis"


def _safe_sheet_name(name: str) -> str:
    """清洗为 Excel 工作表可用的名称（去除非法字符并截断至 31 字符）。"""
    for ch in "[]:*?/\\":
        name = name.replace(ch, "_")
    return (name or "未命名")[:31]


def _bitable_cell(value: Any) -> Any:
    """将多维表格字段值扁平化为单元格可写入的标量。"""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (int, float, str)):
        return value
    if isinstance(value, list):
        parts = []
        for it in value:
            if isinstance(it, dict):
                parts.append(str(it.get("name") or it.get("text") or it.get("file_token") or it))
            else:
                parts.append(str(it))
        return ", ".join(parts)
    if isinstance(value, dict):
        return str(value.get("text") or value.get("name") or json.dumps(value, ensure_ascii=False))
    return str(value)


def _sheet_cell(value: Any) -> Any:
    """将 sheets/v2 values 返回的单元格值归一化为 openpyxl 可写入的标量。

    sheets/v2 的 FormattedValue 会把富文本（带超链接、不同字体的单元格）
    展开成 list[dict{text,type,link,...}]，openpyxl 不认这种结构，
    需要先扁平化成字符串。其他异常类型（时间戳、布尔、None）也一并兜底。
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (int, float, str)):
        return value
    if isinstance(value, list):
        # 富文本 run 数组：取每段 text 拼起来
        if value and isinstance(value[0], dict) and any("text" in it for it in value if isinstance(it, dict)):
            return "".join(it.get("text", "") if isinstance(it, dict) else str(it) for it in value)
        # 其他 list（可能是多值）
        return ", ".join(str(it) for it in value)
    if isinstance(value, dict):
        return str(value.get("text") or json.dumps(value, ensure_ascii=False))
    return str(value)


class FeishuClient:
    """飞书 API Client。"""

    def __init__(self, app_id: str = "", app_secret: str = "") -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self._token: str = ""
        self._token_expires_at: float = 0

        # 如果未传入，自动从平台配置读取
        if not self.app_id or not self.app_secret:
            self._load_from_config()

    def _load_from_config(self) -> None:
        """凭证来源优先级：平台配置（llm_config.json + 环境变量）→ 旧版 config/ai.json。

        平台配置由 load_config 统一处理优先级（环境变量 > 配置文件 > 默认值），
        因此环境变量 INSIGHT_EYE_AI_FEISHU_APP_ID/SECRET 的优先级最高。
        """
        try:
            from insight_aitest.platform.services.kb.deps import get_llm_config

            cfg = get_llm_config()
            if cfg.feishu_app_id and cfg.feishu_app_secret:
                self.app_id = cfg.feishu_app_id
                self.app_secret = cfg.feishu_app_secret
                return
        except Exception as e:
            logger.warning(f"读取平台配置中的飞书凭证失败: {e}")

        # 向后兼容：旧版独立配置文件 config/ai.json（相对进程工作目录）
        cfg_path = os.path.join(os.getcwd(), "config", "ai.json")
        if os.path.exists(cfg_path):
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    feishu_cfg = data.get("feishu", {})
                    self.app_id = feishu_cfg.get("app_id", "")
                    self.app_secret = feishu_cfg.get("app_secret", "")
            except Exception as e:
                logger.warning(f"读取 config/ai.json 失败: {e}")

    def is_configured(self) -> bool:
        return bool(self.app_id and self.app_secret)

    def get_token(self) -> str:
        """获取并自动缓存 tenant_access_token。提前 300 秒刷新。"""
        now = time.time()
        if self._token and now < (self._token_expires_at - 300):
            return self._token

        if not self.is_configured():
            raise ValueError("未配置飞书 App ID 或 App Secret")

        url = f"{FEISHU_API_BASE}/auth/v3/tenant_access_token/internal"
        res = httpx.post(url, json={"app_id": self.app_id, "app_secret": self.app_secret}, timeout=15)
        res.raise_for_status()
        data = res.json()
        if data.get("code") != 0:
            raise RuntimeError(f"获取飞书 token 失败: {data.get('msg')} (code: {data.get('code')})")

        self._token = data["tenant_access_token"]
        expire = data.get("expire", 7200)
        self._token_expires_at = now + expire
        return self._token

    def _headers(self) -> dict[str, str]:
        token = self.get_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        }

    def _raise_feishu(self, res: httpx.Response, action: str) -> dict[str, Any]:
        """校验 HTTP 状态与飞书业务 code，失败时抛出携带 code/msg 的异常。

        飞书在 HTTP 400/403/404 等场景下仍会返回含业务 code 与 msg 的 JSON，
        直接用 raise_for_status 会丢掉这些排查关键信息（如权限缺失的 99991672）。
        """
        if res.status_code >= 400:
            code: Any = -1
            msg = res.text[:500]
            try:
                body = res.json()
                code = body.get("code", code)
                msg = body.get("msg") or (body.get("error") or {}).get("msg") or msg
            except Exception:
                pass
            raise RuntimeError(f"{action} 失败: HTTP {res.status_code} code={code} msg={msg}")
        try:
            data = res.json()
        except Exception as e:
            raise RuntimeError(f"{action} 失败: 响应非 JSON ({e}): {res.text[:200]}")
        if data.get("code") != 0:
            raise RuntimeError(f"{action} 失败: code={data.get('code')} msg={data.get('msg')}")
        return data

    # ===== 知识库空间与节点 =====

    def list_spaces(self) -> list[dict[str, Any]]:
        """获取应用有权限访问的知识库空间列表。"""
        url = f"{FEISHU_API_BASE}/wiki/v2/spaces"
        spaces: list[dict[str, Any]] = []
        page_token = ""
        while True:
            params: dict[str, Any] = {"page_size": 50}
            if page_token:
                params["page_token"] = page_token
            res = httpx.get(url, headers=self._headers(), params=params, timeout=15)
            res.raise_for_status()
            data = res.json()
            if data.get("code") != 0:
                # 不再静默返回空列表：权限不足/凭证错误等需显式暴露给调用方
                raise RuntimeError(
                    f"飞书知识库空间列表接口报错 code={data.get('code')} msg={data.get('msg')}"
                )
            items = data.get("data", {}).get("items", [])
            spaces.extend(items)
            if not data.get("data", {}).get("has_more"):
                break
            page_token = data.get("data", {}).get("page_token", "")
        return spaces

    def get_space(self, space_id: str) -> dict[str, Any] | None:
        """获取单个空间详情。"""
        url = f"{FEISHU_API_BASE}/wiki/v2/spaces/{space_id}"
        res = httpx.get(url, headers=self._headers(), timeout=15)
        data = self._raise_feishu(res, f"获取空间详情({space_id})")
        return data.get("data", {}).get("space")

    def batch_query_metas(
        self,
        tokens_and_types: list[tuple[str, str]],
        batch_size: int = 200,
    ) -> dict[str, dict[str, Any]]:
        """批量查询云文档元数据（latest_modify_time 等），用于增量前置过滤。

        drive/v1/metas/batch_query 单次上限 200 条（实测 300 会 field validation failed）。
        超过则自动分批。返回值 key 是 obj_token，value 是完整 meta 字典，
        至少包含 latest_modify_time（Unix 秒，str 或 int）、create_time、title、owner_id。

        入参格式：[(obj_token, obj_type), ...]
        obj_type ∈ {doc, docx, sheet, bitable, file, slides}。
        """
        result: dict[str, dict[str, Any]] = {}
        if not tokens_and_types:
            return result

        for i in range(0, len(tokens_and_types), batch_size):
            chunk = tokens_and_types[i : i + batch_size]
            body = {
                "request_docs": [
                    {"doc_token": tok, "doc_type": t} for tok, t in chunk
                ],
                "with_url": False,
            }
            url = f"{FEISHU_API_BASE}/drive/v1/metas/batch_query"
            res = httpx.post(url, headers=self._headers(), json=body, timeout=30)
            data = self._raise_feishu(res, f"批量查询文档元数据({i}-{i + len(chunk)})")
            for meta in data.get("data", {}).get("metas", []):
                result[meta["doc_token"]] = meta
        return result

    def list_space_nodes(self, space_id: str, parent_node_token: str | None = None) -> list[dict[str, Any]]:
        """获取知识库空间下的节点列表（支持按 parent_node_token 查询子节点）。"""
        url = f"{FEISHU_API_BASE}/wiki/v2/spaces/{space_id}/nodes"
        nodes: list[dict[str, Any]] = []
        page_token = ""
        while True:
            params: dict[str, Any] = {"page_size": 50}
            if parent_node_token:
                params["parent_node_token"] = parent_node_token
            if page_token:
                params["page_token"] = page_token
            res = httpx.get(url, headers=self._headers(), params=params, timeout=15)
            res.raise_for_status()
            data = res.json()
            if data.get("code") != 0:
                logger.error(f"获取知识库节点失败: {data}")
                break
            items = data.get("data", {}).get("items", [])
            nodes.extend(items)
            if not data.get("data", {}).get("has_more"):
                break
            page_token = data.get("data", {}).get("page_token", "")
        return nodes

    def get_all_nodes_recursive(self, space_id: str) -> list[dict[str, Any]]:
        """递归遍历该空间下的所有节点，返回扁平列表（每个节点含 parent_node_token 标识层级）。"""
        all_nodes: list[dict[str, Any]] = []
        # 1. 获取根节点列表
        root_nodes = self.list_space_nodes(space_id)
        queue = list(root_nodes)
        visited = set()

        while queue:
            node = queue.pop(0)
            token = node.get("node_token")
            if token in visited:
                continue
            visited.add(token)
            all_nodes.append(node)

            # 如果有子节点，拉取并入队
            if node.get("has_child"):
                children = self.list_space_nodes(space_id, parent_node_token=token)
                queue.extend(children)

        return all_nodes

    # ===== 文档内容拉取 =====

    def get_docx_raw_content(self, document_id: str) -> str:
        """获取 Docx 文档纯文本/原始内容。"""
        url = f"{FEISHU_API_BASE}/docx/v1/documents/{document_id}/raw_content"
        res = httpx.get(url, headers=self._headers(), timeout=30)
        data = self._raise_feishu(res, f"获取 docx 原始内容({document_id})")
        return data.get("data", {}).get("content", "")

    def get_doc_raw_content(self, document_id: str) -> str:
        """获取旧版 Doc（obj_type=doc）纯文本内容。

        旧版文档 token 无法通过 docx/v1 接口读取（返回 404 code=1770002），
        须走 doc/v2 raw_content；该接口不需要额外的导出权限。
        """
        url = f"{FEISHU_API_BASE}/doc/v2/{document_id}/raw_content"
        res = httpx.get(url, headers=self._headers(), timeout=30)
        data = self._raise_feishu(res, f"获取旧版 doc 原始内容({document_id})")
        return data.get("data", {}).get("content", "")

    def get_docx_blocks(self, document_id: str) -> list[dict[str, Any]]:
        """获取 Docx 文档的所有块结构（可转为标准 Markdown）。"""
        url = f"{FEISHU_API_BASE}/docx/v1/documents/{document_id}/blocks"
        blocks: list[dict[str, Any]] = []
        page_token = ""
        while True:
            params: dict[str, Any] = {"page_size": 100}
            if page_token:
                params["page_token"] = page_token
            res = httpx.get(url, headers=self._headers(), params=params, timeout=30)
            data = self._raise_feishu(res, f"获取 docx 块({document_id})")
            items = data.get("data", {}).get("items", [])
            blocks.extend(items)
            if not data.get("data", {}).get("has_more"):
                break
            page_token = data.get("data", {}).get("page_token", "")
        return blocks

    def download_file(self, file_token: str) -> bytes:
        """下载云文档中的文件（如 PDF、DOCX、XLSX 等）。"""
        url = f"{FEISHU_API_BASE}/drive/v1/files/{file_token}/download"
        res = httpx.get(url, headers=self._headers(), timeout=60)
        if res.status_code >= 400:
            if res.status_code == 403:
                raise RuntimeError(
                    f"下载文件({file_token}) 权限不足(HTTP 403)。"
                    "该文件在飞书知识库/云空间中可能开启了「禁止查看者下载/导出」安全设置，"
                    "请在飞书空间成员设置中将应用机器人角色设为「管理员」或在节点权限中允许下载。"
                )
            self._raise_feishu(res, f"下载文件({file_token})")
        return res.content

    def get_sheet_as_xlsx(self, spreadsheet_token: str) -> bytes:
        """走 sheets/v3 原生读取接口将电子表格导出为 xlsx 字节流（每张工作表一个工作表）。

        不依赖 drive:export:readonly / docs:document:export 导出权限，
        仅需 sheets:spreadsheet / sheets:spreadsheet:readonly 读取权限——
        该权限随 wiki 空间成员自动继承，不会出现 Drive 导出的 1069902 文档级 ACL 问题。
        """
        from io import BytesIO

        from openpyxl import Workbook

        # 1. 列出所有工作表
        query_url = f"{FEISHU_API_BASE}/sheets/v3/spreadsheets/{spreadsheet_token}/sheets/query"
        q_res = httpx.get(query_url, headers=self._headers(), timeout=30)
        sheets_data = self._raise_feishu(q_res, f"列出电子表格工作表({spreadsheet_token})")
        sheets = sheets_data.get("data", {}).get("sheets", [])
        if not sheets:
            raise RuntimeError(f"电子表格无可读取工作表: {spreadsheet_token}")

        wb = Workbook()
        wb.remove(wb.active)
        for sheet in sheets:
            sid = sheet["sheet_id"]
            # 2. 读取单元格值（默认 FormattedValue 即显示给用户的格式）
            val_url = f"{FEISHU_API_BASE}/sheets/v2/spreadsheets/{spreadsheet_token}/values/{sid}"
            try:
                v_res = httpx.get(val_url, headers=self._headers(),
                                  params={"valueRenderOption": "FormattedValue"}, timeout=30)
                v_data = self._raise_feishu(v_res, f"读取工作表 {sid} 的值")
            except RuntimeError as e:
                # 单张工作表读取失败（如 90215 not found sheetId）不该让整个 spreadsheet 挂
                logger.warning("工作表 %s(%s) 读取失败，跳过: %s", sheet.get("title", sid), sid, e)
                continue
            values = v_data.get("data", {}).get("valueRange", {}).get("values", [])

            ws = wb.create_sheet(title=_safe_sheet_name(sheet.get("title") or "未命名"))
            for row in values:
                ws.append([_sheet_cell(c) for c in row])
        buf = BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def export_sheet_to_xlsx(self, spreadsheet_token: str) -> bytes:
        """调用飞书导出任务将 Sheet / 电子表格导出为 xlsx 字节流。"""
        # 1. 创建导出任务
        create_url = f"{FEISHU_API_BASE}/drive/v1/export_tasks"
        body = {
            "file_extension": "xlsx",
            "token": spreadsheet_token,
            "type": "sheet",
        }
        res = httpx.post(create_url, headers=self._headers(), json=body, timeout=20)
        data = self._raise_feishu(res, f"创建表格导出任务({spreadsheet_token})")
        ticket = data.get("data", {}).get("ticket")

        # 2. 轮询任务状态
        query_url = f"{FEISHU_API_BASE}/drive/v1/export_tasks/{ticket}?token={spreadsheet_token}"
        file_token = ""
        for _ in range(30):
            time.sleep(1)
            q_res = httpx.get(query_url, headers=self._headers(), timeout=15)
            q_data = self._raise_feishu(q_res, "查询表格导出任务状态")
            job_status = q_data.get("data", {}).get("result", {}).get("job_status")
            if job_status == 0:  # 成功
                file_token = q_data.get("data", {}).get("result", {}).get("file_token")
                break
            elif job_status != 1 and job_status != 2:  # 非排队/进行中
                raise RuntimeError(f"导出任务异常: {job_status}")

        if not file_token:
            raise TimeoutError("导出表格超时")

        # 3. 下载导出生成的 xlsx 文件
        dl_url = f"{FEISHU_API_BASE}/drive/v1/export_tasks/file/{file_token}/download"
        dl_res = httpx.get(dl_url, headers=self._headers(), timeout=60)
        if dl_res.status_code >= 400:
            self._raise_feishu(dl_res, "下载导出文件")
        return dl_res.content

    # ===== 多维表格（bitable）=====

    def list_bitable_tables(self, app_token: str) -> list[dict[str, Any]]:
        """列出多维表格中的所有数据表。"""
        url = f"{FEISHU_API_BASE}/bitable/v1/apps/{app_token}/tables"
        tables: list[dict[str, Any]] = []
        page_token = ""
        while True:
            params: dict[str, Any] = {"page_size": 100}
            if page_token:
                params["page_token"] = page_token
            res = httpx.get(url, headers=self._headers(), params=params, timeout=30)
            data = self._raise_feishu(res, f"列出多维表格数据表({app_token})")
            d = data.get("data", {})
            tables.extend(d.get("items", []))
            if not d.get("has_more"):
                break
            page_token = d.get("page_token", "")
        return tables

    def get_bitable_records(self, app_token: str, table_id: str) -> list[dict[str, Any]]:
        """分页拉取多维表格某数据表的全部记录。"""
        url = f"{FEISHU_API_BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/records"
        records: list[dict[str, Any]] = []
        page_token = ""
        while True:
            params: dict[str, Any] = {"page_size": 500}
            if page_token:
                params["page_token"] = page_token
            res = httpx.get(url, headers=self._headers(), params=params, timeout=30)
            data = self._raise_feishu(res, f"拉取多维表格记录({table_id})")
            d = data.get("data", {})
            records.extend(d.get("items", []))
            if not d.get("has_more"):
                break
            page_token = d.get("page_token", "")
        return records

    def get_bitable_as_xlsx(self, app_token: str) -> bytes:
        """将多维表格所有数据表导出为 xlsx 字节流（每张表一个工作表）。

        不依赖 drive:export:readonly 导出权限，仅需多维表格读取权限。
        """
        from io import BytesIO

        from openpyxl import Workbook

        wb = Workbook()
        wb.remove(wb.active)
        for table in self.list_bitable_tables(app_token):
            records = self.get_bitable_records(app_token, table["table_id"])
            ws = wb.create_sheet(title=_safe_sheet_name(table.get("name") or "未命名"))
            headers: list[str] = []
            for rec in records:
                for key in rec.get("fields") or {}:
                    if key not in headers:
                        headers.append(key)
            if headers:
                ws.append(headers)
            for rec in records:
                fields = rec.get("fields") or {}
                ws.append([_bitable_cell(fields.get(h)) for h in headers])
        if not wb.sheetnames:
            raise RuntimeError(f"多维表格无可导出数据表: {app_token}")
        buf = BytesIO()
        wb.save(buf)
        return buf.getvalue()

