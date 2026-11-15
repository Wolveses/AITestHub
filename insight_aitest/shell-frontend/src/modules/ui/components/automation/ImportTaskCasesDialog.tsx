import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import { X, Search, CheckCircle2, CheckSquare, Square, Download } from 'lucide-react';
import { Btn, inputStyle } from './common';
import { CategoryTree } from './CategoryTree';
import { useTaskStore, type ImportableCategory } from '../../store/taskStore';

interface ImportTaskCasesDialogProps {
  open: boolean;
  onClose: () => void;
  taskId: number;
  taskName: string;
  projectId: number;
  onImported: () => void;
}

export function ImportTaskCasesDialog({
  open,
  onClose,
  taskId,
  taskName,
  projectId,
  onImported,
}: ImportTaskCasesDialogProps) {
  const { loadImportableCases, importCasesToTask } = useTaskStore();

  const [categories, setCategories] = useState<ImportableCategory[]>([]);
  const [totalImplemented, setTotalImplemented] = useState(0);
  const [loading, setLoading] = useState(false);
  const [keyword, setKeyword] = useState('');
  const [folder, setFolder] = useState<string | null>(null);
  const [selectedCaseIds, setSelectedCaseIds] = useState<Set<number>>(new Set());
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (open && taskId) {
      setLoading(true);
      setSelectedCaseIds(new Set());
      setKeyword('');
      setFolder(null);
      loadImportableCases(taskId, projectId)
        .then((res) => {
          setCategories(res.categories || []);
          setTotalImplemented(Number(res.total_implemented) || 0);
        })
        .catch((err) => {
          toast.error(err.message || '加载可导入用例失败');
        })
        .finally(() => {
          setLoading(false);
        });
    }
  }, [open, taskId, projectId, loadImportableCases]);

  // 左侧目录树：由用例自身的 category_path 聚合，计数即真实条目数
  const treeItems = useMemo(
    () =>
      categories.flatMap((cat) =>
        cat.cases.map((c) => ({ category_path: c.category_path || cat.name, count: 1 }))
      ),
    [categories]
  );

  // 目录筛选（路径本身或其子路径）+ 关键字过滤
  const filteredCategories = useMemo(() => {
    const kw = keyword.trim().toLowerCase();
    return categories
      .filter((cat) => !folder || cat.name === folder || cat.name.startsWith(`${folder} / `))
      .map((cat) => ({
        ...cat,
        cases: cat.cases.filter((c) => {
          if (!kw) return true;
          return c.title.toLowerCase().includes(kw) || c.category_path.toLowerCase().includes(kw);
        }),
      }))
      .filter((cat) => cat.cases.length > 0); // 空目录严格不展示
  }, [categories, folder, keyword]);

  // 右侧扁平列表：目录分组信息挂在条目上，便于展示与全选
  const visibleCases = useMemo(
    () =>
      filteredCategories.flatMap((cat) =>
        cat.cases.map((c) => ({ caseItem: c, categoryName: cat.name }))
      ),
    [filteredCategories]
  );

  // 当前列表里可勾选（未导入）的用例 ID
  const availableUnimportedIds = useMemo(
    () => visibleCases.filter((v) => !v.caseItem.already_imported).map((v) => v.caseItem.id),
    [visibleCases]
  );

  const allSelected =
    availableUnimportedIds.length > 0 &&
    availableUnimportedIds.every((id) => selectedCaseIds.has(id));

  if (!open) return null;

  const handleToggleSelectAll = () => {
    setSelectedCaseIds((prev) => {
      const next = new Set(prev);
      if (allSelected) {
        availableUnimportedIds.forEach((id) => next.delete(id));
      } else {
        availableUnimportedIds.forEach((id) => next.add(id));
      }
      return next;
    });
  };

  const handleToggleCase = (id: number) => {
    setSelectedCaseIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleSubmit = async () => {
    if (selectedCaseIds.size === 0) {
      toast.warning('请至少选择一条用例导入');
      return;
    }
    setSubmitting(true);
    try {
      const ids = Array.from(selectedCaseIds);
      const res = await importCasesToTask(taskId, ids);
      toast.success(`成功导入 ${res.imported_count} 条用例`);
      onImported();
      onClose();
    } catch (err: any) {
      toast.error(err.message || '导入失败');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,.6)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: 860,
          maxWidth: '94vw',
          maxHeight: '85vh',
          background: 'var(--bg-card)',
          border: '1px solid var(--border)',
          borderRadius: 10,
          boxShadow: '0 12px 36px rgba(0,0,0,.45)',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
        }}
      >
        {/* Header */}
        <div
          style={{
            padding: '14px 18px',
            borderBottom: '1px solid var(--border)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <div>
            <strong style={{ fontSize: 15, color: 'var(--text-primary)' }}>
              从同项目自动化用例导入
            </strong>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>
              任务：{taskName}（仅展示当前项目已实现的固化用例）
            </div>
          </div>
          <button
            onClick={onClose}
            style={{
              background: 'transparent',
              border: 'none',
              cursor: 'pointer',
              color: 'var(--text-muted)',
              display: 'flex',
              padding: 4,
            }}
          >
            <X size={16} />
          </button>
        </div>

        {/* Toolbar */}
        <div
          style={{
            padding: '10px 18px',
            borderBottom: '1px solid var(--border)',
            background: 'var(--bg-base)',
            display: 'flex',
            alignItems: 'center',
            gap: 12,
          }}
        >
          <div style={{ position: 'relative', flex: 1 }}>
            <Search
              size={14}
              style={{
                position: 'absolute',
                left: 10,
                top: '50%',
                transform: 'translateY(-50%)',
                color: 'var(--text-muted)',
              }}
            />
            <input
              type="text"
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              placeholder="搜索用例名称..."
              style={{ ...inputStyle, paddingLeft: 30 }}
            />
          </div>
        </div>

        {/* Body: 左树 + 右条目 */}
        <div style={{ flex: 1, minHeight: 0, display: 'flex', padding: '12px 18px' }}>
          {loading ? (
            <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)', fontSize: 13, width: '100%' }}>
              加载可导入用例中...
            </div>
          ) : categories.length === 0 ? (
            <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)', fontSize: 13, width: '100%' }}>
              暂无可导入的已实现用例（请先在自动化用例页生成脚本）
            </div>
          ) : (
            <div
              style={{
                flex: 1,
                display: 'flex',
                minHeight: 0,
                border: '1px solid var(--border)',
                borderRadius: 8,
                overflow: 'hidden',
              }}
            >
              <CategoryTree
                items={treeItems}
                allCount={totalImplemented || treeItems.length}
                active={folder}
                onSelect={setFolder}
                allLabel="全部用例"
              />

              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    padding: '6px 12px',
                    borderBottom: '1px solid var(--bg-card)',
                    flexShrink: 0,
                  }}
                >
                  <span
                    onClick={() => availableUnimportedIds.length > 0 && handleToggleSelectAll()}
                    title="全选/取消全选当前列表"
                    style={{
                      display: 'inline-flex',
                      cursor: availableUnimportedIds.length === 0 ? 'not-allowed' : 'pointer',
                      opacity: availableUnimportedIds.length === 0 ? 0.5 : 1,
                      color: allSelected ? 'var(--accent)' : 'var(--text-muted)',
                    }}
                  >
                    {allSelected ? <CheckSquare size={15} /> : <Square size={15} />}
                  </span>
                  <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                    当前目录 {visibleCases.length} 条，可导入 {availableUnimportedIds.length} 条
                  </span>
                </div>

                <div style={{ flex: 1, overflowY: 'auto' }}>
                  {visibleCases.length === 0 ? (
                    <div style={{ padding: 32, textAlign: 'center', color: 'var(--text-muted)', fontSize: 12 }}>
                      {keyword.trim() || folder ? '该目录下暂无匹配的已实现用例' : '暂无可导入的已实现用例'}
                    </div>
                  ) : (
                    visibleCases.map(({ caseItem: c, categoryName }) => {
                      const isImported = c.already_imported;
                      const isSelected = selectedCaseIds.has(c.id);

                      return (
                        <div
                          key={c.id}
                          onClick={() => {
                            if (!isImported) handleToggleCase(c.id);
                          }}
                          style={{
                            padding: '8px 12px',
                            display: 'flex',
                            alignItems: 'center',
                            gap: 10,
                            borderBottom: '1px solid var(--border-subtle, rgba(255,255,255,0.05))',
                            cursor: isImported ? 'not-allowed' : 'pointer',
                            background: isSelected ? 'rgba(59,130,246,0.06)' : 'transparent',
                            opacity: isImported ? 0.6 : 1,
                          }}
                        >
                          <span
                            style={{
                              display: 'inline-flex',
                              color: isImported || isSelected ? 'var(--accent)' : 'var(--text-muted)',
                            }}
                          >
                            {isImported || isSelected ? <CheckSquare size={15} /> : <Square size={15} />}
                          </span>

                          <div style={{ flex: 1, minWidth: 0 }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                              <span
                                style={{
                                  fontSize: 13,
                                  color: isImported ? 'var(--text-muted)' : 'var(--text-primary)',
                                  overflow: 'hidden',
                                  textOverflow: 'ellipsis',
                                  whiteSpace: 'nowrap',
                                }}
                              >
                                {c.title}
                              </span>
                              <span
                                style={{
                                  fontSize: 10,
                                  padding: '1px 5px',
                                  borderRadius: 4,
                                  border: '1px solid var(--border)',
                                  color: 'var(--text-muted)',
                                  flexShrink: 0,
                                }}
                              >
                                {c.site === 'backend' ? '后台' : '前台'}
                              </span>
                            </div>
                            <div
                              style={{
                                fontSize: 11,
                                color: 'var(--text-muted)',
                                marginTop: 2,
                                overflow: 'hidden',
                                textOverflow: 'ellipsis',
                                whiteSpace: 'nowrap',
                              }}
                            >
                              {c.category_path || categoryName || '未分类'}
                            </div>
                          </div>

                          {isImported ? (
                            <span
                              style={{
                                fontSize: 11,
                                color: 'var(--text-muted)',
                                display: 'inline-flex',
                                alignItems: 'center',
                                gap: 3,
                                flexShrink: 0,
                              }}
                            >
                              <CheckCircle2 size={12} /> 已在此任务中
                            </span>
                          ) : (
                            <span
                              style={{
                                fontSize: 11,
                                color: 'var(--success, #10b981)',
                                background: 'rgba(16,185,129,0.1)',
                                padding: '1px 6px',
                                borderRadius: 4,
                                flexShrink: 0,
                              }}
                            >
                              已实现
                            </span>
                          )}
                        </div>
                      );
                    })
                  )}
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div
          style={{
            padding: '12px 18px',
            borderTop: '1px solid var(--border)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            background: 'var(--bg-base)',
          }}
        >
          <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            已选 <strong style={{ color: 'var(--accent)' }}>{selectedCaseIds.size}</strong> 条用例
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <Btn onClick={onClose} disabled={submitting}>
              取消
            </Btn>
            <Btn
              variant="primary"
              onClick={handleSubmit}
              disabled={submitting || selectedCaseIds.size === 0}
            >
              <Download size={14} />
              {submitting ? '导入中...' : `导入选中用例 (${selectedCaseIds.size})`}
            </Btn>
          </div>
        </div>
      </div>
    </div>
  );
}
