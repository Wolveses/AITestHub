import { useState, useEffect, useMemo } from 'react';
import { Folder, FolderOpen, ChevronRight, ChevronDown, X, FileText, CheckSquare, Square, MinusSquare } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useProjectStore } from '../../../shared/store/projectStore';

export interface DocItem {
  id: number;
  filename: string;
  folder_id: number | null;
  doc_type?: string;
  status?: string;
  char_count?: number;
}

export interface FolderItem {
  id: number;
  name: string;
  parent_id: number | null;
  children?: FolderItem[];
}

interface DocPickerModalProps {
  open: boolean;
  onClose: () => void;
  selectedDocIds: number[];
  onConfirm: (selectedIds: number[]) => void;
}

export function DocPickerModal({ open, onClose, selectedDocIds, onConfirm }: DocPickerModalProps) {
  const { t } = useTranslation();
  const { currentProjectId } = useProjectStore();

  const [docs, setDocs] = useState<DocItem[]>([]);
  const [folders, setFolders] = useState<FolderItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState<Record<number | string, boolean>>({ root: true });
  const [tempSelected, setTempSelected] = useState<Set<number>>(new Set(selectedDocIds));

  useEffect(() => {
    if (open) {
      setTempSelected(new Set(selectedDocIds));
      setLoading(true);
      const params = currentProjectId != null ? `?project_id=${currentProjectId}` : '';

      Promise.all([
        fetch(`/api/modules/kb/folders${params}`).then((r) => (r.ok ? r.json() : [])),
        fetch(`/api/modules/kb/documents${params}`).then((r) => (r.ok ? r.json() : [])),
      ])
        .then(([foldersData, docsData]) => {
          setFolders(Array.isArray(foldersData) ? foldersData : []);
          setDocs(Array.isArray(docsData) ? docsData : []);
        })
        .finally(() => setLoading(false));
    }
  }, [open, selectedDocIds, currentProjectId]);

  // 映射：计算每个文件夹下包含的所有文档 ID（含递归子目录）
  const folderDocMap = useMemo(() => {
    const map = new Map<number, number[]>();

    // 先收集直接子文档
    const directMap = new Map<number | null, number[]>();
    for (const d of docs) {
      const fId = d.folder_id ?? null;
      if (!directMap.has(fId)) directMap.set(fId, []);
      directMap.get(fId)!.push(d.id);
    }

    // 递归收集包含子目录的全部 doc IDs
    const collectAll = (node: FolderItem): number[] => {
      const ids: number[] = [...(directMap.get(node.id) || [])];
      if (node.children) {
        for (const child of node.children) {
          ids.push(...collectAll(child));
        }
      }
      map.set(node.id, ids);
      return ids;
    };

    for (const f of folders) {
      collectAll(f);
    }

    return map;
  }, [folders, docs]);

  if (!open) return null;

  const totalDocsCount = docs.length;
  const isAllSelected = totalDocsCount > 0 && tempSelected.size === totalDocsCount;
  const isPartialSelected = tempSelected.size > 0 && tempSelected.size < totalDocsCount;

  const handleToggleAll = () => {
    if (isAllSelected) {
      setTempSelected(new Set());
    } else {
      setTempSelected(new Set(docs.map((d) => d.id)));
    }
  };

  const handleToggleDoc = (docId: number) => {
    const next = new Set(tempSelected);
    if (next.has(docId)) {
      next.delete(docId);
    } else {
      next.add(docId);
    }
    setTempSelected(next);
  };

  const handleToggleFolder = (folderId: number) => {
    const docIds = folderDocMap.get(folderId) || [];
    if (docIds.length === 0) return;

    const allChecked = docIds.every((id) => tempSelected.has(id));
    const next = new Set(tempSelected);

    if (allChecked) {
      docIds.forEach((id) => next.delete(id));
    } else {
      docIds.forEach((id) => next.add(id));
    }
    setTempSelected(next);
  };

  const toggleExpand = (id: number | string) => {
    setExpanded((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  const handleConfirm = () => {
    onConfirm(Array.from(tempSelected));
    onClose();
  };

  // 渲染单层文件夹节点及归属文档
  const renderFolderNode = (node: FolderItem, level: number) => {
    const isExpanded = !!expanded[node.id];
    const docIds = folderDocMap.get(node.id) || [];
    const directDocs = docs.filter((d) => d.folder_id === node.id);
    const hasChildren = (node.children && node.children.length > 0) || directDocs.length > 0;

    const checkedCount = docIds.filter((id) => tempSelected.has(id)).length;
    const isFolderAllChecked = docIds.length > 0 && checkedCount === docIds.length;
    const isFolderPartialChecked = checkedCount > 0 && checkedCount < docIds.length;

    return (
      <div key={`folder-${node.id}`} style={{ display: 'flex', flexDirection: 'column' }}>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            padding: '5px 8px',
            paddingLeft: 8 + level * 16,
            borderRadius: 6,
            gap: 6,
            cursor: 'pointer',
            fontSize: 13,
            color: 'var(--text-primary)',
          }}
          className="hover-bg"
          onClick={() => toggleExpand(node.id)}
        >
          {/* 折叠/展开箭头 */}
          <span
            style={{
              width: 14,
              height: 14,
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              opacity: hasChildren ? 0.7 : 0,
            }}
          >
            {hasChildren ? isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} /> : null}
          </span>

          {/* 文件夹复选框 */}
          <span
            onClick={(e) => {
              e.stopPropagation();
              handleToggleFolder(node.id);
            }}
            style={{
              cursor: docIds.length > 0 ? 'pointer' : 'not-allowed',
              opacity: docIds.length > 0 ? 1 : 0.4,
              display: 'inline-flex',
              alignItems: 'center',
            }}
          >
            {isFolderAllChecked ? (
              <CheckSquare size={15} style={{ color: 'var(--primary, #3b82f6)' }} />
            ) : isFolderPartialChecked ? (
              <MinusSquare size={15} style={{ color: 'var(--primary, #3b82f6)' }} />
            ) : (
              <Square size={15} style={{ color: 'var(--border-strong, #cbd5e1)' }} />
            )}
          </span>

          {/* 图标 */}
          {isExpanded ? (
            <FolderOpen size={15} style={{ color: 'var(--primary, #3b82f6)', flexShrink: 0 }} />
          ) : (
            <Folder size={15} style={{ color: 'var(--text-muted, #94a3b8)', flexShrink: 0 }} />
          )}

          {/* 目录名称与数量 */}
          <span style={{ fontWeight: 500, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {node.name}
          </span>
          <span style={{ fontSize: 11, color: 'var(--text-muted)', marginRight: 4 }}>
            ({docIds.length})
          </span>
        </div>

        {/* 展开内容：子文件夹 + 属于该文件夹的文档 */}
        {isExpanded && (
          <div style={{ display: 'flex', flexDirection: 'column' }}>
            {node.children?.map((child) => renderFolderNode(child, level + 1))}
            {directDocs.map((doc) => renderDocItem(doc, level + 1))}
          </div>
        )}
      </div>
    );
  };

  // 渲染单个文档项
  const renderDocItem = (doc: DocItem, level: number) => {
    const isChecked = tempSelected.has(doc.id);
    return (
      <div
        key={`doc-${doc.id}`}
        onClick={() => handleToggleDoc(doc.id)}
        style={{
          display: 'flex',
          alignItems: 'center',
          padding: '4px 8px',
          paddingLeft: 28 + level * 16,
          borderRadius: 6,
          gap: 6,
          cursor: 'pointer',
          fontSize: 12,
          color: isChecked ? 'var(--text-primary)' : 'var(--text-secondary)',
          background: isChecked ? 'var(--bg-active, rgba(59,130,246,0.06))' : 'transparent',
        }}
        className="hover-bg"
      >
        <span style={{ display: 'inline-flex', alignItems: 'center' }}>
          {isChecked ? (
            <CheckSquare size={14} style={{ color: 'var(--primary, #3b82f6)' }} />
          ) : (
            <Square size={14} style={{ color: 'var(--border-strong, #cbd5e1)' }} />
          )}
        </span>
        <FileText size={13} style={{ opacity: 0.65, flexShrink: 0 }} />
        <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {doc.filename}
        </span>
      </div>
    );
  };

  // 未分类或根目录文档
  const unclassifiedDocs = docs.filter((d) => !d.folder_id);

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 1000,
        backgroundColor: 'rgba(0,0,0,0.5)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 16,
      }}
    >
      <div
        style={{
          width: 520,
          maxWidth: '100%',
          maxHeight: '80vh',
          backgroundColor: 'var(--bg-card, #fff)',
          border: '1px solid var(--border-strong)',
          borderRadius: 12,
          boxShadow: 'var(--shadow-elevated, 0 10px 25px rgba(0,0,0,0.2))',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
        }}
      >
        {/* 模态框头部 */}
        <div
          style={{
            padding: '14px 18px',
            borderBottom: '1px solid var(--border)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 15, fontWeight: 600, color: 'var(--text-primary)' }}>
              {t('ai.kbSelectDocs', '选择文档库')}
            </span>
            <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
              (共 {totalDocsCount} 篇文档)
            </span>
          </div>
          <button
            onClick={onClose}
            style={{
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              color: 'var(--text-muted)',
              padding: 4,
            }}
          >
            <X size={16} />
          </button>
        </div>

        {/* 顶部操作工具栏：全选/反选 */}
        <div
          style={{
            padding: '8px 18px',
            borderBottom: '1px solid var(--border)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            backgroundColor: 'var(--bg-secondary, #fafafa)',
            fontSize: 12,
          }}
        >
          <div
            onClick={handleToggleAll}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              cursor: 'pointer',
              userSelect: 'none',
              color: 'var(--text-primary)',
              fontWeight: 500,
            }}
          >
            {isAllSelected ? (
              <CheckSquare size={15} style={{ color: 'var(--primary, #3b82f6)' }} />
            ) : isPartialSelected ? (
              <MinusSquare size={15} style={{ color: 'var(--primary, #3b82f6)' }} />
            ) : (
              <Square size={15} style={{ color: 'var(--border-strong, #cbd5e1)' }} />
            )}
            <span>全选所有文档</span>
          </div>

          <div style={{ color: 'var(--text-muted)' }}>
            已选 <strong style={{ color: 'var(--primary, #3b82f6)' }}>{tempSelected.size}</strong> 篇
          </div>
        </div>

        {/* 树列表区域 */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '10px 14px' }}>
          {loading ? (
            <div style={{ padding: 24, textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
              加载知识库文档中...
            </div>
          ) : docs.length === 0 ? (
            <div style={{ padding: 32, textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
              知识库暂无可用文档
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              {/* 文件夹及子节点 */}
              {folders.map((folder) => renderFolderNode(folder, 0))}

              {/* 根目录/未分类文档 */}
              {unclassifiedDocs.length > 0 && (
                <div style={{ marginTop: 4, borderTop: folders.length > 0 ? '1px dashed var(--border)' : 'none', paddingTop: 4 }}>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', padding: '4px 8px' }}>
                    未分类文档 ({unclassifiedDocs.length})
                  </div>
                  {unclassifiedDocs.map((doc) => renderDocItem(doc, 0))}
                </div>
              )}
            </div>
          )}
        </div>

        {/* 底部按钮栏 */}
        <div
          style={{
            padding: '12px 18px',
            borderTop: '1px solid var(--border)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'flex-end',
            gap: 10,
            backgroundColor: 'var(--bg-secondary, #fafafa)',
          }}
        >
          <button
            onClick={onClose}
            style={{
              padding: '6px 14px',
              fontSize: 12,
              borderRadius: 6,
              border: '1px solid var(--border-strong)',
              background: 'var(--bg-card, #fff)',
              color: 'var(--text-secondary)',
              cursor: 'pointer',
            }}
          >
            取消
          </button>
          <button
            onClick={handleConfirm}
            style={{
              padding: '6px 16px',
              fontSize: 12,
              borderRadius: 6,
              border: 'none',
              background: 'var(--primary, #3b82f6)',
              color: '#fff',
              cursor: 'pointer',
              fontWeight: 500,
            }}
          >
            确定 ({tempSelected.size})
          </button>
        </div>
      </div>
    </div>
  );
}
