import React, { useState, useRef, useEffect, useCallback } from 'react';
import {
  Folder,
  FolderPlus,
  FolderOpen,
  ChevronRight,
  ChevronDown,
  MoreVertical,
  Edit2,
  Trash2,
  Plus,
  Files,
  RefreshCw,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { useConfirmStore } from '../../../shared/store/confirmStore';
import { useKnowledgeStore, type FolderNode } from '../store/knowledgeStore';

interface FolderTreeProps {
  currentFolderId: number | null;
  onSelectFolder: (id: number | null) => void;
}

const STORAGE_KEY = 'insight_kb_folder_tree_width';
const DEFAULT_WIDTH = 220;
const MIN_WIDTH = 160;
const MAX_WIDTH = 500;

export function FolderTree({ currentFolderId, onSelectFolder }: FolderTreeProps) {
  const { t } = useTranslation();
  const { confirm } = useConfirmStore();
  const { folders, createFolder, updateFolder, deleteFolder } = useKnowledgeStore();
  const [expanded, setExpanded] = useState<Record<number, boolean>>({});
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editName, setEditName] = useState('');
  const [creatingParentId, setCreatingParentId] = useState<number | null | undefined>(undefined);
  const [newFolderName, setNewFolderName] = useState('');
  const [activeMenuId, setActiveMenuId] = useState<number | null>(null);

  // 左右拖动调整宽度
  const [width, setWidth] = useState<number>(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved) {
        const val = parseInt(saved, 10);
        if (!isNaN(val) && val >= MIN_WIDTH && val <= MAX_WIDTH) {
          return val;
        }
      }
    } catch {}
    return DEFAULT_WIDTH;
  });
  const [isDragging, setIsDragging] = useState(false);
  const treeRef = useRef<HTMLDivElement>(null);
  const startDragInfo = useRef<{ startX: number; startWidth: number } | null>(null);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    setIsDragging(true);
    startDragInfo.current = { startX: e.clientX, startWidth: width };
  }, [width]);

  useEffect(() => {
    if (!isDragging) return;

    const handleMouseMove = (e: MouseEvent) => {
      if (!startDragInfo.current) return;
      const delta = e.clientX - startDragInfo.current.startX;
      const nextWidth = Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, startDragInfo.current.startWidth + delta));
      setWidth(nextWidth);
    };

    const handleMouseUp = () => {
      setIsDragging(false);
      startDragInfo.current = null;
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isDragging]);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, width.toString());
    } catch {}
  }, [width]);

  const toggleExpand = (id: number, e: React.MouseEvent) => {
    e.stopPropagation();
    setExpanded((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  const handleStartCreate = (parentId: number | null = null, e?: React.MouseEvent) => {
    e?.stopPropagation();
    setCreatingParentId(parentId);
    setNewFolderName('');
    setActiveMenuId(null);
    if (parentId) {
      setExpanded((prev) => ({ ...prev, [parentId]: true }));
    }
  };

  const handleConfirmCreate = async () => {
    if (!newFolderName.trim()) {
      setCreatingParentId(undefined);
      return;
    }
    try {
      await createFolder(newFolderName.trim(), creatingParentId);
    } finally {
      setCreatingParentId(undefined);
      setNewFolderName('');
    }
  };

  const handleStartRename = (node: FolderNode, e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingId(node.id);
    setEditName(node.name);
    setActiveMenuId(null);
  };

  const handleConfirmRename = async (id: number) => {
    if (editName.trim()) {
      await updateFolder(id, editName.trim());
    }
    setEditingId(null);
  };

  const handleDelete = async (id: number, e: React.MouseEvent) => {
    e.stopPropagation();
    setActiveMenuId(null);
    confirm({
      message: t('kb.confirmDeleteFolder', '确定要删除该文件夹吗？其内部文档将移至未分类。'),
      variant: 'danger',
      onConfirm: async () => {
        await deleteFolder(id);
      },
    });
  };

  const renderTreeNodes = (nodes: FolderNode[], level = 0) => {
    return nodes.map((node) => {
      const isExpanded = !!expanded[node.id];
      const isSelected = currentFolderId === node.id;
      const isEditing = editingId === node.id;
      const hasChildren = node.children && node.children.length > 0;

      return (
        <div key={node.id} style={{ display: 'flex', flexDirection: 'column' }}>
          <div
            onClick={() => onSelectFolder(node.id)}
            style={{
              display: 'flex',
              alignItems: 'center',
              padding: '6px 8px',
              paddingLeft: 8 + level * 16,
              borderRadius: 6,
              cursor: 'pointer',
              backgroundColor: isSelected ? 'var(--bg-active, rgba(59, 130, 246, 0.12))' : 'transparent',
              color: isSelected ? 'var(--primary, #3b82f6)' : 'inherit',
              fontSize: 13,
              gap: 6,
              position: 'relative',
              userSelect: 'none',
              transition: 'background 0.15s ease',
            }}
            className="hover-bg"
          >
            {/* 折叠/展开箭头 */}
            <span
              onClick={(e) => hasChildren && toggleExpand(node.id, e)}
              style={{
                width: 14,
                height: 14,
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                cursor: hasChildren ? 'pointer' : 'default',
                opacity: hasChildren ? 0.7 : 0,
              }}
            >
              {hasChildren ? (isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />) : null}
            </span>

            {/* 文件夹图标 */}
            {isExpanded ? (
              <FolderOpen size={16} style={{ flexShrink: 0, color: 'var(--primary, #3b82f6)' }} />
            ) : (
              <Folder size={16} style={{ flexShrink: 0, color: 'var(--text-muted, #888)' }} />
            )}

            {/* 文件夹名称 */}
            {isEditing ? (
              <input
                autoFocus
                value={editName}
                onClick={(e) => e.stopPropagation()}
                onChange={(e) => setEditName(e.target.value)}
                onBlur={() => handleConfirmRename(node.id)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleConfirmRename(node.id);
                  if (e.key === 'Escape') setEditingId(null);
                }}
                style={{
                  fontSize: 12,
                  padding: '1px 4px',
                  borderRadius: 4,
                  border: '1px solid var(--primary, #3b82f6)',
                  background: 'var(--bg-primary, #fff)',
                  color: 'inherit',
                  outline: 'none',
                  flex: 1,
                  minWidth: 60,
                }}
              />
            ) : (
              <span
                style={{
                  flex: 1,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                  fontWeight: isSelected ? 500 : 400,
                }}
              >
                {node.name}
              </span>
            )}

            {/* 文档数量计数 */}
            {node.doc_count > 0 && (
              <span
                style={{
                  fontSize: 11,
                  color: 'var(--text-muted, #999)',
                  padding: '1px 5px',
                  borderRadius: 10,
                  backgroundColor: 'var(--bg-elevated, rgba(0,0,0,0.05))',
                }}
              >
                {node.doc_count}
              </span>
            )}

            {/* 更多操作菜单按钮 */}
            <div
              onClick={(e) => {
                e.stopPropagation();
                setActiveMenuId(activeMenuId === node.id ? null : node.id);
              }}
              style={{
                width: 20,
                height: 20,
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                borderRadius: 4,
                opacity: activeMenuId === node.id ? 1 : 0.4,
                cursor: 'pointer',
              }}
              title={t('common.more', '更多')}
            >
              <MoreVertical size={14} />
            </div>

            {/* 弹出下拉菜单 */}
            {activeMenuId === node.id && (
              <div
                onClick={(e) => e.stopPropagation()}
                style={{
                  position: 'absolute',
                  right: 8,
                  top: 28,
                  zIndex: 20,
                  backgroundColor: 'var(--bg-surface, #fff)',
                  border: '1px solid var(--border-color, #e5e7eb)',
                  borderRadius: 6,
                  boxShadow: '0 4px 12px rgba(0,0,0,0.1)',
                  padding: '4px 0',
                  minWidth: 120,
                }}
              >
                <div
                  onClick={(e) => handleStartCreate(node.id, e)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    padding: '6px 12px',
                    fontSize: 12,
                    cursor: 'pointer',
                  }}
                  className="hover-bg"
                >
                  <Plus size={13} /> {t('kb.newSubFolder', '新建子目录')}
                </div>
                {node.source_type === 'feishu' && node.external_id?.startsWith('space_') && (
                  <div
                    onClick={async (e) => {
                      e.stopPropagation();
                      setActiveMenuId(null);
                      const spaceId = node.external_id?.replace('space_', '');
                      if (spaceId) {
                        try {
                          await useKnowledgeStore.getState().syncFeishuSpace(spaceId);
                        } catch (err: any) {
                          toast.error(t('kb.syncFailed', '同步失败: {{msg}}', { msg: err.message }));
                        }
                      }
                    }}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 8,
                      padding: '6px 12px',
                      fontSize: 12,
                      cursor: 'pointer',
                      color: 'var(--primary, #3b82f6)',
                      fontWeight: 500,
                    }}
                    className="hover-bg"
                  >
                    <RefreshCw size={13} /> {t('kb.syncNow', '立即同步飞书')}
                  </div>
                )}
                <div
                  onClick={(e) => handleStartRename(node, e)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    padding: '6px 12px',
                    fontSize: 12,
                    cursor: 'pointer',
                  }}
                  className="hover-bg"
                >
                  <Edit2 size={13} /> {t('common.rename', '重命名')}
                </div>
                <div
                  onClick={(e) => handleDelete(node.id, e)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    padding: '6px 12px',
                    fontSize: 12,
                    color: 'var(--danger, #ef4444)',
                    cursor: 'pointer',
                  }}
                  className="hover-bg"
                >
                  <Trash2 size={13} /> {t('common.delete', '删除')}
                </div>
              </div>
            )}
          </div>

          {/* 子文件夹新建输入框 */}
          {creatingParentId === node.id && (
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                padding: '4px 8px',
                paddingLeft: 24 + level * 16,
                gap: 6,
              }}
            >
              <Folder size={15} style={{ opacity: 0.5 }} />
              <input
                autoFocus
                placeholder={t('kb.folderNamePlaceholder', '输入目录名…')}
                value={newFolderName}
                onChange={(e) => setNewFolderName(e.target.value)}
                onBlur={handleConfirmCreate}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleConfirmCreate();
                  if (e.key === 'Escape') setCreatingParentId(undefined);
                }}
                style={{
                  fontSize: 12,
                  padding: '2px 6px',
                  borderRadius: 4,
                  border: '1px solid var(--primary, #3b82f6)',
                  background: 'var(--bg-primary, #fff)',
                  color: 'inherit',
                  outline: 'none',
                  flex: 1,
                }}
              />
            </div>
          )}

          {/* 渲染子节点 */}
          {isExpanded && hasChildren && renderTreeNodes(node.children, level + 1)}
        </div>
      );
    });
  };

  return (
    <div
      ref={treeRef}
      onClick={() => setActiveMenuId(null)}
      style={{
        width,
        minWidth: MIN_WIDTH,
        maxWidth: MAX_WIDTH,
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        backgroundColor: 'var(--bg-secondary, #fafafa)',
        padding: '12px 8px',
        boxSizing: 'border-box',
        overflow: 'hidden',
        position: 'relative',
        flexShrink: 0,
        userSelect: isDragging ? 'none' : 'auto',
      }}
    >
      {/* 左右拖动调整宽度手柄 */}
      <div
        onMouseDown={handleMouseDown}
        style={{
          position: 'absolute',
          top: 0,
          right: 0,
          width: 5,
          height: '100%',
          cursor: 'col-resize',
          zIndex: 10,
          backgroundColor: isDragging ? 'var(--accent, #3b82f6)' : 'transparent',
          borderRight: `1px solid ${isDragging ? 'var(--accent, #3b82f6)' : 'var(--border-color, #e5e7eb)'}`,
          transition: isDragging ? 'none' : 'background-color 0.15s ease',
        }}
        onMouseEnter={(e) => {
          if (!isDragging) {
            e.currentTarget.style.backgroundColor = 'rgba(59, 130, 246, 0.3)';
          }
        }}
        onMouseLeave={(e) => {
          if (!isDragging) {
            e.currentTarget.style.backgroundColor = 'transparent';
          }
        }}
        title="拖动调整宽度"
      />

      {/* 头部标题 */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0 4px 8px 4px',
          borderBottom: '1px solid var(--border-color, #f0f0f0)',
          marginBottom: 8,
        }}
      >
        <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary, #111)' }}>
          {t('kb.directoryTitle', '目录导航')}
        </span>
      </div>

      {/* 树主体区域 */}
      <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 2 }}>
        {/* 根目录项（本地文档 / 飞书文档） */}
        <div
          onClick={() => onSelectFolder(null)}
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '6px 8px',
            borderRadius: 6,
            cursor: 'pointer',
            backgroundColor: currentFolderId === null ? 'var(--bg-active, rgba(59, 130, 246, 0.12))' : 'transparent',
            color: currentFolderId === null ? 'var(--primary, #3b82f6)' : 'inherit',
            fontSize: 13,
            fontWeight: currentFolderId === null ? 500 : 400,
          }}
          className="hover-bg"
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Files size={16} style={{ opacity: 0.8 }} />
            <span>{useKnowledgeStore.getState().activeTab === 'feishu' ? '飞书知识库' : t('kb.allDocuments', '全部文档')}</span>
          </div>

          {/* 仅本地文档支持手动新建根目录；飞书目录结构由飞书空间决定 */}
          {useKnowledgeStore.getState().activeTab === 'local' && (
            <button
              onClick={(e) => handleStartCreate(null, e)}
              style={{
                background: 'none',
                border: 'none',
                cursor: 'pointer',
                padding: 2,
                borderRadius: 4,
                display: 'inline-flex',
                alignItems: 'center',
                color: 'var(--text-muted, #666)',
              }}
              title={t('kb.newSubFolder', '新建子目录')}
              className="hover-bg"
            >
              <FolderPlus size={15} />
            </button>
          )}
        </div>

        {/* 根目录新建输入框 */}
        {creatingParentId === null && (
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              padding: '4px 8px',
              gap: 6,
            }}
          >
            <Folder size={15} style={{ opacity: 0.5 }} />
            <input
              autoFocus
              placeholder={t('kb.folderNamePlaceholder', '输入目录名…')}
              value={newFolderName}
              onChange={(e) => setNewFolderName(e.target.value)}
              onBlur={handleConfirmCreate}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleConfirmCreate();
                if (e.key === 'Escape') setCreatingParentId(undefined);
              }}
              style={{
                fontSize: 12,
                padding: '2px 6px',
                borderRadius: 4,
                border: '1px solid var(--primary, #3b82f6)',
                background: 'var(--bg-primary, #fff)',
                color: 'inherit',
                outline: 'none',
                flex: 1,
              }}
            />
          </div>
        )}

        {/* 动态文件夹树 */}
        {renderTreeNodes(folders)}
      </div>
    </div>
  );
}

