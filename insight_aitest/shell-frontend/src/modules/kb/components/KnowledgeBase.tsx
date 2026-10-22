import React, { useEffect, useRef, useState } from 'react';
import { AlertTriangle, Upload, Folder, ChevronRight, Home, UploadCloud, RefreshCw, Globe } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { useKnowledgeStore, type Document, type FolderNode } from '../store/knowledgeStore';
import { useProjectStore } from '../../../shared/store/projectStore';
import { useConfirmStore } from '../../../shared/store/confirmStore';
import { useConfigStore } from '../../ai/store/configStore';
import { DocumentRow } from './DocumentRow';
import { DocumentViewer } from './DocumentViewer';
import { ChunksViewer } from './ChunksViewer';
import { DocumentMetaEditor } from './DocumentMetaEditor';
import { FolderTree } from './FolderTree';
import { MoveDocModal } from './MoveDocModal';
import { TagFilter } from './TagFilter';
import { EmptyState } from '../../../shared/components/EmptyState';

// 分页条组件（无 UI 库，内联实现）
function PaginationBar({
  page, pageSize, total, onChange,
}: {
  page: number; pageSize: number; total: number;
  onChange: (page: number, pageSize: number) => void;
}) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const p = Math.min(Math.max(1, page), totalPages);
  const pages: (number | '...')[] = [];
  if (totalPages <= 7) {
    for (let i = 1; i <= totalPages; i++) pages.push(i);
  } else {
    pages.push(1);
    if (p > 4) pages.push('...');
    const start = Math.max(2, p - 2);
    const end = Math.min(totalPages - 1, p + 2);
    for (let i = start; i <= end; i++) pages.push(i);
    if (p < totalPages - 3) pages.push('...');
    pages.push(totalPages);
  }

  const btn = (disabled: boolean) => ({
    padding: '2px 8px',
    fontSize: 12,
    border: '1px solid var(--bg-elevated)',
    borderRadius: 4,
    background: disabled ? 'var(--bg-secondary, #f8fafc)' : 'var(--bg-card)',
    color: disabled ? '#94a3b8' : 'var(--text-primary)',
    cursor: disabled ? 'not-allowed' : 'pointer',
  });

  return (
    <div style={{
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      padding: '10px 4px', marginTop: 8,
      fontSize: 12, color: 'var(--text-muted)',
    }}>
      <span>共 {total} 条，第 {p}/{totalPages} 页</span>
      <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
        <button style={btn(p === 1)} disabled={p === 1} onClick={() => onChange(1, pageSize)}>«</button>
        <button style={btn(p === 1)} disabled={p === 1} onClick={() => onChange(p - 1, pageSize)}>‹</button>
        {pages.map((x, i) =>
          x === '...' ? (
            <span key={`e${i}`} style={{ padding: '0 4px' }}>…</span>
          ) : (
            <button
              key={x}
              onClick={() => onChange(x, pageSize)}
              style={{
                padding: '2px 8px', fontSize: 12,
                border: `1px solid ${x === p ? 'var(--primary, #3b82f6)' : 'var(--bg-elevated)'}`,
                borderRadius: 4,
                background: x === p ? 'var(--primary, #3b82f6)' : 'var(--bg-card)',
                color: x === p ? '#fff' : 'var(--text-primary)',
                cursor: 'pointer',
                minWidth: 26,
              }}
            >{x}</button>
          )
        )}
        <button style={btn(p === totalPages)} disabled={p === totalPages} onClick={() => onChange(p + 1, pageSize)}>›</button>
        <button style={btn(p === totalPages)} disabled={p === totalPages} onClick={() => onChange(totalPages, pageSize)}>»</button>
        <select
          value={pageSize}
          onChange={(e) => onChange(1, Number(e.target.value))}
          style={{
            marginLeft: 8, padding: '2px 4px', fontSize: 12,
            border: '1px solid var(--bg-elevated)', borderRadius: 4,
            background: 'var(--bg-card)', color: 'var(--text-primary)',
          }}
        >
          {[10, 20, 50, 100].map((n) => (
            <option key={n} value={n}>每页 {n}</option>
          ))}
        </select>
      </div>
    </div>
  );
}

