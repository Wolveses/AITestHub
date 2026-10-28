import { create } from 'zustand';

export interface DefectMeta {
  defect_id: string;
  workspace_id: string;
  status: string;
  priority: string;
  severity: string;
  module: string;
  owner: string;
  created_at: string;
  modified_at: string;
  comment_count: number;
}

export interface CaseMeta {
  case_id: string;
  workspace_id: string;
  status: string;
  priority: string;
  case_type: string;
  category_path: string;
  owner: string;
  creator: string;
  step_count: number;
  created_at: string;
  modified_at: string;
}

export interface Document {
  id: number;
  filename: string;
  status: string;  // pending|parsing|chunking|embedding|ready|*_failed|embed_partial
  char_count: number;
  chunk_count: number;
  error_message: string | null;
  project_id: number | null;
  version_id: number | null;
  folder_id: number | null;
  tags: string[];
  doc_type: string;
  description: string;
  source_type?: string;
  source_url?: string;
  external_id?: string;
  /** 内容实体类型：文档 / 缺陷 / 用例 */
  kind?: 'doc' | 'defect' | 'case';
  /** kind=defect 时的 TAPD 结构化元数据 */
  defect?: DefectMeta | null;
  /** kind=case 时的 TAPD 结构化元数据 */
  case?: CaseMeta | null;
  created_at: string;
  /** 后台重解析进行中（后端内存标记，早于 status 变为 pending） */
  reindexing?: boolean;
}

export interface FolderNode {
  id: number;
  name: string;
  parent_id: number | null;
  project_id: number | null;
  source_type?: string;
  external_id?: string;
  children: FolderNode[];
  doc_count: number;
}

export interface DocVersion {
  id: number;
  document_id: number;
  version_no: number;
  char_count: number;
  chunk_count: number;
  note: string;
  is_current: number;
  created_at: string;
}

export interface TagCount {
  tag: string;
  count: number;
}

export interface FeishuSpace {
  space_id: string;
  name: string;
  description?: string;
}

interface KnowledgeState {
  documents: Document[];
  docTotal: number;
  page: number;
  pageSize: number;
  // filter 状态（保存以便 loadDocuments 无参时复用）
  filterSearch: string;
  filterDocType: string;
  filterTags: string[];
  // 内容实体类型筛选：doc | defect | case
  kindFilter: 'doc' | 'defect' | 'case';
  // 缺陷库独立的项目上下文（不写入全局项目，避免污染知识库文档列表的项目过滤）
  defectProjectId: number | null;
  // 用例库独立的项目上下文，与缺陷库互不影响
  caseProjectId: number | null;
  folders: FolderNode[];
  currentFolderId: number | null; // null 表示当前根目录（本地文档/飞书文档根目录），0 表示未分类
  activeTab: 'local' | 'feishu' | 'defect' | 'case';
  uploading: boolean;
  saving: boolean;
  syncingFeishu: boolean;
  feishuModalOpen: boolean;
  pollTimer: number | null;
  tags: TagCount[];
  setActiveTab: (tab: 'local' | 'feishu' | 'defect' | 'case') => void;
  setDefectProjectId: (id: number | null) => void;
  setCaseProjectId: (id: number | null) => void;
  setKindFilter: (v: 'doc' | 'defect' | 'case') => void;
  setFeishuModalOpen: (v: boolean) => void;
  loadDocuments: (opts?: {
    search?: string;
    doc_type?: string;
    tags?: string[];
    page?: number;
    page_size?: number;
    resetPage?: boolean;
  }) => Promise<void>;
  loadFolders: () => Promise<void>;
  setCurrentFolderId: (folderId: number | null) => void;
  createFolder: (name: string, parentId?: number | null) => Promise<void>;
  updateFolder: (id: number, name?: string, parentId?: number | null) => Promise<void>;
  deleteFolder: (id: number) => Promise<void>;
  moveDocument: (docId: number, folderId: number | null) => Promise<void>;
  uploadDocument: (file: File) => Promise<void>;
  deleteDocument: (id: number) => void;
  startPolling: () => void;
  stopPolling: () => void;
  // 强制轮询：重新解析刚触发时当前页可能还全是终态，需强制保持轮询直到任务结束
  forcePoll: boolean;
  setForcePoll: (v: boolean) => void;
  // 飞书主动同步
  listFeishuSpaces: () => Promise<FeishuSpace[]>;
  syncFeishuSpace: (spaceId: string) => Promise<{ ok: boolean; result: any }>;
  // KB 升级新增
  fetchContent: (id: number) => Promise<{ text: string; filename: string; mime_type: string | null }>;
  saveContent: (id: number, text: string, note?: string) => Promise<void>;
  saveBinaryFile: (id: number, blob: Blob, filename: string, note?: string) => Promise<void>;
  updateMeta: (id: number, meta: { tags?: string[]; doc_type?: string; description?: string }) => Promise<void>;
  loadTags: () => Promise<void>;
  listVersions: (id: number) => Promise<DocVersion[]>;
  getVersionContent: (id: number, versionNo: number) => Promise<string>;
  rollbackVersion: (id: number, versionNo: number) => Promise<void>;
  rawUrl: (id: number) => string;
  exportZipUrl: () => string;
}

