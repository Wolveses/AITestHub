import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import { X, Search, CheckCircle2, Folder, Download } from 'lucide-react';
import { Btn, inputStyle } from './common';
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
  const [loading, setLoading] = useState(false);
  const [keyword, setKeyword] = useState('');
  const [selectedCaseIds, setSelectedCaseIds] = useState<Set<number>>(new Set());
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (open && taskId) {
      setLoading(true);
      setSelectedCaseIds(new Set());
      setKeyword('');
      loadImportableCases(taskId, projectId)
        .then((res) => {
          setCategories(res.categories || []);
        })
        .catch((err) => {
          toast.error(err.message || '加载可导入用例失败');
        })
        .finally(() => {
          setLoading(false);
        });
    }
  }, [open, taskId, projectId, loadImportableCases]);

  // 搜索过滤与空目录不展示
  const filteredCategories = useMemo(() => {
    const kw = keyword.trim().toLowerCase();
    return categories
      .map((cat) => {
        const matchedCases = cat.cases.filter((c) =>
          !kw || c.title.toLowerCase().includes(kw),
        );
        return { ...cat, cases: matchedCases };
      })
      .filter((cat) => cat.cases.length > 0); // 空目录严格不展示
  }, [categories, keyword]);

  // 所有可勾选（未导入）的用例 ID 集合
  const availableUnimportedIds = useMemo(() => {
    const ids: number[] = [];
    filteredCategories.forEach((cat) => {
      cat.cases.forEach((c) => {
        if (!c.already_imported) ids.push(c.id);
      });
    });
    return ids;
  }, [filteredCategories]);

  if (!open) return null;

  const handleToggleSelectAll = () => {
    if (selectedCaseIds.size === availableUnimportedIds.length) {
      setSelectedCaseIds(new Set());
    } else {
      setSelectedCaseIds(new Set(availableUnimportedIds));
    }
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
          width: 680,
          maxWidth: '92vw',
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
              任务：{taskName}（仅展示当前项目已实现的固化用例，空目录不展示）
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
          {availableUnimportedIds.length > 0 && (
            <Btn size="sm" onClick={handleToggleSelectAll}>
              {selectedCaseIds.size === availableUnimportedIds.length ? '取消全选' : '全选未导入'}
            </Btn>
          )}
        </div>

        {/* Body Case Tree / List */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '12px 18px' }}>
          {loading ? (
            <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
              加载可导入用例中...
            </div>
          ) : filteredCategories.length === 0 ? (
            <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
              {keyword ? '未搜索到匹配的已实现用例' : '暂无可导入的已实现用例（请先在自动化用例页生成脚本）'}
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              {filteredCategories.map((cat) => (
                <div
                  key={cat.name}
                  style={{
                    border: '1px solid var(--border)',
                    borderRadius: 8,
                    overflow: 'hidden',
                    background: 'var(--bg-base)',
                  }}
                >
                  {/* Category Header */}
                  <div
                    style={{
                      padding: '8px 12px',
                      background: 'var(--bg-card)',
                      borderBottom: '1px solid var(--border)',
                      fontSize: 12,
                      fontWeight: 600,
                      color: 'var(--text-secondary)',
                      display: 'flex',
                      alignItems: 'center',
                      gap: 6,
                    }}
                  >
                    <Folder size={14} style={{ opacity: 0.8 }} />
                    <span>{cat.name}</span>
                    <span style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 400 }}>
                      ({cat.cases.length} 条已实现用例)
                    </span>
                  </div>

                  {/* Cases list */}
                  <div style={{ display: 'flex', flexDirection: 'column' }}>
                    {cat.cases.map((c) => {
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
                            background: isImported
                              ? 'transparent'
                              : isSelected
                                ? 'rgba(59,130,246,0.06)'
                                : 'transparent',
                            opacity: isImported ? 0.6 : 1,
                          }}
                        >
                          <input
                            type="checkbox"
                            checked={isImported || isSelected}
                            disabled={isImported}
                            onChange={() => {
                              if (!isImported) handleToggleCase(c.id);
                            }}
                            style={{ cursor: isImported ? 'not-allowed' : 'pointer' }}
                          />

                          <div style={{ flex: 1, minWidth: 0, display: 'flex', alignItems: 'center', gap: 8 }}>
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
                              }}
                            >
                              {c.site === 'backend' ? '后台' : '前台'}
                            </span>
                          </div>

                          {isImported ? (
                            <span
                              style={{
                                fontSize: 11,
                                color: 'var(--text-muted)',
                                display: 'inline-flex',
                                alignItems: 'center',
                                gap: 3,
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
                              }}
                            >
                              已实现
                            </span>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              ))}
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
