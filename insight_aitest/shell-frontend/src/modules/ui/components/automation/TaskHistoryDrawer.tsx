import { useEffect } from 'react';
import { toast } from 'sonner';
import { X, History, FileText, CheckCircle2, XCircle, RefreshCw, Loader2 } from 'lucide-react';
import { Btn } from './common';
import { useTaskStore } from '../../store/taskStore';

interface TaskHistoryDrawerProps {
  open: boolean;
  onClose: () => void;
  taskId: number;
  taskName: string;
  onOpenReport: (runId: number) => void;
}

export function TaskHistoryDrawer({
  open,
  onClose,
  taskId,
  taskName,
  onOpenReport,
}: TaskHistoryDrawerProps) {
  const { currentTaskRuns, loadingRuns, loadTaskRuns } = useTaskStore();

  useEffect(() => {
    if (open && taskId) {
      loadTaskRuns(taskId).catch((err) => {
        toast.error(err.message || '加载执行历史失败');
      });
    }
  }, [open, taskId, loadTaskRuns]);

  if (!open) return null;

  const handleRefresh = () => {
    loadTaskRuns(taskId).catch(() => {});
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
          width: 640,
          maxWidth: '92vw',
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
              <History size={18} style={{ color: 'var(--accent)' }} />
              <span>任务执行历史</span>
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>
              {taskName}（历史执行记录与测试报告）
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Btn size="sm" onClick={handleRefresh} disabled={loadingRuns} title="刷新历史">
              <RefreshCw size={13} style={{ animation: loadingRuns ? 'spin 1s linear infinite' : 'none' }} />
              刷新
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

        {/* Runs List */}
        <div style={{ flex: 1, overflowY: 'auto', padding: 16 }}>
          {loadingRuns && currentTaskRuns.length === 0 ? (
            <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
              加载历史记录中...
            </div>
          ) : currentTaskRuns.length === 0 ? (
            <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
              暂无历史执行记录
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {currentTaskRuns.map((r) => {
                const isPassed = r.status === 'passed';
                const isRunning = r.status === 'running';
                const dateStr = r.started_at ? new Date(r.started_at).toLocaleString() : '-';

                return (
                  <div
                    key={r.id}
                    style={{
                      padding: '12px 16px',
                      background: 'var(--bg-card)',
                      border: '1px solid var(--border)',
                      borderRadius: 8,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      gap: 12,
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                      {isRunning ? (
                        <Loader2 size={18} style={{ color: 'var(--accent)', animation: 'spin 1s linear infinite' }} />
                      ) : isPassed ? (
                        <CheckCircle2 size={18} style={{ color: 'var(--success, #10b981)' }} />
                      ) : (
                        <XCircle size={18} style={{ color: 'var(--error, #ef4444)' }} />
                      )}

                      <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                          <strong style={{ fontSize: 13, color: 'var(--text-primary)' }}>
                            批次 #{r.id}
                          </strong>
                          <span
                            style={{
                              fontSize: 10,
                              padding: '1px 5px',
                              borderRadius: 4,
                              border: '1px solid var(--border)',
                              color: 'var(--text-muted)',
                            }}
                          >
                            {r.trigger_type === 'cron' ? '定时调度' : '手动触发'}
                          </span>
                        </div>
                        <div style={{ fontSize: 11, color: 'var(--text-muted)', display: 'flex', gap: 12 }}>
                          <span>时间：{dateStr}</span>
                          <span>耗时：{(r.duration_ms / 1000).toFixed(1)}s</span>
                          <span>
                            通过：
                            <strong style={{ color: 'var(--success, #10b981)' }}>{r.passed_cases}</strong> / {r.total_cases}
                          </span>
                        </div>
                      </div>
                    </div>

                    <Btn
                      size="sm"
                      onClick={() => onOpenReport(r.id)}
                      disabled={isRunning}
                      style={{ flexShrink: 0 }}
                    >
                      <FileText size={13} /> 查看测试报告
                    </Btn>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

