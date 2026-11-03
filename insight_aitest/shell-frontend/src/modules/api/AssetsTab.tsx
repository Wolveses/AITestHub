import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Bot, FilePlus2, Loader2, RefreshCw, Trash2, VolumeX } from 'lucide-react';
import { useProjectStore } from '../../shared/store/projectStore';
import { useIsMobile } from '../../shared/hooks/useIsMobile';
import { useAssetStore, type ApiAsset, type AiMeta, type EnhanceProgress, fetchEnhanceProgress } from './store/assetStore';

const METHODS = ['', 'GET', 'POST', 'PUT', 'PATCH', 'DELETE'];

function methodColor(method: string) {
  switch (method.toUpperCase()) {
    case 'GET':
      return '#3b82f6';
    case 'POST':
      return '#16a34a';
    case 'PUT':
      return '#d97706';
    case 'PATCH':
      return '#a855f7';
    case 'DELETE':
      return '#dc2626';
    default:
      return 'var(--text-secondary)';
  }
}

function pretty(value: unknown): string {
  if (value == null) return '';
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

const boxStyle: CSSProperties = {
  background: 'var(--bg-card)',
  borderRadius: 4,
  padding: 8,
  fontSize: 12,
  fontFamily: 'monospace',
  whiteSpace: 'pre-wrap',
  wordBreak: 'break-all',
  maxHeight: 260,
  overflow: 'auto',
};

const inputStyle: CSSProperties = {
  background: 'var(--bg-card)',
  color: 'var(--text-primary)',
  border: '1px solid var(--bg-card)',
  borderRadius: 4,
  padding: '4px 8px',
  fontSize: 12,
};

const btnStyle = (disabled = false): CSSProperties => ({
  background: 'var(--bg-card)',
  color: 'var(--text-primary)',
  border: '1px solid var(--bg-card)',
  borderRadius: 4,
  padding: '4px 10px',
  fontSize: 12,
  cursor: disabled ? 'not-allowed' : 'pointer',
  opacity: disabled ? 0.5 : 1,
  display: 'inline-flex',
  alignItems: 'center',
  gap: 4,
});

export function AssetsTab() {
  const { t } = useTranslation();
  const currentProjectId = useProjectStore((s) => s.currentProjectId);
  const isMobile = useIsMobile();
  const {
    items, total, loading, selectedId, checkedIds,
    loadAssets, selectAsset, updateAsset, deleteAsset, enhanceAsset, toCase,
    toggleCheck, setChecked, deleteChecked,
  } = useAssetStore();

  const [method, setMethod] = useState('');
  const [keyword, setKeyword] = useState('');
  const [hideNoise, setHideNoise] = useState(true);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [busy, setBusy] = useState(false);
  const [enhancing, setEnhancing] = useState(false);
  const [meta, setMeta] = useState<AiMeta | null>(null);
  const [progress, setProgress] = useState<EnhanceProgress | null>(null);
  const prevRunning = useRef(false);

  const query = useMemo(
    () => ({ project_id: currentProjectId, method, keyword, hide_noise: hideNoise, page, page_size: pageSize }),
    [currentProjectId, method, keyword, hideNoise, page, pageSize],
  );

  useEffect(() => { loadAssets(query).catch((e) => toast.error(String(e))); }, [loadAssets, query]);

  useEffect(() => { setMeta(null); }, [selectedId]);

  // 轮询后台自动整理进度：运行中每 2 秒刷新，结束后重载列表并提示
  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    const tick = async () => {
      try {
        const p = await fetchEnhanceProgress(currentProjectId);
        if (cancelled) return;
        setProgress(p);
        if (p.status === 'running') {
          prevRunning.current = true;
          timer = window.setTimeout(tick, 2000);
        } else if (prevRunning.current) {
          prevRunning.current = false;
          const st = useAssetStore.getState();
          await st.loadAssets(st.lastQuery);
          if (p.done > 0) toast.success(t('api.aiAutoDone', { count: p.done }));
        }
      } catch {
        if (!cancelled) timer = window.setTimeout(tick, 5000);
      }
    };
    tick();
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [currentProjectId, t]);

  const selected: ApiAsset | undefined = items.find((it) => it.id === selectedId);
  const pages = Math.max(1, Math.ceil(total / pageSize));

  const refresh = () => loadAssets(query).catch((e) => toast.error(String(e)));

  const run = async (action: () => Promise<void>, okMsg?: string) => {
    setBusy(true);
    try {
      await action();
      if (okMsg) toast.success(okMsg);
    } catch (e) {
      toast.error(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: isMobile ? 'column' : 'row', overflow: 'hidden' }}>
      <div style={{
        width: isMobile ? '100%' : 460,
        borderRight: isMobile ? 'none' : '1px solid var(--bg-card)',
        borderBottom: isMobile ? '1px solid var(--bg-card)' : 'none',
        display: 'flex', flexDirection: 'column', minHeight: 0,
        ...(isMobile ? { maxHeight: 360 } : {}),
      }}>
        <div style={{ padding: '8px 12px', borderBottom: '1px solid var(--bg-card)', display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' }}>
          <span style={{ fontSize: 13, color: 'var(--text-secondary)', marginRight: 4 }}>{t('api.assetsTitle')}</span>
          <select style={inputStyle} value={method} onChange={(e) => {
            setMethod(e.target.value);
            setPage(1);
          }}>
            {METHODS.map((m) => <option key={m} value={m}>{m || t('api.allMethods')}</option>)}
          </select>
          <input
            style={{ ...inputStyle, width: 140 }}
            placeholder={t('api.searchPath')}
            value={keyword}
            onChange={(e) => { setKeyword(e.target.value); setPage(1); }}
          />
          <label style={{ fontSize: 12, color: 'var(--text-secondary)', display: 'inline-flex', alignItems: 'center', gap: 4 }}>
            <input type="checkbox" checked={hideNoise} onChange={(e) => { setHideNoise(e.target.checked); setPage(1); }} />
            {t('api.hideNoise')}
          </label>
          {items.length > 0 && (
            <label style={{ fontSize: 12, color: 'var(--text-secondary)', display: 'inline-flex', alignItems: 'center', gap: 4 }}>
              <input
                type="checkbox"
                checked={items.every((it) => checkedIds.includes(it.id))}
                onChange={(e) => setChecked(
                  e.target.checked
                    ? Array.from(new Set([...checkedIds, ...items.map((it) => it.id)]))
                    : checkedIds.filter((id) => !items.some((it) => it.id === id)),
                )}
              />
              {t('api.selectAll')}
            </label>
          )}
          {checkedIds.length > 0 && (
            <button style={btnStyle(busy)} disabled={busy} onClick={() => {
              if (!window.confirm(t('api.batchDeleteConfirm', { count: checkedIds.length }))) return;
              run(async () => {
                const deleted = await deleteChecked();
                toast.success(`${t('api.deleteDone')}（${deleted}）`);
              });
            }}>
              <Trash2 size={12} strokeWidth={1.5} /> {t('api.batchDelete')} ({checkedIds.length})
            </button>
          )}
          <button style={btnStyle(loading)} disabled={loading} onClick={refresh}>
            <RefreshCw size={12} strokeWidth={1.5} /> {t('api.refresh')}
          </button>
        </div>

        <div style={{ flex: 1, overflow: 'auto' }}>
          {loading && <div style={{ padding: 12, fontSize: 12, color: 'var(--text-muted)' }}>{t('api.loading')}</div>}
          {!loading && items.length === 0 && (
            <div style={{ padding: 16, fontSize: 12, color: 'var(--text-muted)' }}>{t('api.noAssets')}</div>
          )}
          {items.map((it) => {
            const active = it.id === selectedId
            const aiRunning = progress?.status === 'running' && progress.pending_ids.includes(it.id)
            const aiDone = progress?.done_ids.includes(it.id)
            return (
              <div
                key={it.id}
                onClick={() => selectAsset(it.id).catch((e) => toast.error(String(e)))}
                style={{
                  padding: '8px 12px',
                  paddingLeft: active ? 10 : 12,
                  borderBottom: '1px solid var(--bg-card)',
                  borderLeft: `2px solid ${active ? 'var(--accent)' : 'transparent'}`,
                  cursor: 'pointer',
                  background: active ? 'color-mix(in srgb, var(--accent) 12%, transparent)' : 'transparent',
                  opacity: active ? 1 : it.is_noise ? 0.55 : 1,
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
                  <input
                    type="checkbox"
                    checked={checkedIds.includes(it.id)}
                    onClick={(e) => e.stopPropagation()}
                    onChange={() => toggleCheck(it.id)}
                  />
                  <span style={{ color: methodColor(it.method), fontWeight: 700, minWidth: 46 }}>{it.method}</span>
                  <span style={{
                    flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                    color: active ? 'var(--accent)' : undefined,
                    fontWeight: active ? 600 : 400,
                  }}>{it.path_template || it.path}</span>
                  <span style={{ color: 'var(--text-muted)' }}>{it.response_status}</span>
                </div>
                <div style={{ display: 'flex', gap: 8, marginTop: 2, fontSize: 11, color: 'var(--text-muted)' }}>
                  <span>{it.title || it.fingerprint}</span>
                  <span>×{it.times_seen}</span>
                  {it.is_noise && <span>{t('api.noiseTag')}</span>}
                  {aiRunning
                    ? <span style={{ color: '#d97706', fontWeight: 600 }}>{t('api.aiRowRunning')}</span>
                    : (it.ai_meta || aiDone) && <span>{t('api.aiTag')}</span>}
                </div>
              </div>
            )
          })}
        </div>

        <div style={{ padding: '6px 12px', borderTop: '1px solid var(--bg-card)', display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: 'var(--text-secondary)' }}>
          <span>{t('api.totalAssets', { total })}</span>
          {progress?.status === 'running' && (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, color: '#d97706' }}>
              <Loader2 size={12} className="animate-spin" />
              {t('api.aiAutoRunning', { done: progress.done + progress.failed, total: progress.total })}
            </span>
          )}
          <button style={btnStyle(page <= 1)} disabled={page <= 1} onClick={() => setPage(page - 1)}>‹</button>
          <span>{page}/{pages}</span>
          <button style={btnStyle(page >= pages)} disabled={page >= pages} onClick={() => setPage(page + 1)}>›</button>
        </div>
      </div>

      <div style={{ flex: 1, minWidth: 0, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
        <div style={{ padding: '8px 16px', borderBottom: '1px solid var(--bg-card)', display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 13, flex: 1, minWidth: 80 }}>{selected ? `${selected.method} ${selected.path_template || selected.path}` : t('api.selectAsset')}</span>
          {progress?.status === 'running' && selected && progress.pending_ids.includes(selected.id) && (
            <span style={{ fontSize: 11, color: '#d97706', display: 'inline-flex', alignItems: 'center', gap: 4 }}>
              <Loader2 size={11} className="animate-spin" /> {t('api.aiEnhancingDetail')}
            </span>
          )}
          {selected && (
            <>
              <button style={btnStyle(busy || enhancing)} disabled={busy || enhancing} onClick={async () => {
                setEnhancing(true);
                setMeta(null);
                toast.loading(t('api.aiEnhancing'), { id: 'asset-enhance' });
                try {
                  const result = await enhanceAsset(selected.id);
                  setMeta(result);
                  toast.success(t('api.enhanceDone'), { id: 'asset-enhance' });
                } catch (e) {
                  toast.error(String(e), { id: 'asset-enhance' });
                } finally {
                  setEnhancing(false);
                }
              }}>
                {enhancing
                  ? <Loader2 size={12} strokeWidth={1.5} className="animate-spin" />
                  : <Bot size={12} strokeWidth={1.5} />}
                {enhancing ? t('api.aiEnhancing') : t('api.aiEnhance')}
              </button>
              <button style={btnStyle(busy)} disabled={busy} onClick={() => run(async () => {
                await updateAsset(selected.id, { is_noise: !selected.is_noise });
              }, selected.is_noise ? t('api.unmarkNoise') : t('api.markNoise'))}>
                <VolumeX size={12} strokeWidth={1.5} /> {selected.is_noise ? t('api.unmarkNoise') : t('api.markNoise')}
              </button>
              <button style={btnStyle(busy)} disabled={busy} onClick={() => run(async () => {
                const caseId = await toCase(selected.id);
                toast.success(t('api.toCaseDone', { id: caseId }));
              })}>
                <FilePlus2 size={12} strokeWidth={1.5} /> {t('api.toCase')}
              </button>
              <button style={btnStyle(busy)} disabled={busy} onClick={() => run(async () => {
                await deleteAsset(selected.id);
                toast.success(t('api.deleteDone'));
              })}>
                <Trash2 size={12} strokeWidth={1.5} /> {t('api.delete')}
              </button>
            </>
          )}
        </div>

        <div style={{ flex: 1, overflow: 'auto', padding: 16 }}>
          {!selected && <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{t('api.selectAssetHint')}</div>}
          {selected && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              {enhancing && (
                <div style={{ border: '1px solid var(--accent)', borderRadius: 6, padding: 12, fontSize: 12, color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Loader2 size={14} className="animate-spin" />
                  {t('api.aiEnhancingHint')}
                </div>
              )}
              {meta && (
                <div style={{ border: '1px dashed var(--accent)', borderRadius: 6, padding: 12, fontSize: 12, lineHeight: 1.7 }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
                    <strong>{t('api.aiSuggest')} <span style={{ color: 'var(--accent)', fontWeight: 400 }}>（{t('api.aiPending')}）</span></strong>
                    <button style={btnStyle(busy)} disabled={busy} onClick={() => run(async () => {
                      await updateAsset(selected.id, {
                        title: meta.title,
                        path_template: meta.path_template,
                        is_noise: meta.is_noise,
                        ai_meta: meta,
                      });
                      // 清除未应用建议，改由「AI 整理结果（已保存）」实时展示
                      setMeta(null);
                      toast.success(t('api.applyDone'));
                    })}>{t('api.apply')}</button>
                  </div>
                  {meta.title && <div>{t('api.assetName')}：{meta.title}</div>}
                  {meta.summary && <div>{t('api.summary')}：{meta.summary}</div>}
                  {meta.path_template && <div>{t('api.pathTemplate')}：{meta.path_template}</div>}
                  {meta.is_noise && <div>{t('api.noiseReason')}：{meta.noise_reason || '-'}</div>}
                  {meta.variables?.length ? (
                    <div>{t('api.variables')}：{meta.variables.map((v) => v.name).join(', ')}</div>
                  ) : null}
                  {meta.model && <div style={{ color: 'var(--text-muted)' }}>{t('api.model')}：{meta.model}</div>}
                </div>
              )}

              {selected.ai_meta && !meta && (
                <div style={{ border: '1px solid var(--bg-card)', borderRadius: 6, padding: 12, fontSize: 12, lineHeight: 1.7 }}>
                  <strong style={{ display: 'block', marginBottom: 6 }}>{t('api.aiResultSaved')}</strong>
                  {selected.ai_meta.title && <div>{t('api.assetName')}：{selected.ai_meta.title}</div>}
                  {selected.ai_meta.summary && <div>{t('api.summary')}：{selected.ai_meta.summary}</div>}
                  {selected.ai_meta.path_template && <div>{t('api.pathTemplate')}：{selected.ai_meta.path_template}</div>}
                  {selected.ai_meta.is_noise && <div>{t('api.noiseReason')}：{selected.ai_meta.noise_reason || '-'}</div>}
                  {selected.ai_meta.variables?.length ? (
                    <div>{t('api.variables')}：{selected.ai_meta.variables.map((v) => v.name).join(', ')}</div>
                  ) : null}
                  {selected.ai_meta.model && <div style={{ color: 'var(--text-muted)' }}>{t('api.model')}：{selected.ai_meta.model}</div>}
                </div>
              )}

              <div>
                <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginBottom: 4 }}>
                  {t('api.request')} · {selected.base_url}{selected.path}
                </div>
                <div style={boxStyle}>
                  {pretty(selected.headers)}
                  {selected.body != null && `\n\n${pretty(selected.body)}`}
                </div>
              </div>

              <div>
                <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginBottom: 4 }}>
                  {t('api.response')} · {selected.response_status} · {selected.response_content_type}
                  {selected.body_truncated && `（${t('api.truncated')}）`}
                </div>
                <div style={boxStyle}>{pretty(selected.response_body) || t('api.emptyBody')}</div>
              </div>

              {selected.jsonpath_samples.length > 0 && (
                <div>
                  <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginBottom: 4 }}>{t('api.jsonPathSamples')}</div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 2, fontSize: 12 }}>
                    {selected.jsonpath_samples.map((s) => (
                      <div key={s.path} style={{ display: 'flex', gap: 8 }}>
                        <span style={{ fontFamily: 'monospace', minWidth: 200 }}>{s.path}</span>
                        <span style={{ color: 'var(--text-muted)' }}>{s.type}</span>
                        <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{pretty(s.sample)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                {t('api.assetMeta', { times: selected.times_seen, first: selected.first_seen_at, last: selected.last_seen_at })}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
