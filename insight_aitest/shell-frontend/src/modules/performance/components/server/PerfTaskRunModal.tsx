import React, { useState, useEffect, useRef } from 'react';
import {
  Terminal,
  Play,
  Square,
  Copy,
  Trash2,
  Check,
  BarChart2,
  Globe,
  X,
  Layers,
} from 'lucide-react';
import { toast } from 'sonner';
import type { UIEnv } from '../../../ui/store/automationStore';
import { buildJMeterCommand } from './commandPreview';

export interface PerfTaskRunModalProps {
  isOpen: boolean;
  onClose: () => void;
  task?: {
    id: number;
    project_id?: number;
    name: string;
    engine_type?: string;
    exec_mode?: string;
    slave_hosts?: string;
    custom_properties?: Record<string, string>;
    scripts?: any[];
  } | null;
  runId?: number | null;
  taskName?: string;
  onOpenReport?: (runId: number) => void;
  onRunFinished?: (runId: number) => void;
}

export const PerfTaskRunModal: React.FC<PerfTaskRunModalProps> = ({
  isOpen,
  onClose,
  task,
  runId,
  taskName,
  onOpenReport,
  onRunFinished,
}) => {
  const [envs, setEnvs] = useState<UIEnv[]>([]);
  const [selectedEnvId, setSelectedEnvId] = useState<number | ''>('');
  const [execMode, setExecMode] = useState<'local' | 'distributed'>('local');
  const [slaveHosts, setSlaveHosts] = useState('');

  const [running, setRunning] = useState<boolean>(false);
  const [stopping, setStopping] = useState<boolean>(false);
  const [activeRunId, setActiveRunId] = useState<number | null>(null);
  const [logs, setLogs] = useState<string[]>([]);
  const [autoScroll, setAutoScroll] = useState<boolean>(true);
  const [copied, setCopied] = useState<boolean>(false);
  const [finalStatus, setFinalStatus] = useState<'completed' | 'failed' | 'stopped' | null>(null);
  const [runSummary, setRunSummary] = useState<any>(null);

  // 待执行任务详情与动态参数（用于未运行时的实时命令预览）
  const [taskDetail, setTaskDetail] = useState<any>(null);
  const [baselineProps, setBaselineProps] = useState<{ name: string; default_value: string }[]>([]);
  const [cmdCopied, setCmdCopied] = useState<boolean>(false);

  const terminalRef = useRef<HTMLDivElement>(null);
  const eventSourceRef = useRef<EventSource | null>(null);

  // 初始化或重置弹窗状态
  useEffect(() => {
    if (!isOpen) {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
      return;
    }

    setLogs([]);
    setStopping(false);
    setCopied(false);
    setCmdCopied(false);

    if (task) {
      // 任务启动准备模式
      setExecMode(task.exec_mode === 'distributed' ? 'distributed' : 'local');
      setSlaveHosts(task.slave_hosts || '');
      setRunning(false);
      setActiveRunId(null);
      setFinalStatus(null);
      setRunSummary(null);
      setTaskDetail(null);
      setBaselineProps([]);
      loadProjectEnvs(task.project_id);
      loadTaskDetailAndProps(task.id, task);
    } else if (runId) {
      // 纯日志回看或监控已有运行模式
      setActiveRunId(runId);
      loadExistingRun(runId);
    }
  }, [isOpen, task, runId]);

  const loadTaskDetailAndProps = async (taskId: number, initialTask?: any) => {
    try {
      let currentTaskData = initialTask;
      const res = await fetch(`/api/modules/performance/server/tasks/${taskId}`);
      if (res.ok) {
        currentTaskData = await res.json();
        setTaskDetail(currentTaskData);
        setExecMode(currentTaskData.exec_mode === 'distributed' ? 'distributed' : 'local');
        setSlaveHosts(currentTaskData.slave_hosts || '');
      } else if (initialTask) {
        setTaskDetail(initialTask);
      }

      const scriptIds = (currentTaskData?.scripts || []).map((s: any) => s.script_id).join(',');
      if (scriptIds) {
        const pRes = await fetch(`/api/modules/performance/server/scripts/batch/properties?script_ids=${scriptIds}`);
        if (pRes.ok) {
          const pData = await pRes.json();
          setBaselineProps(pData.properties || []);
        } else {
          setBaselineProps([]);
        }
      } else {
        setBaselineProps([]);
      }
    } catch (e) {
      console.error('加载任务详情与脚本属性失败', e);
    }
  };

  const loadProjectEnvs = async (projId?: number) => {
    try {
      let list: UIEnv[] = [];
      if (projId) {
        const r = await fetch(`/api/modules/ui/automation/envs?project_id=${projId}`);
        if (r.ok) list = await r.json();
      }
      if (!list || list.length === 0) {
        const rAll = await fetch('/api/modules/ui/automation/envs');
        if (rAll.ok) list = await rAll.json();
      }
      setEnvs(list || []);
      if (list && list.length > 0) {
        const def = list.find((e) => e.is_default) || list[0];
        setSelectedEnvId(def.id);
      } else {
        setSelectedEnvId('');
      }
    } catch {
      setEnvs([]);
      setSelectedEnvId('');
    }
  };

  const loadExistingRun = async (id: number) => {
    try {
      const res = await fetch(`/api/modules/performance/server/runs/${id}`);
      if (res.ok) {
        const data = await res.json();
        setRunSummary(data);
        if (data.status === 'running') {
          setRunning(true);
          connectSse(id);
        } else {
          setRunning(false);
          setFinalStatus(data.status);
          if (data.console_output) {
            setLogs(data.console_output.split('\n'));
          }
        }
      }
    } catch (err) {
      console.error('加载已有执行记录失败', err);
    }
  };

  const connectSse = (id: number) => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }
    const es = new EventSource(`/api/modules/performance/server/runs/${id}/stream`);
    eventSourceRef.current = es;

    es.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.type === 'log') {
          setLogs((prev) => [...prev, payload.text]);
        } else if (payload.type === 'done') {
          setRunning(false);
          setStopping(false);
          setFinalStatus(payload.status);
          es.close();
          fetchRunSummary(id);
          onRunFinished?.(id);
        }
      } catch {
        // ignore non-json
      }
    };

    es.onerror = () => {
      fetchRunSummary(id);
    };
  };

  const fetchRunSummary = async (id: number) => {
    try {
      const res = await fetch(`/api/modules/performance/server/runs/${id}`);
      if (res.ok) {
        const data = await res.json();
        setRunSummary(data);
        if (data.status && data.status !== 'running') {
          setFinalStatus(data.status);
          setRunning(false);
        }
      }
    } catch {
      // ignore
    }
  };

  const handleStartRun = async () => {
    if (!task) return;
    setRunning(true);
    setStopping(false);
    setLogs([]);
    setFinalStatus(null);
    setRunSummary(null);

    const chosenEnv = envs.find((e) => e.id === Number(selectedEnvId));

    try {
      const res = await fetch(`/api/modules/performance/server/tasks/${task.id}/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          env_id: chosenEnv ? chosenEnv.id : null,
          env_base_url: chosenEnv ? chosenEnv.base_url : '',
          exec_mode: execMode,
          slave_hosts: execMode === 'distributed' ? slaveHosts : '',
        }),
      });

      const data = await res.json();
      if (!res.ok || !data.ok) {
        throw new Error(data.detail || data.message || '启动运行失败');
      }

      const newRunId = data.run_id;
      setActiveRunId(newRunId);
      toast.success(`压测任务「${task.name}」已开始运行`);
      connectSse(newRunId);
    } catch (err: any) {
      setRunning(false);
      setStopping(false);
      setFinalStatus('failed');
      setLogs((prev) => [...prev, `[ERROR] 启动失败: ${err.message}`]);
      toast.error(err.message || '启动运行失败');
    }
  };

  const handleStop = async () => {
    const curId = activeRunId || runId;
    if (!curId) return;
    setStopping(true);
    try {
      const res = await fetch(`/api/modules/performance/server/runs/${curId}/stop`, {
        method: 'POST',
      });
      if (res.ok) {
        toast.info('已发送停止指令，正在安全关闭压测引擎...');
      } else {
        toast.error('停止压测失败');
        setStopping(false);
      }
    } catch (err: any) {
      toast.error(err.message || '停止失败');
      setStopping(false);
    }
  };

  const handleCopyLogs = () => {
    if (logs.length === 0) return;
    navigator.clipboard.writeText(logs.join('\n'));
    setCopied(true);
    toast.success('控制台日志已复制');
    setTimeout(() => setCopied(false), 2000);
  };

  useEffect(() => {
    if (autoScroll && terminalRef.current) {
      terminalRef.current.scrollTop = terminalRef.current.scrollHeight;
    }
  }, [logs, autoScroll]);

  if (!isOpen) return null;

  const currentDisplayRunId = activeRunId || runId;
  const currentDisplayName = task?.name || taskName || (currentDisplayRunId ? `压测 #${currentDisplayRunId}` : '任务');
  const chosenEnv = envs.find((e) => e.id === Number(selectedEnvId));

  // 计算待执行命令预览 (完全对齐详情页预览逻辑)
  const currentTask = taskDetail || task;
  const effectiveProps: Record<string, string> = {};
  const processedKeys = new Set<string>();

  baselineProps.forEach((p) => {
    const val =
      currentTask?.custom_properties?.[p.name] !== undefined
        ? String(currentTask.custom_properties[p.name])
        : (p.default_value ?? '');
    effectiveProps[p.name] = val;
    processedKeys.add(p.name);
  });

  Object.entries(currentTask?.custom_properties || {}).forEach(([k, v]) => {
    if (!processedKeys.has(k)) {
      effectiveProps[k] = String(v ?? '');
      processedKeys.add(k);
    }
  });

  const firstScriptName = currentTask?.scripts?.[0]?.script_name || '';
  const commandPreview = currentTask
    ? buildJMeterCommand({
        engineType: (currentTask.engine_type as any) || 'jmeter_cli',
        execMode,
        slaveHosts: execMode === 'distributed' ? slaveHosts : '',
        scriptName: firstScriptName,
        customProperties: effectiveProps,
      })
    : '';

  const handleCopyCommand = () => {
    if (!commandPreview) return;
    navigator.clipboard.writeText(commandPreview);
    setCmdCopied(true);
    toast.success('执行命令已复制到剪贴板');
    setTimeout(() => setCmdCopied(false), 2000);
  };

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.65)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1050,
        backdropFilter: 'blur(3px)',
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget && !running) onClose();
      }}
    >
      <div
        style={{
          background: 'var(--bg-card)',
          border: '1px solid var(--border)',
          borderRadius: 10,
          width: '92%',
          maxWidth: 960,
          height: '86vh',
          display: 'flex',
          flexDirection: 'column',
          boxShadow: '0 20px 30px -10px rgba(0,0,0,0.4)',
          overflow: 'hidden',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div
          style={{
            padding: '12px 18px',
            borderBottom: '1px solid var(--border)',
            background: 'var(--bg-base)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <Terminal size={17} color="var(--accent)" />
            <h3 style={{ margin: 0, fontSize: 14, fontWeight: 600, color: 'var(--text-primary)' }}>
              压测任务控制台
            </h3>
            <span style={{ fontSize: 12, color: 'var(--text-secondary)', fontWeight: 500 }}>
              ({currentDisplayName})
            </span>
            {currentDisplayRunId && (
              <span
                style={{
                  fontSize: 11,
                  padding: '2px 8px',
                  borderRadius: 4,
                  fontWeight: 600,
                  background:
                    running
                      ? 'rgba(59,130,246,0.12)'
                      : finalStatus === 'completed'
                      ? 'rgba(16,185,129,0.12)'
                      : finalStatus === 'stopped'
                      ? 'rgba(245,158,11,0.12)'
                      : 'rgba(239,68,68,0.12)',
                  color:
                    running
                      ? '#3b82f6'
                      : finalStatus === 'completed'
                      ? '#10b981'
                      : finalStatus === 'stopped'
                      ? '#f59e0b'
                      : '#ef4444',
                }}
              >
                {running ? '执行中...' : finalStatus === 'completed' ? '已完成' : finalStatus === 'stopped' ? '已停止' : '执行失败'}
              </span>
            )}
          </div>

          <button
            onClick={() => {
              if (!running) onClose();
            }}
            disabled={running}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--text-muted)',
              cursor: running ? 'not-allowed' : 'pointer',
              display: 'flex',
              padding: 4,
            }}
          >
            <X size={18} />
          </button>
        </div>

        {/* Toolbar: 环境选择与执行操作栏 */}
        <div
          style={{
            padding: '8px 16px',
            background: 'var(--bg-card)',
            borderBottom: '1px solid var(--border)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            fontSize: 12,
            gap: 12,
            flexWrap: 'wrap',
          }}
        >
          {/* 左侧：环境与模式配置（任务未启动时可配置） */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            {task && !running && !activeRunId ? (
              <>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <Globe size={14} style={{ color: 'var(--text-muted)' }} />
                  <span style={{ color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>执行环境:</span>
                  <select
                    value={selectedEnvId}
                    disabled={running}
                    onChange={(e) => setSelectedEnvId(e.target.value ? Number(e.target.value) : '')}
                    style={{
                      padding: '5px 10px',
                      borderRadius: 6,
                      border: '1px solid var(--border)',
                      background: 'var(--bg-base)',
                      color: 'var(--text-primary)',
                      fontSize: 12,
                      maxWidth: 240,
                      cursor: 'pointer',
                    }}
                  >
                    <option value="">不覆盖（使用脚本内置地址）</option>
                    {envs.map((env) => (
                      <option key={env.id} value={env.id}>
                        {env.name || '默认环境'} ({env.base_url})
                      </option>
                    ))}
                  </select>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span style={{ color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>运行模式:</span>
                  <span
                    style={{
                      padding: '4px 10px',
                      borderRadius: 6,
                      border: '1px solid var(--border)',
                      background: 'var(--bg-base)',
                      color: execMode === 'distributed' ? 'var(--accent)' : 'var(--text-primary)',
                      fontSize: 12,
                      fontWeight: 500,
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: 6,
                    }}
                  >
                    {execMode === 'distributed' ? '🌐 Master 分布式从机' : '🖥️ 本机单机'}
                  </span>
                </div>

                {execMode === 'distributed' && slaveHosts && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <span style={{ color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>从机节点:</span>
                    <span
                      style={{
                        padding: '4px 10px',
                        borderRadius: 6,
                        border: '1px solid var(--border)',
                        background: 'var(--bg-base)',
                        color: 'var(--text-primary)',
                        fontFamily: 'monospace',
                        fontSize: 11,
                        maxWidth: 240,
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                      }}
                      title={slaveHosts}
                    >
                      {slaveHosts}
                    </span>
                  </div>
                )}
              </>
            ) : (
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, color: 'var(--text-secondary)' }}>
                {currentDisplayRunId && (
                  <span>执行编号: <strong style={{ color: 'var(--accent)', fontFamily: 'monospace' }}>#RUN-{currentDisplayRunId}</strong></span>
                )}
                {chosenEnv && (
                  <span>目标环境: <strong style={{ color: 'var(--text-primary)' }}>{chosenEnv.name} ({chosenEnv.base_url})</strong></span>
                )}
                {runSummary && (
                  <>
                    <span>引擎: {runSummary.engine_used === 'jmeter_cli' ? 'JMeter CLI' : 'Python Async'}</span>
                    <span>模式: {runSummary.exec_mode === 'distributed' ? '分布式从机' : '本机单机'}</span>
                  </>
                )}
              </div>
            )}
          </div>

          {/* 右侧：动作按钮 */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, color: 'var(--text-muted)', cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={autoScroll}
                onChange={(e) => setAutoScroll(e.target.checked)}
              />
              自动滚屏
            </label>

            <button
              onClick={handleCopyLogs}
              style={{
                height: 26,
                padding: '0 8px',
                borderRadius: 4,
                border: '1px solid var(--border)',
                background: 'var(--bg-base)',
                color: copied ? '#10b981' : 'var(--text-secondary)',
                fontSize: 11,
                cursor: 'pointer',
                display: 'inline-flex',
                alignItems: 'center',
                gap: 4,
              }}
            >
              {copied ? <Check size={11} /> : <Copy size={11} />}
              {copied ? '已复制' : '复制日志'}
            </button>

            <button
              onClick={() => setLogs([])}
              style={{
                height: 26,
                padding: '0 8px',
                borderRadius: 4,
                border: '1px solid var(--border)',
                background: 'var(--bg-base)',
                color: 'var(--text-secondary)',
                fontSize: 11,
                cursor: 'pointer',
                display: 'inline-flex',
                alignItems: 'center',
                gap: 4,
              }}
            >
              <Trash2 size={11} />
              清屏
            </button>

            {/* 启动 / 停止操作按钮 */}
            {task && !running && !activeRunId ? (
              <button
                onClick={handleStartRun}
                style={{
                  height: 26,
                  padding: '0 14px',
                  borderRadius: 4,
                  border: 'none',
                  background: '#10b981',
                  color: '#fff',
                  fontSize: 12,
                  fontWeight: 600,
                  cursor: 'pointer',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 5,
                  boxShadow: '0 1px 3px rgba(16, 185, 129, 0.3)',
                }}
              >
                <Play size={12} fill="#fff" />
                开始运行
              </button>
            ) : running ? (
              <button
                onClick={handleStop}
                disabled={stopping}
                style={{
                  height: 26,
                  padding: '0 12px',
                  borderRadius: 4,
                  border: 'none',
                  background: '#ef4444',
                  color: '#fff',
                  fontSize: 11,
                  fontWeight: 600,
                  cursor: stopping ? 'not-allowed' : 'pointer',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 4,
                  opacity: stopping ? 0.6 : 1,
                }}
              >
                <Square size={11} fill="#fff" />
                {stopping ? '停止中...' : '终止压测'}
              </button>
            ) : null}
          </div>
        </div>

        {/* Terminal Output */}
        <div
          ref={terminalRef}
          style={{
            flex: 1,
            background: '#090d16',
            color: '#e2e8f0',
            fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
            fontSize: 11.5,
            lineHeight: 1.5,
            padding: '12px 16px',
            overflowY: 'auto',
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-all',
          }}
        >
          {logs.length === 0 ? (
            <div style={{ padding: '24px 16px', display: 'flex', flexDirection: 'column', height: '100%', boxSizing: 'border-box' }}>
              {task && !running && !activeRunId ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 14, maxWidth: 880, width: '100%', margin: '0 auto' }}>
                  <div
                    style={{
                      background: 'rgba(30, 41, 59, 0.45)',
                      border: '1px solid rgba(255, 255, 255, 0.08)',
                      borderRadius: 8,
                      padding: '10px 16px',
                      display: 'flex',
                      alignItems: 'center',
                      gap: 10,
                    }}
                  >
                    <Layers size={17} style={{ color: 'var(--accent)', flexShrink: 0 }} />
                    <div style={{ fontSize: 12, color: '#cbd5e1', lineHeight: 1.5 }}>
                      请确认上方<strong style={{ color: '#fff' }}>「执行环境」</strong>与<strong style={{ color: '#fff' }}>「运行模式」</strong>，点击右上角<strong style={{ color: '#10b981' }}>「开始运行」</strong>启动性能测试
                    </div>
                  </div>

                  {/* 调度执行命令实时预览 (直接显示详情页预览命令) */}
                  <div
                    style={{
                      background: 'rgba(15, 23, 42, 0.75)',
                      border: '1px solid rgba(56, 189, 248, 0.22)',
                      borderRadius: 8,
                      padding: '14px 16px',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: 8,
                      textAlign: 'left',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                      <div style={{ fontSize: 12, fontWeight: 600, color: '#f1f5f9', display: 'flex', alignItems: 'center', gap: 6 }}>
                        <Terminal size={14} color="#38bdf8" />
                        调度执行命令预览
                      </div>
                      <button
                        onClick={handleCopyCommand}
                        style={{
                          background: 'rgba(56, 189, 248, 0.1)',
                          border: '1px solid rgba(56, 189, 248, 0.25)',
                          borderRadius: 4,
                          color: cmdCopied ? '#10b981' : '#38bdf8',
                          fontSize: 11,
                          cursor: 'pointer',
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: 4,
                          padding: '3px 8px',
                          transition: 'all 0.15s ease',
                        }}
                      >
                        {cmdCopied ? <Check size={12} /> : <Copy size={12} />}
                        {cmdCopied ? '已复制' : '复制命令'}
                      </button>
                    </div>

                    <div
                      style={{
                        background: '#030712',
                        border: '1px solid rgba(255, 255, 255, 0.08)',
                        borderRadius: 6,
                        padding: '10px 12px',
                        fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
                        fontSize: 11.5,
                        color: '#38bdf8',
                        lineHeight: 1.6,
                        wordBreak: 'break-all',
                        maxHeight: 140,
                        overflowY: 'auto',
                      }}
                    >
                      {commandPreview || '正在生成调度执行命令预览...'}
                    </div>

                    <div style={{ fontSize: 11, color: '#94a3b8' }}>
                      启动压测时将执行上述命令，并通过动态参数 <code>-J</code> 实时透传覆盖脚本配置。
                    </div>
                  </div>
                </div>
              ) : (
                <div style={{ color: '#64748b', fontStyle: 'italic', textAlign: 'center', margin: 'auto' }}>
                  正在初始化压测引擎与日志管道...
                </div>
              )}
            </div>
          ) : (
            logs.map((line, idx) => {
              const isErr = line.includes('[STDERR]') || line.includes('ERROR') || line.includes('Exception');
              const isWarn = line.includes('WARN');
              const isSummary = line.includes('summary =') || line.includes('summary +');
              return (
                <div
                  key={idx}
                  style={{
                    color: isErr ? '#f87171' : isWarn ? '#fbbf24' : isSummary ? '#38bdf8' : '#e2e8f0',
                  }}
                >
                  {line}
                </div>
              );
            })
          )}
        </div>

        {/* Summary Card (when finished or summary available) */}
        {runSummary && (
          <div
            style={{
              padding: '10px 18px',
              borderTop: '1px solid var(--border)',
              background: 'var(--bg-base)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 16,
              fontSize: 12,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
              <div>
                <span style={{ color: 'var(--text-muted)' }}>样本总数: </span>
                <strong>{runSummary.total_samples || 0}</strong>
              </div>
              <div>
                <span style={{ color: 'var(--text-muted)' }}>错误率: </span>
                <strong style={{ color: (runSummary.error_rate || 0) > 0 ? '#ef4444' : '#10b981' }}>
                  {runSummary.error_rate || 0}%
                </strong>
              </div>
              <div>
                <span style={{ color: 'var(--text-muted)' }}>平均 TPS: </span>
                <strong style={{ color: 'var(--accent)' }}>{runSummary.avg_tps || 0}</strong>
              </div>
              <div>
                <span style={{ color: 'var(--text-muted)' }}>平均耗时: </span>
                <strong>{runSummary.avg_rt_ms || 0} ms</strong>
              </div>
              <div>
                <span style={{ color: 'var(--text-muted)' }}>P90 耗时: </span>
                <strong>{runSummary.p90_rt_ms || 0} ms</strong>
              </div>
            </div>

            {onOpenReport && currentDisplayRunId && (
              <button
                type="button"
                onClick={() => {
                  onClose();
                  onOpenReport(currentDisplayRunId);
                }}
                style={{
                  height: 30,
                  padding: '0 14px',
                  borderRadius: 5,
                  border: 'none',
                  background: 'var(--accent)',
                  color: '#fff',
                  fontSize: 12,
                  fontWeight: 600,
                  cursor: 'pointer',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 5,
                }}
              >
                <BarChart2 size={13} />
                查看完整执行报表
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
};
