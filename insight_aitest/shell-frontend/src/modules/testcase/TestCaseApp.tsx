import { useEffect } from 'react';
import { useLocation, useNavigate, Outlet } from 'react-router-dom';
import { ArrowLeft, Plus, Sparkles, Camera } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { CaseFolderTree } from './components/CaseFolderTree';
import { CaseDetailDrawer } from './components/CaseDetailDrawer';
import { useCaseStore } from './store/caseStore';
import { useProjectStore } from '../../shared/store/projectStore';
import { useIsMobile } from '../../shared/hooks/useIsMobile';
import { ModuleHelpButton } from '../../shared/components/ModuleHelpButton';

type View = 'list' | 'generate' | 'image';

export function TestCaseApp() {
  const location = useLocation();
  const navigate = useNavigate();
  const { t } = useTranslation();
  const {
    loadCases,
    activeId,
    selectCase,
    createCase,
    currentFolderId,
    selectedProjectId,
    setSelectedProjectId,
  } = useCaseStore();
  const { projects, loadProjects } = useProjectStore();
  const isMobile = useIsMobile();

  useEffect(() => {
    loadProjects();
  }, [loadProjects]);

  // 用例必须归属项目：如果当前未指定有效项目，自动选中第一个项目（本地用例 store 状态，不污染全局）
  useEffect(() => {
    if (projects.length > 0 && (selectedProjectId === null || !projects.some((p) => p.id === selectedProjectId))) {
      setSelectedProjectId(projects[0].id);
    }
  }, [projects, selectedProjectId, setSelectedProjectId]);

  useEffect(() => {
    if (selectedProjectId !== null) {
      loadCases();
    }
  }, [loadCases, selectedProjectId, currentFolderId]);

  const seg = location.pathname.split('/').filter(Boolean).pop() ?? 'list';
  const view: View = (['list', 'generate', 'image'].includes(seg) ? seg : 'list') as View;

  const handleNew = async () => {
    const targetPid = selectedProjectId ?? (projects.length > 0 ? projects[0].id : null);
    if (!targetPid) {
      toast.warning(t('testcase.createProjectFirst', '请先创建或选择一个项目'));
      return;
    }
    const newId = await createCase({
      title: t('testcase.defaultCaseTitle', '新测试用例'),
      type: 'functional',
      folder_id: currentFolderId && currentFolderId > 0 ? currentFolderId : null,
      project_id: targetPid,
      version_id: null,
      content: { steps: [], expected: '' },
    });
    selectCase(newId);
    navigate('list', { replace: true });
  };

  return (
    <div
      style={{
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        background: 'var(--bg-base)',
        color: 'var(--text-primary)',
        overflow: 'hidden',
      }}
    >
      {/* 顶部操作栏：三个按钮水平平铺 */}
      <div
        style={{
          padding: '10px 16px',
          borderBottom: '1px solid var(--border)',
          background: 'var(--bg-card)',
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          flexShrink: 0,
        }}
      >
        {/* 新建用例 */}
        <button
          onClick={handleNew}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            padding: '7px 14px',
            borderRadius: 6,
            background: 'var(--accent)',
            color: '#fff',
            border: 'none',
            fontSize: 13,
            fontWeight: 500,
            cursor: 'pointer',
            transition: 'opacity 0.15s ease',
          }}
          onMouseEnter={(e) => (e.currentTarget.style.opacity = '0.9')}
          onMouseLeave={(e) => (e.currentTarget.style.opacity = '1')}
        >
          <Plus size={15} strokeWidth={2.2} /> {t('testcase.newCase', '新建用例')}
        </button>

        {/* AI 生成分析 */}
        <button
          onClick={() => navigate('generate')}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            padding: '7px 14px',
            borderRadius: 6,
            background: 'var(--bg-base)',
            color: 'var(--text-primary)',
            border: '1px solid var(--border)',
            fontSize: 13,
            fontWeight: 500,
            cursor: 'pointer',
            transition: 'background 0.15s ease',
          }}
          onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--bg-elevated)')}
          onMouseLeave={(e) => (e.currentTarget.style.background = 'var(--bg-base)')}
        >
          <Sparkles size={15} strokeWidth={1.8} style={{ color: 'var(--chart-2, #3b82f6)' }} />
          {t('testcase.aiAnalyzeGenerate', 'AI 生成分析')}
        </button>

        {/* 从截图生成 */}
        <button
          onClick={() => navigate('image')}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            padding: '7px 14px',
            borderRadius: 6,
            background: 'var(--bg-base)',
            color: 'var(--text-primary)',
            border: '1px solid var(--border)',
            fontSize: 13,
            fontWeight: 500,
            cursor: 'pointer',
            transition: 'background 0.15s ease',
          }}
          onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--bg-elevated)')}
          onMouseLeave={(e) => (e.currentTarget.style.background = 'var(--bg-base)')}
        >
          <Camera size={15} strokeWidth={1.8} style={{ color: 'var(--chart-4, #a855f7)' }} />
          {t('testcase.generateFromScreenshot', '从截图生成')}
        </button>

        {/* 子视图下返回列表按钮 */}
        {view !== 'list' && (
          <button
            onClick={() => navigate('list')}
            style={{
              background: 'none',
              border: '1px solid var(--border)',
              color: 'var(--text-secondary)',
              padding: '6px 12px',
              borderRadius: 6,
              cursor: 'pointer',
              display: 'inline-flex',
              alignItems: 'center',
              gap: 4,
              fontSize: 13,
              marginLeft: 8,
            }}
          >
            <ArrowLeft size={13} strokeWidth={1.5} /> {t('testcase.backToList', '返回用例列表')}
          </button>
        )}

        <div style={{ flex: 1 }} />
        <ModuleHelpButton namespace="testcase" />
      </div>

      {/* 主体工作区：左侧目录树 + 中间用例列表/子视图 */}
      <div
        style={{
          flex: 1,
          display: 'flex',
          flexDirection: isMobile ? 'column' : 'row',
          overflow: 'hidden',
        }}
      >
        {/* 左侧目录树 */}
        <CaseFolderTree />

        {/* 中间主内容区 */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          <Outlet />
        </div>
      </div>

      {/* 右侧用例详情抽屉 */}
      <CaseDetailDrawer
        caseId={activeId}
        open={activeId !== null && view === 'list'}
        onClose={() => selectCase(null)}
      />
    </div>
  );
}

export default TestCaseApp;
