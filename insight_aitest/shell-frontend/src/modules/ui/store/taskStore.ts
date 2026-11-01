import { create } from 'zustand';

export interface UiTaskItem {
  id: number;
  project_id: number;
  name: string;
  description: string;
  env_id: number;
  env_name: string;
  cron_expression: string;
  cron_enabled: boolean;
  case_count: number;
  last_status: string;
  last_run_at: string | null;
  last_run_id: number | null;
  created_at: string;
  updated_at: string;
}

export interface UiTaskCaseItem {
  id: number;
  case_id: number;
  title: string;
  category: string;
  category_path: string;
  site: string;
  status: string;
  order_no: number;
  created_at: string;
}

export interface ImportableCaseItem {
  id: number;
  title: string;
  site: string;
  category: string;
  category_path: string;
  status: string;
  already_imported: boolean;
}

export interface ImportableCategory {
  name: string;
  cases: ImportableCaseItem[];
}

export interface UiTaskRunItem {
  id: number;
  task_id: number;
  project_id: number;
  env_id: number;
  trigger_type: string;
  status: string;
  total_cases: number;
  passed_cases: number;
  failed_cases: number;
  duration_ms: number;
  error_message: string;
  started_at: string | null;
  ended_at: string | null;
  created_at: string;
}

export interface TaskReportSummaryItem {
  case_id: number;
  title: string;
  site: string;
  category: string;
  status: string;
  duration_ms: number;
  error: string;
  run_id: number | null;
  artifacts_rel_path: string;
  /** 以下为执行产物探测结果，旧批次数据可能缺失 */
  trace_rel_path?: string;
  has_final?: boolean;
  has_failure?: boolean;
}

export interface TaskReportData {
  run: UiTaskRunItem;
  task_name: string;
  env_name: string;
  summary: TaskReportSummaryItem[];
}

interface TaskState {
  tasks: UiTaskItem[];
  loading: boolean;
  currentTaskCases: UiTaskCaseItem[];
  loadingCases: boolean;
  currentTaskRuns: UiTaskRunItem[];
  loadingRuns: boolean;
  currentReport: TaskReportData | null;
  loadingReport: boolean;

  loadTasks: (projectId: number) => Promise<void>;
  createTask: (data: {
    project_id: number;
    name: string;
    env_id: number;
    description?: string;
    cron_expression?: string;
    cron_enabled?: boolean;
  }) => Promise<UiTaskItem>;
  updateTask: (
    taskId: number,
    data: {
      name?: string;
      env_id?: number;
      description?: string;
      cron_expression?: string;
      cron_enabled?: boolean;
    },
  ) => Promise<UiTaskItem>;
  deleteTask: (taskId: number) => Promise<void>;

  loadTaskCases: (taskId: number) => Promise<void>;
  loadImportableCases: (
    taskId: number,
    projectId: number,
  ) => Promise<{ categories: ImportableCategory[]; total_implemented: number; already_imported_count: number }>;
  importCasesToTask: (taskId: number, caseIds: number[]) => Promise<{ imported_count: number; total_cases: number }>;
  removeCaseFromTask: (taskId: number, caseId: number) => Promise<void>;

  runTask: (taskId: number) => Promise<{ run_id: number; status: string }>;
  loadTaskRuns: (taskId: number) => Promise<void>;
  loadTaskReport: (runId: number) => Promise<TaskReportData>;
}

const BASE = '/api/modules/ui/automation/tasks';

export const useTaskStore = create<TaskState>((set, get) => ({
  tasks: [],
  loading: false,
  currentTaskCases: [],
  loadingCases: false,
  currentTaskRuns: [],
  loadingRuns: false,
  currentReport: null,
  loadingReport: false,

  loadTasks: async (projectId: number) => {
    set({ loading: true });
    try {
      const res = await fetch(`${BASE}?project_id=${projectId}`);
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      set({ tasks: Array.isArray(data) ? data : [] });
    } finally {
      set({ loading: false });
    }
  },

  createTask: async (data) => {
    const res = await fetch(BASE, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || '创建任务失败');
    }
    const created: UiTaskItem = await res.json();
    set((s) => ({ tasks: [created, ...s.tasks] }));
    return created;
  },

  updateTask: async (taskId, data) => {
    const res = await fetch(`${BASE}/${taskId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || '更新任务失败');
    }
    const updated: UiTaskItem = await res.json();
    set((s) => ({
      tasks: s.tasks.map((t) => (t.id === taskId ? updated : t)),
    }));
    return updated;
  },

  deleteTask: async (taskId) => {
    const res = await fetch(`${BASE}/${taskId}`, { method: 'DELETE' });
    if (!res.ok) throw new Error('删除任务失败');
    set((s) => ({ tasks: s.tasks.filter((t) => t.id !== taskId) }));
  },

  loadTaskCases: async (taskId) => {
    set({ loadingCases: true });
    try {
      const res = await fetch(`${BASE}/${taskId}/cases`);
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      set({ currentTaskCases: Array.isArray(data) ? data : [] });
    } finally {
      set({ loadingCases: false });
    }
  },

  loadImportableCases: async (taskId, projectId) => {
    const res = await fetch(`${BASE}/${taskId}/importable-cases?project_id=${projectId}`);
    if (!res.ok) throw new Error(await res.text());
    return await res.json();
  },

  importCasesToTask: async (taskId, caseIds) => {
    const res = await fetch(`${BASE}/${taskId}/cases/import`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ case_ids: caseIds }),
    });
    if (!res.ok) throw new Error('导入用例失败');
    const result = await res.json();
    // 更新任务列表中该任务的 case_count
    set((s) => ({
      tasks: s.tasks.map((t) => (t.id === taskId ? { ...t, case_count: result.total_cases } : t)),
    }));
    // 重新载入当前用例
    await get().loadTaskCases(taskId);
    return result;
  },

  removeCaseFromTask: async (taskId, caseId) => {
    const res = await fetch(`${BASE}/${taskId}/cases/${caseId}`, { method: 'DELETE' });
    if (!res.ok) throw new Error('移除用例失败');
    set((s) => ({
      currentTaskCases: s.currentTaskCases.filter((c) => c.case_id !== caseId),
      tasks: s.tasks.map((t) =>
        t.id === taskId ? { ...t, case_count: Math.max(0, t.case_count - 1) } : t,
      ),
    }));
  },

  runTask: async (taskId) => {
    const res = await fetch(`${BASE}/${taskId}/run`, { method: 'POST' });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || '触发任务执行失败');
    }
    const result = await res.json();
    set((s) => ({
      tasks: s.tasks.map((t) => (t.id === taskId ? { ...t, last_status: 'running' } : t)),
    }));
    return result;
  },

  loadTaskRuns: async (taskId) => {
    set({ loadingRuns: true });
    try {
      const res = await fetch(`${BASE}/${taskId}/runs`);
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      set({ currentTaskRuns: Array.isArray(data) ? data : [] });
    } finally {
      set({ loadingRuns: false });
    }
  },

  loadTaskReport: async (runId) => {
    set({ loadingReport: true, currentReport: null });
    try {
      const res = await fetch(`${BASE}/runs/${runId}/report`);
      if (!res.ok) throw new Error(await res.text());
      const data: TaskReportData = await res.json();
      set({ currentReport: data });
      return data;
    } finally {
      set({ loadingReport: false });
    }
  },
}));

