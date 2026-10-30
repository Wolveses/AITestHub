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
  setProjectId: (id: number | null) => void;
  setStatusFilter: (s: string) => void;
  setCategoryFilter: (c: string | null) => void;
  setKeyword: (k: string) => void;
  loadCases: () => Promise<void>;
  loadEnvs: () => Promise<void>;
  importable: () => Promise<ImportableCase[]>;
  importCases: (
    documentIds: number[],
    siteMap?: Record<number, string>,
  ) => Promise<{ created: number; skipped: number; failed: unknown[] }>;
  generate: (caseId: number) => Promise<void>;
  fix: (caseId: number) => Promise<void>;
  run: (caseId: number) => Promise<void>;
  getCase: (caseId: number) => Promise<AutomationCase>;
  updateCase: (caseId: number, data: Partial<AutomationCase>) => Promise<AutomationCase>;
  deleteCase: (caseId: number) => Promise<void>;
  getScript: (caseId: number) => Promise<{ content: string; version: number }>;
  listRuns: (caseId: number) => Promise<ScriptRun[]>;
  listGenerations: (caseId: number) => Promise<GenerationRecord[]>;
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

  setProjectId: (id) => {
    if (id === null) localStorage.removeItem(LS_PROJECT);
    else localStorage.setItem(LS_PROJECT, String(id));
    set({ projectId: id, categoryFilter: null });
  },
  setStatusFilter: (s) => set({ statusFilter: s }),
  setCategoryFilter: (c) => set({ categoryFilter: c }),
  setKeyword: (k) => set({ keyword: k }),

  loadCases: async () => {
    const { projectId, statusFilter, categoryFilter, keyword } = get();
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

  importable: async () => {
    const projectId = get().projectId;
    if (projectId === null) return [];
    const r = await fetch(`${BASE}/cases/importable?project_id=${projectId}`);
    if (!r.ok) throw new Error(await parseError(r));
    return (await r.json()).items || [];
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

  generate: async (caseId) => {
    const r = await fetch(`${BASE}/cases/${caseId}/generate`, { method: 'POST' });
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
