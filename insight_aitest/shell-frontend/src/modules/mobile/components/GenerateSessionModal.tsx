import { useEffect, useRef, useState } from 'react';
import { Copy, Play, RefreshCw, Square, Unlock } from 'lucide-react';
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

function fallbackCopyText(text: string, container?: HTMLElement | null): boolean {
  const host = container ?? document.body;
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.setAttribute('readonly', '');
  ta.style.position = 'fixed';
  ta.style.top = '0';
  ta.style.left = '0';
  ta.style.width = '1px';
  ta.style.height = '1px';
  ta.style.padding = '0';
  ta.style.border = '0';
  ta.style.opacity = '0';
  ta.style.pointerEvents = 'none';
  const prevFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  host.appendChild(ta);
  try {
    // 挂在 Dialog 容器内，避免被 Radix Dialog focus-trap 抢回焦点导致 execCommand 失败
    ta.focus({ preventScroll: true });
    ta.select();
    ta.setSelectionRange(0, text.length);
    return document.execCommand('copy');
  } finally {
    host.removeChild(ta);
    prevFocus?.focus?.({ preventScroll: true });
  }
}

async function writeClipboard(text: string, container?: HTMLElement | null): Promise<void> {
  if (!text) throw new Error('empty');
  if (window.isSecureContext && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return;
    } catch {
      /* 降级到同步 execCommand */
    }
  }
  if (!fallbackCopyText(text, container)) {
    throw new Error('copy_failed');
  }
}

