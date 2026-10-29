import { create } from 'zustand';

export interface Project {
  id: number;
  name: string;
  description: string;
  color: string;
  version_count: number;
  created_at: string;
  updated_at: string;
}

export interface ProjectVersion {
  id: number;
  project_id: number;
  name: string;
  description: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

interface ProjectState {
  projects: Project[];
  versions: ProjectVersion[];          // 当前选中项目的版本列表
  currentProjectId: number | null;     // null = 全部
  currentVersionId: number | null;     // null = 项目下全部
  loadProjects: () => Promise<void>;
  loadVersions: (projectId: number) => Promise<void>;
  setProject: (projectId: number | null) => void;
  setVersion: (versionId: number | null) => void;
}

const BASE = '/api/platform';

// 项目/版本选择做前端记忆：刷新后恢复上次选择，而不是回落到第一个项目
const LS_PROJECT = 'insight.projectId';
const LS_VERSION = 'insight.versionId';

function readStoredId(key: string): number | null {
  const raw = localStorage.getItem(key);
  if (!raw) return null;
  const n = Number(raw);
  return Number.isFinite(n) ? n : null;
}

function writeStoredId(key: string, value: number | null): void {
  if (value === null) localStorage.removeItem(key);
  else localStorage.setItem(key, String(value));
}

export const useProjectStore = create<ProjectState>((set, get) => ({
  projects: [],
  versions: [],
  currentProjectId: readStoredId(LS_PROJECT),
  currentVersionId: readStoredId(LS_VERSION),

  loadProjects: async () => {
    try {
      const r = await fetch(`${BASE}/projects`);
      if (!r.ok) return;
      const data = await r.json();
      const projects: Project[] = Array.isArray(data) ? data : [];
      const current = get().currentProjectId;
      // 记住的项目已被删除时清空，避免下拉框显示不存在的项目
      if (current !== null && !projects.some((p) => p.id === current)) {
        writeStoredId(LS_PROJECT, null);
        writeStoredId(LS_VERSION, null);
        set({ projects, currentProjectId: null, currentVersionId: null, versions: [] });
        return;
      }
      set({ projects });
      if (current !== null) get().loadVersions(current);
    } catch {
      /* 静默（后端未启动时不阻塞前端渲染） */
    }
  },

  loadVersions: async (projectId: number) => {
    try {
      const r = await fetch(`${BASE}/projects/${projectId}/versions`);
      if (!r.ok) return;
      const data = await r.json();
      const versions: ProjectVersion[] = Array.isArray(data) ? data : [];
      set({ versions });
      const current = get().currentVersionId;
      if (current !== null && !versions.some((v) => v.id === current)) {
        writeStoredId(LS_VERSION, null);
        set({ currentVersionId: null });
      }
    } catch {
      set({ versions: [] });
    }
  },

  setProject: (projectId: number | null) => {
    writeStoredId(LS_PROJECT, projectId);
    writeStoredId(LS_VERSION, null);
    set({ currentProjectId: projectId, currentVersionId: null, versions: [] });
    if (projectId !== null) {
      get().loadVersions(projectId);
    }
  },

  setVersion: (versionId: number | null) => {
    writeStoredId(LS_VERSION, versionId);
    set({ currentVersionId: versionId });
  },
}));
