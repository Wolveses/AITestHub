import { useEffect, useState } from 'react';
import { Download, Play, RefreshCw, Search, Smartphone, Sparkles, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { useProjectStore } from '../../shared/store/projectStore';
import { Btn, StatusBadge, inputStyle } from './components/common';
import { CategoryTree } from './components/CategoryTree';
import { ImportCasesDialog } from './components/ImportCasesDialog';
import { GenerateSessionModal } from './components/GenerateSessionModal';
import { CaseDetailDrawer } from './components/CaseDetailDrawer';
import { DevicePanel } from './components/DevicePanel';
import { AppManagerPanel } from './components/AppManagerPanel';
import { useMobileStore, type MobileCase } from './store/mobileStore';

type MainTab = 'cases' | 'infra';

export function MobileApp() {
  const { projects, currentProjectId, loadProjects } = useProjectStore();
  const {
    projectId,
    setProjectId,
    cases,
    total,
    loading,
    statusFilter,
    categoryFilter,
    keyword,
    setStatusFilter,
    setCategoryFilter,
    setKeyword,
    loadCases,
    loadApps,
    loadDevices,
    deleteCase,
  } = useMobileStore();

  const [tab, setTab] = useState<MainTab>('cases');
  const [importOpen, setImportOpen] = useState(false);
  const [drawerCase, setDrawerCase] = useState<MobileCase | null>(null);
  const [genCase, setGenCase] = useState<MobileCase | null>(null);

  useEffect(() => {
    void loadProjects();
  }, [loadProjects]);

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

  const activeDrawerCase = drawerCase
    ? cases.find((c) => c.id === drawerCase.id) ?? drawerCase
    : null;

  const handleDelete = async (c: MobileCase) => {
    try {
      await deleteCase(c.id);
      if (drawerCase?.id === c.id) setDrawerCase(null);
      toast.success(`已删除用例「${c.title}」`);
    } catch (e) {
      toast.error(`删除失败: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', padding: 20, gap: 16 }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <Smartphone size={20} style={{ color: 'var(--accent)' }} />
          <div>
            <h1 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: 'var(--text-primary)' }}>
              移动 App 自动化
            </h1>
            <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
              平台托管手机池 · Agent MCP 探索生成 · 服务端 Pytest + Appium 回归执行
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <select
            value={projectId ?? ''}
            onChange={(e) => setProjectId(e.target.value ? Number(e.target.value) : null)}
            style={{ ...inputStyle, width: 180 }}
          >
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>

          <div
            style={{
              display: 'inline-flex',
              padding: 3,
              borderRadius: 8,
              background: 'var(--bg-card)',
              border: '1px solid var(--border)',
              gap: 4,
            }}
          >
            <Btn variant={tab === 'cases' ? 'primary' : 'ghost'} onClick={() => setTab('cases')} style={{ fontSize: 12, padding: '5px 12px' }}>
              自动化用例
            </Btn>
            <Btn variant={tab === 'infra' ? 'primary' : 'ghost'} onClick={() => setTab('infra')} style={{ fontSize: 12, padding: '5px 12px' }}>
              设备与 App
            </Btn>
          </div>
        </div>
      </div>

      {tab === 'cases' ? (
        <div style={{ display: 'flex', gap: 14, flex: 1, minHeight: 0 }}>
          <CategoryTree
            cases={cases}
            selected={categoryFilter || ''}
            onSelect={(path) => setCategoryFilter(path || null)}
          />

          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 12, minWidth: 0 }}>
            {/* Toolbar */}
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <div style={{ position: 'relative', flex: 1, minWidth: 200 }}>
                <Search
                  size={14}
                  style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }}
                />
                <input
                  style={{ ...inputStyle, paddingLeft: 30 }}
                  placeholder="搜索用例标题..."
                  value={keyword}
                  onChange={(e) => setKeyword(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') void loadCases();
                  }}
                />
              </div>

              <select
                style={{ ...inputStyle, width: 140 }}
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
              >
                <option value="">全部状态</option>
                <option value="not_implemented">未实现</option>
                <option value="generating">生成中</option>
                <option value="implemented">已实现</option>
                <option value="fixing">修复中</option>
                <option value="running">执行中</option>
              </select>

              <Btn variant="ghost" onClick={() => void loadCases()} disabled={loading}>
                <RefreshCw size={13} /> 刷新 ({total})
              </Btn>

              <Btn variant="primary" onClick={() => setImportOpen(true)} disabled={projectId === null}>
                <Download size={13} /> 从测试设计导入
              </Btn>
            </div>

            {/* Case List */}
            <div
              style={{
                flex: 1,
                overflowY: 'auto',
                background: 'var(--bg-card)',
                border: '1px solid var(--border)',
                borderRadius: 10,
              }}
            >
              {loading && cases.length === 0 ? (
                <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
                  加载中...
                </div>
              ) : cases.length === 0 ? (
                <div style={{ padding: 48, textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
                  暂无移动 App 自动化用例，点击右上角「从测试设计导入」开始接入。
                </div>
              ) : (
                cases.map((c) => (
                  <div
                    key={c.id}
                    onClick={() => setDrawerCase(c)}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      gap: 12,
                      padding: '12px 16px',
                      borderBottom: '1px solid var(--border)',
                      cursor: 'pointer',
                    }}
                  >
                    <div style={{ minWidth: 0, flex: 1 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)' }}>
                          {c.title}
                        </span>
                        <StatusBadge status={c.status} />
                        <span
                          style={{
                            fontSize: 11,
                            padding: '1px 6px',
                            borderRadius: 4,
                            border: '1px solid var(--border)',
                            color: 'var(--text-muted)',
                          }}
                        >
                          {c.platform}
                        </span>
                        {c.script_version > 0 && (
                          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>v{c.script_version}</span>
                        )}
                      </div>
                      <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 3 }}>
                        {c.category_path || '未分类'} · {c.steps?.length || 0} 步
                        {c.last_error_message ? ` · 最近错误: ${c.last_error_message.slice(0, 60)}` : ''}
                      </div>
                    </div>

                    <div
                      style={{ display: 'flex', alignItems: 'center', gap: 6 }}
                      onClick={(e) => e.stopPropagation()}
                    >
                      {c.platform === 'android' && (
                        <Btn
                          variant="ghost"
                          onClick={() => setGenCase(c)}
                          style={{ fontSize: 12, padding: '5px 10px' }}
                        >
                          <Sparkles size={12} /> {c.has_script ? '修复' : 'Agent 生成'}
                        </Btn>
                      )}
                      <Btn
                        variant="ghost"
                        onClick={() => setDrawerCase(c)}
                        style={{ fontSize: 12, padding: '5px 10px' }}
                      >
                        <Play size={12} /> 详情/运行
                      </Btn>
                      <Btn
                        variant="danger"
                        onClick={() => void handleDelete(c)}
                        style={{ padding: '5px 8px' }}
                      >
                        <Trash2 size={12} />
                      </Btn>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      ) : (
        <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 24 }}>
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
        open={!!genCase}
        targetCase={genCase}
        onClose={() => setGenCase(null)}
      />

      <CaseDetailDrawer
        targetCase={activeDrawerCase}
        onClose={() => setDrawerCase(null)}
        onOpenGenerate={(c) => setGenCase(c)}
      />
    </div>
  );
}
