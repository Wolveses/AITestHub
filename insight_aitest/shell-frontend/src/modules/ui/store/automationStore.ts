import { create } from 'zustand';

export interface AutomationCase {
  id: number;
  project_id: number;
  kb_document_id: number;
  source_case_id: string;
  source_workspace_id: string;
  title: string;
  precondition: string;
  steps: string[];
  expected: string;
  category_path: string;
  kb_folder_id: number | null;
  /** 端：frontend（根路径）/ backend（base_url + /manage） */
  site: string;
  /** 复用的流程资产 id（无则为独立脚本） */
  flow_id: number | null;
  /** 生成时所用流程版本 */
  flow_version: number | null;
  /** 流程标题（列表 chip 展示） */
  flow_title?: string;
  /** 流程状态（active/archived） */
  flow_status?: string | null;
  /** 本用例参数值 */
  params: Record<string, string | number | boolean | null>;
  /** 流程参数结构 */
  params_schema: ParamSchemaItem[];
  params_updated_at: string | null;
  status: string;
  script_version: number;
  has_script: boolean;
  last_error_category: string | null;
  last_error_message: string | null;
  last_run_id: number | null;
  last_generated_at: string | null;
  progress: { phase: string; message: string; updated_at: string } | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface ParamSchemaItem {
  name: string;
  label?: string;
  type?: 'str' | 'int' | 'bool' | 'select';
  required?: boolean;
  default?: string | number | boolean | null;
  example?: string;
  desc?: string;
  unique?: boolean;
  options?: string[];
}

export interface UiFlow {
  id: number;
  project_id: number;
  folder_id: number;
  flow_key: string;
  title: string;
  route: string;
  keywords: string[];
  params_schema: ParamSchemaItem[];
  module: string;
  script_rel_path: string;
  version: number;
  status: string;
  case_count: number;
  updated_at: string | null;
  created_at: string | null;
  source?: string;
  cases?: {
    id: number;
    title: string;
    status: string;
    script_version: number;
    flow_version: number | null;
    flow_outdated: boolean;
  }[];
}

export interface ImportableCase {
  document_id: number;
  title: string;
  case_id: string;
  workspace_id: string;
  category_path: string;
  status: string;
  priority: string;
  step_count: number;
  folder_id: number | null;
  imported: boolean;
  /** 后端按关键字词典给出的端推断，导入确认页初始归属 */
  suggested_site: string;
}

export interface ImportablePage {
  items: ImportableCase[];
  total: number;
  page: number;
  page_size: number;
  /** 当前搜索条件下全部用例数（不受目录过滤影响） */
  all_total: number;
  /** 当前搜索条件下的目录聚合计数，供左侧目录树 */
  folders: { path: string; count: number }[];
}

export interface UIEnv {
  id: number;
  project_id: number;
  name: string;
  base_url: string;
  username: string;
  password_set: boolean;
  is_default: boolean;
  has_storage_state: boolean;
}

export interface ScriptRun {
  id: number;
  case_id: number;
  case_title: string;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number;
  base_url_used: string;
  error: string | null;
  env_id: number | null;
  script_version: number | null;
  artifacts_rel_path: string;
  trace_rel_path: string;
}

export interface GenerationRecord {
  id: number;
  kind: string;
  attempt: number;
  status: string;
  error_category: string | null;
  error_message: string | null;
  tool_calls: number;
  model: string;
  started_at: string | null;
  finished_at: string | null;
}

interface AutomationState {
  cases: AutomationCase[];
  total: number;
  loading: boolean;
  projectId: number | null;
  statusFilter: string;
  categoryFilter: string | null;
  keyword: string;
  envs: UIEnv[];
  flows: UiFlow[];
  flowFilter: number | null;
  setProjectId: (id: number | null) => void;
  setStatusFilter: (s: string) => void;
  setCategoryFilter: (c: string | null) => void;
  setKeyword: (k: string) => void;
  setFlowFilter: (id: number | null) => void;
  loadCases: () => Promise<void>;
  loadEnvs: () => Promise<void>;
  loadFlows: () => Promise<void>;
  importable: (opts?: {
    search?: string;
    categoryPath?: string | null;
    page?: number;
    pageSize?: number;
  }) => Promise<ImportablePage>;
  importCases: (
    documentIds: number[],
    siteMap?: Record<number, string>,
  ) => Promise<{ created: number; skipped: number; failed: unknown[] }>;
  generate: (
    caseId: number,
    opts?: { reuseFlowId?: number; forceNewFlow?: boolean },
  ) => Promise<void>;
  fix: (caseId: number) => Promise<void>;
  run: (caseId: number) => Promise<void>;
  getCase: (caseId: number) => Promise<AutomationCase>;
  updateCase: (caseId: number, data: Partial<AutomationCase>) => Promise<AutomationCase>;
  deleteCase: (caseId: number) => Promise<void>;
  getScript: (caseId: number) => Promise<{
    content: string;
    version: number;
    pages: { name: string; path?: string; content: string }[];
  }>;
  listRuns: (caseId: number) => Promise<ScriptRun[]>;
  listGenerations: (caseId: number) => Promise<GenerationRecord[]>;
  getParams: (caseId: number) => Promise<{
    flow_id: number | null;
    flow_version: number | null;
    values: Record<string, string | number | boolean | null>;
    schema: ParamSchemaItem[];
    updated_at: string | null;
  }>;
  saveParams: (
    caseId: number,
    values: Record<string, string | number | boolean | null>,
  ) => Promise<AutomationCase>;
  saveEnv: (data: Record<string, unknown>, envId?: number) => Promise<UIEnv>;
  deleteEnv: (envId: number) => Promise<void>;
  testEnv: (envId: number) => Promise<{ ok: boolean; message: string }>;
}

const BASE = '/api/modules/ui/automation';
const LS_PROJECT = 'insight.uiAutomationProjectId';

function readStoredProjectId(): number | null {
  const raw = localStorage.getItem(LS_PROJECT);
  if (!raw) return null;
  const n = Number(raw);
  return Number.isFinite(n) ? n : null;
}

async function parseError(r: Response): Promise<string> {
  try {
    const data = await r.json();
    return data?.detail || data?.message || `HTTP ${r.status}`;
  } catch {
    return `HTTP ${r.status}`;
  }
}

export const useAutomationStore = create<AutomationState>((set, get) => ({
  cases: [],
  total: 0,
  loading: false,
  projectId: readStoredProjectId(),
  statusFilter: '',
  categoryFilter: null,
  keyword: '',
  envs: [],
  flows: [],
  flowFilter: null,

  setProjectId: (id) => {
    if (id === null) localStorage.removeItem(LS_PROJECT);
    else localStorage.setItem(LS_PROJECT, String(id));
    set({ projectId: id, categoryFilter: null, flowFilter: null });
  },
  setStatusFilter: (s) => set({ statusFilter: s }),
  setCategoryFilter: (c) => set({ categoryFilter: c }),
  setKeyword: (k) => set({ keyword: k }),
  setFlowFilter: (id) => set({ flowFilter: id }),

  loadCases: async () => {
    const { projectId, statusFilter, categoryFilter, keyword, flowFilter } = get();
    if (projectId === null) {
      set({ cases: [], total: 0 });
      return;
    }
    set({ loading: true });
    try {
      const q = new URLSearchParams({ project_id: String(projectId), page_size: '200' });
      if (statusFilter) q.set('status', statusFilter);
      if (categoryFilter) q.set('category_path', categoryFilter);
      if (keyword.trim()) q.set('keyword', keyword.trim());
      if (flowFilter !== null) q.set('flow_id', String(flowFilter));
      const r = await fetch(`${BASE}/cases?${q.toString()}`);
      if (!r.ok) throw new Error(await parseError(r));
      const data = await r.json();
      set({ cases: data.items || [], total: data.total || 0 });
    } finally {
      set({ loading: false });
    }
  },

  loadEnvs: async () => {
    const projectId = get().projectId;
    if (projectId === null) {
      set({ envs: [] });
      return;
    }
    const r = await fetch(`${BASE}/envs?project_id=${projectId}`);
    if (r.ok) set({ envs: await r.json() });
  },

  loadFlows: async () => {
    const projectId = get().projectId;
    if (projectId === null) {
      set({ flows: [] });
      return;
    }
    const r = await fetch(`${BASE}/flows?project_id=${projectId}`);
    if (!r.ok) return;
    const data = await r.json();
    set({ flows: data.items || [] });
  },

  importable: async (opts) => {
    const projectId = get().projectId;
    const empty: ImportablePage = {
      items: [],
      total: 0,
      page: 1,
      page_size: opts?.pageSize ?? 200,
      all_total: 0,
      folders: [],
    };
    if (projectId === null) return empty;
    const q = new URLSearchParams({
      project_id: String(projectId),
      page: String(opts?.page ?? 1),
      page_size: String(opts?.pageSize ?? 200),
    });
    if (opts?.search?.trim()) q.set('search', opts.search.trim());
    if (opts?.categoryPath) q.set('category_path', opts.categoryPath);
    const r = await fetch(`${BASE}/cases/importable?${q.toString()}`);
    if (!r.ok) throw new Error(await parseError(r));
    return await r.json();
  },

  importCases: async (documentIds, siteMap) => {
    const projectId = get().projectId;
    const r = await fetch(`${BASE}/cases/import`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project_id: projectId, document_ids: documentIds, site_map: siteMap }),
    });
    if (!r.ok) throw new Error(await parseError(r));
    await get().loadCases();
    return await r.json();
  },

