import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Play, Sparkles, Wrench, X, Copy, FileCode } from 'lucide-react';
import { useAutomationStore, type AutomationCase, type GenerationRecord, type ScriptRun } from '../../store/automationStore';
import { Btn, ErrorCategoryTag, Field, StatusBadge, inputStyle, STATUS_META } from './common';

const BASE = '/api/modules/ui/automation';
const ACTIVE = new Set(['generating', 'fixing', 'running']);
type Tab = 'snapshot' | 'script' | 'runs' | 'generations';
type ScriptPreview = { content: string; version: number; pages: { name: string; path?: string; content: string }[] };

export function CaseDetailDrawer({ caseId, onClose }: { caseId: number | null; onClose: () => void }) {
  const { t } = useTranslation();
  const { getCase, getScript, listRuns, listGenerations, updateCase, generate, fix, run } = useAutomationStore();
  const [detail, setDetail] = useState<AutomationCase | null>(null);
  const [script, setScript] = useState<ScriptPreview>({ content: '', version: 0, pages: [] });
  const [runs, setRuns] = useState<ScriptRun[]>([]);
  const [gens, setGens] = useState<GenerationRecord[]>([]);
  const [tab, setTab] = useState<Tab>('snapshot');
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({ title: '', precondition: '', steps: '', expected: '' });
  const [submitting, setSubmitting] = useState(false);
  const [preview, setPreview] = useState<{ url: string; label: string } | null>(null);
  const [openRunLog, setOpenRunLog] = useState<number | null>(null);
  const [openGenLog, setOpenGenLog] = useState<number | null>(null);
  const [openRunError, setOpenRunError] = useState<number | null>(null);
  const [openGenError, setOpenGenError] = useState<number | null>(null);
  // 执行/生成记录里是否还有在跑的任务（决定是否继续轮询刷新列表与日志）
  const anyRunning = runs.some((r) => r.status === 'running') || gens.some((g) => g.status === 'running');

  const refresh = async (id: number) => {
    const c = await getCase(id);
    setDetail(c);
    setForm({
      title: c.title,
      precondition: c.precondition,
      steps: (c.steps || []).join('\n'),
      expected: c.expected,
    });
    setScript(await getScript(id).catch(() => ({ content: '', version: 0, pages: [] })));
    setRuns(await listRuns(id).catch(() => []));
    setGens(await listGenerations(id).catch(() => []));
  };

  useEffect(() => {
    if (caseId === null) {
      setDetail(null);
      setEditing(false);
      setTab('snapshot');
      setOpenRunLog(null);
      setOpenGenLog(null);
      setOpenRunError(null);
      setOpenGenError(null);
      return;
    }
    setOpenRunLog(null);
    setOpenGenLog(null);
    setOpenRunError(null);
    setOpenGenError(null);
    refresh(caseId).catch((e) => toast.error((e as Error).message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [caseId]);

  useEffect(() => {
    // 用例状态处于活跃态，或任一执行/生成记录仍在运行，都要保持轮询，
    // 否则执行刚结束的瞬间列表就停止刷新，状态会停在「执行中」
    if (caseId === null) return;
    const caseActive = detail !== null && ACTIVE.has(detail.status);
    if (!caseActive && !anyRunning) return;
    const timer = setInterval(() => {
      refresh(caseId).catch(() => undefined);
    }, 3000);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [caseId, detail?.status, anyRunning]);

  useEffect(() => {
    if (!preview) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setPreview(null);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [preview]);

  if (caseId === null || detail === null) return null;

  const active = ACTIVE.has(detail.status);
  const statusLabel = (s: string) => t(STATUS_META[s]?.labelKey || s, s);
  const errorLabel = (c: string | null) =>
    c === 'environment'
      ? t('ui.auto.errorCategoryEnvironment', '环境问题')
      : c === 'case_info'
        ? t('ui.auto.errorCategoryCase', '用例信息不完善')
        : c === 'model'
          ? t('ui.auto.errorCategoryModel', '模型问题')
          : c === 'script'
            ? t('ui.auto.errorCategoryScript', '脚本缺陷')
            : '';

  const act = async (fn: (id: number) => Promise<void>, msg: string) => {
    setSubmitting(true);
    try {
      await fn(detail.id);
      toast.success(msg);
      await refresh(detail.id);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  const save = async () => {
    setSubmitting(true);
    try {
      await updateCase(detail.id, {
        title: form.title,
        precondition: form.precondition,
        steps: form.steps.split('\n').map((s) => s.trim()).filter(Boolean),
        expected: form.expected,
      });
      toast.success(t('ui.auto.caseSaved', '用例已保存，状态回到未实现'));
      setEditing(false);
      await refresh(detail.id);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  const siteLabel = (s: string) =>
    s === 'backend' ? t('ui.auto.siteBackend', '后台') : t('ui.auto.siteFrontend', '前台');

  const toggleSite = async (next: string) => {
    setSubmitting(true);
    try {
      await updateCase(detail.id, { site: next });
      toast.success(t('ui.auto.siteSwitched', '已切换到{{site}}', { site: siteLabel(next) }));
      await refresh(detail.id);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  const handleSiteClick = () => {
    if (active || submitting) return;
    // 脚本按端入口生成，已产出脚本后不允许再切换
    if (detail.has_script || detail.status === 'implemented') {
      toast.info(t('ui.auto.siteLocked', '用例已生成脚本，端不可再切换'));
      return;
    }
    void toggleSite(detail.site === 'backend' ? 'frontend' : 'backend');
  };

  const artifactUrl = (runId: number, name: string) =>
    `${BASE}/cases/${detail.id}/runs/${runId}/artifact/${encodeURIComponent(name)}`;

  const tabs: { key: Tab; label: string }[] = [
    { key: 'snapshot', label: t('ui.auto.tabSnapshot', '用例快照') },
    { key: 'script', label: t('ui.auto.tabScript', '脚本') },
    { key: 'runs', label: `${t('ui.auto.tabRuns', '执行记录')}（${runs.length}）` },
    { key: 'generations', label: `${t('ui.auto.tabGenerations', '生成记录')}（${gens.length}）` },
  ];

  return (
    <>
      <div onClick={onClose} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.45)', zIndex: 1500 }} />
      <div
        style={{
          position: 'fixed',
          top: 0,
          right: 0,
          bottom: 0,
          width: 'min(820px, 96vw)',
          background: 'var(--bg-base)',
          borderLeft: '1px solid var(--border-strong)',
          zIndex: 1501,
          display: 'flex',
          flexDirection: 'column',
          boxShadow: '-8px 0 32px rgba(0,0,0,.35)',
        }}
      >
        <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 14, fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{detail.title}</div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 3, display: 'flex', alignItems: 'center', gap: 6 }}>
              <span>{detail.category_path || t('ui.auto.uncategorized', '未分类')}</span>
              {detail.source_case_id ? <span>· 用例 #{detail.source_case_id}</span> : null}
              <span
                onClick={handleSiteClick}
                title={
                  detail.has_script || detail.status === 'implemented'
                    ? t('ui.auto.siteLocked', '用例已生成脚本，端不可再切换')
                    : t('ui.auto.switchSiteHint', '点击切换前台/后台')
                }
                style={{
                  padding: '1px 6px',
                  borderRadius: 9,
                  border: '1px solid var(--border)',
                  color: detail.site === 'backend' ? 'var(--accent)' : 'var(--text-secondary)',
                  cursor: active || detail.has_script || detail.status === 'implemented' ? 'not-allowed' : 'pointer',
                  opacity: active || detail.has_script || detail.status === 'implemented' ? 0.5 : 1,
                }}
              >
                {siteLabel(detail.site)}
              </span>
            </div>
          </div>
          <StatusBadge status={detail.status} label={statusLabel(detail.status)} />
          <Btn
            size="sm"
            variant="primary"
            disabled={active || submitting}
            title={t('ui.auto.regenerateHint', '重新探索页面并生成脚本（会消耗模型额度）')}
            onClick={() => act((id) => generate(id), t('ui.auto.generateQueued', '已提交生成任务'))}
          >
            <Sparkles size={12} /> {detail.has_script ? t('ui.auto.regenerate', '重新生成') : t('ui.auto.generateScript', '生成脚本')}
          </Btn>
          <Btn size="sm" disabled={active || submitting || detail.status !== 'implemented'} onClick={() => act(run, t('ui.auto.runQueued', '已提交执行任务'))}>
            <Play size={12} /> {t('ui.auto.runScript', '执行')}
          </Btn>
          <Btn size="sm" disabled={active || submitting || detail.status !== 'implemented'} onClick={() => act(fix, t('ui.auto.fixQueued', '已提交修复任务'))}>
            <Wrench size={12} /> {t('ui.auto.autoFix', '自动修复')}
          </Btn>
          <Btn size="sm" variant="ghost" onClick={onClose} title={t('ui.auto.close', '关闭')}>
            <X size={15} />
          </Btn>
        </div>

        {detail.progress && active && (
          <div style={{ padding: '6px 16px', background: 'var(--bg-card)', fontSize: 11, color: 'var(--text-muted)' }}>
            {detail.progress.phase} · {detail.progress.message}
          </div>
        )}

        <div style={{ display: 'flex', gap: 4, padding: '8px 16px 0', borderBottom: '1px solid var(--border)' }}>
          {tabs.map((item) => (
            <button
              key={item.key}
              onClick={() => setTab(item.key)}
              style={{
                background: 'transparent',
                border: 'none',
                borderBottom: tab === item.key ? '2px solid var(--accent)' : '2px solid transparent',
                color: tab === item.key ? 'var(--text-primary)' : 'var(--text-muted)',
                padding: '6px 10px',
                cursor: 'pointer',
                fontSize: 12,
                marginBottom: -1,
              }}
            >
              {item.label}
            </button>
          ))}
        </div>

        <div style={{ flex: 1, overflowY: 'auto', padding: 16 }}>
          {tab === 'snapshot' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {!editing ? (
                <>
                  <Section title={t('ui.auto.precondition', '前置条件')}>{detail.precondition || '—'}</Section>
                  <Section title={t('ui.auto.steps', '测试步骤')}>
                    {detail.steps.length === 0 ? (
                      '—'
                    ) : (
                      <ol style={{ margin: 0, paddingLeft: 18 }}>
                        {detail.steps.map((s, i) => (
                          <li key={i} style={{ marginBottom: 3 }}>{s}</li>
                        ))}
                      </ol>
                    )}
                  </Section>
                  <Section title={t('ui.auto.expected', '预期结果')}>{detail.expected || '—'}</Section>
                  {detail.last_error_message && (
                    <div style={{ fontSize: 12 }}>
                      <div style={{ color: 'var(--text-muted)', marginBottom: 4, display: 'flex', gap: 6, alignItems: 'center' }}>
                        {t('ui.auto.lastError', '最近失败')}
                        <ErrorCategoryTag category={detail.last_error_category} label={errorLabel(detail.last_error_category)} />
                      </div>
                      <pre style={preStyle}>{detail.last_error_message}</pre>
                    </div>
                  )}
                  <div>
                    <Btn size="sm" onClick={() => setEditing(true)} disabled={active}>
                      {t('ui.auto.editCase', '编辑用例快照')}
                    </Btn>
                  </div>
                </>
              ) : (
                <>
                  <Field label={t('ui.auto.caseTitle', '用例标题')}>
                    <input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} style={inputStyle} />
                  </Field>
                  <Field label={t('ui.auto.precondition', '前置条件')}>
                    <textarea rows={3} value={form.precondition} onChange={(e) => setForm({ ...form, precondition: e.target.value })} style={textareaStyle} />
                  </Field>
                  <Field label={t('ui.auto.stepsOneLine', '测试步骤（每行一步）')}>
                    <textarea rows={7} value={form.steps} onChange={(e) => setForm({ ...form, steps: e.target.value })} style={textareaStyle} />
                  </Field>
                  <Field label={t('ui.auto.expected', '预期结果')}>
                    <textarea rows={4} value={form.expected} onChange={(e) => setForm({ ...form, expected: e.target.value })} style={textareaStyle} />
                  </Field>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                    {t('ui.auto.editResetHint', '保存后用例状态回到「未实现」，需重新生成脚本。')}
                  </div>
                  <div style={{ display: 'flex', gap: 8 }}>
                    <Btn variant="primary" onClick={save} disabled={submitting}>{t('ui.auto.save', '保存')}</Btn>
                    <Btn onClick={() => setEditing(false)}>{t('ui.auto.cancel', '取消')}</Btn>
                  </div>
                </>
              )}
            </div>
          )}

          {tab === 'script' && (
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                  {t('ui.auto.scriptVersion', '脚本版本')} v{script.version}
                </span>
                <Btn
                  size="sm"
                  disabled={!script.content}
                  onClick={() => {
                    navigator.clipboard.writeText(script.content);
                    toast.success(t('ui.auto.copied', '已复制'));
                  }}
                >
                  <Copy size={12} /> {t('ui.auto.copy', '复制')}
                </Btn>
              </div>
              {script.content ? (
                <pre style={{ ...preStyle, maxHeight: 'none' }}>{script.content}</pre>
              ) : (
                <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{t('ui.auto.noScript', '尚未生成脚本')}</div>
              )}
              {script.pages.length > 0 && (
                <div style={{ marginTop: 12 }}>
                  <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 6 }}>
                    {t('ui.auto.relatedPages', '相关公共代码')} · {script.pages.length}
                  </div>
                  {script.pages.map((pg) => (
                    <details
                      key={pg.path || pg.name}
                      style={{
                        border: '1px solid var(--border)',
                        borderRadius: 8,
                        padding: '6px 10px',
                        marginBottom: 8,
                      }}
                    >
                      <summary
                        style={{ cursor: 'pointer', fontSize: 12, display: 'flex', alignItems: 'center', gap: 6 }}
                      >
                        <FileCode size={12} />
                        <span style={{ flex: 1 }}>{pg.path || `pages/${pg.name}`}</span>
                        <Btn
                          size="sm"
                          onClick={(e) => {
                            e.preventDefault();
                            navigator.clipboard.writeText(pg.content);
                            toast.success(t('ui.auto.copied', '已复制'));
                          }}
                        >
                          <Copy size={12} /> {t('ui.auto.copy', '复制')}
                        </Btn>
                      </summary>
                      <pre style={{ ...preStyle, marginTop: 8 }}>{pg.content}</pre>
                    </details>
                  ))}
                </div>
              )}
            </div>
          )}

          {tab === 'runs' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {runs.length === 0 && <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{t('ui.auto.noRuns', '暂无执行记录')}</div>}
              {runs.map((r) => (
                <div key={r.id} style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 10, fontSize: 12 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span
                      style={{
                        color: r.status === 'passed' ? 'var(--success)' : r.status === 'running' ? 'var(--info)' : 'var(--error)',
                        fontWeight: 600,
                      }}
                    >
                      {r.status === 'passed'
                        ? t('ui.auto.pass', '通过')
                        : r.status === 'running'
                          ? t('ui.auto.statusRunning', '执行中')
                          : t('ui.auto.fail', '失败')}
                    </span>
                    <span style={{ color: 'var(--text-muted)' }}>#{r.id}</span>
                    <span style={{ color: 'var(--text-muted)' }}>{r.started_at?.replace('T', ' ').slice(0, 19)}</span>
                    <span style={{ color: 'var(--text-muted)' }}>{r.duration_ms} ms</span>
                    <span style={{ color: 'var(--text-muted)' }}>v{r.script_version ?? 0}</span>
                    <div style={{ flex: 1 }} />
                    {r.error && (
                      <button
                        type="button"
                        style={linkButtonStyle}
                        onClick={() => setOpenRunError(openRunError === r.id ? null : r.id)}
                      >
                        {t('ui.auto.failureReason', '失败原因')}
                      </button>
                    )}
                    <button
                      type="button"
                      style={linkButtonStyle}
                      onClick={() => setOpenRunLog(openRunLog === r.id ? null : r.id)}
                    >
                      {t('ui.auto.runLog', '查看日志')}
                    </button>
                    {(() => {
                      const shot = r.status === 'passed'
                        ? { name: 'final.png', label: t('ui.auto.finalScreenshot', '终态截图') }
                        : { name: 'failure.png', label: t('ui.auto.failureScreenshot', '失败截图') };
                      return (
                        <button
                          type="button"
                          style={linkButtonStyle}
                          onClick={() => setPreview({ url: artifactUrl(r.id, shot.name), label: `${shot.label} · #${r.id}` })}
                        >
                          {shot.label}
                        </button>
                      );
                    })()}
                    {r.status !== 'passed' && (
                      <button
                        type="button"
                        style={linkButtonStyle}
                        onClick={() => setPreview({ url: artifactUrl(r.id, 'final.png'), label: `${t('ui.auto.finalScreenshot', '终态截图')} · #${r.id}` })}
                      >
                        {t('ui.auto.finalScreenshot', '终态截图')}
                      </button>
                    )}
                    {r.trace_rel_path && (
                      <a href={artifactUrl(r.id, 'trace.zip')} style={linkStyle}>
                        Trace
                      </a>
                    )}
                  </div>
                  {r.error && openRunError === r.id && (
                    <pre style={{ ...preStyle, marginTop: 8 }}>{r.error}</pre>
                  )}
                  {openRunLog === r.id && (
                    <LogViewer url={`${BASE}/cases/${detail.id}/runs/${r.id}/log`} live={r.status === 'running'} />
                  )}
                </div>
              ))}
            </div>
          )}

          {tab === 'generations' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {gens.length === 0 && <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{t('ui.auto.noGenerations', '暂无生成记录')}</div>}
              {gens.map((g) => (
                <div key={g.id} style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 10, fontSize: 12 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ fontWeight: 600 }}>
                      {g.kind === 'fix' ? t('ui.auto.kindFix', '自动修复') : t('ui.auto.kindGenerate', '生成脚本')}
                    </span>
                    <span style={{ color: g.status === 'success' ? 'var(--success)' : g.status === 'running' ? 'var(--info)' : 'var(--error)' }}>
                      {g.status === 'success' ? t('ui.auto.pass', '通过') : g.status === 'running' ? t('ui.auto.statusRunning', '执行中') : t('ui.auto.fail', '失败')}
                    </span>
                    <ErrorCategoryTag category={g.error_category} label={errorLabel(g.error_category)} />
                    <span style={{ color: 'var(--text-muted)' }}>{g.tool_calls} {t('ui.auto.toolCalls', '次工具调用')}</span>
                    {(g.corpus_chars > 0 || g.prompt_chars > 0) && (
                      <span style={{ color: 'var(--text-muted)' }}>
                        {t('ui.auto.corpusChars', '语料')} {g.corpus_chars} · {t('ui.auto.promptChars', '输入')} {g.prompt_chars} · {t('ui.auto.completionChars', '输出')} {g.completion_chars}
                        {g.fix_rounds > 0 ? ` · ${t('ui.auto.fixRounds', '修复')} ${g.fix_rounds}` : ''}
                      </span>
                    )}
                    <span style={{ color: 'var(--text-muted)' }}>{g.started_at?.replace('T', ' ').slice(0, 19)}</span>
                    <div style={{ flex: 1 }} />
                    {g.error_message && (
                      <button
                        type="button"
                        style={linkButtonStyle}
                        onClick={() => setOpenGenError(openGenError === g.id ? null : g.id)}
                      >
                        {t('ui.auto.failureReason', '失败原因')}
                      </button>
                    )}
                    <button
                      type="button"
                      style={linkButtonStyle}
                      onClick={() => setOpenGenLog(openGenLog === g.id ? null : g.id)}
                    >
                      {t('ui.auto.generationLog', '查看日志')}
                    </button>
                  </div>
                  {g.error_message && openGenError === g.id && (
                    <pre style={{ ...preStyle, marginTop: 8 }}>{g.error_message}</pre>
                  )}
                  {openGenLog === g.id && (
                    <LogViewer url={`${BASE}/cases/${detail.id}/generations/${g.id}/log`} live={g.status === 'running'} />
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {preview && (
        <div
          onClick={() => setPreview(null)}
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 1600,
            background: 'rgba(0,0,0,.8)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: 24,
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{ display: 'flex', flexDirection: 'column', gap: 8, maxWidth: '94vw', maxHeight: '94vh' }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: '#fff', fontSize: 12 }}>
              <span style={{ flex: 1 }}>{preview.label}</span>
              <a href={preview.url} target="_blank" rel="noreferrer" style={{ color: '#fff', fontSize: 11, textDecoration: 'none', opacity: 0.85 }}>
                {t('ui.auto.openOriginal', '新窗口打开')}
              </a>
              <button
                type="button"
                onClick={() => setPreview(null)}
                aria-label={t('common.close', '关闭')}
                style={{ ...linkButtonStyle, color: '#fff', display: 'flex', alignItems: 'center' }}
              >
                <X size={16} />
              </button>
            </div>
            <img
              src={preview.url}
              alt={preview.label}
              style={{ maxWidth: '94vw', maxHeight: '86vh', objectFit: 'contain', borderRadius: 8, background: '#111' }}
            />
          </div>
        </div>
      )}
    </>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div style={{ fontSize: 12 }}>
      <div style={{ color: 'var(--text-muted)', marginBottom: 4 }}>{title}</div>
      <div style={{ lineHeight: 1.7 }}>{children}</div>
    </div>
  );
}

const preStyle: CSSProperties = {
  margin: 0,
  padding: 10,
  borderRadius: 6,
  background: 'var(--bg-card)',
  border: '1px solid var(--border)',
  fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
  fontSize: 11,
  lineHeight: 1.6,
  whiteSpace: 'pre-wrap',
  wordBreak: 'break-word',
  maxHeight: 360,
  overflowY: 'auto',
};

const textareaStyle: CSSProperties = { ...inputStyle, resize: 'vertical', fontFamily: 'inherit' };

const linkStyle: CSSProperties = { color: 'var(--accent)', fontSize: 11, textDecoration: 'none' };
const linkButtonStyle: CSSProperties = {
  ...linkStyle,
  background: 'none',
  border: 'none',
  padding: 0,
  cursor: 'pointer',
  font: 'inherit',
};

/** 过程日志查看器：运行中按 2 秒轮询，结束后只拉一次。 */
function LogViewer({ url, live }: { url: string; live: boolean }) {
  const { t } = useTranslation();
  const [text, setText] = useState(t('ui.auto.logLoading', '日志加载中…'));
  const boxRef = useRef<HTMLPreElement>(null);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        // 加时间戳绕过浏览器缓存，保证运行中每次都能拿到追加后的内容
        const r = await fetch(`${url}?_t=${Date.now()}`);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const body = await r.text();
        if (alive) setText(body || t('ui.auto.logEmpty', '（暂无输出）'));
      } catch (e) {
        if (alive) setText(t('ui.auto.logLoadFailed', '日志加载失败：{{msg}}', { msg: (e as Error).message }));
      }
    };
    tick();
    const timer = live ? setInterval(tick, 2000) : undefined;
    return () => {
      alive = false;
      if (timer) clearInterval(timer);
    };
  }, [url, live, t]);

  useEffect(() => {
    if (live && boxRef.current) boxRef.current.scrollTop = boxRef.current.scrollHeight;
  }, [text, live]);

  return (
    <pre
      ref={boxRef}
      style={{ ...preStyle, marginTop: 8, maxHeight: 280, overflow: 'auto', whiteSpace: 'pre-wrap' }}
    >
      {text}
    </pre>
  );
}
