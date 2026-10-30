import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Download, Play, RefreshCw, Search, Settings2, Sparkles, Wrench, Eye } from 'lucide-react';
import { useProjectStore } from '../../../../shared/store/projectStore';
import { useConfirmStore } from '../../../../shared/store/confirmStore';
import { ModuleHelpButton } from '../../../../shared/components/ModuleHelpButton';
import { useAutomationStore, type AutomationCase } from '../../store/automationStore';
import { CategoryTree } from './CategoryTree';
import { ImportCasesDialog } from './ImportCasesDialog';
import { CaseDetailDrawer } from './CaseDetailDrawer';
import { EnvManagerDialog } from './EnvManagerDialog';
import { Btn, ErrorCategoryTag, StatusBadge, inputStyle } from './common';

const ACTIVE_STATUSES = new Set(['generating', 'fixing', 'running']);

export function AutomationPage() {
  const { t } = useTranslation();
  const { projects, loadProjects } = useProjectStore();
  const { confirm } = useConfirmStore();
  const {
    projectId,
    setProjectId,
    cases,
    total,
    loading,
    statusFilter,
    setStatusFilter,
    categoryFilter,
    setCategoryFilter,
    keyword,
    setKeyword,
    loadCases,
    loadEnvs,
    generate,
    fix,
    run,
    deleteCase,
    updateCase,
  } = useAutomationStore();

  const [importOpen, setImportOpen] = useState(false);
  const [envOpen, setEnvOpen] = useState(false);
  const [detailId, setDetailId] = useState<number | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  useEffect(() => {
    loadProjects();
  }, [loadProjects]);

  // 记住的项目被删除时回退到第一个项目
  useEffect(() => {
    if (projects.length === 0) return;
    if (projectId === null || !projects.some((p) => p.id === projectId)) {
      setProjectId(projects[0].id);
    }
  }, [projects, projectId, setProjectId]);

  useEffect(() => {
    if (projectId !== null) {
      loadCases();
      loadEnvs();
    }
  }, [projectId, statusFilter, categoryFilter, loadCases, loadEnvs]);

  // 搜索防抖
  useEffect(() => {
    const timer = setTimeout(() => {
      if (projectId !== null) loadCases();
    }, 350);
    return () => clearTimeout(timer);
  }, [keyword, projectId, loadCases]);

  // 生成/执行中的用例轮询进度
  const hasActive = useMemo(() => cases.some((c) => ACTIVE_STATUSES.has(c.status)), [cases]);
  useEffect(() => {
    if (!hasActive) return;
    const timer = setInterval(() => {
      loadCases();
    }, 4000);
    return () => clearInterval(timer);
  }, [hasActive, loadCases]);

  const activeProjectName = projects.find((p) => p.id === projectId)?.name || '';

  const withBusy = async (id: number, fn: () => Promise<void>, okMsg: string) => {
    setBusyId(id);
    try {
      await fn();
      toast.success(okMsg);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusyId(null);
    }
  };

  const handleDelete = (c: AutomationCase) => {
    confirm({
      title: t('ui.auto.deleteCase', '删除用例'),
      message: t('ui.auto.deleteCaseConfirm', '确定删除「{{title}}」吗？脚本文件不会自动清理。', { title: c.title }),
      variant: 'danger',
      onConfirm: async () => {
        try {
          await deleteCase(c.id);
          toast.success(t('ui.auto.deleted', '已删除'));
        } catch (e) {
          toast.error((e as Error).message);
        }
      },
    });
  };

  const siteLabel = (s: string) =>
    s === 'backend' ? t('ui.auto.siteBackend', '后台') : t('ui.auto.siteFrontend', '前台');

  const applySite = async (c: AutomationCase, next: string) => {
    try {
      await updateCase(c.id, { site: next });
      toast.success(t('ui.auto.siteSwitched', '已切换到{{site}}', { site: siteLabel(next) }));
    } catch (e) {
      toast.error((e as Error).message);
    }
  };

  const handleSiteToggle = (c: AutomationCase) => {
    if (ACTIVE_STATUSES.has(c.status) || busyId === c.id) return;
    const next = c.site === 'backend' ? 'frontend' : 'backend';
    if (c.has_script || c.status === 'implemented') {
      confirm({
        title: t('ui.auto.switchSite', '切换端'),
        message: t(
          'ui.auto.switchSiteConfirm',
          '切换端会改变入口地址，旧脚本将归档，需要重新生成脚本。确定继续吗？',
        ),
        onConfirm: () => void applySite(c, next),
      });
      return;
    }
    void applySite(c, next);
  };

  const statusLabel = (s: string) =>
    ({
      not_implemented: t('ui.auto.statusNotImplemented', '未实现'),
      generating: t('ui.auto.statusGenerating', '生成中'),
      implemented: t('ui.auto.statusImplemented', '已实现'),
      fixing: t('ui.auto.statusFixing', '修复中'),
      running: t('ui.auto.statusRunning', '执行中'),
    })[s] || s;

  const errorLabel = (c: string | null) =>
    c === 'environment'
      ? t('ui.auto.errorCategoryEnvironment', '环境问题')
      : c === 'case_info'
        ? t('ui.auto.errorCategoryCase', '用例信息不完善')
        : c === 'model'
          ? t('ui.auto.errorCategoryModel', '模型问题')
          : c === 'script'
            ? t('ui.auto.errorCategoryScript', '脚本缺陷')
            : '';

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: 'var(--bg-base)', color: 'var(--text-primary)', overflow: 'hidden' }}>
      {/* 顶部工具栏 */}
      <div
        style={{
          padding: '10px 16px',
          borderBottom: '1px solid var(--border)',
          background: 'var(--bg-card)',
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          flexShrink: 0,
          flexWrap: 'wrap',
        }}
      >
        <select
          value={projectId ?? ''}
          onChange={(e) => setProjectId(Number(e.target.value))}
          style={{ ...inputStyle, width: 180 }}
          title={t('ui.auto.selectProject', '选择项目')}
        >
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>

        <Btn variant="primary" onClick={() => setImportOpen(true)} disabled={projectId === null}>
          <Download size={14} /> {t('ui.auto.importCases', '导入用例')}
        </Btn>
        <Btn onClick={() => setEnvOpen(true)} disabled={projectId === null}>
          <Settings2 size={14} /> {t('ui.auto.manageEnv', '环境管理')}
        </Btn>

        <div style={{ flex: 1 }} />

        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          style={{ ...inputStyle, width: 130 }}
        >
          <option value="">{t('ui.auto.allStatus', '全部状态')}</option>
          <option value="not_implemented">{t('ui.auto.statusNotImplemented', '未实现')}</option>
          <option value="generating">{t('ui.auto.statusGenerating', '生成中')}</option>
          <option value="implemented">{t('ui.auto.statusImplemented', '已实现')}</option>
          <option value="fixing">{t('ui.auto.statusFixing', '修复中')}</option>
          <option value="running">{t('ui.auto.statusRunning', '执行中')}</option>
        </select>

        <div style={{ position: 'relative' }}>
          <Search size={13} style={{ position: 'absolute', left: 8, top: 8, color: 'var(--text-muted)' }} />
          <input
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            placeholder={t('ui.auto.searchPlaceholder', '搜索用例标题')}
            style={{ ...inputStyle, width: 200, paddingLeft: 26 }}
          />
        </div>
        <Btn size="sm" onClick={() => loadCases()} disabled={loading} title={t('ui.auto.refresh', '刷新')}>
          <RefreshCw size={13} style={{ opacity: loading ? 0.5 : 1 }} />
        </Btn>
        <ModuleHelpButton namespace="ui" />
      </div>

      <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
        <CategoryTree
          items={cases}
          active={categoryFilter}
          onSelect={setCategoryFilter}
          allLabel={t('ui.auto.allCases', '全部用例')}
        />

        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
          {/* 列表表头 */}
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '1fr 60px 110px 90px',
              gap: 8,
              padding: '8px 16px',
              fontSize: 11,
              color: 'var(--text-muted)',
              borderBottom: '1px solid var(--border)',
              background: 'var(--bg-card)',
              flexShrink: 0,
            }}
          >
            <span>{t('ui.auto.caseTitle', '用例标题')}</span>
            <span>{t('ui.auto.site', '端')}</span>
            <span>{t('ui.auto.status', '状态')}</span>
            <span>{t('ui.auto.actions', '操作')}</span>
          </div>

          <div style={{ flex: 1, overflowY: 'auto' }}>
            {projectId === null ? (
              <Empty text={t('ui.auto.selectProjectFirst', '请先选择项目')} />
            ) : cases.length === 0 && !loading ? (
              <Empty text={t('ui.auto.noCases', '暂无自动化用例，点击「导入用例」从用例库导入')} />
            ) : (
              cases.map((c) => {
                const active = ACTIVE_STATUSES.has(c.status) || busyId === c.id;
                return (
                  <div
                    key={c.id}
                    onClick={() => setDetailId(c.id)}
                    style={{
                      display: 'grid',
                      gridTemplateColumns: '1fr 60px 110px 90px',
                      gap: 8,
                      alignItems: 'center',
                      padding: '9px 16px',
                      borderBottom: '1px solid var(--bg-card)',
                      fontSize: 12,
                      cursor: 'pointer',
                    }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--surface-hover)')}
                    onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
                      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={c.title}>
                        {c.title}
                      </span>
                      {c.script_version > 0 && (
                        <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>v{c.script_version}</span>
                      )}
                      {c.last_error_category && (
                        <ErrorCategoryTag category={c.last_error_category} label={errorLabel(c.last_error_category)} />
                      )}
                    </div>
                    <span
                      onClick={(e) => {
                        e.stopPropagation();
                        handleSiteToggle(c);
                      }}
                      title={t('ui.auto.switchSiteHint', '点击切换前台/后台')}
                      style={{
                        justifySelf: 'start',
                        padding: '1px 7px',
                        borderRadius: 9,
                        border: '1px solid var(--border)',
                        fontSize: 10,
                        color: c.site === 'backend' ? 'var(--accent)' : 'var(--text-secondary)',
                        cursor: active ? 'not-allowed' : 'pointer',
                        opacity: active ? 0.5 : 1,
                      }}
                    >
                      {siteLabel(c.site)}
                    </span>
                    <span>
                      <StatusBadge status={c.status} label={statusLabel(c.status)} />
                      {active && c.progress?.message && (
                        <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }} title={c.progress.message}>
                          {c.progress.phase} · {c.progress.message}
                        </div>
                      )}
                    </span>
                    <div style={{ display: 'flex', gap: 4 }} onClick={(e) => e.stopPropagation()}>
                      {!c.has_script ? (
                        <Btn size="sm" variant="primary" disabled={active} title={t('ui.auto.generateScript', '生成脚本')} onClick={() => withBusy(c.id, () => generate(c.id), t('ui.auto.generateQueued', '已提交生成任务'))}>
                          <Sparkles size={12} />
                        </Btn>
                      ) : (
                        <Btn size="sm" disabled={active} title={c.status === 'implemented' ? t('ui.auto.runScript', '执行') : t('ui.auto.generateScript', '生成脚本')} onClick={() => c.status === 'implemented' ? withBusy(c.id, () => run(c.id), t('ui.auto.runQueued', '已提交执行任务')) : withBusy(c.id, () => generate(c.id), t('ui.auto.generateQueued', '已提交生成任务'))}>
                          {c.status === 'implemented' ? <Play size={12} /> : <RefreshCw size={12} />}
                        </Btn>
                      )}
                      <Btn size="sm" variant="ghost" disabled={active || c.status !== 'implemented'} title={t('ui.auto.autoFix', '自动修复')} onClick={() => withBusy(c.id, () => fix(c.id), t('ui.auto.fixQueued', '已提交修复任务'))}>
                        <Wrench size={12} />
                      </Btn>
                      <Btn size="sm" variant="ghost" title={t('ui.auto.viewDetail', '详情')} onClick={() => setDetailId(c.id)}>
                        <Eye size={12} />
                      </Btn>
                      <Btn size="sm" variant="ghost" disabled={active} title={t('ui.auto.deleteCase', '删除用例')} onClick={() => handleDelete(c)}>
                        ×
                      </Btn>
                    </div>
                  </div>
                );
              })
            )}
          </div>

          <div style={{ padding: '6px 16px', borderTop: '1px solid var(--border)', fontSize: 11, color: 'var(--text-muted)', flexShrink: 0 }}>
            {activeProjectName} · {t('ui.auto.total', '共 {{count}} 条', { count: total })}
          </div>
        </div>
      </div>

      <ImportCasesDialog open={importOpen} onClose={() => setImportOpen(false)} />
      <EnvManagerDialog open={envOpen} onClose={() => setEnvOpen(false)} />
      <CaseDetailDrawer caseId={detailId} onClose={() => setDetailId(null)} />
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', padding: 40, color: 'var(--text-muted)', fontSize: 13 }}>
      {text}
    </div>
  );
}

export default AutomationPage;
