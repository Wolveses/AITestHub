import { useEffect, useState, useMemo } from 'react';
import { toast } from 'sonner';
import {
  Plus,
  Play,
  Trash2,
  RefreshCw,
  Layers,
  BarChart2,
  CheckSquare,
  Square,
  FileCode,
  Search,
  Tag,
  X,
  Eye,
  Edit3,
  Terminal,
  Copy,
  Check,
  History,
  FileSpreadsheet,
} from 'lucide-react';
import { useProjectStore } from '../../../../shared/store/projectStore';
import { useConfirmStore } from '../../../../shared/store/confirmStore';
import { useServerPerfStore, type PerfTaskItem } from '../../store/serverPerfStore';
import { PerfTaskDetailModal } from './PerfTaskDetailModal';
import { PerfTaskEditModal } from './PerfTaskEditModal';
import { PerfTaskRunModal } from './PerfTaskRunModal';
import { JtlReportModal } from './JtlReportModal';
import { buildJMeterCommand } from './commandPreview';

export function PerfTaskList() {
  const currentProjectId = useProjectStore((s) => s.currentProjectId);
  const { tasks, scripts, slaveNodes, loading, loadTasks, loadScripts, loadSlaveNodes } = useServerPerfStore();
  const confirm = useConfirmStore((s) => s.confirm);
  const [createModalOpen, setCreateModalOpen] = useState(false);

  // 顶层视图切换：压测任务编排 vs 执行记录与历史
  const [activeTab, setActiveTab] = useState<'tasks' | 'runs'>('tasks');

  // 任务详情与编辑弹窗状态
  const [detailTaskId, setDetailTaskId] = useState<number | null>(null);
  const [editTaskId, setEditTaskId] = useState<number | null>(null);

  // 实时运行控制台状态
  const [runTaskTarget, setRunTaskTarget] = useState<PerfTaskItem | null>(null);
  const [viewRunId, setViewRunId] = useState<number | null>(null);
  const [activeRunTaskName, setActiveRunTaskName] = useState<string | undefined>(undefined);
  const [isRunModalOpen, setIsRunModalOpen] = useState(false);

  // JTL 执行报告弹窗状态
  const [reportRunId, setReportRunId] = useState<number | null>(null);
  const [reportScriptName, setReportScriptName] = useState<string | undefined>(undefined);
  const [isReportModalOpen, setIsReportModalOpen] = useState(false);

  // 全量执行记录管理
  const [runs, setRuns] = useState<any[]>([]);
  const [loadingRuns, setLoadingRuns] = useState(false);
  const [runSearch, setRunSearch] = useState('');
  const [runFilterStatus, setRunFilterStatus] = useState<string>('all');
  const [runFilterTaskId, setRunFilterTaskId] = useState<number | 'all'>('all');

  // 创建任务表单
  const [name, setName] = useState('');
  const [desc, setDesc] = useState('');
  const [engineType, setEngineType] = useState<'builtin' | 'jmeter_cli'>('jmeter_cli');
  const [execMode, setExecMode] = useState<'local' | 'distributed'>('local');
  const [slaveHosts, setSlaveHosts] = useState('');
  const [selectedScripts, setSelectedScripts] = useState<{ script_id: number; weight: number }[]>([]);
  const [scriptSearch, setScriptSearch] = useState('');

  // 动态属性参数管理 (由后端接口 /scripts/batch/properties 统一返回)
  const [customProperties, setCustomProperties] = useState<Record<string, string>>({});
  const [extractedProps, setExtractedProps] = useState<{ name: string; default_value: string }[]>([]);
  const [deletedPropKeys, setDeletedPropKeys] = useState<string[]>([]);
  const [loadingProps, setLoadingProps] = useState(false);
  const [newPropKey, setNewPropKey] = useState('');
  const [newPropVal, setNewPropVal] = useState('');
  const [createCopied, setCreateCopied] = useState(false);

  const handleDeleteProp = (propName: string) => {
    // 1. 从 customProperties 中移除
    setCustomProperties((prev) => {
      const next = { ...prev };
      delete next[propName];
      return next;
    });
    // 2. 标记为主动删除，确保在当前任务中彻底移除该参数
    setDeletedPropKeys((prev) => (prev.includes(propName) ? prev : [...prev, propName]));
  };

  const allCreatePropertyKeys = Array.from(
    new Set([
      ...extractedProps.map((p) => p.name).filter((k) => !deletedPropKeys.includes(k)),
      ...Object.keys(customProperties),
    ])
  );

  const createPrimaryScript = scripts.find((s) => s.id === selectedScripts[0]?.script_id);
  const createCommandPreview = buildJMeterCommand({
    engineType,
    execMode,
    slaveHosts,
    scriptName: createPrimaryScript?.name || 'plan',
    customProperties,
  });

  const loadRuns = async () => {
    if (currentProjectId === null) return;
    setLoadingRuns(true);
    try {
      const res = await fetch(`/api/modules/performance/server/runs?project_id=${currentProjectId}&page_size=100`);
      if (res.ok) {
        const data = await res.json();
        setRuns(data.items || []);
      }
    } catch (err) {
      console.error('加载执行记录失败', err);
    } finally {
      setLoadingRuns(false);
    }
  };

  const handleDeleteRun = (runId: number) => {
    confirm({
      title: '确认删除执行记录',
      message: `确定要删除执行记录 #RUN-${runId} 吗？删除后相关 JTL 采样数据与指标将无法恢复。`,
      confirmText: '确认删除',
      variant: 'danger',
      onConfirm: async () => {
        try {
          const res = await fetch(`/api/modules/performance/server/runs/${runId}`, {
            method: 'DELETE',
          });
          if (res.ok) {
            toast.success('执行记录已删除');
            loadRuns();
            if (currentProjectId !== null) loadTasks(currentProjectId);
          } else {
            const data = await res.json();
            throw new Error(data.detail || '删除失败');
          }
        } catch (err: any) {
          toast.error(err.message || '删除记录失败');
        }
      },
    });
  };

  const filteredRuns = useMemo(() => {
    return runs.filter((r) => {
      if (runFilterTaskId !== 'all' && r.task_id !== runFilterTaskId) {
        return false;
      }
      if (runFilterStatus !== 'all' && r.status !== runFilterStatus) {
        return false;
      }
      if (runSearch.trim()) {
        const q = runSearch.toLowerCase().trim();
        const matchId = String(r.id).includes(q);
        const matchTask = (r.task_name || '').toLowerCase().includes(q);
        const matchScript = (r.script_name || '').toLowerCase().includes(q);
        return matchId || matchTask || matchScript;
      }
      return true;
    });
  }, [runs, runFilterTaskId, runFilterStatus, runSearch]);

  useEffect(() => {
    if (selectedScripts.length === 0) {
      // 当没有选中任何脚本时，仅保留用户手动添加的非脚本参数
      setExtractedProps([]);
      setCustomProperties((prev) => {
        const next: Record<string, string> = {};
        // 之前已被标记为 extracted 的属性全部清理
        Object.entries(prev).forEach(([k, v]) => {
          if (!extractedProps.some((p) => p.name === k)) {
            next[k] = v;
          }
        });
        return next;
      });
      return;
    }
    const ids = selectedScripts.map((s) => s.script_id).join(',');
    setLoadingProps(true);
    fetch(`/api/modules/performance/server/scripts/batch/properties?script_ids=${ids}`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data) => {
        const newExtracted: { name: string; default_value: string }[] = data.properties || [];
        const newExtractedNames = new Set(newExtracted.map((p) => p.name));

        setExtractedProps(newExtracted);
        setCustomProperties((prev) => {
          const next: Record<string, string> = {};
          // 1. 保留原本属于用户手动添加的非脚本探测参数
          Object.entries(prev).forEach(([k, v]) => {
            const wasExtracted = extractedProps.some((p) => p.name === k);
            if (!wasExtracted) {
              // 纯手动参数保留
              next[k] = v;
            } else if (newExtractedNames.has(k)) {
              // 如果新脚本集合中依然包含该参数，保留用户的当前输入值
              next[k] = v;
            }
            // 否则（属于取消勾选的脚本专属参数）自动剔除！
          });

          // 2. 将新检测到的脚本参数填入（若未填过则使用其 default_value）
          newExtracted.forEach((p) => {
            if (next[p.name] === undefined) {
              next[p.name] = p.default_value ?? '';
            }
          });
          return next;
        });
      })
      .catch((err) => {
        console.error('从后端接口获取脚本动态参数失败', err);
      })
      .finally(() => {
        setLoadingProps(false);
      });
  }, [selectedScripts]);

  useEffect(() => {
    if (currentProjectId !== null) {
      loadTasks(currentProjectId);
      loadScripts(currentProjectId);
      loadSlaveNodes(currentProjectId);
      loadRuns();
    }
  }, [currentProjectId, loadTasks, loadScripts, loadSlaveNodes]);

  useEffect(() => {
    if (createModalOpen) {
      loadSlaveNodes(currentProjectId ?? undefined);
    }
  }, [createModalOpen, currentProjectId, loadSlaveNodes]);

  const handleRunTask = (task: PerfTaskItem) => {
    setRunTaskTarget(task);
    setViewRunId(null);
    setActiveRunTaskName(task.name);
    setIsRunModalOpen(true);
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
    // 确保所有脚本动态参数均完整传入，已主动删除的参数不传入
    const finalProps: Record<string, string> = { ...customProperties };
    extractedProps.forEach((p) => {
      if (!deletedPropKeys.includes(p.name) && finalProps[p.name] === undefined) {
        finalProps[p.name] = p.default_value ?? '';
      }
    });

    try {
      const res = await fetch('/api/modules/performance/server/tasks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_id: currentProjectId,
          name,
          description: desc,
          engine_type: engineType,
          exec_mode: execMode,
          slave_hosts: execMode === 'distributed' ? slaveHosts : '',
          custom_properties: finalProps,
          script_items: selectedScripts,
        }),
      });
      const ret = await res.json();
      if (!res.ok) throw new Error(ret.detail || '创建失败');
      toast.success('性能测试任务创建成功');
      setCreateModalOpen(false);
      setName('');
      setSelectedScripts([]);
      setCustomProperties({});
      setExtractedProps([]);
      setDeletedPropKeys([]);
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
      {/* 顶部二级 Tab 切换栏 */}
      <div
        style={{
          padding: '0 16px',
          background: 'var(--bg-card)',
          borderBottom: '1px solid var(--border)',
          display: 'flex',
          gap: 20,
          flexShrink: 0,
        }}
      >
        <button
          onClick={() => setActiveTab('tasks')}
          style={{
            padding: '10px 4px',
            border: 'none',
            background: 'transparent',
            borderBottom: activeTab === 'tasks' ? '2px solid var(--accent)' : '2px solid transparent',
            color: activeTab === 'tasks' ? 'var(--accent)' : 'var(--text-secondary)',
            fontWeight: activeTab === 'tasks' ? 600 : 400,
            fontSize: 13,
            cursor: 'pointer',
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
          }}
        >
          <Layers size={14} /> 压测任务编排 ({tasks.length})
        </button>

        <button
          onClick={() => setActiveTab('runs')}
          style={{
            padding: '10px 4px',
            border: 'none',
            background: 'transparent',
            borderBottom: activeTab === 'runs' ? '2px solid var(--accent)' : '2px solid transparent',
            color: activeTab === 'runs' ? 'var(--accent)' : 'var(--text-secondary)',
            fontWeight: activeTab === 'runs' ? 600 : 400,
            fontSize: 13,
            cursor: 'pointer',
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
          }}
        >
          <History size={14} /> 执行记录与历史 ({runs.length})
        </button>
      </div>

      {activeTab === 'tasks' ? (
        <>
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
                      <th style={{ padding: '10px 14px', width: 130 }}>组合脚本</th>
                      <th style={{ padding: '10px 14px', width: 150 }}>执行引擎</th>
                      <th style={{ padding: '10px 14px', width: 110 }}>状态</th>
                      <th style={{ padding: '10px 16px', width: 220, textAlign: 'right' }}>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {tasks.map((task) => {
                      const statusMap: Record<string, { label: string; bg: string; color: string }> = {
                        running: { label: '运行中', bg: 'rgba(59,130,246,0.12)', color: '#3b82f6' },
                        completed: { label: '已完成', bg: 'rgba(16,185,129,0.12)', color: '#10b981' },
                        failed: { label: '执行失败', bg: 'rgba(239,68,68,0.12)', color: '#ef4444' },
                        stopped: { label: '已停止', bg: 'rgba(245,158,11,0.12)', color: '#f59e0b' },
                        idle: { label: '空闲', bg: 'var(--bg-base)', color: 'var(--text-muted)' },
                      };
                      const statusInfo = statusMap[task.last_status || 'idle'] || statusMap.idle;

                      return (
                      <tr
                        key={task.id}
                        style={{
                          borderBottom: '1px solid var(--border)',
                          transition: 'background 0.15s ease',
                        }}
                      >
                        <td style={{ padding: '12px 16px' }}>
                          <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                            <strong
                              onClick={() => setDetailTaskId(task.id)}
                              style={{
                                color: 'var(--text-primary)',
                                fontSize: 13,
                                cursor: 'pointer',
                                transition: 'color 0.15s ease',
                              }}
                              onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--accent)')}
                              onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--text-primary)')}
                              title="点击查看任务详情"
                            >
                              {task.name}
                            </strong>
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
                              background: statusInfo.bg,
                              color: statusInfo.color,
                            }}
                          >
                            {statusInfo.label}
                          </span>
                        </td>
                        <td style={{ padding: '12px 16px', textAlign: 'right' }}>
                          <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                            <button
                              onClick={() => setDetailTaskId(task.id)}
                              title="查看任务详情"
                              style={{
                                background: 'transparent',
                                border: 'none',
                                color: 'var(--text-secondary)',
                                cursor: 'pointer',
                                padding: 5,
                                borderRadius: 4,
                              }}
                            >
                              <Eye size={15} />
                            </button>
                            <button
                              onClick={() => setEditTaskId(task.id)}
                              title="编辑任务"
                              style={{
                                background: 'transparent',
                                border: 'none',
                                color: 'var(--text-secondary)',
                                cursor: 'pointer',
                                padding: 5,
                                borderRadius: 4,
                              }}
                            >
                              <Edit3 size={15} />
                            </button>
                            <button
                              onClick={() => handleRunTask(task)}
                              disabled={task.last_status === 'running'}
                              title="立即启动压测"
                              style={{
                                background: 'transparent',
                                border: 'none',
                                color: task.last_status === 'running' ? 'var(--text-muted)' : '#10b981',
                                cursor: task.last_status === 'running' ? 'not-allowed' : 'pointer',
                                padding: 5,
                                borderRadius: 4,
                              }}
                            >
                              <Play size={15} />
                            </button>
                            <button
                              onClick={() => {
                                setRunFilterTaskId(task.id);
                                setActiveTab('runs');
                              }}
                              title="查看该任务的执行历史"
                              style={{
                                background: 'transparent',
                                border: 'none',
                                color: 'var(--text-secondary)',
                                cursor: 'pointer',
                                padding: 5,
                                borderRadius: 4,
                              }}
                            >
                              <History size={15} />
                            </button>
                            {task.last_run_id && (
                              <button
                                onClick={() => {
                                  setReportRunId(task.last_run_id!);
                                  setReportScriptName(task.name);
                                  setIsReportModalOpen(true);
                                }}
                                title="查看最新执行报告"
                                style={{
                                  background: 'transparent',
                                  border: 'none',
                                  color: 'var(--accent)',
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
                    );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      ) : (
        <>
          {/* 执行记录工具栏 */}
          <div
            style={{
              padding: '10px 16px',
              borderBottom: '1px solid var(--border)',
              background: 'var(--bg-card)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 12,
              flexShrink: 0,
              flexWrap: 'wrap',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
              {/* 按任务筛选 */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>任务筛选:</span>
                <select
                  value={runFilterTaskId}
                  onChange={(e) => setRunFilterTaskId(e.target.value === 'all' ? 'all' : Number(e.target.value))}
                  style={{
                    padding: '5px 10px',
                    borderRadius: 6,
                    border: '1px solid var(--border)',
                    background: 'var(--bg-base)',
                    color: 'var(--text-primary)',
                    fontSize: 12,
                    cursor: 'pointer',
                  }}
                >
                  <option value="all">全部任务 ({runs.length})</option>
                  {tasks.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.name}
                    </option>
                  ))}
                </select>
              </div>

              {/* 按状态筛选 */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>状态:</span>
                <select
                  value={runFilterStatus}
                  onChange={(e) => setRunFilterStatus(e.target.value)}
                  style={{
                    padding: '5px 10px',
                    borderRadius: 6,
                    border: '1px solid var(--border)',
                    background: 'var(--bg-base)',
                    color: 'var(--text-primary)',
                    fontSize: 12,
                    cursor: 'pointer',
                  }}
                >
                  <option value="all">全部状态</option>
                  <option value="completed">已完成</option>
                  <option value="running">运行中</option>
                  <option value="stopped">已停止</option>
                  <option value="failed">执行失败</option>
                </select>
              </div>

              {/* 关键词搜索 */}
              <div style={{ position: 'relative', width: 220 }}>
                <Search size={13} style={{ position: 'absolute', left: 8, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
                <input
                  type="text"
                  placeholder="搜索执行 ID / 任务名..."
                  value={runSearch}
                  onChange={(e) => setRunSearch(e.target.value)}
                  style={{
                    width: '100%',
                    padding: '5px 10px 5px 28px',
                    borderRadius: 6,
                    border: '1px solid var(--border)',
                    background: 'var(--bg-base)',
                    color: 'var(--text-primary)',
                    fontSize: 12,
                    boxSizing: 'border-box',
                  }}
                />
              </div>

              {(runFilterTaskId !== 'all' || runFilterStatus !== 'all' || runSearch) && (
                <button
                  onClick={() => {
                    setRunFilterTaskId('all');
                    setRunFilterStatus('all');
                    setRunSearch('');
                  }}
                  style={{
                    padding: '4px 8px',
                    borderRadius: 4,
                    border: '1px solid var(--border)',
                    background: 'transparent',
                    color: 'var(--text-muted)',
                    fontSize: 11,
                    cursor: 'pointer',
                  }}
                >
                  重置筛选
                </button>
              )}
            </div>

            <button
              onClick={loadRuns}
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
              <RefreshCw size={13} style={{ animation: loadingRuns ? 'spin 1s linear infinite' : 'none' }} />
              刷新记录
            </button>
          </div>

          {/* 执行记录列表 */}
          <div style={{ flex: 1, overflowY: 'auto', padding: 16 }}>
            {filteredRuns.length === 0 ? (
              <div
                style={{
                  border: '1px dashed var(--border)',
                  borderRadius: 8,
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
                <FileSpreadsheet size={40} strokeWidth={1.2} style={{ opacity: 0.5 }} />
                <div>
                  {runs.length === 0 ? '暂无压测执行记录，请在「压测任务编排」中启动任务' : '没有符合筛选条件的执行记录'}
                </div>
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
                <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: 12 }}>
                  <thead>
                    <tr
                      style={{
                        background: 'var(--bg-base)',
                        borderBottom: '1px solid var(--border)',
                        color: 'var(--text-muted)',
                        fontSize: 12,
                      }}
                    >
                      <th style={{ padding: '10px 14px', width: 90 }}>执行 ID</th>
                      <th style={{ padding: '10px 14px' }}>所属任务 / 脚本</th>
                      <th style={{ padding: '10px 12px', width: 90 }}>状态</th>
                      <th style={{ padding: '10px 12px', width: 100 }}>引擎</th>
                      <th style={{ padding: '10px 12px', width: 70 }}>并发</th>
                      <th style={{ padding: '10px 12px', width: 80 }}>样本数</th>
                      <th style={{ padding: '10px 12px', width: 80 }}>TPS</th>
                      <th style={{ padding: '10px 12px', width: 80 }}>平均响应</th>
                      <th style={{ padding: '10px 12px', width: 80 }}>P90</th>
                      <th style={{ padding: '10px 12px', width: 80 }}>错误率</th>
                      <th style={{ padding: '10px 14px', width: 140 }}>执行时间</th>
                      <th style={{ padding: '10px 16px', width: 150, textAlign: 'right' }}>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredRuns.map((run: any) => {
                      const isCompleted = run.status === 'completed';
                      const isRunning = run.status === 'running';
                      const isStopped = run.status === 'stopped';

                      return (
                        <tr
                          key={run.id}
                          style={{
                            borderBottom: '1px solid var(--border)',
                            transition: 'background 0.15s ease',
                          }}
                        >
                          <td style={{ padding: '12px 14px', fontFamily: 'monospace', fontWeight: 600, color: 'var(--accent)' }}>
                            #RUN-{run.id}
                          </td>
                          <td style={{ padding: '12px 14px' }}>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                              <span style={{ fontWeight: 600, color: 'var(--text-primary)', fontSize: 13 }}>
                                {run.task_name || (run.task_id ? `任务 #${run.task_id}` : run.script_name || '性能压测')}
                              </span>
                              {run.script_name && run.task_name && (
                                <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                                  关联脚本: {run.script_name}
                                </span>
                              )}
                            </div>
                          </td>
                          <td style={{ padding: '12px 12px' }}>
                            <span
                              style={{
                                fontSize: 11,
                                padding: '2px 8px',
                                borderRadius: 12,
                                fontWeight: 500,
                                background: isCompleted
                                  ? 'rgba(16, 185, 129, 0.1)'
                                  : isRunning
                                  ? 'rgba(59, 130, 246, 0.1)'
                                  : isStopped
                                  ? 'rgba(245, 158, 11, 0.1)'
                                  : 'rgba(239, 68, 68, 0.1)',
                                color: isCompleted
                                  ? '#10b981'
                                  : isRunning
                                  ? 'var(--accent)'
                                  : isStopped
                                  ? '#f59e0b'
                                  : '#ef4444',
                                display: 'inline-flex',
                                alignItems: 'center',
                                gap: 4,
                              }}
                            >
                              {isRunning && (
                                <span
                                  style={{
                                    width: 6,
                                    height: 6,
                                    borderRadius: '50%',
                                    background: 'var(--accent)',
                                    animation: 'pulse 1.5s infinite',
                                  }}
                                />
                              )}
                              {isCompleted ? '已完成' : isRunning ? '运行中' : isStopped ? '已停止' : '失败'}
                            </span>
                          </td>
                          <td style={{ padding: '12px 12px', color: 'var(--text-secondary)' }}>
                            {run.engine_used === 'jmeter_cli' ? 'JMeter CLI' : '内置 Python'}
                          </td>
                          <td style={{ padding: '12px 12px' }}>{run.concurrency || 1}</td>
                          <td style={{ padding: '12px 12px' }}>{run.total_samples || 0}</td>
                          <td style={{ padding: '12px 12px', color: 'var(--accent)', fontWeight: 600 }}>
                            {run.avg_tps || 0}
                          </td>
                          <td style={{ padding: '12px 12px' }}>{run.avg_rt_ms || 0} ms</td>
                          <td style={{ padding: '12px 12px' }}>{run.p90_rt_ms || 0} ms</td>
                          <td
                            style={{
                              padding: '12px 12px',
                              fontWeight: 600,
                              color: (run.error_rate || 0) > 0 ? '#ef4444' : '#10b981',
                            }}
                          >
                            {run.error_rate || 0}%
                          </td>
                          <td style={{ padding: '12px 14px', color: 'var(--text-muted)', fontSize: 11 }}>
                            {new Date(run.started_at).toLocaleString()}
                          </td>
                          <td style={{ padding: '12px 16px', textAlign: 'right' }}>
                            <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                              <button
                                onClick={() => {
                                  setReportRunId(run.id);
                                  setReportScriptName(run.task_name || run.script_name);
                                  setIsReportModalOpen(true);
                                }}
                                title="查看详细执行报表"
                                style={{
                                  padding: '4px 8px',
                                  borderRadius: 4,
                                  border: '1px solid var(--border)',
                                  background: 'var(--bg-base)',
                                  color: 'var(--accent)',
                                  fontSize: 11,
                                  cursor: 'pointer',
                                  display: 'inline-flex',
                                  alignItems: 'center',
                                  gap: 3,
                                }}
                              >
                                <Eye size={12} /> 报表
                              </button>
                              <button
                                onClick={() => {
                                  setRunTaskTarget(null);
                                  setViewRunId(run.id);
                                  setActiveRunTaskName(run.task_name || `压测 #${run.id}`);
                                  setIsRunModalOpen(true);
                                }}
                                title="查看控制台执行日志"
                                style={{
                                  padding: '4px 8px',
                                  borderRadius: 4,
                                  border: '1px solid var(--border)',
                                  background: 'var(--bg-base)',
                                  color: 'var(--text-secondary)',
                                  fontSize: 11,
                                  cursor: 'pointer',
                                  display: 'inline-flex',
                                  alignItems: 'center',
                                  gap: 3,
                                }}
                              >
                                <Terminal size={12} /> 日志
                              </button>
                              <button
                                onClick={() => handleDeleteRun(run.id)}
                                title="删除该执行记录"
                                style={{
                                  padding: '4px 6px',
                                  borderRadius: 4,
                                  border: '1px solid var(--border)',
                                  background: 'transparent',
                                  color: '#ef4444',
                                  fontSize: 11,
                                  cursor: 'pointer',
                                }}
                              >
                                <Trash2 size={12} />
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
        </>
      )}

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
              background: 'var(--bg-card)',
              border: '1px solid var(--border)',
              borderRadius: 10,
              width: '90%',
              maxWidth: 780,
              maxHeight: '90vh',
              display: 'flex',
              flexDirection: 'column',
              boxShadow: '0 20px 25px -5px rgba(0,0,0,0.3)',
              overflow: 'hidden',
            }}
          >
            {/* 顶栏 */}
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
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Layers size={17} color="var(--accent)" />
                <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, color: 'var(--text-primary)' }}>
                  新建性能测试任务
                </h3>
              </div>
              <button
                onClick={() => setCreateModalOpen(false)}
                style={{
                  background: 'transparent',
                  border: 'none',
                  color: 'var(--text-muted)',
                  cursor: 'pointer',
                  display: 'flex',
                  padding: 4,
                }}
              >
                <X size={18} />
              </button>
            </div>

                        {/* Content Body - 参照详情弹窗的单列纵向布局 */}
            <div style={{ padding: '18px 22px', overflowY: 'auto', flex: 1, display: 'flex', flexDirection: 'column', gap: 16 }}>
              {/* 1. 任务基础信息 */}
              <div
                style={{
                  background: 'var(--bg-base)',
                  border: '1px solid var(--border)',
                  borderRadius: 6,
                  padding: '12px 16px',
                  display: 'grid',
                  gridTemplateColumns: 'repeat(2, 1fr)',
                  gap: '10px 16px',
                  fontSize: 12,
                }}
              >
                <div>
                  <label style={{ color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>
                    任务名称 <span style={{ color: '#ef4444' }}>*</span>
                  </label>
                  <input
                    type="text"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="输入任务名称"
                    style={{
                      width: '100%',
                      height: 30,
                      padding: '0 8px',
                      borderRadius: 4,
                      border: '1px solid var(--border)',
                      background: 'var(--bg-card)',
                      color: 'var(--text-primary)',
                      fontSize: 12,
                    }}
                  />
                </div>

                <div>
                  <label style={{ color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>压测引擎</label>
                  <select
                    value={engineType}
                    onChange={(e: any) => setEngineType(e.target.value)}
                    style={{
                      width: '100%',
                      height: 30,
                      padding: '0 6px',
                      borderRadius: 4,
                      border: '1px solid var(--border)',
                      background: 'var(--bg-card)',
                      color: 'var(--text-primary)',
                      fontSize: 12,
                      cursor: 'pointer',
                    }}
                  >
                    <option value="jmeter_cli">本地 JMeter CLI (推荐)</option>
                    <option value="builtin">内置 Python 异步 (备用)</option>
                  </select>
                </div>

                <div style={{ gridColumn: 'span 2' }}>
                  <label style={{ color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>任务描述</label>
                  <input
                    type="text"
                    value={desc}
                    onChange={(e) => setDesc(e.target.value)}
                    placeholder="任务的场景说明与测试目标描述（选填）"
                    style={{
                      width: '100%',
                      height: 30,
                      padding: '0 8px',
                      borderRadius: 4,
                      border: '1px solid var(--border)',
                      background: 'var(--bg-card)',
                      color: 'var(--text-primary)',
                      fontSize: 12,
                    }}
                  />
                </div>

                <div>
                  <label style={{ color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>执行模式</label>
                  <select
                    value={execMode}
                    onChange={(e: any) => setExecMode(e.target.value)}
                    style={{
                      width: '100%',
                      height: 30,
                      padding: '0 6px',
                      borderRadius: 4,
                      border: '1px solid var(--border)',
                      background: 'var(--bg-card)',
                      color: 'var(--text-primary)',
                      fontSize: 12,
                      cursor: 'pointer',
                    }}
                  >
                    <option value="local">🖥️ 本机单机执行</option>
                    <option value="distributed">🌐 Master 分布式从机</option>
                  </select>
                </div>

                {execMode === 'distributed' && (
                  <div style={{ gridColumn: 'span 2', display: 'flex', flexDirection: 'column', gap: 6 }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                      <label style={{ color: 'var(--text-muted)' }}>从机节点配置</label>
                      {slaveNodes.length > 0 && (
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
                          style={{ background: 'none', border: 'none', color: 'var(--accent)', cursor: 'pointer', padding: 0, fontSize: 11 }}
                        >
                          全选在线从机 ({slaveNodes.filter((n) => n.status === 'online').length})
                        </button>
                      )}
                    </div>

                    {/* 可用从机节点快捷勾选列表 */}
                    {slaveNodes.length > 0 ? (
                      <div
                        style={{
                          display: 'flex',
                          flexWrap: 'wrap',
                          gap: 6,
                          padding: '6px 8px',
                          background: 'var(--bg-card)',
                          border: '1px solid var(--border)',
                          borderRadius: 4,
                          maxHeight: 90,
                          overflowY: 'auto',
                        }}
                      >
                        {slaveNodes.map((node) => {
                          const hostPort = `${node.host}:${node.port}`;
                          const currentHosts = slaveHosts
                            .split(',')
                            .map((h) => h.trim())
                            .filter(Boolean);
                          const isChecked = currentHosts.includes(hostPort);

                          return (
                            <label
                              key={node.id}
                              style={{
                                display: 'inline-flex',
                                alignItems: 'center',
                                gap: 4,
                                fontSize: 11,
                                cursor: 'pointer',
                                padding: '2px 6px',
                                borderRadius: 4,
                                background: isChecked ? 'rgba(59, 130, 246, 0.12)' : 'var(--bg-base)',
                                border: `1px solid ${isChecked ? 'var(--accent)' : 'var(--border)'}`,
                                color: isChecked ? 'var(--accent)' : 'var(--text-primary)',
                              }}
                            >
                              <input
                                type="checkbox"
                                checked={isChecked}
                                onChange={(e) => {
                                  if (e.target.checked) {
                                    const next = Array.from(new Set([...currentHosts, hostPort]));
                                    setSlaveHosts(next.join(', '));
                                  } else {
                                    const next = currentHosts.filter((h) => h !== hostPort);
                                    setSlaveHosts(next.join(', '));
                                  }
                                }}
                                style={{ margin: 0 }}
                              />
                              <span
                                style={{
                                  display: 'inline-block',
                                  width: 6,
                                  height: 6,
                                  borderRadius: '50%',
                                  background: node.status === 'online' ? '#10b981' : '#94a3b8',
                                }}
                              />
                              <span>{node.name || node.host}</span>
                              <span style={{ color: 'var(--text-muted)', fontSize: 10 }}>({hostPort})</span>
                            </label>
                          );
                        })}
                      </div>
                    ) : (
                      <div
                        style={{
                          fontSize: 11,
                          color: 'var(--text-muted)',
                          padding: '4px 8px',
                          background: 'var(--bg-card)',
                          border: '1px dashed var(--border)',
                          borderRadius: 4,
                        }}
                      >
                        暂无注册从机节点，您可直接在下方手动输入从机 IP:Port
                      </div>
                    )}

                    <input
                      type="text"
                      placeholder="自定义从机节点列表 (如 192.168.1.101:1099, 192.168.1.102:1099)"
                      value={slaveHosts}
                      onChange={(e) => setSlaveHosts(e.target.value)}
                      style={{
                        width: '100%',
                        height: 30,
                        padding: '0 8px',
                        borderRadius: 4,
                        border: '1px solid var(--border)',
                        background: 'var(--bg-card)',
                        color: 'var(--text-primary)',
                        fontFamily: 'monospace',
                        fontSize: 11,
                      }}
                    />
                  </div>
                )}
              </div>

              {/* 2. 关联压测脚本 */}
              <div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: 6 }}>
                    <FileCode size={14} color="var(--accent)" />
                    关联压测脚本
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

                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    {scripts.length > 0 && (
                      <button
                        type="button"
                        onClick={() => {
                          if (selectedScripts.length === scripts.length) {
                            setSelectedScripts([]);
                          } else {
                            setSelectedScripts(scripts.map((s) => ({ script_id: s.id, weight: 100 })));
                          }
                        }}
                        style={{ background: 'none', border: 'none', color: 'var(--accent)', fontSize: 11, cursor: 'pointer', padding: 0 }}
                      >
                        {selectedScripts.length === scripts.length ? '取消全选' : '全选全部'}
                      </button>
                    )}
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 4,
                        background: 'var(--bg-base)',
                        border: '1px solid var(--border)',
                        borderRadius: 4,
                        padding: '0 6px',
                        height: 24,
                      }}
                    >
                      <Search size={12} style={{ color: 'var(--text-muted)' }} />
                      <input
                        type="text"
                        placeholder="搜索脚本..."
                        value={scriptSearch}
                        onChange={(e) => setScriptSearch(e.target.value)}
                        style={{
                          background: 'transparent',
                          border: 'none',
                          outline: 'none',
                          fontSize: 11,
                          color: 'var(--text-primary)',
                          width: 100,
                        }}
                      />
                    </div>
                  </div>
                </div>

                <div
                  style={{
                    border: '1px solid var(--border)',
                    borderRadius: 6,
                    maxHeight: 160,
                    overflowY: 'auto',
                    background: 'var(--bg-base)',
                  }}
                >
                  {scripts.length === 0 ? (
                    <div style={{ padding: 20, textAlign: 'center', color: 'var(--text-muted)', fontSize: 12 }}>
                      暂无压测脚本
                    </div>
                  ) : (
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                      <thead>
                        <tr style={{ background: 'var(--bg-card)', borderBottom: '1px solid var(--border)', color: 'var(--text-muted)' }}>
                          <th style={{ padding: '6px 12px', width: 36, textAlign: 'center' }}></th>
                          <th style={{ padding: '6px 12px', textAlign: 'left' }}>脚本名称</th>
                          <th style={{ padding: '6px 12px', textAlign: 'left', width: 90 }}>脚本 ID</th>
                          <th style={{ padding: '6px 12px', textAlign: 'left', width: 100 }}>接口数</th>
                        </tr>
                      </thead>
                      <tbody>
                        {scripts
                          .filter((sc) => !scriptSearch.trim() || sc.name.toLowerCase().includes(scriptSearch.toLowerCase()))
                          .map((sc) => {
                            const isSelected = selectedScripts.some((s) => s.script_id === sc.id);
                            const stepCount = (sc.asset_ids && sc.asset_ids.length > 0)
                              ? sc.asset_ids.length
                              : (Array.isArray(sc.config?.steps) ? sc.config.steps.length : (Array.isArray(sc.config?.samplers) ? sc.config.samplers.length : 0));
                            return (
                              <tr
                                key={sc.id}
                                onClick={() => toggleScriptSelection(sc.id)}
                                style={{
                                  borderBottom: '1px solid var(--border)',
                                  background: isSelected ? 'rgba(59, 130, 246, 0.05)' : 'transparent',
                                  cursor: 'pointer',
                                }}
                              >
                                <td style={{ padding: '6px 12px', textAlign: 'center' }}>
                                  {isSelected ? <CheckSquare size={14} color="var(--accent)" /> : <Square size={14} color="var(--text-muted)" />}
                                </td>
                                <td style={{ padding: '6px 12px', color: isSelected ? 'var(--accent)' : 'var(--text-primary)', fontWeight: isSelected ? 600 : 400 }}>
                                  {sc.name}
                                </td>
                                <td style={{ padding: '6px 12px', color: 'var(--text-muted)' }}>
                                  #{sc.id}
                                </td>
                                <td style={{ padding: '6px 12px', color: 'var(--text-secondary)' }}>
                                  {stepCount} 个
                                </td>
                              </tr>
                            );
                          })}
                      </tbody>
                    </table>
                  )}
                </div>
              </div>

              {/* 3. 脚本动态参数配置 (-J 属性) */}
              <div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: 6 }}>
                    <Tag size={14} color="var(--accent)" />
                    脚本动态参数配置 (-J 属性)
                    <span style={{ fontSize: 11, fontWeight: 400, color: 'var(--text-muted)' }}>
                      (共 {allCreatePropertyKeys.length} 个参数)
                    </span>
                  </div>
                  {loadingProps && <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>解析中...</span>}
                </div>

                <div
                  style={{
                    background: 'var(--bg-base)',
                    border: '1px solid var(--border)',
                    borderRadius: 6,
                    padding: '10px 12px',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 10,
                  }}
                >
                  {allCreatePropertyKeys.length === 0 ? (
                    <div style={{ padding: '8px', color: 'var(--text-muted)', fontSize: 12, textAlign: 'center' }}>
                      未配置动态参数，您可在下方添加自定义 -J 属性。
                    </div>
                  ) : (
                    <div
                      style={{
                        display: 'grid',
                        gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
                        gap: 8,
                        maxHeight: 180,
                        overflowY: 'auto',
                      }}
                    >
                      {allCreatePropertyKeys.map((propName: string) => {
                        const rawExt = extractedProps.find((p: { name: string; default_value: string }) => p.name === propName);
                        const val = customProperties[propName] !== undefined ? customProperties[propName] : (rawExt?.default_value ?? '');
                        const isExtracted = !!rawExt;

                        return (
                          <div
                            key={propName}
                            style={{
                              background: 'var(--bg-card)',
                              border: '1px solid var(--border)',
                              borderRadius: 6,
                              padding: '6px 8px',
                              display: 'flex',
                              alignItems: 'center',
                              gap: 6,
                            }}
                          >
                            <span
                              style={{
                                fontSize: 11,
                                fontWeight: 600,
                                color: isExtracted ? 'var(--text-primary)' : 'var(--accent)',
                                flex: 1,
                                overflow: 'hidden',
                                textOverflow: 'ellipsis',
                                whiteSpace: 'nowrap',
                              }}
                              title={propName}
                            >
                              {propName}
                            </span>
                            <input
                              type="text"
                              value={val}
                              placeholder={rawExt?.default_value ? `默认: ${rawExt.default_value}` : '空值'}
                              onChange={(e) => setCustomProperties({ ...customProperties, [propName]: e.target.value })}
                              style={{
                                width: 90,
                                height: 22,
                                padding: '0 6px',
                                borderRadius: 4,
                                border: '1px solid var(--border)',
                                background: 'var(--bg-base)',
                                color: 'var(--text-primary)',
                                fontSize: 11,
                              }}
                            />
                            <button
                              type="button"
                              onClick={() => handleDeleteProp(propName)}
                              title="移除该动态参数"
                              style={{
                                background: 'none',
                                border: 'none',
                                color: '#ef4444',
                                cursor: 'pointer',
                                padding: 2,
                                display: 'flex',
                              }}
                            >
                              <Trash2 size={12} />
                            </button>
                          </div>
                        );
                      })}
                    </div>
                  )}

                  {/* 快捷追加新参数 */}
                  <div style={{ display: 'flex', gap: 6, paddingTop: 4, borderTop: '1px solid var(--border)' }}>
                    <input
                      type="text"
                      placeholder="自定义参数名 (如 threads)"
                      value={newPropKey}
                      onChange={(e) => setNewPropKey(e.target.value)}
                      style={{
                        flex: 1,
                        height: 26,
                        padding: '0 8px',
                        borderRadius: 4,
                        border: '1px solid var(--border)',
                        background: 'var(--bg-card)',
                        color: 'var(--text-primary)',
                        fontSize: 11,
                      }}
                    />
                    <input
                      type="text"
                      placeholder="属性值"
                      value={newPropVal}
                      onChange={(e) => setNewPropVal(e.target.value)}
                      style={{
                        flex: 1,
                        height: 26,
                        padding: '0 8px',
                        borderRadius: 4,
                        border: '1px solid var(--border)',
                        background: 'var(--bg-card)',
                        color: 'var(--text-primary)',
                        fontSize: 11,
                      }}
                    />
                    <button
                      type="button"
                      onClick={() => {
                        if (!newPropKey.trim()) return;
                        const key = newPropKey.trim();
                        setDeletedPropKeys((prev) => prev.filter((k) => k !== key));
                        setCustomProperties({ ...customProperties, [key]: newPropVal.trim() });
                        setNewPropKey('');
                        setNewPropVal('');
                      }}
                      style={{
                        height: 26,
                        padding: '0 10px',
                        borderRadius: 4,
                        border: '1px solid var(--border)',
                        background: 'var(--bg-card)',
                        color: 'var(--text-primary)',
                        fontSize: 11,
                        cursor: 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        gap: 3,
                      }}
                    >
                      <Plus size={12} /> 添加
                    </button>
                  </div>
                </div>
              </div>

              {/* 4. 实时调度命令预览 */}
              <div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: 6 }}>
                    <Terminal size={14} color="#38bdf8" />
                    调度执行命令实时预览
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      if (!createCommandPreview) return;
                      navigator.clipboard.writeText(createCommandPreview);
                      setCreateCopied(true);
                      toast.success('命令已复制到剪贴板');
                      setTimeout(() => setCreateCopied(false), 2000);
                    }}
                    style={{
                      background: 'none',
                      border: 'none',
                      color: createCopied ? '#10b981' : 'var(--accent)',
                      fontSize: 11,
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      gap: 4,
                      padding: 0,
                    }}
                  >
                    {createCopied ? <Check size={12} /> : <Copy size={12} />}
                    {createCopied ? '已复制' : '复制命令'}
                  </button>
                </div>
                <div
                  style={{
                    background: '#090d16',
                    border: '1px solid rgba(255,255,255,0.1)',
                    borderRadius: 6,
                    padding: '10px 14px',
                    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
                    fontSize: 11,
                    color: '#38bdf8',
                    lineHeight: 1.5,
                    wordBreak: 'break-all',
                    maxHeight: 80,
                    overflowY: 'auto',
                  }}
                >
                  {createCommandPreview}
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

      {/* 实时运行控制台 Modal */}
      <PerfTaskRunModal
        isOpen={isRunModalOpen}
        onClose={() => {
          setIsRunModalOpen(false);
          setRunTaskTarget(null);
          setViewRunId(null);
          if (currentProjectId !== null) {
            loadTasks(currentProjectId);
            loadRuns();
          }
        }}
        task={runTaskTarget}
        runId={viewRunId}
        taskName={activeRunTaskName || runTaskTarget?.name}
        onOpenReport={(runId) => {
          setIsRunModalOpen(false);
          setReportRunId(runId);
          setReportScriptName(runTaskTarget?.name || activeRunTaskName);
          setIsReportModalOpen(true);
        }}
        onRunFinished={() => {
          if (currentProjectId !== null) {
            loadTasks(currentProjectId);
            loadRuns();
          }
        }}
      />

      {/* JTL 测试报告与明细分析 Modal */}
      <JtlReportModal
        isOpen={isReportModalOpen}
        onClose={() => setIsReportModalOpen(false)}
        runId={reportRunId}
        scriptName={reportScriptName}
      />

      {/* 任务详情弹窗 */}
      <PerfTaskDetailModal
        isOpen={detailTaskId !== null}
        taskId={detailTaskId}
        onClose={() => setDetailTaskId(null)}
        onEdit={(id) => {
          setDetailTaskId(null);
          setEditTaskId(id);
        }}
        onRun={(t) => handleRunTask(t)}
        onOpenReport={(runId) => {
          setReportRunId(runId);
          setIsReportModalOpen(true);
        }}
      />

      {/* 任务编辑弹窗 */}
      <PerfTaskEditModal
        isOpen={editTaskId !== null}
        taskId={editTaskId}
        onClose={() => setEditTaskId(null)}
        onSuccess={() => {
          if (currentProjectId !== null) {
            loadTasks(currentProjectId);
          }
        }}
      />
    </div>
  );
}
