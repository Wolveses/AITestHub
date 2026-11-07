import { create } from 'zustand';

export interface PerfScriptItem {
  id: number;
  project_id: number;
  name: string;
  description: string;
  plan_description: string;
  config: any;
  asset_ids: number[];
  created_at: string;
  updated_at: string;
}

export interface PerfTaskItem {
  id: number;
  project_id: number;
  name: string;
  description: string;
  strategy_type: 'duration' | 'loops';
  duration_seconds: number;
  loop_count: number;
  concurrency: number;
  ramp_up_seconds: number;
  engine_type: 'builtin' | 'jmeter_cli';
  last_status: string;
  last_run_at: string | null;
  last_run_id: number | null;
  script_count: number;
  scripts?: any[];
}

export interface PerfRunItem {
  id: number;
  task_id: number;
  project_id: number;
  status: string;
  engine_used: string;
  concurrency: number;
  total_samples: number;
  failed_samples: number;
  error_rate: number;
  avg_tps: number;
  avg_rt_ms: number;
  p90_rt_ms: number;
  p95_rt_ms: number;
  p99_rt_ms: number;
  started_at: string;
  ended_at: string | null;
  error_message: string | null;
  timeline_metrics?: any[];
  sampler_summary?: any[];
}

interface ServerPerfStore {
  scripts: PerfScriptItem[];
  tasks: PerfTaskItem[];
  runs: PerfRunItem[];
  loading: boolean;
  loadScripts: (projectId: number) => Promise<void>;
  loadTasks: (projectId: number) => Promise<void>;
  loadRuns: (projectId: number, taskId?: number) => Promise<void>;
}

export const useServerPerfStore = create<ServerPerfStore>((set) => ({
  scripts: [],
  tasks: [],
  runs: [],
  loading: false,

  loadScripts: async (projectId: number) => {
    set({ loading: true });
    try {
      const res = await fetch(`/api/modules/performance/server/scripts?project_id=${projectId}&page_size=100`);
      const data = await res.json();
      set({ scripts: data.items || [] });
    } finally {
      set({ loading: false });
    }
  },

  loadTasks: async (projectId: number) => {
    set({ loading: true });
    try {
      const res = await fetch(`/api/modules/performance/server/tasks?project_id=${projectId}&page_size=100`);
      const data = await res.json();
      set({ tasks: data.items || [] });
    } finally {
      set({ loading: false });
    }
  },

  loadRuns: async (projectId: number, taskId?: number) => {
    set({ loading: true });
    try {
      let url = `/api/modules/performance/server/runs?project_id=${projectId}&page_size=50`;
      if (taskId) url += `&task_id=${taskId}`;
      const res = await fetch(url);
      const data = await res.json();
      set({ runs: data.items || [] });
    } finally {
      set({ loading: false });
    }
  },
}));
