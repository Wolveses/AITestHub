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
  /** 本用例参数值（生成时由实测弹窗控件提取，可在参数面板修改） */
  params: Record<string, string | number | boolean | null>;
  /** 参数结构 */
  params_schema: ParamSchemaItem[];
  params_updated_at: string | null;
  status: string;
  script_version: number;
  has_script: boolean;
  /** 脚本来处：ai（平台）/ local_agent（本地 Agent 提交） */
  source?: string;
  authoring_by?: string;
  authoring_at?: string | null;
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
  desc?: string;
  unique?: boolean;
  options?: string[];
  /** 是否与用例步骤相关（相关才会展示在参数面板） */
  related?: boolean;
  /** 是否由系统自动填充（不展示、不可编辑） */
  auto?: boolean;
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
  auth_script?: string;
  token_inject?: string;
  token_name?: string;
  token_prefix?: string;
  is_default: boolean;
  has_storage_state: boolean;
  /** 是否允许本地 Agent 通过 MCP 获取该环境的认证信息 */
  allow_local_agent?: boolean;
}

export interface ScriptTemplate {
  id: string;
  name: string;
  description: string;
  code: string;
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
  /** local_agent | platform（后端派生） */
  origin?: 'local_agent' | 'platform';
  corpus_chars: number;
  prompt_chars: number;
  completion_chars: number;
  fix_rounds: number;
  /** 过程日志相对路径；本地 Agent 会话建行时即写入 */
  log_rel_path?: string;
  has_log?: boolean;
  duration_ms?: number | null;
  /** 生成成功时首跑的终态截图可预览 */
  has_screenshot: boolean;
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
  generate: (caseId: number) => Promise<void>;
  fix: (caseId: number) => Promise<void>;
  regenerate: (caseId: number) => Promise<void>;
  cancelGenerate: (caseId: number) => Promise<void>;
  run: (caseId: number) => Promise<void>;
  getCase: (caseId: number) => Promise<AutomationCase>;
  updateCase: (caseId: number, data: Partial<AutomationCase>) => Promise<AutomationCase>;
  saveParams: (
    caseId: number,
    values: Record<string, string | number | boolean | null>,
  ) => Promise<AutomationCase>;
  deleteCase: (caseId: number) => Promise<void>;
  getScript: (caseId: number) => Promise<{
    content: string;
    version: number;
    pages: { name: string; path?: string; content: string }[];
  }>;
  listRuns: (caseId: number) => Promise<ScriptRun[]>;
  listGenerations: (caseId: number) => Promise<GenerationRecord[]>;
  saveEnv: (data: Record<string, unknown>, envId?: number) => Promise<UIEnv>;
  cloneEnv: (envId: number, newName?: string) => Promise<UIEnv>;
  deleteEnv: (envId: number) => Promise<void>;
  switchEnv: (envId: number) => Promise<void>;
  testEnv: (envId: number, payload?: Record<string, unknown>) => Promise<{ ok: boolean; message: string; token?: string }>;
  testCustomEnv: (payload: Record<string, unknown>) => Promise<{ ok: boolean; message: string; token?: string }>;
  loadTemplates: () => Promise<ScriptTemplate[]>;
  loadProjectAuthScript: (projectId: number) => Promise<{ project_id: number; auth_script: string; has_script: boolean }>;
  saveProjectAuthScript: (projectId: number, authScript: string) => Promise<void>;
  testProjectAuthScript: (projectId: number, payload: Record<string, unknown>) => Promise<{ ok: boolean; message: string; token?: string }>;
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

  regenerate: async (caseId) => {
    const r = await fetch(`${BASE}/cases/${caseId}/regenerate`, { method: 'POST' });
    if (!r.ok) throw new Error(await parseError(r));
    await get().loadCases();
  },

