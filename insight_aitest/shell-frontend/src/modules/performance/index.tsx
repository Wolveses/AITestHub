import { lazy, Suspense, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { Smartphone, Server } from 'lucide-react';
import { ServerPerfWorkbench } from './components/server/ServerPerfWorkbench';
import { SystemMonitorPanel } from './components/server/SystemMonitorPanel';

// 懒加载移动端监控主界面
const MainWindow = lazy(() => import('./components/layout/MainWindow'));

export function PerformanceScriptsApp() {
  return <ServerPerfWorkbench />;
}

export function PerformanceMonitoringApp() {
  const [monitorMode, setMonitorMode] = useState<'system' | 'mobile'>('system');

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: 'var(--bg-base)' }}>
      {/* 顶部监控类型切换栏 */}
      <div
        style={{
          padding: '0 16px',
          background: 'var(--bg-card)',
          borderBottom: '1px solid var(--border)',
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          flexShrink: 0,
          height: 38,
        }}
      >
        <button
          onClick={() => setMonitorMode('system')}
          style={{
            background: 'transparent',
            border: 'none',
            borderBottom: monitorMode === 'system' ? '2px solid var(--accent)' : '2px solid transparent',
            color: monitorMode === 'system' ? 'var(--accent)' : 'var(--text-secondary)',
            fontWeight: monitorMode === 'system' ? 600 : 500,
            fontSize: 12,
            padding: '8px 12px',
            cursor: 'pointer',
            display: 'inline-flex',
            alignItems: 'center',
            gap: 5,
            height: '100%',
            transition: 'all 0.15s ease',
          }}
        >
          <Server size={13} />
          <span>服务器监控</span>
        </button>

        <button
          onClick={() => setMonitorMode('mobile')}
          style={{
            background: 'transparent',
            border: 'none',
            borderBottom: monitorMode === 'mobile' ? '2px solid var(--accent)' : '2px solid transparent',
            color: monitorMode === 'mobile' ? 'var(--accent)' : 'var(--text-secondary)',
            fontWeight: monitorMode === 'mobile' ? 600 : 500,
            fontSize: 12,
            padding: '8px 12px',
            cursor: 'pointer',
            display: 'inline-flex',
            alignItems: 'center',
            gap: 5,
            height: '100%',
            transition: 'all 0.15s ease',
          }}
        >
          <Smartphone size={13} />
          <span>移动端监控</span>
        </button>
      </div>

      {/* 监控内容视图 */}
      <div style={{ flex: 1, minHeight: 0, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        {monitorMode === 'system' ? (
          <SystemMonitorPanel />
        ) : (
          <Suspense fallback={<div style={{ padding: 24, color: 'var(--text-secondary)' }}>加载移动端监控中…</div>}>
            <MainWindow />
          </Suspense>
        )}
      </div>
    </div>
  );
}

/**
 * 根 PerformanceApp 入口：兼容直接访问 /performance
 */
export function PerformanceApp() {
  const location = useLocation();
  const isMonitoring = location.pathname.includes('/monitoring');

  if (isMonitoring) {
    return <PerformanceMonitoringApp />;
  }
  return <PerformanceScriptsApp />;
}

export default PerformanceApp;
