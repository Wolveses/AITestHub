import { create } from 'zustand'

export interface Environment {
  id: number; name: string; base_url: string
  project_id?: number | null
  variables: Record<string, string>; is_default: boolean
  variables_meta?: Record<string, string>
}

async function _jsonOrThrow(r: Response) {
  if (!r.ok) {
    const msg = await r.text().catch(() => r.statusText)
    throw new Error(`API ${r.status}: ${msg}`)
  }
  return r.json()
}

interface EnvState {
  envs: Environment[]
  loading: boolean
  loadEnvs: (projectId?: number | null) => Promise<void>
  createEnv: (data: { name: string; base_url: string; project_id?: number | null; variables?: Record<string,string>; is_default?: boolean }) => Promise<void>
  updateEnv: (id: number, data: Partial<Environment>) => Promise<void>
  deleteEnv: (id: number) => Promise<void>
}

const BASE = '/api/modules/api/environments'

export const useEnvStore = create<EnvState>((set, get) => ({
  envs: [], loading: false,
  loadEnvs: async (projectId?: number | null) => {
    set({ loading: true })
    try {
      const url = projectId ? `${BASE}?project_id=${projectId}` : BASE
      const r = await fetch(url)
      set({ envs: await _jsonOrThrow(r) })
    }
    catch (e) { console.error('loadEnvs failed:', e); throw e }
    finally { set({ loading: false }) }
  },
  createEnv: async (data) => {
    const r = await fetch(BASE, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(data) })
    await _jsonOrThrow(r)
    await get().loadEnvs(data.project_id)
  },
  updateEnv: async (id, data) => {
    const r = await fetch(`${BASE}/${id}`, { method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify(data) })
    await _jsonOrThrow(r)
    const currentProj = get().envs.find((e) => e.id === id)?.project_id
    await get().loadEnvs(currentProj)
  },
  deleteEnv: async (id) => {
    const currentProj = get().envs.find((e) => e.id === id)?.project_id
    const r = await fetch(`${BASE}/${id}`, { method: 'DELETE' })
    if (!r.ok) throw new Error(`删除环境失败: ${r.status}`)
    await get().loadEnvs(currentProj)
  },
}))
