import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { Plus, Play, Trash2, RefreshCw, Layers, Clock, BarChart2 } from 'lucide-react';
import { useProjectStore } from '../../../../shared/store/projectStore';
import { useConfirmStore } from '../../../../shared/store/confirmStore';
import { useServerPerfStore, type PerfTaskItem } from '../../store/serverPerfStore';

export function PerfTaskList({ onOpenReport }: { onOpenReport: (runId: number) => void }) {
  const currentProjectId = useProjectStore((s) => s.currentProjectId);
  const { tasks, scripts, loading, loadTasks, loadScripts } = useServerPerfStore();
  const confirm = useConfirmStore((s) => s.confirm);
  const [createModalOpen, setCreateModalOpen] = useState(false);

  // 创建任务表单
  const [name, setName] = useState('');
  const [desc] = useState('');
  const [strategyType, setStrategyType] = useState<'duration' | 'loops'>('duration');
  const [duration, setDuration] = useState(60);
  const [loops, setLoops] = useState(1);
  const [concurrency, setConcurrency] = useState(10);
  const [rampUp, setRampUp] = useState(5);
  const [engineType, setEngineType] = useState<'builtin' | 'jmeter_cli'>('builtin');
  const [selectedScripts, setSelectedScripts] = useState<{ script_id: number; weight: number }[]>([]);

  useEffect(() => {
    if (currentProjectId !== null) {
      loadTasks(currentProjectId);
      loadScripts(currentProjectId);
    }
  }, [currentProjectId, loadTasks, loadScripts]);

  const handleRunTask = async (task: PerfTaskItem) => {
    try {
      const res = await fetch(`/api/modules/performance/server/tasks/${task.id}/execute`, {
        method: 'POST',
      });
      const ret = await res.json();
      if (!res.ok) throw new Error(ret.detail || '启动失败');
      toast.success(`压测任务「${task.name}」已开始运行`);
      if (currentProjectId !== null) loadTasks(currentProjectId);
      if (ret.run_id) {
        onOpenReport(ret.run_id);
      }
    } catch (err: any) {
      toast.error(err.message || '启动失败');
    }
  };

  const handleDelete = (task: PerfTaskItem) => {
    confirm({
      title: '确认删除压测任务',
      message: `确定要删除压测任务「${task.name}」吗？删除后相关编排配置将无法恢复。`,
      confirmText: '确认删除',
      variant: 'danger',
      onConfirm: async () => {
        try {
          const res = await fetch(`/api/modules/performance/server/tasks/${task.id}`, {
            method: 'DELETE',
          });
          if (!res.ok) throw new Error('删除失败');
          toast.success('任务已删除');
          if (currentProjectId !== null) loadTasks(currentProjectId);
        } catch (err: any) {
          toast.error(err.message || '删除失败');
        }
      },
    });
  };

  const handleCreateTask = async () => {
    if (!name.trim()) {
      toast.error('请输入任务名称');
      return;
    }
    if (selectedScripts.length === 0) {
      toast.error('请至少挑选一个压测脚本组合为任务');
      return;
    }
    try {
      const res = await fetch('/api/modules/performance/server/tasks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_id: currentProjectId,
          name,
          description: desc,
          strategy_type: strategyType,
          duration_seconds: duration,
          loop_count: loops,
          concurrency,
          ramp_up_seconds: rampUp,
          engine_type: engineType,
          script_items: selectedScripts,
        }),
      });
      const ret = await res.json();
      if (!res.ok) throw new Error(ret.detail || '创建失败');
      toast.success('性能测试任务创建成功');
      setCreateModalOpen(false);
      setName('');
      setSelectedScripts([]);
      if (currentProjectId !== null) loadTasks(currentProjectId);
    } catch (err: any) {
      toast.error(err.message || '创建任务失败');
    }
  };

  const toggleScriptSelection = (scriptId: number) => {
    if (selectedScripts.some((s) => s.script_id === scriptId)) {
      setSelectedScripts(selectedScripts.filter((s) => s.script_id !== scriptId));
    } else {
      setSelectedScripts([...selectedScripts, { script_id: scriptId, weight: 100 }]);
    }
  };

  if (currentProjectId === null) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>
        请先在顶部选择项目
      </div>
    );
  }

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
      {/* 工具栏 */}
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
        <button
          onClick={() => setCreateModalOpen(true)}
          style={{
            padding: '6px 14px',
            borderRadius: 6,
            border: 'none',
            background: 'var(--accent)',
            color: '#fff',
            fontSize: 13,
            fontWeight: 600,
            cursor: 'pointer',
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
          }}
        >
          <Plus size={14} /> 新建压测任务 (组合脚本)
        </button>

        <div style={{ flex: 1 }} />

        <button
          onClick={() => loadTasks(currentProjectId)}
          style={{
            padding: '6px 12px',
            borderRadius: 6,
            border: '1px solid var(--border)',
            background: 'var(--bg-base)',
            color: 'var(--text-primary)',
            fontSize: 12,
            cursor: 'pointer',
            display: 'inline-flex',
            alignItems: 'center',
            gap: 4,
          }}
        >
          <RefreshCw size={13} style={{ animation: loading ? 'spin 1s linear infinite' : 'none' }} />
          刷新列表
        </button>
      </div>

      {/* 列表内容 */}
      <div style={{ flex: 1, overflowY: 'auto', padding: 16 }}>
        {tasks.length === 0 ? (
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
            <Layers size={36} strokeWidth={1.2} style={{ opacity: 0.5 }} />
            <div>暂无性能测试任务，可将已生成的多个脚本组合为一个压测场景</div>
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
                  <th style={{ padding: '10px 14px', width: 140 }}>组合脚本</th>
                  <th style={{ padding: '10px 14px', width: 150 }}>施压策略</th>
                  <th style={{ padding: '10px 14px', width: 130 }}>执行引擎</th>
                  <th style={{ padding: '10px 14px', width: 110 }}>状态</th>
                  <th style={{ padding: '10px 16px', width: 180, textAlign: 'right' }}>操作</th>
                </tr>
              </thead>
              <tbody>
                {tasks.map((task) => (
                  <tr
                    key={task.id}
                    style={{
                      borderBottom: '1px solid var(--border)',
                      transition: 'background 0.15s ease',
                    }}
                  >
                    <td style={{ padding: '12px 16px' }}>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                        <strong style={{ color: 'var(--text-primary)', fontSize: 13 }}>{task.name}</strong>
                        {task.description && (
                          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{task.description}</span>
                        )}
                      </div>
                    </td>
                    <td style={{ padding: '12px 14px' }}>
                      <span
                        style={{
                          fontSize: 11,
                          padding: '2px 8px',
                          borderRadius: 12,
                          background: 'var(--bg-base)',
                          border: '1px solid var(--border)',
                        }}
                      >
                        {task.script_count} 个脚本
                      </span>
                    </td>
                    <td style={{ padding: '12px 14px', fontSize: 12 }}>
                      {task.strategy_type === 'duration' ? (
                        <div style={{ display: 'flex', alignItems: 'center', gap: 4, color: 'var(--accent)' }}>
                          <Clock size={13} /> 时长: {task.duration_seconds}s (并发 {task.concurrency})
                        </div>
                      ) : (
                        <div style={{ display: 'flex', alignItems: 'center', gap: 4, color: 'var(--text-secondary)' }}>
                          循环: {task.loop_count} 次 (并发 {task.concurrency})
                        </div>
                      )}
                    </td>
                    <td style={{ padding: '12px 14px', fontSize: 12 }}>
                      {task.engine_type === 'builtin' ? (
                        <span style={{ color: '#10b981', fontWeight: 500 }}>内置 Python 异步</span>
                      ) : (
                        <span style={{ color: '#f59e0b', fontWeight: 500 }}>本地 JMeter CLI</span>
                      )}
                    </td>
                    <td style={{ padding: '12px 14px' }}>
                      <span
                        style={{
                          fontSize: 11,
                          padding: '2px 8px',
                          borderRadius: 4,
                          fontWeight: 600,
                          background:
                            task.last_status === 'running'
                              ? 'rgba(59,130,246,0.1)'
                              : task.last_status === 'completed'
                              ? 'rgba(16,185,129,0.1)'
                              : 'var(--bg-base)',
                          color:
                            task.last_status === 'running'
                              ? 'var(--accent)'
                              : task.last_status === 'completed'
                              ? '#10b981'
                              : 'var(--text-muted)',
                        }}
                      >
                        {task.last_status}
                      </span>
                    </td>
                    <td style={{ padding: '12px 16px', textAlign: 'right' }}>
                      <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                        <button
                          onClick={() => handleRunTask(task)}
                          disabled={task.last_status === 'running'}
                          title="立即启动压测"
                          style={{
                            background: 'transparent',
                            border: 'none',
                            color: task.last_status === 'running' ? 'var(--text-muted)' : 'var(--accent)',
                            cursor: task.last_status === 'running' ? 'not-allowed' : 'pointer',
                            padding: 5,
                            borderRadius: 4,
                          }}
                        >
                          <Play size={15} />
                        </button>
                        {task.last_run_id && (
                          <button
                            onClick={() => onOpenReport(task.last_run_id!)}
                            title="查看最新执行报告"
                            style={{
                              background: 'transparent',
                              border: 'none',
                              color: 'var(--text-secondary)',
                              cursor: 'pointer',
                              padding: 5,
                              borderRadius: 4,
                            }}
                          >
                            <BarChart2 size={15} />
                          </button>
                        )}
                        <button
                          onClick={() => handleDelete(task)}
                          title="删除任务"
                          style={{
                            background: 'transparent',
                            border: 'none',
                            color: 'var(--text-muted)',
                            cursor: 'pointer',
                            padding: 5,
                            borderRadius: 4,
                          }}
                        >
                          <Trash2 size={15} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* 新建任务 Modal */}
      {createModalOpen && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 100,
            background: 'rgba(0,0,0,0.6)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: 24,
          }}
        >
          <div
            style={{
              width: '90%',
              maxWidth: 720,
              maxHeight: '90vh',
              background: 'var(--bg-card)',
              borderRadius: 8,
              border: '1px solid var(--border)',
              display: 'flex',
              flexDirection: 'column',
              overflow: 'hidden',
            }}
          >
            <div
              style={{
                padding: '14px 20px',
                borderBottom: '1px solid var(--border)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                background: 'var(--bg-base)',
              }}
            >
              <strong style={{ fontSize: 15 }}>新建性能测试任务</strong>
              <button
                onClick={() => setCreateModalOpen(false)}
                style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}
              >
                ✕
              </button>
            </div>
            <div style={{ flex: 1, overflowY: 'auto', padding: 20, display: 'flex', flexDirection: 'column', gap: 14 }}>
              <div>
                <label style={{ fontSize: 12, color: 'var(--text-secondary)' }}>任务名称 *</label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="例如：核心交易链路稳定性压测"
                  style={{
                    width: '100%',
                    height: 32,
                    marginTop: 4,
                    padding: '0 8px',
                    borderRadius: 4,
                    border: '1px solid var(--border)',
                    background: 'var(--bg-base)',
                    color: 'var(--text-primary)',
                  }}
                />
              </div>

              {/* 挑选脚本组合 */}
              <div>
                <label style={{ fontSize: 12, color: 'var(--text-secondary)', display: 'block', marginBottom: 6 }}>
                  挑选参与组合的脚本 (已选 {selectedScripts.length} 个) *
                </label>
                <div style={{ maxHeight: 150, overflowY: 'auto', border: '1px solid var(--border)', borderRadius: 6, padding: 8 }}>
                  {scripts.map((sc) => {
                    const isSelected = selectedScripts.some((s) => s.script_id === sc.id);
                    return (
                      <div
                        key={sc.id}
                        onClick={() => toggleScriptSelection(sc.id)}
                        style={{
                          padding: '6px 10px',
                          borderRadius: 4,
                          background: isSelected ? 'rgba(59,130,246,0.1)' : 'transparent',
                          color: isSelected ? 'var(--accent)' : 'var(--text-primary)',
                          cursor: 'pointer',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                          fontSize: 13,
                        }}
                      >
                        <span>{sc.name}</span>
                        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{sc.asset_ids?.length || 0} 个接口</span>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* 策略模式 */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <div>
                  <label style={{ fontSize: 12, color: 'var(--text-secondary)' }}>调度模式</label>
                  <select
                    value={strategyType}
                    onChange={(e: any) => setStrategyType(e.target.value)}
                    style={{
                      width: '100%',
                      height: 32,
                      marginTop: 4,
                      padding: '0 8px',
                      borderRadius: 4,
                      border: '1px solid var(--border)',
                      background: 'var(--bg-base)',
                      color: 'var(--text-primary)',
                    }}
                  >
                    <option value="duration">按持续运行时长 (Duration)</option>
                    <option value="loops">按每个线程循环次数 (Loops)</option>
                  </select>
                </div>

                <div>
                  <label style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                    {strategyType === 'duration' ? '持续时间 (秒)' : '循环次数 (轮)'}
                  </label>
                  <input
                    type="number"
                    min={1}
                    value={strategyType === 'duration' ? duration : loops}
                    onChange={(e) =>
                      strategyType === 'duration'
                        ? setDuration(Number(e.target.value))
                        : setLoops(Number(e.target.value))
                    }
                    style={{
                      width: '100%',
                      height: 32,
                      marginTop: 4,
                      padding: '0 8px',
                      borderRadius: 4,
                      border: '1px solid var(--border)',
                      background: 'var(--bg-base)',
                      color: 'var(--text-primary)',
                    }}
                  />
                </div>
              </div>

              {/* 并发与预热 */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
                <div>
                  <label style={{ fontSize: 12, color: 'var(--text-secondary)' }}>目标并发线程数</label>
                  <input
                    type="number"
                    min={1}
                    max={500}
                    value={concurrency}
                    onChange={(e) => setConcurrency(Number(e.target.value))}
                    style={{
                      width: '100%',
                      height: 32,
                      marginTop: 4,
                      padding: '0 8px',
                      borderRadius: 4,
                      border: '1px solid var(--border)',
                      background: 'var(--bg-base)',
                      color: 'var(--text-primary)',
                    }}
                  />
                </div>
                <div>
                  <label style={{ fontSize: 12, color: 'var(--text-secondary)' }}>加压预热时长 (秒)</label>
                  <input
                    type="number"
                    min={0}
                    value={rampUp}
                    onChange={(e) => setRampUp(Number(e.target.value))}
                    style={{
                      width: '100%',
                      height: 32,
                      marginTop: 4,
                      padding: '0 8px',
                      borderRadius: 4,
                      border: '1px solid var(--border)',
                      background: 'var(--bg-base)',
                      color: 'var(--text-primary)',
                    }}
                  />
                </div>
                <div>
                  <label style={{ fontSize: 12, color: 'var(--text-secondary)' }}>执行引擎</label>
                  <select
                    value={engineType}
                    onChange={(e: any) => setEngineType(e.target.value)}
                    style={{
                      width: '100%',
                      height: 32,
                      marginTop: 4,
                      padding: '0 8px',
                      borderRadius: 4,
                      border: '1px solid var(--border)',
                      background: 'var(--bg-base)',
                      color: 'var(--text-primary)',
                    }}
                  >
                    <option value="builtin">内置 Python 异步高并发 (推荐)</option>
                    <option value="jmeter_cli">本地 JMeter 原生 CLI</option>
                  </select>
                </div>
              </div>
            </div>

            <div
              style={{
                padding: '12px 20px',
                borderTop: '1px solid var(--border)',
                background: 'var(--bg-base)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'flex-end',
                gap: 10,
              }}
            >
              <button
                onClick={() => setCreateModalOpen(false)}
                style={{
                  padding: '6px 14px',
                  borderRadius: 6,
                  border: '1px solid var(--border)',
                  background: 'transparent',
                  color: 'var(--text-secondary)',
                  cursor: 'pointer',
                }}
              >
                取消
              </button>
              <button
                onClick={handleCreateTask}
                style={{
                  padding: '6px 16px',
                  borderRadius: 6,
                  border: 'none',
                  background: 'var(--accent)',
                  color: '#fff',
                  fontWeight: 600,
                  cursor: 'pointer',
                }}
              >
                确认创建
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
