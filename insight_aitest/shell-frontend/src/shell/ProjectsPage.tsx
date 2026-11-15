import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import {
  ChevronDown,
  ChevronRight,
  Circle,
  CircleDot,
  Code2,
  Globe,
  Layers,
  PlugZap,
  X,
} from 'lucide-react';
import { EnvManagerDialog } from '../modules/ui/components/automation/EnvManagerDialog';
import { useAutomationStore, type UIEnv } from '../modules/ui/store/automationStore';
import { useConfirmStore } from '../shared/store/confirmStore';
import { useProjectStore } from '../shared/store/projectStore';

interface Project {
  id: number;
  name: string;
  description: string;
  color: string;
  version_count: number;
  env_count?: number;
  created_at: string;
}

interface Version {
  id: number;
  project_id: number;
  name: string;
  description: string;
  is_active: boolean;
  created_at: string;
}

const BASE = '/api/platform';
const ENV_BASE = '/api/modules/ui/automation/envs';

export function ProjectsPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [subTab, setSubTab] = useState<'envs' | 'versions'>('envs');
  const [versions, setVersions] = useState<Version[]>([]);
  const [projectEnvs, setProjectEnvs] = useState<UIEnv[]>([]);
  const [testingEnvId, setTestingEnvId] = useState<number | null>(null);

  const [editing, setEditing] = useState<{ id: number | null; name: string; description: string; color: string } | null>(null);
  const [editingVer, setEditingVer] = useState<{ projectId: number; id: number | null; name: string; description: string } | null>(null);

  // 环境管理弹窗状态
  const [envModalState, setEnvModalState] = useState<{
    open: boolean;
    projectId: number | null;
    projectName: string;
    initialTab: 'envs' | 'script';
    initialEditEnv: UIEnv | null;
  }>({
    open: false,
    projectId: null,
    projectName: '',
    initialTab: 'envs',
    initialEditEnv: null,
  });

  const { confirm } = useConfirmStore();
  const { testEnv, deleteEnv } = useAutomationStore();

  const loadProjects = async () => {
    const r = await fetch(`${BASE}/projects`);
    if (r.ok) setProjects(await r.json());
  };

  useEffect(() => {
    fetch(`${BASE}/projects`)
      .then((r) => r.json())
      .then(setProjects)
      .catch(() => { /* 列表加载失败保持空态 */ });
  }, []);

  const loadVersions = async (projectId: number) => {
    const r = await fetch(`${BASE}/projects/${projectId}/versions`);
    if (r.ok) setVersions(await r.json());
  };

  const loadProjectEnvs = async (projectId: number) => {
    const r = await fetch(`${ENV_BASE}?project_id=${projectId}`);
    if (r.ok) setProjectEnvs(await r.json());
  };

  const saveProject = async () => {
    if (!editing) return;
    const body = { name: editing.name, description: editing.description, color: editing.color };
    if (editing.id) {
      await fetch(`${BASE}/projects/${editing.id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    } else {
      await fetch(`${BASE}/projects`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    }
    setEditing(null);
    await loadProjects();
    useProjectStore.getState().loadProjects();
  };

  const deleteProject = (p: Project) => {
    confirm({
      title: '确认删除',
      message: `确定要删除项目「${p.name}」吗？\n\n项目下的版本与环境配置将被一并删除。\n如果项目下有文档或用例，删除将被阻止。`,
      variant: 'danger',
      onConfirm: async () => {
        const r = await fetch(`${BASE}/projects/${p.id}`, { method: 'DELETE' });
        if (r.ok) {
          await loadProjects();
          useProjectStore.getState().loadProjects();
          setExpandedId(null);
        } else {
          const err = await r.json();
          toast.error(err.detail || '删除失败');
        }
      },
    });
  };

  const saveVersion = async () => {
    if (!editingVer) return;
    const body = { name: editingVer.name, description: editingVer.description };
    if (editingVer.id) {
      await fetch(`${BASE}/versions/${editingVer.id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    } else {
      await fetch(`${BASE}/projects/${editingVer.projectId}/versions`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    }
    setEditingVer(null);
    if (expandedId) await loadVersions(expandedId);
    await loadProjects();
    useProjectStore.getState().loadProjects();
  };

  const deleteVersion = (v: Version) => {
    confirm({
      title: '确认删除',
      message: `确定要删除版本「${v.name}」吗？`,
      variant: 'danger',
      onConfirm: async () => {
        const r = await fetch(`${BASE}/versions/${v.id}`, { method: 'DELETE' });
        if (r.ok) {
          if (expandedId) await loadVersions(expandedId);
          await loadProjects();
          useProjectStore.getState().loadProjects();
        }
      },
    });
  };

  const toggleExpand = (projectId: number) => {
    if (expandedId === projectId) {
      setExpandedId(null);
    } else {
      setExpandedId(projectId);
      loadVersions(projectId);
      loadProjectEnvs(projectId);
    }
  };

  const handleTestEnv = async (env: UIEnv) => {
    setTestingEnvId(env.id);
    try {
      const res = await testEnv(env.id);
      if (res.ok) toast.success(res.message || '连接成功');
      else toast.error(res.message || '连接失败');
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setTestingEnvId(null);
    }
  };

  const handleDeleteEnv = (env: UIEnv, projId: number) => {
    confirm({
      title: '确认删除环境',
      message: `确定要删除环境「${env.name || env.base_url}」吗？`,
      variant: 'danger',
      onConfirm: async () => {
        try {
          await deleteEnv(env.id);
          toast.success('已删除');
          await loadProjectEnvs(projId);
          await loadProjects();
        } catch (e) {
          toast.error((e as Error).message);
        }
      },
    });
  };

  return (
    <div style={{ padding: 24, color: 'var(--text-primary)', maxWidth: 860, margin: '0 auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <div>
          <h2 style={{ fontSize: 18, margin: 0 }}>项目管理</h2>
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>
            维护项目基础信息、执行环境地址配置与发布版本
          </div>
        </div>
        <button
          onClick={() => setEditing({ id: null, name: '', description: '', color: 'var(--accent)' })}
          style={primaryBtn}
        >
          + 新建项目
        </button>
      </div>

      {projects.length === 0 && (
        <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>
          还没有项目。创建一个开始分类管理你的测试资产。
        </div>
      )}

      {projects.map((p) => {
        const isExpanded = expandedId === p.id;
        return (
          <div
            key={p.id}
            style={{
              marginBottom: 12,
              border: `1px solid ${isExpanded ? 'var(--border)' : 'var(--bg-card)'}`,
              borderRadius: 8,
              background: 'var(--bg-base)',
              overflow: 'hidden',
              boxShadow: isExpanded ? '0 4px 12px rgba(0,0,0,0.06)' : 'none',
              transition: 'all 0.2s ease',
            }}
          >
            <div
              style={{
                padding: '12px 16px',
                display: 'flex',
                alignItems: 'center',
                gap: 12,
                cursor: 'pointer',
                background: isExpanded ? 'var(--bg-card)' : 'transparent',
              }}
              onClick={() => toggleExpand(p.id)}
            >
              <span style={{ width: 8, height: 8, borderRadius: '50%', background: p.color, flexShrink: 0 }} />
              <span style={{ flex: 1, fontWeight: 600, fontSize: 14 }}>{p.name}</span>

              <div style={{ display: 'flex', alignItems: 'center', gap: 12, fontSize: 12, color: 'var(--text-muted)' }}>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                  <Globe size={13} style={{ opacity: 0.8 }} />
                  {p.env_count ?? 0} 个环境
                </span>
                <span>·</span>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                  <Layers size={13} style={{ opacity: 0.8 }} />
                  {p.version_count} 个版本
                </span>
              </div>

              <button
                onClick={(e) => {
                  e.stopPropagation();
                  setEditing({ id: p.id, name: p.name, description: p.description, color: p.color });
                }}
                style={miniBtn}
              >
                编辑
              </button>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  deleteProject(p);
                }}
                style={{ ...miniBtn, color: 'var(--error)' }}
              >
                删除
              </button>
              <span style={{ color: 'var(--text-muted)', display: 'inline-flex', alignItems: 'center' }}>
                {isExpanded ? <ChevronDown size={14} strokeWidth={1.5} /> : <ChevronRight size={14} strokeWidth={1.5} />}
              </span>
            </div>

            {p.description && !isExpanded && (
              <div style={{ padding: '0 36px 8px', fontSize: 12, color: 'var(--text-muted)' }}>
                {p.description}
              </div>
            )}

            {isExpanded && (
              <div style={{ borderTop: '1px solid var(--border)', background: 'var(--bg-base)' }}>
                {/* 展开子 Tab 切换头 */}
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 16,
                    padding: '8px 20px',
                    borderBottom: '1px solid var(--border)',
                    background: 'var(--bg-card)',
                  }}
                >
                  <button
                    onClick={() => setSubTab('envs')}
                    style={{
                      padding: '4px 8px',
                      borderRadius: 4,
                      border: 'none',
                      background: subTab === 'envs' ? 'var(--bg-base)' : 'transparent',
                      color: subTab === 'envs' ? 'var(--accent)' : 'var(--text-muted)',
                      fontWeight: subTab === 'envs' ? 600 : 400,
                      fontSize: 12,
                      cursor: 'pointer',
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: 6,
                    }}
                  >
                    <Globe size={13} /> 环境配置 ({projectEnvs.length})
                  </button>

                  <button
                    onClick={() => setSubTab('versions')}
                    style={{
                      padding: '4px 8px',
                      borderRadius: 4,
                      border: 'none',
                      background: subTab === 'versions' ? 'var(--bg-base)' : 'transparent',
                      color: subTab === 'versions' ? 'var(--accent)' : 'var(--text-muted)',
                      fontWeight: subTab === 'versions' ? 600 : 400,
                      fontSize: 12,
                      cursor: 'pointer',
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: 6,
                    }}
                  >
                    <Layers size={13} /> 版本管理 ({versions.length})
                  </button>
                </div>

                {/* Tab 1: 环境配置 */}
                {subTab === 'envs' && (
                  <div style={{ padding: '12px 20px 16px' }}>
                    {projectEnvs.length === 0 ? (
                      <div style={{ padding: '16px 0', color: 'var(--text-muted)', fontSize: 12 }}>
                        暂未配置任何测试环境，请点击下方「新建环境」添加被测系统地址。
                      </div>
                    ) : (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 12 }}>
                        {projectEnvs.map((env) => (
                          <div
                            key={env.id}
                            style={{
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'space-between',
                              padding: '8px 12px',
                              borderRadius: 6,
                              border: '1px solid var(--border)',
                              background: 'var(--bg-card)',
                              fontSize: 12,
                            }}
                          >
                            <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
                              <span
                                style={{
                                  fontSize: 10,
                                  padding: '1px 6px',
                                  borderRadius: 4,
                                  border: '1px solid var(--border)',
                                  background: env.is_default ? 'rgba(16, 185, 129, 0.1)' : 'var(--bg-base)',
                                  color: env.is_default ? '#10b981' : 'var(--text-muted)',
                                  fontWeight: env.is_default ? 600 : 400,
                                  flexShrink: 0,
                                }}
                              >
                                {env.is_default ? '默认' : '环境'}
                              </span>
                              <span style={{ fontWeight: 600, color: 'var(--text-primary)', whiteSpace: 'nowrap' }}>
                                {env.name || '未命名'}
                              </span>
                              <span
                                style={{
                                  color: 'var(--accent)',
                                  fontFamily: 'monospace',
                                  overflow: 'hidden',
                                  textOverflow: 'ellipsis',
                                  whiteSpace: 'nowrap',
                                }}
                                title={env.base_url}
                              >
                                {env.base_url}
                              </span>
                              {env.username && (
                                <span style={{ color: 'var(--text-muted)', fontSize: 11, whiteSpace: 'nowrap' }}>
                                  ({env.username})
                                </span>
                              )}
                            </div>

                            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
                              <button
                                onClick={() => handleTestEnv(env)}
                                disabled={testingEnvId === env.id}
                                style={{
                                  ...miniBtn,
                                  display: 'inline-flex',
                                  alignItems: 'center',
                                  gap: 4,
                                }}
                              >
                                <PlugZap size={11} /> {testingEnvId === env.id ? '测试中...' : '测试连接'}
                              </button>
                              <button
                                onClick={() =>
                                  setEnvModalState({
                                    open: true,
                                    projectId: p.id,
                                    projectName: p.name,
                                    initialTab: 'envs',
                                    initialEditEnv: env,
                                  })
                                }
                                style={miniBtn}
                              >
                                编辑
                              </button>
                              <button
                                onClick={() => handleDeleteEnv(env, p.id)}
                                style={{ ...miniBtn, color: 'var(--error)' }}
                              >
                                删除
                              </button>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}

                    <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 8 }}>
                      <button
                        onClick={() =>
                          setEnvModalState({
                            open: true,
                            projectId: p.id,
                            projectName: p.name,
                            initialTab: 'envs',
                            initialEditEnv: null,
                          })
                        }
                        style={{ ...primaryBtn, fontSize: 11 }}
                      >
                        + 新建环境
                      </button>

                      <button
                        onClick={() =>
                          setEnvModalState({
                            open: true,
                            projectId: p.id,
                            projectName: p.name,
                            initialTab: 'script',
                            initialEditEnv: null,
                          })
                        }
                        style={{ ...secondaryBtn, fontSize: 11, display: 'inline-flex', alignItems: 'center', gap: 5 }}
                      >
                        <Code2 size={12} /> 项目前置鉴权脚本
                      </button>
                    </div>
                  </div>
                )}

                {/* Tab 2: 版本管理 */}
                {subTab === 'versions' && (
                  <div style={{ padding: '12px 20px 16px' }}>
                    {versions.length === 0 ? (
                      <div style={{ padding: '16px 0', color: 'var(--text-muted)', fontSize: 12 }}>
                        暂未创建任何发布版本。
                      </div>
                    ) : (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 12 }}>
                        {versions.map((v) => (
                          <div
                            key={v.id}
                            style={{
                              display: 'flex',
                              alignItems: 'center',
                              gap: 8,
                              padding: '6px 8px',
                              borderRadius: 4,
                              background: 'var(--bg-card)',
                              border: '1px solid var(--border)',
                              fontSize: 12,
                            }}
                          >
                            <span
                              style={{
                                fontSize: 12,
                                color: v.is_active ? '#10b981' : 'var(--text-muted)',
                                display: 'inline-flex',
                                alignItems: 'center',
                              }}
                            >
                              {v.is_active ? <CircleDot size={12} strokeWidth={1.5} /> : <Circle size={12} strokeWidth={1.5} />}
                            </span>
                            <span style={{ fontSize: 13, flex: 1, fontWeight: 500 }}>{v.name}</span>
                            {v.description && (
                              <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{v.description}</span>
                            )}
                            <button
                              onClick={() =>
                                setEditingVer({
                                  projectId: p.id,
                                  id: v.id,
                                  name: v.name,
                                  description: v.description,
                                })
                              }
                              style={miniBtn}
                            >
                              编辑
                            </button>
                            <button onClick={() => deleteVersion(v)} style={{ ...miniBtn, color: 'var(--error)' }}>
                              删除
                            </button>
                          </div>
                        ))}
                      </div>
                    )}

                    <button
                      onClick={() => setEditingVer({ projectId: p.id, id: null, name: '', description: '' })}
                      style={{ ...primaryBtn, fontSize: 11 }}
                    >
                      + 新建版本
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}

      {/* 项目编辑弹窗 */}
      {editing && (
        <Modal title={editing.id ? '编辑项目' : '新建项目'} onClose={() => setEditing(null)}>
          <Field label="名称">
            <input style={inputStyle} value={editing.name} onChange={(e) => setEditing({ ...editing, name: e.target.value })} />
          </Field>
          <Field label="描述">
            <input style={inputStyle} value={editing.description} onChange={(e) => setEditing({ ...editing, description: e.target.value })} />
          </Field>
          <Field label="标识色">
            <input type="color" value={editing.color} onChange={(e) => setEditing({ ...editing, color: e.target.value })} style={{ width: 40, height: 28, border: 'none', background: 'none' }} />
          </Field>
          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 16 }}>
            <button onClick={() => setEditing(null)} style={secondaryBtn}>取消</button>
            <button onClick={saveProject} style={primaryBtn}>保存</button>
          </div>
        </Modal>
      )}

      {/* 版本编辑弹窗 */}
      {editingVer && (
        <Modal title={editingVer.id ? '编辑版本' : '新建版本'} onClose={() => setEditingVer(null)}>
          <Field label="版本名">
            <input style={inputStyle} value={editingVer.name} onChange={(e) => setEditingVer({ ...editingVer, name: e.target.value })} placeholder="如 v2.0" />
          </Field>
          <Field label="描述">
            <input style={inputStyle} value={editingVer.description} onChange={(e) => setEditingVer({ ...editingVer, description: e.target.value })} />
          </Field>
          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 16 }}>
            <button onClick={() => setEditingVer(null)} style={secondaryBtn}>取消</button>
            <button onClick={saveVersion} style={primaryBtn}>保存</button>
          </div>
        </Modal>
      )}

      {/* 环境管理弹窗 */}
      <EnvManagerDialog
        open={envModalState.open}
        targetProjectId={envModalState.projectId}
        projectName={envModalState.projectName}
        initialTab={envModalState.initialTab}
        initialEditEnv={envModalState.initialEditEnv}
        onClose={() => setEnvModalState((prev) => ({ ...prev, open: false }))}
        onChanged={async () => {
          if (envModalState.projectId) {
            await loadProjectEnvs(envModalState.projectId);
          }
          await loadProjects();
        }}
      />
    </div>
  );
}

function Modal({ title, children, onClose }: { title: string; children: React.ReactNode; onClose: () => void }) {
  return (
    <div onClick={onClose} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 1000, display: 'flex', alignItems: 'flex-start', justifyContent: 'center', paddingTop: 60 }}>
      <div onClick={(e) => e.stopPropagation()} style={{ width: 'min(480px, 90vw)', background: 'var(--bg-base)', border: '1px solid var(--bg-elevated)', borderRadius: 10, padding: 20 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <strong style={{ fontSize: 14 }}>{title}</strong>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer', display: 'inline-flex', alignItems: 'center', padding: 0 }}>
            <X size={16} strokeWidth={1.5} />
          </button>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>{children}</div>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label style={{ display: 'block', fontSize: 11, color: 'var(--text-secondary)', marginBottom: 4 }}>{label}</label>
      {children}
    </div>
  );
}

const inputStyle: React.CSSProperties = { width: '100%', background: 'var(--bg-card)', border: '1px solid var(--bg-elevated)', borderRadius: 4, color: 'var(--text-primary)', padding: '6px 8px', fontSize: 13 };
const primaryBtn: React.CSSProperties = { background: 'var(--accent)', color: 'var(--bg-base)', border: 'none', borderRadius: 4, padding: '4px 12px', cursor: 'pointer', fontSize: 12, fontWeight: 600 };
const secondaryBtn: React.CSSProperties = { background: 'none', border: '1px solid var(--bg-elevated)', color: 'var(--text-secondary)', borderRadius: 4, padding: '4px 12px', cursor: 'pointer', fontSize: 12 };
const miniBtn: React.CSSProperties = { background: 'none', border: '1px solid var(--bg-elevated)', color: 'var(--text-secondary)', borderRadius: 3, padding: '2px 8px', cursor: 'pointer', fontSize: 11 };
