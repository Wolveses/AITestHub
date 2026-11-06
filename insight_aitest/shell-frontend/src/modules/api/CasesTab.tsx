import { useEffect, useState, type CSSProperties } from 'react';
import { Play, Plus, Pencil, Trash2, History, ChevronDown, ChevronRight, Check, X, AlertTriangle, Layers, FileText } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { useRunStore, type RunSummary } from './store/runStore';
import { useSuiteStore } from './store/suiteStore';
import { useProjectStore } from '../../shared/store/projectStore';
import { useConfirmStore } from '../../shared/store/confirmStore';
import { useEnvStore } from './store/envStore';
import { CasePicker } from '../../shared/components/CasePicker';
import { EnvironmentSelect } from './components/EnvironmentSelect';
import { CaseEditorDialog, NewCaseDialog } from './components/CaseFlowDialogs';
import { CaseStepsView } from './components/CaseStepsView';
import { RunDetail } from './components/RunDetail';
import { SuitePanel } from './components/suite/SuitePanel';
import { useIsMobile } from '../../shared/hooks/useIsMobile';

const iconBtnStyle = (active = false): CSSProperties => ({
  background: active ? 'var(--bg-elevated)' : 'none',
  border: '1px solid var(--bg-elevated)',
  color: active ? 'var(--accent)' : 'var(--text-secondary)',
  borderRadius: 4,
  padding: '4px 8px',
  fontSize: 12,
  cursor: 'pointer',
  display: 'inline-flex',
  alignItems: 'center',
  gap: 4,
  whiteSpace: 'nowrap',
});

function runStatusColor(status: string) {
  if (status === 'passed') return 'var(--success)';
  if (status === 'failed') return 'var(--error)';
  return 'var(--chart-3)';
}

function RunStatusIcon({ status }: { status: string }) {
  if (status === 'passed') return <Check size={12} strokeWidth={2} style={{ color: runStatusColor(status) }} />;
  if (status === 'failed') return <X size={12} strokeWidth={2} style={{ color: runStatusColor(status) }} />;
  return <AlertTriangle size={12} strokeWidth={2} style={{ color: runStatusColor(status) }} />;
}

