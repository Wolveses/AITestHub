import { create } from 'zustand';

const BASE = '/api/modules/mobile';

export interface MobileCase {
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
  platform: string;
  default_app_id: number | null;
  params: Record<string, string | number | boolean | null>;
  params_schema: Array<Record<string, unknown>>;
  status: string;
  script_version: number;
  has_script: boolean;
  last_error_category: string | null;
  last_error_message: string | null;
  last_run_id: number | null;
  last_generated_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface MobileAppEnv {
  id: number;
  project_id: number;
  name: string;
  platform: string;
  app_package: string;
  app_activity: string;
  app_file_rel: string;
  has_app_file: boolean;
  reset_mode: string;
  appium_url: string;
  test_username: string;
  password_set: boolean;
  extra_caps: Record<string, unknown>;
  is_default: boolean;
}

export interface MobileDevice {
  device_id: string;
  name: string;
  type: string;
  status: string;
  model: string | null;
  sdk_version: string | null;
  busy: boolean;
  lease: {
    device_id: string;
    holder_type: string;
    case_id: number;
    generation_id: number | null;
    acquired_at: string;
    expires_at: string;
  } | null;
  wireless_endpoint: string;
}

export interface MobileGenerationSession {
  generation_id: number;
  case_id: number;
  device_id: string;
  app_id: number;
  session_token: string;
  expires_at: string;
  mcp_url: string;
  mcp_config: Record<string, unknown>;
  agent_prompt: string;
}

export interface MobileGenerationDetail {
  id: number;
  case_id: number;
  kind: string;
  attempt: number;
  status: string;
  engine_type: string;
  engine_detail: string;
  device_id: string;
  app_id: number | null;
  error_category: string | null;
  error_message: string | null;
  tool_calls: number;
  last_dry_run_passed: boolean;
  started_at: string | null;
  finished_at: string | null;
  step_screenshots: string[];
  events?: Array<{
    ts: string;
    type: string;
    tool?: string;
    filename?: string;
    passed?: boolean;
    error?: string;
    [k: string]: unknown;
  }>;
}

export interface MobileActiveGenerationItem {
  generation_id: number;
  case_id: number;
  title: string;
  kind: string;
  status: string;
  stage: 'waiting' | 'generating' | 'dry_run_ok' | string;
  device_id: string;
  tool_calls: number;
  last_dry_run_passed: boolean;
  latest_event: {
    ts?: string;
    type?: string;
    tool?: string;
    error?: string;
    filename?: string;
    passed?: boolean;
    run_id?: number;
    [k: string]: unknown;
  } | null;
  last_error: string | null;
  started_at: string | null;
  expires_at: string | null;
  step_screenshots: string[];
}

export interface MobileRunItem {
  id: number;
  case_id: number;
  project_id: number | null;
  app_id: number | null;
  case_title: string;
  status: string;
  runner: string;
  device_id: string;
  script_version: number | null;
  duration_ms: number;
  error: string | null;
  screenshots?: string[];
  has_log?: boolean;
  has_device_log?: boolean;
  started_at: string | null;
  finished_at: string | null;
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
  imported: boolean;
  suggested_platform: string;
}

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try {
      const data = await res.json();
      if (Array.isArray(data.detail)) {
        msg =
          data.detail
            .map((d: { loc?: unknown[]; msg?: string }) =>
              d.loc ? `${d.loc.join('.')}: ${d.msg || ''}` : d.msg || JSON.stringify(d)
            )
            .join('; ') || msg;
      } else {
        msg = data.detail || data.message || msg;
      }
    } catch {
      // ignore non-json error
    }
    throw new Error(msg);
  }
  return res.json();
}

interface MobileState {
  projectId: number | null;
  cases: MobileCase[];
  total: number;
  loading: boolean;
  statusFilter: string;
  categoryFilter: string | null;
  keyword: string;
  apps: MobileAppEnv[];
  devices: MobileDevice[];
  appiumReady: boolean;
  appiumDetail: string;
  devicesLoading: boolean;
  activeSessions: Record<number, MobileGenerationSession>;

  setProjectId: (id: number | null) => void;
  setStatusFilter: (s: string) => void;
  setCategoryFilter: (c: string | null) => void;
  setKeyword: (k: string) => void;

  loadCases: () => Promise<void>;
  importable: (opts: {
    search: string;
    categoryPath: string | null;
    page: number;
    pageSize: number;
  }) => Promise<{
    items: ImportableCase[];
    total: number;
    all_total: number;
    page: number;
    folders: { path: string; count: number }[];
  }>;
  importCases: (docIds: number[], platformMap?: Record<number, string>) => Promise<{
    created: number;
    skipped: number;
  }>;
  updateCase: (caseId: number, patch: Partial<MobileCase>) => Promise<MobileCase>;
  deleteCase: (caseId: number) => Promise<void>;
  getScript: (caseId: number) => Promise<{ content: string; version: number }>;
  saveScript: (caseId: number, content: string) => Promise<{ version: number }>;

