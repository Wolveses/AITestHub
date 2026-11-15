import React, { useState, useEffect } from 'react';
import {
  FileSpreadsheet,
  Layers,
  Terminal,
  FileCode,
  CheckCircle2,
  XCircle,
  Copy,
  Download,
  Check,
  Search,
  ChevronDown,
  ChevronRight,
} from 'lucide-react';

interface JtlReportModalProps {
  isOpen: boolean;
  onClose: () => void;
  runId: number | null;
  scriptName?: string;
}

export const JtlReportModal: React.FC<JtlReportModalProps> = ({
  isOpen,
  onClose,
  runId,
  scriptName,
}) => {
  const [loading, setLoading] = useState<boolean>(true);
  const [report, setReport] = useState<any>(null);
  const [activeTab, setActiveTab] = useState<'aggregate' | 'samples' | 'raw_jtl' | 'console'>('aggregate');

  // 明细过滤与分页
  const [filterSuccess, setFilterSuccess] = useState<'all' | 'success' | 'failed'>('all');
  const [searchLabel, setSearchLabel] = useState<string>('');
  const [expandedRowIdx, setExpandedRowIdx] = useState<string | null>(null);
  const [expandedTxKeys, setExpandedTxKeys] = useState<Record<string, boolean>>({});

  const [copiedJtl, setCopiedJtl] = useState<boolean>(false);
  const [copiedLog, setCopiedLog] = useState<boolean>(false);

  useEffect(() => {
    if (isOpen && runId) {
      loadReport(runId);
    } else {
      setReport(null);
    }
  }, [isOpen, runId]);

  // 当 report 加载完成时，默认展开所有事务节点
  useEffect(() => {
    if (report?.jtl_tree) {
      const initialMap: Record<string, boolean> = {};
      report.jtl_tree.forEach((item: any, idx: number) => {
        if (item.is_transaction && item.children && item.children.length > 0) {
          initialMap[`tx_${idx}`] = true;
        }
      });
      setExpandedTxKeys(initialMap);
    }
  }, [report]);

  const toggleTx = (key: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setExpandedTxKeys((prev) => ({
      ...prev,
      [key]: !prev[key],
    }));
  };

  const loadReport = async (id: number) => {
    setLoading(true);
    try {
      const res = await fetch(`/api/modules/performance/server/runs/${id}`);
      if (res.ok) {
        const data = await res.json();

        // 兼容处理：若服务端未预存 jtl_tree，或打开的是老执行历史，则前端自动根据 JTL 规则动态构建树
        if (!data.jtl_tree || data.jtl_tree.length === 0) {
          const rows: any[] = data.jtl_rows || [];
          const txRegex = /Number of samples in transaction\s*:\s*(\d+)/i;
          const tree: any[] = [];
          const threadBuffers: Record<string, any[]> = {};

          rows.forEach((s) => {
            const url = (s.URL || '').trim().toLowerCase();
            const rm = s.responseMessage || '';
            const matchTx = txRegex.exec(rm);
            const isTx = s.is_transaction ?? ((!url || url === 'null') || matchTx !== null);
            const childCount = matchTx ? parseInt(matchTx[1], 10) : (s.tx_child_count || 0);
            const tName = s.threadName || 'default';

            const itemNode = {
              ...s,
              is_transaction: isTx,
              tx_child_count: childCount,
              children: [],
            };

            if (!isTx) {
              if (!threadBuffers[tName]) threadBuffers[tName] = [];
              threadBuffers[tName].push(itemNode);
            } else {
              const buf = threadBuffers[tName] || [];
              if (childCount > 0 && buf.length >= childCount) {
                itemNode.children = buf.splice(-childCount, childCount);
              } else {
                itemNode.children = [...buf];
                threadBuffers[tName] = [];
              }
              tree.push(itemNode);
            }
          });

          // 把未归属事务的独立采样平铺加入
          Object.values(threadBuffers).forEach((remaining) => {
            remaining.forEach((r) => tree.push(r));
          });

          data.jtl_tree = tree;
        }

        // 聚合报表中兼容补齐 is_transaction 标记
        if (data.sampler_summary && Array.isArray(data.sampler_summary)) {
          const txLabelSet = new Set<string>();
          (data.jtl_tree || []).forEach((n: any) => {
            if (n.is_transaction && n.label) txLabelSet.add(n.label);
          });
          data.sampler_summary = data.sampler_summary.map((row: any) => ({
            ...row,
            is_transaction: row.is_transaction ?? txLabelSet.has(row.label),
          }));
        }

        setReport(data);
      }
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  };

  if (!isOpen || !runId) return null;

  const handleCopyJtl = () => {
    if (!report?.jtl_content) return;
    navigator.clipboard.writeText(report.jtl_content);
    setCopiedJtl(true);
    setTimeout(() => setCopiedJtl(false), 2000);
  };

  const handleDownloadJtl = () => {
    if (!report?.jtl_content) return;
    const blob = new Blob([report.jtl_content], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.setAttribute('download', `run_${runId}_result.jtl`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const handleCopyLog = () => {
    if (!report?.console_output) return;
    navigator.clipboard.writeText(report.console_output);
    setCopiedLog(true);
    setTimeout(() => setCopiedLog(false), 2000);
  };

  // 过滤后的样本列表与树形结构
  const rawRows: any[] = report?.jtl_rows || [];
  const rawTree: any[] = report?.jtl_tree || [];

  // 判断节点自身是否命中过滤
  const checkItemMatch = (row: any) => {
    if (filterSuccess === 'success' && !row.success) return false;
    if (filterSuccess === 'failed' && row.success) return false;
    if (searchLabel.trim()) {
      const q = searchLabel.toLowerCase();
      const matchLabel = (row.label || '').toLowerCase().includes(q);
      const matchCode = String(row.responseCode || '').includes(q);
      const matchUrl = (row.URL || '').toLowerCase().includes(q);
      if (!matchLabel && !matchCode && !matchUrl) return false;
    }
    return true;
  };

  // 过滤树形结构：如果主节点命中，或者其任一子节点命中，则保留
  const filteredTree = rawTree
    .map((node: any) => {
      const children = (node.children || []).filter(checkItemMatch);
      const selfMatch = checkItemMatch(node);
      if (selfMatch || children.length > 0) {
        return {
          ...node,
          filteredChildren: children,
        };
      }
      return null;
    })
    .filter(Boolean);

  const filteredSamples = rawRows.filter(checkItemMatch);

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
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        style={{
          width: '94%',
          maxWidth: 1100,
          height: '88vh',
          maxHeight: 860,
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
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <div
              style={{
                width: 32,
                height: 32,
                borderRadius: 8,
                background: 'rgba(59, 130, 246, 0.1)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: 'var(--accent)',
              }}
            >
              <FileSpreadsheet size={18} />
            </div>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 16, fontWeight: 600, color: 'var(--text-primary)' }}>
                  结构化报表
                </span>
                <span
                  style={{
                    fontSize: 11,
                    fontFamily: 'monospace',
                    padding: '2px 8px',
                    borderRadius: 12,
                    background: 'var(--bg-base)',
                    color: 'var(--accent)',
                    border: '1px solid var(--border)',
                  }}
                >
                  #RUN-{runId}
                </span>
                {report && (
                  <span
                    style={{
                      fontSize: 11,
                      padding: '2px 8px',
                      borderRadius: 12,
                      background:
                        report.status === 'completed'
                          ? 'rgba(16, 185, 129, 0.1)'
                          : report.status === 'stopped'
                          ? 'rgba(245, 158, 11, 0.1)'
                          : report.status === 'failed'
                          ? 'rgba(239, 68, 68, 0.1)'
                          : 'rgba(59, 130, 246, 0.1)',
                      color:
                        report.status === 'completed'
                          ? '#10b981'
                          : report.status === 'stopped'
                          ? '#f59e0b'
                          : report.status === 'failed'
                          ? '#ef4444'
                          : 'var(--accent)',
                    }}
                  >
                    {report.status === 'completed'
                      ? '已完成'
                      : report.status === 'stopped'
                      ? '已停止'
                      : report.status === 'failed'
                      ? '执行异常'
                      : '运行中'}
                  </span>
                )}
              </div>
              <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>
                场景: {scriptName || `ID ${report?.script_id || ''}`} · 引擎: {report?.engine_used || 'jmeter_cli'} · 执行时间: {report ? new Date(report.started_at).toLocaleString() : ''}
              </div>
            </div>
          </div>

          <button
            onClick={onClose}
            style={{
              border: 'none',
              background: 'transparent',
              color: 'var(--text-muted)',
              fontSize: 18,
              cursor: 'pointer',
              padding: '4px 8px',
              borderRadius: 4,
            }}
          >
            ✕
          </button>
        </div>

        {loading ? (
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)' }}>
            正在加载 JTL 结构化数据...
          </div>
        ) : !report ? (
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)' }}>
            未找到该执行记录的数据
          </div>
        ) : (
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
            {/* KPI 指标卡片行 */}
            <div
              style={{
                padding: '12px 20px',
                background: 'var(--bg-base)',
                borderBottom: '1px solid var(--border)',
                display: 'grid',
                gridTemplateColumns: 'repeat(6, 1fr)',
                gap: 12,
              }}
            >
              <div style={{ background: 'var(--bg-card)', padding: '10px 12px', borderRadius: 8, border: '1px solid var(--border)' }}>
                <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>样本总数</div>
                <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--text-primary)', marginTop: 2 }}>
                  {report.total_samples || 0}
                </div>
              </div>

              <div style={{ background: 'var(--bg-card)', padding: '10px 12px', borderRadius: 8, border: '1px solid var(--border)' }}>
                <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>错误率 (Fail%)</div>
                <div
                  style={{
                    fontSize: 18,
                    fontWeight: 700,
                    color: (report.error_rate || 0) > 0 ? '#ef4444' : '#10b981',
                    marginTop: 2,
                  }}
                >
                  {report.error_rate || 0}%
                  <span style={{ fontSize: 11, fontWeight: 400, color: 'var(--text-muted)', marginLeft: 4 }}>
                    ({report.failed_samples || 0} 失败)
                  </span>
                </div>
              </div>

              <div style={{ background: 'var(--bg-card)', padding: '10px 12px', borderRadius: 8, border: '1px solid var(--border)' }}>
                <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>平均响应时间</div>
                <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--text-primary)', marginTop: 2 }}>
                  {report.avg_rt_ms || 0} <span style={{ fontSize: 11, fontWeight: 400, color: 'var(--text-muted)' }}>ms</span>
                </div>
              </div>

              <div style={{ background: 'var(--bg-card)', padding: '10px 12px', borderRadius: 8, border: '1px solid var(--border)' }}>
                <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>90% 分位线 (P90)</div>
                <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--text-primary)', marginTop: 2 }}>
                  {report.p90_rt_ms || 0} <span style={{ fontSize: 11, fontWeight: 400, color: 'var(--text-muted)' }}>ms</span>
                </div>
              </div>

              <div style={{ background: 'var(--bg-card)', padding: '10px 12px', borderRadius: 8, border: '1px solid var(--border)' }}>
                <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>95% 分位线 (P95)</div>
                <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--text-primary)', marginTop: 2 }}>
                  {report.p95_rt_ms || 0} <span style={{ fontSize: 11, fontWeight: 400, color: 'var(--text-muted)' }}>ms</span>
                </div>
              </div>

              <div style={{ background: 'var(--bg-card)', padding: '10px 12px', borderRadius: 8, border: '1px solid var(--border)' }}>
                <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>平均吞吐量 (TPS)</div>
                <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--accent)', marginTop: 2 }}>
                  {report.avg_tps || 0} <span style={{ fontSize: 11, fontWeight: 400, color: 'var(--text-muted)' }}>req/s</span>
                </div>
              </div>
            </div>

            {/* 子 Tab 切换栏 */}
            <div
              style={{
                padding: '0 20px',
                background: 'var(--bg-card)',
                borderBottom: '1px solid var(--border)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
              }}
            >
              <div style={{ display: 'flex', gap: 20 }}>
                <button
                  onClick={() => setActiveTab('aggregate')}
                  style={{
                    padding: '11px 4px',
                    border: 'none',
                    background: 'transparent',
                    borderBottom: activeTab === 'aggregate' ? '2px solid var(--accent)' : '2px solid transparent',
                    color: activeTab === 'aggregate' ? 'var(--accent)' : 'var(--text-secondary)',
                    fontWeight: activeTab === 'aggregate' ? 600 : 400,
                    fontSize: 13,
                    cursor: 'pointer',
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 6,
                  }}
                >
                  <Layers size={14} /> 聚合报表
                </button>

                <button
                  onClick={() => setActiveTab('samples')}
                  style={{
                    padding: '11px 4px',
                    border: 'none',
                    background: 'transparent',
                    borderBottom: activeTab === 'samples' ? '2px solid var(--accent)' : '2px solid transparent',
                    color: activeTab === 'samples' ? 'var(--accent)' : 'var(--text-secondary)',
                    fontWeight: activeTab === 'samples' ? 600 : 400,
                    fontSize: 13,
                    cursor: 'pointer',
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 6,
                  }}
                >
                  <FileSpreadsheet size={14} /> 采样明细 ({rawRows.length})
                </button>

                <button
                  onClick={() => setActiveTab('raw_jtl')}
                  style={{
                    padding: '11px 4px',
                    border: 'none',
                    background: 'transparent',
                    borderBottom: activeTab === 'raw_jtl' ? '2px solid var(--accent)' : '2px solid transparent',
                    color: activeTab === 'raw_jtl' ? 'var(--accent)' : 'var(--text-secondary)',
                    fontWeight: activeTab === 'raw_jtl' ? 600 : 400,
                    fontSize: 13,
                    cursor: 'pointer',
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 6,
                  }}
                >
                  <FileCode size={14} /> JTL 原文
                </button>

                <button
                  onClick={() => setActiveTab('console')}
                  style={{
                    padding: '11px 4px',
                    border: 'none',
                    background: 'transparent',
                    borderBottom: activeTab === 'console' ? '2px solid var(--accent)' : '2px solid transparent',
                    color: activeTab === 'console' ? 'var(--accent)' : 'var(--text-secondary)',
                    fontWeight: activeTab === 'console' ? 600 : 400,
                    fontSize: 13,
                    cursor: 'pointer',
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 6,
                  }}
                >
                  <Terminal size={14} /> 控制台日志
                </button>
              </div>

              {activeTab === 'raw_jtl' && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <button
                    onClick={handleCopyJtl}
                    style={{
                      padding: '4px 10px',
                      borderRadius: 4,
                      border: '1px solid var(--border)',
                      background: 'var(--bg-base)',
                      color: 'var(--text-primary)',
                      fontSize: 11,
                      cursor: 'pointer',
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: 4,
                    }}
                  >
                    {copiedJtl ? <Check size={12} color="#10b981" /> : <Copy size={12} />}
                    {copiedJtl ? '已复制' : '复制 JTL'}
                  </button>
                  <button
                    onClick={handleDownloadJtl}
                    style={{
                      padding: '4px 10px',
                      borderRadius: 4,
                      border: '1px solid var(--border)',
                      background: 'var(--bg-base)',
                      color: 'var(--accent)',
                      fontSize: 11,
                      fontWeight: 500,
                      cursor: 'pointer',
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: 4,
                    }}
                  >
                    <Download size={12} /> 下载 .jtl
                  </button>
                </div>
              )}

              {activeTab === 'console' && (
                <button
                  onClick={handleCopyLog}
                  style={{
                    padding: '4px 10px',
                    borderRadius: 4,
                    border: '1px solid var(--border)',
                    background: 'var(--bg-base)',
                    color: 'var(--text-primary)',
                    fontSize: 11,
                    cursor: 'pointer',
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 4,
                  }}
                >
                  {copiedLog ? <Check size={12} color="#10b981" /> : <Copy size={12} />}
                  {copiedLog ? '已复制' : '复制日志'}
                </button>
              )}
            </div>

            {/* Tab 1: 聚合报表 */}
            {activeTab === 'aggregate' && (
              <div style={{ flex: 1, overflowY: 'auto', padding: 20 }}>
                {(!report.sampler_summary || report.sampler_summary.length === 0) ? (
                  <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
                    该次执行未包含聚合报表数据
                  </div>
                ) : (
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12, textAlign: 'left' }}>
                    <thead>
                      <tr style={{ background: 'var(--bg-base)', borderBottom: '1px solid var(--border)', color: 'var(--text-muted)' }}>
                        <th style={{ padding: '8px 12px' }}>Sampler 接口名称</th>
                        <th style={{ padding: '8px 12px' }}>样本数</th>
                        <th style={{ padding: '8px 12px' }}>失败数</th>
                        <th style={{ padding: '8px 12px' }}>错误率</th>
                        <th style={{ padding: '8px 12px' }}>平均耗时 (ms)</th>
                        <th style={{ padding: '8px 12px' }}>最小 (ms)</th>
                        <th style={{ padding: '8px 12px' }}>最大 (ms)</th>
                        <th style={{ padding: '8px 12px' }}>90% Line</th>
                        <th style={{ padding: '8px 12px' }}>95% Line</th>
                        <th style={{ padding: '8px 12px' }}>TPS</th>
                      </tr>
                    </thead>
                    <tbody>
                      {report.sampler_summary.map((row: any, i: number) => (
                        <tr
                          key={i}
                          style={{
                            borderBottom: '1px solid var(--border)',
                            background: i % 2 === 0 ? 'transparent' : 'rgba(0,0,0,0.02)',
                          }}
                        >
                          <td style={{ padding: '10px 12px', fontWeight: 600, color: 'var(--text-primary)' }}>
                            <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                              {row.is_transaction ? (
                                <span
                                  style={{
                                    fontSize: 10,
                                    padding: '1px 6px',
                                    borderRadius: 4,
                                    background: 'rgba(168, 85, 247, 0.1)',
                                    color: '#a855f7',
                                    fontWeight: 600,
                                    border: '1px solid rgba(168, 85, 247, 0.25)',
                                  }}
                                >
                                  事务
                                </span>
                              ) : (
                                <span
                                  style={{
                                    fontSize: 10,
                                    padding: '1px 6px',
                                    borderRadius: 4,
                                    background: 'rgba(59, 130, 246, 0.08)',
                                    color: '#3b82f6',
                                    fontWeight: 500,
                                    border: '1px solid rgba(59, 130, 246, 0.2)',
                                  }}
                                >
                                  接口
                                </span>
                              )}
                              <span>{row.label}</span>
                            </div>
                          </td>
                          <td style={{ padding: '10px 12px' }}>{row.samples}</td>
                          <td style={{ padding: '10px 12px', color: row.failed > 0 ? '#ef4444' : 'inherit' }}>
                            {row.failed}
                          </td>
                          <td style={{ padding: '10px 12px', color: row.error_rate > 0 ? '#ef4444' : '#10b981', fontWeight: 600 }}>
                            {row.error_rate}%
                          </td>
                          <td style={{ padding: '10px 12px', fontWeight: 600 }}>{row.avg_rt}</td>
                          <td style={{ padding: '10px 12px', color: 'var(--text-muted)' }}>{row.min_rt}</td>
                          <td style={{ padding: '10px 12px', color: 'var(--text-muted)' }}>{row.max_rt}</td>
                          <td style={{ padding: '10px 12px' }}>{row.p90_rt}</td>
                          <td style={{ padding: '10px 12px' }}>{row.p95_rt}</td>
                          <td style={{ padding: '10px 12px', color: 'var(--accent)', fontWeight: 600 }}>{row.tps}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            )}

            {/* Tab 2: JTL 结构化样本流水 */}
            {activeTab === 'samples' && (
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
                {/* 过滤搜索条 */}
                <div
                  style={{
                    padding: '10px 20px',
                    background: 'var(--bg-base)',
                    borderBottom: '1px solid var(--border)',
                    display: 'flex',
                    alignItems: 'center',
                    gap: 16,
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
                    <span style={{ color: 'var(--text-muted)' }}>状态筛选:</span>
                    <div style={{ display: 'flex', border: '1px solid var(--border)', borderRadius: 6, overflow: 'hidden' }}>
                      <button
                        onClick={() => setFilterSuccess('all')}
                        style={{
                          padding: '3px 10px',
                          border: 'none',
                          background: filterSuccess === 'all' ? 'var(--accent)' : 'var(--bg-card)',
                          color: filterSuccess === 'all' ? '#fff' : 'var(--text-primary)',
                          fontSize: 11,
                          cursor: 'pointer',
                        }}
                      >
                        全部 ({rawRows.length})
                      </button>
                      <button
                        onClick={() => setFilterSuccess('success')}
                        style={{
                          padding: '3px 10px',
                          border: 'none',
                          background: filterSuccess === 'success' ? '#10b981' : 'var(--bg-card)',
                          color: filterSuccess === 'success' ? '#fff' : 'var(--text-primary)',
                          fontSize: 11,
                          cursor: 'pointer',
                        }}
                      >
                        成功
                      </button>
                      <button
                        onClick={() => setFilterSuccess('failed')}
                        style={{
                          padding: '3px 10px',
                          border: 'none',
                          background: filterSuccess === 'failed' ? '#ef4444' : 'var(--bg-card)',
                          color: filterSuccess === 'failed' ? '#fff' : 'var(--text-primary)',
                          fontSize: 11,
                          cursor: 'pointer',
                        }}
                      >
                        失败
                      </button>
                    </div>
                  </div>

                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, flex: 1, maxWidth: 300 }}>
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 6,
                        background: 'var(--bg-card)',
                        border: '1px solid var(--border)',
                        borderRadius: 6,
                        padding: '3px 8px',
                        width: '100%',
                      }}
                    >
                      <Search size={13} color="var(--text-muted)" />
                      <input
                        type="text"
                        placeholder="检索 Sampler / URL / 状态码..."
                        value={searchLabel}
                        onChange={(e) => setSearchLabel(e.target.value)}
                        style={{
                          border: 'none',
                          background: 'transparent',
                          color: 'var(--text-primary)',
                          fontSize: 11,
                          outline: 'none',
                          width: '100%',
                        }}
                      />
                    </div>
                  </div>

                  <span style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 'auto' }}>
                    展示记录: <strong>{filteredTree.length > 0 ? filteredTree.length : filteredSamples.length}</strong> 项 (共 {rawRows.length} 条原始采样)
                  </span>
                </div>

                {/* 样本流水表格（支持事务主子树形展开与独立接口平铺） */}
                <div style={{ flex: 1, overflowY: 'auto' }}>
                  {filteredTree.length === 0 && filteredSamples.length === 0 ? (
                    <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
                      无匹配的采样记录
                    </div>
                  ) : (
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12, textAlign: 'left' }}>
                      <thead>
                        <tr style={{ background: 'var(--bg-base)', borderBottom: '1px solid var(--border)', color: 'var(--text-muted)' }}>
                          <th style={{ width: 44, padding: '8px 12px' }}>#</th>
                          <th style={{ padding: '8px 12px' }}>类型 / Sampler 名称</th>
                          <th style={{ padding: '8px 12px' }}>状态码</th>
                          <th style={{ padding: '8px 12px' }}>结果</th>
                          <th style={{ padding: '8px 12px' }}>耗时 (ms)</th>
                          <th style={{ padding: '8px 12px' }}>线程名</th>
                          <th style={{ padding: '8px 12px' }}>数据大小</th>
                          <th style={{ width: 36, padding: '8px 12px' }}></th>
                        </tr>
                      </thead>
                      <tbody>
                        {(filteredTree.length > 0 ? filteredTree : filteredSamples).map((node: any, idx: number) => {
                          const hasChildren = node.is_transaction && node.filteredChildren && node.filteredChildren.length > 0;
                          const txKey = `tx_${idx}`;
                          const isTxOpen = expandedTxKeys[txKey] !== false; // 默认展开
                          const isDetailOpen = expandedRowIdx === `main_${idx}`;

                          return (
                            <React.Fragment key={`main_${idx}`}>
                              {/* 主节点行（事务控制器 或 独立平铺接口） */}
                              <tr
                                onClick={() => {
                                  if (hasChildren) {
                                    toggleTx(txKey, { stopPropagation: () => {} } as any);
                                  } else {
                                    setExpandedRowIdx(isDetailOpen ? null : `main_${idx}`);
                                  }
                                }}
                                style={{
                                  borderBottom: '1px solid var(--border)',
                                  background: node.is_transaction
                                    ? 'rgba(168, 85, 247, 0.04)'
                                    : isDetailOpen
                                    ? 'rgba(59, 130, 246, 0.05)'
                                    : idx % 2 === 0
                                    ? 'transparent'
                                    : 'rgba(0,0,0,0.015)',
                                  cursor: 'pointer',
                                }}
                              >
                                <td style={{ padding: '9px 12px', color: 'var(--text-muted)', fontSize: 11 }}>
                                  {idx + 1}
                                </td>
                                <td style={{ padding: '9px 12px', fontWeight: 600, color: 'var(--text-primary)' }}>
                                  <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                                    {hasChildren && (
                                      <span
                                        onClick={(e) => toggleTx(txKey, e)}
                                        style={{
                                          display: 'inline-flex',
                                          alignItems: 'center',
                                          justifyContent: 'center',
                                          width: 18,
                                          height: 18,
                                          borderRadius: 4,
                                          background: 'rgba(168, 85, 247, 0.12)',
                                          color: '#a855f7',
                                          cursor: 'pointer',
                                        }}
                                        title={isTxOpen ? '收起子采样' : '展开子采样'}
                                      >
                                        {isTxOpen ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                                      </span>
                                    )}

                                    {node.is_transaction ? (
                                      <span
                                        style={{
                                          fontSize: 10,
                                          padding: '1px 6px',
                                          borderRadius: 4,
                                          background: 'rgba(168, 85, 247, 0.12)',
                                          color: '#9333ea',
                                          fontWeight: 600,
                                          border: '1px solid rgba(168, 85, 247, 0.25)',
                                        }}
                                      >
                                        事务
                                      </span>
                                    ) : (
                                      <span
                                        style={{
                                          fontSize: 10,
                                          padding: '1px 6px',
                                          borderRadius: 4,
                                          background: 'rgba(59, 130, 246, 0.08)',
                                          color: '#3b82f6',
                                          fontWeight: 500,
                                          border: '1px solid rgba(59, 130, 246, 0.2)',
                                        }}
                                      >
                                        接口
                                      </span>
                                    )}

                                    <span>{node.label}</span>
                                    {hasChildren && (
                                      <span style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 400 }}>
                                        ({node.filteredChildren.length} 个子请求)
                                      </span>
                                    )}
                                  </div>
                                </td>
                                <td style={{ padding: '9px 12px', fontFamily: 'monospace' }}>
                                  <span
                                    style={{
                                      padding: '1px 6px',
                                      borderRadius: 4,
                                      background: String(node.responseCode).startsWith('2')
                                        ? 'rgba(16, 185, 129, 0.1)'
                                        : node.responseCode
                                        ? 'rgba(239, 68, 68, 0.1)'
                                        : 'rgba(156, 163, 175, 0.1)',
                                      color: String(node.responseCode).startsWith('2')
                                        ? '#10b981'
                                        : node.responseCode
                                        ? '#ef4444'
                                        : 'var(--text-muted)',
                                      fontSize: 11,
                                    }}
                                  >
                                    {node.responseCode || (node.is_transaction ? 'TX' : '--')}
                                  </span>
                                </td>
                                <td style={{ padding: '9px 12px' }}>
                                  {node.success ? (
                                    <span style={{ color: '#10b981', display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11 }}>
                                      <CheckCircle2 size={13} /> Success
                                    </span>
                                  ) : (
                                    <span style={{ color: '#ef4444', display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11 }}>
                                      <XCircle size={13} /> Failed
                                    </span>
                                  )}
                                </td>
                                <td style={{ padding: '9px 12px', fontWeight: 600 }}>
                                  {node.elapsed} ms
                                </td>
                                <td style={{ padding: '9px 12px', color: 'var(--text-muted)', fontSize: 11 }}>
                                  {node.threadName}
                                </td>
                                <td style={{ padding: '9px 12px', color: 'var(--text-muted)', fontSize: 11 }}>
                                  {node.bytes} B
                                </td>
                                <td
                                  style={{ padding: '9px 12px', textAlign: 'center', color: 'var(--text-muted)' }}
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    setExpandedRowIdx(isDetailOpen ? null : `main_${idx}`);
                                  }}
                                  title="查看采样详情"
                                >
                                  {isDetailOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                                </td>
                              </tr>

                              {/* 主节点参数明细展开 */}
                              {isDetailOpen && (
                                <tr style={{ background: 'var(--bg-base)', borderBottom: '1px solid var(--border)' }}>
                                  <td colSpan={8} style={{ padding: '12px 16px 12px 36px' }}>
                                    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: 12 }}>
                                      <div>
                                        <strong style={{ color: 'var(--text-muted)' }}>URL / 目标: </strong>
                                        <span style={{ fontFamily: 'monospace', color: 'var(--accent)' }}>
                                          {node.URL || (node.is_transaction ? '事务控制器封装 (聚合子节点网络流)' : '无')}
                                        </span>
                                      </div>
                                      {node.responseMessage && (
                                        <div>
                                          <strong style={{ color: 'var(--text-muted)' }}>响应信息: </strong>
                                          <span>{node.responseMessage}</span>
                                        </div>
                                      )}
                                      {node.failureMessage && (
                                        <div style={{ color: '#ef4444' }}>
                                          <strong>失败断言/异常信息: </strong>
                                          <span>{node.failureMessage}</span>
                                        </div>
                                      )}
                                      <div style={{ display: 'flex', gap: 20, fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>
                                        <span>时间戳: {node.timeStamp}</span>
                                        <span>等待延时 (Latency): {node.latency} ms</span>
                                      </div>
                                    </div>
                                  </td>
                                </tr>
                              )}

                              {/* 子采样列表（事务内部步骤层级展示） */}
                              {hasChildren &&
                                isTxOpen &&
                                node.filteredChildren.map((child: any, cIdx: number) => {
                                  const childDetailKey = `child_${idx}_${cIdx}`;
                                  const isChildDetailOpen = expandedRowIdx === childDetailKey;

                                  return (
                                    <React.Fragment key={childDetailKey}>
                                      <tr
                                        onClick={() => setExpandedRowIdx(isChildDetailOpen ? null : childDetailKey)}
                                        style={{
                                          borderBottom: '1px solid var(--border)',
                                          background: isChildDetailOpen
                                            ? 'rgba(59, 130, 246, 0.05)'
                                            : 'rgba(0,0,0,0.01)',
                                          cursor: 'pointer',
                                        }}
                                      >
                                        <td style={{ padding: '8px 12px 8px 24px', color: 'var(--text-muted)', fontSize: 11 }}>
                                          {idx + 1}.{cIdx + 1}
                                        </td>
                                        <td style={{ padding: '8px 12px' }}>
                                          <div style={{ display: 'flex', alignItems: 'center', gap: 6, paddingLeft: 22 }}>
                                            <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>└─</span>
                                            <span
                                              style={{
                                                fontSize: 10,
                                                padding: '1px 5px',
                                                borderRadius: 4,
                                                background: 'rgba(59, 130, 246, 0.08)',
                                                color: '#3b82f6',
                                                border: '1px solid rgba(59, 130, 246, 0.2)',
                                              }}
                                            >
                                              子请求
                                            </span>
                                            <span style={{ fontWeight: 500, color: 'var(--text-primary)' }}>
                                              {child.label}
                                            </span>
                                          </div>
                                        </td>
                                        <td style={{ padding: '8px 12px', fontFamily: 'monospace' }}>
                                          <span
                                            style={{
                                              padding: '1px 6px',
                                              borderRadius: 4,
                                              background: String(child.responseCode).startsWith('2')
                                                ? 'rgba(16, 185, 129, 0.1)'
                                                : 'rgba(239, 68, 68, 0.1)',
                                              color: String(child.responseCode).startsWith('2') ? '#10b981' : '#ef4444',
                                              fontSize: 11,
                                            }}
                                          >
                                            {child.responseCode || '--'}
                                          </span>
                                        </td>
                                        <td style={{ padding: '8px 12px' }}>
                                          {child.success ? (
                                            <span style={{ color: '#10b981', display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11 }}>
                                              <CheckCircle2 size={12} /> Success
                                            </span>
                                          ) : (
                                            <span style={{ color: '#ef4444', display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11 }}>
                                              <XCircle size={12} /> Failed
                                            </span>
                                          )}
                                        </td>
                                        <td style={{ padding: '8px 12px', fontWeight: 500 }}>
                                          {child.elapsed} ms
                                        </td>
                                        <td style={{ padding: '8px 12px', color: 'var(--text-muted)', fontSize: 11 }}>
                                          {child.threadName}
                                        </td>
                                        <td style={{ padding: '8px 12px', color: 'var(--text-muted)', fontSize: 11 }}>
                                          {child.bytes} B
                                        </td>
                                        <td
                                          style={{ padding: '8px 12px', textAlign: 'center', color: 'var(--text-muted)' }}
                                          onClick={(e) => {
                                            e.stopPropagation();
                                            setExpandedRowIdx(isChildDetailOpen ? null : childDetailKey);
                                          }}
                                        >
                                          {isChildDetailOpen ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                                        </td>
                                      </tr>

                                      {/* 子请求明细展开 */}
                                      {isChildDetailOpen && (
                                        <tr style={{ background: 'var(--bg-base)', borderBottom: '1px solid var(--border)' }}>
                                          <td colSpan={8} style={{ padding: '12px 16px 12px 56px' }}>
                                            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: 12 }}>
                                              <div>
                                                <strong style={{ color: 'var(--text-muted)' }}>URL: </strong>
                                                <span style={{ fontFamily: 'monospace', color: 'var(--accent)' }}>
                                                  {child.URL || '无'}
                                                </span>
                                              </div>
                                              {child.responseMessage && (
                                                <div>
                                                  <strong style={{ color: 'var(--text-muted)' }}>响应信息: </strong>
                                                  <span>{child.responseMessage}</span>
                                                </div>
                                              )}
                                              {child.failureMessage && (
                                                <div style={{ color: '#ef4444' }}>
                                                  <strong>失败断言/异常信息: </strong>
                                                  <span>{child.failureMessage}</span>
                                                </div>
                                              )}
                                              <div style={{ display: 'flex', gap: 20, fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>
                                                <span>时间戳: {child.timeStamp}</span>
                                                <span>等待延时 (Latency): {child.latency} ms</span>
                                              </div>
                                            </div>
                                          </td>
                                        </tr>
                                      )}
                                    </React.Fragment>
                                  );
                                })}
                            </React.Fragment>
                          );
                        })}
                      </tbody>
                    </table>
                  )}
                </div>
              </div>
            )}

            {/* Tab 3: JTL 原文 CSV */}
            {activeTab === 'raw_jtl' && (
              <div style={{ flex: 1, padding: 16, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
                <pre
                  style={{
                    flex: 1,
                    margin: 0,
                    background: '#090d16',
                    color: '#e2e8f0',
                    fontFamily: 'Consolas, Monaco, monospace',
                    fontSize: 12,
                    lineHeight: 1.5,
                    padding: 16,
                    borderRadius: 8,
                    overflow: 'auto',
                    border: '1px solid #1e293b',
                  }}
                >
                  {report.jtl_content || '暂无 JTL 原文内容'}
                </pre>
              </div>
            )}

            {/* Tab 4: 控制台日志 */}
            {activeTab === 'console' && (
              <div style={{ flex: 1, padding: 16, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
                <pre
                  style={{
                    flex: 1,
                    margin: 0,
                    background: '#090d16',
                    color: '#38bdf8',
                    fontFamily: 'Consolas, Monaco, monospace',
                    fontSize: 12,
                    lineHeight: 1.6,
                    padding: 16,
                    borderRadius: 8,
                    overflow: 'auto',
                    border: '1px solid #1e293b',
                  }}
                >
                  {report.console_output || '暂无执行控制台输出日志'}
                </pre>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};
