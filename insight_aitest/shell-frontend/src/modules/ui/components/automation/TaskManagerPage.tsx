import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import {
  Plus,
  Play,
  Download,
  History,
  Pencil,
  Trash2,
  Clock,
  Search,
  RefreshCw,
  CheckCircle2,
  XCircle,
  Loader2,
  ListChecks,
} from 'lucide-react';
import { Btn, inputStyle } from './common';
import { useProjectStore } from '../../../../shared/store/projectStore';
import { useConfirmStore } from '../../../../shared/store/confirmStore';
import { useTaskStore, type UiTaskItem } from '../../store/taskStore';
import { TaskEditModal } from './TaskEditModal';
import { ImportTaskCasesDialog } from './ImportTaskCasesDialog';
import { TaskCasesDrawer } from './TaskCasesDrawer';
import { TaskHistoryDrawer } from './TaskHistoryDrawer';
import { TaskReportModal } from './TaskReportModal';

export function TaskManagerPage() {
  const currentProjectId = useProjectStore((s) => s.currentProjectId);
  const { tasks, loading, loadTasks, deleteTask, runTask } = useTaskStore();
  const { confirm } = useConfirmStore();

  const [keyword, setKeyword] = useState('');
  const [editModalOpen, setEditModalOpen] = useState(false);
  const [editingTask, setEditingTask] = useState<UiTaskItem | null>(null);

  const [importDialogOpen, setImportDialogOpen] = useState(false);
  const [importTargetTask, setImportTargetTask] = useState<UiTaskItem | null>(null);

  const [casesDrawerOpen, setCasesDrawerOpen] = useState(false);
  const [casesTargetTask, setCasesTargetTask] = useState<UiTaskItem | null>(null);

  const [historyDrawerOpen, setHistoryDrawerOpen] = useState(false);
  const [historyTargetTask, setHistoryTargetTask] = useState<UiTaskItem | null>(null);

  const [reportModalOpen, setReportModalOpen] = useState(false);
  const [reportRunId, setReportRunId] = useState<number | null>(null);

  // 随全局项目切换自动载入任务
  useEffect(() => {
    if (currentProjectId !== null) {
      loadTasks(currentProjectId).catch((err) => {
        toast.error(err.message || '加载任务列表失败');
      });
    }
  }, [currentProjectId, loadTasks]);

  // 如果有正在运行的任务，启动轮询
  useEffect(() => {
    if (!currentProjectId) return;
    const hasRunning = tasks.some((t) => t.last_status === 'running');
    if (!hasRunning) return;

    const timer = setInterval(() => {
      loadTasks(currentProjectId).catch(() => {});
    }, 2500);
    return () => clearInterval(timer);
  }, [tasks, currentProjectId, loadTasks]);

  const filteredTasks = useMemo(() => {
    const kw = keyword.trim().toLowerCase();
    if (!kw) return tasks;
    return tasks.filter(
      (t) => t.name.toLowerCase().includes(kw) || (t.description && t.description.toLowerCase().includes(kw)),
    );
  }, [tasks, keyword]);

  const handleRunTask = async (task: UiTaskItem) => {
    try {
      await runTask(task.id);
      toast.success(`任务「${task.name}」已开始执行`);
      if (currentProjectId) loadTasks(currentProjectId);
    } catch (err: any) {
      toast.error(err.message || '执行失败');
    }
  };

  const handleDeleteTask = (task: UiTaskItem) => {
    confirm({
      title: '删除任务',
      message: `确定要删除任务「${task.name}」吗？关联的用例配置与历史记录也将被清理。`,
      confirmText: '确认删除',
      variant: 'danger',
      onConfirm: async () => {
        try {
          await deleteTask(task.id);
          toast.success('任务已删除');
        } catch (err: any) {
          toast.error(err.message || '删除失败');
        }
      },
    });
  };

  if (currentProjectId === null) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>
        请先在顶部选择一个项目
      </div>
    );
  }

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
      {/* Toolbar */}
      <div
        style={{
          padding: '10px 16px',
          borderBottom: '1px solid var(--border)',
          background: 'var(--bg-card)',
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          flexShrink: 0,
        }}
      >
        <Btn
          variant="primary"
          onClick={() => {
            setEditingTask(null);
            setEditModalOpen(true);
          }}
        >
          <Plus size={14} /> 新建任务
        </Btn>

        <div style={{ flex: 1 }} />

        <div style={{ position: 'relative', width: 220 }}>
          <Search
            size={13}
            style={{
              position: 'absolute',
              left: 9,
              top: '50%',
              transform: 'translateY(-50%)',
              color: 'var(--text-muted)',
            }}
          />
          <input
            type="text"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            placeholder="搜索任务名称..."
            style={{ ...inputStyle, paddingLeft: 28, height: 30 }}
          />
        </div>

        <Btn
          size="sm"
          onClick={() => {
            if (currentProjectId) loadTasks(currentProjectId);
          }}
          title="刷新列表"
        >
          <RefreshCw size={13} style={{ animation: loading ? 'spin 1s linear infinite' : 'none' }} />
        </Btn>
      </div>

      {/* Task List / Table */}
      <div style={{ flex: 1, overflowY: 'auto', padding: 16 }}>
        {loading && tasks.length === 0 ? (
          <div style={{ padding: 60, textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
            加载任务列表中...
          </div>
        ) : filteredTasks.length === 0 ? (
          <div
            style={{
              padding: 60,
              textAlign: 'center',
              color: 'var(--text-muted)',
              fontSize: 13,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: 12,
            }}
          >
            <div>{keyword ? '未搜索到匹配任务' : '当前项目暂无自动化任务，点击上方按钮新建一个任务吧'}</div>
            {!keyword && (
              <Btn
                variant="primary"
                onClick={() => {
                  setEditingTask(null);
                  setEditModalOpen(true);
                }}
              >
                <Plus size={14} /> 立即新建任务
              </Btn>
            )}
          </div>
        ) : (
          <div
            style={{
              border: '1px solid var(--border)',
              borderRadius: 8,
              background: 'var(--bg-card)',
              overflow: 'hidden',
            }}
          >
            <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: 13 }}>
              <thead>
                <tr
                  style={{
                    background: 'var(--bg-base)',
                    borderBottom: '1px solid var(--border)',
                    color: 'var(--text-muted)',
                    fontSize: 12,
                  }}
                >
                  <th style={{ padding: '10px 16px' }}>任务名称</th>
                  <th style={{ padding: '10px 14px', width: 140 }}>执行环境</th>
                  <th style={{ padding: '10px 14px', width: 150 }}>定时调度</th>
                  <th style={{ padding: '10px 14px', width: 110 }}>包含用例</th>
                  <th style={{ padding: '10px 14px', width: 120 }}>最近状态</th>
                  <th style={{ padding: '10px 14px', width: 150 }}>最近执行时间</th>
                  <th style={{ padding: '10px 16px', width: 220, textAlign: 'right' }}>操作</th>
                </tr>
              </thead>
              <tbody>
                {filteredTasks.map((task) => {
                  const isRunning = task.last_status === 'running';
                  const isPassed = task.last_status === 'passed';
                  const isFailed = task.last_status === 'failed';
                  const dateStr = task.last_run_at ? new Date(task.last_run_at).toLocaleString() : '-';

                  return (
                    <tr
                      key={task.id}
                      style={{
                        borderBottom: '1px solid var(--border-subtle, rgba(255,255,255,0.05))',
                        transition: 'background 0.15s ease',
                      }}
                    >
                      {/* Name & Desc */}
                      <td style={{ padding: '12px 16px' }}>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                          <strong style={{ color: 'var(--text-primary)', fontSize: 13 }}>{task.name}</strong>
                          {task.description && (
                            <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{task.description}</span>
                          )}
                        </div>
                      </td>

                      {/* Env */}
                      <td style={{ padding: '12px 14px' }}>
                        <span
                          style={{
                            fontSize: 11,
                            padding: '2px 8px',
                            borderRadius: 4,
                            background: 'var(--bg-base)',
                            border: '1px solid var(--border)',
                            color: 'var(--text-secondary)',
                          }}
                        >
                          {task.env_name || `环境 #${task.env_id}`}
                        </span>
                      </td>

                      {/* Cron */}
                      <td style={{ padding: '12px 14px' }}>
                        {task.cron_enabled && task.cron_expression ? (
                          <div style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12, color: 'var(--accent)' }}>
                            <Clock size={13} />
                            <code style={{ fontSize: 11 }}>{task.cron_expression}</code>
                          </div>
                        ) : (
                          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>未启用</span>
                        )}
                      </td>

                      {/* Case count */}
                      <td style={{ padding: '12px 14px' }}>
                        <button
                          onClick={() => {
                            setCasesTargetTask(task);
                            setCasesDrawerOpen(true);
                          }}
                          style={{
                            background: 'transparent',
                            border: '1px solid var(--border)',
                            borderRadius: 12,
                            padding: '2px 8px',
                            fontSize: 11,
                            color: task.case_count > 0 ? 'var(--text-primary)' : 'var(--text-muted)',
                            cursor: 'pointer',
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: 4,
                          }}
                          title="点击查看任务关联用例"
                        >
                          <ListChecks size={12} />
                          {task.case_count} 条
                        </button>
                      </td>

                      {/* Status */}
                      <td style={{ padding: '12px 14px' }}>
                        {isRunning ? (
                          <span
                            style={{
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: 4,
                              fontSize: 11,
                              fontWeight: 600,
                              color: 'var(--accent)',
                              background: 'rgba(59,130,246,0.1)',
                              padding: '2px 8px',
                              borderRadius: 4,
                            }}
                          >
                            <Loader2 size={12} style={{ animation: 'spin 1s linear infinite' }} /> 执行中
                          </span>
                        ) : isPassed ? (
                          <span
                            style={{
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: 4,
                              fontSize: 11,
                              fontWeight: 600,
                              color: 'var(--success, #10b981)',
                              background: 'rgba(16,185,129,0.1)',
                              padding: '2px 8px',
                              borderRadius: 4,
                            }}
                          >
                            <CheckCircle2 size={12} /> 全部通过
                          </span>
                        ) : isFailed ? (
                          <span
                            style={{
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: 4,
                              fontSize: 11,
                              fontWeight: 600,
                              color: 'var(--error, #ef4444)',
                              background: 'rgba(239,68,68,0.1)',
                              padding: '2px 8px',
                              borderRadius: 4,
                            }}
                          >
                            <XCircle size={12} /> 执行未通过
                          </span>
                        ) : (
                          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>未执行</span>
                        )}
                      </td>

                      {/* Last run at */}
                      <td style={{ padding: '12px 14px', fontSize: 11, color: 'var(--text-muted)' }}>
                        {dateStr}
                      </td>

                      {/* Actions */}
                      <td style={{ padding: '12px 16px', textAlign: 'right' }}>
                        <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                          <button
                            onClick={() => handleRunTask(task)}
                            disabled={isRunning}
                            title="立即执行任务"
                            style={{
                              background: 'transparent',
                              border: 'none',
                              color: isRunning ? 'var(--text-muted)' : 'var(--accent)',
                              cursor: isRunning ? 'not-allowed' : 'pointer',
                              padding: 5,
                              borderRadius: 4,
                              display: 'flex',
                              alignItems: 'center',
                            }}
                          >
                            <Play size={15} />
                          </button>

                          <button
                            onClick={() => {
                              setImportTargetTask(task);
                              setImportDialogOpen(true);
                            }}
                            title="从自动化用例导入"
                            style={{
                              background: 'transparent',
                              border: 'none',
                              color: 'var(--text-secondary)',
                              cursor: 'pointer',
                              padding: 5,
                              borderRadius: 4,
                              display: 'flex',
                              alignItems: 'center',
                            }}
                          >
                            <Download size={15} />
                          </button>

                          <button
                            onClick={() => {
                              setHistoryTargetTask(task);
                              setHistoryDrawerOpen(true);
                            }}
                            title="查看执行历史与测试报告"
                            style={{
                              background: 'transparent',
                              border: 'none',
                              color: 'var(--text-secondary)',
                              cursor: 'pointer',
                              padding: 5,
                              borderRadius: 4,
                              display: 'flex',
                              alignItems: 'center',
                            }}
                          >
                            <History size={15} />
                          </button>

                          <button
                            onClick={() => {
                              setEditingTask(task);
                              setEditModalOpen(true);
                            }}
                            title="编辑任务"
                            style={{
                              background: 'transparent',
                              border: 'none',
                              color: 'var(--text-secondary)',
                              cursor: 'pointer',
                              padding: 5,
                              borderRadius: 4,
                              display: 'flex',
                              alignItems: 'center',
                            }}
                          >
                            <Pencil size={15} />
                          </button>

                          <button
                            onClick={() => handleDeleteTask(task)}
                            title="删除任务"
                            style={{
                              background: 'transparent',
                              border: 'none',
                              color: 'var(--text-muted)',
                              cursor: 'pointer',
                              padding: 5,
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
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Modals & Drawers */}
      <TaskEditModal
        open={editModalOpen}
        onClose={() => setEditModalOpen(false)}
        task={editingTask}
        projectId={currentProjectId}
        onSaved={() => {
          if (currentProjectId) loadTasks(currentProjectId);
        }}
      />

      {importTargetTask && (
        <ImportTaskCasesDialog
          open={importDialogOpen}
          onClose={() => {
            setImportDialogOpen(false);
            setImportTargetTask(null);
          }}
          taskId={importTargetTask.id}
          taskName={importTargetTask.name}
          projectId={currentProjectId}
          onImported={() => {
            if (currentProjectId) loadTasks(currentProjectId);
          }}
        />
      )}

      {casesTargetTask && (
        <TaskCasesDrawer
          open={casesDrawerOpen}
          onClose={() => {
            setCasesDrawerOpen(false);
            setCasesTargetTask(null);
          }}
          taskId={casesTargetTask.id}
          taskName={casesTargetTask.name}
          onImportClick={() => {
            setCasesDrawerOpen(false);
            setImportTargetTask(casesTargetTask);
            setImportDialogOpen(true);
          }}
        />
      )}

      {historyTargetTask && (
        <TaskHistoryDrawer
          open={historyDrawerOpen}
          onClose={() => {
            setHistoryDrawerOpen(false);
            setHistoryTargetTask(null);
          }}
          taskId={historyTargetTask.id}
          taskName={historyTargetTask.name}
          onOpenReport={(runId) => {
            setReportRunId(runId);
            setReportModalOpen(true);
          }}
        />
      )}

      <TaskReportModal
        open={reportModalOpen}
        onClose={() => {
          setReportModalOpen(false);
          setReportRunId(null);
        }}
        runId={reportRunId}
      />
    </div>
  );
}