  createGenerationSession: (
    caseId: number,
    payload: { device_id: string; app_id?: number | null; kind?: string }
  ) => Promise<MobileGenerationSession>;
  cancelGenerate: (caseId: number) => Promise<void>;
  getActiveGeneration: (
    caseId: number
  ) => Promise<{ active: boolean; generation: MobileGenerationDetail | null }>;
  getActiveGenerations: (projectId: number) => Promise<MobileActiveGenerationItem[]>;
  clearActiveSession: (caseId: number) => void;
  getGenerations: (caseId: number) => Promise<MobileGenerationDetail[]>;
  getGenerationDetail: (genId: number) => Promise<MobileGenerationDetail>;

  runCase: (caseId: number, payload: { device_id: string; app_id?: number | null }) => Promise<{ run_id: number }>;
  getCaseRuns: (caseId: number) => Promise<MobileRunItem[]>;
  getRunDetail: (runId: number) => Promise<MobileRunItem>;
  getRunLog: (runId: number) => Promise<string>;
  getRunDeviceLog: (runId: number) => Promise<string>;

  loadApps: () => Promise<void>;
  createApp: (payload: Record<string, unknown>) => Promise<MobileAppEnv>;
  updateApp: (appId: number, payload: Record<string, unknown>) => Promise<MobileAppEnv>;
  deleteApp: (appId: number) => Promise<void>;
  uploadApk: (appId: number, file: File) => Promise<MobileAppEnv>;

  loadDevices: () => Promise<void>;
  enableWireless: (deviceId: string) => Promise<{ endpoint: string }>;
  releaseDevice: (deviceId: string) => Promise<void>;
}

