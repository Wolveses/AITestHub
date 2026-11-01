import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Code2, FileCode, Play, PlugZap, Plus, Star, Trash2 } from 'lucide-react';
import { Modal } from '../../../../components/ui/modal';
import { useAutomationStore, type UIEnv, type ScriptTemplate } from '../../store/automationStore';
import { Btn, Field, inputStyle } from './common';

interface EnvForm {
  name: string;
  base_url: string;
  username: string;
  password: string;
  auth_script: string;
  token_inject: string;
  token_name: string;
  token_prefix: string;
  is_default: boolean;
}

const DEFAULT_SCRIPT_PLACEHOLDER = `import httpx

def get_token(base_url: str, username: str, password: str) -> str:
    """自动化前置脚本：输入域名、用户名、密码，返回 token 字符串或字典。"""
    resp = httpx.post(
        f"{base_url}/api/auth/login",
        json={"username": username, "password": password},
        timeout=15,
        verify=False,
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("token") or (data.get("data") or {}).get("token", "")
`;

const EMPTY: EnvForm = {
  name: '',
  base_url: '',
  username: '',
  password: '',
  auth_script: DEFAULT_SCRIPT_PLACEHOLDER,
  token_inject: 'cookie',
  token_name: 'token',
  token_prefix: '',
  is_default: true,
};

