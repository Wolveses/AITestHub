import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Download, Globe, Play, RefreshCw, Search, Sparkles, Wrench, Eye, Square, Bot, Activity } from 'lucide-react';
import { useProjectStore } from '../../../../shared/store/projectStore';
import { useConfirmStore } from '../../../../shared/store/confirmStore';
import { useCapabilitiesStore } from '@/shared/store/capabilitiesStore';
import { ModuleHelpButton } from '../../../../shared/components/ModuleHelpButton';
import { useAutomationStore, type AutomationCase, fetchAuthoringActive, fetchAuthoringTriage, type AuthoringTriageSummary } from '../../store/automationStore';
import { CategoryTree } from './CategoryTree';
import { ImportCasesDialog } from './ImportCasesDialog';
import { CaseDetailDrawer } from './CaseDetailDrawer';
import { AgentAuthoringDialog } from './AgentAuthoringDialog';
import { AuthoringProgressDialog } from './AuthoringProgressDialog';
import { Btn, ErrorCategoryTag, StatusBadge, inputStyle } from './common';

const ACTIVE_STATUSES = new Set(['generating', 'fixing', 'running']);

export function AutomationPage() {
  const { t } = useTranslation();
  const aiAssistEnabled = useCapabilitiesStore((s) => s.aiAssistEnabled);
  const { projects, currentProjectId, loadProjects } = useProjectStore();
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
    envs,
    loadEnvs,
    switchEnv,
    generate,
    fix,
    cancelGenerate,
    run,
    deleteCase,
    updateCase,
  } = useAutomationStore();

  const [importOpen, setImportOpen] = useState(false);
  const [detailId, setDetailId] = useState<number | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [agentOpen, setAgentOpen] = useState(false);
  const [progressOpen, setProgressOpen] = useState(false);
  const [activeCount, setActiveCount] = useState(0);
  const [triageSummary, setTriageSummary] = useState<AuthoringTriageSummary | null>(null);
  // 本地 Agent 处理进度快照：用例从进行中消失（已入库）或版本变化时刷新列表
  const activeSnapshot = useRef<Map<number, string> | null>(null);

  const selectedIds = useMemo(() => Array.from(selected), [selected]);
  const allSelected = cases.length > 0 && cases.every((c) => selected.has(c.id));
  const nothingToDo =
    !!triageSummary &&
    triageSummary.create + triageSummary.fix + (triageSummary.regenerate || 0) === 0;

  const toggleSelect = (id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleSelectAll = () => {
    setSelected((prev) => {
      if (cases.every((c) => prev.has(c.id))) return new Set();
      return new Set(cases.map((c) => c.id));
    });
  };

  useEffect(() => {
    loadProjects();
  }, [loadProjects]);

  // 与顶部全局项目选择器保持联动
  useEffect(() => {
    if (currentProjectId !== null && currentProjectId !== projectId) {
      setProjectId(currentProjectId);
    }
  }, [currentProjectId, projectId, setProjectId]);

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

  // 勾选后预判本轮动作（防抖；失败静默，不影响按钮可用）
  useEffect(() => {
    if (projectId === null || selectedIds.length === 0) {
      setTriageSummary(null);
      return;
    }
    let cancelled = false;
    const timer = setTimeout(() => {
      fetchAuthoringTriage(projectId, selectedIds)
        .then((r) => {
          if (!cancelled) setTriageSummary(r.summary);
        })
        .catch(() => {
          if (!cancelled) setTriageSummary(null);
        });
    }, 350);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [projectId, selectedIds]);

  // 进行中的编写任务数量（弹窗打开时由弹窗自身轮询并回传，避免重复请求）
  useEffect(() => {
    if (projectId === null || progressOpen) return;
    activeSnapshot.current = null;
    let stopped = false;
    const tick = async () => {
      if (document.hidden) return;
      try {
        const list = await fetchAuthoringActive(projectId);
        if (stopped) return;
        setActiveCount(list.length);
        const next = new Map(list.map((item) => [item.case_id, `${item.stage}|${item.script_version}`]));
        const prev = activeSnapshot.current;
        // 首次只建基线；之后有新增/消失/阶段或版本变化，说明脚本链路推进了，刷新列表状态
        if (prev && (prev.size !== next.size || Array.from(prev).some(([id, key]) => next.get(id) !== key))) {
          void loadCases();
        }
        activeSnapshot.current = next;
      } catch {
        /* 静默，等待下次 */
      }
    };
    void tick();
    const timer = window.setInterval(() => void tick(), 5000);
    const onVisible = () => {
      if (!document.hidden) void tick();
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      stopped = true;
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [projectId, progressOpen]);

  const activeProjectName = projects.find((p) => p.id === projectId)?.name || '';

  const currentEnv = envs.find((e) => e.is_default) || envs[0];

  const handleEnvChange = async (envId: number) => {
    try {
      await switchEnv(envId);
      const target = envs.find((e) => e.id === envId);
      toast.success(t('ui.auto.envSwitched', '已切换到环境「{{name}}」', { name: target?.name || target?.base_url }));
    } catch (e) {
      toast.error((e as Error).message);
    }
  };

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
          setSelected((prev) => {
            if (!prev.has(c.id)) return prev;
            const next = new Set(prev);
            next.delete(c.id);
            return next;
          });
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
    // 脚本按端入口生成，已产出脚本后不允许再切换
    if (c.has_script || c.status === 'implemented') {
      toast.info(t('ui.auto.siteLocked', '用例已生成脚本，端不可再切换'));
      return;
    }
    void applySite(c, c.site === 'backend' ? 'frontend' : 'backend');
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
        <Btn variant="primary" onClick={() => setImportOpen(true)} disabled={projectId === null}>
          <Download size={14} /> {t('ui.auto.importCases', '导入用例')}
        </Btn>

        <Btn
          onClick={() => setAgentOpen(true)}
          disabled={projectId === null || selected.size === 0}
          title={
            selected.size === 0
              ? t('ui.auto.selectCasesFirst', '请先勾选用例')
              : nothingToDo
                ? t('ui.auto.nothingToDoHint', '选中用例均正在生成或执行中，暂无需处理')
                : triageSummary
                  ? t(
                      'ui.auto.triageHint',
                      '编写 {{create}} · 修复 {{fix}} · 重新生成 {{regenerate}} · 跳过 {{skip}}',
                      {
                        create: triageSummary.create,
                        fix: triageSummary.fix,
                        regenerate: triageSummary.regenerate || 0,
                        skip: triageSummary.skip,
                      },
                    )
                  : t('ui.auto.agentAuthoringHint', '生成文案并粘贴到本地 Agent，由它分诊后编写、修复或重新生成')
          }
        >
          <Bot size={14} /> {t('ui.auto.agentAuthoring', '本地 Agent 生成/修复')}
          {selected.size > 0 ? ` (${selected.size})` : ''}
        </Btn>

        <Btn
          onClick={() => setProgressOpen(true)}
          disabled={projectId === null}
          title={t('ui.auto.authoringProgressHint', '查看当前项目中校验/试跑通过、尚未入库的用例')}
        >
          <Activity size={14} /> {t('ui.auto.authoringProgress', '编写进度')}
          {activeCount > 0 ? ` (${activeCount})` : ''}
        </Btn>

        {/* 环境快速切换下拉 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
          <Globe size={14} style={{ color: 'var(--text-muted)' }} />
          <span style={{ color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>{t('ui.auto.env', '环境')}:</span>
          <select
            value={currentEnv?.id ?? ''}
            disabled={loading || envs.length === 0}
            onChange={(e) => e.target.value && handleEnvChange(Number(e.target.value))}
            style={{
              ...inputStyle,
              width: 'auto',
              maxWidth: 240,
              padding: '4px 8px',
              fontSize: 12,
              cursor: envs.length > 0 ? 'pointer' : 'default',
            }}
          >
            {envs.length === 0 ? (
              <option value="">{t('ui.auto.noEnvProjectTip', '暂无环境 (可在项目管理中添加)')}</option>
            ) : (
              envs.map((env) => (
                <option key={env.id} value={env.id}>
                  {env.name || '环境'} ({env.base_url}){env.is_default ? ' · 默认' : ''}
                </option>
              ))
            )}
          </select>
        </div>

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
              gridTemplateColumns: '28px 1fr 60px 110px 120px',
              gap: 8,
              padding: '8px 16px',
              fontSize: 11,
              color: 'var(--text-muted)',
              borderBottom: '1px solid var(--border)',
              background: 'var(--bg-card)',
              flexShrink: 0,
            }}
          >
            <span style={{ display: 'flex', alignItems: 'center' }}>
              <input
                type="checkbox"
                checked={allSelected}
                onChange={toggleSelectAll}
                title={t('ui.auto.selectAll', '全选当前列表')}
                style={{ accentColor: 'var(--accent)', cursor: 'pointer' }}
              />
            </span>
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
                const generating = c.status === 'generating' || c.status === 'fixing';
                return (
                  <div
                    key={c.id}
                    onClick={() => setDetailId(c.id)}
                    style={{
                      display: 'grid',
                      gridTemplateColumns: '28px 1fr 60px 110px 120px',
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
                    <span style={{ display: 'flex', alignItems: 'center' }} onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        checked={selected.has(c.id)}
                        onChange={() => toggleSelect(c.id)}
                        style={{ accentColor: 'var(--accent)', cursor: 'pointer' }}
                      />
                    </span>
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
                      title={
                        c.has_script || c.status === 'implemented'
                          ? t('ui.auto.siteLocked', '用例已生成脚本，端不可再切换')
                          : t('ui.auto.switchSiteHint', '点击切换前台/后台')
                      }
                      style={{
                        justifySelf: 'start',
                        padding: '1px 7px',
                        borderRadius: 9,
                        border: '1px solid var(--border)',
                        fontSize: 10,
                        color: c.site === 'backend' ? 'var(--accent)' : 'var(--text-secondary)',
                        cursor: active || c.has_script || c.status === 'implemented' ? 'not-allowed' : 'pointer',
                        opacity: active || c.has_script || c.status === 'implemented' ? 0.5 : 1,
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
                        <Btn
                          size="sm"
                          variant="primary"
                          disabled={active || !aiAssistEnabled}
                          title={
                            !aiAssistEnabled
                              ? t('ui.auto.aiAssistDisabledHint', '系统设置已关闭内置 LLM 脚本生成，请改用「本地 Agent」或前往系统设置开启')
                              : t('ui.auto.generateScript', '生成脚本')
                          }
                          onClick={() => withBusy(c.id, () => generate(c.id), t('ui.auto.generateQueued', '已提交生成任务'))}
                        >
                          <Sparkles size={12} />
                        </Btn>
                      ) : (
                        <Btn
                          size="sm"
                          disabled={active || (c.status !== 'implemented' && !aiAssistEnabled)}
                          title={
                            c.status === 'implemented'
                              ? t('ui.auto.runScript', '执行')
                              : !aiAssistEnabled
                                ? t('ui.auto.aiAssistDisabledHint', '系统设置已关闭内置 LLM 脚本生成，请改用「本地 Agent」或前往系统设置开启')
                                : t('ui.auto.generateScript', '生成脚本')
                          }
                          onClick={() => c.status === 'implemented' ? withBusy(c.id, () => run(c.id), t('ui.auto.runQueued', '已提交执行任务')) : withBusy(c.id, () => generate(c.id), t('ui.auto.generateQueued', '已提交生成任务'))}
                        >
                          {c.status === 'implemented' ? <Play size={12} /> : <RefreshCw size={12} />}
                        </Btn>
                      )}
                      <Btn
                        size="sm"
                        variant="ghost"
                        disabled={active || c.status !== 'implemented' || !aiAssistEnabled}
                        title={
                          !aiAssistEnabled
                            ? t('ui.auto.aiAssistDisabledHint', '系统设置已关闭内置 LLM 脚本生成，请改用「本地 Agent」或前往系统设置开启')
                            : t('ui.auto.autoFix', '自动修复')
                        }
                        onClick={() => withBusy(c.id, () => fix(c.id), t('ui.auto.fixQueued', '已提交修复任务'))}
                      >
                        <Wrench size={12} />
                      </Btn>
                      {generating && (
                        <Btn size="sm" variant="ghost" title={t('ui.auto.cancelGenerateHint', '停止当前生成/修复任务（已产生的临时资产会被丢弃）')} onClick={() => withBusy(c.id, () => cancelGenerate(c.id), t('ui.auto.cancelGenerateQueued', '已请求终止，正在停止任务'))}>
                          <Square size={12} />
                        </Btn>
                      )}
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

          <div style={{ padding: '6px 16px', borderTop: '1px solid var(--border)', fontSize: 11, color: 'var(--text-muted)', flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span>
              {activeProjectName} · {t('ui.auto.total', '共 {{count}} 条', { count: total })}
            </span>
            {currentEnv && (
              <span style={{ color: 'var(--text-secondary)' }}>
                {t('ui.auto.currentEnv', '当前环境')}: <strong style={{ color: 'var(--accent)' }}>{currentEnv.name || '环境'}</strong> ({currentEnv.base_url})
              </span>
            )}
          </div>
        </div>
      </div>

      <ImportCasesDialog open={importOpen} onClose={() => setImportOpen(false)} />
      <CaseDetailDrawer caseId={detailId} onClose={() => setDetailId(null)} />
      <AgentAuthoringDialog
        open={agentOpen}
        onClose={() => {
          setAgentOpen(false);
          setTriageSummary(null);
          loadCases();
        }}
        projectId={projectId}
        caseIds={selectedIds}
      />
      <AuthoringProgressDialog
        open={progressOpen}
        onClose={() => {
          setProgressOpen(false);
          loadCases();
        }}
        projectId={projectId}
        onCount={setActiveCount}
      />
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
