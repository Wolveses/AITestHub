import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { Plus, Play, Trash2, RefreshCw, Layers, Clock, BarChart2, CheckSquare, Square, FileCode, Sliders, Cpu, Globe, Monitor, Search } from 'lucide-react';
import { useProjectStore } from '../../../../shared/store/projectStore';
import { useConfirmStore } from '../../../../shared/store/confirmStore';
import { useServerPerfStore, type PerfTaskItem } from '../../store/serverPerfStore';

export function PerfTaskList({ onOpenReport }: { onOpenReport: (runId: number) => void }) {
  const currentProjectId = useProjectStore((s) => s.currentProjectId);
  const { tasks, scripts, slaveNodes, loading, loadTasks, loadScripts, loadSlaveNodes } = useServerPerfStore();
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
  const [engineType, setEngineType] = useState<'builtin' | 'jmeter_cli'>('jmeter_cli');
  const [execMode, setExecMode] = useState<'local' | 'distributed'>('local');
  const [slaveHosts, setSlaveHosts] = useState('');
  const [selectedScripts, setSelectedScripts] = useState<{ script_id: number; weight: number }[]>([]);
  const [scriptSearch, setScriptSearch] = useState('');

  useEffect(() => {
    if (currentProjectId !== null) {
      loadTasks(currentProjectId);
      loadScripts(currentProjectId);
      loadSlaveNodes(currentProjectId);
    }
  }, [currentProjectId, loadTasks, loadScripts, loadSlaveNodes]);

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
          exec_mode: execMode,
          slave_hosts: execMode === 'distributed' ? slaveHosts : '',
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
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                        {task.engine_type === 'builtin' ? (
                          <span style={{ color: '#10b981', fontWeight: 500 }}>内置 Python 异步</span>
                        ) : (
                          <span style={{ color: '#f59e0b', fontWeight: 500 }}>本地 JMeter CLI</span>
                        )}
                        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                          {task.exec_mode === 'distributed'
                            ? `分布式 (${(task.slave_hosts || '').split(',').filter(Boolean).length} 从机)`
                            : '本机单机'}
                        </span>
                      </div>
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
            background: 'rgba(0,0,0,0.65)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: 20,
          }}
        >
          <div
            style={{
              width: '92%',
              maxWidth: 960,
              height: '84vh',
              maxHeight: 760,
              background: 'var(--bg-card)',
              borderRadius: 10,
              border: '1px solid var(--border)',
              display: 'flex',
              flexDirection: 'column',
              overflow: 'hidden',
              boxShadow: '0 20px 40px rgba(0,0,0,0.3)',
            }}
          >
            {/* 顶栏 */}
            <div
              style={{
                padding: '12px 20px',
                borderBottom: '1px solid var(--border)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                background: 'var(--bg-base)',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Layers size={17} color="var(--accent)" />
                <span style={{ fontSize: 15, fontWeight: 600, color: 'var(--text-primary)' }}>
                  新建性能测试任务
                </span>
                <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                  (组合多个脚本构成独立施压场景)
                </span>
              </div>
              <button
                onClick={() => setCreateModalOpen(false)}
                style={{
                  background: 'transparent',
                  border: 'none',
                  color: 'var(--text-muted)',
                  cursor: 'pointer',
                  padding: 4,
                  fontSize: 14,
                }}
              >
                ✕
              </button>
            </div>

            {/* 左右分栏主体内容 */}
            <div
              style={{
                flex: 1,
                display: 'grid',
                gridTemplateColumns: '1.2fr 1fr',
                overflow: 'hidden',
              }}
            >
              {/* 左栏：挑选参与组合的脚本 (重点区域，大幅提升可视范围与操作性) */}
              <div
                style={{
                  borderRight: '1px solid var(--border)',
                  display: 'flex',
                  flexDirection: 'column',
                  overflow: 'hidden',
                  background: 'var(--bg-base)',
                }}
              >
                {/* 脚本栏表头 */}
                <div
                  style={{
                    padding: '12px 16px',
                    borderBottom: '1px solid var(--border)',
                    background: 'var(--bg-card)',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 8,
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <FileCode size={14} color="var(--accent)" />
                      <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>
                        挑选压测脚本
                      </span>
                      <span
                        style={{
                          fontSize: 11,
                          padding: '1px 7px',
                          borderRadius: 10,
                          background: selectedScripts.length > 0 ? 'rgba(59,130,246,0.12)' : 'var(--bg-base)',
                          color: selectedScripts.length > 0 ? 'var(--accent)' : 'var(--text-muted)',
                          fontWeight: 500,
                        }}
                      >
                        已选 {selectedScripts.length} / {scripts.length}
                      </span>
                    </div>

                    {scripts.length > 0 && (
                      <div style={{ display: 'flex', gap: 8 }}>
                        <button
                          type="button"
                          onClick={() => {
                            if (selectedScripts.length === scripts.length) {
                              setSelectedScripts([]);
                            } else {
                              setSelectedScripts(scripts.map((s) => ({ script_id: s.id, weight: 100 })));
                            }
                          }}
                          style={{
                            background: 'none',
                            border: 'none',
                            color: 'var(--accent)',
                            fontSize: 11,
                            cursor: 'pointer',
                            fontWeight: 500,
                            padding: 0,
                          }}
                        >
                          {selectedScripts.length === scripts.length ? '取消全选' : '全选全部'}
                        </button>
                      </div>
                    )}
                  </div>

                  {/* 搜索框 */}
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 6,
                      background: 'var(--bg-base)',
                      border: '1px solid var(--border)',
                      borderRadius: 6,
                      padding: '0 8px',
                      height: 28,
                    }}
                  >
                    <Search size={13} style={{ color: 'var(--text-muted)' }} />
                    <input
                      type="text"
                      placeholder="搜索脚本名称或描述..."
                      value={scriptSearch}
                      onChange={(e) => setScriptSearch(e.target.value)}
                      style={{
                        flex: 1,
                        background: 'transparent',
                        border: 'none',
                        outline: 'none',
                        fontSize: 12,
                        color: 'var(--text-primary)',
                      }}
                    />
                    {scriptSearch && (
                      <button
                        onClick={() => setScriptSearch('')}
                        style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', padding: 0, fontSize: 11 }}
                      >
                        ✕
                      </button>
                    )}
                  </div>
                </div>

                {/* 脚本列表主体 */}
                <div style={{ flex: 1, overflowY: 'auto', padding: 10, display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {scripts.length === 0 ? (
                    <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)', fontSize: 12 }}>
                      暂无已保存的压测脚本，请先前往「JMeter 脚本管理」生成或编写脚本
                    </div>
                  ) : (
                    scripts
                      .filter((sc) => {
                        if (!scriptSearch.trim()) return true;
                        const kw = scriptSearch.toLowerCase();
                        return sc.name.toLowerCase().includes(kw) || (sc.description || '').toLowerCase().includes(kw);
                      })
                      .map((sc) => {
                        const isSelected = selectedScripts.some((s) => s.script_id === sc.id);
                        return (
                          <div
                            key={sc.id}
                            onClick={() => toggleScriptSelection(sc.id)}
                            style={{
                              padding: '10px 12px',
                              borderRadius: 6,
                              border: `1px solid ${isSelected ? 'var(--accent)' : 'var(--border)'}`,
                              background: isSelected ? 'rgba(59, 130, 246, 0.08)' : 'var(--bg-card)',
                              cursor: 'pointer',
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'space-between',
                              gap: 10,
                              transition: 'all 0.15s ease',
                            }}
                          >
                            <div style={{ display: 'flex', alignItems: 'flex-start', gap: 9, flex: 1, minWidth: 0 }}>
                              <div style={{ color: isSelected ? 'var(--accent)' : 'var(--text-muted)', marginTop: 2, display: 'flex' }}>
                                {isSelected ? <CheckSquare size={16} /> : <Square size={16} />}
                              </div>
                              <div style={{ flex: 1, minWidth: 0 }}>
                                <div
                                  style={{
                                    fontSize: 13,
                                    fontWeight: isSelected ? 600 : 500,
                                    color: isSelected ? 'var(--accent)' : 'var(--text-primary)',
                                    overflow: 'hidden',
                                    textOverflow: 'ellipsis',
                                    whiteSpace: 'nowrap',
                                  }}
                                >
                                  {sc.name}
                                </div>
                                <div
                                  style={{
                                    fontSize: 11,
                                    color: 'var(--text-muted)',
                                    marginTop: 3,
                                    overflow: 'hidden',
                                    textOverflow: 'ellipsis',
                                    whiteSpace: 'nowrap',
                                  }}
                                >
                                  {sc.description || '无附加描述'}
                                </div>
                              </div>
                            </div>

                            <span
                              style={{
                                fontSize: 11,
                                color: isSelected ? 'var(--accent)' : 'var(--text-secondary)',
                                background: isSelected ? 'rgba(59, 130, 246, 0.12)' : 'var(--bg-base)',
                                border: '1px solid var(--border)',
                                padding: '2px 8px',
                                borderRadius: 4,
                                flexShrink: 0,
                              }}
                            >
                              {(sc.asset_ids && sc.asset_ids.length > 0)
                                ? sc.asset_ids.length
                                : (Array.isArray(sc.config?.steps) ? sc.config.steps.length : (Array.isArray(sc.config?.samplers) ? sc.config.samplers.length : 0))} 个接口
                            </span>
                          </div>
                        );
                      })
                  )}
                </div>
              </div>

              {/* 右栏：紧凑分层的参数配置 */}
              <div
                style={{
                  overflowY: 'auto',
                  padding: '16px 20px',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 14,
                  background: 'var(--bg-card)',
                }}
              >
                {/* 1. 任务基本信息 */}
                <div>
                  <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 6, display: 'flex', alignItems: 'center', gap: 5 }}>
                    <Sliders size={13} color="var(--accent)" />
                    任务基本信息
                  </div>
                  <div>
                    <label style={{ fontSize: 11, color: 'var(--text-secondary)', display: 'block', marginBottom: 3 }}>
                      任务名称 <span style={{ color: '#ef4444' }}>*</span>
                    </label>
                    <input
                      type="text"
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      placeholder="例如：核心交易链路稳定性压测"
                      style={{
                        width: '100%',
                        height: 30,
                        padding: '0 8px',
                        borderRadius: 4,
                        border: '1px solid var(--border)',
                        background: 'var(--bg-base)',
                        color: 'var(--text-primary)',
                        fontSize: 12,
                      }}
                    />
                  </div>
                </div>

                {/* 2. 调度策略与压力指标 */}
                <div
                  style={{
                    padding: 12,
                    background: 'var(--bg-base)',
                    borderRadius: 6,
                    border: '1px solid var(--border)',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 10,
                  }}
                >
                  <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: 5 }}>
                    <Clock size={13} color="var(--accent)" />
                    施压策略与并发控制
                  </div>

                  <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: 8 }}>
                    <div>
                      <label style={{ fontSize: 11, color: 'var(--text-secondary)', display: 'block', marginBottom: 3 }}>
                        调度模式
                      </label>
                      <select
                        value={strategyType}
                        onChange={(e: any) => setStrategyType(e.target.value)}
                        style={{
                          width: '100%',
                          height: 28,
                          padding: '0 6px',
                          borderRadius: 4,
                          border: '1px solid var(--border)',
                          background: 'var(--bg-card)',
                          color: 'var(--text-primary)',
                          fontSize: 12,
                        }}
                      >
                        <option value="duration">持续时长 (Duration)</option>
                        <option value="loops">固定循环 (Loops)</option>
                      </select>
                    </div>

                    <div>
                      <label style={{ fontSize: 11, color: 'var(--text-secondary)', display: 'block', marginBottom: 3 }}>
                        {strategyType === 'duration' ? '持续时间 (秒)' : '循环轮数 (次)'}
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
                          height: 28,
                          padding: '0 6px',
                          borderRadius: 4,
                          border: '1px solid var(--border)',
                          background: 'var(--bg-card)',
                          color: 'var(--text-primary)',
                          fontSize: 12,
                        }}
                      />
                    </div>
                  </div>

                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                    <div>
                      <label style={{ fontSize: 11, color: 'var(--text-secondary)', display: 'block', marginBottom: 3 }}>
                        目标并发线程数
                      </label>
                      <input
                        type="number"
                        min={1}
                        max={1000}
                        value={concurrency}
                        onChange={(e) => setConcurrency(Number(e.target.value))}
                        style={{
                          width: '100%',
                          height: 28,
                          padding: '0 6px',
                          borderRadius: 4,
                          border: '1px solid var(--border)',
                          background: 'var(--bg-card)',
                          color: 'var(--text-primary)',
                          fontSize: 12,
                        }}
                      />
                    </div>

                    <div>
                      <label style={{ fontSize: 11, color: 'var(--text-secondary)', display: 'block', marginBottom: 3 }}>
                        预热时长 (秒)
                      </label>
                      <input
                        type="number"
                        min={0}
                        value={rampUp}
                        onChange={(e) => setRampUp(Number(e.target.value))}
                        style={{
                          width: '100%',
                          height: 28,
                          padding: '0 6px',
                          borderRadius: 4,
                          border: '1px solid var(--border)',
                          background: 'var(--bg-card)',
                          color: 'var(--text-primary)',
                          fontSize: 12,
                        }}
                      />
                    </div>
                  </div>
                </div>

                {/* 3. 执行引擎与分布式模式 */}
                <div
                  style={{
                    padding: 12,
                    background: 'var(--bg-base)',
                    borderRadius: 6,
                    border: '1px solid var(--border)',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 10,
                  }}
                >
                  <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: 5 }}>
                    <Cpu size={13} color="var(--accent)" />
                    引擎与分布式架构
                  </div>

                  <div>
                    <label style={{ fontSize: 11, color: 'var(--text-secondary)', display: 'block', marginBottom: 3 }}>
                      压测引擎
                    </label>
                    <select
                      value={engineType}
                      onChange={(e: any) => setEngineType(e.target.value)}
                      style={{
                        width: '100%',
                        height: 28,
                        padding: '0 6px',
                        borderRadius: 4,
                        border: '1px solid var(--border)',
                        background: 'var(--bg-card)',
                        color: 'var(--text-primary)',
                        fontSize: 12,
                      }}
                    >
                      <option value="jmeter_cli">本地 JMeter 原生 CLI (推荐/默认)</option>
                      <option value="builtin">内置 Python 异步高并发 (备用)</option>
                    </select>
                  </div>

                  <div>
                    <label style={{ fontSize: 11, color: 'var(--text-secondary)', display: 'block', marginBottom: 4 }}>
                      调度架构
                    </label>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                      <div
                        onClick={() => setExecMode('local')}
                        style={{
                          border: `1px solid ${execMode === 'local' ? 'var(--accent)' : 'var(--border)'}`,
                          background: execMode === 'local' ? 'rgba(59,130,246,0.08)' : 'var(--bg-card)',
                          borderRadius: 5,
                          padding: '6px 8px',
                          cursor: 'pointer',
                          display: 'flex',
                          alignItems: 'center',
                          gap: 6,
                        }}
                      >
                        <Monitor size={14} color={execMode === 'local' ? 'var(--accent)' : 'var(--text-muted)'} />
                        <div>
                          <div style={{ fontSize: 11, fontWeight: 600, color: execMode === 'local' ? 'var(--accent)' : 'var(--text-primary)' }}>
                            本机单机执行
                          </div>
                        </div>
                      </div>

                      <div
                        onClick={() => setExecMode('distributed')}
                        style={{
                          border: `1px solid ${execMode === 'distributed' ? 'var(--accent)' : 'var(--border)'}`,
                          background: execMode === 'distributed' ? 'rgba(59,130,246,0.08)' : 'var(--bg-card)',
                          borderRadius: 5,
                          padding: '6px 8px',
                          cursor: 'pointer',
                          display: 'flex',
                          alignItems: 'center',
                          gap: 6,
                        }}
                      >
                        <Globe size={14} color={execMode === 'distributed' ? 'var(--accent)' : 'var(--text-muted)'} />
                        <div>
                          <div style={{ fontSize: 11, fontWeight: 600, color: execMode === 'distributed' ? 'var(--accent)' : 'var(--text-primary)' }}>
                            Master 分布式从机
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* 分布式从机勾选区 */}
                  {execMode === 'distributed' && (
                    <div style={{ marginTop: 4, display: 'flex', flexDirection: 'column', gap: 6 }}>
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                        <span style={{ fontSize: 11, color: 'var(--text-secondary)' }}>
                          从机节点 (已选 {slaveHosts.split(',').map((s) => s.trim()).filter(Boolean).length} 台)
                        </span>
                        {slaveNodes.length > 0 && (
                          <div style={{ display: 'flex', gap: 8 }}>
                            <button
                              type="button"
                              onClick={() => {
                                const onlineHosts = slaveNodes.filter((n) => n.status === 'online').map((n) => `${n.host}:${n.port}`);
                                if (onlineHosts.length === 0) {
                                  toast.warning('暂无在线从机节点');
                                  return;
                                }
                                setSlaveHosts(onlineHosts.join(', '));
                              }}
                              style={{ background: 'none', border: 'none', color: 'var(--accent)', fontSize: 11, cursor: 'pointer', padding: 0 }}
                            >
                              全选在线 ({slaveNodes.filter((n) => n.status === 'online').length})
                            </button>
                            <button
                              type="button"
                              onClick={() => setSlaveHosts('')}
                              style={{ background: 'none', border: 'none', color: 'var(--text-muted)', fontSize: 11, cursor: 'pointer', padding: 0 }}
                            >
                              清空
                            </button>
                          </div>
                        )}
                      </div>

                      {slaveNodes.length === 0 ? (
                        <div style={{ padding: 12, borderRadius: 4, border: '1px dashed var(--border)', background: 'var(--bg-card)', textAlign: 'center', color: 'var(--text-muted)', fontSize: 11 }}>
                          从机池为空，请先在「分布式从机节点」Tab 录入从机
                        </div>
                      ) : (
                        <div style={{ maxHeight: 110, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 4, padding: 6, background: 'var(--bg-card)', borderRadius: 4, border: '1px solid var(--border)' }}>
                          {slaveNodes.map((n) => {
                            const hostStr = `${n.host}:${n.port}`;
                            const isSelected = slaveHosts.split(',').map((s) => s.trim()).includes(hostStr);
                            return (
                              <div
                                key={n.id}
                                onClick={() => {
                                  const currentList = slaveHosts.split(',').map((s) => s.trim()).filter(Boolean);
                                  if (isSelected) {
                                    setSlaveHosts(currentList.filter((s) => s !== hostStr).join(', '));
                                  } else {
                                    setSlaveHosts([...currentList, hostStr].join(', '));
                                  }
                                }}
                                style={{
                                  padding: '4px 8px',
                                  borderRadius: 4,
                                  border: `1px solid ${isSelected ? 'var(--accent)' : 'var(--border)'}`,
                                  background: isSelected ? 'rgba(59,130,246,0.08)' : 'var(--bg-base)',
                                  cursor: 'pointer',
                                  display: 'flex',
                                  alignItems: 'center',
                                  justifyContent: 'space-between',
                                }}
                              >
                                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                                  <span
                                    style={{
                                      width: 6,
                                      height: 6,
                                      borderRadius: '50%',
                                      background: n.status === 'online' ? '#10b981' : '#ef4444',
                                    }}
                                  />
                                  <span style={{ fontSize: 11, fontWeight: 500, color: 'var(--text-primary)' }}>{n.name}</span>
                                  <span style={{ fontSize: 10, fontFamily: 'monospace', color: 'var(--text-muted)' }}>{hostStr}</span>
                                </div>
                                <input type="checkbox" checked={isSelected} onChange={() => {}} style={{ accentColor: 'var(--accent)' }} />
                              </div>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* 底栏按钮 */}
            <div
              style={{
                padding: '10px 20px',
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
                  fontSize: 12,
                  cursor: 'pointer',
                }}
              >
                取消
              </button>
              <button
                onClick={handleCreateTask}
                style={{
                  padding: '6px 18px',
                  borderRadius: 6,
                  border: 'none',
                  background: 'var(--accent)',
                  color: '#fff',
                  fontSize: 12,
                  fontWeight: 600,
                  cursor: 'pointer',
                }}
              >
                确认创建任务
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
