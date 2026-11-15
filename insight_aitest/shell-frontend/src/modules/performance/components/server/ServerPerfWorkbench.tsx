import { useState } from 'react';
import { FileText, Layers, Server } from 'lucide-react';
import { PerfScriptList } from './PerfScriptList';
import { PerfTaskList } from './PerfTaskList';
import { PerfSlaveNodeList } from './PerfSlaveNodeList';

type ServerSubTab = 'scripts' | 'tasks' | 'nodes';

/**
 * 测试脚本与压测任务管理组件（包含 JMeter 脚本库、任务编排执行与分布式从机节点管理）。
 */
export function ServerPerfWorkbench() {
  const [activeTab, setActiveTab] = useState<ServerSubTab>('scripts');

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

        <button
          onClick={() => setActiveTab('nodes')}
          style={{
            background: 'transparent',
            border: 'none',
            borderBottom: activeTab === 'nodes' ? '2px solid var(--accent)' : '2px solid transparent',
            color: activeTab === 'nodes' ? 'var(--accent)' : 'var(--text-secondary)',
            fontWeight: activeTab === 'nodes' ? 600 : 500,
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
          <span>分布式从机节点</span>
        </button>
      </div>

      {/* 视图内容 */}
      <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        {activeTab === 'scripts' ? (
          <PerfScriptList />
        ) : activeTab === 'tasks' ? (
          <PerfTaskList />
        ) : (
          <PerfSlaveNodeList />
        )}
      </div>
    </div>
  );
}
