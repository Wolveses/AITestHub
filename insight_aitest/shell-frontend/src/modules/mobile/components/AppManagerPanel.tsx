import { useEffect, useRef, useState } from 'react';
import { Pencil, Plus, Trash2, Upload } from 'lucide-react';
import { toast } from 'sonner';
import { Modal } from '../../../components/ui/modal';
import { Btn, Field, inputStyle } from './common';
import { useMobileStore, type MobileAppEnv } from '../store/mobileStore';

interface AppFormState {
  id?: number;
  name: string;
  platform: 'android' | 'ios';
  app_package: string;
  app_activity: string;
  reset_mode: 'no_reset' | 'fast_reset';
  appium_url: string;
  test_username: string;
  password: string;
  is_default: boolean;
}

const emptyForm = (): AppFormState => ({
  name: '',
  platform: 'android',
  app_package: '',
  app_activity: '',
  reset_mode: 'no_reset',
  appium_url: 'http://127.0.0.1:4723',
  test_username: '',
  password: '',
  is_default: false,
});

export function AppManagerPanel() {
  const { projectId, apps, loadApps, createApp, updateApp, deleteApp, uploadApk } = useMobileStore();
  const [modalOpen, setModalOpen] = useState(false);
  const [form, setForm] = useState<AppFormState>(emptyForm);
  const [saving, setSaving] = useState(false);
  const [uploadingId, setUploadingId] = useState<number | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);
  const [pendingUploadAppId, setPendingUploadAppId] = useState<number | null>(null);

  useEffect(() => {
    if (projectId) {
      void loadApps();
    }
  }, [projectId, loadApps]);

  const openCreate = () => {
    setForm(emptyForm());
    setModalOpen(true);
  };

  const openEdit = (app: MobileAppEnv) => {
    setForm({
      id: app.id,
      name: app.name,
      platform: (app.platform as 'android' | 'ios') || 'android',
      app_package: app.app_package,
      app_activity: app.app_activity || '',
      reset_mode: (app.reset_mode === 'fast_reset' ? 'fast_reset' : 'no_reset'),
      appium_url: app.appium_url || 'http://127.0.0.1:4723',
      test_username: app.test_username || '',
      password: '',
      is_default: app.is_default,
    });
    setModalOpen(true);
  };

  const triggerUpload = (appId: number) => {
    setPendingUploadAppId(appId);
    fileRef.current?.click();
  };

  const handleUpload = async (appId: number, file: File) => {
    setUploadingId(appId);
    try {
      await uploadApk(appId, file);
      toast.success(`安装包 ${file.name} 已上传`);
    } catch (e) {
      toast.error(`上传失败: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setUploadingId(null);
      setPendingUploadAppId(null);
    }
  };

  const handleSave = async () => {
    if (!form.name.trim() || !form.app_package.trim()) {
      toast.warning('请填写 App 名称与包名 (app_package)');
      return;
    }
    setSaving(true);
    try {
      const payload: Record<string, unknown> = {
        name: form.name.trim(),
        platform: form.platform,
        app_package: form.app_package.trim(),
        app_activity: form.app_activity.trim(),
        reset_mode: form.reset_mode,
        appium_url: form.appium_url.trim() || 'http://127.0.0.1:4723',
        test_username: form.test_username.trim(),
        is_default: form.is_default,
      };
      if (form.password) {
        payload.password = form.password;
      }
      if (form.id) {
        await updateApp(form.id, payload);
        toast.success('App 配置已更新');
      } else {
        await createApp(payload);
        toast.success('App 配置已创建');
      }
      setModalOpen(false);
    } catch (e) {
      toast.error(`保存失败: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (app: MobileAppEnv) => {
    try {
      await deleteApp(app.id);
      toast.success(`已删除 ${app.name}`);
    } catch (e) {
      toast.error(`删除失败: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <input
        ref={fileRef}
        type="file"
        accept=".apk,.ipa"
        style={{ display: 'none' }}
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f && pendingUploadAppId !== null) void handleUpload(pendingUploadAppId, f);
          e.target.value = '';
        }}
      />

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>
          被测 App 环境 ({apps.length})
        </div>
        <Btn variant="primary" onClick={openCreate}>
          <Plus size={13} /> 新增 App 配置
        </Btn>
      </div>

      {apps.length === 0 ? (
        <div
          style={{
            padding: 32,
            textAlign: 'center',
            background: 'var(--bg-card)',
            border: '1px solid var(--border)',
            borderRadius: 10,
            color: 'var(--text-muted)',
            fontSize: 13,
          }}
        >
          暂未配置被测 App。点击右上角“新增 App 配置”填写包名与启动参数。
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 12 }}>
          {apps.map((app) => (
            <div
              key={app.id}
              style={{
                background: 'var(--bg-card)',
                border: '1px solid var(--border)',
                borderRadius: 10,
                padding: 14,
                display: 'flex',
                flexDirection: 'column',
                gap: 6,
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)' }}>
                  {app.name} {app.is_default ? '· 默认' : ''}
                </span>
                <div style={{ display: 'flex', gap: 6 }}>
                  <Btn
                    variant="ghost"
                    disabled={uploadingId === app.id}
                    onClick={() => triggerUpload(app.id)}
                    style={{ padding: '4px 8px', fontSize: 11 }}
                  >
                    <Upload size={12} /> {uploadingId === app.id ? '上传中' : '上传APK'}
                  </Btn>
                  <Btn variant="ghost" onClick={() => openEdit(app)} style={{ padding: '4px 8px' }}>
                    <Pencil size={12} />
                  </Btn>
                  <Btn variant="danger" onClick={() => void handleDelete(app)} style={{ padding: '4px 8px' }}>
                    <Trash2 size={12} />
                  </Btn>
                </div>
              </div>
              <div style={{ fontSize: 12, color: 'var(--text-secondary)', fontFamily: 'monospace' }}>
                {app.app_package} {app.app_activity ? `(${app.app_activity})` : ''}
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                平台: {app.platform} · 重置策略: {app.reset_mode}
                {app.test_username ? ` · 测试账号: ${app.test_username}` : ''}
                {app.password_set ? ' (已存密码)' : ''}
              </div>
              {app.has_app_file && (
                <div style={{ fontSize: 11, color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  安装包: {app.app_file_rel}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      <Modal
        open={modalOpen}
        onOpenChange={setModalOpen}
        title={form.id ? '编辑 App 环境' : '新增 App 环境'}
        width="min(560px, 92vw)"
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <Field label="App 名称 *">
            <input
              style={inputStyle}
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="如：智联云盘 Android"
            />
          </Field>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            <Field label="平台">
              <select
                style={inputStyle}
                value={form.platform}
                onChange={(e) => setForm({ ...form, platform: e.target.value as 'android' | 'ios' })}
              >
                <option value="android">Android</option>
                <option value="ios">iOS (Phase 3)</option>
              </select>
            </Field>
            <Field label="会话重置策略">
              <select
                style={inputStyle}
                value={form.reset_mode}
                onChange={(e) => setForm({ ...form, reset_mode: e.target.value as AppFormState['reset_mode'] })}
              >
                <option value="no_reset">no_reset (保留登录态)</option>
                <option value="fast_reset">fast_reset (清空应用数据)</option>
              </select>
            </Field>
          </div>

          <Field label="包名 (appPackage / bundleId) *">
            <input
              style={inputStyle}
              value={form.app_package}
              onChange={(e) => setForm({ ...form, app_package: e.target.value })}
              placeholder="com.example.app"
            />
          </Field>

          <Field label="启动 Activity (可选)">
            <input
              style={inputStyle}
              value={form.app_activity}
              onChange={(e) => setForm({ ...form, app_activity: e.target.value })}
              placeholder=".MainActivity"
            />
          </Field>

          <Field label="Appium 服务地址">
            <input
              style={inputStyle}
              value={form.appium_url}
              onChange={(e) => setForm({ ...form, appium_url: e.target.value })}
              placeholder="http://127.0.0.1:4723"
            />
          </Field>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            <Field label="测试账号 (可选)">
              <input
                style={inputStyle}
                value={form.test_username}
                onChange={(e) => setForm({ ...form, test_username: e.target.value })}
                placeholder="13800000000"
              />
            </Field>
            <Field label="测试密码 (服务端存储，不回显)">
              <input
                type="password"
                style={inputStyle}
                value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
                placeholder={form.id ? '留空表示不修改' : '输入测试账号密码'}
              />
            </Field>
          </div>

          <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: 'var(--text-secondary)', cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={form.is_default}
              onChange={(e) => setForm({ ...form, is_default: e.target.checked })}
            />
            设为当前项目默认被测 App
          </label>

          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 6 }}>
            <Btn variant="ghost" onClick={() => setModalOpen(false)}>
              取消
            </Btn>
            <Btn variant="primary" onClick={() => void handleSave()} disabled={saving}>
              {saving ? '保存中...' : '保存'}
            </Btn>
          </div>
        </div>
      </Modal>
    </div>
  );
}