  generate: async (caseId, opts) => {
    const r = await fetch(`${BASE}/cases/${caseId}/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        reuse_flow_id: opts?.reuseFlowId ?? null,
        force_new_flow: opts?.forceNewFlow ?? false,
      }),
    });
    if (!r.ok) throw new Error(await parseError(r));
    await get().loadCases();
  },

  fix: async (caseId) => {
    const r = await fetch(`${BASE}/cases/${caseId}/fix`, { method: 'POST' });
    if (!r.ok) throw new Error(await parseError(r));
    await get().loadCases();
  },

  run: async (caseId) => {
    const r = await fetch(`${BASE}/cases/${caseId}/run`, { method: 'POST' });
    if (!r.ok) throw new Error(await parseError(r));
    await get().loadCases();
  },

  getCase: async (caseId) => {
    const r = await fetch(`${BASE}/cases/${caseId}`);
    if (!r.ok) throw new Error(await parseError(r));
    return await r.json();
  },

  updateCase: async (caseId, data) => {
    const r = await fetch(`${BASE}/cases/${caseId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!r.ok) throw new Error(await parseError(r));
    const updated = await r.json();
    set({ cases: get().cases.map((c) => (c.id === caseId ? updated : c)) });
    return updated;
  },

  deleteCase: async (caseId) => {
    const r = await fetch(`${BASE}/cases/${caseId}`, { method: 'DELETE' });
    if (!r.ok) throw new Error(await parseError(r));
    await get().loadCases();
  },

  getScript: async (caseId) => {
    const r = await fetch(`${BASE}/cases/${caseId}/script`);
    if (!r.ok) throw new Error(await parseError(r));
    return await r.json();
  },

  listRuns: async (caseId) => {
    const r = await fetch(`${BASE}/cases/${caseId}/runs`);
    if (!r.ok) throw new Error(await parseError(r));
    return await r.json();
  },

  listGenerations: async (caseId) => {
    const r = await fetch(`${BASE}/cases/${caseId}/generations`);
    if (!r.ok) throw new Error(await parseError(r));
    return await r.json();
  },

  getParams: async (caseId) => {
    const r = await fetch(`${BASE}/cases/${caseId}/params`);
    if (!r.ok) throw new Error(await parseError(r));
    return await r.json();
  },

  saveParams: async (caseId, values) => {
    const r = await fetch(`${BASE}/cases/${caseId}/params`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ values }),
    });
    if (!r.ok) throw new Error(await parseError(r));
    const updated = await r.json();
    set({ cases: get().cases.map((c) => (c.id === caseId ? updated : c)) });
    return updated;
  },

  saveEnv: async (data, envId) => {
    const r = await fetch(envId ? `${BASE}/envs/${envId}` : `${BASE}/envs`, {
      method: envId ? 'PUT' : 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(envId ? data : { ...data, project_id: get().projectId }),
    });
    if (!r.ok) throw new Error(await parseError(r));
    await get().loadEnvs();
    return await r.json();
  },

  deleteEnv: async (envId) => {
    const r = await fetch(`${BASE}/envs/${envId}`, { method: 'DELETE' });
    if (!r.ok) throw new Error(await parseError(r));
    await get().loadEnvs();
  },

  testEnv: async (envId) => {
    const r = await fetch(`${BASE}/envs/${envId}/test`, { method: 'POST' });
    if (!r.ok) throw new Error(await parseError(r));
    return await r.json();
  },
}));