export function GenerateSessionModal({
  open,
  targetCase: propTargetCase = null,
  targetCases,
  onClose,
}: {
  open: boolean;
  targetCase?: MobileCase | null;
  targetCases?: MobileCase[];
  onClose: () => void;
}) {
  const {
    devices,
    apps,
    activeSessions,
    loadDevices,
    loadApps,
    loadCases,
    createGenerationSession,
    cancelGenerate,
    getActiveGeneration,
    clearActiveSession,
    getGenerationDetail,
    releaseDevice,
  } = useMobileStore();

  const candidates =
    targetCases && targetCases.length > 0
      ? targetCases
      : propTargetCase
        ? [propTargetCase]
        : [];
  const [activeCaseId, setActiveCaseId] = useState<number | null>(null);

  useEffect(() => {
    if (!open) {
      setActiveCaseId(null);
      return;
    }
    if (candidates.length === 0) return;
    if (activeCaseId !== null && candidates.some((c) => c.id === activeCaseId)) return;
    const preferred =
      candidates.find((c) => c.status === 'generating' || c.status === 'fixing') ||
      candidates.find((c) => !c.has_script) ||
      candidates[0];
    setActiveCaseId(preferred.id);
  }, [open, candidates, activeCaseId]);

  const targetCase = candidates.find((c) => c.id === activeCaseId) ?? candidates[0] ?? null;

  const [deviceId, setDeviceId] = useState('');
  const [appId, setAppId] = useState<number | ''>('');
  const [creating, setCreating] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [releasingId, setReleasingId] = useState<string | null>(null);
  const [checkingActive, setCheckingActive] = useState(false);
  const [session, setSession] = useState<MobileGenerationSession | null>(null);
  const [recoveredGen, setRecoveredGen] = useState<MobileGenerationDetail | null>(null);
  const [detail, setDetail] = useState<MobileGenerationDetail | null>(null);
  const [showMcpConfig, setShowMcpConfig] = useState(false);
  const dialogBodyRef = useRef<HTMLDivElement>(null);

  const targetCaseId = targetCase?.id ?? null;

  // 打开弹窗或切换选定用例时：优先恢复该用例进行中的会话
  useEffect(() => {
    setSession(null);
    setRecoveredGen(null);
    setDetail(null);
    setShowMcpConfig(false);

    if (!open || targetCaseId === null) {
      setCheckingActive(false);
      return;
    }

    let cancelled = false;
    const cached = useMobileStore.getState().activeSessions[targetCaseId] || null;
    if (cached) {
      setSession(cached);
    }
    setCheckingActive(!cached && (targetCase?.status === 'generating' || targetCase?.status === 'fixing'));

    void loadDevices();
    void loadApps();

    void (async () => {
      try {
        const res = await getActiveGeneration(targetCaseId);
        if (cancelled) return;
        if (res.active && res.generation) {
          setDetail(res.generation);
          if (cached && cached.generation_id === res.generation.id) {
            setSession(cached);
            setRecoveredGen(null);
          } else {
            clearActiveSession(targetCaseId);
            setSession(null);
            setRecoveredGen(res.generation);
          }
        } else {
          clearActiveSession(targetCaseId);
          setSession(null);
          setRecoveredGen(null);
          setDetail(null);
          if (targetCase?.status === 'generating' || targetCase?.status === 'fixing') {
            void loadCases();
            void loadDevices();
          }
        }
      } catch {
        // 保持缓存态，等待轮询或手动操作
      } finally {
        if (!cancelled) setCheckingActive(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [open, targetCaseId]);

  useEffect(() => {
    if (!open || !targetCase) return;
    const currentValid = devices.some((d) => d.device_id === deviceId && !d.busy);
    if (!currentValid) {
      const idleDevice = devices.find((d) => d.status === 'online' && !d.busy);
      setDeviceId(idleDevice ? idleDevice.device_id : '');
    }
    const defaultApp =
      apps.find((a) => a.id === targetCase.default_app_id) ||
      apps.find((a) => a.is_default) ||
      apps[0];
    if (defaultApp && appId === '') setAppId(defaultApp.id);
  }, [open, targetCase, devices, apps, deviceId, appId]);

  const activeGenId = session?.generation_id ?? recoveredGen?.id ?? null;

  useEffect(() => {
    if (!open || activeGenId === null || targetCaseId === null) return;
    let active = true;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const res = await getGenerationDetail(activeGenId);
        if (!active) return;
        setDetail(res);
        if (res.status === 'success' || res.status === 'failed' || res.status === 'cancelled') {
          clearActiveSession(targetCaseId);
          void loadCases();
          void loadDevices();
          if (timer !== undefined) {
            window.clearInterval(timer);
            timer = undefined;
          }
        }
      } catch {
        // ignore transient poll errors
      }
    };
    void poll();
    timer = window.setInterval(() => void poll(), 3000);
    return () => {
      active = false;
      if (timer !== undefined) window.clearInterval(timer);
    };
  }, [open, activeGenId, targetCaseId, getGenerationDetail, clearActiveSession, loadCases, loadDevices]);

  // 同步外部（如列表行/详情抽屉/设备面板）发起的取消
  useEffect(() => {
    if (!open || targetCaseId === null) return;
    if (!activeSessions[targetCaseId] && session) {
      setSession(null);
    }
  }, [open, targetCaseId, activeSessions, session]);

  if (!targetCase) return null;

  const handleStart = async () => {
    if (!deviceId) {
      toast.warning('请选择一台空闲设备');
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
      setRecoveredGen(null);
      setDetail(null);
      toast.success('生成会话已创建，已锁定平台设备');
    } catch (e) {
      toast.error(`创建会话失败: ${e instanceof Error ? e.message : String(e)}`);
      void loadDevices();
      void loadCases();
    } finally {
      setCreating(false);
    }
  };

  const handleCancel = async () => {
    setCancelling(true);
    try {
      await cancelGenerate(targetCase.id);
      toast.info('已停止生成会话并释放设备');
      setSession(null);
      setRecoveredGen(null);
      setDetail(null);
    } catch (e) {
      toast.error(`停止失败: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setCancelling(false);
    }
  };

  const handleForceRelease = async (did: string) => {
    setReleasingId(did);
    try {
      await releaseDevice(did);
      toast.success(`设备 ${did} 已释放`);
      setDeviceId(did);
    } catch (e) {
      toast.error(`释放失败: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setReleasingId(null);
    }
  };

  const copy = async (text: string, label: string) => {
    try {
      await writeClipboard(text, dialogBodyRef.current);
      toast.success(`已复制${label}`);
    } catch {
      toast.error('复制失败，请手动选中复制');
    }
  };

  const mcpConfigStr = session ? JSON.stringify(session.mcp_config, null, 2) : '';
  const screenshots = detail?.step_screenshots || [];
  const events = detail?.events || [];
  const busyDevices = devices.filter((d) => d.busy);
  const currentGenId = session?.generation_id ?? recoveredGen?.id ?? detail?.id ?? null;
  const currentDeviceId = session?.device_id ?? recoveredGen?.device_id ?? detail?.device_id ?? '';
  const currentStatus = detail?.status ?? recoveredGen?.status ?? 'running';
  const showActiveView = !!session || !!recoveredGen;

  return (
    <Modal
      open={open}
      onOpenChange={(o) => !o && onClose()}
      title={candidates.length > 1 ? `交给本地 Agent（已选 ${candidates.length} 条）` : `交给本地 Agent：${targetCase.title}`}
      width="min(900px, 95vw)"
    >
      <div
        ref={dialogBodyRef}
        style={{ padding: '4px 20px 18px', maxHeight: '76vh', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 12 }}
      >
        {candidates.length > 1 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, paddingBottom: 6, borderBottom: '1px solid var(--border)' }}>
            {candidates.map((c) => {
              const active = c.id === targetCase.id;
              return (
                <button
                  key={c.id}
                  type="button"
                  onClick={() => setActiveCaseId(c.id)}
                  style={{
                    padding: '4px 10px',
                    borderRadius: 999,
                    border: active ? '1px solid var(--accent)' : '1px solid var(--border)',
                    background: active ? 'var(--surface-tint)' : 'var(--bg-card)',
                    color: active ? 'var(--accent)' : 'var(--text-secondary)',
                    fontSize: 11,
                    cursor: 'pointer',
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 6,
                    maxWidth: 240,
                  }}
                >
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    #{c.id} {c.title}
                  </span>
                  {(c.status === 'generating' || c.status === 'fixing') && (
                    <span style={{ color: '#0ea5e9', fontWeight: 600 }}>进行中</span>
                  )}
                </button>
              );
            })}
          </div>
        )}
        {checkingActive ? (
          <div style={{ padding: '24px 0', textAlign: 'center', fontSize: 12, color: 'var(--text-muted)' }}>
            正在检查当前用例的生成会话状态…
          </div>
        ) : !showActiveView ? (
          <>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.7 }}>
              创建会话后平台将锁定所选真机并签发一次性 MCP 配置与提示词；将文案粘贴到本地 Agent（Claude Code / Codex / Cursor），Agent 会通过 MCP 自动拉取用例、操纵真机探索并完成服务端试跑入库。
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              <Field label="平台主机设备">
                <div style={{ display: 'flex', gap: 6 }}>
                  <select
                    style={{ ...inputStyle, flex: 1 }}
                    value={deviceId}
                    onChange={(e) => setDeviceId(e.target.value)}
                  >
                    <option value="">请选择设备</option>
                    {devices.map((d) => (
                      <option key={d.device_id} value={d.device_id} disabled={d.busy}>
                        {d.model || d.name || d.device_id} ({d.type} · {d.device_id}) {d.busy ? '[占用中]' : ''}
                      </option>
                    ))}
                  </select>
                  <Btn size="sm" variant="ghost" onClick={() => void loadDevices()} title="刷新设备">
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
                      {a.name} ({a.platform} · {a.app_package})
                    </option>
                  ))}
                </select>
              </Field>
            </div>

            {busyDevices.length > 0 && (
              <div
                style={{
                  padding: '8px 12px',
                  borderRadius: 6,
                  background: 'var(--bg-card)',
                  border: '1px solid var(--border)',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 6,
                }}
              >
                <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-secondary)' }}>
                  当前被占用的设备（可手动停止并释放）
                </div>
                {busyDevices.map((d) => (
                  <div
                    key={d.device_id}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      gap: 8,
                      fontSize: 12,
                    }}
                  >
                    <span style={{ color: 'var(--text-muted)' }}>
                      <code style={{ color: 'var(--text-primary)' }}>{d.device_id}</code>
                      {d.lease
                        ? ` · 被用例 #${d.lease.case_id} (${d.lease.holder_type}) 锁定`
                        : ' · 占用中'}
                    </span>
                    <Btn
                      size="sm"
                      variant="danger"
                      disabled={releasingId === d.device_id}
                      onClick={() => void handleForceRelease(d.device_id)}
                    >
                      <Unlock size={12} /> {releasingId === d.device_id ? '释放中…' : '停止并释放'}
                    </Btn>
                  </div>
                ))}
              </div>
            )}

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 4 }}>
              <Btn size="sm" onClick={onClose}>
                取消
              </Btn>
              <Btn size="sm" variant="primary" onClick={() => void handleStart()} disabled={creating || !deviceId}>
                <Play size={12} /> {creating ? '正在锁定设备…' : '创建生成会话'}
              </Btn>
            </div>
          </>
        ) : (
          <>
            {session ? (
              <>
                <div style={{ fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.6 }}>
                  把下面的文案粘贴到你的本地 Agent 执行（Agent 将自动通过 MCP 获取用例详情、规范与骨架）；关闭弹窗不会中断后台会话，可随时重新打开查看或手动停止。
                </div>

                {/* 工具条（对齐 UI 自动化 AgentAuthoringDialog） */}
                <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                  <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                    MCP: <code style={{ color: 'var(--accent)' }}>{session.mcp_url}</code>
                  </span>
                  <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                    Token: <code>{session.session_token.slice(0, 18)}…</code>
                  </span>
                  <div style={{ flex: 1 }} />
                  <Btn size="sm" onClick={() => void copy(session.session_token, ' Token')}>
                    <Copy size={12} /> Token
                  </Btn>
                  <Btn size="sm" onClick={() => void copy(mcpConfigStr, ' MCP 配置')}>
                    <Copy size={12} /> MCP 配置
                  </Btn>
                  <Btn size="sm" variant="primary" onClick={() => void copy(session.agent_prompt, '文案')}>
                    <Copy size={12} /> 复制文案
                  </Btn>
                </div>

                <textarea
                  readOnly
                  value={session.agent_prompt}
                  style={{
                    ...inputStyle,
                    width: '100%',
                    height: 120,
                    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
                    fontSize: 12,
                    lineHeight: 1.6,
                    resize: 'vertical',
                  }}
                />

                <div>
                  <button
                    type="button"
                    onClick={() => setShowMcpConfig((v) => !v)}
                    style={{ background: 'transparent', border: 'none', color: 'var(--text-secondary)', fontSize: 12, cursor: 'pointer', padding: 0 }}
                  >
                    {showMcpConfig ? '▾' : '▸'} MCP 客户端 JSON 配置（如 IDE 未预配可手动导入）
                  </button>
                  {showMcpConfig && (
                    <pre
                      style={{
                        margin: '6px 0 0',
                        padding: 10,
                        borderRadius: 6,
                        background: 'var(--bg-card)',
                        border: '1px solid var(--border)',
                        fontSize: 11,
                        color: 'var(--text-secondary)',
                        overflow: 'auto',
                        maxHeight: 150,
                      }}
                    >
                      {mcpConfigStr}
                    </pre>
                  )}
                </div>
              </>
            ) : (
              <div
                style={{
                  padding: '10px 12px',
                  borderRadius: 6,
                  background: 'var(--bg-card)',
                  border: '1px solid var(--border)',
                  fontSize: 12,
                  color: 'var(--text-secondary)',
                  lineHeight: 1.6,
                }}
              >
                当前用例正在进行生成会话 <strong>#{currentGenId}</strong>（设备 <code>{currentDeviceId}</code> 锁定中）。页面刷新后出于安全原因不再明文保留一次性 Token；若尚未将文案交给本地 Agent，可点击右侧「取消并释放设备」后重新创建会话。
              </div>
            )}

            {/* 生成进度区（对齐 UI 自动化） */}
            <div style={{ marginTop: 4, borderTop: '1px solid var(--border)', paddingTop: 12, display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
                  <span style={{ fontSize: 13, fontWeight: 600 }}>生成进度</span>
                  <StatusBadge status={currentStatus} />
                  <span style={{ color: 'var(--text-muted)' }}>
                    会话 #{currentGenId} · 设备 <code>{currentDeviceId}</code> · 工具调用{' '}
                    <strong>{detail?.tool_calls ?? 0}</strong> 次
                  </span>
                  {detail?.last_dry_run_passed && (
                    <span style={{ color: 'var(--success, #10b981)', fontWeight: 600 }}>服务端 Dry-Run 已通过</span>
                  )}
                </div>
                <div style={{ display: 'flex', gap: 8 }}>
                  {(currentStatus === 'failed' || currentStatus === 'cancelled') && (
                    <Btn
                      size="sm"
                      onClick={() => {
                        clearActiveSession(targetCase.id);
                        setSession(null);
                        setRecoveredGen(null);
                        setDetail(null);
                      }}
                    >
                      重新创建会话
                    </Btn>
                  )}
                  {currentStatus === 'running' && (
                    <Btn size="sm" variant="danger" onClick={() => void handleCancel()} disabled={cancelling}>
                      <Square size={12} /> {cancelling ? '释放中…' : '取消并释放设备'}
                    </Btn>
                  )}
                </div>
              </div>

              {detail?.error_message && (
                <div
                  style={{
                    padding: '8px 10px',
                    borderRadius: 6,
                    border: '1px solid var(--error)',
                    color: 'var(--error)',
                    fontSize: 12,
                  }}
                >
                  {detail.error_message}
                </div>
              )}

              {events.length > 0 && (
                <div
                  style={{
                    maxHeight: 150,
                    overflowY: 'auto',
                    border: '1px solid var(--border)',
                    borderRadius: 6,
                    padding: '6px 10px',
                    background: 'var(--bg-card)',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 4,
                  }}
                >
                  {events.slice(-12).map((ev, idx) => (
                    <div key={idx} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 11 }}>
                      <span style={{ color: 'var(--text-muted)', fontFamily: 'monospace', flexShrink: 0 }}>
                        {(ev.ts || '').slice(11, 19)}
                      </span>
                      <span style={{ color: ev.type === 'tool_error' ? 'var(--error)' : 'var(--accent)', fontWeight: 500 }}>
                        {ev.tool || ev.type}
                      </span>
                      <span style={{ color: 'var(--text-secondary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {ev.error
                          ? String(ev.error)
                          : ev.filename
                            ? `截图 ${ev.filename}`
                            : ev.type === 'dry_run_finished'
                              ? (ev.passed ? `试跑通过 (Run #${ev.run_id})` : `试跑失败 (Run #${ev.run_id})`)
                              : ev.type === 'committed'
                                ? `已固化入库 v${ev.version}`
                                : ev.type === 'session_started'
                                  ? '会话已锁定设备'
                                  : ev.type === 'session_cancelled'
                                    ? '会话已取消并释放设备'
                                    : ''}
                      </span>
                    </div>
                  ))}
                </div>
              )}

              {screenshots.length > 0 && currentGenId !== null && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)' }}>
                    实时操作画面截图 ({screenshots.length})
                  </div>
                  <div style={{ display: 'flex', gap: 8, overflowX: 'auto', paddingBottom: 4 }}>
                    {screenshots.map((fn) => (
                      <a
                        key={fn}
                        href={generationStepImageUrl(currentGenId, fn)}
                        target="_blank"
                        rel="noreferrer"
                        style={{
                          flexShrink: 0,
                          border: '1px solid var(--border)',
                          borderRadius: 6,
                          overflow: 'hidden',
                          background: 'var(--bg-card)',
                        }}
                      >
                        <img
                          src={generationStepImageUrl(currentGenId, fn)}
                          alt={fn}
                          style={{ height: 140, width: 'auto', display: 'block' }}
                        />
                      </a>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </Modal>
  );
}
