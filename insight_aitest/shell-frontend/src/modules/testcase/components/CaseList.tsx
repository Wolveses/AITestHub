import { useState, useMemo, type MouseEvent, type CSSProperties } from 'react';
import {
  Search,
  Layers,
  FileSpreadsheet,
  Trash2,
  CheckSquare,
  Square,
  MinusSquare,
  Eye,
  X,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { useCaseStore, type FolderNode } from '../store/caseStore';
import { useProjectStore } from '../../../shared/store/projectStore';
import { useConfirmStore } from '../../../shared/store/confirmStore';
import { BatchAssignModal } from './BatchAssignModal';
import { exportTestCasesToExcel } from '../utils/exportExcel';
import { formatCaseType } from '../utils/caseLabels';

const STATUS_COLOR: Record<string, string> = {
  draft: 'var(--warning, #f59e0b)',
  reviewed: 'var(--info, #3b82f6)',
  ready: 'var(--success, #10b981)',
  deprecated: 'var(--text-muted, #94a3b8)',
};

const PRIORITY_COLOR: Record<string, string> = {
  p0: 'var(--error, #ef4444)',
  p1: 'var(--warning, #f59e0b)',
  p2: 'var(--text-muted, #94a3b8)',
  p3: 'var(--border-strong, #64748b)',
};

export function CaseList() {
  const { t } = useTranslation();
  const { cases, folders, activeId, selectCase, deleteCase, batchDelete, loadCases, loadFolders } = useCaseStore();
  const { versions } = useProjectStore();
  const { confirm } = useConfirmStore();

  const [searchKeyword, setSearchKeyword] = useState('');
  const [selectedType, setSelectedType] = useState('');
  const [selectedPriority, setSelectedPriority] = useState('');
  const [selectedStatus, setSelectedStatus] = useState('');

  // 多选用例 ID 集合
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());

  // 批量操作弹窗状态
  const [assignModalOpen, setAssignModalOpen] = useState(false);

  // 过滤用例
  const filteredCases = useMemo(() => {
    return cases.filter((c) => {
      if (selectedType && c.type !== selectedType) return false;
      if (selectedPriority && c.priority !== selectedPriority) return false;
      if (selectedStatus && c.status !== selectedStatus) return false;
      if (searchKeyword.trim()) {
        const kw = searchKeyword.trim().toLowerCase();
        const matchTitle = c.title.toLowerCase().includes(kw);
        const matchDesc = (c.description || '').toLowerCase().includes(kw);
        const matchTag = (c.tags || []).some((tag) => tag.toLowerCase().includes(kw));
        if (!matchTitle && !matchDesc && !matchTag) return false;
      }
      return true;
    });
  }, [cases, selectedType, selectedPriority, selectedStatus, searchKeyword]);

  // 全选/半选状态
  const isAllSelected = filteredCases.length > 0 && filteredCases.every((c) => selectedIds.has(c.id));
  const isPartiallySelected =
    !isAllSelected && filteredCases.some((c) => selectedIds.has(c.id));

  const toggleSelectAll = () => {
    if (isAllSelected) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(filteredCases.map((c) => c.id)));
    }
  };

  const toggleSelect = (id: number, e: MouseEvent) => {
    e.stopPropagation();
    const next = new Set(selectedIds);
    if (next.has(id)) {
      next.delete(id);
    } else {
      next.add(id);
    }
    setSelectedIds(next);
  };

  const handleBatchDelete = () => {
    const ids = Array.from(selectedIds);
    if (ids.length === 0) return;
    confirm({
      title: t('testcase.batchDeleteTitle', '确认批量删除'),
      message: t('testcase.batchDeleteConfirmMsg', '确定要删除选中的 {{count}} 条用例吗？删除后不可恢复。', { count: ids.length }),
      variant: 'danger',
      onConfirm: async () => {
        try {
          await batchDelete(ids);
          setSelectedIds(new Set());
          toast.success(t('testcase.batchDeletedSuccess', '批量删除成功'));
        } catch (e) {
          toast.error((e as Error).message);
        }
      },
    });
  };

  // 目录扁平映射表，用于展示目录名
  const folderMap = useMemo(() => {
    const map = new Map<number, string>();
    const traverse = (nodes: FolderNode[]) => {
      for (const n of nodes) {
        map.set(n.id, n.name);
        if (n.children) traverse(n.children);
      }
    };
    traverse(folders);
    return map;
  }, [folders]);

  // 版本映射表
  const versionMap = useMemo(() => {
    const map = new Map<number, string>();
    for (const v of versions) {
      map.set(v.id, v.name);
    }
    return map;
  }, [versions]);

  return (
    <div
      style={{
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        overflow: 'hidden',
        background: 'var(--bg-base)',
      }}
    >
      {/* 搜索与条件过滤栏 */}
      <div
        style={{
          padding: '12px 16px',
          borderBottom: '1px solid var(--border)',
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          flexWrap: 'wrap',
          background: 'var(--bg-card)',
        }}
      >
        <div style={{ position: 'relative', width: 220 }}>
          <Search
            size={14}
            style={{ position: 'absolute', left: 9, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }}
          />
          <input
            placeholder={t('testcase.searchPlaceholder', '搜索用例标题/标签...')}
            value={searchKeyword}
            onChange={(e) => setSearchKeyword(e.target.value)}
            style={{
              width: '100%',
              padding: '6px 8px 6px 28px',
              borderRadius: 6,
              background: 'var(--bg-base)',
              border: '1px solid var(--border)',
              color: 'var(--text-primary)',
              fontSize: 13,
              outline: 'none',
            }}
          />
          {searchKeyword && (
            <button
              onClick={() => setSearchKeyword('')}
              style={{
                position: 'absolute',
                right: 8,
                top: '50%',
                transform: 'translateY(-50%)',
                background: 'none',
                border: 'none',
                color: 'var(--text-muted)',
                cursor: 'pointer',
              }}
            >
              <X size={12} />
            </button>
          )}
        </div>

        {/* 类型筛选 */}
        <select
          value={selectedType}
          onChange={(e) => setSelectedType(e.target.value)}
          style={filterSelectStyle}
        >
          <option value="">{t('testcase.allTypes', '全部类型')}</option>
          <option value="functional">{t('testcase.typeFunctional', '功能用例')}</option>
          <option value="api">{t('testcase.typeApi', '接口用例')}</option>
          <option value="performance">{t('testcase.typePerformance', '性能用例')}</option>
          <option value="ui">{t('testcase.typeUi', 'UI用例')}</option>
        </select>

        {/* 优先级筛选 */}
        <select
          value={selectedPriority}
          onChange={(e) => setSelectedPriority(e.target.value)}
          style={filterSelectStyle}
        >
          <option value="">{t('testcase.allPriorities', '全部优先级')}</option>
          <option value="p0">P0</option>
          <option value="p1">P1</option>
          <option value="p2">P2</option>
          <option value="p3">P3</option>
        </select>

        {/* 状态筛选 */}
        <select
          value={selectedStatus}
          onChange={(e) => setSelectedStatus(e.target.value)}
          style={filterSelectStyle}
        >
          <option value="">{t('testcase.allStatuses', '全部状态')}</option>
          <option value="draft">{t('testcase.statusPending', '待审阅')}</option>
          <option value="reviewed">{t('testcase.statusReviewed', '已审阅')}</option>
          <option value="ready">{t('testcase.statusReady', '就绪')}</option>
          <option value="deprecated">{t('testcase.statusDeprecated', '已废弃')}</option>
        </select>

        <div style={{ flex: 1 }} />

        <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
          {t('testcase.totalCountMsg', '共 {{count}} 条用例', { count: filteredCases.length })}
        </span>
      </div>

      {/* 批量操作浮层工具栏（当勾选 > 0 条时展示） */}
      {selectedIds.size > 0 && (
        <div
          style={{
            padding: '8px 16px',
            background: 'rgba(91,140,123,0.1)',
            borderBottom: '1px solid var(--accent)',
            display: 'flex',
            alignItems: 'center',
            gap: 12,
            animation: 'fade-in 0.2s ease',
          }}
        >
          <span style={{ fontSize: 13, color: 'var(--accent)', fontWeight: 600 }}>
            {t('testcase.selectedCountLabel', '已勾选 {{count}} 条用例', { count: selectedIds.size })}
          </span>

          <button
            onClick={() => setAssignModalOpen(true)}
            style={batchActionBtnStyle}
          >
            <Layers size={13} strokeWidth={1.8} /> {t('testcase.batchAssign', '批量修改归属')}
          </button>

          <button
            onClick={() => exportTestCasesToExcel({ case_ids: Array.from(selectedIds) })}
            style={batchActionBtnStyle}
          >
            <FileSpreadsheet size={13} strokeWidth={1.8} style={{ color: 'var(--success, #10b981)' }} />
            {t('testcase.exportToExcel', '导出到 Excel（TAPD）')}
          </button>

          <button
            onClick={handleBatchDelete}
            style={{ ...batchActionBtnStyle, color: 'var(--error, #ef4444)', borderColor: 'rgba(239,68,68,0.3)' }}
          >
            <Trash2 size={13} strokeWidth={1.8} /> {t('testcase.batchDelete', '批量删除')}
          </button>

          <div style={{ flex: 1 }} />

          <button
            onClick={() => setSelectedIds(new Set())}
            style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: 12 }}
          >
            {t('testcase.clearSelection', '取消勾选')}
          </button>
        </div>
      )}

      {/* 用例数据表格 */}
      <div style={{ flex: 1, overflowY: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: 13 }}>
          <thead>
            <tr
              style={{
                background: 'var(--bg-card)',
                borderBottom: '1px solid var(--border)',
                color: 'var(--text-secondary)',
                position: 'sticky',
                top: 0,
                zIndex: 10,
              }}
            >
              <th style={{ width: 44, padding: '10px 14px' }}>
                <span onClick={toggleSelectAll} style={{ cursor: 'pointer', display: 'inline-flex', alignItems: 'center' }}>
                  {isAllSelected ? (
                    <CheckSquare size={16} style={{ color: 'var(--accent)' }} />
                  ) : isPartiallySelected ? (
                    <MinusSquare size={16} style={{ color: 'var(--accent)' }} />
                  ) : (
                    <Square size={16} style={{ color: 'var(--text-muted)' }} />
                  )}
                </span>
              </th>
              <th style={{ width: 64, padding: '10px 8px' }}>ID</th>
              <th style={{ padding: '10px 8px' }}>{t('testcase.caseTitle', '用例标题')}</th>
              <th style={{ width: 90, padding: '10px 8px' }}>{t('testcase.type', '类型')}</th>
              <th style={{ width: 70, padding: '10px 8px' }}>{t('testcase.priority', '优先级')}</th>
              <th style={{ width: 80, padding: '10px 8px' }}>{t('testcase.status', '状态')}</th>
              <th style={{ width: 110, padding: '10px 8px' }}>{t('testcase.folder', '目录')}</th>
              <th style={{ width: 110, padding: '10px 8px' }}>{t('testcase.version', '版本')}</th>
              <th style={{ width: 100, padding: '10px 8px', textAlign: 'right' }}>{t('testcase.actions', '操作')}</th>
            </tr>
          </thead>
          <tbody>
            {filteredCases.length === 0 ? (
              <tr>
                <td colSpan={9} style={{ padding: '48px 16px', textAlign: 'center', color: 'var(--text-muted)' }}>
                  {t('testcase.noCasesMatch', '暂无符合条件的用例')}
                </td>
              </tr>
            ) : (
              filteredCases.map((c) => {
                const isSelected = selectedIds.has(c.id);
                const isActive = activeId === c.id;
                const folderName = c.folder_id ? folderMap.get(c.folder_id) || `#${c.folder_id}` : null;
                const versionName = c.version_id ? versionMap.get(c.version_id) || `#${c.version_id}` : null;

                return (
                  <tr
                    key={c.id}
                    onClick={() => selectCase(c.id)}
                    style={{
                      borderBottom: '1px solid var(--border)',
                      background: isActive
                        ? 'rgba(91,140,123,0.1)'
                        : isSelected
                        ? 'rgba(91,140,123,0.04)'
                        : 'transparent',
                      cursor: 'pointer',
                      transition: 'background 0.15s ease',
                    }}
                    onMouseEnter={(e) => {
                      if (!isActive && !isSelected) e.currentTarget.style.background = 'var(--bg-elevated)';
                    }}
                    onMouseLeave={(e) => {
                      if (!isActive && !isSelected) e.currentTarget.style.background = 'transparent';
                    }}
                  >
                    {/* 复选框 */}
                    <td style={{ padding: '10px 14px' }}>
                      <span onClick={(e) => toggleSelect(c.id, e)} style={{ display: 'inline-flex', alignItems: 'center' }}>
                        {isSelected ? (
                          <CheckSquare size={16} style={{ color: 'var(--accent)' }} />
                        ) : (
                          <Square size={16} style={{ color: 'var(--text-muted)' }} />
                        )}
                      </span>
                    </td>

                    {/* ID */}
                    <td style={{ padding: '10px 8px', color: 'var(--text-muted)', fontSize: 12 }}>
                      #{c.id}
                    </td>

                    {/* 标题 */}
                    <td style={{ padding: '10px 8px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <span style={{ fontWeight: 500, color: 'var(--text-primary)' }}>
                          {c.title}
                        </span>
                        {c.tags && c.tags.slice(0, 2).map((t, i) => (
                          <span
                            key={i}
                            style={{
                              fontSize: 10,
                              padding: '1px 5px',
                              borderRadius: 4,
                              background: 'var(--bg-card)',
                              border: '1px solid var(--border)',
                              color: 'var(--text-muted)',
                            }}
                          >
                            {t}
                          </span>
                        ))}
                      </div>
                    </td>

                    {/* 类型 */}
                    <td style={{ padding: '10px 8px' }}>
                      <span style={{ fontSize: 11, color: 'var(--text-secondary)' }}>
                        {formatCaseType(c.type)}
                      </span>
                    </td>

                    {/* 优先级 */}
                    <td style={{ padding: '10px 8px' }}>
                      <span
                        style={{
                          fontSize: 10,
                          fontWeight: 700,
                          color: PRIORITY_COLOR[c.priority] || 'var(--text-muted)',
                          padding: '1px 5px',
                          borderRadius: 3,
                          background: 'var(--bg-card)',
                          border: `1px solid ${PRIORITY_COLOR[c.priority] || 'var(--border)'}`,
                        }}
                      >
                        {c.priority.toUpperCase()}
                      </span>
                    </td>

                    {/* 状态 */}
                    <td style={{ padding: '10px 8px' }}>
                      <span
                        style={{
                          fontSize: 11,
                          color: STATUS_COLOR[c.status] || 'var(--text-muted)',
                          padding: '1px 5px',
                          borderRadius: 3,
                          border: `1px solid ${STATUS_COLOR[c.status] || 'var(--border)'}`,
                        }}
                      >
                        {c.status}
                      </span>
                    </td>

                    {/* 目录 */}
                    <td style={{ padding: '10px 8px', color: 'var(--text-secondary)', fontSize: 12 }}>
                      {folderName ? `📁 ${folderName}` : <span style={{ color: 'var(--text-muted)' }}>-</span>}
                    </td>

                    {/* 版本 */}
                    <td style={{ padding: '10px 8px', color: 'var(--text-secondary)', fontSize: 12 }}>
                      {versionName ? `🏷️ ${versionName}` : <span style={{ color: 'var(--text-muted)' }}>-</span>}
                    </td>

                    {/* 操作列 */}
                    <td style={{ padding: '10px 14px', textAlign: 'right' }}>
                      <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            selectCase(c.id);
                          }}
                          style={{
                            background: 'none',
                            border: 'none',
                            color: 'var(--accent)',
                            cursor: 'pointer',
                            fontSize: 12,
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: 2,
                            padding: '2px 4px',
                          }}
                        >
                          <Eye size={12} /> 查看
                        </button>
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            confirm({
                              title: t('testcase.confirmDelete'),
                              message: t('testcase.confirmDeleteMessage', { title: c.title }),
                              variant: 'danger',
                              onConfirm: () => deleteCase(c.id),
                            });
                          }}
                          style={{
                            background: 'none',
                            border: 'none',
                            color: 'var(--text-muted)',
                            cursor: 'pointer',
                            fontSize: 12,
                            padding: '2px 4px',
                          }}
                          onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--error, #ef4444)')}
                          onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--text-muted)')}
                        >
                          ×
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* 批量修改用例归属弹窗 */}
      <BatchAssignModal
        open={assignModalOpen}
        caseIds={Array.from(selectedIds)}
        onClose={() => setAssignModalOpen(false)}
        onSuccess={() => {
          setSelectedIds(new Set());
          loadCases();
          loadFolders();
        }}
      />
    </div>
  );
}

const filterSelectStyle: CSSProperties = {
  background: 'var(--bg-base)',
  border: '1px solid var(--border)',
  color: 'var(--text-primary)',
  padding: '6px 10px',
  borderRadius: 6,
  fontSize: 12,
  outline: 'none',
  cursor: 'pointer',
};

const batchActionBtnStyle: CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 5,
  padding: '4px 10px',
  borderRadius: 5,
  fontSize: 12,
  background: 'var(--bg-card)',
  border: '1px solid var(--border)',
  color: 'var(--text-primary)',
  cursor: 'pointer',
};
