import { useEffect, useState, type CSSProperties, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Play, Sparkles, Wrench, X, Copy } from 'lucide-react';
import { useConfirmStore } from '../../../../shared/store/confirmStore';
import { useAutomationStore, type AutomationCase, type GenerationRecord, type ScriptRun } from '../../store/automationStore';
import { Btn, ErrorCategoryTag, Field, StatusBadge, inputStyle, STATUS_META } from './common';

const BASE = '/api/modules/ui/automation';
const ACTIVE = new Set(['generating', 'fixing', 'running']);
type Tab = 'snapshot' | 'script' | 'runs' | 'generations';

export function CaseDetailDrawer({ caseId, onClose }: { caseId: number | null; onClose: () => void }) {
  const { t } = useTranslation();
  const { confirm } = useConfirmStore();
  const { getCase, getScript, listRuns, listGenerations, updateCase, generate, fix, run } = useAutomationStore();
  const [detail, setDetail] = useState<AutomationCase | null>(null);
  const [script, setScript] = useState<{ content: string; version: number }>({ content: '', version: 0 });
  const [runs, setRuns] = useState<ScriptRun[]>([]);
  const [gens, setGens] = useState<GenerationRecord[]>([]);
  const [tab, setTab] = useState<Tab>('snapshot');
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({ title: '', precondition: '', steps: '', expected: '' });
  const [submitting, setSubmitting] = useState(false);

  const refresh = async (id: number) => {
    const c = await getCase(id);
    setDetail(c);
    setForm({
      title: c.title,
      precondition: c.precondition,
      steps: (c.steps || []).join('\n'),
      expected: c.expected,
    });
    setScript(await getScript(id).catch(() => ({ content: '', version: 0 })));
    setRuns(await listRuns(id).catch(() => []));
    setGens(await listGenerations(id).catch(() => []));
  };

  useEffect(() => {
    if (caseId === null) {
      setDetail(null);
      setEditing(false);
      setTab('snapshot');
      return;
    }
    refresh(caseId).catch((e) => toast.error((e as Error).message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [caseId]);

  useEffect(() => {
    if (caseId === null || !detail || !ACTIVE.has(detail.status)) return;
    const timer = setInterval(() => {
      refresh(caseId).catch(() => undefined);
    }, 3000);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [caseId, detail?.status]);

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
    const next = detail.site === 'backend' ? 'frontend' : 'backend';
    if (detail.has_script || detail.status === 'implemented') {
      confirm({
        title: t('ui.auto.switchSite', '切换端'),
        message: t(
          'ui.auto.switchSiteConfirm',
          '切换端会改变入口地址，旧脚本将归档，需要重新生成脚本。确定继续吗？',
        ),
        onConfirm: () => void toggleSite(next),
      });
      return;
    }
    void toggleSite(next);
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
                title={t('ui.auto.switchSiteHint', '点击切换前台/后台')}
                style={{
                  padding: '1px 6px',
                  borderRadius: 9,
                  border: '1px solid var(--border)',
                  color: detail.site === 'backend' ? 'var(--accent)' : 'var(--text-secondary)',
                  cursor: active ? 'not-allowed' : 'pointer',
                }}
              >
                {siteLabel(detail.site)}
              </span>
            </div>
          </div>
          <StatusBadge status={detail.status} label={statusLabel(detail.status)} />
          <Btn size="sm" variant="primary" disabled={active || submitting} onClick={() => act(generate, t('ui.auto.generateQueued', '已提交生成任务'))}>
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
            </div>
          )}

          {tab === 'runs' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {runs.length === 0 && <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{t('ui.auto.noRuns', '暂无执行记录')}</div>}
              {runs.map((r) => (
                <div key={r.id} style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 10, fontSize: 12 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ color: r.status === 'passed' ? 'var(--success)' : 'var(--error)', fontWeight: 600 }}>
                      {r.status === 'passed' ? t('ui.auto.pass', '通过') : t('ui.auto.fail', '失败')}
                    </span>
                    <span style={{ color: 'var(--text-muted)' }}>#{r.id}</span>
                    <span style={{ color: 'var(--text-muted)' }}>{r.started_at?.replace('T', ' ').slice(0, 19)}</span>
                    <span style={{ color: 'var(--text-muted)' }}>{r.duration_ms} ms</span>
                    <span style={{ color: 'var(--text-muted)' }}>v{r.script_version ?? 0}</span>
                    <div style={{ flex: 1 }} />
                    <a href={artifactUrl(r.id, r.status === 'passed' ? 'final.png' : 'failure.png')} target="_blank" rel="noreferrer" style={linkStyle}>
                      {t('ui.auto.finalScreenshot', '终态截图')}
                    </a>
                    {r.status !== 'passed' && (
                      <a href={artifactUrl(r.id, 'final.png')} target="_blank" rel="noreferrer" style={linkStyle}>
                        {t('ui.auto.failureScreenshot', '失败截图')}
                      </a>
                    )}
                    {r.trace_rel_path && (
                      <a href={artifactUrl(r.id, 'trace.zip')} style={linkStyle}>
                        Trace
                      </a>
                    )}
                  </div>
                  {r.error && <pre style={{ ...preStyle, marginTop: 8 }}>{r.error}</pre>}
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
                    <span style={{ color: 'var(--text-muted)' }}>{g.started_at?.replace('T', ' ').slice(0, 19)}</span>
                  </div>
                  {g.error_message && <pre style={{ ...preStyle, marginTop: 8 }}>{g.error_message}</pre>}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
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
