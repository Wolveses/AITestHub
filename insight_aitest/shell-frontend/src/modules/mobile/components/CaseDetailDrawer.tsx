import { useEffect, useState } from 'react';
import { Code2, FileText, History, Play, Save, Sparkles, X } from 'lucide-react';
import { toast } from 'sonner';
import { Btn, Field, StatusBadge, inputStyle } from './common';
import {
  runArtifactUrl,
  useMobileStore,
  type MobileCase,
  type MobileRunItem,
} from '../store/mobileStore';

type DrawerTab = 'steps' | 'script' | 'runs';

export function CaseDetailDrawer({
  targetCase,
  onClose,
  onOpenGenerate,
}: {
  targetCase: MobileCase | null;
  onClose: () => void;
  onOpenGenerate: (c: MobileCase) => void;
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
  } = useMobileStore();

  const [tab, setTab] = useState<DrawerTab>('steps');
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
  const [runs, setRuns] = useState<MobileRunItem[]>([]);
  const [selectedRun, setSelectedRun] = useState<MobileRunItem | null>(null);
  const [runLog, setRunLog] = useState('');
  const [deviceLog, setDeviceLog] = useState('');
  const [logMode, setLogMode] = useState<'stdout' | 'logcat'>('stdout');

  useEffect(() => {
    if (!targetCase) return;
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
    const idleAndroid = devices.find((d) => d.type === 'android' && d.status === 'online' && !d.busy);
    if (idleAndroid && !runDeviceId) setRunDeviceId(idleAndroid.device_id);
    const defaultApp =
      apps.find((a) => a.id === targetCase.default_app_id) ||
      apps.find((a) => a.is_default) ||
      apps[0];
    if (defaultApp && runAppId === '') setRunAppId(defaultApp.id);
  }, [targetCase, devices, apps, runDeviceId, runAppId]);

  if (!targetCase) return null;

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
      toast.success('用例信息已更新');
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
      toast.warning('请先选择一台空闲 Android 设备');
      return;
    }
    setRunning(true);
    try {
      const res = await runCase(targetCase.id, {
        device_id: runDeviceId,
        app_id: runAppId === '' ? null : runAppId,
      });
      toast.success(`已触发服务端运行 (Run #${res.run_id})`);
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

  const androidDevices = devices.filter((d) => d.type === 'android');

  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        right: 0,
        bottom: 0,
        width: 'min(760px, 95vw)',
        background: 'var(--bg-elevated)',
        borderLeft: '1px solid var(--border)',
        zIndex: 60,
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      <div
        style={{
          padding: '14px 18px',
          borderBottom: '1px solid var(--border)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 12,
        }}
      >
        <div style={{ minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 15, fontWeight: 600, color: 'var(--text-primary)' }}>
              {targetCase.title}
            </span>
            <StatusBadge status={targetCase.status} />
            {targetCase.script_version > 0 && (
              <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>v{targetCase.script_version}</span>
            )}
          </div>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
            {targetCase.category_path || '未分类'} · {targetCase.platform}
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Btn variant="ghost" onClick={() => onOpenGenerate(targetCase)}>
            <Sparkles size={13} /> {targetCase.has_script ? 'Agent 修复' : 'Agent 生成'}
          </Btn>
          <button
            onClick={onClose}
            style={{
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              color: 'var(--text-muted)',
              padding: 4,
            }}
          >
            <X size={18} />
          </button>
        </div>
      </div>

      {/* Run trigger bar */}
      <div
        style={{
          padding: '10px 18px',
          borderBottom: '1px solid var(--border)',
          background: 'var(--bg-card)',
          display: 'flex',
          alignItems: 'center',
          gap: 8,
        }}
      >
        <select
          style={{ ...inputStyle, flex: 1 }}
          value={runDeviceId}
          onChange={(e) => setRunDeviceId(e.target.value)}
        >
          <option value="">选择执行设备</option>
          {androidDevices.map((d) => (
            <option key={d.device_id} value={d.device_id} disabled={d.busy}>
              {d.model || d.name || d.device_id} ({d.device_id}) {d.busy ? '[占用]' : ''}
            </option>
          ))}
        </select>
        <select
          style={{ ...inputStyle, width: 200 }}
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
          variant="primary"
          disabled={running || !targetCase.has_script || !runDeviceId}
          onClick={() => void handleRun()}
        >
          <Play size={13} /> {running ? '执行中...' : '立即运行'}
        </Btn>
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 4, padding: '8px 18px', borderBottom: '1px solid var(--border)' }}>
        <Btn variant={tab === 'steps' ? 'primary' : 'ghost'} onClick={() => setTab('steps')} style={{ fontSize: 12 }}>
          <FileText size={13} /> 用例步骤
        </Btn>
        <Btn variant={tab === 'script' ? 'primary' : 'ghost'} onClick={() => setTab('script')} style={{ fontSize: 12 }}>
          <Code2 size={13} /> 脚本源码 (v{scriptVersion})
        </Btn>
        <Btn variant={tab === 'runs' ? 'primary' : 'ghost'} onClick={() => setTab('runs')} style={{ fontSize: 12 }}>
          <History size={13} /> 运行记录 ({runs.length})
        </Btn>
      </div>

      {/* Tab Body */}
      <div style={{ flex: 1, overflowY: 'auto', padding: 18 }}>
        {tab === 'steps' && (
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
            <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
              <Btn variant="primary" onClick={() => void handleSaveMeta()} disabled={savingMeta}>
                <Save size={13} /> {savingMeta ? '保存中...' : '保存用例修改'}
              </Btn>
            </div>
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
              <Btn variant="primary" onClick={() => void handleSaveScript()} disabled={savingScript}>
                <Save size={13} /> {savingScript ? '校验并保存中...' : 'AST 校验并保存脚本'}
              </Btn>
            </div>
          </div>
        )}

        {tab === 'runs' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {runs.length === 0 ? (
              <div style={{ color: 'var(--text-muted)', fontSize: 13, textAlign: 'center', padding: 32 }}>
                暂无运行记录。
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
                      background: selectedRun?.id === r.id ? 'var(--surface-tint)' : 'var(--bg-card)',
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
                    variant={logMode === 'stdout' ? 'primary' : 'ghost'}
                    onClick={() => setLogMode('stdout')}
                    style={{ fontSize: 11, padding: '4px 10px' }}
                  >
                    Pytest 输出 (stdout.log)
                  </Btn>
                  <Btn
                    variant={logMode === 'logcat' ? 'primary' : 'ghost'}
                    onClick={() => setLogMode('logcat')}
                    style={{ fontSize: 11, padding: '4px 10px' }}
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
  );
}
