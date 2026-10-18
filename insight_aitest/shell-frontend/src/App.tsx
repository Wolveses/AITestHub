import { useEffect, useState } from 'react';
import { PlatformRouter } from './routing';
import { AuthPage } from './shell/AuthPage';
import { useAuthStore } from './shared/store/authStore';
import type { ModuleManifest } from './shell/types';
import './index.css';

type State =
  | { status: 'loading' }
  | { status: 'ok'; modules: ModuleManifest[] }
  | { status: 'error'; message: string };

export default function App() {
  const [state, setState] = useState<State>({ status: 'loading' });
  const { token, checkAuth } = useAuthStore();
  const [authChecked, setAuthChecked] = useState(false);

  useEffect(() => {
    checkAuth().finally(() => setAuthChecked(true));
  }, [checkAuth]);

  useEffect(() => {
    fetch('/api/platform/modules')
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((modules: ModuleManifest[]) => setState({ status: 'ok', modules }))
      .catch((e) => setState({ status: 'error', message: String(e) }));
  }, []);

  if (!authChecked || state.status === 'loading') {
    return <div style={{ padding: 48, color: "var(--text-secondary)" }}>加载平台…</div>;
  }

  // 未登录或 token 无效拦截展示登录/注册页
  if (!token) {
    return <AuthPage />;
  }

  if (state.status === 'error') {
    return (
      <div style={{ padding: 48, color: "var(--text-primary)" }}>
        <h2>平台模块加载失败</h2>
        <p style={{ color: "var(--text-secondary)" }}>{state.message}</p>
        <button onClick={() => location.reload()}>重试</button>
      </div>
    );
  }
  return <PlatformRouter modules={state.modules} />;
}
