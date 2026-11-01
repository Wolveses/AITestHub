import { useEffect } from 'react';
import { toast } from 'sonner';
import { X, Trash2, Download, ListChecks } from 'lucide-react';
import { Btn } from './common';
import { useTaskStore } from '../../store/taskStore';
import { useConfirmStore } from '../../../../shared/store/confirmStore';

interface TaskCasesDrawerProps {
  open: boolean;
  onClose: () => void;
  taskId: number;
  taskName: string;
  onImportClick: () => void;
}

export function TaskCasesDrawer({
  open,
  onClose,
  taskId,
  taskName,
  onImportClick,
}: TaskCasesDrawerProps) {
  const { currentTaskCases, loadingCases, loadTaskCases, removeCaseFromTask } = useTaskStore();
  const { confirm } = useConfirmStore();

  useEffect(() => {
    if (open && taskId) {
      loadTaskCases(taskId).catch((err) => {
        toast.error(err.message || '加载用例失败');
      });
    }
  }, [open, taskId, loadTaskCases]);

  if (!open) return null;

  const handleRemove = (caseId: number, title: string) => {
    confirm({
      title: '移除用例',
      message: `确定要从任务中移除用例「${title}」吗？（用例本体不会被删除）`,
      confirmText: '确认移除',
      variant: 'danger',
      onConfirm: async () => {
        try {
          await removeCaseFromTask(taskId, caseId);
          toast.success('已从任务中移除');
        } catch (err: any) {
          toast.error(err.message || '移除失败');
        }
      },
    });
  };

  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,.5)',
        zIndex: 1000,
        display: 'flex',
        justifyContent: 'flex-end',
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: 580,
          maxWidth: '90vw',
          height: '100%',
          background: 'var(--bg-base)',
          borderLeft: '1px solid var(--border)',
          display: 'flex',
          flexDirection: 'column',
          boxShadow: '-8px 0 32px rgba(0,0,0,.35)',
        }}
      >
        {/* Header */}
        <div
          style={{
            padding: '16px 20px',
            borderBottom: '1px solid var(--border)',
            background: 'var(--bg-card)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 15, fontWeight: 600, color: 'var(--text-primary)' }}>
              <ListChecks size={18} style={{ color: 'var(--accent)' }} />
              <span>任务用例列表</span>
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>
              {taskName}（共 {currentTaskCases.length} 条用例）
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Btn size="sm" variant="primary" onClick={onImportClick}>
              <Download size={13} /> 导入用例
            </Btn>
            <button
              onClick={onClose}
              style={{
                background: 'transparent',
                border: 'none',
                cursor: 'pointer',
                color: 'var(--text-muted)',
                padding: 4,
                display: 'flex',
              }}
            >
              <X size={18} />
            </button>
          </div>
        </div>

        {/* List */}
        <div style={{ flex: 1, overflowY: 'auto', padding: 16 }}>
          {loadingCases ? (
            <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
              加载用例中...
            </div>
          ) : currentTaskCases.length === 0 ? (
            <div
              style={{
                padding: 40,
                textAlign: 'center',
                color: 'var(--text-muted)',
                fontSize: 13,
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                gap: 12,
              }}
            >
              <div>该任务暂未导入任何自动化用例</div>
              <Btn variant="primary" size="sm" onClick={onImportClick}>
                <Download size={13} /> 立即导入已实现的用例
              </Btn>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {currentTaskCases.map((tc, idx) => (
                <div
                  key={tc.id}
                  style={{
                    padding: '10px 14px',
                    background: 'var(--bg-card)',
                    border: '1px solid var(--border)',
                    borderRadius: 8,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    gap: 12,
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, flex: 1, minWidth: 0 }}>
                    <span
                      style={{
                        fontSize: 11,
                        color: 'var(--text-muted)',
                        fontFamily: 'monospace',
                        minWidth: 20,
                      }}
                    >
                      {idx + 1}.
                    </span>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 3, flex: 1, minWidth: 0 }}>
                      <span
                        style={{
                          fontSize: 13,
                          fontWeight: 500,
                          color: 'var(--text-primary)',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {tc.title}
                      </span>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                          {tc.category || '未分类'}
                        </span>
                        <span
                          style={{
                            fontSize: 10,
                            padding: '0 4px',
                            borderRadius: 4,
                            border: '1px solid var(--border)',
                            color: 'var(--text-muted)',
                          }}
                        >
                          {tc.site === 'backend' ? '后台' : '前台'}
                        </span>
                      </div>
                    </div>
                  </div>

                  <button
                    onClick={() => handleRemove(tc.case_id, tc.title)}
                    title="从任务移除"
                    style={{
                      background: 'transparent',
                      border: 'none',
                      color: 'var(--text-muted)',
                      cursor: 'pointer',
                      padding: 6,
                      borderRadius: 4,
                      display: 'flex',
                      alignItems: 'center',
                    }}
                    onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--error)')}
                    onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--text-muted)')}
                  >
                    <Trash2 size={15} />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