export function CasesTab() {
  const { cases, loadingCases, selectedCaseId, runs, selectedRun, executing,
          loadCases, selectCase, execute, loadRunDetail, deleteCase } = useRunStore();
  const { suites, selectedSuiteId, loadSuites, selectSuite } = useSuiteStore();
  const { t } = useTranslation();
  const [viewMode, setViewMode] = useState<'case' | 'suite'>('case');
  const [creatingSuite, setCreatingSuite] = useState(false);
  const [envId, setEnvId] = useState<number | null>(null);
  const [newOpen, setNewOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [showRecords, setShowRecords] = useState(false);
  const [expandedRunId, setExpandedRunId] = useState<number | null>(null);
  const isMobile = useIsMobile();
  const currentProjectId = useProjectStore((s) => s.currentProjectId);
  const currentVersionId = useProjectStore((s) => s.currentVersionId);
  const confirm = useConfirmStore((s) => s.confirm);

  useEffect(() => {
    loadCases();
    loadSuites();
  }, [loadCases, loadSuites, currentProjectId, currentVersionId]);

  // 环境未显式选择时，默认选中已启用的环境
  const envs = useEnvStore((s) => s.envs);
  useEffect(() => {
    if (envId === null && envs.length > 0) {
      const def = envs.find((e) => e.is_default) || envs[0];
      if (def) setEnvId(def.id);
    }
  }, [envs, envId]);

  // 切换用例时回到步骤视图，避免展示上一条用例的执行记录
  useEffect(() => { setShowRecords(false); setExpandedRunId(null); }, [selectedCaseId]);

  const selectedCase = cases.find((c) => c.id === selectedCaseId);

  const runNow = async () => {
    if (!selectedCase) return;
    try {
      await execute(selectedCase.id, envId);
      const st = useRunStore.getState();
      setShowRecords(true);
      setExpandedRunId(st.selectedRun?.id ?? null);
    } catch (e) {
      toast.error(String(e));
    }
  };

  const removeCase = () => {
    if (!selectedCase) return;
    confirm({
      title: t('api.deleteCase'),
      message: t('api.deleteCaseConfirm', { title: selectedCase.title }),
      variant: 'danger',
      onConfirm: () => {
        deleteCase(selectedCase.id).then(() => toast.success(t('common.delete'))).catch((e) => toast.error(String(e)));
      },
    });
  };

  const toggleRun = (run: RunSummary) => {
    if (expandedRunId === run.id) {
      setExpandedRunId(null);
      return;
    }
    setExpandedRunId(run.id);
    if (selectedRun?.id !== run.id) loadRunDetail(run.id);
  };

  const modeBtnStyle = (active: boolean): CSSProperties => ({
    background: active ? 'var(--accent)' : 'transparent',
    color: active ? 'var(--bg-base)' : 'var(--text-secondary)',
    border: 'none',
    borderRadius: 4,
    padding: '3px 8px',
    fontSize: 12,
    fontWeight: active ? 600 : 400,
    cursor: 'pointer',
    display: 'inline-flex',
    alignItems: 'center',
    gap: 4,
  });

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: isMobile ? 'column' : 'row', overflow: 'hidden' }}>
      {/* 左侧边栏：单条用例 / 测试套件 切换与列表 */}
      <aside style={{
        width: isMobile ? '100%' : 330,
        borderRight: isMobile ? 'none' : '1px solid var(--bg-card)',
        borderBottom: isMobile ? '1px solid var(--bg-card)' : 'none',
        display: 'flex', flexDirection: 'column', flexShrink: 0,
        ...(isMobile ? { maxHeight: 280 } : {}),
      }}>
        <div style={{
          padding: '8px 12px', borderBottom: '1px solid var(--bg-card)', fontSize: 13, color: 'var(--text-secondary)',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 6,
        }}>
          <div style={{
            display: 'inline-flex', alignItems: 'center', gap: 2,
            background: 'var(--bg-card)', padding: 2, borderRadius: 6,
          }}>
            <button onClick={() => setViewMode('case')} style={modeBtnStyle(viewMode === 'case')}>
              <FileText size={12} strokeWidth={1.5} />
              <span>{t('api.casesTitle')} ({cases.length})</span>
            </button>
            <button onClick={() => setViewMode('suite')} style={modeBtnStyle(viewMode === 'suite')}>
              <Layers size={12} strokeWidth={1.5} />
              <span>{t('api.tabSuites')} ({suites.length})</span>
            </button>
          </div>
          {viewMode === 'case' ? (
            <button onClick={() => setNewOpen(true)} style={iconBtnStyle()}>
              <Plus size={12} strokeWidth={1.5} /> {t('api.newCase')}
            </button>
          ) : (
            <button onClick={() => { selectSuite(null); setCreatingSuite(true); }} style={iconBtnStyle()}>
              <Plus size={12} strokeWidth={1.5} /> {t('api.newSuite')}
            </button>
          )}
        </div>

        {viewMode === 'case' ? (
          <CasePicker cases={cases} selectedId={selectedCaseId} onSelect={selectCase} loading={loadingCases} emptyLabel={t('api.noCaseHint')} />
        ) : (
          <div style={{ flex: 1, overflowY: 'auto' }}>
            {suites.length === 0 ? (
              <div style={{ padding: 16, fontSize: 12, color: 'var(--text-muted)' }}>
                {t('api.selectOrNewSuite')}
              </div>
            ) : (
              suites.map((s) => (
                <div
                  key={s.id}
                  onClick={() => { setCreatingSuite(false); selectSuite(s.id); }}
                  style={{
                    padding: '8px 12px', cursor: 'pointer',
                    background: selectedSuiteId === s.id ? 'var(--bg-card)' : 'transparent',
                    borderBottom: '1px solid var(--bg-primary)', fontSize: 12,
                  }}
                >
                  <div style={{ color: 'var(--text-primary)', fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {s.name}
                  </div>
                  <div style={{ color: 'var(--text-muted)', fontSize: 11, marginTop: 2 }}>
                    {t('api.caseCount', { count: s.case_ids.length })}
                  </div>
                </div>
              ))
            )}
          </div>
        )}
      </aside>

      {/* 右侧主区域：根据当前模式展示单条用例执行或套件批量执行 */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', minWidth: 0 }}>
        {viewMode === 'case' ? (
          <>
            {/* 单条用例顶部工具栏 */}
            <div style={{
              display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap',
              padding: '8px 16px', borderBottom: '1px solid var(--bg-card)', flexShrink: 0,
            }}>
              <span style={{ fontSize: 13, color: 'var(--text-primary)', fontWeight: 600, flex: 1, minWidth: 120 }}>
                {selectedCase ? selectedCase.title : t('api.selectCase')}
              </span>
              {selectedCase && (
                <>
                  <EnvironmentSelect value={envId} onChange={setEnvId} />
                  <button onClick={runNow} disabled={executing} style={{
                    background: 'var(--accent)', color: 'var(--bg-base)', border: 'none', borderRadius: 4,
                    padding: '4px 12px', cursor: executing ? 'wait' : 'pointer', fontSize: 12, fontWeight: 600,
                    display: 'inline-flex', alignItems: 'center', gap: 4, whiteSpace: 'nowrap',
                  }}>
                    {executing ? t('api.executing') : <><Play size={12} strokeWidth={1.5} /> {t('api.execute')}</>}
                  </button>
                  <button onClick={() => setEditOpen(true)} style={iconBtnStyle()}>
                    <Pencil size={12} strokeWidth={1.5} /> {t('api.editCase')}
                  </button>
                  <button onClick={removeCase} style={{ ...iconBtnStyle(), color: 'var(--error)' }}>
                    <Trash2 size={12} strokeWidth={1.5} /> {t('common.delete')}
                  </button>
                  <button onClick={() => setShowRecords((v) => !v)} style={iconBtnStyle(showRecords)}>
                    <History size={12} strokeWidth={1.5} />
                    {showRecords ? t('api.backToSteps') : t('api.executionRecords')} ({runs.length})
                  </button>
                </>
              )}
            </div>

            <main style={{ flex: 1, overflow: 'auto', minWidth: 0 }}>
              {!selectedCase ? (
                <div style={{ padding: 24, fontSize: 13, color: 'var(--text-muted)' }}>{t('api.selectCase')}</div>
              ) : showRecords ? (
                <div style={{ padding: 16 }}>
                  {runs.length === 0 && (
                    <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{t('api.noCaseRuns')}</div>
                  )}
                  {runs.map((run) => {
                    const expanded = expandedRunId === run.id;
                    return (
                      <div key={run.id} style={{
                        border: '1px solid var(--bg-card)', borderRadius: 6, marginBottom: 8, overflow: 'hidden',
                      }}>
                        <button
                          onClick={() => toggleRun(run)}
                          style={{
                            width: '100%', display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px',
                            background: expanded ? 'var(--bg-card)' : 'var(--bg-primary)', border: 'none',
                            cursor: 'pointer', fontSize: 12, color: 'var(--text-secondary)', textAlign: 'left',
                          }}
                        >
                          {expanded
                            ? <ChevronDown size={12} strokeWidth={1.5} />
                            : <ChevronRight size={12} strokeWidth={1.5} />}
                          <RunStatusIcon status={run.status} />
                          <span style={{ color: 'var(--text-primary)', flex: 1 }}>
                            {run.started_at || `#${run.id}`}
                          </span>
                          <span>{t('api.stepsPassed', { passed: run.passed_steps, total: run.total_steps })}</span>
                          <span>{run.duration_ms}ms</span>
                        </button>
                        {expanded && (
                          <div style={{ borderTop: '1px solid var(--bg-card)', background: 'var(--bg-primary)' }}>
                            {selectedRun?.id === run.id
                              ? <RunDetail run={selectedRun} />
                              : <div style={{ padding: 16, fontSize: 12, color: 'var(--text-muted)' }}>{t('api.loading')}</div>}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              ) : (
                <CaseStepsView caseItem={selectedCase} />
              )}
            </main>
          </>
        ) : (
          <main style={{ flex: 1, overflow: 'hidden', minWidth: 0 }}>
            {(selectedSuiteId != null || creatingSuite) ? (
              <SuitePanel suiteId={selectedSuiteId} onNew={() => setCreatingSuite(false)} />
            ) : (
              <div style={{ padding: 24, fontSize: 13, color: 'var(--text-muted)' }}>
                {t('api.selectOrNewSuite')}
              </div>
            )}
          </main>
        )}
      </div>

      <NewCaseDialog
        open={newOpen}
        onClose={() => setNewOpen(false)}
        onCreated={(id) => {
          loadCases().finally(() => selectCase(id));
        }}
      />
      <CaseEditorDialog
        open={editOpen}
        caseItem={selectedCase ?? null}
        onClose={() => setEditOpen(false)}
        onSaved={() => { loadCases(); }}
      />
    </div>
  );
}
