import { create } from 'zustand';
import { useProjectStore } from '../../../shared/store/projectStore';

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
  created_at: string;
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
  folders: FolderNode[];
  currentFolderId: number | null; // null 表示当前根目录（本地文档/飞书文档根目录），0 表示未分类
  activeTab: 'local' | 'feishu';
  uploading: boolean;
  saving: boolean;
  syncingFeishu: boolean;
  feishuModalOpen: boolean;
  pollTimer: number | null;
  tags: TagCount[];
  setActiveTab: (tab: 'local' | 'feishu') => void;
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

function projectQs(extraParams?: Record<string, any>): string {
  const { currentProjectId, currentVersionId } = useProjectStore.getState();
  const params = new URLSearchParams();
  if (currentProjectId !== null) params.set('project_id', String(currentProjectId));
  if (currentVersionId !== null) params.set('version_id', String(currentVersionId));
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
  folders: [],
  currentFolderId: null,
  activeTab: 'local',
  uploading: false,
  saving: false,
  syncingFeishu: false,
  feishuModalOpen: false,
  pollTimer: null,
  tags: [],

  setActiveTab: (tab: 'local' | 'feishu') => {
    set({ activeTab: tab, currentFolderId: null, page: 1, filterSearch: '', filterDocType: '', filterTags: [] });
    get().loadFolders();
    get().loadDocuments();
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

      const { currentFolderId, activeTab } = get();
      const extra: Record<string, any> = {
        source_type: activeTab,
        search: filterSearch || undefined,
        doc_type: filterDocType || undefined,
        tags: filterTags.length > 0 ? filterTags : undefined,
        page,
        page_size: pageSize,
      };
      if (currentFolderId !== null) {
        extra.folder_id = currentFolderId;
      }
      const qs = projectQs(extra);
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
      // 有非终态文档则启动轮询
      if (items.some((d) => NON_TERMINAL.includes(d.status))) {
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
      const { activeTab } = get();
      const qs = projectQs({ source_type: activeTab });
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

  createFolder: async (name: string, parentId?: number | null) => {
    const { currentProjectId } = useProjectStore.getState();
    const r = await fetch(FOLDERS_BASE, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name,
        parent_id: parentId ?? null,
        project_id: currentProjectId ?? null,
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
      const { currentProjectId } = useProjectStore.getState();
      const r = await fetch('/api/modules/kb/feishu/sync', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ space_id: spaceId, project_id: currentProjectId }),
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
