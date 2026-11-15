import { useEffect, useState, type ReactNode } from 'react';
import { Play, Save, Square, X } from 'lucide-react';
import { toast } from 'sonner';
import { Btn, ErrorCategoryTag, Field, StatusBadge, inputStyle } from './common';
import {
  runArtifactUrl,
  useMobileStore,
  type MobileCase,
  type MobileRunItem,
} from '../store/mobileStore';

type DrawerTab = 'snapshot' | 'script' | 'runs';

export function CaseDetailDrawer({
  targetCase,
  onClose,
}: {
  targetCase: MobileCase | null;
  onClose: () => void;
}) {
  const {
    devices,
    apps,
    updateCase,
    getScript,
    saveScript,
    runCase,
    getCaseRuns,
    getRunDetail,
    getRunLog,
    getRunDeviceLog,
    loadDevices,
    loadApps,
    cancelGenerate,
  } = useMobileStore();

  const [tab, setTab] = useState<DrawerTab>('snapshot');
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState('');
  const [precondition, setPrecondition] = useState('');
  const [stepsText, setStepsText] = useState('');
  const [expected, setExpected] = useState('');
  const [savingMeta, setSavingMeta] = useState(false);

  const [scriptContent, setScriptContent] = useState('');
  const [scriptVersion, setScriptVersion] = useState(0);
  const [savingScript, setSavingScript] = useState(false);

  const [runDeviceId, setRunDeviceId] = useState('');
  const [runAppId, setRunAppId] = useState<number | ''>('');
  const [running, setRunning] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [runs, setRuns] = useState<MobileRunItem[]>([]);
  const [selectedRun, setSelectedRun] = useState<MobileRunItem | null>(null);
  const [runLog, setRunLog] = useState('');
  const [deviceLog, setDeviceLog] = useState('');
  const [logMode, setLogMode] = useState<'stdout' | 'logcat'>('stdout');

  useEffect(() => {
    if (!targetCase) return;
    setEditing(false);
    setTab('snapshot');
    setTitle(targetCase.title || '');
    setPrecondition(targetCase.precondition || '');
    setStepsText((targetCase.steps || []).join('\n'));
    setExpected(targetCase.expected || '');
    setSelectedRun(null);
    setRunLog('');
    setDeviceLog('');
    void loadDevices();
    void loadApps();
    void getCaseRuns(targetCase.id).then(setRuns).catch(() => setRuns([]));
    if (targetCase.has_script) {
      void getScript(targetCase.id)
        .then((res) => {
          setScriptContent(res.content);
          setScriptVersion(res.version);
        })
        .catch(() => {
          setScriptContent('');
          setScriptVersion(0);
        });
    } else {
      setScriptContent('');
      setScriptVersion(0);
    }
  }, [targetCase, getCaseRuns, getScript, loadDevices, loadApps]);

  useEffect(() => {
    if (!targetCase) return;
    const idleDevice = devices.find((d) => d.status === 'online' && !d.busy);
    if (idleDevice && !runDeviceId) setRunDeviceId(idleDevice.device_id);
    const defaultApp =
      apps.find((a) => a.id === targetCase.default_app_id) ||
      apps.find((a) => a.is_default) ||
      apps[0];
    if (defaultApp && runAppId === '') setRunAppId(defaultApp.id);
  }, [targetCase, devices, apps, runDeviceId, runAppId]);

  if (!targetCase) return null;

  const isGenerating = targetCase.status === 'generating' || targetCase.status === 'fixing';
  const isActive = isGenerating || targetCase.status === 'running';

  const handleCancelGenerate = async () => {
    setCancelling(true);
    try {
      await cancelGenerate(targetCase.id);
      toast.info('已终止生成并释放设备');
    } catch (e) {
      toast.error(`终止失败: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setCancelling(false);
    }
  };

  const handleSaveMeta = async () => {
    setSavingMeta(true);
    try {
      await updateCase(targetCase.id, {
        title: title.trim(),
        precondition: precondition.trim(),
        steps: stepsText
          .split('\n')
          .map((s) => s.trim())
          .filter(Boolean),
        expected: expected.trim(),
      });
      setEditing(false);
      toast.success('用例快照已保存');
    } catch (e) {
      toast.error(`更新失败: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setSavingMeta(false);
    }
  };

  const handleSaveScript = async () => {
    setSavingScript(true);
    try {
      const res = await saveScript(targetCase.id, scriptContent);
      setScriptVersion(res.version);
      toast.success(`脚本已保存 (v${res.version})`);
    } catch (e) {
      toast.error(`保存脚本失败: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setSavingScript(false);
    }
  };

  const handleRun = async () => {
    if (!runDeviceId) {
      toast.warning('请先选择一台空闲设备');
      return;
    }
    setRunning(true);
    try {
      const res = await runCase(targetCase.id, {
        device_id: runDeviceId,
        app_id: runAppId === '' ? null : runAppId,
      });
      toast.success(`已提交执行任务 (Run #${res.run_id})`);
      setTab('runs');
      const nextRuns = await getCaseRuns(targetCase.id);
      setRuns(nextRuns);
      const latest = nextRuns.find((r) => r.id === res.run_id) || nextRuns[0];
      if (latest) void inspectRun(latest.id);
    } catch (e) {
      toast.error(`执行失败: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setRunning(false);
    }
  };

  const inspectRun = async (runId: number) => {
    try {
      const [detail, stdoutText, logcatText] = await Promise.all([
        getRunDetail(runId),
        getRunLog(runId).catch(() => ''),
        getRunDeviceLog(runId).catch(() => ''),
      ]);
      setSelectedRun(detail);
      setRunLog(stdoutText);
      setDeviceLog(logcatText);
    } catch (e) {
      toast.error(`读取运行详情失败: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  const tabs: { key: DrawerTab; label: string }[] = [
    { key: 'snapshot', label: '用例快照' },
    { key: 'script', label: scriptVersion > 0 ? `脚本 (v${scriptVersion})` : '脚本' },
    { key: 'runs', label: `执行记录（${runs.length}）` },
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
        <div
          style={{
            padding: '12px 16px',
            borderBottom: '1px solid var(--border)',
            display: 'flex',
            flexDirection: 'column',
            gap: 10,
          }}
        >
          {/* 第一行：标题、目录、ID 与状态 + 关闭按钮 */}
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                <span title={targetCase.title} style={{ fontSize: 15, fontWeight: 600, lineHeight: 1.4, wordBreak: 'break-word' }}>
                  {targetCase.title}
                </span>
                <StatusBadge status={targetCase.status} />
                {targetCase.script_version > 0 && (
                  <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>v{targetCase.script_version}</span>
                )}
              </div>
              <div
                style={{
                  fontSize: 11,
                  color: 'var(--text-muted)',
                  marginTop: 4,
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                  flexWrap: 'wrap',
                }}
              >
                <span>{targetCase.category_path || '未分类'}</span>
                <span>·</span>
                <span style={{ fontFamily: 'monospace' }}>ID #{targetCase.id}</span>
                {targetCase.source_case_id ? (
                  <>
                    <span>·</span>
                    <span>源用例 #{targetCase.source_case_id}</span>
                  </>
                ) : null}
              </div>
            </div>
            <Btn size="sm" variant="ghost" onClick={onClose} title="关闭">
              <X size={15} />
            </Btn>
          </div>

          {/* 第二行：操作栏与执行设备/App 选择 */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <select
              style={{ ...inputStyle, width: 220 }}
              value={runDeviceId}
              onChange={(e) => setRunDeviceId(e.target.value)}
            >
              <option value="">选择执行设备</option>
              {devices.map((d) => (
                <option key={d.device_id} value={d.device_id} disabled={d.busy}>
                  {d.model || d.name || d.device_id} ({d.type} · {d.device_id}) {d.busy ? '[占用]' : ''}
                </option>
              ))}
            </select>
            <select
              style={{ ...inputStyle, width: 170 }}
              value={runAppId}
              onChange={(e) => setRunAppId(e.target.value ? Number(e.target.value) : '')}
            >
              <option value="">默认 App 环境</option>
              {apps.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
            <Btn
              size="sm"
              variant="primary"
              disabled={isActive || running || !targetCase.has_script || !runDeviceId}
              onClick={() => void handleRun()}
            >
              <Play size={12} /> {running ? '执行中…' : '执行'}
            </Btn>
            {isGenerating && (
              <Btn size="sm" variant="danger" disabled={cancelling} onClick={() => void handleCancelGenerate()}>
                <Square size={12} /> {cancelling ? '终止中…' : '终止生成'}
              </Btn>
            )}
          </div>
        </div>

        {/* 下划线 Tabs（对齐 UI 自动化） */}
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

        {/* Tab 内容 */}
        <div style={{ flex: 1, overflowY: 'auto', padding: 16 }}>
          {tab === 'snapshot' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {!editing ? (
                <>
                  <Section title="前置条件">{targetCase.precondition || '—'}</Section>
                  <Section title="测试步骤">
                    {!targetCase.steps || targetCase.steps.length === 0 ? (
                      '—'
                    ) : (
                      <ol style={{ margin: 0, paddingLeft: 18 }}>
                        {targetCase.steps.map((s, i) => (
                          <li key={i} style={{ marginBottom: 3 }}>{s}</li>
                        ))}
                      </ol>
                    )}
                  </Section>
                  <Section title="预期结果">{targetCase.expected || '—'}</Section>
                  {targetCase.last_error_message && (
                    <div style={{ fontSize: 12 }}>
                      <div style={{ color: 'var(--text-muted)', marginBottom: 4, display: 'flex', gap: 6, alignItems: 'center' }}>
                        最近失败
                        <ErrorCategoryTag category={targetCase.last_error_category} />
                      </div>
                      <pre
                        style={{
                          margin: 0,
                          padding: 10,
                          borderRadius: 6,
                          background: 'var(--bg-card)',
                          border: '1px solid var(--border)',
                          fontSize: 11,
                          whiteSpace: 'pre-wrap',
                          wordBreak: 'break-word',
                        }}
                      >
                        {targetCase.last_error_message}
                      </pre>
                    </div>
                  )}
                  <div>
                    <Btn size="sm" disabled={isActive} onClick={() => setEditing(true)}>
                      编辑用例快照
                    </Btn>
                  </div>
                </>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                  <Field label="标题">
                    <input style={inputStyle} value={title} onChange={(e) => setTitle(e.target.value)} />
                  </Field>
                  <Field label="前置条件">
                    <textarea
                      rows={2}
                      style={inputStyle}
                      value={precondition}
                      onChange={(e) => setPrecondition(e.target.value)}
                    />
                  </Field>
                  <Field label="测试步骤 (每行一步)">
                    <textarea
                      rows={8}
                      style={inputStyle}
                      value={stepsText}
                      onChange={(e) => setStepsText(e.target.value)}
                    />
                  </Field>
                  <Field label="预期结果">
                    <textarea
                      rows={3}
                      style={inputStyle}
                      value={expected}
                      onChange={(e) => setExpected(e.target.value)}
                    />
                  </Field>
                  <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
                    <Btn size="sm" onClick={() => setEditing(false)}>取消</Btn>
                    <Btn size="sm" variant="primary" onClick={() => void handleSaveMeta()} disabled={savingMeta}>
                      <Save size={12} /> {savingMeta ? '保存中…' : '保存快照'}
                    </Btn>
                  </div>
                </div>
              )}
            </div>
          )}

          {tab === 'script' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10, height: '100%' }}>
              <textarea
                value={scriptContent}
                onChange={(e) => setScriptContent(e.target.value)}
                placeholder="暂未生成脚本，点击上方 'Agent 生成' 进行探索生成，或在此手动粘贴符合规范的 def test_(driver, params, app_env) 脚本。"
                style={{
                  ...inputStyle,
                  fontFamily: 'monospace',
                  fontSize: 12,
                  minHeight: 420,
                  flex: 1,
                  lineHeight: 1.5,
                }}
              />
              <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                <Btn size="sm" variant="primary" onClick={() => void handleSaveScript()} disabled={savingScript}>
                  <Save size={12} /> {savingScript ? '校验并保存中…' : 'AST 校验并保存脚本'}
                </Btn>
              </div>
            </div>
          )}

          {tab === 'runs' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {runs.length === 0 ? (
                <div style={{ color: 'var(--text-muted)', fontSize: 12, textAlign: 'center', padding: 32 }}>
                  暂无执行记录
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {runs.map((r) => (
                    <div
                      key={r.id}
                      onClick={() => void inspectRun(r.id)}
                      style={{
                        padding: '10px 12px',
                        borderRadius: 8,
                        border: `1px solid ${selectedRun?.id === r.id ? 'var(--accent)' : 'var(--border)'}`,
                        background: selectedRun?.id === r.id ? 'var(--surface-hover)' : 'var(--bg-card)',
                        cursor: 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        fontSize: 12,
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <StatusBadge status={r.status} />
                        <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>Run #{r.id}</span>
                        <span style={{ color: 'var(--text-muted)' }}>
                          {r.device_id} · {r.duration_ms}ms · {r.runner}
                        </span>
                      </div>
                      <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>{r.started_at || ''}</span>
                    </div>
                  ))}
                </div>
              )}

              {selectedRun && (
                <div
                  style={{
                    padding: 12,
                    borderRadius: 8,
                    border: '1px solid var(--border)',
                    background: 'var(--bg-card)',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 10,
                  }}
                >
                  {selectedRun.error && (
                    <div style={{ color: 'var(--error)', fontSize: 12 }}>{selectedRun.error}</div>
                  )}

                  {selectedRun.screenshots && selectedRun.screenshots.length > 0 && (
                    <div style={{ display: 'flex', gap: 8, overflowX: 'auto' }}>
                      {selectedRun.screenshots.map((fn) => (
                        <a
                          key={fn}
                          href={runArtifactUrl(selectedRun.id, fn)}
                          target="_blank"
                          rel="noreferrer"
                          style={{
                            flexShrink: 0,
                            border: '1px solid var(--border)',
                            borderRadius: 6,
                            overflow: 'hidden',
                          }}
                        >
                          <img
                            src={runArtifactUrl(selectedRun.id, fn)}
                            alt={fn}
                            style={{ height: 150, width: 'auto', display: 'block' }}
                          />
                        </a>
                      ))}
                    </div>
                  )}

                  <div style={{ display: 'flex', gap: 6 }}>
                    <Btn
                      size="sm"
                      variant={logMode === 'stdout' ? 'primary' : 'ghost'}
                      onClick={() => setLogMode('stdout')}
                    >
                      Pytest 输出 (stdout.log)
                    </Btn>
                    <Btn
                      size="sm"
                      variant={logMode === 'logcat' ? 'primary' : 'ghost'}
                      onClick={() => setLogMode('logcat')}
                    >
                      设备日志 (device.log)
                    </Btn>
                  </div>

                  <pre
                    style={{
                      margin: 0,
                      padding: 10,
                      borderRadius: 6,
                      background: 'var(--bg-base)',
                      border: '1px solid var(--border)',
                      fontSize: 11,
                      color: 'var(--text-secondary)',
                      maxHeight: 260,
                      overflow: 'auto',
                      whiteSpace: 'pre-wrap',
                    }}
                  >
                    {logMode === 'stdout' ? runLog || '(空)' : deviceLog || '(无设备日志)'}
                  </pre>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 8, padding: '10px 12px' }}>
      <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>{title}</div>
      <div style={{ fontSize: 12, lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>{children}</div>
    </div>
  );
}
