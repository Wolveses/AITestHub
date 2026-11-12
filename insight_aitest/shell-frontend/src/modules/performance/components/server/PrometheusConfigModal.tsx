import { useState, useEffect } from 'react';
import { Settings, CheckCircle2, XCircle, Loader2, X, Plus, Trash2, Globe, Key } from 'lucide-react';
import { toast } from 'sonner';

export interface PrometheusEndpoint {
  id: string;
  name: string;
  url: string;
  token?: string;
}

interface PrometheusConfigModalProps {
  open: boolean;
  onClose: () => void;
  onConfigSaved: (activeUrl: string) => void;
}

export function PrometheusConfigModal({ open, onClose, onConfigSaved }: PrometheusConfigModalProps) {
  const [activeUrl, setActiveUrl] = useState('');
  const [token, setToken] = useState('');
  const [endpoints, setEndpoints] = useState<PrometheusEndpoint[]>([]);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; msg: string } | null>(null);
  const [saving, setSaving] = useState(false);

  // 加载当前配置
  useEffect(() => {
    if (!open) return;
    setTestResult(null);
    fetch('/api/modules/performance/system_monitor/config')
      .then((r) => r.json())
      .then((data) => {
        setActiveUrl(data.active_url || 'http://192.2.8.100:9091');
        setToken(data.token || '');
        setEndpoints(data.endpoints || []);
      })
      .catch((err) => {
        console.error('加载 Prometheus 配置失败:', err);
      });
  }, [open]);

  if (!open) return null;

  // 测试连通性
  const handleTestConnection = async (testTargetUrl?: string, testTargetToken?: string) => {
    const target = testTargetUrl || activeUrl;
    if (!target.trim()) {
      toast.error('请输入 Prometheus 主机地址');
      return;
    }
    setTesting(true);
    setTestResult(null);
    try {
      const res = await fetch('/api/modules/performance/system_monitor/test-connection', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url: target.trim(),
          token: testTargetToken !== undefined ? testTargetToken : token,
        }),
      });
      const data = await res.json();
      if (data.ok) {
        setTestResult({ ok: true, msg: data.message });
        toast.success(data.message);
      } else {
        setTestResult({ ok: false, msg: data.message });
        toast.error(data.message);
      }
    } catch (e: any) {
      const msg = e.message || '连接请求失败';
      setTestResult({ ok: false, msg });
      toast.error(msg);
    } finally {
      setTesting(false);
    }
  };

  // 保存配置
  const handleSave = async () => {
    if (!activeUrl.trim()) {
      toast.error('Prometheus 地址不能为空');
      return;
    }
    setSaving(true);
    try {
      const res = await fetch('/api/modules/performance/system_monitor/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          active_url: activeUrl.trim(),
          token: token.trim(),
          endpoints,
        }),
      });
      const data = await res.json();
      if (res.ok) {
        toast.success('Prometheus 配置已更新生效');
        onConfigSaved(data.active_url);
        onClose();
      } else {
        toast.error(data.detail || '保存失败');
      }
    } catch (e: any) {
      toast.error(e.message || '保存请求异常');
    } finally {
      setSaving(false);
    }
  };

  // 快捷从历史预设中选择
  const handleSelectPreset = (ep: PrometheusEndpoint) => {
    setActiveUrl(ep.url);
    if (ep.token !== undefined) {
      setToken(ep.token);
    }
    setTestResult(null);
  };

  // 添加到预设列表
  const handleAddCurrentToPresets = () => {
    if (!activeUrl.trim()) return;
    const exists = endpoints.some((e) => e.url.replace(/\/$/, '') === activeUrl.replace(/\/$/, ''));
    if (exists) {
      toast.info('该地址已在快速预设列表中');
      return;
    }
    const newEp: PrometheusEndpoint = {
      id: `ep_${Date.now()}`,
      name: `自定义节点 (${activeUrl.replace(/^https?:\/\//, '')})`,
      url: activeUrl.trim(),
      token: token.trim(),
    };
    setEndpoints([...endpoints, newEp]);
    toast.success('已加入预设列表');
  };

  const handleDeletePreset = (id: string) => {
    setEndpoints(endpoints.filter((e) => e.id !== id));
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
        padding: 16,
      }}
    >
      <div
        style={{
          width: '100%',
          maxWidth: 580,
          background: 'var(--bg-card)',
          border: '1px solid var(--border)',
          borderRadius: 10,
          boxShadow: '0 20px 40px rgba(0,0,0,0.4)',
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        {/* 标题栏 */}
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
            <Settings size={18} color="var(--accent)" />
            <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)' }}>
              配置 Prometheus 数据源
            </span>
          </div>
          <button
            onClick={onClose}
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

        {/* 内容区 */}
        <div style={{ padding: 20, display: 'flex', flexDirection: 'column', gap: 16 }}>
          {/* 地址输入 */}
          <div>
            <label style={{ display: 'block', fontSize: 12, fontWeight: 500, color: 'var(--text-secondary)', marginBottom: 6 }}>
              Prometheus 地址 <span style={{ color: '#ef4444' }}>*</span>
            </label>
            <div style={{ position: 'relative' }}>
              <Globe size={15} style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
              <input
                type="text"
                placeholder="例如: http://192.2.8.100:9091"
                value={activeUrl}
                onChange={(e) => setActiveUrl(e.target.value)}
                style={{
                  width: '100%',
                  background: 'var(--bg-base)',
                  color: 'var(--text-primary)',
                  border: '1px solid var(--border)',
                  borderRadius: 6,
                  padding: '7px 12px 7px 32px',
                  fontSize: 13,
                  outline: 'none',
                }}
              />
            </div>
          </div>

          {/* Token (可选) */}
          <div>
            <label style={{ display: 'block', fontSize: 12, fontWeight: 500, color: 'var(--text-secondary)', marginBottom: 6 }}>
              认证 Token <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}>(可选)</span>
            </label>
            <div style={{ position: 'relative' }}>
              <Key size={15} style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
              <input
                type="password"
                placeholder="免密可留空"
                value={token}
                onChange={(e) => setToken(e.target.value)}
                style={{
                  width: '100%',
                  background: 'var(--bg-base)',
                  color: 'var(--text-primary)',
                  border: '1px solid var(--border)',
                  borderRadius: 6,
                  padding: '7px 12px 7px 32px',
                  fontSize: 13,
                  outline: 'none',
                }}
              />
            </div>
          </div>

          {/* 快速选择已有预设 */}
          <div>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
              <span style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-secondary)' }}>
                预设节点列表:
              </span>
              <button
                type="button"
                onClick={handleAddCurrentToPresets}
                style={{
                  background: 'transparent',
                  border: 'none',
                  color: 'var(--accent)',
                  fontSize: 11,
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 3,
                }}
              >
                <Plus size={12} />
                <span>存入预设</span>
              </button>
            </div>

            <div
              style={{
                maxHeight: 120,
                overflowY: 'auto',
                border: '1px solid var(--border)',
                borderRadius: 6,
                background: 'var(--bg-base)',
                padding: '4px 6px',
              }}
            >
              {endpoints.map((ep) => {
                const isCurrent = ep.url.replace(/\/$/, '') === activeUrl.replace(/\/$/, '');
                return (
                  <div
                    key={ep.id}
                    onClick={() => handleSelectPreset(ep)}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      padding: '5px 8px',
                      borderRadius: 4,
                      background: isCurrent ? 'rgba(59, 130, 246, 0.12)' : 'transparent',
                      border: isCurrent ? '1px solid rgba(59, 130, 246, 0.3)' : '1px solid transparent',
                      cursor: 'pointer',
                      fontSize: 12,
                      color: isCurrent ? 'var(--accent)' : 'var(--text-primary)',
                      marginBottom: 2,
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <span>{isCurrent ? '●' : '○'}</span>
                      <span style={{ fontWeight: isCurrent ? 600 : 400 }}>{ep.name || ep.url}</span>
                      <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>({ep.url})</span>
                    </div>
                    {endpoints.length > 1 && (
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleDeletePreset(ep.id);
                        }}
                        style={{
                          background: 'transparent',
                          border: 'none',
                          color: 'var(--text-muted)',
                          cursor: 'pointer',
                          padding: 2,
                        }}
                      >
                        <Trash2 size={12} />
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          {/* 探测测试反馈 */}
          {testResult && (
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                padding: '8px 12px',
                borderRadius: 6,
                fontSize: 12,
                background: testResult.ok ? 'rgba(16, 185, 129, 0.1)' : 'rgba(239, 68, 68, 0.1)',
                border: `1px solid ${testResult.ok ? 'rgba(16, 185, 129, 0.3)' : 'rgba(239, 68, 68, 0.3)'}`,
                color: testResult.ok ? '#10b981' : '#ef4444',
              }}
            >
              {testResult.ok ? <CheckCircle2 size={15} flex-shrink={0} /> : <XCircle size={15} flex-shrink={0} />}
              <span>{testResult.msg}</span>
            </div>
          )}
        </div>

        {/* 底部按钮栏 */}
        <div
          style={{
            padding: '12px 20px',
            borderTop: '1px solid var(--border)',
            background: 'var(--bg-base)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <button
            type="button"
            onClick={() => handleTestConnection()}
            disabled={testing}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 5,
              background: 'transparent',
              border: '1px solid var(--border)',
              color: 'var(--text-primary)',
              borderRadius: 6,
              padding: '6px 14px',
              fontSize: 12,
              cursor: testing ? 'not-allowed' : 'pointer',
            }}
          >
            {testing ? <Loader2 size={13} className="animate-spin" /> : <Settings size={13} />}
            <span>测试连接</span>
          </button>

          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <button
              type="button"
              onClick={onClose}
              style={{
                background: 'transparent',
                border: '1px solid var(--border)',
                color: 'var(--text-secondary)',
                borderRadius: 6,
                padding: '6px 14px',
                fontSize: 12,
                cursor: 'pointer',
              }}
            >
              取消
            </button>
            <button
              type="button"
              onClick={handleSave}
              disabled={saving}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 5,
                background: 'var(--accent)',
                color: '#fff',
                border: 'none',
                borderRadius: 6,
                padding: '6px 16px',
                fontSize: 12,
                fontWeight: 600,
                cursor: saving ? 'not-allowed' : 'pointer',
              }}
            >
              {saving && <Loader2 size={13} className="animate-spin" />}
              <span>保存并生效</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
