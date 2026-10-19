# -*- coding: utf-8 -*-
"""飞书知识库空间同步服务。

负责：
1. 镜像飞书 Wiki 目录树到 kb_folders；
2. 过滤 ppt；将 doc/docx 转换为 md，sheet 转换为 xlsx，pdf 保存源格式；
3. 将文件写入独立目录 ~/.insight_eye/ai_docs/feishu/；
4. 注册 Document 并触发后台分块与向量化处理流水线；
5. 提供主动同步（增量比对）能力。
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Any

from insight_aitest.modules.ai.backend.deps import get_config, get_kb_db, get_llm, get_vector_store
from insight_aitest.platform.services.feishu import FeishuClient, docx_blocks_to_markdown
from insight_aitest.platform.services.kb.ingest import process_document

logger = logging.getLogger(__name__)

# Windows 文件/路径非法字符：\ / : * ? " < > |
_ILLEGAL_PATH_CHARS = re.compile(r'[\\/:*?"<>|]')


def _sanitize_filename(name: str) -> str:
    """清洗 Windows 非法文件名字符，避免 Path 把 / 当目录分隔。

    飞书文档标题常含 '/'（如 "输入/输出卡"），在 Windows 上直接当文件名会被
    Path 解析为多层目录导致 FileNotFoundError。
    """
    cleaned = _ILLEGAL_PATH_CHARS.sub("_", name)
    # 去掉尾部空白和点（Windows 不允许文件名以 . 或空格结尾）
    cleaned = cleaned.rstrip(" .")
    return cleaned or "未命名"


class FeishuSyncService:
    def __init__(self, client: FeishuClient | None = None) -> None:
        self.client = client or FeishuClient()
        self.db = get_kb_db()
        self.cfg = get_config()

    def get_feishu_docs_dir(self) -> Path:
        """获取飞书专有存储目录 ~/.insight_eye/ai_docs/feishu/"""
        base = Path(self.cfg.docs_dir)
        feishu_dir = base / "feishu"
        feishu_dir.mkdir(parents=True, exist_ok=True)
        return feishu_dir

    def sync_space(self, space_id: str, project_id: int | None = None) -> dict[str, Any]:
        """同步指定飞书知识库空间。"""
        if not self.client.is_configured():
            raise ValueError("飞书应用凭证未配置")

        space_info = self.client.get_space(space_id)
        space_name = space_info.get("name", f"飞书知识库-{space_id}") if space_info else f"飞书知识库-{space_id}"

        # 1. 确保顶级根目录：飞书知识库 - {space_name}
        root_folder = self.db.find_folder_by_external_id(f"space_{space_id}")
        if not root_folder:
            root_folder = self.db.create_folder(
                name=f"飞书 - {space_name}",
                parent_id=None,
                project_id=project_id,
                source_type="feishu",
                external_id=f"space_{space_id}",
            )

        # 2. 获取该空间所有节点（递归扁平列表）
        nodes = self.client.get_all_nodes_recursive(space_id)

        # 3. 建立映射：node_token -> folder_id
        folder_token_map: dict[str, int] = {}

        # 飞书节点有两种情况：
        # - 有些节点本身是目录/父节点（has_child=True）
        # - 有些节点是文档同时包含子文档
        # 先处理所有带子节点的目录创建
        for node in nodes:
            token = node.get("node_token")
            title = node.get("title", "未命名目录")
            has_child = node.get("has_child", False)

            # 如果该节点有子节点，为它在系统中建立对应的 Folder
            if has_child:
                existing_folder = self.db.find_folder_by_external_id(f"node_{token}")
                if not existing_folder:
                    # 确定 parent_id
                    p_token = node.get("parent_node_token")
                    p_id = folder_token_map.get(p_token, root_folder.id) if p_token else root_folder.id
                    f = self.db.create_folder(
                        name=title,
                        parent_id=p_id,
                        project_id=project_id,
                        source_type="feishu",
                        external_id=f"node_{token}",
                    )
                    folder_token_map[token] = f.id
                else:
                    folder_token_map[token] = existing_folder.id

        # 4. 同步文档内容
        synced_count = 0
        skipped_count = 0
        ignored_count = 0

        feishu_dir = self.get_feishu_docs_dir()

        # 4a. 先批量查所有节点的 latest_modify_time，用于元数据前置增量过滤。
        # drive/v1/metas/batch_query 单次上限 200，自动分批；实测全量 720 节点 ≈ 9 秒。
        # 如果 meta.latest_modify_time 与本地存的 source_modified_at 完全相同，
        # 直接跳过该节点，避免后续 docx/v1 blocks / sheets/v2 values 等飞书内容 API 调用。
        try:
            meta_map = self.client.batch_query_metas(
                [
                    (n["obj_token"], n["obj_type"])
                    for n in nodes
                    if n.get("obj_token")
                    and n.get("obj_type") in ("doc", "docx", "sheet", "bitable", "file", "slides")
                ],
                batch_size=200,
            )
            logger.info(f"批量拉取元数据 {len(meta_map)} 条，用于增量前置过滤")
        except Exception as e:
            logger.warning(f"批量查询元数据失败，退化为全量内容比对: {e}")
            meta_map = {}

        for node in nodes:
            token = node.get("node_token")
            obj_type = node.get("obj_type")  # docx, sheet, bitable, file...
            title = node.get("title", "未命名文档").strip()
            obj_token = node.get("obj_token")

            # 过滤 ppt / presentation
            if obj_type in ("slides", "ppt", "pptx") or title.lower().endswith((".ppt", ".pptx")):
                ignored_count += 1
                logger.info(f"过滤 PPT 文档: {title}")
                continue

            # 确定所属目录 folder_id
            p_token = node.get("parent_node_token")
            folder_id = folder_token_map.get(p_token, root_folder.id) if p_token else root_folder.id

            source_url = f"https://feishu.cn/wiki/{token}"
            external_id = f"wiki_{token}"

            try:
                # 检查是否已有文档
                existing_doc = self.db.find_by_external_id(external_id)

                # 4b. 元数据前置增量过滤：existing_doc 存在且 source_modified_at 非空，
                # 并且飞书侧 latest_modify_time 完全一致 → 跳过，省掉内容 API 调用。
                # 只有两条件都满足才 skip；任一缺失则回退到 content_hash 比对（向后兼容）。
                meta = meta_map.get(obj_token) if obj_token else None
                remote_modified_at = None
                if meta:
                    t = meta.get("latest_modify_time")
                    remote_modified_at = str(t) if t is not None else None
                if (
                    existing_doc
                    and existing_doc.source_modified_at
                    and remote_modified_at
                    and existing_doc.source_modified_at == remote_modified_at
                ):
                    skipped_count += 1
                    continue

                file_bytes: bytes = b""
                target_ext = ""
                content_type = ""

                # 分流处理类型
                if obj_type == "docx":
                    # docx 转标准 Markdown
                    blocks = self.client.get_docx_blocks(obj_token)
                    md_text = docx_blocks_to_markdown(blocks)
                    if not md_text:
                        # 降级尝试 raw_content
                        md_text = self.client.get_docx_raw_content(obj_token)
                    if not md_text.startswith("#"):
                        md_text = f"# {title}\n\n" + md_text
                    file_bytes = md_text.encode("utf-8")
                    target_ext = ".md"
                    content_type = "text/markdown"
                elif obj_type == "doc":
                    # 旧版 Doc：token 无法用 docx 接口读取（会 404），走 doc/v2 取纯文本
                    md_text = self.client.get_doc_raw_content(obj_token)
                    if not md_text.startswith("#"):
                        md_text = f"# {title}\n\n" + md_text
                    file_bytes = md_text.encode("utf-8")
                    target_ext = ".md"
                    content_type = "text/markdown"
                elif obj_type == "sheet":
                    # 电子表格：走 sheets/v3 原生读取接口生成 xlsx，避免 Drive 导出的
                    # 文档级 ACL 1069902 问题（wiki 空间成员不会自动继承到 sheet 的 Drive ACL）
                    file_bytes = self.client.get_sheet_as_xlsx(obj_token)
                    target_ext = ".xlsx"
                    content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                elif obj_type == "bitable":
                    # 多维表格：走 bitable 读取接口生成 xlsx，无需导出权限
                    file_bytes = self.client.get_bitable_as_xlsx(obj_token)
                    target_ext = ".xlsx"
                    content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                elif obj_type == "file":
                    # 文件类型，检查是否为 pdf
                    if title.lower().endswith(".pdf"):
                        file_bytes = self.client.download_file(obj_token)
                        target_ext = ".pdf"
                        content_type = "application/pdf"
                    else:
                        # 其他类型暂时跳过
                        ignored_count += 1
                        continue
                else:
                    # 其他未知类型跳过
                    ignored_count += 1
                    continue

                if not file_bytes:
                    skipped_count += 1
                    continue

                content_hash = hashlib.sha256(file_bytes).hexdigest()

                if existing_doc:
                    # 比对内容哈希，相同则跳过。
                    # 同时补上 source_modified_at（若此前为空），让下次同步能走元数据前置过滤。
                    if existing_doc.content_hash == content_hash:
                        if remote_modified_at and not existing_doc.source_modified_at:
                            with self.db.get_connection() as conn:
                                conn.execute(
                                    "UPDATE documents SET source_modified_at = ? WHERE id = ?",
                                    (remote_modified_at, existing_doc.id),
                                )
                        skipped_count += 1
                        continue

                    # 内容有变化，覆盖写入并重新索引
                    storage_path = Path(existing_doc.storage_path)
                    storage_path.write_bytes(file_bytes)
                    with self.db.get_connection() as conn:
                        conn.execute(
                            "UPDATE documents SET content_hash = ?, char_count = ?, source_modified_at = ? WHERE id = ?",
                            (content_hash, len(file_bytes), remote_modified_at, existing_doc.id),
                        )
                    from insight_aitest.modules.kb.backend.routes.documents import _reindex_in_bg

                    _reindex_in_bg(existing_doc.id, self.db)
                    synced_count += 1
                else:
                    # 新增文档
                    sanitized = _sanitize_filename(title)
                    safe_title = sanitized if sanitized.endswith(target_ext) else f"{sanitized}{target_ext}"
                    storage_path = feishu_dir / f"{content_hash[:16]}_{safe_title}"
                    storage_path.write_bytes(file_bytes)

                    doc_id = self.db.create_document(
                        filename=safe_title,
                        storage_path=str(storage_path),
                        content_hash=content_hash,
                        mime_type=content_type,
                        project_id=project_id,
                        folder_id=folder_id,
                        source_type="feishu",
                        source_url=source_url,
                        external_id=external_id,
                        source_modified_at=remote_modified_at,
                    )
                    # 触发后台分块与向量化
                    llm = get_llm()
                    vs = get_vector_store()
                    process_document(doc_id, self.db, vs, llm, self.cfg)
                    synced_count += 1

            except Exception as e:
                logger.error(f"处理飞书节点 {title} 失败: {e}", exc_info=True)
                skipped_count += 1

        return {
            "space_id": space_id,
            "space_name": space_name,
            "root_folder_id": root_folder.id,
            "synced_count": synced_count,
            "skipped_count": skipped_count,
            "ignored_count": ignored_count,
            "total_nodes": len(nodes),
        }
