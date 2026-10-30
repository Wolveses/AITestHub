import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { PlugZap, Plus, Star, Trash2 } from 'lucide-react';
import { Modal } from '../../../../components/ui/modal';
import { useAutomationStore, type UIEnv } from '../../store/automationStore';
import { Btn, Field, inputStyle } from './common';

interface EnvForm {
  name: string;
  base_url: string;
  username: string;
  password: string;
  is_default: boolean;
}

const EMPTY: EnvForm = {
  name: '',
  base_url: '',
  username: '',
  password: '',
  is_default: true,
};

export function EnvManagerDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation();
  const { envs, loadEnvs, saveEnv, deleteEnv, testEnv } = useAutomationStore();
  const [form, setForm] = useState<EnvForm>(EMPTY);
  const [editId, setEditId] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [testingId, setTestingId] = useState<number | null>(null);

  useEffect(() => {
    if (open) {
      loadEnvs();
      setForm(EMPTY);
      setEditId(null);
    }
  }, [open, loadEnvs]);

  const startEdit = (env: UIEnv) => {
    setEditId(env.id);
    setForm({
      name: env.name,
      base_url: env.base_url,
      username: env.username,
      password: '',
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
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async (env: UIEnv) => {
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

  const handleDelete = async (env: UIEnv) => {
    try {
      await deleteEnv(env.id);
      toast.success(t('ui.auto.deleted', '已删除'));
      if (editId === env.id) {
        setEditId(null);
        setForm(EMPTY);
      }
    } catch (e) {
      toast.error((e as Error).message);
    }
  };

  return (
    <Modal
      open={open}
      onOpenChange={(v) => !v && onClose()}
      title={t('ui.auto.envTitle', '环境管理（主机地址 / 登录信息）')}
      width="min(920px, 95vw)"
    >
      <div style={{ display: 'grid', gridTemplateColumns: '320px 1fr', gap: 14, padding: '0 20px 18px', height: 'min(70vh, 600px)' }}>
        {/* 环境列表 */}
        <div style={{ overflowY: 'auto', borderRight: '1px solid var(--border)', paddingRight: 10 }}>
          <Btn
            size="sm"
            variant="primary"
            onClick={() => {
              setEditId(null);
              setForm(EMPTY);
            }}
            style={{ marginBottom: 8 }}
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
                <Btn size="sm" disabled={testingId === env.id} onClick={() => handleTest(env)}>
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
        <div style={{ overflowY: 'auto', paddingRight: 4, display: 'flex', flexDirection: 'column', gap: 9 }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 9 }}>
            <Field label={t('ui.auto.envName', '环境名称')}>
              <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} style={inputStyle} />
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
              hint={editId !== null ? t('ui.auto.passwordKeep', '留空表示不修改') : undefined}
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

          <Field label={t('ui.auto.setDefault', '设为默认环境')}>
            <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, height: 30 }}>
              <input
                type="checkbox"
                checked={form.is_default}
                onChange={(e) => setForm({ ...form, is_default: e.target.checked })}
              />
              {t('ui.auto.defaultHint', '生成/执行时默认使用该环境')}
            </label>
          </Field>

          <div style={{ fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.6, background: 'var(--bg-card)', padding: 8, borderRadius: 6 }}>
            {t(
              'ui.auto.passwordStorageHint',
              '登录接口与密码加密算法已内置（获取 zoneId → 加密密码 → 换取 token），只需填写地址、用户名、密码。密码保存在运行后端的用户目录文件中，不入数据库、不回显；登录后的 Cookie 会转成 storageState 供浏览器与脚本共用。'
            )}
          </div>

          <div style={{ display: 'flex', gap: 8 }}>
            <Btn variant="primary" disabled={saving} onClick={submit}>
              {saving ? t('ui.auto.saving', '保存中…') : editId !== null ? t('ui.auto.save', '保存') : t('ui.auto.createEnv', '创建环境')}
            </Btn>
            {editId !== null && (
              <Btn
                onClick={() => {
                  setEditId(null);
                  setForm(EMPTY);
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