const BASE = '/api/modules/kb/documents';
const FOLDERS_BASE = '/api/modules/kb/folders';

const NON_TERMINAL = ['pending', 'parsing', 'chunking', 'embedding'];
export const isNonTerminal = (status: string) => NON_TERMINAL.includes(status);

function projectQs(
  extraParams?: Record<string, any>,
  projectOverride?: { projectId: number | null },
): string {
  const params = new URLSearchParams();
  // 知识库不绑定全局项目：仅缺陷库按 defectProjectId 显式过滤，其余查询不带项目条件
  if (projectOverride?.projectId != null) {
    params.set('project_id', String(projectOverride.projectId));
  }
  if (extraParams) {
    for (const [k, v] of Object.entries(extraParams)) {
      if (v === undefined || v === null || v === '') continue;
      if (Array.isArray(v)) {
        for (const item of v) params.append(k, String(item));
      } else {
        params.set(k, String(v));
      }
    }
  }
  const qs = params.toString();
  return qs ? `?${qs}` : '';
}

export const useKnowledgeStore = create<KnowledgeState>((set, get) => ({
  documents: [],
  docTotal: 0,
  page: 1,
  pageSize: 20,
  filterSearch: '',
  filterDocType: '',
  filterTags: [],
  kindFilter: 'doc',
  defectProjectId: null,
  caseProjectId: null,
  folders: [],
  currentFolderId: null,
  activeTab: 'local',
  uploading: false,
  saving: false,
  syncingFeishu: false,
  feishuModalOpen: false,
  pollTimer: null,
  forcePoll: false,
  tags: [],

  setActiveTab: (tab: 'local' | 'feishu' | 'defect' | 'case') => {
    set({ activeTab: tab, currentFolderId: null, page: 1, filterSearch: '', filterDocType: '', filterTags: [] });
    // 缺陷/用例 Tab 分别查询 kind=defect / kind=case，其余 Tab 回到普通文档
    get().setKindFilter(tab === 'defect' ? 'defect' : tab === 'case' ? 'case' : 'doc');
    if (tab === 'defect') {
      // 缺陷来自 TAPD，不使用目录树
      set({ folders: [] });
    } else {
      // 用例库使用 TAPD 目录（与本地目录同树混排）
      get().loadFolders();
    }
    get().loadDocuments();
  },

  setKindFilter: (v: 'doc' | 'defect' | 'case') => {
    set({ kindFilter: v, page: 1 });
  },

  setDefectProjectId: (id) => {
    set({ defectProjectId: id, page: 1 });
  },

  setCaseProjectId: (id) => {
    set({ caseProjectId: id, page: 1 });
  },

  setFeishuModalOpen: (v: boolean) => set({ feishuModalOpen: v }),

  loadDocuments: async (opts) => {
    try {
      const s = get();
      // 合并 opts 与当前 filter 状态
      const filterSearch = opts?.search !== undefined ? opts.search : s.filterSearch;
      const filterDocType = opts?.doc_type !== undefined ? opts.doc_type : s.filterDocType;
      const filterTags = opts?.tags !== undefined ? opts.tags : s.filterTags;
      const page = opts?.page ?? (opts?.resetPage ? 1 : s.page);
      const pageSize = opts?.page_size ?? s.pageSize;

      const { currentFolderId, activeTab, kindFilter, defectProjectId, caseProjectId } = get();
      // 用例库尚未选定项目时不查询，避免把其他项目的用例混进列表
      if (kindFilter === 'case' && caseProjectId == null) {
        set({ documents: [], docTotal: 0 });
        return;
      }
      const extra: Record<string, any> = {
        // 缺陷/用例数据来自 TAPD，source_type 与 local/feishu 不同，按 kind 查询时不再按来源过滤
        source_type: kindFilter === 'defect' || kindFilter === 'case' ? undefined : activeTab,
        kind: kindFilter,
        search: filterSearch || undefined,
        doc_type: filterDocType || undefined,
        tags: filterTags.length > 0 ? filterTags : undefined,
        page,
        page_size: pageSize,
      };
      if (currentFolderId !== null) {
        extra.folder_id = currentFolderId;
        // 浏览某个目录时，列表同时展示其所有子目录下的文档
        extra.include_subfolders = true;
      }
      const projectOverride =
        kindFilter === 'defect'
          ? { projectId: defectProjectId }
          : kindFilter === 'case'
            ? { projectId: caseProjectId }
            : undefined;
      const qs = projectQs(extra, projectOverride);
      const r = await fetch(`${BASE}${qs}`);
      const data = await r.json();
      const items: Document[] = data.items || [];
      set({
        documents: items,
        docTotal: data.total || 0,
        page: data.page || page,
        pageSize: data.page_size || pageSize,
        filterSearch,
        filterDocType,
        filterTags,
      });
      // 有非终态文档或处于强制轮询（如刚触发重新解析）则启动轮询
      if (get().forcePoll || items.some((d) => NON_TERMINAL.includes(d.status))) {
        get().startPolling();
      } else {
        get().stopPolling();
      }
    } catch {
      /* 静默 */
    }
  },

  loadFolders: async () => {
    try {
      const { activeTab, kindFilter, caseProjectId } = get();
      if (activeTab === 'defect' || kindFilter === 'defect') {
        set({ folders: [] });
        return;
      }
      // 用例库按项目加载 TAPD 目录（与本地目录同树混排）
      const isCase = kindFilter === 'case';
      // 项目未就绪时不请求：不带 project_id 会拿到全局（飞书）目录，导致用例全部显示未归属
      if (isCase && caseProjectId == null) {
        set({ folders: [] });
        return;
      }
      const qs = isCase
        ? projectQs({ source_type: 'tapd_case', kind: 'case' }, { projectId: caseProjectId })
        : projectQs({ source_type: activeTab });
      const r = await fetch(`${FOLDERS_BASE}${qs}`);
      if (r.ok) {
        const folders = await r.json();
        set({ folders });
      }
    } catch {
      /* 静默 */
    }
  },

  setCurrentFolderId: (folderId: number | null) => {
    set({ currentFolderId: folderId, page: 1 });
    get().loadDocuments({ page: 1 });
  },

  createFolder: async (name, parentId) => {
    const r = await fetch(FOLDERS_BASE, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name,
        parent_id: parentId ?? null,
      }),
    });
    if (!r.ok) throw new Error(await r.text());
    await get().loadFolders();
  },

  updateFolder: async (id: number, name?: string, parentId?: number | null) => {
    const body: Record<string, any> = {};
    if (name !== undefined) body.name = name;
    if (parentId !== undefined) body.parent_id = parentId;
    const r = await fetch(`${FOLDERS_BASE}/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error(await r.text());
    await get().loadFolders();
  },

  deleteFolder: async (id: number) => {
    const r = await fetch(`${FOLDERS_BASE}/${id}`, { method: 'DELETE' });
    if (!r.ok) throw new Error(await r.text());
    if (get().currentFolderId === id) {
      set({ currentFolderId: null });
    }
    await get().loadFolders();
    await get().loadDocuments();
  },

  moveDocument: async (docId: number, folderId: number | null) => {
    const r = await fetch(`${BASE}/${docId}/move`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ folder_id: folderId }),
    });
    if (!r.ok) throw new Error(await r.text());
    await get().loadDocuments();
    await get().loadFolders();
  },

  uploadDocument: async (file: File) => {
    set({ uploading: true });
    try {
      const { currentFolderId } = get();
      const extra: Record<string, any> = {};
      if (currentFolderId && currentFolderId > 0) {
        extra.folder_id = currentFolderId;
      }
      const qs = projectQs(extra);
      const fd = new FormData();
      fd.append('file', file);
      const r = await fetch(`${BASE}${qs}`, { method: 'POST', body: fd });
      if (!r.ok) {
        const msg = await r.text();
        throw new Error(msg);
      }
      await get().loadDocuments();
      await get().loadFolders();
    } finally {
      set({ uploading: false });
    }
  },

  deleteDocument: async (id: number) => {
    await fetch(`${BASE}/${id}`, { method: 'DELETE' });
    await get().loadDocuments();
    await get().loadFolders();
  },

  startPolling: () => {
    if (get().pollTimer) return;
    const t = window.setInterval(() => get().loadDocuments(), 2000);
    set({ pollTimer: t });
  },

  stopPolling: () => {
    const t = get().pollTimer;
    if (t) {
      window.clearInterval(t);
      set({ pollTimer: null });
    }
  },

  setForcePoll: (v: boolean) => {
    set({ forcePoll: v });
    if (v) get().startPolling();
    else if (!get().documents.some((d) => NON_TERMINAL.includes(d.status))) get().stopPolling();
  },

  // ===== KB 升级新增 =====

  fetchContent: async (id: number) => {
    const r = await fetch(`${BASE}/${id}/content`);
    if (!r.ok) throw new Error('加载内容失败');
    return r.json();
  },

  saveContent: async (id: number, text: string, note = '') => {
    set({ saving: true });
    try {
      const r = await fetch(`${BASE}/${id}/content`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, note }),
      });
      if (!r.ok) throw new Error('保存失败');
      await get().loadDocuments();
    } finally {
      set({ saving: false });
    }
  },

  saveBinaryFile: async (id: number, blob: Blob, filename: string, note = '在线编辑保存') => {
    set({ saving: true });
    try {
      const fd = new FormData();
      fd.append('file', blob, filename);
      fd.append('note', note);
      const r = await fetch(`${BASE}/${id}/file`, { method: 'PUT', body: fd });
      if (!r.ok) throw new Error('保存失败');
      await get().loadDocuments();
    } finally {
      set({ saving: false });
    }
  },

  updateMeta: async (id: number, meta) => {
    const r = await fetch(`${BASE}/${id}/meta`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(meta),
    });
    if (!r.ok) throw new Error('更新元数据失败');
    await get().loadDocuments();
    await get().loadTags();
  },

  loadTags: async () => {
    try {
      const qs = projectQs();
      const r = await fetch(`${BASE}/tags/all${qs}`);
      if (r.ok) set({ tags: await r.json() });
    } catch {
      /* 静默 */
    }
  },

  listVersions: async (id: number) => {
    const r = await fetch(`${BASE}/${id}/versions`);
    if (!r.ok) throw new Error('加载版本失败');
    return r.json();
  },

  getVersionContent: async (id: number, versionNo: number) => {
    const r = await fetch(`${BASE}/${id}/versions/${versionNo}/content`);
    if (!r.ok) throw new Error('加载版本内容失败');
    const data = await r.json();
    return data.text || '';
  },

  rollbackVersion: async (id: number, versionNo: number) => {
    const r = await fetch(`${BASE}/${id}/rollback/${versionNo}`, { method: 'POST' });
    if (!r.ok) throw new Error('回滚失败');
    await get().loadDocuments();
  },

  rawUrl: (id: number) => `${BASE}/${id}/raw`,

  exportZipUrl: () => `${BASE}/export/zip${projectQs()}`,

  // ===== 飞书主动同步 =====

  listFeishuSpaces: async () => {
    const r = await fetch('/api/modules/kb/feishu/spaces');
    if (!r.ok) {
      // 不再静默返回空数组：把后端原因透传给调用方，避免"列表为空"与"出错"混淆
      let msg = `HTTP ${r.status}`;
      try {
        const body = await r.json();
        msg = body?.detail || msg;
      } catch {
        /* 非 JSON 响应，保留状态码信息 */
      }
      throw new Error(msg);
    }
    const data = await r.json();
    return (data || []).map((s: any) => ({
      space_id: s.space_id || s.id,
      name: s.name || s.space_name || s.space_id,
      description: s.description || '',
    }));
  },

  syncFeishuSpace: async (spaceId: string) => {
    set({ syncingFeishu: true });
    try {
      const r = await fetch('/api/modules/kb/feishu/sync', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ space_id: spaceId }),
      });
      if (!r.ok) {
        const err = await r.text();
        throw new Error(err);
      }
      const data = await r.json();
      await get().loadFolders();
      await get().loadDocuments();
      return data;
    } finally {
      set({ syncingFeishu: false });
    }
  },
}));
