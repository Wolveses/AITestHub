import { lazy, Suspense } from 'react';
import { useLocation } from 'react-router-dom';
import { ServerPerfWorkbench } from './components/server/ServerPerfWorkbench';

// 懒加载移动端监控主界面
const MainWindow = lazy(() => import('./components/layout/MainWindow'));

export function PerformanceScriptsApp() {
  return <ServerPerfWorkbench />;
}

export function PerformanceMonitoringApp() {
  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: 'var(--bg-base)' }}>
      <Suspense fallback={<div style={{ padding: 24, color: 'var(--text-secondary)' }}>加载性能监控中…</div>}>
        <MainWindow />
      </Suspense>
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
