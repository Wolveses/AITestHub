import { create } from 'zustand'

/** 接口资产（UI 自动化生成期首跑抓包自动写入）。 */
export interface ApiAsset {
  id: number
  project_id: number | null
  title: string
  method: string
  path: string
  path_template: string
  base_url: string
  headers: Record<string, string>
  body: unknown
  response_status: number
  response_headers: Record<string, string>
  response_body: unknown
  response_content_type: string
  body_truncated: boolean
  fingerprint: string
  times_seen: number
  source: string
  source_case_id: number | null
  tags: string[]
  is_noise: boolean
  ai_meta: AiMeta | null
  jsonpath_samples: JsonPathSample[]
  first_seen_at: string
  last_seen_at: string
}

export interface AiMeta {
  title?: string
  summary?: string
  is_noise?: boolean
  noise_reason?: string
  path_template?: string
  variables?: { name: string; description?: string }[]
  model?: string
}

export interface JsonPathSample {
  path: string
  type: string
  sample: unknown
}

export interface EnhanceProgress {
  status: 'idle' | 'running' | 'done'
  total: number
  done: number
  failed: number
  pending_ids: number[]
  done_ids: number[]
  failed_ids: number[]
  started_at: string | null
  finished_at: string | null
}

export async function fetchEnhanceProgress(projectId: number | null): Promise<EnhanceProgress> {
  const qs = projectId != null ? `?project_id=${projectId}` : ''
  return _jsonOrThrow(await fetch(`${BASE}/enhance-progress${qs}`))
}

export interface AssetQuery {
  project_id?: number | null
  method?: string
  keyword?: string
  hide_noise?: boolean
  page?: number
  page_size?: number
}

async function _jsonOrThrow(r: Response) {
  if (!r.ok) {
    const msg = await r.text().catch(() => r.statusText)
    throw new Error(`API ${r.status}: ${msg}`)
  }
  return r.json()
}

const BASE = '/api/modules/api/assets'

// 只应用最后一次请求结果，避免快速切换筛选时旧响应覆盖新结果
let _loadSeq = 0

interface AssetState {
  items: ApiAsset[]
  total: number
  page: number
  pageSize: number
  loading: boolean
  selectedId: number | null
  checkedIds: number[]
  lastQuery: AssetQuery
  loadAssets: (q: AssetQuery) => Promise<void>
  selectAsset: (id: number | null) => Promise<void>
  toggleCheck: (id: number) => void
  setChecked: (ids: number[]) => void
  deleteChecked: () => Promise<number>
  updateAsset: (id: number, data: Partial<Pick<ApiAsset, 'title' | 'tags' | 'is_noise' | 'path_template'>> & { ai_meta?: AiMeta }) => Promise<void>
  deleteAsset: (id: number) => Promise<void>
  enhanceAsset: (id: number) => Promise<AiMeta>
  toCase: (id: number) => Promise<number>
}

export const useAssetStore = create<AssetState>((set, get) => ({
  items: [],
  total: 0,
  page: 1,
  pageSize: 20,
  loading: false,
  selectedId: null,
  checkedIds: [],
  lastQuery: {},
  loadAssets: async (q) => {
    set({ loading: true, lastQuery: q })
    const seq = ++_loadSeq
    try {
      const params = new URLSearchParams()
      if (q.project_id != null) params.set('project_id', String(q.project_id))
      if (q.method) params.set('method', q.method)
      if (q.keyword) params.set('keyword', q.keyword)
      if (q.hide_noise) params.set('hide_noise', 'true')
      params.set('page', String(q.page ?? 1))
      params.set('page_size', String(q.page_size ?? 20))
      const data = await _jsonOrThrow(await fetch(`${BASE}?${params.toString()}`))
      if (seq !== _loadSeq) return
      set({
        items: data.items ?? [],
        total: data.total ?? 0,
        page: data.page ?? 1,
        pageSize: data.page_size ?? 20,
      })
    } catch (e) {
      console.error('loadAssets failed:', e)
      throw e
    } finally {
      set({ loading: false })
    }
  },
  selectAsset: async (id) => {
    if (id == null) {
      set({ selectedId: null })
      return
    }
    // 立即标记选中，详情请求完成后再补全数据
    set({ selectedId: id })
    const data = await _jsonOrThrow(await fetch(`${BASE}/${id}`))
    set((s) => ({ items: s.items.map((it) => (it.id === id ? data : it)) }))
  },
  updateAsset: async (id, data) => {
    const next = await _jsonOrThrow(
      await fetch(`${BASE}/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      }),
    )
    set((s) => ({ items: s.items.map((it) => (it.id === id ? next : it)) }))
  },
  toggleCheck: (id) => {
    set((s) => ({
      checkedIds: s.checkedIds.includes(id)
        ? s.checkedIds.filter((x) => x !== id)
        : [...s.checkedIds, id],
    }))
  },
  setChecked: (ids) => set({ checkedIds: ids }),
  deleteChecked: async () => {
    const ids = get().checkedIds
    if (ids.length === 0) return 0
    const res = await _jsonOrThrow(
      await fetch(`${BASE}/batch-delete`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids }),
      }),
    )
    set((s) => ({
      checkedIds: [],
      selectedId: s.selectedId != null && ids.includes(s.selectedId) ? null : s.selectedId,
    }))
    await get().loadAssets(get().lastQuery)
    return Number(res.deleted) || 0
  },
  deleteAsset: async (id) => {
    const r = await fetch(`${BASE}/${id}`, { method: 'DELETE' })
    if (!r.ok) throw new Error(`删除接口资产失败: ${r.status}`)
    set((s) => ({
      items: s.items.filter((it) => it.id !== id),
      total: Math.max(0, s.total - 1),
      selectedId: s.selectedId === id ? null : s.selectedId,
    }))
  },
  enhanceAsset: async (id) => {
    const data = await _jsonOrThrow(await fetch(`${BASE}/${id}/enhance`, { method: 'POST' }))
    return data as AiMeta
  },
  toCase: async (id) => {
    const data = await _jsonOrThrow(await fetch(`${BASE}/${id}/to-case`, { method: 'POST' }))
    return data.case_id as number
  },
}))
