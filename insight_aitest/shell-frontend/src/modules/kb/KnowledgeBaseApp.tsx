import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { BookOpen, RefreshCw, Cloud } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { KnowledgeBase } from './components/KnowledgeBase';
import { ModuleHelpButton } from '../../shared/components/ModuleHelpButton';
import { useKnowledgeStore } from './store/knowledgeStore';

export function KnowledgeBaseApp() {
  const { t } = useTranslation();
  const location = useLocation();
  const { activeTab, setActiveTab, syncingFeishu, setFeishuModalOpen } = useKnowledgeStore();

  // 根据 URL 末段派生当前子路由：/kb/local 或 /kb/feishu，默认为 local
  const seg = location.pathname.split('/').filter(Boolean).pop() ?? 'local';
  const currentTab = seg === 'feishu' ? 'feishu' : 'local';

  useEffect(() => {
    if (activeTab !== currentTab) {
      setActiveTab(currentTab);
    }
  }, [currentTab, activeTab, setActiveTab]);

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: "var(--bg-base)", color: "var(--text-primary)" }}>
      {/* 顶部标题栏（无多余二级 Tab，纯粹标题 + 操作 + 帮助） */}
      <div
        style={{
          padding: '8px 16px',
          borderBottom: '1px solid var(--bg-card)',
          display: 'flex',
          alignItems: 'center',
          gap: 16,
        }}
      >
        <span style={{ fontSize: 13, color: "var(--text-secondary)", display: 'inline-flex', alignItems: 'center', gap: 6, fontWeight: 500 }}>
          <BookOpen size={15} strokeWidth={1.5} />
          {t('kb.title', '知识库')} / {currentTab === 'feishu' ? t('nav.kbFeishu', '飞书文档') : t('nav.kbLocal', '本地文档')}
        </span>

        {syncingFeishu && currentTab === 'feishu' && (
          <span style={{ fontSize: 12, color: 'var(--primary, #3b82f6)', display: 'inline-flex', alignItems: 'center', gap: 4 }}>
            <RefreshCw size={12} className="animate-spin" /> 正在同步飞书...
          </span>
        )}

        <div style={{ flex: 1 }} />
        {currentTab === 'feishu' && (
          <button
            onClick={() => setFeishuModalOpen(true)}
            disabled={syncingFeishu}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 5,
              background: 'transparent',
              color: 'var(--text-secondary)',
              border: '1px solid var(--border-color, rgba(148,163,184,0.25))',
              borderRadius: 6,
              padding: '4px 10px',
              fontSize: 12,
              fontWeight: 500,
              cursor: syncingFeishu ? 'not-allowed' : 'pointer',
              opacity: syncingFeishu ? 0.6 : 1,
              transition: 'all 0.15s ease',
            }}
            title="配置并同步飞书知识库空间"
          >
            <Cloud size={13} />
            同步飞书
          </button>
        )}
        <ModuleHelpButton namespace="kb" />
      </div>
      <KnowledgeBase />
    </div>
  );
}

export const LocalKnowledgeBaseApp = () => <KnowledgeBaseApp />;
export const FeishuKnowledgeBaseApp = () => <KnowledgeBaseApp />;

export default KnowledgeBaseApp;
