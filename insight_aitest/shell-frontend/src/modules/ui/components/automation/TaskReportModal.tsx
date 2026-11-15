import { Fragment, useEffect, useState } from 'react';
import { toast } from 'sonner';
import { X, CheckCircle2, XCircle, FileText, ChevronDown, ChevronRight, RefreshCw } from 'lucide-react';
import { Btn } from './common';
import { artifactUrl, ImagePreviewOverlay, LogViewer, type ArtifactPreview } from './RunArtifacts';
import { useTaskStore } from '../../store/taskStore';

interface TaskReportModalProps {
  open: boolean;
  onClose: () => void;
  runId: number | null;
}

const BASE = '/api/modules/ui/automation';
const linkButtonStyle: React.CSSProperties = {
  background: 'none',
  border: 'none',
  padding: 0,
  cursor: 'pointer',
  font: 'inherit',
  color: 'var(--accent)',
  fontSize: 11,
};

export function TaskReportModal({ open, onClose, runId }: TaskReportModalProps) {
  const { currentReport, loadingReport, loadTaskReport } = useTaskStore();
  const [expandedErrors, setExpandedErrors] = useState<Record<number, boolean>>({});
  const [openRunLog, setOpenRunLog] = useState<number | null>(null);
  const [preview, setPreview] = useState<ArtifactPreview | null>(null);

  useEffect(() => {
    if (open && runId) {
      setExpandedErrors({});
      setOpenRunLog(null);
      setPreview(null);
      loadTaskReport(runId).catch((err) => {
        toast.error(err.message || '加载测试报告失败');
      });
    }
  }, [open, runId, loadTaskReport]);

  if (!open || !runId) return null;

  const toggleExpand = (caseId: number) => {
    setExpandedErrors((prev) => ({ ...prev, [caseId]: !prev[caseId] }));
  };

  const run = currentReport?.run;
  const summary = currentReport?.summary || [];
  const total = run?.total_cases ?? 0;
  const passed = run?.passed_cases ?? 0;
  const failed = run?.failed_cases ?? 0;
  // 执行中总用例数含未开始用例，通过率按已完成用例计算，避免显示成 1/7=14%
  const completed = passed + failed;
  const passRate = completed > 0 ? Math.round((passed / completed) * 100) : null;
  const durationSec = ((run?.duration_ms ?? 0) / 1000).toFixed(1);

  return (
    <>
      <div
        onClick={onClose}
        style={{
          position: 'fixed',
          inset: 0,
          background: 'rgba(0,0,0,.6)',
          zIndex: 1100,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: 820,
          maxWidth: '92vw',
          maxHeight: '88vh',
          background: 'var(--bg-card)',
          border: '1px solid var(--border)',
          borderRadius: 10,
          display: 'flex',
          flexDirection: 'column',
          boxShadow: '0 16px 40px rgba(0,0,0,.5)',
          overflow: 'hidden',
        }}
      >
        {/* Header */}
        <div
          style={{
            padding: '16px 20px',
            borderBottom: '1px solid var(--border)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            background: 'var(--bg-card)',
          }}
        >
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <FileText size={18} style={{ color: 'var(--accent)' }} />
              <strong style={{ fontSize: 16, color: 'var(--text-primary)' }}>
                UI 自动化任务测试报告
              </strong>
              <span
                style={{
                  fontSize: 11,
                  padding: '2px 8px',
                  borderRadius: 999,
                  fontWeight: 600,
                  color: run?.status === 'passed' ? 'var(--success, #10b981)' : 'var(--error, #ef4444)',
                  background: run?.status === 'passed' ? 'rgba(16,185,129,0.12)' : 'rgba(239,68,68,0.12)',
                  border: `1px solid ${run?.status === 'passed' ? 'var(--success, #10b981)' : 'var(--error, #ef4444)'}`,
                }}
              >
                {run?.status === 'passed' ? '全部通过' : run?.status === 'running' ? '执行中' : '执行未通过'}
              </span>
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>
              任务：{currentReport?.task_name} | 执行批次 #{runId} | 环境：{currentReport?.env_name} |{' '}
              {run?.trigger_type === 'cron' ? '定时调度触发' : '手动触发'}
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            {/* 批次执行中报告是增量数据，提供手动刷新拉取最新已完成用例 */}
            <Btn
              size="sm"
              onClick={() => runId && loadTaskReport(runId).catch(() => {})}
              disabled={loadingReport}
              title="刷新报告"
            >
              <RefreshCw size={13} style={{ animation: loadingReport ? 'spin 1s linear infinite' : 'none' }} />
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

        {/* Content */}
        <div style={{ flex: 1, overflowY: 'auto', padding: 20, display: 'flex', flexDirection: 'column', gap: 18 }}>
          {loadingReport && !currentReport ? (
            <div style={{ padding: 60, textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
              加载测试报告中...
            </div>
          ) : (
            <>
              {/* Summary Cards */}
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))',
                  gap: 12,
                }}
              >
                <div
                  style={{
                    padding: '12px 14px',
                    borderRadius: 8,
                    background: 'var(--bg-base)',
                    border: '1px solid var(--border)',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 4,
                  }}
                >
                  <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>总用例数</span>
                  <span style={{ fontSize: 20, fontWeight: 700, color: 'var(--text-primary)' }}>
                    {total}
                  </span>
                </div>

                <div
                  style={{
                    padding: '12px 14px',
                    borderRadius: 8,
                    background: 'var(--bg-base)',
                    border: '1px solid var(--border)',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 4,
                  }}
                >
                  <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>通过用例</span>
                  <span style={{ fontSize: 20, fontWeight: 700, color: 'var(--success, #10b981)' }}>
                    {passed}
                  </span>
                </div>

                <div
                  style={{
                    padding: '12px 14px',
                    borderRadius: 8,
                    background: 'var(--bg-base)',
                    border: '1px solid var(--border)',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 4,
                  }}
                >
                  <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>失败用例</span>
                  <span
                    style={{
                      fontSize: 20,
                      fontWeight: 700,
                      color: failed > 0 ? 'var(--error, #ef4444)' : 'var(--text-muted)',
                    }}
                  >
                    {failed}
                  </span>
                </div>

                <div
                  style={{
                    padding: '12px 14px',
                    borderRadius: 8,
                    background: 'var(--bg-base)',
                    border: '1px solid var(--border)',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 4,
                  }}
                >
                  <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>用例通过率</span>
                  <span
                    style={{
                      fontSize: 20,
                      fontWeight: 700,
                      color:
                        passRate === null
                          ? 'var(--text-muted)'
                          : passRate === 100
                            ? 'var(--success, #10b981)'
                            : passRate > 80
                              ? 'var(--warning, #f59e0b)'
                              : 'var(--error, #ef4444)',
                    }}
                  >
                    {passRate === null ? '—' : `${passRate}%`}
                  </span>
                  <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>
                    已完成 {completed} / {total}
                  </span>
                </div>

                <div
                  style={{
                    padding: '12px 14px',
                    borderRadius: 8,
                    background: 'var(--bg-base)',
                    border: '1px solid var(--border)',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 4,
                  }}
                >
                  <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>执行总耗时</span>
                  <span style={{ fontSize: 20, fontWeight: 700, color: 'var(--text-primary)' }}>
                    {durationSec}s
                  </span>
                </div>
              </div>

              {/* Detail Table */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <strong style={{ fontSize: 14, color: 'var(--text-primary)' }}>用例执行明细</strong>
                <div
                  style={{
                    border: '1px solid var(--border)',
                    borderRadius: 8,
                    overflow: 'hidden',
                    background: 'var(--bg-base)',
                  }}
                >
                  <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: 12 }}>
                    <thead>
                      <tr
                        style={{
                          background: 'var(--bg-card)',
                          borderBottom: '1px solid var(--border)',
                          color: 'var(--text-muted)',
                        }}
                      >
                        <th style={{ padding: '8px 12px', width: 40 }}>#</th>
                        <th style={{ padding: '8px 12px' }}>用例名称</th>
                        <th style={{ padding: '8px 12px', width: 60 }}>端</th>
                        <th style={{ padding: '8px 12px', width: 100 }}>所属模块</th>
                        <th style={{ padding: '8px 12px', width: 80 }}>状态</th>
                        <th style={{ padding: '8px 12px', width: 80 }}>耗时</th>
                        <th style={{ padding: '8px 12px', width: 60 }}>详情</th>
                        <th style={{ padding: '8px 12px', width: 150 }}>产物</th>
                      </tr>
                    </thead>
                    <tbody>
                      {summary.length === 0 ? (
                        <tr>
                          <td colSpan={8} style={{ padding: 24, textAlign: 'center', color: 'var(--text-muted)' }}>
                            暂无用例明细数据
                          </td>
                        </tr>
                      ) : (
                        summary.map((item, idx) => {
                          const isPassed = item.status === 'passed';
                          const isExpanded = !!expandedErrors[item.case_id];
                          // 产物按钮全部以本次执行的 ui_runs 记录为准，没有记录时不展示
                          const subRunId = item.run_id;

                          return (
                            <Fragment key={item.case_id}>
                              <tr
                                style={{
                                  borderBottom: '1px solid var(--border-subtle, rgba(255,255,255,0.05))',
                                  background: isPassed ? 'transparent' : 'rgba(239,68,68,0.03)',
                                }}
                              >
                                <td style={{ padding: '8px 12px', color: 'var(--text-muted)' }}>{idx + 1}</td>
                                <td style={{ padding: '8px 12px', fontWeight: 500, color: 'var(--text-primary)' }}>
                                  {item.title}
                                </td>
                                <td style={{ padding: '8px 12px', color: 'var(--text-muted)' }}>
                                  {item.site === 'backend' ? '后台' : '前台'}
                                </td>
                                <td style={{ padding: '8px 12px', color: 'var(--text-muted)' }}>
                                  {item.category || '未分类'}
                                </td>
                                <td style={{ padding: '8px 12px' }}>
                                  <span
                                    style={{
                                      display: 'inline-flex',
                                      alignItems: 'center',
                                      gap: 4,
                                      padding: '1px 6px',
                                      borderRadius: 4,
                                      fontSize: 11,
                                      fontWeight: 600,
                                      color: isPassed ? 'var(--success, #10b981)' : 'var(--error, #ef4444)',
                                      background: isPassed ? 'rgba(16,185,129,0.1)' : 'rgba(239,68,68,0.1)',
                                    }}
                                  >
                                    {isPassed ? <CheckCircle2 size={12} /> : <XCircle size={12} />}
                                    {isPassed ? '通过' : '失败'}
                                  </span>
                                </td>
                                <td style={{ padding: '8px 12px', color: 'var(--text-muted)' }}>
                                  {(item.duration_ms / 1000).toFixed(1)}s
                                </td>
                                <td style={{ padding: '8px 12px' }}>
                                  {item.error ? (
                                    <button
                                      onClick={() => toggleExpand(item.case_id)}
                                      style={{
                                        background: 'transparent',
                                        border: 'none',
                                        color: 'var(--error, #ef4444)',
                                        cursor: 'pointer',
                                        display: 'inline-flex',
                                        alignItems: 'center',
                                        gap: 2,
                                        fontSize: 11,
                                        padding: 0,
                                      }}
                                    >
                                      {isExpanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                                      错误
                                    </button>
                                  ) : (
                                    <span style={{ color: 'var(--text-muted)' }}>-</span>
                                  )}
                                </td>
                                <td style={{ padding: '8px 12px' }}>
                                  {subRunId ? (
                                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                                      <button
                                        type="button"
                                        style={linkButtonStyle}
                                        onClick={() => setOpenRunLog(openRunLog === subRunId ? null : subRunId)}
                                      >
                                        日志
                                      </button>
                                      {item.has_final && (
                                        <button
                                          type="button"
                                          style={linkButtonStyle}
                                          onClick={() =>
                                            setPreview({
                                              url: artifactUrl(item.case_id, subRunId, 'final.png'),
                                              label: `终态截图 · #${subRunId}`,
                                            })
                                          }
                                        >
                                          终态截图
                                        </button>
                                      )}
                                      {item.has_failure && (
                                        <button
                                          type="button"
                                          style={linkButtonStyle}
                                          onClick={() =>
                                            setPreview({
                                              url: artifactUrl(item.case_id, subRunId, 'failure.png'),
                                              label: `失败截图 · #${subRunId}`,
                                            })
                                          }
                                        >
                                          失败截图
                                        </button>
                                      )}
                                      {item.trace_rel_path && (
                                        <a href={artifactUrl(item.case_id, subRunId, 'trace.zip')} style={linkButtonStyle}>
                                          Trace
                                        </a>
                                      )}
                                    </div>
                                  ) : (
                                    <span style={{ color: 'var(--text-muted)' }}>-</span>
                                  )}
                                </td>
                              </tr>
                              {isExpanded && item.error && (
                                <tr style={{ background: 'rgba(239,68,68,0.06)' }}>
                                  <td colSpan={8} style={{ padding: '8px 16px 12px 16px' }}>
                                    <div
                                      style={{
                                        fontSize: 11,
                                        fontFamily: 'monospace',
                                        color: 'var(--error, #ef4444)',
                                        background: 'rgba(0,0,0,0.25)',
                                        padding: 8,
                                        borderRadius: 6,
                                        maxHeight: 160,
                                        overflowY: 'auto',
                                        whiteSpace: 'pre-wrap',
                                        wordBreak: 'break-all',
                                      }}
                                    >
                                      {item.error}
                                    </div>
                                  </td>
                                </tr>
                              )}
                              {subRunId && openRunLog === subRunId && (
                                <tr>
                                  <td colSpan={8} style={{ padding: '0 16px 10px' }}>
                                    <LogViewer
                                      url={`${BASE}/cases/${item.case_id}/runs/${subRunId}/log`}
                                      live={run?.status === 'running'}
                                    />
                                  </td>
                                </tr>
                              )}
                            </Fragment>
                          );
                        })
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </>
          )}
        </div>

        {/* Footer */}
        <div
          style={{
            padding: '12px 20px',
            borderTop: '1px solid var(--border)',
            background: 'var(--bg-card)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'flex-end',
          }}
        >
          <Btn onClick={onClose}>关闭报告</Btn>
        </div>
      </div>
      </div>
      <ImagePreviewOverlay preview={preview} onClose={() => setPreview(null)} />
    </>
  );
}
