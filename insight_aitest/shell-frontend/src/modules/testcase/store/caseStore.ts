import { create } from 'zustand';

export interface TestCase {
  id: number;
  title: string;
  type: string;            // functional|api|performance|ui
  description: string;
  priority: string;        // p0|p1|p2|p3
  status: string;          // draft|reviewed|ready|deprecated
  test_design: string;     // positive|negative|boundary|edge
  preconditions: string;
  content: Record<string, unknown>;
  tags: string[];
  source: string;
  project_id: number | null;
  version_id: number | null;
  folder_id: number | null;
  last_run_at: string | null;
  last_result: string | null;
  created_at: string;
  updated_at: string;
}

export interface FolderNode {
  id: number;
  name: string;
  parent_id: number | null;
  project_id: number | null;
  children: FolderNode[];
  case_count: number;
}

export interface TestPoint {
  id: string;
  summary: string;
  suggested_type: string;
  suggested_design: string;
  rationale: string;
}

interface CaseState {
  cases: TestCase[];
  activeId: number | null;
  loading: boolean;
  folders: FolderNode[];
  currentFolderId: number | null; // null: 全部, -1: 未分类, >0: 具体目录
  selectedProjectId: number | null;
  setSelectedProjectId: (id: number | null) => void;
  // 生成向导临时态
  analyzeLoading: boolean;
  analyzePoints: TestPoint[];
  generateProgress: { done: number; total: number } | null;
  imageGenerating: boolean;

  loadCases: (type?: string, status?: string) => Promise<void>;
  selectCase: (id: number | null) => void;
  createCase: (data: Partial<TestCase>) => Promise<number>;
  updateCase: (id: number, data: Partial<TestCase>) => Promise<void>;
  updateStatus: (id: number, status: string) => Promise<void>;
  deleteCase: (id: number) => Promise<void>;
  analyze: (query: string, documentIds?: number[] | null) => Promise<void>;

  // 目录管理
  loadFolders: (projectId?: number | null) => Promise<void>;
  createFolder: (name: string, parentId?: number | null, projectId?: number | null) => Promise<FolderNode>;
  updateFolder: (id: number, name: string) => Promise<void>;
  deleteFolder: (id: number) => Promise<void>;
  setCurrentFolderId: (id: number | null) => void;

  // 批量操作
  batchAssign: (caseIds: number[], options: { project_id?: number | null; version_id?: number | null; folder_id?: number | null }) => Promise<void>;
  batchDelete: (caseIds: number[]) => Promise<void>;

  // P2: 统一通过 AI /tasks/quick 创建预置任务（analyze_generate | image_generate）
  createQuickTask: (mode: 'analyze_generate' | 'image_generate', payload: Record<string, unknown>) => Promise<{ task_id: number; source_mode: string }>;
  // P2: 迁移用例归属（项目 / 版本）
  assignCase: (caseId: number, projectId?: number, versionId?: number) => Promise<TestCase>;
}

const BASE = '/api/modules/testcase';

