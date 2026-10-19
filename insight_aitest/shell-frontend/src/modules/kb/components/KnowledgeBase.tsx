import React, { useEffect, useRef, useState } from 'react';
import { AlertTriangle, Upload, Folder, ChevronRight, Home, UploadCloud, RefreshCw, Globe } from 'lucide-react';
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
    activeTab,
    uploading,
    syncingFeishu,
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
  const [feishuModalOpen, setFeishuModalOpen] = useState(false);
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

          {/* 飞书文档标签下：展示飞书空间同步操作按钮 */}
          {activeTab === 'feishu' && (
            <button
              onClick={async () => {
                setFeishuModalOpen(true);
                setLoadingSpaces(true);
                setFeishuError('');
                try {
                  const spaces = await listFeishuSpaces();
                  setFeishuSpaces(spaces);
                } catch (err: any) {
                  setFeishuError(err?.message || String(err));
                  setFeishuSpaces([]);
                } finally {
                  setLoadingSpaces(false);
                }
              }}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 5,
                background: 'rgba(59, 130, 246, 0.08)',
                color: '#2563eb',
                border: '1px solid rgba(59, 130, 246, 0.25)',
                borderRadius: 6,
                padding: '4px 12px',
                fontSize: 12,
                fontWeight: 500,
                cursor: 'pointer',
                transition: 'all 0.15s ease',
              }}
              title="配置并同步飞书知识库空间"
            >
              <RefreshCw size={13} className={syncingFeishu ? 'animate-spin' : ''} />
              {syncingFeishu ? '正在同步飞书...' : '同步飞书知识库'}
            </button>
          )}
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
        )}

        {activeTab === 'local' && (
          <p style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 8, display: 'flex', alignItems: 'flex-start', gap: 4 }}>
            <AlertTriangle size={12} strokeWidth={1.5} style={{ flexShrink: 0, marginTop: 1 }} />
            <span>{t('kb.docStorageHint')}</span>
          </p>
        )}

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
                showFolderScope={currentFolderId === null}
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
                            alert(`同步成功！已拉取 ${res.result?.synced_count || 0} 个文档`);
                            setFeishuModalOpen(false);
                          } catch (err: any) {
                            alert(`同步失败: ${err.message}`);
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
                          alert(`同步成功！已拉取 ${res.result?.synced_count || 0} 个文档`);
                          setFeishuModalOpen(false);
                          setSyncSpaceIdInput('');
                        } catch (err: any) {
                          alert(`同步失败: ${err.message}`);
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