  cancelGenerate: async (caseId) => {
    const r = await fetch(`${BASE}/cases/${caseId}/cancel`, { method: 'POST' });
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

  cloneEnv: async (envId, newName) => {
    const r = await fetch(`${BASE}/envs/${envId}/clone`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ new_name: newName || undefined }),
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

  switchEnv: async (envId) => {
    const r = await fetch(`${BASE}/envs/${envId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_default: true }),
    });
    if (!r.ok) throw new Error(await parseError(r));
    await get().loadEnvs();
  },

  testEnv: async (envId, payload) => {
    const r = await fetch(`${BASE}/envs/${envId}/test`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: payload ? JSON.stringify(payload) : undefined,
    });
    if (!r.ok) throw new Error(await parseError(r));
    return await r.json();
  },

  testCustomEnv: async (payload) => {
    const r = await fetch(`${BASE}/envs/test-custom`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!r.ok) throw new Error(await parseError(r));
    return await r.json();
  },

  loadTemplates: async () => {
    const r = await fetch(`${BASE}/envs/templates`);
    if (!r.ok) return [];
    return await r.json();
  },

  loadProjectAuthScript: async (projectId) => {
    const r = await fetch(`${BASE}/envs/projects/${projectId}/auth-script`);
    if (!r.ok) throw new Error(await parseError(r));
    return await r.json();
  },

  saveProjectAuthScript: async (projectId, authScript) => {
    const r = await fetch(`${BASE}/envs/projects/${projectId}/auth-script`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ auth_script: authScript }),
    });
    if (!r.ok) throw new Error(await parseError(r));
  },

  testProjectAuthScript: async (projectId, payload) => {
    const r = await fetch(`${BASE}/envs/projects/${projectId}/auth-script/test`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!r.ok) throw new Error(await parseError(r));
    return await r.json();
  },
}));

// ===== 本地 Agent 编写（MCP）=====

export type AuthoringMode = 'auto' | 'create' | 'fix' | 'regenerate';

export interface AuthoringTriageItem {
  case_id: number;
  title: string;
  site: string;
  status: string;
  case_rev: string;
  has_script: boolean;
  script_version: number;
  last_run: {
    run_id: number;
    status: string;
    finished_at: string | null;
    duration_ms: number | null;
    error: string;
  } | null;
  action: 'create' | 'fix' | 'regenerate' | 'skip';
  reason: string;
  next_tool: string | null;
  mode?: 'auto' | 'regenerate';
}

export interface AuthoringTriageSummary {
  create: number;
  fix: number;
  regenerate: number;
  skip: number;
}

export interface AuthoringPrompt {
  ok: boolean;
  project_id: number;
  project_name: string;
  case_ids: number[];
  skipped_case_ids: number[];
  mode: AuthoringMode;
  action_required: number;
  summary: AuthoringTriageSummary;
  cases: AuthoringTriageItem[];
  prompt: string | null;
  token: string | null;
  mcp_url: string;
  token_id: number | null;
  expires_at: string | null;
}

export interface AuthoringToken {
  id: number;
  name: string;
  prefix: string;
  created_at: string | null;
  last_used_at: string | null;
  expires_at: string | null;
  revoked: boolean;
  expired: boolean;
  active: boolean;
}

export interface AuthoringEvent {
  id: number;
  case_id: number;
  kind: string;
  message: string;
  payload: Record<string, unknown>;
  created_at: string | null;
}

export interface AuthoringStatusItem {
  case_id: number;
  exists: boolean;
  title?: string;
  status?: string;
  script_version?: number;
  source?: string;
  authoring_at?: string | null;
  stage?: string;
  last_error?: string;
  latest_event_id?: number;
  recent_events?: AuthoringEvent[];
}

export interface AuthoringActiveItem {
  case_id: number;
  title: string;
  status: string;
  stage: string;
  script_version: number;
  source_hash: string;
  last_error: string;
  updated_at: string | null;
  busy: boolean;
  latest_event: { message: string; created_at: string | null } | null;
}

export async function fetchAuthoringActive(projectId: number): Promise<AuthoringActiveItem[]> {
  const r = await fetch(`${BASE}/authoring/active?project_id=${projectId}`);
  if (!r.ok) throw new Error(await parseError(r));
  const data = await r.json();
  return data.items || [];
}

const EMPTY_TRIAGE_SUMMARY: AuthoringTriageSummary = {
  create: 0,
  fix: 0,
  regenerate: 0,
  skip: 0,
};

export async function fetchAuthoringTriage(
  projectId: number,
  caseIds: number[],
  mode: 'auto' | 'regenerate' = 'auto'
): Promise<{ summary: AuthoringTriageSummary; items: AuthoringTriageItem[] }> {
  if (caseIds.length === 0) return { summary: { ...EMPTY_TRIAGE_SUMMARY }, items: [] };
  const q = new URLSearchParams({
    project_id: String(projectId),
    case_ids: caseIds.join(','),
    mode,
  });
  const r = await fetch(`${BASE}/authoring/triage?${q.toString()}`);
  if (!r.ok) throw new Error(await parseError(r));
  const data = await r.json();
  return { summary: data.summary || { ...EMPTY_TRIAGE_SUMMARY }, items: data.items || [] };
}

export async function requestAuthoringPrompt(
  projectId: number,
  caseIds: number[],
  mode: AuthoringMode = 'auto'
): Promise<AuthoringPrompt> {
  const r = await fetch(`${BASE}/authoring/prompt`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project_id: projectId, case_ids: caseIds, mode }),
  });
  if (!r.ok) throw new Error(await parseError(r));
  return await r.json();
}

export async function fetchAuthoringTokens(projectId: number): Promise<AuthoringToken[]> {
  const r = await fetch(`${BASE}/authoring/tokens?project_id=${projectId}`);
  if (!r.ok) throw new Error(await parseError(r));
  const data = await r.json();
  return data.items || [];
}

export async function revokeAuthoringToken(projectId: number, tokenId: number): Promise<void> {
  const r = await fetch(`${BASE}/authoring/tokens/${tokenId}?project_id=${projectId}`, { method: 'DELETE' });
  if (!r.ok) throw new Error(await parseError(r));
}

export async function fetchAuthoringStatus(caseIds: number[]): Promise<AuthoringStatusItem[]> {
  if (caseIds.length === 0) return [];
  const r = await fetch(`${BASE}/authoring/status?case_ids=${caseIds.join(',')}`);
  if (!r.ok) throw new Error(await parseError(r));
  const data = await r.json();
  return data.items || [];
}
