import { useEffect, useMemo, useRef, useState } from 'react';
import { Activity, Bot, Download, Eye, ListChecks, Play, RefreshCw, Search, Smartphone, Square } from 'lucide-react';
import { toast } from 'sonner';
import { useProjectStore } from '../../shared/store/projectStore';
import { useConfirmStore } from '../../shared/store/confirmStore';
import { CategoryTree } from '../ui/components/automation/CategoryTree';
import { Btn, ErrorCategoryTag, StatusBadge, inputStyle } from './components/common';
import { ImportCasesDialog } from './components/ImportCasesDialog';
import { GenerateSessionModal } from './components/GenerateSessionModal';
import { AuthoringProgressDialog } from './components/AuthoringProgressDialog';
import { CaseDetailDrawer } from './components/CaseDetailDrawer';
import { DevicePanel } from './components/DevicePanel';
import { AppManagerPanel } from './components/AppManagerPanel';
import { useMobileStore, type MobileCase } from './store/mobileStore';

type MainTab = 'cases' | 'infra';

export function MobileApp() {
  const { projects, currentProjectId, loadProjects } = useProjectStore();
  const { confirm } = useConfirmStore();
  const {
    projectId,
    setProjectId,
    cases,
    total,
    loading,
    statusFilter,
    categoryFilter,
    keyword,
    apps,
    devices,
    setStatusFilter,
    setCategoryFilter,
    setKeyword,
    loadCases,
    loadApps,
    loadDevices,
    deleteCase,
    cancelGenerate,
    getActiveGenerations,
  } = useMobileStore();

  const [activeTab, setActiveTab] = useState<MainTab>('cases');
  const [importOpen, setImportOpen] = useState(false);
  const [drawerCase, setDrawerCase] = useState<MobileCase | null>(null);
  const [genCase, setGenCase] = useState<MobileCase | null>(null);
  const [agentOpen, setAgentOpen] = useState(false);
  const [progressOpen, setProgressOpen] = useState(false);
  const [activeCount, setActiveCount] = useState(0);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [stoppingCaseId, setStoppingCaseId] = useState<number | null>(null);
  const activeSnapshot = useRef<Map<number, string> | null>(null);

  const selectedCases = useMemo(
    () => cases.filter((c) => selected.has(c.id)),
    [cases, selected]
  );
  const allSelected = cases.length > 0 && cases.every((c) => selected.has(c.id));

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
    void loadProjects();
  }, [loadProjects]);

  // 与顶部全局项目选择器保持联动
  useEffect(() => {
    const active = currentProjectId ?? projects[0]?.id ?? null;
    if (active !== null && active !== projectId) {
      setProjectId(active);
    }
  }, [currentProjectId, projects, projectId, setProjectId]);

  useEffect(() => {
    if (projectId !== null) {
      void Promise.all([loadCases(), loadApps(), loadDevices()]);
    }
  }, [projectId, statusFilter, categoryFilter, loadCases, loadApps, loadDevices]);

  // 搜索防抖
  useEffect(() => {
    const timer = window.setTimeout(() => {
      if (projectId !== null) void loadCases();
    }, 350);
    return () => window.clearTimeout(timer);
  }, [keyword, projectId, loadCases]);

  const activeDrawerCase = drawerCase
    ? cases.find((c) => c.id === drawerCase.id) ?? drawerCase
    : null;
  const activeGenCase = genCase
    ? cases.find((c) => c.id === genCase.id) ?? genCase
    : null;
  const hasActiveCases = cases.some(
    (c) => c.status === 'generating' || c.status === 'fixing' || c.status === 'running'
  );

  // 有进行中的生成或执行任务时，轻量轮询同步列表与设备状态
  useEffect(() => {
    if (!hasActiveCases || projectId === null) return;
    const timer = window.setInterval(() => {
      void Promise.all([loadCases(), loadDevices()]);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [hasActiveCases, projectId, loadCases, loadDevices]);

  // 进行中的编写任务数量（参照 UI 自动化：进度弹窗关闭时由页面轻量轮询）
  useEffect(() => {
    if (projectId === null || progressOpen) return;
    activeSnapshot.current = null;
    let stopped = false;
    const tick = async () => {
      if (document.hidden) return;
      try {
        const list = await getActiveGenerations(projectId);
        if (stopped) return;
        setActiveCount(list.length);
        const next = new Map(
          list.map((item) => [item.case_id, `${item.stage}|${item.tool_calls}`])
        );
        const prev = activeSnapshot.current;
        if (
          prev &&
          (prev.size !== next.size ||
            Array.from(prev).some(([id, key]) => next.get(id) !== key))
        ) {
          void Promise.all([loadCases(), loadDevices()]);
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
  }, [projectId, progressOpen, getActiveGenerations, loadCases, loadDevices]);

  const handleStopGenerate = async (c: MobileCase) => {
    setStoppingCaseId(c.id);
    try {
      await cancelGenerate(c.id);
      toast.info(`已停止「${c.title}」的生成会话并释放设备`);
    } catch (e) {
      toast.error(`停止失败: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setStoppingCaseId(null);
    }
  };

  const activeProjectName = projects.find((p) => p.id === projectId)?.name || '';
  const defaultApp = apps.find((a) => a.is_default) || apps[0];
  const onlineDevicesCount = devices.filter((d) => d.status === 'online').length;

  const handleDelete = (c: MobileCase) => {
    confirm({
      title: '删除用例',
      message: `确定删除「${c.title}」吗？脚本文件不会自动清理。`,
      variant: 'danger',
      onConfirm: async () => {
        try {
          await deleteCase(c.id);
          if (drawerCase?.id === c.id) setDrawerCase(null);
          setSelected((prev) => {
            if (!prev.has(c.id)) return prev;
            const next = new Set(prev);
            next.delete(c.id);
            return next;
          });
          toast.success('已删除');
        } catch (e) {
          toast.error(`删除失败: ${e instanceof Error ? e.message : String(e)}`);
        }
      },
    });
  };

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: 'var(--bg-base)', color: 'var(--text-primary)' }}>
      {/* 子 Tab 导航栏（对齐 UI 自动化） */}
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
          onClick={() => setActiveTab('infra')}
          style={{
            background: 'transparent',
            border: 'none',
            borderBottom: activeTab === 'infra' ? '2px solid var(--accent)' : '2px solid transparent',
            color: activeTab === 'infra' ? 'var(--accent)' : 'var(--text-secondary)',
            fontWeight: activeTab === 'infra' ? 600 : 500,
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
          <Smartphone size={15} />
          <span>设备与 App</span>
        </button>
      </div>

      {activeTab === 'cases' ? (
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0, overflow: 'hidden' }}>
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
              <Download size={14} /> 从用例库导入
            </Btn>

            <Btn
              onClick={() => setAgentOpen(true)}
              disabled={projectId === null || selected.size === 0}
              title={
                selected.size === 0
                  ? '请先勾选用例'
                  : '创建本地 Agent 生成/修复会话并签发 MCP 配置与提示词'
              }
            >
              <Bot size={14} /> 本地 Agent 生成/修复
              {selected.size > 0 ? ` (${selected.size})` : ''}
            </Btn>

            <Btn
              onClick={() => setProgressOpen(true)}
              disabled={projectId === null}
              title="查看当前项目中进行中的生成会话与真机锁定状态"
            >
              <Activity size={14} /> 编写进度
              {activeCount > 0 ? ` (${activeCount})` : ''}
            </Btn>

            {/* 默认 App 与在线设备摘要（对齐 UI 自动化工具栏环境信息） */}
            <button
              onClick={() => setActiveTab('infra')}
              title="点击管理设备池与被测 App 环境"
              style={{
                background: 'transparent',
                border: '1px solid var(--border)',
                borderRadius: 6,
                padding: '4px 10px',
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
                fontSize: 12,
                color: 'var(--text-secondary)',
                cursor: 'pointer',
              }}
            >
              <Smartphone size={13} style={{ color: 'var(--text-muted)' }} />
              <span>
                App: {defaultApp ? defaultApp.name : '未配置'} · 在线设备 {onlineDevicesCount} 台
              </span>
            </button>

            <div style={{ flex: 1 }} />

            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              style={{ ...inputStyle, width: 130 }}
            >
              <option value="">全部状态</option>
              <option value="not_implemented">未实现</option>
              <option value="generating">生成中</option>
              <option value="implemented">已实现</option>
              <option value="fixing">修复中</option>
              <option value="running">执行中</option>
            </select>

            <div style={{ position: 'relative' }}>
              <Search size={13} style={{ position: 'absolute', left: 8, top: 8, color: 'var(--text-muted)' }} />
              <input
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') void loadCases();
                }}
                placeholder="搜索用例标题"
                style={{ ...inputStyle, width: 200, paddingLeft: 26 }}
              />
            </div>

            <Btn size="sm" onClick={() => void loadCases()} disabled={loading} title="刷新">
              <RefreshCw size={13} style={{ opacity: loading ? 0.5 : 1 }} />
            </Btn>
          </div>

          {/* 左侧目录树 + 右侧用例列表 */}
          <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
            <CategoryTree
              items={cases}
              active={categoryFilter}
              onSelect={setCategoryFilter}
              allLabel="全部用例"
            />

            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
              {/* 列表表头 */}
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: '28px 1fr 110px 130px',
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
                    title="全选当前列表"
                    style={{ accentColor: 'var(--accent)', cursor: 'pointer' }}
                  />
                </span>
                <span>用例标题</span>
                <span>状态</span>
                <span>操作</span>
              </div>

              <div style={{ flex: 1, overflowY: 'auto' }}>
                {projectId === null ? (
                  <Empty text="请先选择项目" />
                ) : cases.length === 0 && !loading ? (
                  <Empty text="暂无自动化用例，点击「从用例库导入」接入用例" />
                ) : (
                  cases.map((c) => {
                    const isGenerating = c.status === 'generating' || c.status === 'fixing';
                    const isActive = isGenerating || c.status === 'running';
                    return (
                    <div
                      key={c.id}
                      onClick={() => setDrawerCase(c)}
                      style={{
                        display: 'grid',
                        gridTemplateColumns: '28px 1fr 110px 130px',
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
                          <span style={{ fontSize: 10, color: 'var(--text-muted)', flexShrink: 0 }}>
                            v{c.script_version}
                          </span>
                        )}
                        {c.last_error_category && (
                          <ErrorCategoryTag category={c.last_error_category} />
                        )}
                      </div>

                      <span>
                        <StatusBadge status={c.status} />
                      </span>

                      <div style={{ display: 'flex', gap: 4 }} onClick={(e) => e.stopPropagation()}>
                        {isGenerating && (
                          <Btn
                            size="sm"
                            variant="danger"
                            title="停止生成并释放设备"
                            disabled={stoppingCaseId === c.id}
                            onClick={() => void handleStopGenerate(c)}
                          >
                            <Square size={12} />
                          </Btn>
                        )}
                        <Btn
                          size="sm"
                          disabled={isActive || !c.has_script}
                          title={isActive ? '用例正在生成或执行中' : c.has_script ? '运行脚本' : '请先生成脚本'}
                          onClick={() => setDrawerCase(c)}
                        >
                          <Play size={12} />
                        </Btn>
                        <Btn
                          size="sm"
                          variant="ghost"
                          title="详情"
                          onClick={() => setDrawerCase(c)}
                        >
                          <Eye size={12} />
                        </Btn>
                        <Btn
                          size="sm"
                          variant="ghost"
                          disabled={isActive}
                          title={isActive ? '进行中不可删除' : '删除用例'}
                          onClick={() => handleDelete(c)}
                        >
                          ×
                        </Btn>
                      </div>
                    </div>
                    );
                  })
                )}
              </div>

              {/* 底部汇总栏 */}
              <div
                style={{
                  padding: '6px 16px',
                  borderTop: '1px solid var(--border)',
                  fontSize: 11,
                  color: 'var(--text-muted)',
                  flexShrink: 0,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                }}
              >
                <span>
                  {activeProjectName} · 共 {total} 条
                </span>
                {defaultApp && (
                  <span style={{ color: 'var(--text-secondary)' }}>
                    默认 App: <strong style={{ color: 'var(--accent)' }}>{defaultApp.name}</strong> ({defaultApp.app_package})
                  </span>
                )}
              </div>
            </div>
          </div>
        </div>
      ) : (
        <div style={{ flex: 1, overflowY: 'auto', padding: 16, display: 'flex', flexDirection: 'column', gap: 20 }}>
          <DevicePanel />
          <AppManagerPanel />
        </div>
      )}

      <ImportCasesDialog
        open={importOpen}
        onClose={() => {
          setImportOpen(false);
          void loadCases();
        }}
      />

      <GenerateSessionModal
        open={agentOpen || !!activeGenCase}
        targetCase={activeGenCase}
        targetCases={agentOpen ? selectedCases : undefined}
        onClose={() => {
          setAgentOpen(false);
          setGenCase(null);
          void Promise.all([loadCases(), loadDevices()]);
        }}
      />

      <AuthoringProgressDialog
        open={progressOpen}
        onClose={() => {
          setProgressOpen(false);
          void Promise.all([loadCases(), loadDevices()]);
        }}
        projectId={projectId}
        onCount={setActiveCount}
        onOpenSession={(cid) => {
          const found = cases.find((item) => item.id === cid);
          if (found) setGenCase(found);
        }}
      />

      <CaseDetailDrawer
        targetCase={activeDrawerCase}
        onClose={() => setDrawerCase(null)}
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

export default MobileApp;
