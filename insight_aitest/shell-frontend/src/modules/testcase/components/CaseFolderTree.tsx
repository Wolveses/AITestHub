import { useState, useEffect, type MouseEvent } from 'react';
import {
  Folder,
  FolderOpen,
  FolderPlus,
  ChevronRight,
  ChevronDown,
  Edit2,
  Trash2,
  Plus,
  Files,
  Inbox,
  FolderTree as TreeIcon,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { useConfirmStore } from '../../../shared/store/confirmStore';
import { useProjectStore } from '../../../shared/store/projectStore';
import { useCaseStore, type FolderNode } from '../store/caseStore';

interface CaseFolderTreeProps {
  onFolderChange?: () => void;
}

export function CaseFolderTree({ onFolderChange }: CaseFolderTreeProps) {
  const { t } = useTranslation();
  const { confirm } = useConfirmStore();
  const { projects } = useProjectStore();
  const {
    folders,
    currentFolderId,
    selectedProjectId,
    setSelectedProjectId,
    loadFolders,
    createFolder,
    updateFolder,
    deleteFolder,
    setCurrentFolderId,
    loadCases,
  } = useCaseStore();

  const [expanded, setExpanded] = useState<Record<number, boolean>>({});
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editName, setEditName] = useState('');
  const [creatingParentId, setCreatingParentId] = useState<number | null | undefined>(undefined);
  const [newFolderName, setNewFolderName] = useState('');

  // 当选中的项目变化时，重新加载目录树
  useEffect(() => {
    if (selectedProjectId !== null) {
      loadFolders(selectedProjectId);
    }
  }, [selectedProjectId, loadFolders]);

  // 用例必须归属项目：如果当前未选项目或选中的项目不存在，自动选中第一个项目
  useEffect(() => {
    if (projects.length > 0 && (selectedProjectId === null || !projects.some((p) => p.id === selectedProjectId))) {
      setSelectedProjectId(projects[0].id);
    }
  }, [projects, selectedProjectId, setSelectedProjectId]);

  const handleSelectProject = (pid: number) => {
    setCurrentFolderId(null);
    setSelectedProjectId(pid);
  };

  const toggleExpand = (id: number, e: MouseEvent) => {
    e.stopPropagation();
    setExpanded((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  const handleStartCreate = (parentId: number | null = null, e?: MouseEvent) => {
    e?.stopPropagation();
    setCreatingParentId(parentId);
    setNewFolderName('');
    if (parentId !== null) {
      setExpanded((prev) => ({ ...prev, [parentId]: true }));
    }
  };

  const handleConfirmCreate = async () => {
    if (!newFolderName.trim()) {
      setCreatingParentId(undefined);
      return;
    }
    try {
      await createFolder(newFolderName.trim(), creatingParentId, selectedProjectId);
      toast.success(t('testcase.folderCreated', '目录创建成功'));
      setCreatingParentId(undefined);
      setNewFolderName('');
    } catch (e) {
      toast.error((e as Error).message);
    }
  };

  const handleStartEdit = (folder: FolderNode, e: MouseEvent) => {
    e.stopPropagation();
    setEditingId(folder.id);
    setEditName(folder.name);
  };

  const handleConfirmEdit = async (folderId: number) => {
    if (!editName.trim()) {
      setEditingId(null);
      return;
    }
    try {
      await updateFolder(folderId, editName.trim());
      toast.success(t('testcase.folderUpdated', '目录重命名成功'));
      setEditingId(null);
    } catch (e) {
      toast.error((e as Error).message);
    }
  };

  const handleDeleteFolder = (folder: FolderNode, e: MouseEvent) => {
    e.stopPropagation();
    confirm({
      title: t('testcase.confirmDeleteFolder', '确认删除目录'),
      message: t('testcase.confirmDeleteFolderMsg', '确定删除目录「{{name}}」吗？其下子目录将被递归删除，用例将被移至未分类。', { name: folder.name }),
      variant: 'danger',
      onConfirm: async () => {
        try {
          await deleteFolder(folder.id);
          toast.success(t('testcase.folderDeleted', '目录已删除'));
        } catch (e) {
          toast.error((e as Error).message);
        }
      },
    });
  };

  const handleSelectFolder = (id: number | null) => {
    setCurrentFolderId(id);
    loadCases();
    onFolderChange?.();
  };

  const renderFolderItem = (folder: FolderNode, depth: number = 0) => {
    const isExpanded = expanded[folder.id] ?? true;
    const isSelected = currentFolderId === folder.id;
    const hasChildren = folder.children && folder.children.length > 0;
    const isEditing = editingId === folder.id;

    return (
      <div key={folder.id} style={{ display: 'flex', flexDirection: 'column' }}>
        <div
          onClick={() => handleSelectFolder(folder.id)}
          style={{
            display: 'flex',
            alignItems: 'center',
            padding: `6px 10px 6px ${12 + depth * 16}px`,
            cursor: 'pointer',
            borderRadius: 6,
            fontSize: 13,
            color: isSelected ? 'var(--accent)' : 'var(--text-primary)',
            background: isSelected ? 'rgba(91,140,123,0.12)' : 'transparent',
            userSelect: 'none',
            position: 'relative',
            gap: 6,
            transition: 'background 0.15s ease',
          }}
          onMouseEnter={(e) => {
            if (!isSelected) e.currentTarget.style.background = 'var(--bg-elevated)';
            const actions = e.currentTarget.querySelector('.folder-actions') as HTMLElement;
            if (actions) actions.style.opacity = '1';
          }}
          onMouseLeave={(e) => {
            if (!isSelected) e.currentTarget.style.background = 'transparent';
            const actions = e.currentTarget.querySelector('.folder-actions') as HTMLElement;
            if (actions) actions.style.opacity = '0';
          }}
        >
          {/* 展开折叠图标 */}
          <span
            onClick={(e) => hasChildren && toggleExpand(folder.id, e)}
            style={{
              width: 16,
              height: 16,
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              cursor: hasChildren ? 'pointer' : 'default',
              color: 'var(--text-muted)',
              flexShrink: 0,
            }}
          >
            {hasChildren ? (
              isExpanded ? <ChevronDown size={13} strokeWidth={2} /> : <ChevronRight size={13} strokeWidth={2} />
            ) : null}
          </span>

          {/* 目录图标 */}
          {isSelected || isExpanded ? (
            <FolderOpen size={15} strokeWidth={1.5} style={{ color: isSelected ? 'var(--accent)' : '#eab308', flexShrink: 0 }} />
          ) : (
            <Folder size={15} strokeWidth={1.5} style={{ color: '#eab308', flexShrink: 0 }} />
          )}

          {/* 目录名称 / 编辑框 */}
          {isEditing ? (
            <input
              autoFocus
              value={editName}
              onChange={(e) => setEditName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleConfirmEdit(folder.id);
                if (e.key === 'Escape') setEditingId(null);
              }}
              onBlur={() => handleConfirmEdit(folder.id)}
              onClick={(e) => e.stopPropagation()}
              style={{
                flex: 1,
                fontSize: 12,
                padding: '2px 4px',
                background: 'var(--bg-card)',
                border: '1px solid var(--accent)',
                borderRadius: 4,
                color: 'var(--text-primary)',
                outline: 'none',
              }}
            />
          ) : (
            <span
              style={{
                flex: 1,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
                fontWeight: isSelected ? 600 : 400,
              }}
              title={folder.name}
            >
              {folder.name}
            </span>
          )}

          {/* 用例数量徽标 */}
          {folder.case_count > 0 && !isEditing && (
            <span
              style={{
                fontSize: 10,
                color: 'var(--text-muted)',
                background: 'var(--bg-card)',
                padding: '1px 6px',
                borderRadius: 999,
                border: '1px solid var(--border)',
                flexShrink: 0,
              }}
            >
              {folder.case_count}
            </span>
          )}

          {/* 悬浮操作图标 */}
          {!isEditing && (
            <div
              className="folder-actions"
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 4,
                opacity: 0,
                transition: 'opacity 0.15s ease',
                flexShrink: 0,
              }}
            >
              <button
                title={t('testcase.newSubFolder', '新建子目录')}
                onClick={(e) => handleStartCreate(folder.id, e)}
                style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', padding: 2 }}
              >
                <Plus size={13} strokeWidth={1.8} />
              </button>
              <button
                title={t('testcase.renameFolder', '重命名')}
                onClick={(e) => handleStartEdit(folder, e)}
                style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', padding: 2 }}
              >
                <Edit2 size={12} strokeWidth={1.5} />
              </button>
              <button
                title={t('testcase.deleteFolder', '删除目录')}
                onClick={(e) => handleDeleteFolder(folder, e)}
                style={{ background: 'none', border: 'none', color: 'var(--error, #ef4444)', cursor: 'pointer', padding: 2 }}
              >
                <Trash2 size={12} strokeWidth={1.5} />
              </button>
            </div>
          )}
        </div>

        {/* 正在该目录下创建子目录的行 */}
        {creatingParentId === folder.id && (
          <div style={{ display: 'flex', alignItems: 'center', padding: `4px 10px 4px ${28 + depth * 16}px`, gap: 6 }}>
            <Folder size={14} style={{ color: 'var(--text-muted)' }} />
            <input
              autoFocus
              placeholder={t('testcase.inputFolderName', '输入目录名称...')}
              value={newFolderName}
              onChange={(e) => setNewFolderName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleConfirmCreate();
                if (e.key === 'Escape') setCreatingParentId(undefined);
              }}
              onBlur={handleConfirmCreate}
              style={{
                flex: 1,
                fontSize: 12,
                padding: '2px 6px',
                background: 'var(--bg-card)',
                border: '1px solid var(--accent)',
                borderRadius: 4,
                color: 'var(--text-primary)',
                outline: 'none',
              }}
            />
          </div>
        )}

        {/* 递归渲染子目录 */}
        {hasChildren && isExpanded && (
          <div>
            {folder.children.map((child) => renderFolderItem(child, depth + 1))}
          </div>
        )}
      </div>
    );
  };

  return (
    <div
      style={{
        width: 240,
        height: '100%',
        borderRight: '1px solid var(--bg-card)',
        display: 'flex',
        flexDirection: 'column',
        background: 'var(--bg-base)',
        flexShrink: 0,
      }}
    >
      {/* 目录最上方：项目下拉选择框 */}
      <div style={{ padding: '12px 12px 8px', borderBottom: '1px solid var(--bg-card)' }}>
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 6, fontWeight: 500, display: 'flex', alignItems: 'center', gap: 4 }}>
          <TreeIcon size={12} strokeWidth={1.5} /> {t('testcase.projectCatalog', '项目目录')}
        </div>
        <select
          value={selectedProjectId ?? (projects.length > 0 ? projects[0].id : '')}
          onChange={(e) => {
            const val = e.target.value;
            if (val) handleSelectProject(Number(val));
          }}
          style={{
            width: '100%',
            background: 'var(--bg-card)',
            border: '1px solid var(--border)',
            color: 'var(--text-primary)',
            padding: '6px 8px',
            borderRadius: 6,
            fontSize: 13,
            cursor: 'pointer',
            outline: 'none',
          }}
        >
          {projects.length === 0 ? (
            <option value="">{t('testcase.noProjects', '暂无项目')}</option>
          ) : (
            projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))
          )}
        </select>
      </div>

      {/* 根级别导航选项（全部用例、未分类） */}
      <div style={{ padding: '8px 8px 4px', display: 'flex', flexDirection: 'column', gap: 2 }}>
        {/* 全部用例 */}
        <div
          onClick={() => handleSelectFolder(null)}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: '7px 10px',
            borderRadius: 6,
            fontSize: 13,
            cursor: 'pointer',
            color: currentFolderId === null ? 'var(--accent)' : 'var(--text-primary)',
            background: currentFolderId === null ? 'rgba(91,140,123,0.12)' : 'transparent',
            fontWeight: currentFolderId === null ? 600 : 400,
          }}
          onMouseEnter={(e) => {
            if (currentFolderId !== null) e.currentTarget.style.background = 'var(--bg-elevated)';
          }}
          onMouseLeave={(e) => {
            if (currentFolderId !== null) e.currentTarget.style.background = 'transparent';
          }}
        >
          <Files size={15} strokeWidth={1.5} style={{ color: currentFolderId === null ? 'var(--accent)' : 'var(--text-muted)' }} />
          <span style={{ flex: 1 }}>{t('testcase.allCases', '全部用例')}</span>
        </div>

        {/* 未分类用例 */}
        <div
          onClick={() => handleSelectFolder(-1)}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: '7px 10px',
            borderRadius: 6,
            fontSize: 13,
            cursor: 'pointer',
            color: currentFolderId === -1 ? 'var(--accent)' : 'var(--text-secondary)',
            background: currentFolderId === -1 ? 'rgba(91,140,123,0.12)' : 'transparent',
            fontWeight: currentFolderId === -1 ? 600 : 400,
          }}
          onMouseEnter={(e) => {
            if (currentFolderId !== -1) e.currentTarget.style.background = 'var(--bg-elevated)';
          }}
          onMouseLeave={(e) => {
            if (currentFolderId !== -1) e.currentTarget.style.background = 'transparent';
          }}
        >
          <Inbox size={15} strokeWidth={1.5} style={{ color: currentFolderId === -1 ? 'var(--accent)' : 'var(--text-muted)' }} />
          <span style={{ flex: 1 }}>{t('testcase.unclassifiedCases', '未分类用例')}</span>
        </div>
      </div>

      {/* 目录树分界头 */}
      <div
        style={{
          padding: '8px 12px 4px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          borderTop: '1px solid var(--border)',
          marginTop: 4,
        }}
      >
        <span style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 500, letterSpacing: '0.02em' }}>
          {t('testcase.folderList', '用例目录')}
        </span>
        <button
          onClick={(e) => handleStartCreate(null, e)}
          title={t('testcase.newRootFolder', '新建根目录')}
          style={{
            background: 'none',
            border: 'none',
            color: 'var(--text-muted)',
            cursor: 'pointer',
            display: 'inline-flex',
            alignItems: 'center',
            gap: 2,
            fontSize: 11,
            padding: '2px 4px',
            borderRadius: 4,
          }}
          onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--accent)')}
          onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--text-muted)')}
        >
          <Plus size={13} strokeWidth={1.8} /> {t('testcase.newFolder', '新建目录')}
        </button>
      </div>

      {/* 根目录下新建输入行 */}
      {creatingParentId === null && (
        <div style={{ display: 'flex', alignItems: 'center', padding: '4px 12px', gap: 6 }}>
          <FolderPlus size={14} style={{ color: 'var(--accent)' }} />
          <input
            autoFocus
            placeholder={t('testcase.inputFolderName', '输入目录名称...')}
            value={newFolderName}
            onChange={(e) => setNewFolderName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleConfirmCreate();
              if (e.key === 'Escape') setCreatingParentId(undefined);
            }}
            onBlur={handleConfirmCreate}
            style={{
              flex: 1,
              fontSize: 12,
              padding: '2px 6px',
              background: 'var(--bg-card)',
              border: '1px solid var(--accent)',
              borderRadius: 4,
              color: 'var(--text-primary)',
              outline: 'none',
            }}
          />
        </div>
      )}

      {/* 目录树列表区域 */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '4px 6px 12px' }}>
        {folders.length === 0 && creatingParentId !== null ? (
          <div style={{ padding: '24px 12px', textAlign: 'center', color: 'var(--text-muted)', fontSize: 12 }}>
            {t('testcase.noFoldersHint', '暂无目录，点击上方「新建目录」创建')}
          </div>
        ) : (
          folders.map((node) => renderFolderItem(node, 0))
        )}
      </div>
    </div>
  );
}
