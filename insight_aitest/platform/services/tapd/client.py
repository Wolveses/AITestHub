# -*- coding: utf-8 -*-
"""TAPD OpenAPI 客户端封装。

只封装缺陷同步需要的两个接口：缺陷列表（/bugs）与缺陷评论（/comments）。
认证走 HTTP Basic Auth（api_user:api_password），凭证只出现在 Authorization 头，
任何日志与异常消息都不得输出凭证。
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.tapd.cn"
_MAX_RETRIES = 2  # 首次失败后最多再重试 2 次（退避 1s、2s）
_RETRY_BACKOFF = (1.0, 2.0)


class TapdError(Exception):
    """TAPD 接口调用异常。消息中只允许出现接口路径、HTTP 状态与 info 文本。"""


class TapdClient:
    def __init__(
        self,
        auth_user: str,
        auth_pwd: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 20.0,
    ) -> None:
        self._base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self._client = httpx.Client(
            auth=(auth_user, auth_pwd),
            timeout=timeout,
            headers={"Accept": "application/json"},
        )

    @classmethod
    def from_config(cls, cfg: Any) -> "TapdClient | None":
        """从 LLMConfig 构造客户端；凭证为空返回 None。"""
        auth_user = str(getattr(cfg, "tapd_auth_user", "") or "")
        auth_pwd = str(getattr(cfg, "tapd_auth_pwd", "") or "")
        if not auth_user or not auth_pwd:
            return None
        base_url = str(getattr(cfg, "tapd_base_url", "") or DEFAULT_BASE_URL)
        return cls(auth_user, auth_pwd, base_url)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "TapdClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ===== 底层请求 =====

    def _request(self, path: str, params: dict[str, Any]) -> httpx.Response:
        """GET 请求：5xx 与超时重试 2 次（1s、2s 退避），4xx 直接失败。

        异常消息只包含 path 与状态码，不包含认证信息（认证在 header，不在 params）。
        """
        url = f"{self._base_url}{path}"
        last_error: TapdError | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                res = self._client.get(url, params=params)
            except httpx.TimeoutException:
                last_error = TapdError(f"TAPD 请求超时 path={path}")
                logger.warning("TAPD 请求超时 path=%s attempt=%d", path, attempt + 1)
            except httpx.HTTPError as exc:
                last_error = TapdError(f"TAPD 请求失败 path={path} error={type(exc).__name__}")
                logger.warning(
                    "TAPD 请求异常 path=%s attempt=%d error=%s",
                    path,
                    attempt + 1,
                    type(exc).__name__,
                )
            else:
                if res.status_code == 429:
                    # TAPD 按分钟限流：退避后重试，仍失败则上报
                    if attempt < _MAX_RETRIES:
                        wait = 20 * (attempt + 1)
                        logger.warning(
                            "TAPD 请求被限流 path=%s attempt=%d，%ds 后重试",
                            path,
                            attempt + 1,
                            wait,
                        )
                        time.sleep(wait)
                        continue
                    raise TapdError(f"TAPD 请求被限流 path={path} HTTP 429")
                if res.status_code < 400:
                    return res
                if res.status_code < 500:
                    # 4xx 不重试
                    raise TapdError(f"TAPD 请求失败 path={path} HTTP {res.status_code}")
                body = (res.text or "")[:200]
                last_error = TapdError(
                    f"TAPD 请求失败 path={path} HTTP {res.status_code}: {body}"
                )
                logger.warning(
                    "TAPD 服务端错误 path=%s attempt=%d HTTP %d",
                    path,
                    attempt + 1,
                    res.status_code,
                )
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_BACKOFF[min(attempt, len(_RETRY_BACKOFF) - 1)])
        raise last_error or TapdError(f"TAPD 请求失败 path={path}")

    def _get_json(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        res = self._request(path, params)
        try:
            payload = res.json()
        except ValueError:
            raise TapdError(f"TAPD 返回非 JSON path={path} HTTP {res.status_code}")
        if not isinstance(payload, dict):
            raise TapdError(f"TAPD 返回格式异常 path={path} HTTP {res.status_code}")
        info = payload.get("info")
        if info != "success":
            raise TapdError(
                f"TAPD 接口返回失败 path={path} HTTP {res.status_code}: {str(info)[:200]}"
            )
        return payload

    # ===== 业务接口 =====

    def list_bugs(
        self,
        workspace_id: str,
        created_from: str,
        created_to: str,
        page_size: int = 100,
    ) -> list[dict]:
        """按创建时间区间拉取缺陷列表（自动翻页），返回扁平后的 Bug dict 列表。"""
        bugs: list[dict] = []
        page = 1
        while True:
            payload = self._get_json(
                "/bugs",
                {
                    "workspace_id": workspace_id,
                    "created": f"{created_from}~{created_to}",
                    "limit": page_size,
                    "page": page,
                    "order": "created desc",
                },
            )
            items = payload.get("data") or []
            if not isinstance(items, list):
                items = []
            for item in items:
                bug = item.get("Bug") if isinstance(item, dict) else None
                if isinstance(bug, dict):
                    bugs.append(bug)
            if len(items) < page_size:
                break
            page += 1
        logger.info("TAPD 缺陷拉取完成 workspace_id=%s count=%d", workspace_id, len(bugs))
        return bugs

    def list_comments(
        self,
        workspace_id: str,
        bug_id: str,
        page_size: int = 100,
    ) -> list[dict]:
        """拉取某条缺陷的全部评论（自动翻页），返回扁平后的 Comment dict 列表。"""
        comments: list[dict] = []
        page = 1
        while True:
            payload = self._get_json(
                "/comments",
                {
                    "workspace_id": workspace_id,
                    "entry_id": bug_id,
                    "entry_type": "bug",
                    "limit": page_size,
                    "page": page,
                },
            )
            items = payload.get("data") or []
            if not isinstance(items, list):
                items = []
            for item in items:
                comment = item.get("Comment") if isinstance(item, dict) else None
                if isinstance(comment, dict):
                    comments.append(comment)
            if len(items) < page_size:
                break
            page += 1
        logger.info(
            "TAPD 评论拉取完成 workspace_id=%s bug_id=%s count=%d",
            workspace_id,
            bug_id,
            len(comments),
        )
        return comments

    def list_tcase_categories(self, workspace_id: str, page_size: int = 200) -> list[dict]:
        """拉取测试用例目录（自动翻页），返回扁平后的 TcaseCategory dict 列表。"""
        categories: list[dict] = []
        page = 1
        while True:
            payload = self._get_json(
                "/tcase_categories",
                {
                    "workspace_id": workspace_id,
                    "limit": page_size,
                    "page": page,
                },
            )
            items = payload.get("data") or []
            if not isinstance(items, list):
                items = []
            for item in items:
                cat = item.get("TcaseCategory") if isinstance(item, dict) else None
                if isinstance(cat, dict):
                    categories.append(cat)
            if len(items) < page_size:
                break
            page += 1
        logger.info("TAPD 用例目录拉取完成 workspace_id=%s count=%d", workspace_id, len(categories))
        return categories

    def list_tcases(
        self,
        workspace_id: str,
        created_from: str | None = None,
        created_to: str | None = None,
        modified_from: str | None = None,
        modified_to: str | None = None,
        page_size: int = 200,
        limit: int | None = None,
    ) -> list[dict]:
        """拉取测试用例（自动翻页），返回扁平后的 Tcase dict 列表。

        ``created`` 与 ``modified`` 二选一：首次回填按创建时间，增量按修改时间；
        ``limit`` 为本次最多拉取的条数（用于首次小批量验证）。
        """
        cases: list[dict] = []
        page = 1
        while True:
            params: dict[str, Any] = {
                "workspace_id": workspace_id,
                "limit": page_size,
                "page": page,
                "order": "created desc",
            }
            if created_from and created_to:
                params["created"] = f"{created_from}~{created_to}"
            elif modified_from and modified_to:
                params["modified"] = f"{modified_from}~{modified_to}"
            payload = self._get_json("/tcases", params)
            items = payload.get("data") or []
            if not isinstance(items, list):
                items = []
            for item in items:
                case = item.get("Tcase") if isinstance(item, dict) else None
                if isinstance(case, dict):
                    cases.append(case)
                    if limit is not None and len(cases) >= limit:
                        break
            if len(items) < page_size:
                break
            if limit is not None and len(cases) >= limit:
                break
            page += 1
            # 主动节流，避免触发 TAPD 每分钟调用上限
            time.sleep(0.4)
        logger.info("TAPD 用例拉取完成 workspace_id=%s count=%d", workspace_id, len(cases))
        return cases
