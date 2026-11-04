import { create } from 'zustand';
import { useProjectStore } from '../../../shared/store/projectStore';

/** API 用例步骤（前端可编辑的最小结构；未识别字段透传后端）。 */
export interface ApiStep {
  name?: string;
  method: string;
  path: string;
  headers?: Record<string, string>;
  body?: unknown;
  assertions?: { type: string; path?: string; expected?: unknown }[];
  extract?: Record<string, string>;
  [key: string]: unknown;
}

/** D 的 API 用例（只读引用）。 */
export interface ApiCase {
  id: number;
  title: string;
  status: string;
  content: { base_url?: string; steps: ApiStep[] };
  last_result: string | null;
}

export interface StepResult {
  step_index: number;
  request: { method: string; url: string; headers: Record<string, string>; body: unknown };
  status_code: number | null;
  response_body: unknown;
  response_headers: Record<string, string>;
  elapsed_ms: number;
  assertions: { type: string; target: string; expected: unknown; actual: unknown; passed: boolean }[];
  extracts: Record<string, unknown>;
  error: string | null;
  passed: boolean;
}

export interface RunSummary {
  id: number;
  case_id: number;
  case_title: string;
  status: 'passed' | 'failed' | 'error';
  total_steps: number;
  passed_steps: number;
  started_at: string;
  duration_ms: number;
}

export interface RunDetail extends RunSummary {
  steps: StepResult[];
}

interface RunState {
  cases: ApiCase[];
  selectedCaseId: number | null;
  runs: RunSummary[];
  selectedRun: RunDetail | null;
  executing: boolean;
  loadingCases: boolean;

  loadCases: () => Promise<void>;
  selectCase: (id: number) => void;
  createCase: (title: string) => Promise<number>;
  updateCase: (id: number, patch: { title?: string; content?: { base_url: string; steps: unknown[] } }) => Promise<void>;
  deleteCase: (id: number) => Promise<void>;
  loadRuns: (caseId: number) => Promise<void>;
  execute: (caseId: number, environmentId?: number | null) => Promise<void>;
  loadRunDetail: (runId: number) => Promise<void>;
}

const API_BASE = '/api/modules/api';
const TC_BASE = '/api/modules/testcase/testcases';

export const useRunStore = create<RunState>((set, get) => ({
  cases: [],
  selectedCaseId: null,
  runs: [],
  selectedRun: null,
  executing: false,
  loadingCases: false,

  loadCases: async () => {
    set({ loadingCases: true });
    try {
      const { currentProjectId, currentVersionId } = useProjectStore.getState();
      const params = new URLSearchParams({ type: 'api' });
      if (currentProjectId !== null) params.set('project_id', String(currentProjectId));
      if (currentVersionId !== null) params.set('version_id', String(currentVersionId));
      const r = await fetch(`${TC_BASE}?${params}`);
      const cases = await r.json();
      set({ cases });
    } finally {
      set({ loadingCases: false });
    }
  },

  selectCase: (id) => {
    set({ selectedCaseId: id, runs: [], selectedRun: null });
    get().loadRuns(id);
  },

  createCase: async (title) => {
    const { currentProjectId, currentVersionId } = useProjectStore.getState();
    const r = await fetch(TC_BASE, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title,
        type: 'api',
        content: { base_url: '', steps: [] },
        project_id: currentProjectId,
        version_id: currentVersionId,
      }),
    });
    if (!r.ok) throw new Error((await r.text()) || '新建用例失败');
    const created = (await r.json()) as ApiCase;
    await get().loadCases();
    return created.id;
  },

  updateCase: async (id, patch) => {
    const r = await fetch(`${TC_BASE}/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    });
    if (!r.ok) throw new Error((await r.text()) || '保存用例失败');
    const updated = (await r.json()) as ApiCase;
    set((s) => ({ cases: s.cases.map((c) => (c.id === id ? { ...c, ...updated } : c)) }));
  },

  deleteCase: async (id) => {
    const r = await fetch(`${TC_BASE}/${id}`, { method: 'DELETE' });
    if (!r.ok) throw new Error((await r.text()) || '删除用例失败');
    set((s) => ({
      cases: s.cases.filter((c) => c.id !== id),
      selectedCaseId: s.selectedCaseId === id ? null : s.selectedCaseId,
      runs: s.selectedCaseId === id ? [] : s.runs,
      selectedRun: s.selectedCaseId === id ? null : s.selectedRun,
    }));
  },

  loadRuns: async (caseId) => {
    const r = await fetch(`${API_BASE}/runs?case_id=${caseId}`);
    const runs = await r.json();
    set({ runs });
  },

  execute: async (caseId, environmentId = null) => {
    set({ executing: true });
    try {
      const url = environmentId
        ? `${API_BASE}/runs/execute?environment_id=${environmentId}`
        : `${API_BASE}/runs/execute`;
      const r = await fetch(url, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ case_id: caseId }),
      });
      if (!r.ok) throw new Error((await r.text()) || '执行失败');
      const run: RunDetail = await r.json();
      // 刷新历史 + 自动选中最新
      await get().loadRuns(caseId);
      set({ selectedRun: run });
    } finally {
      set({ executing: false });
    }
  },

  loadRunDetail: async (runId) => {
    const r = await fetch(`${API_BASE}/runs/${runId}`);
    if (r.ok) {
      const run = await r.json();
      set({ selectedRun: run });
    }
  },
}));
