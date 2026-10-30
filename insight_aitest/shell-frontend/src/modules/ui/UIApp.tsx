import { useTranslation } from 'react-i18next';
import { Construction } from 'lucide-react';
import { AutomationPage } from './components/automation/AutomationPage';

/**
 * UI 自动化模块入口。
 *
 * 当前主链路：知识库用例快照 → AI 生成 Playwright 脚本 → 固化后本地执行。
 * 旧的 Midscene 视觉驱动页面（执行/编辑/看板/批量/定时/视觉配置）暂时雪藏：
 * 组件与后端接口保留，不再挂到路由，后续作为补充场景接入。
 */
export function UIApp() {
  return <AutomationPage />;
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
