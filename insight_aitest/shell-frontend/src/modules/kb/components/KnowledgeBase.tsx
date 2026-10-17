import React, { useEffect, useRef, useState } from 'react';
import { AlertTriangle, Upload, Folder, ChevronRight, Home, UploadCloud } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useKnowledgeStore, type Document, type FolderNode } from '../store/knowledgeStore';
import { useProjectStore } from '../../../shared/store/projectStore';
import { DocumentRow } from './DocumentRow';
import { DocumentViewer } from './DocumentViewer';
import { DocumentMetaEditor } from './DocumentMetaEditor';
import { FolderTree } from './FolderTree';
import { MoveDocModal } from './MoveDocModal';
import { TagFilter } from './TagFilter';
import { EmptyState } from '../../../shared/components/EmptyState';

export function KnowledgeBase() {
  const { t } = useTranslation();
  const {
    documents,
    folders,
    currentFolderId,
    uploading,
    loadDocuments,
    loadFolders,
    setCurrentFolderId,
    uploadDocument,
    deleteDocument,
    stopPolling,
    exportZipUrl,
  } = useKnowledgeStore();
  const { currentProjectId } = useProjectStore();
  const inputRef = useRef<HTMLInputElement>(null);
  const [search, setSearch] = useState('');
  const [selectedTags, setSelectedTags] = useState<Set<string>>(new Set());
  const [selectedType, setSelectedType] = useState('');
  const [previewDoc, setPreviewDoc] = useState<Document | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [metaDoc, setMetaDoc] = useState<Document | null>(null);
  const [metaOpen, setMetaOpen] = useState(false);
  const [moveDoc, setMoveDoc] = useState<Document | null>(null);
  const [moveOpen, setMoveOpen] = useState(false);
  const [isDragging, setIsDragging] = useState(false);

  useEffect(() => {
    loadFolders();
    loadDocuments();
    return () => stopPolling();
  }, [currentProjectId]); // 项目切换时重新加载

  // 根据当前 currentFolderId 查找面包屑路径
  const findFolderPath = (nodes: FolderNode[], targetId: number | null): FolderNode[] => {
    if (!targetId) return [];
    for (const node of nodes) {
      if (node.id === targetId) return [node];
      if (node.children && node.children.length > 0) {
        const sub = findFolderPath(node.children, targetId);
        if (sub.length > 0) return [node, ...sub];
      }
    }
    return [];
  };

  const breadcrumbs = findFolderPath(folders, currentFolderId);

  // 递归建立 folder_id 到 完整面包屑路径 的查找映射
  const folderPathMap = React.useMemo(() => {
    const map = new Map<number, { id: number; name: string }[]>();
    const walk = (nodes: FolderNode[], parentTrail: { id: number; name: string }[] = []) => {
      for (const n of nodes) {
        const currentTrail = [...parentTrail, { id: n.id, name: n.name }];
        map.set(n.id, currentTrail);
        if (n.children && n.children.length > 0) {
          walk(n.children, currentTrail);
        }
      }
    };
    walk(folders);
    return map;
  }, [folders]);

  const onPick = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) {
      await uploadDocument(f);
      e.target.value = '';
    }
  };

  const onDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (!isDragging) setIsDragging(true);
  };

  const onDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  };

  const onDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
    const f = e.dataTransfer.files?.[0];
    if (f) await uploadDocument(f);
  };

  // 过滤：文件名搜索 + 标签筛选 + 类型筛选
  const filtered = documents.filter((d) => {
    if (search && !d.filename.toLowerCase().includes(search.toLowerCase())) return false;
    if (selectedType && d.doc_type !== selectedType) return false;
    if (selectedTags.size > 0) {
      const docTags = new Set(d.tags || []);
      // 选中的标签必须至少有一个在文档标签里（OR 语义）
      const hasAny = [...selectedTags].some((t) => docTags.has(t));
      if (!hasAny) return false;
    }
    return true;
  });

  const toggleTag = (tag: string) => {
    const next = new Set(selectedTags);
    if (next.has(tag)) next.delete(tag);
    else next.add(tag);
    setSelectedTags(next);
  };

  const handlePreview = (doc: Document) => {
    setPreviewDoc(doc);
    setPreviewOpen(true);
  };

  const handleEditMeta = (doc: Document) => {
    setMetaDoc(doc);
    setMetaOpen(true);
  };

  const handleShowVersions = (doc: Document) => {
    setPreviewDoc(doc);
    setPreviewOpen(true);
    // 版本面板在 DocumentViewer 内部，打开后自动可点
  };

  const handleMove = (doc: Document) => {
    setMoveDoc(doc);
    setMoveOpen(true);
  };

  return (
    <div style={{ flex: 1, display: 'flex', height: '100%', overflow: 'hidden' }}>
      {/* 左侧目录树 */}
      <FolderTree currentFolderId={currentFolderId} onSelectFolder={setCurrentFolderId} />

      {/* 右侧主工作区 */}
      <div style={{ flex: 1, overflow: 'auto', padding: 16, display: 'flex', flexDirection: 'column' }}>
        {/* 面包屑导航与当前目录指示 */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            fontSize: 13,
            color: 'var(--text-muted, #666)',
            marginBottom: 12,
            padding: '4px 0',
          }}
        >
          <span
            onClick={() => setCurrentFolderId(null)}
            style={{
              cursor: 'pointer',
              display: 'inline-flex',
              alignItems: 'center',
              gap: 4,
              color: currentFolderId === null ? 'var(--text-primary, #111)' : 'inherit',
              fontWeight: currentFolderId === null ? 600 : 400,
            }}
          >
            <Home size={14} /> {t('kb.allDocuments', '全部文档')}
          </span>

          {breadcrumbs.map((b) => (
            <React.Fragment key={b.id}>
              <ChevronRight size={13} style={{ opacity: 0.5 }} />
              <span
                onClick={() => setCurrentFolderId(b.id)}
                style={{
                  cursor: 'pointer',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 4,
                  color: currentFolderId === b.id ? 'var(--primary, #3b82f6)' : 'inherit',
                  fontWeight: currentFolderId === b.id ? 600 : 400,
                }}
              >
                <Folder size={14} /> {b.name}
              </span>
            </React.Fragment>
          ))}
        </div>

        {/* 上传区：紧凑尺寸、明确边界、拖拽高亮 */}
        <div
          onDrop={onDrop}
          onDragOver={onDragOver}
          onDragLeave={onDragLeave}
          onClick={() => inputRef.current?.click()}
          style={{
            border: isDragging
              ? '2px dashed var(--primary, #3b82f6)'
              : '1.5px dashed var(--border-color, #cbd5e1)',
            backgroundColor: isDragging
              ? 'var(--bg-active, rgba(59, 130, 246, 0.08))'
              : 'var(--bg-secondary, #fafafa)',
            borderRadius: 8,
            padding: '12px 16px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 12,
            cursor: 'pointer',
            marginBottom: 12,
            transition: 'all 0.18s ease-in-out',
            boxShadow: isDragging ? '0 0 0 3px rgba(59, 130, 246, 0.15)' : 'none',
          }}
        >
          <div
            style={{
              width: 32,
              height: 32,
              borderRadius: 6,
              backgroundColor: isDragging ? 'var(--primary, #3b82f6)' : 'var(--bg-elevated, #e2e8f0)',
              color: isDragging ? '#fff' : 'var(--text-muted, #64748b)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
              transition: 'all 0.18s ease',
            }}
          >
            <UploadCloud size={18} />
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', textAlign: 'left', minWidth: 0 }}>
            <div style={{ fontSize: 13, fontWeight: 500, color: isDragging ? 'var(--primary, #3b82f6)' : 'var(--text-primary, #1e293b)' }}>
              {uploading ? t('kb.uploading') : (
                isDragging
                  ? t('kb.dropToUpload', '松开鼠标即可上传文档')
                  : (currentFolderId && breadcrumbs.length > 0
                    ? t('kb.uploadToFolderHint', { folder: breadcrumbs[breadcrumbs.length - 1].name, defaultValue: `上传文档到「${breadcrumbs[breadcrumbs.length - 1].name}」` })
                    : t('kb.uploadClickHint', '点击或拖拽文件到此处上传'))
              )}
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-muted, #64748b)', marginTop: 2 }}>
              {t('kb.supportedFormats', '支持 .md .txt .pdf .docx .xlsx .pptx .html，单个 ≤ 100MB')}
            </div>
          </div>

          <input
            ref={inputRef}
            type="file"
            accept=".md,.markdown,.txt,.pdf,.docx,.xlsx,.xls,.pptx,.html,.htm,.png,.jpg,.jpeg"
            onChange={onPick}
            hidden
          />
        </div>

        <p style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 8, display: 'flex', alignItems: 'flex-start', gap: 4 }}>
          <AlertTriangle size={12} strokeWidth={1.5} style={{ flexShrink: 0, marginTop: 1 }} />
          <span>{t('kb.docStorageHint')}</span>
        </p>

        {/* 工具栏：搜索 + 导出全部 */}
        {documents.length > 0 && (
          <>
            <TagFilter
              selectedTags={selectedTags}
              onToggleTag={toggleTag}
              onClearTags={() => setSelectedTags(new Set())}
              selectedType={selectedType}
              onSelectType={setSelectedType}
            />
            <div style={{ marginBottom: 12, display: 'flex', gap: 8 }}>
              <input
                type="text"
                placeholder={t('kb.searchFilenamePlaceholder')}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                style={{
                  flex: 1,
                  background: 'var(--bg-card)',
                  border: '1px solid var(--bg-elevated)',
                  borderRadius: 4,
                  color: 'var(--text-primary)',
                  padding: '6px 8px',
                  fontSize: 13,
                }}
              />
              <a
                href={exportZipUrl()}
                title={t('kb.exportAllZip')}
                style={{
                  background: 'var(--bg-card)',
                  border: '1px solid var(--bg-elevated)',
                  color: 'var(--text-secondary)',
                  borderRadius: 4,
                  padding: '6px 12px',
                  cursor: 'pointer',
                  fontSize: 13,
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 4,
                  textDecoration: 'none',
                  flexShrink: 0,
                }}
              >
                <Upload size={14} /> {t('kb.exportAll')}
              </a>
            </div>
          </>
        )}

        {filtered.length === 0 ? (
          <EmptyState message={documents.length === 0 ? t('kb.noDocumentsHint') : t('kb.noMatchingDocuments')} />
        ) : (
          <div style={{ border: '1px solid var(--bg-card)', borderRadius: 8 }}>
            {filtered.map((d) => (
              <DocumentRow
                key={d.id}
                doc={d}
                folderPath={d.folder_id ? folderPathMap.get(d.folder_id) : undefined}
                onSelectFolder={setCurrentFolderId}
                onDelete={deleteDocument}
                onPreview={handlePreview}
                onEditMeta={handleEditMeta}
                onShowVersions={handleShowVersions}
                onMove={handleMove}
              />
            ))}
          </div>
        )}

        {/* 全屏预览/编辑弹窗 */}
        <DocumentViewer doc={previewDoc} open={previewOpen} onOpenChange={setPreviewOpen} />

        {/* 元数据编辑弹窗 */}
        <DocumentMetaEditor doc={metaDoc} open={metaOpen} onOpenChange={setMetaOpen} />

        {/* 移动到目录弹窗 */}
        <MoveDocModal doc={moveDoc} open={moveOpen} onOpenChange={setMoveOpen} />
      </div>
    </div>
  );
}