export const useCaseStore = create<CaseState>((set, get) => ({
  cases: [],
  activeId: null,
  loading: false,
  folders: [],
  currentFolderId: null,
  selectedProjectId: null,
  setSelectedProjectId: (id) => {
    set({ selectedProjectId: id });
  },
  analyzeLoading: false,
  analyzePoints: [],
  generateProgress: null,
  imageGenerating: false,

  setCurrentFolderId: (id) => {
    set({ currentFolderId: id });
  },

  loadFolders: async (projectId) => {
    const projId = projectId !== undefined ? projectId : get().selectedProjectId;
    const url = projId !== null ? `${BASE}/testcases/folders?project_id=${projId}` : `${BASE}/testcases/folders`;
    try {
      const r = await fetch(url);
      if (r.ok) {
        const folders: FolderNode[] = await r.json();
        set({ folders });
      }
    } catch {
      // 保持现状
    }
  },

  createFolder: async (name, parentId, projectId) => {
    const projId = projectId !== undefined ? projectId : get().selectedProjectId;
    const r = await fetch(`${BASE}/testcases/folders`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, parent_id: parentId ?? null, project_id: projId ?? null }),
    });
    if (!r.ok) throw new Error(await r.text());
    const node: FolderNode = await r.json();
    await get().loadFolders(projId);
    return node;
  },

  updateFolder: async (id, name) => {
    const r = await fetch(`${BASE}/testcases/folders/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
    if (!r.ok) throw new Error(await r.text());
    await get().loadFolders();
  },

  deleteFolder: async (id) => {
    const r = await fetch(`${BASE}/testcases/folders/${id}`, { method: 'DELETE' });
    if (!r.ok) throw new Error(await r.text());
    if (get().currentFolderId === id) {
      set({ currentFolderId: null });
    }
    await get().loadFolders();
    await get().loadCases();
  },

  batchAssign: async (caseIds, options) => {
    const r = await fetch(`${BASE}/testcases/batch-assign`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        case_ids: caseIds,
        project_id: options.project_id,
        version_id: options.version_id,
        folder_id: options.folder_id,
      }),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: '批量分配失败' }));
      throw new Error(err.detail || '批量分配失败');
    }
    await get().loadCases();
    await get().loadFolders();
  },

  batchDelete: async (caseIds) => {
    const r = await fetch(`${BASE}/testcases/batch-delete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ case_ids: caseIds }),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: '批量删除失败' }));
      throw new Error(err.detail || '批量删除失败');
    }
    const { activeId } = get();
    if (activeId && caseIds.includes(activeId)) {
      set({ activeId: null });
    }
    await get().loadCases();
    await get().loadFolders();
  },

  loadCases: async (type?: string, status?: string) => {
    set({ loading: true });
    try {
      const { currentFolderId, selectedProjectId } = get();
      const params = new URLSearchParams();
      if (type) params.set('type', type);
      if (status) params.set('status', status);
      if (selectedProjectId !== null) params.set('project_id', String(selectedProjectId));
      if (currentFolderId !== null) params.set('folder_id', String(currentFolderId));
      const q = params.toString() ? `?${params}` : '';
      const r = await fetch(`${BASE}/testcases${q}`);
      const cases = await r.json();
      set({ cases: Array.isArray(cases) ? cases : [] });
    } finally {
      set({ loading: false });
    }
  },

  selectCase: (id) => set({ activeId: id }),

  createCase: async (data) => {
    const { selectedProjectId } = get();
    const r = await fetch(`${BASE}/testcases`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ...data,
        project_id: data.project_id ?? selectedProjectId,
        version_id: data.version_id ?? null,
      }),
    });
    const c = await r.json();
    set((s) => ({ cases: [c, ...s.cases], activeId: c.id }));
    return c.id;
  },

  updateCase: async (id, data) => {
    const r = await fetch(`${BASE}/testcases/${id}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    const updated = await r.json();
    set((s) => ({ cases: s.cases.map((c) => (c.id === id ? updated : c)) }));
  },

  updateStatus: async (id, status) => {
    const r = await fetch(`${BASE}/testcases/${id}/status`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status }),
    });
    const updated = await r.json();
    set((s) => ({ cases: s.cases.map((c) => (c.id === id ? updated : c)) }));
  },

  deleteCase: async (id) => {
    await fetch(`${BASE}/testcases/${id}`, { method: 'DELETE' });
    set((s) => ({
      cases: s.cases.filter((c) => c.id !== id),
      activeId: s.activeId === id ? null : s.activeId,
    }));
  },

  analyze: async (query, documentIds) => {
    set({ analyzeLoading: true, analyzePoints: [] });
    try {
      const r = await fetch(`${BASE}/testcases/analyze`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query, document_ids: documentIds ?? null }),
      });
      const points = await r.json();
      set({ analyzePoints: points });
    } finally {
      set({ analyzeLoading: false });
    }
  },

  createQuickTask: async (mode, payload) => {
    const resp = await fetch('/api/modules/ai/tasks/quick', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode, ...payload }),
    });
    if (!resp.ok) throw new Error(await resp.text());
    return resp.json();
  },

  assignCase: async (caseId, projectId, versionId) => {
    const resp = await fetch(`/api/modules/testcase/testcases/${caseId}/assignment`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project_id: projectId, version_id: versionId }),
    });
    if (!resp.ok) throw new Error(await resp.text());
    const updated: TestCase = await resp.json();
    set((s) => ({ cases: s.cases.map((c) => (c.id === caseId ? updated : c)) }));
    return updated;
  },
}));
