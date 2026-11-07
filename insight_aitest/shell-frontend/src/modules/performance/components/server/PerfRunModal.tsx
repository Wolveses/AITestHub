import React, { useState, useEffect, useRef } from 'react';
import {
  Play,
  Square,
  Terminal,
  CheckCircle2,
  XCircle,
  Copy,
  Trash2,
  Check,
  Globe,
} from 'lucide-react';
import type { UIEnv } from '../../../ui/store/automationStore';

interface PerfRunModalProps {
  isOpen: boolean;
  onClose: () => void;
  script: {
    id: number;
    project_id?: number;
    name: string;
    config?: {
      concurrency?: number;
      duration?: number;
      steps?: any[];
    };
  } | null;
  onRunFinished?: (runId: number) => void;
}

export const PerfRunModal: React.FC<PerfRunModalProps> = ({
  isOpen,
  onClose,
  script,
  onRunFinished,
}) => {
  const [envs, setEnvs] = useState<UIEnv[]>([]);
  const [selectedEnvId, setSelectedEnvId] = useState<number | ''>('');

  const [running, setRunning] = useState<boolean>(false);
  const [stopping, setStopping] = useState<boolean>(false);
  const [activeRunId, setActiveRunId] = useState<number | null>(null);
  const [logs, setLogs] = useState<string[]>([]);
  const [autoScroll, setAutoScroll] = useState<boolean>(true);
  const [copied, setCopied] = useState<boolean>(false);
  const [finalStatus, setFinalStatus] = useState<'completed' | 'failed' | 'stopped' | null>(null);
  const [runSummary, setRunSummary] = useState<any>(null);

  const terminalRef = useRef<HTMLDivElement>(null);
  const eventSourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (script && isOpen) {
      setLogs([]);
      setActiveRunId(null);
      setRunning(false);
      setStopping(false);
      setFinalStatus(null);
      setRunSummary(null);
      loadProjectEnvs(script.project_id);
    }
  }, [script, isOpen]);

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

  useEffect(() => {
    if (autoScroll && terminalRef.current) {
      terminalRef.current.scrollTop = terminalRef.current.scrollHeight;
    }
  }, [logs, autoScroll]);

  useEffect(() => {
    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
    };
  }, []);

  if (!isOpen || !script) return null;

  const startRun = async () => {
    setRunning(true);
    setStopping(false);
    setLogs([]);
    setFinalStatus(null);
    setRunSummary(null);

    const chosenEnv = envs.find((e) => e.id === Number(selectedEnvId));

    try {
      const res = await fetch(`/api/modules/performance/server/scripts/${script.id}/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          engine_type: 'jmeter_cli',
          env_id: chosenEnv ? chosenEnv.id : null,
          env_base_url: chosenEnv ? chosenEnv.base_url : '',
        }),
      });

      const data = await res.json();
      if (!res.ok || !data.ok) {
        throw new Error(data.detail || data.message || '启动运行失败');
      }

      const runId = data.run_id;
      setActiveRunId(runId);

      // 建立 SSE 实时日志连接
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }

      const es = new EventSource(`/api/modules/performance/server/runs/${runId}/stream`);
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
            fetchRunSummary(runId);
            if (onRunFinished) {
              onRunFinished(runId);
            }
          }
        } catch {
          // ignore non-json
        }
      };

      es.onerror = () => {
        checkRunFinalStatus(runId);
      };
    } catch (err: any) {
      setRunning(false);
      setStopping(false);
      setFinalStatus('failed');
      setLogs((prev) => [...prev, `[ERROR] 启动失败: ${err.message}`]);
    }
  };

  const checkRunFinalStatus = async (runId: number) => {
    try {
      const res = await fetch(`/api/modules/performance/server/runs/${runId}`);
      if (res.ok) {
        const data = await res.json();
        if (['completed', 'failed', 'stopped'].includes(data.status)) {
          setRunning(false);
          setStopping(false);
          setFinalStatus(data.status);
          setRunSummary(data);
          if (eventSourceRef.current) {
            eventSourceRef.current.close();
          }
          if (onRunFinished) {
            onRunFinished(runId);
          }
        }
      }
    } catch {
      // ignore
    }
  };

  const fetchRunSummary = async (runId: number) => {
    try {
      const res = await fetch(`/api/modules/performance/server/runs/${runId}`);
      if (res.ok) {
        const data = await res.json();
        setRunSummary(data);
      }
    } catch {
      // ignore
    }
  };

  const stopRun = async () => {
    if (!activeRunId || stopping) return;
    setStopping(true);
    try {
      await fetch(`/api/modules/performance/server/runs/${activeRunId}/stop`, {
        method: 'POST',
      });
    } catch (err: any) {
      setStopping(false);
      setLogs((prev) => [...prev, `[ERROR] 停止请求失败: ${err.message}`]);
    }
  };

  const handleCopyLogs = () => {
    navigator.clipboard.writeText(logs.join('\n'));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 1000,
        background: 'rgba(0, 0, 0, 0.65)',
        backdropFilter: 'blur(3px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 24,
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget && !running) onClose();
      }}
    >
      <div
        style={{
          width: '92%',
          maxWidth: 1000,
          height: '86vh',
          maxHeight: 820,
          background: 'var(--bg-card)',
          borderRadius: 12,
          border: '1px solid var(--border)',
          boxShadow: '0 20px 45px rgba(0,0,0,0.4)',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
        }}
      >
        {/* 顶部标题栏 */}
        <div
          style={{
            padding: '14px 20px',
            borderBottom: '1px solid var(--border)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            background: 'var(--bg-card)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div
              style={{
                width: 30,
                height: 30,
                borderRadius: 8,
                background: 'rgba(16, 185, 129, 0.12)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: '#10b981',
              }}
            >
              <Play size={16} fill="#10b981" />
            </div>
            <div>
              <div style={{ fontSize: 15, fontWeight: 600, color: 'var(--text-primary)' }}>
                运行场景
              </div>
              <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                {script.name} · 按照脚本内容运行
              </div>
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
              <Globe size={14} style={{ color: 'var(--text-muted)' }} />
              <span style={{ color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>环境:</span>
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
                  maxWidth: 260,
                  cursor: running ? 'not-allowed' : 'pointer',
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

            {!running ? (
              <button
                onClick={startRun}
                style={{
                  padding: '6px 16px',
                  borderRadius: 6,
                  border: 'none',
                  background: '#10b981',
                  color: '#fff',
                  fontSize: 12,
                  fontWeight: 600,
                  cursor: 'pointer',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 6,
                }}
              >
                <Play size={13} fill="#fff" /> 开始运行
              </button>
            ) : (
              <button
                onClick={stopRun}
                disabled={stopping}
                style={{
                  padding: '6px 16px',
                  borderRadius: 6,
                  border: 'none',
                  background: '#ef4444',
                  color: '#fff',
                  fontSize: 12,
                  fontWeight: 600,
                  cursor: stopping ? 'not-allowed' : 'pointer',
                  opacity: stopping ? 0.7 : 1,
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 6,
                }}
              >
                <Square size={13} fill="#fff" /> {stopping ? '正在停止...' : '停止'}
              </button>
            )}

            <button
              onClick={onClose}
              disabled={running}
              style={{
                border: 'none',
                background: 'transparent',
                color: 'var(--text-muted)',
                fontSize: 18,
                cursor: running ? 'not-allowed' : 'pointer',
                padding: '4px 8px',
                borderRadius: 4,
              }}
            >
              ✕
            </button>
          </div>
        </div>

        {/* 控制台工具栏与状态徽标 */}
        <div
          style={{
            padding: '8px 16px',
            background: '#090d16',
            borderBottom: '1px solid #1e293b',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            fontSize: 12,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: '#94a3b8' }}>
            <Terminal size={14} color="#38bdf8" />
            <span style={{ fontWeight: 600, color: '#f8fafc' }}>实时控制台终端</span>
            {running && (
              <span
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 5,
                  color: '#38bdf8',
                  fontSize: 11,
                }}
              >
                <span
                  style={{
                    width: 6,
                    height: 6,
                    borderRadius: '50%',
                    background: '#38bdf8',
                    animation: 'pulse 1.5s infinite',
                  }}
                />
                执行中...
              </span>
            )}
            {finalStatus === 'completed' && (
              <span style={{ color: '#10b981', display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11 }}>
                <CheckCircle2 size={13} /> 已完成
              </span>
            )}
            {finalStatus === 'stopped' && (
              <span style={{ color: '#f59e0b', display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11 }}>
                <Square size={12} fill="#f59e0b" /> 已停止
              </span>
            )}
            {finalStatus === 'failed' && (
              <span style={{ color: '#ef4444', display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11 }}>
                <XCircle size={13} /> 执行异常
              </span>
            )}
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 4, color: '#94a3b8', fontSize: 11, cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={autoScroll}
                onChange={(e) => setAutoScroll(e.target.checked)}
              />
              自动滚屏
            </label>

            <button
              onClick={handleCopyLogs}
              disabled={logs.length === 0}
              style={{
                border: 'none',
                background: 'transparent',
                color: '#94a3b8',
                fontSize: 11,
                cursor: 'pointer',
                display: 'inline-flex',
                alignItems: 'center',
                gap: 4,
              }}
            >
              {copied ? <Check size={12} color="#10b981" /> : <Copy size={12} />}
              {copied ? '已复制' : '复制日志'}
            </button>

            <button
              onClick={() => setLogs([])}
              disabled={running || logs.length === 0}
              style={{
                border: 'none',
                background: 'transparent',
                color: '#94a3b8',
                fontSize: 11,
                cursor: 'pointer',
                display: 'inline-flex',
                alignItems: 'center',
                gap: 4,
              }}
            >
              <Trash2 size={12} /> 清屏
            </button>
          </div>
        </div>

        {/* 黑色控制台输出主体 */}
        <div
          ref={terminalRef}
          style={{
            flex: 1,
            background: '#090d16',
            color: '#e2e8f0',
            fontFamily: 'Consolas, Monaco, "Courier New", monospace',
            fontSize: 12,
            lineHeight: 1.6,
            padding: '12px 16px',
            overflowY: 'auto',
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-all',
          }}
        >
          {logs.length === 0 ? (
            <div style={{ color: '#475569', fontStyle: 'italic', padding: '20px 0' }}>
              点击右上角「开始运行」按钮按照脚本内容启动场景，运行期间可随时手动停止。
            </div>
          ) : (
            logs.map((line, idx) => {
              let color = '#cbd5e1';
              if (line.includes('[ERROR]') || line.includes('Err:') || line.includes('Exception')) {
                color = '#f87171';
              } else if (line.includes('[WARN]') || line.includes('🛑') || line.includes('⏹') || line.includes('手动停止')) {
                color = '#fbbf24';
              } else if (line.includes('✅') || line.includes('成功完成') || line.includes('completed')) {
                color = '#4ade80';
              } else if (line.includes('🚀') || line.includes('启动') || line.includes('====================')) {
                color = '#38bdf8';
              } else if (line.includes('summary =') || line.includes('summary +')) {
                color = '#a78bfa';
              }

              return (
                <div key={idx} style={{ color }}>
                  {line}
                </div>
              );
            })
          )}
        </div>

        {/* 运行完成汇总卡片 */}
        {runSummary && (
          <div
            style={{
              padding: '12px 20px',
              background: 'var(--bg-card)',
              borderTop: '1px solid var(--border)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 16,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 20 }}>
              <div style={{ fontSize: 12 }}>
                <span style={{ color: 'var(--text-muted)' }}>样本总数: </span>
                <strong style={{ color: 'var(--text-primary)' }}>{runSummary.total_samples || 0}</strong>
              </div>
              <div style={{ fontSize: 12 }}>
                <span style={{ color: 'var(--text-muted)' }}>错误率: </span>
                <strong style={{ color: (runSummary.error_rate || 0) > 0 ? '#ef4444' : '#10b981' }}>
                  {runSummary.error_rate || 0}%
                </strong>
              </div>
              <div style={{ fontSize: 12 }}>
                <span style={{ color: 'var(--text-muted)' }}>平均耗时: </span>
                <strong style={{ color: 'var(--text-primary)' }}>{runSummary.avg_rt_ms || 0} ms</strong>
              </div>
              <div style={{ fontSize: 12 }}>
                <span style={{ color: 'var(--text-muted)' }}>TPS: </span>
                <strong style={{ color: 'var(--accent)' }}>{runSummary.avg_tps || 0}</strong>
              </div>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                执行记录已收录至「执行记录」Tab
              </span>
              <button
                onClick={onClose}
                style={{
                  padding: '6px 14px',
                  borderRadius: 6,
                  border: '1px solid var(--border)',
                  background: 'var(--bg-base)',
                  color: 'var(--text-primary)',
                  fontSize: 12,
                  cursor: 'pointer',
                }}
              >
                关闭
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
