import { create } from 'zustand'

export interface Environment {
  id: number
  name: string
  base_url: string
  project_id?: number | null
  is_default: boolean
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
  updateEnv: (id: number, data: Partial<Environment>) => Promise<void>
}

// 统一复用 UI 自动化的环境接口
const BASE = '/api/modules/ui/automation/envs'

export const useEnvStore = create<EnvState>((set, get) => ({
  envs: [],
  loading: false,
  loadEnvs: async (projectId?: number | null) => {
    set({ loading: true })
    try {
      const url = projectId ? `${BASE}?project_id=${projectId}` : BASE
      const r = await fetch(url)
      set({ envs: await _jsonOrThrow(r) })
    } catch (e) {
      console.error('loadEnvs failed:', e)
      throw e
    } finally {
      set({ loading: false })
    }
  },
  updateEnv: async (id, data) => {
    const r = await fetch(`${BASE}/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    })
    await _jsonOrThrow(r)
    const currentProj = get().envs.find((e) => e.id === id)?.project_id
    await get().loadEnvs(currentProj)
  },
}))
