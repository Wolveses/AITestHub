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
from pathlib import Path
from typing import Any

from insight_aitest.modules.ai.backend.deps import get_config, get_kb_db, get_llm, get_vector_store
from insight_aitest.platform.services.feishu import FeishuClient, docx_blocks_to_markdown
from insight_aitest.platform.services.kb.ingest import process_document

logger = logging.getLogger(__name__)


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

                file_bytes: bytes = b""
                target_ext = ""
                content_type = ""

                # 分流处理类型
                if obj_type in ("docx", "doc"):
                    # doc/docx 转标准 Markdown
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
                elif obj_type in ("sheet", "bitable"):
                    # 表格转换为 xlsx
                    file_bytes = self.client.export_sheet_to_xlsx(obj_token)
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
                    # 比对内容哈希，相同则跳过
                    if existing_doc.content_hash == content_hash:
                        skipped_count += 1
                        continue

                    # 内容有变化，覆盖写入并重新索引
                    storage_path = Path(existing_doc.storage_path)
                    storage_path.write_bytes(file_bytes)
                    with self.db.get_connection() as conn:
                        conn.execute(
                            "UPDATE documents SET content_hash = ?, char_count = ? WHERE id = ?",
                            (content_hash, len(file_bytes), existing_doc.id),
                        )
                    from insight_aitest.modules.kb.backend.routes.documents import _reindex_in_bg

                    _reindex_in_bg(existing_doc.id, self.db)
                    synced_count += 1
                else:
                    # 新增文档
                    safe_title = title if title.endswith(target_ext) else f"{title}{target_ext}"
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
