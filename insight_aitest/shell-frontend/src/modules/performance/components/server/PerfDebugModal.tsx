import { useState } from 'react';
import { toast } from 'sonner';
import { Play, X, CheckCircle2, AlertTriangle, ChevronDown, ChevronUp, Loader2 } from 'lucide-react';
import type { PerfScriptItem } from '../../store/serverPerfStore';

interface PerfDebugModalProps {
  open: boolean;
  onClose: () => void;
  script: PerfScriptItem & { jmx_content?: string };
}

export function PerfDebugModal({ open, onClose, script }: PerfDebugModalProps) {
  const [baseUrl, setBaseUrl] = useState('http://127.0.0.1:8001');
  const [globalVarsText, setGlobalVarsText] = useState('{\n  "zoneId": "default"\n}');
  const [debugging, setDebugging] = useState(false);
  const [debugResult, setDebugResult] = useState<any | null>(null);
  const [expandedResponses, setExpandedResponses] = useState<Record<number, boolean>>({});

  if (!open) return null;

  const handleRunDebug = async () => {
    if (!script.jmx_content) {
      toast.error('当前脚本暂无 JMX 源码内容，无法调试');
      return;
    }

    let globalVars = {};
    if (globalVarsText.trim()) {
      try {
        globalVars = JSON.parse(globalVarsText);
      } catch (e: any) {
        toast.error(`全局变量 JSON 格式错误: ${e.message}`);
        return;
      }
    }

    setDebugging(true);
    setDebugResult(null);

    try {
      const res = await fetch('/api/modules/performance/server/scripts/debug', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          jmx_content: script.jmx_content,
          base_url: baseUrl.trim(),
          global_vars: globalVars,
        }),
      });

      const ret = await res.json();
      if (!res.ok) throw new Error(ret.detail || '调试失败');

      setDebugResult(ret.data);
      if (ret.data.all_passed) {
        toast.success(`沙箱单步调试通过，共执行 ${ret.data.steps?.length || 0} 个接口`);
      } else {
        toast.warning('部分接口响应异常或断言失败，请检查调试结果');
      }
    } catch (err: any) {
      toast.error(err.message || '调试执行失败');
    } finally {
      setDebugging(false);
    }
  };

  const toggleResponse = (idx: number) => {
    setExpandedResponses((prev) => ({ ...prev, [idx]: !prev[idx] }));
  };

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 120,
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
          maxWidth: 920,
          maxHeight: '90vh',
          background: 'var(--bg-card)',
          borderRadius: 8,
          border: '1px solid var(--border)',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          boxShadow: '0 20px 25px -5px rgba(0,0,0,0.3)',
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
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Play size={18} color="#10b981" />
            <strong style={{ fontSize: 15 }}>脚本沙箱调试 - {script.name}</strong>
          </div>
          <button
            onClick={onClose}
            style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', padding: 4 }}
          >
            <X size={18} />
          </button>
        </div>

        {/* Content */}
        <div style={{ flex: 1, overflowY: 'auto', padding: 20, display: 'flex', flexDirection: 'column', gap: 16 }}>
          {/* 参数配置栏 */}
          <div
            style={{
              padding: 14,
              border: '1px solid var(--border)',
              borderRadius: 8,
              background: 'var(--bg-base)',
              display: 'flex',
              flexDirection: 'column',
              gap: 12,
            }}
          >
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
              <div>
                <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 6 }}>
                  环境 Base URL (统一前缀 / 网关地址)
                </label>
                <input
                  type="text"
                  value={baseUrl}
                  onChange={(e) => setBaseUrl(e.target.value)}
                  placeholder="例如：http://127.0.0.1:8001 或 http://192.168.1.100:8080"
                  style={{
                    width: '100%',
                    padding: '7px 10px',
                    borderRadius: 6,
                    border: '1px solid var(--border)',
                    background: 'var(--bg-card)',
                    color: 'var(--text-primary)',
                    fontSize: 12,
                    fontFamily: 'monospace',
                    outline: 'none',
                  }}
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 6 }}>
                  初始全局变量 (JSON 键值对)
                </label>
                <textarea
                  rows={2}
                  value={globalVarsText}
                  onChange={(e) => setGlobalVarsText(e.target.value)}
                  placeholder='{"token": "xxx", "userId": 1}'
                  style={{
                    width: '100%',
                    padding: '6px 10px',
                    borderRadius: 6,
                    border: '1px solid var(--border)',
                    background: 'var(--bg-card)',
                    color: 'var(--text-primary)',
                    fontSize: 11,
                    fontFamily: 'monospace',
                    outline: 'none',
                    resize: 'none',
                  }}
                />
              </div>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', paddingTop: 4 }}>
              <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                将按顺序单步执行脚本中的 HTTP Sampler，沙箱支持动态上下文变量提取传递与状态码断言校验
              </span>

              <button
                onClick={handleRunDebug}
                disabled={debugging}
                style={{
                  padding: '6px 16px',
                  borderRadius: 6,
                  border: 'none',
                  background: '#10b981',
                  color: '#fff',
                  fontSize: 12,
                  fontWeight: 600,
                  cursor: debugging ? 'not-allowed' : 'pointer',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 6,
                }}
              >
                {debugging ? <Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} /> : <Play size={13} />}
                {debugging ? '正在沙箱执行中...' : '开始单步调试'}
              </button>
            </div>
          </div>

          {/* 调试结果展示区 */}
          {debugResult && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {/* 总览横幅 */}
              <div
                style={{
                  padding: '12px 16px',
                  borderRadius: 8,
                  border: `1px solid ${debugResult.all_passed ? '#10b981' : '#f59e0b'}`,
                  background: debugResult.all_passed
                    ? 'rgba(16, 185, 129, 0.08)'
                    : 'rgba(245, 158, 11, 0.08)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  {debugResult.all_passed ? (
                    <CheckCircle2 size={20} color="#10b981" />
                  ) : (
                    <AlertTriangle size={20} color="#f59e0b" />
                  )}
                  <div>
                    <strong style={{ fontSize: 13, color: debugResult.all_passed ? '#10b981' : '#f59e0b' }}>
                      {debugResult.all_passed ? '调试全部通过 (All Passed)' : '调试部分步骤未通过或响应异常'}
                    </strong>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
                      共执行 {debugResult.steps?.length || 0} 个接口 · 总耗时 {debugResult.total_time_ms} ms
                    </div>
                  </div>
                </div>

                {debugResult.context_vars && Object.keys(debugResult.context_vars).length > 0 && (
                  <div style={{ fontSize: 11, color: 'var(--text-secondary)', textAlign: 'right' }}>
                    提取变量总数: <strong>{Object.keys(debugResult.context_vars).length}</strong>
                  </div>
                )}
              </div>

              {/* 步骤卡片列表 */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {debugResult.steps?.map((step: any, idx: number) => {
                  const passed = step.passed !== false && !step.error;
                  const isExp = !!expandedResponses[idx];

                  return (
                    <div
                      key={idx}
                      style={{
                        border: '1px solid var(--border)',
                        borderRadius: 6,
                        background: 'var(--bg-card)',
                        padding: 12,
                        display: 'flex',
                        flexDirection: 'column',
                        gap: 8,
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                          <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)' }}>#{idx + 1}</span>
                          <span
                            style={{
                              fontSize: 10,
                              fontWeight: 700,
                              padding: '1px 6px',
                              borderRadius: 4,
                              background: 'var(--bg-base)',
                              border: '1px solid var(--border)',
                            }}
                          >
                            {step.method}
                          </span>
                          <strong style={{ fontSize: 13 }}>{step.step_name}</strong>
                          <span style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'monospace' }}>
                            {step.url}
                          </span>
                        </div>

                        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                          <span
                            style={{
                              fontSize: 11,
                              fontWeight: 600,
                              padding: '2px 8px',
                              borderRadius: 4,
                              background: passed ? 'rgba(16, 185, 129, 0.1)' : 'rgba(239, 68, 68, 0.1)',
                              color: passed ? '#10b981' : '#ef4444',
                              border: `1px solid ${passed ? 'rgba(16, 185, 129, 0.3)' : 'rgba(239, 68, 68, 0.3)'}`,
                            }}
                          >
                            {step.status_code ? `Status ${step.status_code}` : '请求失败'}
                          </span>
                          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{step.elapsed_ms} ms</span>
                        </div>
                      </div>

                      {/* 报错信息 */}
                      {step.error && (
                        <div style={{ background: 'rgba(239, 68, 68, 0.08)', color: '#ef4444', padding: '6px 10px', borderRadius: 4, fontSize: 11 }}>
                          错误: {step.error}
                        </div>
                      )}

                      {/* 变量提取结果 */}
                      {step.extracted_vars && Object.keys(step.extracted_vars).length > 0 && (
                        <div style={{ background: 'var(--bg-base)', padding: '5px 8px', borderRadius: 4, fontSize: 11, display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                          <span style={{ color: 'var(--accent)', fontWeight: 600 }}>提取变量:</span>
                          {Object.entries(step.extracted_vars).map(([k, v]) => (
                            <span key={k} style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', padding: '1px 6px', borderRadius: 4, fontFamily: 'monospace' }}>
                              ${`{${k}}`} = {String(v)}
                            </span>
                          ))}
                        </div>
                      )}

                      {/* 断言校验结果 */}
                      {step.assert_results && step.assert_results.length > 0 && (
                        <div style={{ background: 'var(--bg-base)', padding: '5px 8px', borderRadius: 4, fontSize: 11, display: 'flex', alignItems: 'center', gap: 8 }}>
                          <span style={{ color: '#10b981', fontWeight: 600 }}>断言:</span>
                          {step.assert_results.map((ass: any, i: number) => (
                            <span
                              key={i}
                              style={{
                                color: ass.passed ? '#10b981' : '#ef4444',
                                background: 'var(--bg-card)',
                                border: '1px solid var(--border)',
                                padding: '1px 6px',
                                borderRadius: 4,
                              }}
                            >
                              期望 {ass.expected} / 实际 {ass.actual} {ass.passed ? '✓' : '✗'}
                            </span>
                          ))}
                        </div>
                      )}

                      {/* 响应文本查看 */}
                      {step.response_preview && (
                        <div>
                          <button
                            onClick={() => toggleResponse(idx)}
                            style={{
                              border: 'none',
                              background: 'transparent',
                              color: 'var(--text-muted)',
                              cursor: 'pointer',
                              fontSize: 11,
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: 2,
                              padding: 0,
                            }}
                          >
                            {isExp ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
                            {isExp ? '收起响应体' : '查看响应体 Preview'}
                          </button>

                          {isExp && (
                            <pre
                              style={{
                                margin: '6px 0 0',
                                padding: 8,
                                background: 'var(--bg-base)',
                                borderRadius: 4,
                                fontSize: 11,
                                fontFamily: 'monospace',
                                maxHeight: 160,
                                overflow: 'auto',
                                color: 'var(--text-secondary)',
                                whiteSpace: 'pre-wrap',
                                wordBreak: 'break-all',
                              }}
                            >
                              {step.response_preview}
                            </pre>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div
          style={{
            padding: '12px 20px',
            borderTop: '1px solid var(--border)',
            background: 'var(--bg-base)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'flex-end',
          }}
        >
          <button
            onClick={onClose}
            style={{
              padding: '6px 14px',
              borderRadius: 6,
              border: '1px solid var(--border)',
              background: 'var(--bg-card)',
              color: 'var(--text-primary)',
              fontSize: 13,
              cursor: 'pointer',
            }}
          >
            关闭
          </button>
        </div>
      </div>
    </div>
  );
}