export function KnowledgeBase() {
  const { t } = useTranslation();
  const { confirm } = useConfirmStore();
  const {
    documents,
    docTotal,
    page,
    pageSize,
    folders,
    currentFolderId,
    activeTab,
    uploading,
    syncingFeishu,
    feishuModalOpen,
    setFeishuModalOpen,
    loadDocuments,
    loadFolders,
    setCurrentFolderId,
    uploadDocument,
    deleteDocument,
    stopPolling,
    exportZipUrl,
    listFeishuSpaces,
    syncFeishuSpace,
  } = useKnowledgeStore();
  const { currentProjectId } = useProjectStore();
  const inputRef = useRef<HTMLInputElement>(null);
  const [searchInput, setSearchInput] = useState('');  // 输入框本地 state（防抖后同步到后端）
  const [selectedTags, setSelectedTags] = useState<Set<string>>(new Set());
  const [selectedType, setSelectedType] = useState('');
  const [previewDoc, setPreviewDoc] = useState<Document | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [metaDoc, setMetaDoc] = useState<Document | null>(null);
  const [metaOpen, setMetaOpen] = useState(false);
  const [moveDoc, setMoveDoc] = useState<Document | null>(null);
  const [moveOpen, setMoveOpen] = useState(false);
  const [chunksDoc, setChunksDoc] = useState<Document | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [feishuSpaces, setFeishuSpaces] = useState<{ space_id: string; name: string }[]>([]);
  const [loadingSpaces, setLoadingSpaces] = useState(false);
  const [feishuError, setFeishuError] = useState('');
  const [syncSpaceIdInput, setSyncSpaceIdInput] = useState('');

  useEffect(() => {
    loadFolders();
    loadDocuments();
    return () => stopPolling();
  }, [currentProjectId, activeTab]); // 项目切换或标签切换时重新加载

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

  // 搜索 debounce（300ms）→ 调后端 search filter
  const searchTimer = useRef<number | null>(null);
  const onSearchChange = (val: string) => {
    setSearchInput(val);
    if (searchTimer.current) window.clearTimeout(searchTimer.current);
    searchTimer.current = window.setTimeout(() => {
      loadDocuments({ search: val, resetPage: true });
    }, 300);
  };

  const toggleTag = (tag: string) => {
    const next = new Set(selectedTags);
    if (next.has(tag)) next.delete(tag);
    else next.add(tag);
    setSelectedTags(next);
    loadDocuments({ tags: [...next], resetPage: true });
  };

  const onTypeChange = (type: string) => {
    setSelectedType(type);
    loadDocuments({ doc_type: type, resetPage: true });
  };

  const onClearTags = () => {
    setSelectedTags(new Set());
    loadDocuments({ tags: [], resetPage: true });
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

  const handleReindex = async (docId: number) => {
    try {
      const r = await fetch(`/api/modules/kb/documents/${docId}/reindex`, { method: 'POST' });
      if (!r.ok) {
        const err = await r.text();
        toast.error(err || `重新向量化失败 (HTTP ${r.status})`);
        return;
      }
      toast.success(t('kb.reindexStarted', '已触发重新向量化'));
      setTimeout(() => loadDocuments(), 1000);
    } catch (e: any) {
      toast.error(`重新向量化失败: ${e?.message || e}`);
    }
  };

  const handleReindexAll = async () => {
    try {
      const stats = await fetch('/api/modules/ai/tasks/kb/stats').then(r => r.ok ? r.json() : null);
      const cnt = stats?.need_reindex_count ?? 0;
      if (cnt === 0) {
        toast.info(t('kb.noNeedReindex', '没有需要重新向量化的文档'));
        return;
      }
      const ragOn = stats?.vector_enabled;
      confirm({
        title: t('kb.confirmReindexAllTitle', '批量重新向量化'),
        message: ragOn
          ? t('kb.confirmReindexAllMsg', '将对 {{n}} 个文档重新解析并向量化，需要调用 embedding API，确定？', { n: cnt })
          : t('kb.confirmReindexAllMsgRagOff', '当前 RAG 未开启，将对 {{n}} 个文档重新解析分块（不执行向量化），确定？', { n: cnt }),
        onConfirm: async () => {
          try {
            const r = await fetch('/api/modules/ai/tasks/kb/reindex', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ all: true, document_ids: [] }),
            });
            if (!r.ok) {
              const err = await r.text();
              toast.error(err || `批量重新向量化失败 (HTTP ${r.status})`);
              return;
            }
            toast.success(t('kb.reindexAllStarted', '已触发批量重新向量化'));
            setTimeout(() => loadDocuments(), 1500);
          } catch (e: any) {
            toast.error(`批量重新向量化失败: ${e?.message || e}`);
          }
        },
      });
    } catch (e: any) {
      toast.error(`批量重新向量化失败: ${e?.message || e}`);
    }
  };

  // 顶部按钮数量用全库范围（调 stats 接口），与 handleReindexAll 的 confirm 弹框保持一致
  const [needReindexCount, setNeedReindexCount] = useState(0);
  const [vectorEnabled, setVectorEnabled] = useState(false);
  // 订阅 configStore 的 vector_enabled，保存 AI 设置后立即生效，无需刷新页面
  const configVectorEnabled = useConfigStore((s) => !!s.config?.vector_enabled);
  useEffect(() => {
    fetch('/api/modules/ai/tasks/kb/stats')
      .then(r => r.ok ? r.json() : null)
      .then(s => {
        setNeedReindexCount(s?.need_reindex_count ?? 0);
        setVectorEnabled(!!s?.vector_enabled);
      })
      .catch(() => {});
  }, [activeTab, currentFolderId, configVectorEnabled]);
  // 同步到本地 state（保存配置后后端 stats 接口需要重新拉才能拿到最新值，
  // 但 configStore 已经更新了，这里用它当即时源让 UI 立即响应）
  useEffect(() => {
    setVectorEnabled(configVectorEnabled);
  }, [configVectorEnabled]);

  // feishuModalOpen 由 KnowledgeBaseApp 顶部按钮触发，这里监听并初始化飞书空间列表
  useEffect(() => {
    if (feishuModalOpen) {
      setLoadingSpaces(true);
      setFeishuError('');
      listFeishuSpaces()
        .then(spaces => setFeishuSpaces(spaces))
        .catch((err: any) => {
          setFeishuError(err?.message || String(err));
          setFeishuSpaces([]);
        })
        .finally(() => setLoadingSpaces(false));
    }
  }, [feishuModalOpen, listFeishuSpaces]);

  return (
    <div style={{ flex: 1, display: 'flex', height: '100%', overflow: 'hidden' }}>
      {/* 左侧目录树 */}
      <FolderTree currentFolderId={currentFolderId} onSelectFolder={setCurrentFolderId} />

      {/* 右侧主工作区 */}
      <div style={{ flex: 1, overflow: 'auto', padding: 16, display: 'flex', flexDirection: 'column' }}>
        {/* 面包屑导航与飞书同步按钮 */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            fontSize: 13,
            color: 'var(--text-muted, #666)',
            marginBottom: 12,
            padding: '2px 0',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
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
              <Home size={14} /> {activeTab === 'feishu' ? '飞书知识库' : t('kb.allDocuments', '全部文档')}
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

          <button
            onClick={handleReindexAll}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 5,
              background: 'var(--bg-card, rgba(148,163,184,0.08))',
              color: 'var(--text-secondary)',
              border: '1px solid var(--border-color, rgba(148,163,184,0.25))',
              borderRadius: 6,
              padding: '4px 12px',
              fontSize: 12,
              fontWeight: 500,
              cursor: 'pointer',
              transition: 'all 0.15s ease',
            }}
            title="对所有未向量化/向量化失败的文档重新执行向量化"
          >
            <RefreshCw size={13} />
            {needReindexCount > 0 ? `全部重新解析 (${needReindexCount})` : '全部重新解析'}
          </button>
        </div>

        {/* 本地文档模式下展示上传区：紧凑尺寸、明确边界、拖拽高亮 */}
        {activeTab === 'local' && (
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
              {t('kb.supportedFormats', '支持 .md .txt .pdf .doc .docx .xlsx .xls .pptx .html，单个 ≤ 100MB')}
            </div>
          </div>

          <input
            ref={inputRef}
            type="file"
            accept=".md,.markdown,.txt,.pdf,.doc,.docx,.xlsx,.xls,.pptx,.html,.htm,.png,.jpg,.jpeg"
            onChange={onPick}
            hidden
          />
        </div>
        )}

        {activeTab === 'local' && (
          <p style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 8, display: 'flex', alignItems: 'flex-start', gap: 4 }}>
            <AlertTriangle size={12} strokeWidth={1.5} style={{ flexShrink: 0, marginTop: 1 }} />
            <span>{t('kb.docStorageHint')}</span>
          </p>
        )}

        {/* 工具栏：搜索 + 导出全部 */}
        {(docTotal > 0 || searchInput || selectedTags.size > 0 || selectedType) && (
          <>
            <TagFilter
              selectedTags={selectedTags}
              onToggleTag={toggleTag}
              onClearTags={onClearTags}
              selectedType={selectedType}
              onSelectType={onTypeChange}
            />
            <div style={{ marginBottom: 12, display: 'flex', gap: 8 }}>
              <input
                type="text"
                placeholder={t('kb.searchFilenamePlaceholder')}
                value={searchInput}
                onChange={(e) => onSearchChange(e.target.value)}
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

        {docTotal === 0 ? (
          <EmptyState message={documents.length === 0 ? t('kb.noDocumentsHint') : t('kb.noMatchingDocuments')} />
        ) : (
          <>
            <div style={{ border: '1px solid var(--bg-card)', borderRadius: 8 }}>
              {documents.map((d) => (
                <DocumentRow
                  key={d.id}
                  doc={d}
                  vectorEnabled={vectorEnabled}
                  folderPath={d.folder_id ? folderPathMap.get(d.folder_id) : undefined}
                  showFolderScope={currentFolderId === null}
                  onSelectFolder={setCurrentFolderId}
                  onDelete={deleteDocument}
                  onPreview={handlePreview}
                  onEditMeta={handleEditMeta}
                  onShowVersions={handleShowVersions}
                  onMove={handleMove}
                  onReindex={handleReindex}
                  onPreviewChunks={setChunksDoc}
                />
              ))}
            </div>
            <PaginationBar
              page={page}
              pageSize={pageSize}
              total={docTotal}
              onChange={(p, ps) => loadDocuments({ page: p, page_size: ps })}
            />
          </>
        )}

        {/* 全屏预览/编辑弹窗 */}
        <DocumentViewer doc={previewDoc} open={previewOpen} onOpenChange={setPreviewOpen} />

        {/* 元数据编辑弹窗 */}
        <DocumentMetaEditor doc={metaDoc} open={metaOpen} onOpenChange={setMetaOpen} />

        {/* 移动到目录弹窗 */}
        <MoveDocModal doc={moveDoc} open={moveOpen} onOpenChange={setMoveOpen} />

        {/* 分块预览弹窗 */}
        {chunksDoc && (
          <ChunksViewer docId={chunksDoc.id} filename={chunksDoc.filename} onOpenChange={(open) => !open && setChunksDoc(null)} />
        )}

        {/* 飞书知识库空间同步弹窗 */}
        {feishuModalOpen && (
          <div
            style={{
              position: 'fixed',
              inset: 0,
              background: 'rgba(0,0,0,0.5)',
              zIndex: 3000,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
            onClick={() => setFeishuModalOpen(false)}
          >
            <div
              style={{
                width: 480,
                background: 'var(--bg-base, #fff)',
                borderRadius: 8,
                padding: 20,
                boxShadow: '0 8px 30px rgba(0,0,0,0.2)',
                display: 'flex',
                flexDirection: 'column',
                gap: 16,
              }}
              onClick={(e) => e.stopPropagation()}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 15, fontWeight: 600 }}>
                  <Globe size={18} style={{ color: '#2563eb' }} />
                  同步飞书知识库空间 (Wiki)
                </div>
                <button
                  onClick={() => setFeishuModalOpen(false)}
                  style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 16, color: '#999' }}
                >
                  ✕
                </button>
              </div>

              <div style={{ fontSize: 12, color: 'var(--text-muted, #64748b)', lineHeight: 1.5 }}>
                系统将递归拉取飞书知识库目录树并在本地建立镜像目录，自动将 Doc/Docx 转为 Markdown，Sheet 转为 Excel，PDF 下载源格式（PPT 自动忽略）。
              </div>

              {feishuError && (
                <div
                  style={{
                    display: 'flex',
                    gap: 8,
                    alignItems: 'flex-start',
                    background: 'rgba(239, 68, 68, 0.08)',
                    border: '1px solid rgba(239, 68, 68, 0.3)',
                    borderRadius: 6,
                    padding: '10px 12px',
                    fontSize: 12,
                    color: '#dc2626',
                    lineHeight: 1.5,
                  }}
                >
                  <AlertTriangle size={14} style={{ flexShrink: 0, marginTop: 1 }} />
                  <span>{feishuError}</span>
                </div>
              )}

              {loadingSpaces ? (
                <div style={{ textAlign: 'center', padding: '24px 0', fontSize: 13, color: '#666' }}>
                  正在连接飞书开放平台获取知识库列表...
                </div>
              ) : feishuSpaces.length > 0 ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxHeight: 220, overflowY: 'auto' }}>
                  <div style={{ fontSize: 12, fontWeight: 500 }}>选择已授权的知识库空间：</div>
                  {feishuSpaces.map((s) => (
                    <div
                      key={s.space_id}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        padding: '10px 12px',
                        borderRadius: 6,
                        border: '1px solid var(--border-color, #e2e8f0)',
                        background: 'var(--bg-secondary, #f8fafc)',
                      }}
                    >
                      <div>
                        <div style={{ fontSize: 13, fontWeight: 500 }}>{s.name}</div>
                        <div style={{ fontSize: 11, color: '#94a3b8' }}>ID: {s.space_id}</div>
                      </div>
                      <button
                        disabled={syncingFeishu}
                        onClick={async () => {
                          try {
                            const res = await syncFeishuSpace(s.space_id);
                            toast.success(t('kb.syncSuccess', '同步成功！已拉取 {{n}} 个文档', { n: res.result?.synced_count || 0 }));
                            setFeishuModalOpen(false);
                          } catch (err: any) {
                            toast.error(t('kb.syncFailed', '同步失败: {{msg}}', { msg: err.message }));
                          }
                        }}
                        style={{
                          background: '#2563eb',
                          color: '#fff',
                          border: 'none',
                          borderRadius: 4,
                          padding: '5px 12px',
                          fontSize: 12,
                          cursor: 'pointer',
                          fontWeight: 500,
                        }}
                      >
                        {syncingFeishu ? '同步中...' : '开始同步'}
                      </button>
                    </div>
                  ))}
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                  {!feishuError && (
                    <div style={{ fontSize: 12, color: 'var(--text-secondary, #475569)' }}>
                      暂未自动列出空间（飞书机器人可能未直接加入空间成员）。您可以直接输入飞书知识库 Space ID：
                    </div>
                  )}
                  <div style={{ display: 'flex', gap: 8 }}>
                    <input
                      type="text"
                      placeholder="例如: 7123456789012345678"
                      value={syncSpaceIdInput}
                      onChange={(e) => setSyncSpaceIdInput(e.target.value)}
                      style={{
                        flex: 1,
                        padding: '6px 10px',
                        fontSize: 13,
                        borderRadius: 4,
                        border: '1px solid var(--border-color, #cbd5e1)',
                        outline: 'none',
                      }}
                    />
                    <button
                      disabled={!syncSpaceIdInput.trim() || syncingFeishu}
                      onClick={async () => {
                        try {
                          const res = await syncFeishuSpace(syncSpaceIdInput.trim());
                          toast.success(t('kb.syncSuccess', '同步成功！已拉取 {{n}} 个文档', { n: res.result?.synced_count || 0 }));
                          setFeishuModalOpen(false);
                          setSyncSpaceIdInput('');
                        } catch (err: any) {
                          toast.error(t('kb.syncFailed', '同步失败: {{msg}}', { msg: err.message }));
                        }
                      }}
                      style={{
                        background: syncSpaceIdInput.trim() ? '#2563eb' : '#94a3b8',
                        color: '#fff',
                        border: 'none',
                        borderRadius: 4,
                        padding: '6px 14px',
                        fontSize: 13,
                        cursor: syncSpaceIdInput.trim() ? 'pointer' : 'not-allowed',
                        fontWeight: 500,
                      }}
                    >
                      {syncingFeishu ? '同步中...' : '立即同步'}
                    </button>
                  </div>
                </div>
              )}

              <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 8 }}>
                <button
                  onClick={() => setFeishuModalOpen(false)}
                  style={{
                    background: 'var(--bg-elevated, #f1f5f9)',
                    border: '1px solid var(--border-color, #cbd5e1)',
                    borderRadius: 4,
                    padding: '6px 14px',
                    fontSize: 12,
                    cursor: 'pointer',
                  }}
                >
                  关闭
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

