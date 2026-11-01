import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Code2, FileCode, Globe, Play, PlugZap, Plus, Save, Star, Trash2 } from 'lucide-react';
import { Modal } from '../../../../components/ui/modal';
import { useAutomationStore, type UIEnv, type ScriptTemplate } from '../../store/automationStore';
import { Btn, Field, inputStyle } from './common';

interface EnvForm {
  name: string;
  base_url: string;
  username: string;
  password: string;
  is_default: boolean;
}

const EMPTY_ENV: EnvForm = {
  name: '',
  base_url: '',
  username: '',
  password: '',
  is_default: true,
};

export function EnvManagerDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation();
  const {
    projectId,
    envs,
    loadEnvs,
    saveEnv,
    deleteEnv,
    testEnv,
    testCustomEnv,
    loadTemplates,
    loadProjectAuthScript,
    saveProjectAuthScript,
    testProjectAuthScript,
  } = useAutomationStore();

  const [activeTab, setActiveTab] = useState<'envs' | 'script'>('envs');

  // 环境管理状态
  const [envForm, setEnvForm] = useState<EnvForm>(EMPTY_ENV);
  const [editEnvId, setEditEnvId] = useState<number | null>(null);
  const [savingEnv, setSavingEnv] = useState(false);
  const [testingEnvId, setTestingEnvId] = useState<number | null>(null);
  const [formTesting, setFormTesting] = useState(false);
  const [envTestResult, setEnvTestResult] = useState<{ ok: boolean; message: string } | null>(null);

  // 项目级脚本状态
  const [projectScript, setProjectScript] = useState<string>('');
  const [savingScript, setSavingScript] = useState(false);
  const [testingScript, setTestingScript] = useState(false);
  const [selectedDebugEnvId, setSelectedDebugEnvId] = useState<number | null>(null);
  const [scriptTestResult, setScriptTestResult] = useState<{ ok: boolean; message: string } | null>(null);
  const [templates, setTemplates] = useState<ScriptTemplate[]>([]);

  useEffect(() => {
    if (open) {
      loadEnvs();
      loadTemplates().then(setTemplates).catch(() => {});
      setEnvForm(EMPTY_ENV);
      setEditEnvId(null);
      setEnvTestResult(null);
      setScriptTestResult(null);

      if (projectId !== null) {
        loadProjectAuthScript(projectId)
          .then((res) => {
            setProjectScript(res.auth_script || '');
          })
          .catch(() => {});
      }
    }
  }, [open, projectId, loadEnvs, loadTemplates, loadProjectAuthScript]);

  // 环境编辑
  const startEditEnv = (env: UIEnv) => {
    setEditEnvId(env.id);
    setEnvTestResult(null);
    setEnvForm({
      name: env.name,
      base_url: env.base_url,
      username: env.username,
      password: '',
      is_default: env.is_default,
    });
  };

  const submitEnv = async () => {
    if (!envForm.base_url.trim()) {
      toast.warning(t('ui.auto.baseUrlRequired', '请填写被测系统地址'));
      return;
    }
    setSavingEnv(true);
    try {
      const payload: Record<string, unknown> = { ...envForm };
      if (editEnvId !== null && !envForm.password) delete payload.password;
      await saveEnv(payload, editEnvId ?? undefined);
      toast.success(t('ui.auto.envSaved', '环境已保存'));
      setEnvForm(EMPTY_ENV);
      setEditEnvId(null);
      setEnvTestResult(null);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setSavingEnv(false);
    }
  };

  const handleTestEnvItem = async (env: UIEnv) => {
    setTestingEnvId(env.id);
    try {
      const res = await testEnv(env.id);
      if (res.ok) toast.success(res.message || t('ui.auto.testOk', '连接成功'));
      else toast.error(res.message || t('ui.auto.testFail', '连接失败'));
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setTestingEnvId(null);
    }
  };

  const handleTestCurrentEnvForm = async () => {
    if (!envForm.base_url.trim()) {
      toast.warning(t('ui.auto.baseUrlRequired', '请填写被测系统地址'));
      return;
    }
    setFormTesting(true);
    setEnvTestResult(null);
    try {
      let res: { ok: boolean; message: string; token?: string };
      if (editEnvId !== null) {
        res = await testEnv(editEnvId, envForm as unknown as Record<string, unknown>);
      } else {
        res = await testCustomEnv(envForm as unknown as Record<string, unknown>);
      }
      setEnvTestResult(res);
      if (res.ok) toast.success(res.message || t('ui.auto.testOk', '测试通过'));
      else toast.error(res.message || t('ui.auto.testFail', '测试失败'));
    } catch (e) {
      const err = (e as Error).message;
      setEnvTestResult({ ok: false, message: err });
      toast.error(err);
    } finally {
      setFormTesting(false);
    }
  };

  const handleDeleteEnv = async (env: UIEnv) => {
    try {
      await deleteEnv(env.id);
      toast.success(t('ui.auto.deleted', '已删除'));
      if (editEnvId === env.id) {
        setEditEnvId(null);
        setEnvForm(EMPTY_ENV);
        setEnvTestResult(null);
      }
    } catch (e) {
      toast.error((e as Error).message);
    }
  };

  // 项目级脚本管理
  const handleApplyTemplate = () => {
    const tmpl = templates[0];
    if (!tmpl) return;
    setProjectScript(tmpl.code);
    toast.info(t('ui.auto.templateApplied', `已载入模板：${tmpl.name}`));
  };

  const handleSaveProjectScript = async () => {
    if (projectId === null) {
      toast.error('未指定项目 ID');
      return;
    }
    setSavingScript(true);
    try {
      await saveProjectAuthScript(projectId, projectScript);
      toast.success(t('ui.auto.scriptSaved', '项目前置脚本已保存'));
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setSavingScript(false);
    }
  };

  const handleDebugProjectScript = async () => {
    if (projectId === null) {
      toast.error('未指定项目 ID');
      return;
    }
    setTestingScript(true);
    setScriptTestResult(null);
    try {
      const payload: Record<string, unknown> = {
        auth_script: projectScript,
      };
      if (selectedDebugEnvId) {
        payload.env_id = selectedDebugEnvId;
      }
      const res = await testProjectAuthScript(projectId, payload);
      setScriptTestResult(res);
      if (res.ok) toast.success(res.message || t('ui.auto.testOk', '脚本调试通过'));
      else toast.error(res.message || t('ui.auto.testFail', '脚本调试失败'));
    } catch (e) {
      const err = (e as Error).message;
      setScriptTestResult({ ok: false, message: err });
      toast.error(err);
    } finally {
      setTestingScript(false);
    }
  };

  return (
    <Modal
      open={open}
      onOpenChange={(v) => !v && onClose()}
      title={t('ui.auto.envManagerModalTitle', '环境与前置登录配置')}
      width="min(1080px, 95vw)"
    >
      <div style={{ padding: '0 20px 18px', height: 'min(78vh, 720px)', display: 'flex', flexDirection: 'column', gap: 12 }}>
        {/* 顶部 Tab 栏 */}
        <div style={{ display: 'flex', gap: 8, borderBottom: '1px solid var(--border)', paddingBottom: 8 }}>
          <button
            type="button"
            onClick={() => setActiveTab('envs')}
            style={{
              padding: '6px 14px',
              borderRadius: 6,
              fontSize: 13,
              fontWeight: activeTab === 'envs' ? 600 : 400,
              cursor: 'pointer',
              border: 'none',
              background: activeTab === 'envs' ? 'var(--surface-hover)' : 'transparent',
              color: activeTab === 'envs' ? 'var(--accent)' : 'var(--text-muted)',
              display: 'flex',
              alignItems: 'center',
              gap: 6,
            }}
          >
            <Globe size={14} />
            <span>{t('ui.auto.tabEnvs', '环境列表与配置')}</span>
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('script')}
            style={{
              padding: '6px 14px',
              borderRadius: 6,
              fontSize: 13,
              fontWeight: activeTab === 'script' ? 600 : 400,
              cursor: 'pointer',
              border: 'none',
              background: activeTab === 'script' ? 'var(--surface-hover)' : 'transparent',
              color: activeTab === 'script' ? 'var(--accent)' : 'var(--text-muted)',
              display: 'flex',
              alignItems: 'center',
              gap: 6,
            }}
          >
            <Code2 size={14} />
            <span>{t('ui.auto.tabProjectScript', '项目前置获取 Token 脚本 (Python)')}</span>
          </button>
        </div>

        {/* Tab 1: 环境管理 */}
        {activeTab === 'envs' && (
          <div style={{ display: 'grid', gridTemplateColumns: '300px 1fr', gap: 14, flex: 1, minHeight: 0 }}>
            {/* 左侧环境列表 */}
            <div style={{ overflowY: 'auto', borderRight: '1px solid var(--border)', paddingRight: 10 }}>
              <Btn
                size="sm"
                variant="primary"
                onClick={() => {
                  setEditEnvId(null);
                  setEnvForm(EMPTY_ENV);
                  setEnvTestResult(null);
                }}
                style={{ marginBottom: 8, width: '100%', justifyContent: 'center' }}
              >
                <Plus size={12} /> {t('ui.auto.addEnv', '新增环境')}
              </Btn>
              {envs.length === 0 && (
                <div style={{ fontSize: 12, color: 'var(--text-muted)', padding: '12px 4px' }}>
                  {t('ui.auto.noEnv', '暂无环境配置')}
                </div>
              )}
              {envs.map((env) => (
                <div
                  key={env.id}
                  onClick={() => startEditEnv(env)}
                  style={{
                    padding: 10,
                    borderRadius: 8,
                    border: `1px solid ${editEnvId === env.id ? 'var(--accent)' : 'var(--border)'}`,
                    marginBottom: 8,
                    cursor: 'pointer',
                    background: editEnvId === env.id ? 'var(--surface-hover)' : 'transparent',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
                    <span style={{ flex: 1, fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {env.name}
                    </span>
                    {env.is_default && <Star size={12} style={{ color: 'var(--warning, #f59e0b)' }} />}
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 3, wordBreak: 'break-all' }}>{env.base_url}</div>
                  <div style={{ display: 'flex', gap: 4, marginTop: 6 }} onClick={(e) => e.stopPropagation()}>
                    <Btn size="sm" disabled={testingEnvId === env.id} onClick={() => handleTestEnvItem(env)}>
                      <PlugZap size={11} /> {testingEnvId === env.id ? t('ui.auto.testing', '测试中…') : t('ui.auto.testConn', '测试连接')}
                    </Btn>
                    {!env.is_default && (
                      <Btn
                        size="sm"
                        onClick={async () => {
                          try {
                            await saveEnv({ is_default: true }, env.id);
                            toast.success(t('ui.auto.defaultSwitched', '已切换默认环境'));
                          } catch (e) {
                            toast.error((e as Error).message);
                          }
                        }}
                      >
                        <Star size={11} /> {t('ui.auto.setDefaultBtn', '设为默认')}
                      </Btn>
                    )}
                    <Btn size="sm" variant="danger" onClick={() => handleDeleteEnv(env)}>
                      <Trash2 size={11} />
                    </Btn>
                  </div>
                </div>
              ))}
            </div>

            {/* 右侧环境表单 */}
            <div style={{ overflowY: 'auto', paddingRight: 4, display: 'flex', flexDirection: 'column', gap: 14 }}>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <Field label={t('ui.auto.envName', '环境名称')}>
                  <input
                    value={envForm.name}
                    onChange={(e) => setEnvForm({ ...envForm, name: e.target.value })}
                    style={inputStyle}
                    placeholder="如：测试环境 A"
                  />
                </Field>
                <Field label="base_url" hint={t('ui.auto.baseUrlHint', '如 http://10.0.0.8:8080')}>
                  <input
                    value={envForm.base_url}
                    onChange={(e) => setEnvForm({ ...envForm, base_url: e.target.value })}
                    style={inputStyle}
                  />
                </Field>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <Field label={t('ui.auto.loginUser', '登录用户名')}>
                  <input
                    value={envForm.username}
                    onChange={(e) => setEnvForm({ ...envForm, username: e.target.value })}
                    style={inputStyle}
                    autoComplete="off"
                  />
                </Field>
                <Field
                  label={t('ui.auto.loginPassword', '登录密码')}
                  hint={editEnvId !== null ? t('ui.auto.passwordKeep', '留空表示保持原密码') : undefined}
                >
                  <input
                    type="password"
                    value={envForm.password}
                    onChange={(e) => setEnvForm({ ...envForm, password: e.target.value })}
                    style={inputStyle}
                    autoComplete="new-password"
                    placeholder={editEnvId !== null && envs.find((e) => e.id === editEnvId)?.password_set ? '••••••' : ''}
                  />
                </Field>
              </div>

              <Field label={t('ui.auto.setDefault', '设为默认环境')}>
                <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, height: 26 }}>
                  <input
                    type="checkbox"
                    checked={envForm.is_default}
                    onChange={(e) => setEnvForm({ ...envForm, is_default: e.target.checked })}
                  />
                  {t('ui.auto.defaultHint', '生成/执行时默认使用该环境')}
                </label>
              </Field>

              <div style={{ fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.6, background: 'var(--bg-base)', padding: '8px 12px', borderRadius: 6 }}>
                {t('ui.auto.envScopeHint', '💡 本环境将自动使用项目统一配置的「前置获取 Token 脚本」换取登录态。点击测试连接可实时检验。')}
              </div>

              {/* 连通测试结果反馈 */}
              {envTestResult && (
                <div
                  style={{
                    fontSize: 12,
                    borderRadius: 6,
                    padding: '8px 12px',
                    border: `1px solid ${envTestResult.ok ? 'var(--success, #10b981)' : 'var(--danger, #ef4444)'}`,
                    background: envTestResult.ok ? 'rgba(16, 185, 129, 0.08)' : 'rgba(239, 68, 68, 0.08)',
                    color: envTestResult.ok ? 'var(--success, #10b981)' : 'var(--danger, #ef4444)',
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-all',
                  }}
                >
                  {envTestResult.message}
                </div>
              )}

              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 'auto', paddingTop: 10 }}>
                <Btn variant="primary" disabled={savingEnv || formTesting} onClick={submitEnv}>
                  {savingEnv ? t('ui.auto.saving', '保存中…') : editEnvId !== null ? t('ui.auto.save', '保存环境') : t('ui.auto.createEnv', '创建环境')}
                </Btn>
                <Btn disabled={formTesting || savingEnv} onClick={handleTestCurrentEnvForm}>
                  <PlugZap size={12} /> {formTesting ? t('ui.auto.testing', '连通测试中…') : t('ui.auto.testConn', '测试连接')}
                </Btn>
                {editEnvId !== null && (
                  <Btn
                    onClick={() => {
                      setEditEnvId(null);
                      setEnvForm(EMPTY_ENV);
                      setEnvTestResult(null);
                    }}
                  >
                    {t('ui.auto.cancel', '取消')}
                  </Btn>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Tab 2: 项目前置获取 Token 脚本 */}
        {activeTab === 'script' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, flex: 1, minHeight: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', background: 'var(--bg-card)', padding: '8px 12px', borderRadius: 8, border: '1px solid var(--border)' }}>
              <div>
                <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)' }}>
                  {t('ui.auto.projectScriptDescTitle', '项目级统一前置脚本')}
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
                  {t('ui.auto.projectScriptDesc', '本项目下所有环境（Dev/Test/Prod）共用此脚本。执行自动化用例时，系统自动传入各环境的 base_url、username、password。')}
                </div>
              </div>
              <button
                type="button"
                onClick={handleApplyTemplate}
                style={{
                  padding: '4px 10px',
                  fontSize: 11,
                  background: 'var(--bg-muted)',
                  border: '1px solid var(--border)',
                  borderRadius: 4,
                  color: 'var(--text-primary)',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 4,
                  whiteSpace: 'nowrap',
                }}
                title={t('ui.auto.insertGenericTemplate', '插入通用登录脚本模板')}
              >
                <FileCode size={12} />
                <span>{t('ui.auto.applyTemplateBtn', '载入通用模板')}</span>
              </button>
            </div>

            {/* 脚本编辑器 */}
            <div style={{ flex: 1, minHeight: 280, display: 'flex', flexDirection: 'column' }}>
              <textarea
                value={projectScript}
                onChange={(e) => setProjectScript(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Tab') {
                    e.preventDefault();
                    const target = e.currentTarget;
                    const start = target.selectionStart;
                    const end = target.selectionEnd;
                    const val = target.value;
                    target.value = val.substring(0, start) + '    ' + val.substring(end);
                    target.selectionStart = target.selectionEnd = start + 4;
                    setProjectScript(target.value);
                  }
                }}
                spellCheck={false}
                style={{
                  width: '100%',
                  flex: 1,
                  minHeight: 280,
                  fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
                  fontSize: 12,
                  lineHeight: 1.5,
                  padding: '10px 12px',
                  borderRadius: 8,
                  border: '1px solid var(--border)',
                  background: 'var(--bg-base)',
                  color: 'var(--text-primary)',
                  resize: 'none',
                  outline: 'none',
                  boxSizing: 'border-box',
                }}
              />
            </div>

            {/* 调试反馈 */}
            {scriptTestResult && (
              <div
                style={{
                  fontSize: 12,
                  borderRadius: 6,
                  padding: '8px 12px',
                  border: `1px solid ${scriptTestResult.ok ? 'var(--success, #10b981)' : 'var(--danger, #ef4444)'}`,
                  background: scriptTestResult.ok ? 'rgba(16, 185, 129, 0.08)' : 'rgba(239, 68, 68, 0.08)',
                  color: scriptTestResult.ok ? 'var(--success, #10b981)' : 'var(--danger, #ef4444)',
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-all',
                }}
              >
                {scriptTestResult.message}
              </div>
            )}

            {/* 底部操作与调试栏 */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, paddingTop: 4 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{t('ui.auto.debugEnvSelect', '调试环境:')}</span>
                <select
                  value={selectedDebugEnvId ?? ''}
                  onChange={(e) => setSelectedDebugEnvId(e.target.value ? Number(e.target.value) : null)}
                  style={{ ...inputStyle, width: 'auto', minWidth: 150, height: 28, fontSize: 12 }}
                >
                  <option value="">{t('ui.auto.defaultEnvOpt', '-- 使用默认环境 --')}</option>
                  {envs.map((env) => (
                    <option key={env.id} value={env.id}>
                      {env.name} ({env.base_url})
                    </option>
                  ))}
                </select>
                <Btn disabled={testingScript || savingScript} onClick={handleDebugProjectScript}>
                  <Play size={12} /> {testingScript ? t('ui.auto.testing', '调试运行中…') : t('ui.auto.testScriptBtn', '调试前置脚本')}
                </Btn>
              </div>

              <Btn variant="primary" disabled={savingScript || testingScript} onClick={handleSaveProjectScript}>
                <Save size={12} /> {savingScript ? t('ui.auto.saving', '保存中…') : t('ui.auto.saveProjectScript', '保存项目脚本')}
              </Btn>
            </div>
          </div>
        )}
      </div>
    </Modal>
  );
}

