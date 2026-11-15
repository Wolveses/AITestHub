import { useEffect, useState } from 'react';
import { Copy, Play, RefreshCw, Square, Terminal } from 'lucide-react';
import { toast } from 'sonner';
import { Modal } from '../../../components/ui/modal';
import { Btn, Field, StatusBadge, inputStyle } from './common';
import {
  generationStepImageUrl,
  useMobileStore,
  type MobileCase,
  type MobileGenerationDetail,
  type MobileGenerationSession,
} from '../store/mobileStore';

export function GenerateSessionModal({
  open,
  targetCase,
  onClose,
}: {
  open: boolean;
  targetCase: MobileCase | null;
  onClose: () => void;
}) {
  const {
    devices,
    apps,
    loadDevices,
    loadApps,
    loadCases,
    createGenerationSession,
    cancelGenerate,
    getGenerationDetail,
  } = useMobileStore();

  const [deviceId, setDeviceId] = useState('');
  const [appId, setAppId] = useState<number | ''>('');
  const [creating, setCreating] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [session, setSession] = useState<MobileGenerationSession | null>(null);
  const [detail, setDetail] = useState<MobileGenerationDetail | null>(null);

  useEffect(() => {
    if (!open) {
      setSession(null);
      setDetail(null);
      return;
    }
    void loadDevices();
    void loadApps();
  }, [open, loadDevices, loadApps]);

  useEffect(() => {
    if (!open || !targetCase) return;
    const idleAndroid = devices.find((d) => d.type === 'android' && d.status === 'online' && !d.busy);
    if (idleAndroid && !deviceId) setDeviceId(idleAndroid.device_id);
    const defaultApp =
      apps.find((a) => a.id === targetCase.default_app_id) ||
      apps.find((a) => a.is_default) ||
      apps[0];
    if (defaultApp && appId === '') setAppId(defaultApp.id);
  }, [open, targetCase, devices, apps, deviceId, appId]);

  useEffect(() => {
    if (!open || !session) return;
    let active = true;
    const poll = async () => {
      try {
        const res = await getGenerationDetail(session.generation_id);
        if (active) {
          setDetail(res);
          if (res.status === 'success' || res.status === 'failed' || res.status === 'cancelled') {
            void loadCases();
            void loadDevices();
          }
        }
      } catch {
        // ignore transient poll errors
      }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 3000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [open, session, getGenerationDetail, loadCases, loadDevices]);

  if (!targetCase) return null;

  const androidDevices = devices.filter((d) => d.type === 'android');

  const handleStart = async () => {
    if (!deviceId) {
      toast.warning('请选择一台空闲的 Android 设备');
      return;
    }
    setCreating(true);
    try {
      const res = await createGenerationSession(targetCase.id, {
        device_id: deviceId,
        app_id: appId === '' ? null : appId,
        kind: targetCase.has_script ? 'fix' : 'generate',
      });
      setSession(res);
      toast.success('生成会话已创建，已锁定平台设备');
      void loadDevices();
      void loadCases();
    } catch (e) {
      toast.error(`创建会话失败: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setCreating(false);
    }
  };

  const handleCancel = async () => {
    setCancelling(true);
    try {
      await cancelGenerate(targetCase.id);
      toast.info('已取消生成会话并释放设备');
      setSession(null);
      setDetail(null);
      void loadDevices();
      void loadCases();
    } catch (e) {
      toast.error(`取消失败: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setCancelling(false);
    }
  };

  const copyText = async (label: string, text: string) => {
    await navigator.clipboard.writeText(text);
    toast.success(`已复制 ${label}`);
  };

  const mcpConfigStr = session ? JSON.stringify(session.mcp_config, null, 2) : '';
  const screenshots = detail?.step_screenshots || [];

  return (
    <Modal
      open={open}
      onOpenChange={(o) => !o && onClose()}
      title={`Agent 探索生成：${targetCase.title}`}
      width="min(840px, 94vw)"
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        {!session ? (
          <>
            <div
              style={{
                padding: 12,
                borderRadius: 8,
                background: 'var(--bg-base)',
                border: '1px solid var(--border)',
                fontSize: 12,
                color: 'var(--text-secondary)',
                lineHeight: 1.6,
              }}
            >
              设备直接连接在<strong>平台主机</strong>上。创建会话后平台将锁定所选手机并生成一次性 MCP 配置；
              您可在本地 IDE / Claude Code / Codex 中接入该 MCP，让 Agent 远程操控平台手机探索并完成服务端 Dry-Run 验证。
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              <Field label="平台主机设备 (Android)">
                <div style={{ display: 'flex', gap: 6 }}>
                  <select
                    style={{ ...inputStyle, flex: 1 }}
                    value={deviceId}
                    onChange={(e) => setDeviceId(e.target.value)}
                  >
                    <option value="">请选择设备</option>
                    {androidDevices.map((d) => (
                      <option key={d.device_id} value={d.device_id} disabled={d.busy}>
                        {d.model || d.name || d.device_id} ({d.device_id}) {d.busy ? '[占用中]' : ''}
                      </option>
                    ))}
                  </select>
                  <Btn variant="ghost" onClick={() => void loadDevices()} style={{ padding: '6px 10px' }}>
                    <RefreshCw size={13} />
                  </Btn>
                </div>
              </Field>

              <Field label="被测 App 环境">
                <select
                  style={inputStyle}
                  value={appId}
                  onChange={(e) => setAppId(e.target.value ? Number(e.target.value) : '')}
                >
                  <option value="">使用项目默认 App</option>
                  {apps.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name} ({a.app_package})
                    </option>
                  ))}
                </select>
              </Field>
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
              <Btn variant="ghost" onClick={onClose}>
                关闭
              </Btn>
              <Btn variant="primary" onClick={() => void handleStart()} disabled={creating || !deviceId}>
                <Play size={13} /> {creating ? '正在锁定设备...' : '创建 MCP 生成会话'}
              </Btn>
            </div>
          </>
        ) : (
          <>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '10px 12px',
                borderRadius: 8,
                background: 'var(--bg-base)',
                border: '1px solid var(--border)',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 12 }}>
                <StatusBadge status={detail?.status || 'running'} />
                <span style={{ color: 'var(--text-secondary)' }}>
                  会话 #{session.generation_id} · 设备 <code>{session.device_id}</code> · 工具调用{' '}
                  <strong>{detail?.tool_calls ?? 0}</strong> 次
                </span>
                {detail?.last_dry_run_passed && (
                  <span style={{ color: 'var(--success)', fontWeight: 600 }}>服务端 Dry-Run 已通过</span>
                )}
              </div>
              <Btn variant="danger" onClick={() => void handleCancel()} disabled={cancelling}>
                <Square size={12} /> {cancelling ? '释放中...' : '取消并释放设备'}
              </Btn>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)' }}>
                    <Terminal size={13} style={{ display: 'inline', marginRight: 4 }} />
                    1. MCP Server 配置 (JSON)
                  </span>
                  <Btn variant="ghost" onClick={() => void copyText('MCP 配置', mcpConfigStr)} style={{ padding: '3px 8px', fontSize: 11 }}>
                    <Copy size={11} /> 复制配置
                  </Btn>
                </div>
                <pre
                  style={{
                    margin: 0,
                    padding: 10,
                    borderRadius: 8,
                    background: 'var(--bg-base)',
                    border: '1px solid var(--border)',
                    fontSize: 11,
                    color: 'var(--text-secondary)',
                    overflow: 'auto',
                    maxHeight: 170,
                  }}
                >
                  {mcpConfigStr}
                </pre>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)' }}>
                    2. Agent 提示词 (Prompt)
                  </span>
                  <Btn
                    variant="ghost"
                    onClick={() => void copyText('Agent Prompt', session.agent_prompt)}
                    style={{ padding: '3px 8px', fontSize: 11 }}
                  >
                    <Copy size={11} /> 复制提示词
                  </Btn>
                </div>
                <pre
                  style={{
                    margin: 0,
                    padding: 10,
                    borderRadius: 8,
                    background: 'var(--bg-base)',
                    border: '1px solid var(--border)',
                    fontSize: 11,
                    color: 'var(--text-secondary)',
                    overflow: 'auto',
                    maxHeight: 170,
                    whiteSpace: 'pre-wrap',
                  }}
                >
                  {session.agent_prompt}
                </pre>
              </div>
            </div>

            {screenshots.length > 0 && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)' }}>
                  实时操作画面截图 ({screenshots.length})
                </div>
                <div style={{ display: 'flex', gap: 8, overflowX: 'auto', paddingBottom: 4 }}>
                  {screenshots.map((fn) => (
                    <a
                      key={fn}
                      href={generationStepImageUrl(session.generation_id, fn)}
                      target="_blank"
                      rel="noreferrer"
                      style={{
                        flexShrink: 0,
                        border: '1px solid var(--border)',
                        borderRadius: 6,
                        overflow: 'hidden',
                        background: 'var(--bg-base)',
                      }}
                    >
                      <img
                        src={generationStepImageUrl(session.generation_id, fn)}
                        alt={fn}
                        style={{ height: 140, width: 'auto', display: 'block' }}
                      />
                    </a>
                  ))}
                </div>
              </div>
            )}

            {detail?.error_message && (
              <div
                style={{
                  padding: 10,
                  borderRadius: 6,
                  border: '1px solid var(--error)',
                  color: 'var(--error)',
                  fontSize: 12,
                }}
              >
                {detail.error_message}
              </div>
            )}
          </>
        )}
      </div>
    </Modal>
  );
}
