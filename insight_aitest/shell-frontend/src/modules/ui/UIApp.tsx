import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Construction, ListChecks, CalendarCheck } from 'lucide-react';
import { AutomationPage } from './components/automation/AutomationPage';
import { TaskManagerPage } from './components/automation/TaskManagerPage';

type SubTab = 'cases' | 'tasks';

/**
 * UI 自动化模块入口。
 * 包含两个子 Tab：
 * 1. 自动化用例：管理用例资产、AI 生成与本地脚本执行；
 * 2. 任务管理：管理批次任务、从自动化用例导入已实现用例、定时调度、执行历史与测试报告。
 */
export function UIApp() {
  const [activeTab, setActiveTab] = useState<SubTab>('cases');

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: 'var(--bg-base)' }}>
      {/* 子 Tab 导航栏 */}
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
          onClick={() => setActiveTab('cases')}
          style={{
            background: 'transparent',
            border: 'none',
            borderBottom: activeTab === 'cases' ? '2px solid var(--accent)' : '2px solid transparent',
            color: activeTab === 'cases' ? 'var(--accent)' : 'var(--text-secondary)',
            fontWeight: activeTab === 'cases' ? 600 : 500,
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
          <ListChecks size={15} />
          <span>自动化用例</span>
        </button>

        <button
          onClick={() => setActiveTab('tasks')}
          style={{
            background: 'transparent',
            border: 'none',
            borderBottom: activeTab === 'tasks' ? '2px solid var(--accent)' : '2px solid transparent',
            color: activeTab === 'tasks' ? 'var(--accent)' : 'var(--text-secondary)',
            fontWeight: activeTab === 'tasks' ? 600 : 500,
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
          <CalendarCheck size={15} />
          <span>任务管理</span>
        </button>
      </div>

      {/* Tab 内容区 */}
      <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        {activeTab === 'cases' ? <AutomationPage /> : <TaskManagerPage />}
      </div>
    </div>
  );
}

/** 移动端占位（路由已雪藏，保留导出避免其它模块引用断裂）。 */
export function MobilePlaceholder() {
  const { t } = useTranslation();
  return (
    <div
      style={{
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 48,
        gap: 16,
      }}
    >
      <Construction size={48} strokeWidth={1} style={{ color: 'var(--chart-4)', opacity: 0.6 }} />
      <h2 style={{ fontSize: 18, color: 'var(--text-primary)', margin: 0 }}>{t('ui.mobileTitle')}</h2>
      <p style={{ fontSize: 13, color: 'var(--text-muted)', textAlign: 'center', maxWidth: 400, lineHeight: 1.6 }}>
        {t('ui.mobileComingSoonDesc')}
        <br />
        {t('ui.mobileAppiumDesc')}
      </p>
    </div>
  );
}

export default UIApp;
