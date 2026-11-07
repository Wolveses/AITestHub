import { useState } from 'react';
import { FileText, Layers } from 'lucide-react';
import { PerfScriptList } from './PerfScriptList';
import { PerfTaskList } from './PerfTaskList';
import { PerfReportModal } from './PerfReportModal';

type ServerSubTab = 'scripts' | 'tasks';

/**
 * 测试脚本与压测任务管理组件（包含 JMeter 脚本库与任务编排执行）。
 */
export function ServerPerfWorkbench() {
  const [activeTab, setActiveTab] = useState<ServerSubTab>('scripts');
  const [viewRunId, setViewRunId] = useState<number | null>(null);

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
      {/* 内部二级导航栏 */}
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
          onClick={() => setActiveTab('scripts')}
          style={{
            background: 'transparent',
            border: 'none',
            borderBottom: activeTab === 'scripts' ? '2px solid var(--accent)' : '2px solid transparent',
            color: activeTab === 'scripts' ? 'var(--accent)' : 'var(--text-secondary)',
            fontWeight: activeTab === 'scripts' ? 600 : 500,
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
          <FileText size={13} />
          <span>JMeter 脚本库</span>
        </button>

        <button
          onClick={() => setActiveTab('tasks')}
          style={{
            background: 'transparent',
            border: 'none',
            borderBottom: activeTab === 'tasks' ? '2px solid var(--accent)' : '2px solid transparent',
            color: activeTab === 'tasks' ? 'var(--accent)' : 'var(--text-secondary)',
            fontWeight: activeTab === 'tasks' ? 600 : 500,
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
          <Layers size={13} />
          <span>压测任务管理</span>
        </button>
      </div>

      {/* 视图内容 */}
      <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        {activeTab === 'scripts' ? (
          <PerfScriptList />
        ) : (
          <PerfTaskList onOpenReport={(runId) => setViewRunId(runId)} />
        )}
      </div>

      {/* 报告弹窗 */}
      <PerfReportModal runId={viewRunId} onClose={() => setViewRunId(null)} />
    </div>
  );
}
