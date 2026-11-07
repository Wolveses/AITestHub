import { useState } from 'react';
import { toast } from 'sonner';
import { Sparkles, Loader2, Play, Check } from 'lucide-react';
import { useServerPerfStore } from '../../store/serverPerfStore';

interface PerfAIGenerateModalProps {
  open: boolean;
  onClose: () => void;
  projectId: number;
  onSuccess: () => void;
}

export function PerfAIGenerateModal({ open, onClose, projectId, onSuccess }: PerfAIGenerateModalProps) {
  const { loadScripts } = useServerPerfStore();
  const [planDesc, setPlanDesc] = useState('');
  const [concurrency, setConcurrency] = useState(10);
  const [rampUp, setRampUp] = useState(5);
  const [duration, setDuration] = useState(60);

  const [generating, setGenerating] = useState(false);
  const [generatedResult, setGeneratedResult] = useState<any | null>(null);

  const [scriptName, setScriptName] = useState('');
  const [scriptDesc, setScriptDesc] = useState('');

  const [saving, setSaving] = useState(false);
  const [debugging, setDebugging] = useState(false);
  const [debugResult, setDebugResult] = useState<any | null>(null);

  if (!open) return null;

  const handleGenerate = async () => {
    if (!planDesc.trim()) {
      toast.error('请输入性能测试方案描述');
      return;
    }
    setGenerating(true);
    setGeneratedResult(null);
    setDebugResult(null);
    try {
      const res = await fetch('/api/modules/performance/server/scripts/generate-from-plan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_id: projectId,
          plan_description: planDesc,
          concurrency,
          ramp_up: rampUp,
          duration,
        }),
      });
      const ret = await res.json();
      if (!res.ok) throw new Error(ret.detail || '生成失败');
      setGeneratedResult(ret.data);
      setScriptName(ret.data.name || 'JMeter压测脚本');
      setScriptDesc(ret.data.description || '');
      toast.success('AI 已挑选接口并生成 JMeter 脚本');
    } catch (err: any) {
      toast.error(err.message || '生成失败');
    } finally {
      setGenerating(false);
    }
  };

  const handleDebug = async () => {
    if (!generatedResult?.jmx_content) return;
    setDebugging(true);
    try {
      const res = await fetch('/api/modules/performance/server/scripts/debug', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          jmx_content: generatedResult.jmx_content,
          base_url: generatedResult.base_url || '',
        }),
      });
      const ret = await res.json();
      if (!res.ok) throw new Error(ret.detail || '调试执行失败');
      setDebugResult(ret.data);
      if (ret.data.all_passed) {
        toast.success('沙箱调试通过，所有接口连通且断言成功');
      } else {
        toast.warning('部分接口响应异常或断言失败，请检查调试日志');
      }
    } catch (err: any) {
      toast.error(err.message || '调试出错');
    } finally {
      setDebugging(false);
    }
  };

  const handleSave = async () => {
    if (!scriptName.trim()) {
      toast.error('请输入脚本名称');
      return;
    }
    setSaving(true);
    try {
      const res = await fetch('/api/modules/performance/server/scripts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_id: projectId,
          name: scriptName,
          description: scriptDesc,
          plan_description: planDesc,
          config: {
            steps: generatedResult.steps,
            concurrency: generatedResult.concurrency,
            ramp_up: generatedResult.ramp_up,
            duration: generatedResult.duration,
          },
          jmx_content: generatedResult.jmx_content,
          asset_ids: generatedResult.selected_asset_ids || [],
        }),
      });
      const ret = await res.json();
      if (!res.ok) throw new Error(ret.detail || '保存失败');
      toast.success('JMeter 脚本已成功入库');
      await loadScripts(projectId);
      onSuccess();
      onClose();
    } catch (err: any) {
      toast.error(err.message || '保存脚本失败');
    } finally {
      setSaving(false);
    }
  };

  return (
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
          maxWidth: 960,
          maxHeight: '90vh',
          background: 'var(--bg-card)',
          borderRadius: 8,
          border: '1px solid var(--border)',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          boxShadow: '0 12px 32px rgba(0,0,0,0.4)',
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
            <Sparkles size={18} style={{ color: 'var(--accent)' }} />
            <strong style={{ fontSize: 15, color: 'var(--text-primary)' }}>
              AI 智能生成 JMeter 性能测试脚本
            </strong>
          </div>
          <button
            onClick={onClose}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--text-muted)',
              fontSize: 18,
              cursor: 'pointer',
            }}
          >
            ✕
          </button>
        </div>

        {/* Body */}
        <div style={{ flex: 1, overflowY: 'auto', padding: 20, display: 'flex', flexDirection: 'column', gap: 16 }}>
          {/* Step 1: 输入方案与配置 */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <label style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>
              性能测试方案描述 <span style={{ color: 'var(--accent)' }}>*</span>
            </label>
            <textarea
              value={planDesc}
              onChange={(e) => setPlanDesc(e.target.value)}
              placeholder="例如：模拟大促高并发场景，用户先进行认证登录获取 Token，然后查询商品列表，最后提交订单，目标并发 30 线程..."
              rows={3}
              style={{
                width: '100%',
                padding: '10px 12px',
                borderRadius: 6,
                border: '1px solid var(--border)',
                background: 'var(--bg-base)',
                color: 'var(--text-primary)',
                fontSize: 13,
                outline: 'none',
              }}
            />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
            <div>
              <label style={{ fontSize: 12, color: 'var(--text-secondary)' }}>目标并发 (Threads)</label>
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
              <label style={{ fontSize: 12, color: 'var(--text-secondary)' }}>加压预热时间 (Ramp-up, 秒)</label>
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
              <label style={{ fontSize: 12, color: 'var(--text-secondary)' }}>持续运行时长 (Duration, 秒)</label>
              <input
                type="number"
                min={10}
                value={duration}
                onChange={(e) => setDuration(Number(e.target.value))}
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

          <div>
            <button
              onClick={handleGenerate}
              disabled={generating}
              style={{
                padding: '8px 16px',
                borderRadius: 6,
                border: 'none',
                background: 'var(--accent)',
                color: '#fff',
                fontSize: 13,
                fontWeight: 600,
                cursor: generating ? 'not-allowed' : 'pointer',
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
              }}
            >
              {generating ? <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} /> : <Sparkles size={14} />}
              {generating ? 'AI 正在分析资产并编排脚本...' : '从项目 API 资产库自动挑选并生成脚本'}
            </button>
          </div>

          {/* 生成结果预览与调试区 */}
          {generatedResult && (
            <div
              style={{
                marginTop: 8,
                padding: 16,
                border: '1px solid var(--border)',
                borderRadius: 8,
                background: 'var(--bg-base)',
                display: 'flex',
                flexDirection: 'column',
                gap: 12,
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>
                  ✅ 挑选完成：已识别 {generatedResult.steps?.length || 0} 个关键接口步骤
                </span>
                <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                  推荐理由：{generatedResult.reason}
                </span>
              </div>

              {/* 步骤列表 */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {generatedResult.steps?.map((step: any, idx: number) => (
                  <div
                    key={idx}
                    style={{
                      padding: '8px 12px',
                      borderRadius: 4,
                      background: 'var(--bg-card)',
                      border: '1px solid var(--border)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      fontSize: 12,
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span
                        style={{
                          fontWeight: 700,
                          color: step.method === 'POST' ? '#f59e0b' : '#3b82f6',
                        }}
                      >
                        {step.method}
                      </span>
                      <span style={{ color: 'var(--text-primary)', fontWeight: 500 }}>{step.name}</span>
                      <code style={{ color: 'var(--text-muted)', fontSize: 11 }}>{step.path}</code>
                    </div>
                    {step.extract && Object.keys(step.extract).length > 0 && (
                      <span style={{ fontSize: 11, color: 'var(--accent)', background: 'rgba(59,130,246,0.1)', padding: '2px 6px', borderRadius: 4 }}>
                        提取变量: {Object.keys(step.extract).join(', ')}
                      </span>
                    )}
                  </div>
                ))}
              </div>

              {/* 调试按钮与回显 */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 4 }}>
                <button
                  onClick={handleDebug}
                  disabled={debugging}
                  style={{
                    padding: '6px 14px',
                    borderRadius: 4,
                    border: '1px solid var(--border)',
                    background: 'var(--bg-card)',
                    color: 'var(--text-primary)',
                    fontSize: 12,
                    cursor: debugging ? 'not-allowed' : 'pointer',
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 6,
                  }}
                >
                  {debugging ? <Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} /> : <Play size={13} />}
                  单步沙箱调试 (验证连通性与变量提取)
                </button>
              </div>

              {debugResult && (
                <div style={{ fontSize: 12, padding: 10, borderRadius: 6, background: 'var(--bg-card)', border: '1px solid var(--border)' }}>
                  <div style={{ marginBottom: 6, fontWeight: 600, color: debugResult.all_passed ? 'var(--success, #10b981)' : '#ef4444' }}>
                    调试耗时: {debugResult.total_time_ms}ms · 提取变量: {JSON.stringify(debugResult.context_vars)}
                  </div>
                  {debugResult.steps?.map((ds: any, didx: number) => (
                    <div key={didx} style={{ padding: '4px 0', borderBottom: '1px dashed var(--border)', display: 'flex', justifyContent: 'space-between' }}>
                      <span>{ds.name}</span>
                      <span>状态码: {ds.status_code} ({ds.elapsed_ms}ms)</span>
                    </div>
                  ))}
                </div>
              )}

              {/* 脚本命名与保存 */}
              <div style={{ borderTop: '1px solid var(--border)', paddingTop: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
                <div>
                  <label style={{ fontSize: 12, color: 'var(--text-secondary)' }}>入库脚本名称</label>
                  <input
                    type="text"
                    value={scriptName}
                    onChange={(e) => setScriptName(e.target.value)}
                    style={{
                      width: '100%',
                      height: 32,
                      marginTop: 4,
                      padding: '0 8px',
                      borderRadius: 4,
                      border: '1px solid var(--border)',
                      background: 'var(--bg-card)',
                      color: 'var(--text-primary)',
                    }}
                  />
                </div>
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
            gap: 10,
          }}
        >
          <button
            onClick={onClose}
            style={{
              padding: '6px 14px',
              borderRadius: 6,
              border: '1px solid var(--border)',
              background: 'transparent',
              color: 'var(--text-secondary)',
              fontSize: 13,
              cursor: 'pointer',
            }}
          >
            取消
          </button>
          {generatedResult && (
            <button
              onClick={handleSave}
              disabled={saving}
              style={{
                padding: '6px 16px',
                borderRadius: 6,
                border: 'none',
                background: 'var(--accent)',
                color: '#fff',
                fontSize: 13,
                fontWeight: 600,
                cursor: saving ? 'not-allowed' : 'pointer',
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
              }}
            >
              {saving ? <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} /> : <Check size={14} />}
              保存脚本到脚本库
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
