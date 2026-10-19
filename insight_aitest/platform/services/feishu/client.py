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
        if res.status_code == 200:
            data = res.json()
            if data.get("code") == 0:
                return data.get("data", {}).get("space")
        return None

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
        res.raise_for_status()
        data = res.json()
        if data.get("code") != 0:
            raise RuntimeError(f"获取 docx 失败: {data.get('msg')}")
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
            res.raise_for_status()
            data = res.json()
            if data.get("code") != 0:
                break
            items = data.get("data", {}).get("items", [])
            blocks.extend(items)
            if not data.get("data", {}).get("has_more"):
                break
            page_token = data.get("data", {}).get("page_token", "")
        return blocks

    def download_file(self, file_token: str) -> bytes:
        """下载云文档中的文件（如 PDF）。"""
        url = f"{FEISHU_API_BASE}/drive/v1/files/{file_token}/download"
        res = httpx.get(url, headers=self._headers(), timeout=60)
        res.raise_for_status()
        return res.content

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
        res.raise_for_status()
        data = res.json()
        if data.get("code") != 0:
            raise RuntimeError(f"创建导出任务失败: {data.get('msg')}")
        ticket = data.get("data", {}).get("ticket")

        # 2. 轮询任务状态
        query_url = f"{FEISHU_API_BASE}/drive/v1/export_tasks/{ticket}?token={spreadsheet_token}"
        file_token = ""
        for _ in range(30):
            time.sleep(1)
            q_res = httpx.get(query_url, headers=self._headers(), timeout=15)
            q_res.raise_for_status()
            q_data = q_res.json()
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
        dl_res.raise_for_status()
        return dl_res.content