export function EnvManagerDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation();
  const { envs, loadEnvs, saveEnv, deleteEnv, testEnv, testCustomEnv, loadTemplates } = useAutomationStore();
  const [form, setForm] = useState<EnvForm>(EMPTY);
  const [editId, setEditId] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [testingId, setTestingId] = useState<number | null>(null);
  const [formTesting, setFormTesting] = useState(false);
  const [templates, setTemplates] = useState<ScriptTemplate[]>([]);
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null);

  useEffect(() => {
    if (open) {
      loadEnvs();
      loadTemplates().then(setTemplates).catch(() => {});
      setForm(EMPTY);
      setEditId(null);
      setTestResult(null);
    }
  }, [open, loadEnvs, loadTemplates]);

  const startEdit = (env: UIEnv) => {
    setEditId(env.id);
    setTestResult(null);
    setForm({
      name: env.name,
      base_url: env.base_url,
      username: env.username,
      password: '',
      auth_script: env.auth_script || DEFAULT_SCRIPT_PLACEHOLDER,
      token_inject: env.token_inject || 'cookie',
      token_name: env.token_name || 'token',
      token_prefix: env.token_prefix || '',
      is_default: env.is_default,
    });
  };

  const submit = async () => {
    if (!form.base_url.trim()) {
      toast.warning(t('ui.auto.baseUrlRequired', '请填写被测系统地址'));
      return;
    }
    setSaving(true);
    try {
      const payload: Record<string, unknown> = { ...form };
      if (editId !== null && !form.password) delete payload.password;
      await saveEnv(payload, editId ?? undefined);
      toast.success(t('ui.auto.envSaved', '环境已保存'));
      setForm(EMPTY);
      setEditId(null);
      setTestResult(null);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const handleTestList = async (env: UIEnv) => {
    setTestingId(env.id);
    try {
      const res = await testEnv(env.id);
      if (res.ok) toast.success(res.message || t('ui.auto.testOk', '连接成功'));
      else toast.error(res.message || t('ui.auto.testFail', '连接失败'));
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setTestingId(null);
    }
  };

  const handleTestCurrentForm = async () => {
    if (!form.base_url.trim()) {
      toast.warning(t('ui.auto.baseUrlRequired', '请填写被测系统地址'));
      return;
    }
    setFormTesting(true);
    setTestResult(null);
    try {
      let res: { ok: boolean; message: string; token?: string };
      if (editId !== null) {
        res = await testEnv(editId, form as unknown as Record<string, unknown>);
      } else {
        res = await testCustomEnv(form as unknown as Record<string, unknown>);
      }
      setTestResult(res);
      if (res.ok) {
        toast.success(res.message || t('ui.auto.testOk', '测试通过'));
      } else {
        toast.error(res.message || t('ui.auto.testFail', '测试失败'));
      }
    } catch (e) {
      const err = (e as Error).message;
      setTestResult({ ok: false, message: err });
      toast.error(err);
    } finally {
      setFormTesting(false);
    }
  };

  const handleDelete = async (env: UIEnv) => {
    try {
      await deleteEnv(env.id);
      toast.success(t('ui.auto.deleted', '已删除'));
      if (editId === env.id) {
        setEditId(null);
        setForm(EMPTY);
        setTestResult(null);
      }
    } catch (e) {
      toast.error((e as Error).message);
    }
  };

  const handleApplyTemplate = (tmplId?: string) => {
    const tmpl = tmplId ? templates.find((t) => t.id === tmplId) : templates[0];
    if (!tmpl) return;
    setForm((f) => ({
      ...f,
      auth_script: tmpl.code,
    }));
    toast.info(t('ui.auto.templateApplied', `已载入模板：${tmpl.name}`));
  };

  return (
    <Modal
      open={open}
      onOpenChange={(v) => !v && onClose()}
      title={t('ui.auto.envTitle', '环境管理（地址 / 用户名密码 / 自定义前置获取 Token 脚本）')}
      width="min(1080px, 95vw)"
    >
      <div style={{ display: 'grid', gridTemplateColumns: '300px 1fr', gap: 14, padding: '0 20px 18px', height: 'min(78vh, 720px)' }}>
        {/* 环境列表 */}
        <div style={{ overflowY: 'auto', borderRight: '1px solid var(--border)', paddingRight: 10 }}>
          <Btn
            size="sm"
            variant="primary"
            onClick={() => {
              setEditId(null);
              setForm(EMPTY);
              setTestResult(null);
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
              onClick={() => startEdit(env)}
              style={{
                padding: 10,
                borderRadius: 8,
                border: `1px solid ${editId === env.id ? 'var(--accent)' : 'var(--border)'}`,
                marginBottom: 8,
                cursor: 'pointer',
                background: editId === env.id ? 'var(--surface-hover)' : 'transparent',
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
                <Btn size="sm" disabled={testingId === env.id} onClick={() => handleTestList(env)}>
                  <PlugZap size={11} /> {testingId === env.id ? t('ui.auto.testing', '测试中…') : t('ui.auto.testConn', '测试连接')}
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
                <Btn size="sm" variant="danger" onClick={() => handleDelete(env)}>
                  <Trash2 size={11} />
                </Btn>
              </div>
            </div>
          ))}
        </div>

        {/* 表单 */}
        <div style={{ overflowY: 'auto', paddingRight: 4, display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 9 }}>
            <Field label={t('ui.auto.envName', '环境名称')}>
              <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} style={inputStyle} placeholder="如：测试环境 A" />
            </Field>
            <Field label="base_url" hint={t('ui.auto.baseUrlHint', '如 http://10.0.0.8:8080')}>
              <input value={form.base_url} onChange={(e) => setForm({ ...form, base_url: e.target.value })} style={inputStyle} />
            </Field>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 9 }}>
            <Field label={t('ui.auto.loginUser', '登录用户名')}>
              <input value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} style={inputStyle} autoComplete="off" />
            </Field>
            <Field
              label={t('ui.auto.loginPassword', '登录密码')}
              hint={editId !== null ? t('ui.auto.passwordKeep', '留空表示保持原密码') : undefined}
            >
              <input
                type="password"
                value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
                style={inputStyle}
                autoComplete="new-password"
                placeholder={editId !== null && envs.find((e) => e.id === editId)?.password_set ? '••••••' : ''}
              />
            </Field>
          </div>

          {/* 前置脚本编辑区 */}
          <div style={{ border: '1px solid var(--border)', borderRadius: 8, padding: '10px 12px', background: 'var(--bg-card)' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, fontWeight: 600 }}>
                <Code2 size={14} style={{ color: 'var(--accent)' }} />
                <span>{t('ui.auto.authScriptTitle', '前置获取 Token 脚本 (Python)')}</span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <button
                  type="button"
                  onClick={() => handleApplyTemplate()}
                  style={{
                    padding: '3px 8px',
                    fontSize: 11,
                    background: 'var(--bg-muted)',
                    border: '1px solid var(--border)',
                    borderRadius: 4,
                    color: 'var(--text-primary)',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    gap: 4,
                  }}
                  title={t('ui.auto.insertGenericTemplate', '插入通用登录脚本模板')}
                >
                  <FileCode size={12} />
                  <span>{t('ui.auto.applyTemplateBtn', '载入通用模板')}</span>
                </button>
              </div>
            </div>

            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 6 }}>
              {t('ui.auto.authScriptHint', '需定义函数 def get_token(base_url, username, password)，返回值支持 Token 字符串（自动注入浏览器）或复合字典。')}
            </div>

            <textarea
              value={form.auth_script}
              onChange={(e) => setForm({ ...form, auth_script: e.target.value })}
              onKeyDown={(e) => {
                // 支持 Tab 缩进 4 空格
                if (e.key === 'Tab') {
                  e.preventDefault();
                  const target = e.currentTarget;
                  const start = target.selectionStart;
                  const end = target.selectionEnd;
                  const val = target.value;
                  target.value = val.substring(0, start) + '    ' + val.substring(end);
                  target.selectionStart = target.selectionEnd = start + 4;
                  setForm((f) => ({ ...f, auth_script: target.value }));
                }
              }}
              spellCheck={false}
              style={{
                width: '100%',
                height: 190,
                fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
                fontSize: 12,
                lineHeight: 1.5,
                padding: '8px 10px',
                borderRadius: 6,
                border: '1px solid var(--border)',
                background: 'var(--bg-base)',
                color: 'var(--text-primary)',
                resize: 'vertical',
                outline: 'none',
                boxSizing: 'border-box',
              }}
            />

            {/* Token 注入策略设置 */}
            <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr 1fr', gap: 8, marginTop: 10 }}>
              <div>
                <label style={{ display: 'block', fontSize: 11, color: 'var(--text-muted)', marginBottom: 3 }}>
                  {t('ui.auto.tokenInject', 'Token 注入方式')}
                </label>
                <select
                  value={form.token_inject}
                  onChange={(e) => setForm({ ...form, token_inject: e.target.value })}
                  style={{ ...inputStyle, height: 28, fontSize: 12 }}
                >
                  <option value="cookie">Cookie 注入 (Playwright storageState)</option>
                  <option value="localStorage">LocalStorage 注入</option>
                  <option value="header">请求头 Header 注入</option>
                  <option value="custom">脚本自定义复合字典 (按返回值写入)</option>
                </select>
              </div>
              <div>
                <label style={{ display: 'block', fontSize: 11, color: 'var(--text-muted)', marginBottom: 3 }}>
                  {t('ui.auto.tokenName', 'Token 键名')}
                </label>
                <input
                  value={form.token_name}
                  onChange={(e) => setForm({ ...form, token_name: e.target.value })}
                  style={{ ...inputStyle, height: 28, fontSize: 12 }}
                  placeholder="token / Authorization"
                />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: 11, color: 'var(--text-muted)', marginBottom: 3 }}>
                  {t('ui.auto.tokenPrefix', 'Token 前缀 (可选)')}
                </label>
                <input
                  value={form.token_prefix}
                  onChange={(e) => setForm({ ...form, token_prefix: e.target.value })}
                  style={{ ...inputStyle, height: 28, fontSize: 12 }}
                  placeholder="如: Bearer "
                />
              </div>
            </div>
          </div>

          <Field label={t('ui.auto.setDefault', '设为默认环境')}>
            <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, height: 26 }}>
              <input
                type="checkbox"
                checked={form.is_default}
                onChange={(e) => setForm({ ...form, is_default: e.target.checked })}
              />
              {t('ui.auto.defaultHint', '生成/执行时默认使用该环境')}
            </label>
          </Field>

          {/* 调试执行结果反馈 */}
          {testResult && (
            <div
              style={{
                fontSize: 12,
                borderRadius: 6,
                padding: '8px 12px',
                border: `1px solid ${testResult.ok ? 'var(--success, #10b981)' : 'var(--danger, #ef4444)'}`,
                background: testResult.ok ? 'rgba(16, 185, 129, 0.08)' : 'rgba(239, 68, 68, 0.08)',
                color: testResult.ok ? 'var(--success, #10b981)' : 'var(--danger, #ef4444)',
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-all',
              }}
            >
              {testResult.message}
            </div>
          )}

          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 4 }}>
            <Btn variant="primary" disabled={saving || formTesting} onClick={submit}>
              {saving ? t('ui.auto.saving', '保存中…') : editId !== null ? t('ui.auto.save', '保存环境') : t('ui.auto.createEnv', '创建环境')}
            </Btn>
            <Btn disabled={formTesting || saving} onClick={handleTestCurrentForm}>
              <Play size={12} /> {formTesting ? t('ui.auto.testing', '脚本运行测试中…') : t('ui.auto.testScriptBtn', '调试前置脚本')}
            </Btn>
            {editId !== null && (
              <Btn
                onClick={() => {
                  setEditId(null);
                  setForm(EMPTY);
                  setTestResult(null);
                }}
              >
                {t('ui.auto.cancel', '取消')}
              </Btn>
            )}
          </div>
        </div>
      </div>
    </Modal>
  );
}