export const useMobileStore = create<MobileState>((set, get) => ({
  projectId: null,
  cases: [],
  total: 0,
  loading: false,
  statusFilter: '',
  categoryFilter: null,
  keyword: '',
  apps: [],
  devices: [],
  appiumReady: false,
  appiumDetail: '',
  devicesLoading: false,
  activeSessions: {},

  setProjectId: (id) => set({ projectId: id }),
  setStatusFilter: (statusFilter) => set({ statusFilter }),
  setCategoryFilter: (categoryFilter) => set({ categoryFilter }),
  setKeyword: (keyword) => set({ keyword }),

  loadCases: async () => {
    const { projectId, statusFilter, categoryFilter, keyword } = get();
    if (projectId === null) return;
    set({ loading: true });
    try {
      const sp = new URLSearchParams({ project_id: String(projectId), page_size: '200' });
      if (statusFilter) sp.set('status', statusFilter);
      if (categoryFilter) sp.set('category_path', categoryFilter);
      if (keyword.trim()) sp.set('keyword', keyword.trim());
      const res = await req<{ items: MobileCase[]; total: number }>(`${BASE}/automation/cases?${sp}`);
      set({ cases: res.items, total: res.total });
    } finally {
      set({ loading: false });
    }
  },

  importable: async ({ search, categoryPath, page, pageSize }) => {
    const { projectId } = get();
    if (projectId === null) {
      return { items: [], total: 0, all_total: 0, page: 1, folders: [] };
    }
    const sp = new URLSearchParams({
      project_id: String(projectId),
      page: String(page),
      page_size: String(pageSize),
    });
    if (search.trim()) sp.set('search', search.trim());
    if (categoryPath) sp.set('category_path', categoryPath);
    return req(`${BASE}/automation/cases/importable?${sp}`);
  },

  importCases: async (document_ids, platform_map = {}) => {
    const { projectId, loadCases } = get();
    const res = await req<{ created: number; skipped: number }>(`${BASE}/automation/cases/import`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project_id: projectId, document_ids, platform_map }),
    });
    await loadCases();
    return res;
  },

  updateCase: async (caseId, patch) => {
    const updated = await req<MobileCase>(`${BASE}/automation/cases/${caseId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    });
    await get().loadCases();
    return updated;
  },

  deleteCase: async (caseId) => {
    await req(`${BASE}/automation/cases/${caseId}`, { method: 'DELETE' });
    await get().loadCases();
  },

  getScript: (caseId) => req(`${BASE}/automation/cases/${caseId}/script`),

  saveScript: async (caseId, content) => {
    const res = await req<{ version: number }>(`${BASE}/automation/cases/${caseId}/script`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    });
    await get().loadCases();
    return res;
  },

  createGenerationSession: async (caseId, payload) => {
    const res = await req<MobileGenerationSession>(
      `${BASE}/automation/cases/${caseId}/generation-sessions`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      }
    );
    set((s) => ({
      activeSessions: { ...s.activeSessions, [caseId]: res },
    }));
    await Promise.all([get().loadCases(), get().loadDevices()]);
    return res;
  },

  cancelGenerate: async (caseId) => {
    await req(`${BASE}/automation/cases/${caseId}/cancel-generate`, { method: 'POST' });
    get().clearActiveSession(caseId);
    await Promise.all([get().loadCases(), get().loadDevices()]);
  },

  getActiveGeneration: (caseId) => req(`${BASE}/automation/cases/${caseId}/active-generation`),

  getActiveGenerations: (projectId) =>
    req(`${BASE}/automation/cases/generations/active?project_id=${projectId}`),

  clearActiveSession: (caseId) =>
    set((s) => {
      if (!(caseId in s.activeSessions)) return s;
      const next = { ...s.activeSessions };
      delete next[caseId];
      return { activeSessions: next };
    }),

  getGenerations: (caseId) => req(`${BASE}/automation/cases/${caseId}/generations`),

  getGenerationDetail: (genId) => req(`${BASE}/automation/cases/generations/${genId}`),

  runCase: async (caseId, payload) => {
    const res = await req<{ run_id: number }>(`${BASE}/automation/cases/${caseId}/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    await Promise.all([get().loadCases(), get().loadDevices()]);
    return res;
  },

  getCaseRuns: (caseId) => req(`${BASE}/runs?case_id=${caseId}`),
  getRunDetail: (runId) => req(`${BASE}/runs/${runId}`),
  getRunLog: async (runId) => {
    const r = await fetch(`${BASE}/runs/${runId}/log`);
    return r.ok ? r.text() : '';
  },
  getRunDeviceLog: async (runId) => {
    const r = await fetch(`${BASE}/runs/${runId}/device-log`);
    return r.ok ? r.text() : '';
  },

  loadApps: async () => {
    const { projectId } = get();
    if (projectId === null) return;
    const apps = await req<MobileAppEnv[]>(`${BASE}/automation/apps?project_id=${projectId}`);
    set({ apps });
  },

  createApp: async (payload) => {
    const { projectId, loadApps } = get();
    if (projectId === null) {
      throw new Error('请先选择项目');
    }
    const res = await req<MobileAppEnv>(`${BASE}/automation/apps`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project_id: projectId, ...payload }),
    });
    await loadApps();
    return res;
  },

  updateApp: async (appId, payload) => {
    const res = await req<MobileAppEnv>(`${BASE}/automation/apps/${appId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    await get().loadApps();
    return res;
  },

  deleteApp: async (appId) => {
    await req(`${BASE}/automation/apps/${appId}`, { method: 'DELETE' });
    await get().loadApps();
  },

  uploadApk: async (appId, file) => {
    const fd = new FormData();
    fd.append('file', file);
    const res = await req<MobileAppEnv>(`${BASE}/automation/apps/${appId}/upload`, {
      method: 'POST',
      body: fd,
    });
    await get().loadApps();
    return res;
  },

  loadDevices: async () => {
    set({ devicesLoading: true });
    try {
      const res = await req<{
        devices: MobileDevice[];
        appium: { ready: boolean; url: string; detail: string };
      }>(`${BASE}/devices`);
      set({
        devices: res.devices || [],
        appiumReady: Boolean(res.appium?.ready),
        appiumDetail: res.appium?.detail || '',
      });
    } finally {
      set({ devicesLoading: false });
    }
  },

  enableWireless: async (deviceId) => {
    const res = await req<{ endpoint: string }>(
      `${BASE}/devices/${encodeURIComponent(deviceId)}/wireless`,
      { method: 'POST' }
    );
    await get().loadDevices();
    return res;
  },

  releaseDevice: async (deviceId) => {
    await req(`${BASE}/devices/${encodeURIComponent(deviceId)}/release`, { method: 'POST' });
    set((s) => {
      const next = { ...s.activeSessions };
      let changed = false;
      for (const [k, v] of Object.entries(next)) {
        if (v.device_id === deviceId) {
          delete next[Number(k)];
          changed = true;
        }
      }
      return changed ? { activeSessions: next } : s;
    });
    await Promise.all([get().loadDevices(), get().loadCases()]);
  },
}));

export function generationStepImageUrl(genId: number, filename: string): string {
  return `${BASE}/automation/cases/generations/${genId}/steps/${encodeURIComponent(filename)}`;
}

export function runArtifactUrl(runId: number, filename: string): string {
  return `${BASE}/runs/${runId}/artifacts/${encodeURIComponent(filename)}`;
}
