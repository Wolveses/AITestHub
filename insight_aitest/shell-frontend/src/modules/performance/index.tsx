import { lazy, Suspense, useState } from 'react';
import { Gauge, FileText, Layers } from 'lucide-react';
import { PerfScriptList } from './components/server/PerfScriptList';
import { PerfTaskList } from './components/server/PerfTaskList';
import { PerfReportModal } from './components/server/PerfReportModal';

// 懒加载原有移动端监控界面（完整保留，无缝兼容）
const MainWindow = lazy(() => import('./components/layout/MainWindow'));

type MainTab = 'server_scripts' | 'server_tasks' | 'device_monitor';

/**
 * 性能测试模块前端入口（支持服务端 JMeter 压测 与 原有移动设备性能监控 双模式切换）。
 */
export function PerformanceApp() {
  const [activeTab, setActiveTab] = useState<MainTab>('server_scripts');
  const [viewRunId, setViewRunId] = useState<number | null>(null);

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: 'var(--bg-base)' }}>
      {/* 顶部主 Tab 导航栏 */}
      <div
        style={{
          padding: '0 16px',
          background: 'var(--bg-card)',
          borderBottom: '1px solid var(--border)',
          display: 'flex',
          alignItems: 'center',
          gap: 4,
          flexShrink: 0,
          height: 44,
        }}
      >
        <button
          onClick={() => setActiveTab('server_scripts')}
          style={{
            background: 'transparent',
            border: 'none',
            borderBottom: activeTab === 'server_scripts' ? '2px solid var(--accent)' : '2px solid transparent',
            color: activeTab === 'server_scripts' ? 'var(--accent)' : 'var(--text-secondary)',
            fontWeight: activeTab === 'server_scripts' ? 600 : 500,
            fontSize: 13,
            padding: '10px 14px',
            cursor: 'pointer',
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            height: '100%',
            transition: 'all 0.15s ease',
          }}
        >
          <FileText size={15} />
          <span>JMeter 脚本库</span>
        </button>

        <button
          onClick={() => setActiveTab('server_tasks')}
          style={{
            background: 'transparent',
            border: 'none',
            borderBottom: activeTab === 'server_tasks' ? '2px solid var(--accent)' : '2px solid transparent',
            color: activeTab === 'server_tasks' ? 'var(--accent)' : 'var(--text-secondary)',
            fontWeight: activeTab === 'server_tasks' ? 600 : 500,
            fontSize: 13,
            padding: '10px 14px',
            cursor: 'pointer',
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            height: '100%',
            transition: 'all 0.15s ease',
          }}
        >
          <Layers size={15} />
          <span>压测任务管理</span>
        </button>

        <div style={{ width: 1, height: 20, background: 'var(--border)', margin: '0 8px' }} />

        <button
          onClick={() => setActiveTab('device_monitor')}
          style={{
            background: 'transparent',
            border: 'none',
            borderBottom: activeTab === 'device_monitor' ? '2px solid var(--accent)' : '2px solid transparent',
            color: activeTab === 'device_monitor' ? 'var(--accent)' : 'var(--text-secondary)',
            fontWeight: activeTab === 'device_monitor' ? 600 : 500,
            fontSize: 13,
            padding: '10px 14px',
            cursor: 'pointer',
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            height: '100%',
            transition: 'all 0.15s ease',
          }}
        >
          <Gauge size={15} />
          <span>移动端设备监控 (原有功能)</span>
        </button>
      </div>

      {/* Tab 内容区 */}
      <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        {activeTab === 'server_scripts' && <PerfScriptList />}
        {activeTab === 'server_tasks' && (
          <PerfTaskList onOpenReport={(runId) => setViewRunId(runId)} />
        )}
        {activeTab === 'device_monitor' && (
          <Suspense fallback={<div style={{ padding: 24, color: 'var(--text-secondary)' }}>加载移动设备监控界面…</div>}>
            <MainWindow />
          </Suspense>
        )}
      </div>

      {/* 查看压测报告弹窗 */}
      <PerfReportModal runId={viewRunId} onClose={() => setViewRunId(null)} />
    </div>
  );
}

export default PerformanceApp;
