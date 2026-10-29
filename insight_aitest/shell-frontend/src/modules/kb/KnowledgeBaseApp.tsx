import { useEffect, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { BookOpen, RefreshCw, Cloud, Bug, ListChecks } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { KnowledgeBase } from './components/KnowledgeBase';
import { TapdSyncModal } from './components/TapdSyncModal';
import { ModuleHelpButton } from '../../shared/components/ModuleHelpButton';
import { useKnowledgeStore } from './store/knowledgeStore';

type KbTab = 'local' | 'feishu' | 'defect' | 'case';

export function KnowledgeBaseApp() {
  const { t } = useTranslation();
  const location = useLocation();
  const { activeTab, setActiveTab, loadDocuments, syncingFeishu, setFeishuModalOpen } = useKnowledgeStore();
  const [tapdOpen, setTapdOpen] = useState(false);

  // 根据 URL 末段派生当前子路由：/kb/local、/kb/feishu、/kb/defect 或 /kb/case，默认为 local
  const seg = location.pathname.split('/').filter(Boolean).pop() ?? 'local';
  const currentTab: KbTab = seg === 'feishu' || seg === 'defect' || seg === 'case' ? seg : 'local';

  useEffect(() => {
    if (activeTab !== currentTab) {
      setActiveTab(currentTab);
    }
  }, [currentTab, activeTab, setActiveTab]);

  const tabTitle =
    currentTab === 'feishu'
      ? t('nav.kbFeishu', '飞书文档')
      : currentTab === 'defect'
        ? t('nav.defectLibrary', '缺陷库')
        : currentTab === 'case'
          ? t('nav.caseLibrary', '用例库')
          : t('nav.kbLocal', '本地文档');

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
          {/* 缺陷库、用例库为一级入口，不再挂在「知识库 /」下 */}
          {currentTab === 'defect' || currentTab === 'case' ? tabTitle : `${t('kb.title', '知识库')} / ${tabTitle}`}
        </span>

        {syncingFeishu && currentTab === 'feishu' && (
          <span style={{ fontSize: 12, color: 'var(--primary, #3b82f6)', display: 'inline-flex', alignItems: 'center', gap: 4 }}>
            <RefreshCw size={12} className="animate-spin" /> {t('kb.syncingFeishu', '正在同步飞书...')}
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
            title={t('kb.feishuSyncHint', '配置并同步飞书知识库空间')}
          >
            <Cloud size={13} />
            {t('kb.syncFeishu', '从飞书同步')}
          </button>
        )}
        {(currentTab === 'defect' || currentTab === 'case') && (
          <button
            onClick={() => setTapdOpen(true)}
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
              cursor: 'pointer',
              transition: 'all 0.15s ease',
            }}
            title={
              currentTab === 'case'
                ? t('kb.tapdCaseSyncHint', '从 TAPD 工作空间同步用例')
                : t('kb.tapdSyncHint', '从 TAPD 工作空间同步缺陷')
            }
          >
            {currentTab === 'case' ? <ListChecks size={13} /> : <Bug size={13} />}
            {t('kb.tapdSync', '从 TAPD 同步')}
          </button>
        )}
        <ModuleHelpButton namespace="kb" />
      </div>
      <KnowledgeBase />

      <TapdSyncModal
        open={tapdOpen}
        onOpenChange={setTapdOpen}
        mode={currentTab === 'case' ? 'case' : 'bug'}
        onSynced={() => loadDocuments({ resetPage: true })}
      />
    </div>
  );
}

export const LocalKnowledgeBaseApp = () => <KnowledgeBaseApp />;
export const FeishuKnowledgeBaseApp = () => <KnowledgeBaseApp />;
export const DefectKnowledgeBaseApp = () => <KnowledgeBaseApp />;
export const CaseKnowledgeBaseApp = () => <KnowledgeBaseApp />;

export default KnowledgeBaseApp;
