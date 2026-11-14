import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Copy, RefreshCw, ShieldOff } from 'lucide-react';
import { Modal } from '../../../../components/ui/modal';
import {
  fetchAuthoringStatus,
  fetchAuthoringTokens,
  requestAuthoringPrompt,
  revokeAuthoringToken,
  type AuthoringPrompt,
  type AuthoringStatusItem,
  type AuthoringToken,
} from '../../store/automationStore';
import { Btn, inputStyle } from './common';

const STAGE_META: Record<string, { label: string; color: string }> = {
  '': { label: '等待本地 Agent', color: 'var(--text-muted)' },
  validated: { label: '已通过校验', color: 'var(--accent)' },
  dry_run_ok: { label: '试跑通过', color: '#22c55e' },
  submitted: { label: '已入库', color: '#22c55e' },
  failed: { label: '未完成', color: '#f97316' },
};

function stageOf(item: AuthoringStatusItem, submitted: boolean): string {
  if (submitted) return 'submitted';
  if (item.stage === 'dry_run_ok') return 'dry_run_ok';
  if (item.stage === 'validated') return 'validated';
  if (item.last_error) return 'failed';
  return '';
}

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

async function copyText(text: string, container?: HTMLElement | null): Promise<void> {
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

export function AgentAuthoringDialog({
  open,
  onClose,
  projectId,
  caseIds,
}: {
  open: boolean;
  onClose: () => void;
  projectId: number | null;
  caseIds: number[];
}) {
  const { t } = useTranslation();
  const [prompt, setPrompt] = useState<AuthoringPrompt | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [status, setStatus] = useState<AuthoringStatusItem[]>([]);
  const [tokens, setTokens] = useState<AuthoringToken[]>([]);
  const [showTokens, setShowTokens] = useState(false);
  const seqRef = useRef(0);
  const dialogBodyRef = useRef<HTMLDivElement>(null);

  const refreshStatus = useCallback(async () => {
    if (caseIds.length === 0) return;
    try {
      setStatus(await fetchAuthoringStatus(caseIds));
    } catch {
      /* 轮询失败静默，等待下次 */
    }
  }, [caseIds]);

  const refreshTokens = useCallback(async () => {
    if (projectId === null) return;
    try {
      setTokens(await fetchAuthoringTokens(projectId));
    } catch (e) {
      toast.error((e as Error).message);
    }
  }, [projectId]);

  // 打开时生成文案（每次打开都生成新 Token，旧 Token 不会被覆盖）
  useEffect(() => {
    if (!open) return;
    const seq = ++seqRef.current;
    setPrompt(null);
    setError('');
    setStatus([]);
    setLoading(true);
    (async () => {
      try {
        if (projectId === null) throw new Error(t('ui.auto.selectProjectFirst', '请先选择项目'));
        if (caseIds.length === 0) throw new Error(t('ui.auto.selectCasesFirst', '请先勾选用例'));
        const data = await requestAuthoringPrompt(projectId, caseIds);
        if (seq !== seqRef.current) return;
        setPrompt(data);
        void refreshStatus();
        void refreshTokens();
      } catch (e) {
        if (seq === seqRef.current) setError((e as Error).message);
      } finally {
        if (seq === seqRef.current) setLoading(false);
      }
    })();
  }, [open, projectId, caseIds, refreshStatus, refreshTokens, t]);

  // 进度轮询（3 秒；SSE 为增强通道，轮询保证可用）
  useEffect(() => {
    if (!open || caseIds.length === 0) return;
    const timer = window.setInterval(() => void refreshStatus(), 3000);
    return () => window.clearInterval(timer);
  }, [open, caseIds, refreshStatus]);

  const copy = async (text: string, label: string) => {
    try {
      await copyText(text, dialogBodyRef.current);
      toast.success(t('ui.auto.copied', '已复制{{label}}', { label }));
    } catch {
      toast.error(t('ui.auto.copyFailed', '复制失败，请手动选中复制'));
    }
  };

  const handleRevoke = async (tokenId: number) => {
    if (projectId === null) return;
    try {
      await revokeAuthoringToken(projectId, tokenId);
      toast.success(t('ui.auto.tokenRevoked', 'Token 已吊销'));
      void refreshTokens();
    } catch (e) {
      toast.error((e as Error).message);
    }
  };

  return (
    <Modal
      open={open}
      onOpenChange={(v) => !v && onClose()}
      width="min(900px, 95vw)"
      title={t('ui.auto.agentAuthoringTitle', '交给本地 Agent')}
    >
      <div ref={dialogBodyRef} style={{ padding: '4px 20px 18px', maxHeight: '76vh', overflowY: 'auto' }}>
        <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 12, lineHeight: 1.7 }}>
          {t('ui.auto.agentAuthoringDesc', '把下面的文案粘贴到你的本地 Agent 执行')}
        </div>

        {loading && <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{t('ui.auto.generatingPrompt', '正在生成文案…')}</div>}
        {error && <div style={{ fontSize: 12, color: '#f87171', marginBottom: 12 }}>{error}</div>}

        {prompt && (
          <>
            {prompt.prompt === null ? (
              <div
                style={{
                  padding: '10px 12px',
                  border: '1px solid var(--border)',
                  borderRadius: 6,
                  fontSize: 12,
                  color: 'var(--text-secondary)',
                  background: 'var(--bg-base)',
                }}
              >
                {t('ui.auto.nothingToDo', '选中用例均已通过或正在执行，无需交给本地 Agent 处理。')}
              </div>
            ) : (
              <>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8, flexWrap: 'wrap' }}>
                  <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>MCP: <code style={{ color: 'var(--accent)' }}>{prompt.mcp_url}</code></span>
                  <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>Token: <code>{(prompt.token || '').slice(0, 18)}…</code></span>
                  <div style={{ flex: 1 }} />
                  <Btn size="sm" onClick={() => copy(prompt.token || '', ' Token')}>
                    <Copy size={12} /> Token
                  </Btn>
                  <Btn size="sm" variant="primary" onClick={() => copy(prompt.prompt || '', '文案')}>
                    <Copy size={12} /> {t('ui.auto.copyPrompt', '复制文案')}
                  </Btn>
                </div>
                <textarea
                  readOnly
                  value={prompt.prompt}
                  style={{
                    ...inputStyle,
                    width: '100%',
                    height: 140,
                    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
                    fontSize: 12,
                    lineHeight: 1.6,
                    resize: 'vertical',
                  }}
                />
              </>
            )}
            {prompt.skipped_case_ids.length > 0 && (
              <div style={{ fontSize: 11, color: '#fbbf24', marginTop: 6 }}>
                {t('ui.auto.skippedCases', '以下用例不属于当前项目，已跳过：{{ids}}', { ids: prompt.skipped_case_ids.join(', ') })}
              </div>
            )}
          </>
        )}

        <div style={{ marginTop: 18, borderTop: '1px solid var(--border)', paddingTop: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
            <span style={{ fontSize: 13, fontWeight: 600 }}>{t('ui.auto.authoringProgress', '生成进度')}</span>
            <Btn size="sm" variant="ghost" onClick={() => void refreshStatus()}>
              <RefreshCw size={12} />
            </Btn>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {caseIds.map((cid) => {
              const item = status.find((s) => s.case_id === cid);
              const submitted = !!(item && item.source === 'local_agent' && item.authoring_at && (item.script_version || 0) > 0 && item.stage === '');
              const stage = item ? stageOf(item, submitted) : '';
              const meta = STAGE_META[stage] || STAGE_META[''];
              const last = item?.recent_events?.[item.recent_events.length - 1];
              const action = prompt?.cases.find((c) => c.case_id === cid)?.action;
              return (
                <div
                  key={cid}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 10,
                    padding: '6px 10px',
                    border: '1px solid var(--border)',
                    borderRadius: 6,
                    fontSize: 12,
                  }}
                >
                  <span style={{ color: 'var(--text-muted)', fontFamily: 'monospace' }}>#{cid}</span>
                  <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {item?.title || '—'}
                    {!!item?.script_version && <span style={{ color: 'var(--text-muted)' }}> · v{item.script_version}</span>}
                  </span>
                  <span style={{ fontSize: 11, color: 'var(--text-muted)', maxWidth: 260, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={last?.message || item?.last_error || ''}>
                    {last?.message || item?.last_error || ''}
                  </span>
                  <span style={{ color: action === 'skip' ? 'var(--text-muted)' : meta.color, fontWeight: 600, whiteSpace: 'nowrap' }}>
                    {action === 'skip' ? t('ui.auto.triageSkip', '跳过') : meta.label}
                  </span>
                </div>
              );
            })}
          </div>
        </div>

        <div style={{ marginTop: 16, borderTop: '1px solid var(--border)', paddingTop: 10 }}>
          <button
            type="button"
            onClick={() => {
              setShowTokens((v) => !v);
              if (!showTokens) void refreshTokens();
            }}
            style={{ background: 'transparent', border: 'none', color: 'var(--text-secondary)', fontSize: 12, cursor: 'pointer', padding: 0 }}
          >
            {showTokens ? '▾' : '▸'} {t('ui.auto.mcpTokens', '接入令牌（{{count}}）', { count: tokens.length })}
          </button>
          {showTokens && (
            <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
              {tokens.length === 0 && <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>—</span>}
              {tokens.map((tk) => (
                <div key={tk.id} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
                  <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {tk.name} <code style={{ color: 'var(--text-muted)' }}>{tk.prefix}</code>
                  </span>
                  <span style={{ color: tk.active ? '#22c55e' : 'var(--text-muted)', fontSize: 11 }}>
                    {tk.revoked ? t('ui.auto.tokenRevokedState', '已吊销') : tk.expired ? t('ui.auto.tokenExpired', '已过期') : t('ui.auto.tokenActive', '有效')}
                  </span>
                  <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>{(tk.expires_at || '').slice(0, 10)}</span>
                  {tk.active && (
                    <Btn size="sm" variant="ghost" title={t('ui.auto.revokeToken', '吊销')} onClick={() => void handleRevoke(tk.id)}>
                      <ShieldOff size={12} />
                    </Btn>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </Modal>
  );
}
