import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { StopCircle, ArrowLeft } from 'lucide-react';
import type { PerfRunItem } from '../../store/serverPerfStore';

export function PerfReportModal({
  runId,
  onClose,
}: {
  runId: number | null;
  onClose: () => void;
}) {
  const [report, setReport] = useState<PerfRunItem | null>(null);

  const fetchReport = async () => {
    if (!runId) return;
    try {
      const res = await fetch(`/api/modules/performance/server/runs/${runId}`);
      const data = await res.json();
      setReport(data);
    } catch (err: any) {
      toast.error('获取执行报告失败');
    }
  };

  useEffect(() => {
    fetchReport();
    if (!runId) return;
    // 如果是运行中，启动轮询
    const timer = setInterval(() => {
      fetchReport();
    }, 2000);
    return () => clearInterval(timer);
  }, [runId]);

  const handleStop = async () => {
    if (!runId) return;
    try {
      await fetch(`/api/modules/performance/server/runs/${runId}/stop`, { method: 'POST' });
      toast.success('已发送停止压测指令');
      fetchReport();
    } catch (err: any) {
      toast.error('停止失败');
    }
  };

  if (!runId) return null;

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 120,
        background: 'rgba(0,0,0,0.65)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 24,
      }}
    >
      <div
        style={{
          width: '90%',
          maxWidth: 1000,
          maxHeight: '90vh',
          background: 'var(--bg-card)',
          borderRadius: 8,
          border: '1px solid var(--border)',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          boxShadow: '0 12px 32px rgba(0,0,0,0.5)',
        }}
      >
        {/* Header */}
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
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <button
              onClick={onClose}
              style={{
                background: 'transparent',
                border: 'none',
                color: 'var(--text-secondary)',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
              }}
            >
              <ArrowLeft size={16} />
            </button>
            <strong style={{ fontSize: 15 }}>性能测试执行报告 (Run #{runId})</strong>
            <span
              style={{
                fontSize: 11,
                padding: '2px 8px',
                borderRadius: 4,
                fontWeight: 600,
                background:
                  report?.status === 'running'
                    ? 'rgba(59,130,246,0.1)'
                    : report?.status === 'completed'
                    ? 'rgba(16,185,129,0.1)'
                    : 'var(--bg-base)',
                color:
                  report?.status === 'running'
                    ? 'var(--accent)'
                    : report?.status === 'completed'
                    ? '#10b981'
                    : '#ef4444',
              }}
            >
              {report?.status || '加载中...'}
            </span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            {report?.status === 'running' && (
              <button
                onClick={handleStop}
                style={{
                  padding: '5px 12px',
                  borderRadius: 4,
                  border: 'none',
                  background: '#ef4444',
                  color: '#fff',
                  fontSize: 12,
                  fontWeight: 600,
                  cursor: 'pointer',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 4,
                }}
              >
                <StopCircle size={14} /> 停止压测
              </button>
            )}
            <button
              onClick={onClose}
              style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}
            >
              ✕
            </button>
          </div>
        </div>

        {/* Content */}
        <div style={{ flex: 1, overflowY: 'auto', padding: 20, display: 'flex', flexDirection: 'column', gap: 16 }}>
          {/* KPI 核心仪表盘 */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 12 }}>
            <div style={{ padding: 12, borderRadius: 6, background: 'var(--bg-base)', border: '1px solid var(--border)' }}>
              <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>平均 TPS</div>
              <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--accent)', marginTop: 4 }}>
                {report?.avg_tps || 0}
              </div>
            </div>
            <div style={{ padding: 12, borderRadius: 6, background: 'var(--bg-base)', border: '1px solid var(--border)' }}>
              <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>平均响应时间 (ms)</div>
              <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text-primary)', marginTop: 4 }}>
                {report?.avg_rt_ms || 0}
              </div>
            </div>
            <div style={{ padding: 12, borderRadius: 6, background: 'var(--bg-base)', border: '1px solid var(--border)' }}>
              <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>P95 响应耗时 (ms)</div>
              <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text-primary)', marginTop: 4 }}>
                {report?.p95_rt_ms || 0}
              </div>
            </div>
            <div style={{ padding: 12, borderRadius: 6, background: 'var(--bg-base)', border: '1px solid var(--border)' }}>
              <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>总样本数 (Samples)</div>
              <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text-primary)', marginTop: 4 }}>
                {report?.total_samples || 0}
              </div>
            </div>
            <div style={{ padding: 12, borderRadius: 6, background: 'var(--bg-base)', border: '1px solid var(--border)' }}>
              <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>错误率 (%)</div>
              <div
                style={{
                  fontSize: 20,
                  fontWeight: 700,
                  color: (report?.error_rate || 0) > 0 ? '#ef4444' : '#10b981',
                  marginTop: 4,
                }}
              >
                {report?.error_rate || 0}%
              </div>
            </div>
          </div>

          {/* 实时/历史时序指标流 */}
          {report?.timeline_metrics && report.timeline_metrics.length > 0 && (
            <div style={{ padding: 14, borderRadius: 6, background: 'var(--bg-base)', border: '1px solid var(--border)' }}>
              <strong style={{ fontSize: 13, marginBottom: 8, display: 'block' }}>实时时序流采样 (最近采样切片)</strong>
              <div style={{ display: 'flex', gap: 8, overflowX: 'auto', paddingBottom: 6 }}>
                {report.timeline_metrics.slice(-12).map((tm: any, tmidx: number) => (
                  <div
                    key={tmidx}
                    style={{
                      flexShrink: 0,
                      padding: '6px 10px',
                      borderRadius: 4,
                      background: 'var(--bg-card)',
                      border: '1px solid var(--border)',
                      fontSize: 11,
                      minWidth: 100,
                    }}
                  >
                    <div style={{ color: 'var(--text-muted)' }}>+{tm.elapsed_sec}s</div>
                    <div style={{ fontWeight: 600, color: 'var(--accent)' }}>TPS: {tm.tps}</div>
                    <div style={{ color: 'var(--text-secondary)' }}>RT: {tm.avg_rt}ms</div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* 各 Sampler 统计明细 */}
          <div>
            <strong style={{ fontSize: 13, marginBottom: 8, display: 'block' }}>各接口聚合性能矩阵 (Sampler Summary)</strong>
            <div style={{ border: '1px solid var(--border)', borderRadius: 6, overflow: 'hidden' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: 12 }}>
                <thead>
                  <tr style={{ background: 'var(--bg-base)', borderBottom: '1px solid var(--border)', color: 'var(--text-muted)' }}>
                    <th style={{ padding: '8px 12px' }}>Sampler 名称</th>
                    <th style={{ padding: '8px 10px' }}>样本数</th>
                    <th style={{ padding: '8px 10px' }}>失败数</th>
                    <th style={{ padding: '8px 10px' }}>错误率</th>
                    <th style={{ padding: '8px 10px' }}>TPS</th>
                    <th style={{ padding: '8px 10px' }}>平均耗时</th>
                    <th style={{ padding: '8px 10px' }}>最小耗时</th>
                    <th style={{ padding: '8px 10px' }}>最大耗时</th>
                    <th style={{ padding: '8px 10px' }}>P95 耗时</th>
                  </tr>
                </thead>
                <tbody>
                  {(report?.sampler_summary || []).map((sm: any, smidx: number) => (
                    <tr key={smidx} style={{ borderBottom: '1px solid var(--border)' }}>
                      <td style={{ padding: '8px 12px', fontWeight: 500 }}>{sm.sampler_name}</td>
                      <td style={{ padding: '8px 10px' }}>{sm.samples}</td>
                      <td style={{ padding: '8px 10px', color: sm.failed > 0 ? '#ef4444' : 'inherit' }}>{sm.failed}</td>
                      <td style={{ padding: '8px 10px', color: sm.failed > 0 ? '#ef4444' : 'inherit' }}>{sm.error_rate}</td>
                      <td style={{ padding: '8px 10px', color: 'var(--accent)' }}>{sm.tps}</td>
                      <td style={{ padding: '8px 10px' }}>{sm.avg_rt_ms}ms</td>
                      <td style={{ padding: '8px 10px' }}>{sm.min_rt_ms}ms</td>
                      <td style={{ padding: '8px 10px' }}>{sm.max_rt_ms}ms</td>
                      <td style={{ padding: '8px 10px', fontWeight: 600 }}>{sm.p95_rt_ms}ms</td>
                    </tr>
                  ))}
                  {(!report?.sampler_summary || report.sampler_summary.length === 0) && (
                    <tr>
                      <td colSpan={9} style={{ padding: 24, textAlign: 'center', color: 'var(--text-muted)' }}>
                        暂无接口聚合样本
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
