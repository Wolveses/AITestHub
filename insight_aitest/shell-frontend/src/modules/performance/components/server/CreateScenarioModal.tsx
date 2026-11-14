import { useState, useRef } from 'react';
import { toast } from 'sonner';
import { Sparkles, Upload, Play, Check, FileCode, Loader2 } from 'lucide-react';
import { useCapabilitiesStore } from '@/shared/store/capabilitiesStore';
import { useServerPerfStore } from '../../store/serverPerfStore';

interface CreateScenarioModalProps {
  open: boolean;
  onClose: () => void;
  projectId: number;
  onSuccess: () => void;
}

type Mode = 'ai' | 'upload';

export function CreateScenarioModal({ open, onClose, projectId, onSuccess }: CreateScenarioModalProps) {
  const { loadScripts } = useServerPerfStore();
  const aiAssistEnabled = useCapabilitiesStore((s) => s.aiAssistEnabled);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [mode, setMode] = useState<Mode>('ai');
  const effectiveMode: Mode = aiAssistEnabled ? mode : 'upload';

  // 基础表单
  const [scenarioName, setScenarioName] = useState('');
  const [scenarioDesc, setScenarioDesc] = useState('');

  // AI 生成模式表单
  const [planDesc, setPlanDesc] = useState('');
  const [concurrency, setConcurrency] = useState(20);
  const [rampUp, setRampUp] = useState(5);
  const [duration, setDuration] = useState(60);

  // 生成/上传结果状态
  const [generating, setGenerating] = useState(false);
  const [generatedData, setGeneratedData] = useState<any | null>(null);

  // 手动上传 JMX 状态
  const [uploadFileName, setUploadFileName] = useState('');
  const [jmxContent, setJmxContent] = useState('');

  // 调试状态
  const [debugging, setDebugging] = useState(false);
  const [debugResult, setDebugResult] = useState<any | null>(null);
  const [saving, setSaving] = useState(false);

  if (!open) return null;

  // 1. AI 根据方案生成
  const handleAIGenerate = async () => {
    if (!planDesc.trim()) {
      toast.error('请输入性能测试方案描述');
      return;
    }
    setGenerating(true);
    setGeneratedData(null);
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
      setGeneratedData(ret.data);
      setJmxContent(ret.data.jmx_content);
      if (!scenarioName) {
        setScenarioName(ret.data.name || 'JMeter性能场景');
      }
      setScenarioDesc(ret.data.description || '');
      toast.success('AI 已挑选相关接口并编排生成 JMX 场景');
    } catch (err: any) {
      toast.error(err.message || '生成失败');
    } finally {
      setGenerating(false);
    }
  };

  // 2. 手动读取本地 JMX 文件
  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!file.name.toLowerCase().endsWith('.jmx') && !file.name.toLowerCase().endsWith('.xml')) {
      toast.error('请上传标准 JMeter .jmx 脚本文件');
      return;
    }
    setUploadFileName(file.name);
    if (!scenarioName) {
      setScenarioName(file.name.replace(/\.[^/.]+$/, ''));
    }
    const reader = new FileReader();
    reader.onload = (event) => {
      const text = event.target?.result as string;
      setJmxContent(text);
      setGeneratedData({
        name: file.name,
        jmx_content: text,
        steps: [],
      });
      toast.success(`已载入脚本：${file.name}`);
    };
    reader.readAsText(file, 'utf-8');
  };

  // 3. 在线沙箱单步调试
  const handleDebug = async () => {
    if (!jmxContent.trim()) {
      toast.error('请先通过 AI 生成或上传 JMX 脚本');
      return;
    }
    setDebugging(true);
    try {
      const res = await fetch('/api/modules/performance/server/scripts/debug', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          jmx_content: jmxContent,
          base_url: generatedData?.base_url || '',
        }),
      });
      const ret = await res.json();
      if (!res.ok) throw new Error(ret.detail || '调试失败');
      setDebugResult(ret.data);
      if (ret.data.all_passed) {
        toast.success('沙箱调试通过，所有 Sampler 连通且断言成功');
      } else {
        toast.warning('部分接口响应异常或断言失败，请检查调试日志');
      }
    } catch (err: any) {
      toast.error(err.message || '调试执行失败');
    } finally {
      setDebugging(false);
    }
  };

  // 4. 确认保存入库
  const handleSave = async () => {
    if (!scenarioName.trim()) {
      toast.error('请输入场景名称');
      return;
    }
    if (!jmxContent.trim()) {
      toast.error('JMX 脚本内容不能为空，请上传或点击 AI 生成');
      return;
    }
    setSaving(true);
    try {
      const res = await fetch('/api/modules/performance/server/scripts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_id: projectId,
          name: scenarioName,
          description: scenarioDesc,
          plan_description: effectiveMode === 'ai' ? planDesc : `手动上传脚本: ${uploadFileName}`,
          config: generatedData?.config || { steps: generatedData?.steps || [] },
          jmx_content: jmxContent,
          asset_ids: generatedData?.selected_asset_ids || [],
        }),
      });
      const ret = await res.json();
      if (!res.ok) throw new Error(ret.detail || '保存失败');
      toast.success('测试场景已成功入库');
      await loadScripts(projectId);
      onSuccess();
      onClose();
    } catch (err: any) {
      toast.error(err.message || '保存失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 110,
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
          maxWidth: 960,
          maxHeight: '90vh',
          background: 'var(--bg-card)',
          borderRadius: 8,
          border: '1px solid var(--border)',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          boxShadow: '0 16px 36px rgba(0,0,0,0.5)',
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
            <FileCode size={18} style={{ color: 'var(--accent)' }} />
            <strong style={{ fontSize: 15, color: 'var(--text-primary)' }}>
              新增测试场景 (JMeter)
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
          {/* 模式切换选项卡 */}
          <div style={{ display: 'flex', gap: 8, borderBottom: '1px solid var(--border)', paddingBottom: 12 }}>
            <button
              onClick={() => aiAssistEnabled && setMode('ai')}
              disabled={!aiAssistEnabled}
              title={!aiAssistEnabled ? '系统设置已关闭「LLM 自动化辅助能力」，暂不可使用 AI 自动生成' : undefined}
              style={{
                padding: '6px 14px',
                borderRadius: 6,
                border: 'none',
                background: effectiveMode === 'ai' ? 'var(--accent)' : 'var(--bg-base)',
                color: effectiveMode === 'ai' ? 'var(--bg-base)' : 'var(--text-secondary)',
                fontSize: 13,
                fontWeight: 600,
                cursor: !aiAssistEnabled ? 'not-allowed' : 'pointer',
                opacity: !aiAssistEnabled ? 0.5 : 1,
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
              }}
            >
              <Sparkles size={14} /> AI 填入测试方案自动生成{!aiAssistEnabled ? '（设置已关闭）' : ''}
            </button>
            <button
              onClick={() => setMode('upload')}
              style={{
                padding: '6px 14px',
                borderRadius: 6,
                border: 'none',
                background: effectiveMode === 'upload' ? 'var(--accent)' : 'var(--bg-base)',
                color: effectiveMode === 'upload' ? 'var(--bg-base)' : 'var(--text-secondary)',
                fontSize: 13,
                fontWeight: 600,
                cursor: 'pointer',
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
              }}
            >
              <Upload size={14} /> 手动上传 JMeter 脚本 (.jmx)
            </button>
          </div>

          {/* 场景基本信息 */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div>
              <label style={{ fontSize: 12, color: 'var(--text-secondary)' }}>测试场景名称 *</label>
              <input
                type="text"
                value={scenarioName}
                onChange={(e) => setScenarioName(e.target.value)}
                placeholder="例如：核心下单链路高并发压测"
                style={{
                  width: '100%',
                  height: 32,
                  marginTop: 4,
                  padding: '0 8px',
                  borderRadius: 4,
                  border: '1px solid var(--border)',
                  background: 'var(--bg-base)',
                  color: 'var(--text-primary)',
                  fontSize: 13,
                }}
              />
            </div>
            <div>
              <label style={{ fontSize: 12, color: 'var(--text-secondary)' }}>场景描述 (可选)</label>
              <input
                type="text"
                value={scenarioDesc}
                onChange={(e) => setScenarioDesc(e.target.value)}
                placeholder="简要备注压测目标或业务背景"
                style={{
                  width: '100%',
                  height: 32,
                  marginTop: 4,
                  padding: '0 8px',
                  borderRadius: 4,
                  border: '1px solid var(--border)',
                  background: 'var(--bg-base)',
                  color: 'var(--text-primary)',
                  fontSize: 13,
                }}
              />
            </div>
          </div>

          {/* 模式 A: AI 填入测试方案自动生成 */}
          {effectiveMode === 'ai' && (
            <div
              style={{
                padding: 16,
                borderRadius: 8,
                background: 'var(--bg-base)',
                border: '1px solid var(--border)',
                display: 'flex',
                flexDirection: 'column',
                gap: 12,
              }}
            >
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                <label style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>
                  性能测试方案描述 (填入需求自动挑选接口) *
                </label>
                <textarea
                  value={planDesc}
                  onChange={(e) => setPlanDesc(e.target.value)}
                  placeholder={`【输入引导语示例】
• 场景链路：模拟用户首先调用登录接口获取 Token，然后携带 Token 分页查询商品列表，最后调用下单接口；
• 施压目标：模拟 50 并发线程，加压预热 5 秒，持续压测 60 秒；
• 重点关注：高并发下单下的接口响应延迟与系统吞吐量（TPS）。`}
                  rows={4}
                  style={{
                    width: '100%',
                    padding: '10px 12px',
                    borderRadius: 6,
                    border: '1px solid var(--border)',
                    background: 'var(--bg-card)',
                    color: 'var(--text-primary)',
                    fontSize: 13,
                    lineHeight: 1.6,
                    outline: 'none',
                  }}
                />
              </div>

              {/* 并发与预热参数设置 */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
                <div>
                  <label style={{ fontSize: 11, color: 'var(--text-muted)' }}>目标并发线程数</label>
                  <input
                    type="number"
                    min={1}
                    max={500}
                    value={concurrency}
                    onChange={(e) => setConcurrency(Number(e.target.value))}
                    style={{
                      width: '100%',
                      height: 30,
                      marginTop: 4,
                      padding: '0 8px',
                      borderRadius: 4,
                      border: '1px solid var(--border)',
                      background: 'var(--bg-card)',
                      color: 'var(--text-primary)',
                    }}
                  />
                </div>
                <div>
                  <label style={{ fontSize: 11, color: 'var(--text-muted)' }}>预热加压时间 (秒)</label>
                  <input
                    type="number"
                    min={0}
                    value={rampUp}
                    onChange={(e) => setRampUp(Number(e.target.value))}
                    style={{
                      width: '100%',
                      height: 30,
                      marginTop: 4,
                      padding: '0 8px',
                      borderRadius: 4,
                      border: '1px solid var(--border)',
                      background: 'var(--bg-card)',
                      color: 'var(--text-primary)',
                    }}
                  />
                </div>
                <div>
                  <label style={{ fontSize: 11, color: 'var(--text-muted)' }}>持续运行时长 (秒)</label>
                  <input
                    type="number"
                    min={10}
                    value={duration}
                    onChange={(e) => setDuration(Number(e.target.value))}
                    style={{
                      width: '100%',
                      height: 30,
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

              <div>
                <button
                  onClick={handleAIGenerate}
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
                  {generating ? (
                    <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} />
                  ) : (
                    <Sparkles size={14} />
                  )}
                  {generating ? 'AI 正在匹配接口并组装 JMX...' : '点击根据方案 AI 自动生成测试场景'}
                </button>
              </div>
            </div>
          )}

          {/* 模式 B: 手动上传 JMX 文件 */}
          {effectiveMode === 'upload' && (
            <div
              style={{
                padding: 24,
                borderRadius: 8,
                background: 'var(--bg-base)',
                border: '2px dashed var(--border)',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 12,
              }}
            >
              <input
                type="file"
                ref={fileInputRef}
                accept=".jmx,.xml"
                onChange={handleFileUpload}
                style={{ display: 'none' }}
              />
              <Upload size={36} strokeWidth={1.5} style={{ color: 'var(--accent)' }} />
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)' }}>
                  {uploadFileName ? `已选择文件：${uploadFileName}` : '点击上传本地 JMeter 脚本 (.jmx)'}
                </div>
                <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>
                  支持官方 JMeter 5.x 导出的测试计划文件，载入后可在线调试与任务组合
                </div>
              </div>
              <button
                onClick={() => fileInputRef.current?.click()}
                style={{
                  padding: '6px 16px',
                  borderRadius: 6,
                  border: '1px solid var(--border)',
                  background: 'var(--bg-card)',
                  color: 'var(--text-primary)',
                  fontSize: 13,
                  cursor: 'pointer',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 6,
                }}
              >
                <Upload size={14} /> 选择 .jmx 脚本文件
              </button>
            </div>
          )}

          {/* 生成/上传后的预览与单步沙箱调试 */}
          {jmxContent && (
            <div
              style={{
                padding: 16,
                borderRadius: 8,
                background: 'var(--bg-base)',
                border: '1px solid var(--border)',
                display: 'flex',
                flexDirection: 'column',
                gap: 12,
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <Check size={16} style={{ color: '#10b981' }} />
                  <strong style={{ fontSize: 13, color: 'var(--text-primary)' }}>
                    JMX 脚本已就绪 ({Math.round(jmxContent.length / 1024)} KB)
                  </strong>
                </div>

                <button
                  onClick={handleDebug}
                  disabled={debugging}
                  style={{
                    padding: '5px 12px',
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
                  {debugging ? (
                    <Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} />
                  ) : (
                    <Play size={13} />
                  )}
                  在线沙箱单步调试 (验证连通性)
                </button>
              </div>

              {/* 调试回显 */}
              {debugResult && (
                <div
                  style={{
                    fontSize: 12,
                    padding: 10,
                    borderRadius: 6,
                    background: 'var(--bg-card)',
                    border: '1px solid var(--border)',
                  }}
                >
                  <div
                    style={{
                      marginBottom: 6,
                      fontWeight: 600,
                      color: debugResult.all_passed ? 'var(--success, #10b981)' : '#ef4444',
                    }}
                  >
                    耗时: {debugResult.total_time_ms}ms · 提取变量: {JSON.stringify(debugResult.context_vars)}
                  </div>
                  {debugResult.steps?.map((ds: any, didx: number) => (
                    <div
                      key={didx}
                      style={{
                        padding: '4px 0',
                        borderBottom: '1px dashed var(--border)',
                        display: 'flex',
                        justifyContent: 'space-between',
                      }}
                    >
                      <span>{ds.name}</span>
                      <span>
                        状态码: {ds.status_code} ({ds.elapsed_ms}ms)
                      </span>
                    </div>
                  ))}
                </div>
              )}
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
          <button
            onClick={handleSave}
            disabled={saving || !jmxContent}
            style={{
              padding: '6px 16px',
              borderRadius: 6,
              border: 'none',
              background: jmxContent ? 'var(--accent)' : 'var(--bg-card)',
              color: jmxContent ? '#fff' : 'var(--text-muted)',
              fontSize: 13,
              fontWeight: 600,
              cursor: saving || !jmxContent ? 'not-allowed' : 'pointer',
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
            }}
          >
            {saving ? <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} /> : <Check size={14} />}
            保存测试场景到库
          </button>
        </div>
      </div>
    </div>
  );
}
