import { useEffect, useRef, useState } from 'react'
import { Play, Pencil, Trash2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { useSuiteStore } from '../../store/suiteStore'
import { useRunStore } from '../../store/runStore'
import { useEnvStore } from '../../store/envStore'
import { useConfirmStore } from '../../../../shared/store/confirmStore'
import { EnvironmentSelect } from '../EnvironmentSelect'
import { SuiteEditor } from './SuiteEditor'
import { SuiteRunList } from './SuiteRunList'
import { SuiteRunDetail } from './SuiteRunDetail'
import type { RunDetail } from '../../store/runStore'

export function SuitePanel({ suiteId, onNew }: { suiteId: number | null; onNew: () => void }) {
  const { suites, runs, selectedRun, executing, loadSuites,
          createSuite, updateSuite, deleteSuite, selectSuite, executeSuite, loadRunDetail } = useSuiteStore()
  const { cases, loadCases } = useRunStore()
  const envs = useEnvStore((s) => s.envs)
  const confirm = useConfirmStore((s) => s.confirm)
  const { t } = useTranslation()
  const [editing, setEditing] = useState(false)
  const [envId, setEnvId] = useState<number | null>(null)
  const [caseRuns, setCaseRuns] = useState<CaseRunSummary[]>([])

  useEffect(() => {
    if (envId === null && envs.length > 0) {
      const def = envs.find((e) => e.is_default) || envs[0]
      if (def) setEnvId(def.id)
    }
  }, [envs, envId])

  // 轮询 interval ref（防泄漏）
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => { loadCases(); loadSuites() }, [loadCases, loadSuites])

  // 组件卸载或切换套件时清理轮询
  const clearPoll = () => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
  }
  useEffect(() => () => clearPoll(), [])

  const suite = suites.find((s) => s.id === suiteId)

  // 选中 run 变化时重置子 run 列表（渲染期调整模式）
  const prevRunKey = selectedRun?.id ?? 0
  const [syncedRunKey, setSyncedRunKey] = useState(prevRunKey)
  if (prevRunKey !== syncedRunKey) {
    setSyncedRunKey(prevRunKey)
    setCaseRuns([])
  }

  // 并行 fetch 子 run 详情 → caseRuns（setCaseRuns 全部发生在异步回调中）
  useEffect(() => {
    if (!selectedRun || selectedRun.case_run_ids.length === 0) return
    let cancelled = false
    Promise.all(
      selectedRun.case_run_ids.map((id) =>
        fetch(`/api/modules/api/runs/${id}`).then((r) => (r.ok ? r.json() : null)).catch(() => null)
      )
    ).then((results) => {
      if (cancelled) return
      setCaseRuns(results.filter((r): r is RunDetail => r != null).map((r) => ({
        id: r.id, status: r.status, case_title: r.case_title,
        passed_steps: r.passed_steps, total_steps: r.total_steps,
      })))
    })
    return () => { cancelled = true }
  }, [selectedRun])

  const doExecute = async () => {
    if (!suiteId) return
    clearPoll()
    try {
      const srid = await executeSuite(suiteId, envId)
      await loadRunDetail(srid)
      // 轮询（带泄漏防护）
      pollRef.current = setInterval(async () => {
        await loadRunDetail(srid)
        const cur = useSuiteStore.getState().selectedRun
        if (cur && cur.status !== 'running') clearPoll()
      }, 1500)
    } catch (e) {
      toast.error(String(e))
    }
  }

  const removeSuite = () => {
    if (!suite) return
    confirm({
      title: t('api.confirmDelete', '确认删除'),
      message: `${t('common.delete', '删除')} "${suite.name}"？`,
      variant: 'danger',
      onConfirm: () => {
        deleteSuite(suite.id)
          .then(() => {
            selectSuite(null)
            toast.success(t('common.delete'))
          })
          .catch((e) => toast.error(String(e)))
      },
    })
  }

  if (editing || !suiteId) {
    return (
      <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
        <SuiteEditor
          initial={suite ? { name: suite.name, description: suite.description, case_ids: suite.case_ids, setup: suite.setup, teardown: suite.teardown } : null}
          cases={cases}
          onSave={async (data) => {
            if (suiteId) await updateSuite(suiteId, data)
            else await createSuite(data)
            setEditing(false)
            onNew()
          }}
          onCancel={() => {
            setEditing(false)
            if (!suiteId) onNew()
          }} />
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ padding: '8px 16px', borderBottom: '1px solid var(--bg-card)', display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)", flex: 1, minWidth: 120 }}>{suite?.name ?? t('api.suite')}</span>
        <EnvironmentSelect value={envId} onChange={setEnvId} />
        <button onClick={doExecute} disabled={executing} style={{ ...primaryBtn, display: 'inline-flex', alignItems: 'center', gap: 4 }}>
          {executing ? t('api.executing') : <><Play size={12} strokeWidth={1.5} /> {t('api.runSuiteBtn')}</>}
        </button>
        <button onClick={() => setEditing(true)} style={{ ...secondaryBtn, display: 'inline-flex', alignItems: 'center', gap: 4 }}>
          <Pencil size={12} strokeWidth={1.5} /> {t('api.editBtn')}
        </button>
        <button onClick={removeSuite} style={{ ...secondaryBtn, color: 'var(--error)', display: 'inline-flex', alignItems: 'center', gap: 4 }}>
          <Trash2 size={12} strokeWidth={1.5} /> {t('common.delete')}
        </button>
      </div>
      <div style={{ height: 200, borderBottom: '1px solid var(--bg-card)' }}>
        <SuiteRunList runs={runs} selectedRunId={selectedRun?.id ?? null} onSelect={loadRunDetail} />
      </div>
      <div style={{ flex: 1, overflow: 'auto' }}>
        <SuiteRunDetail run={selectedRun} caseRuns={caseRuns} />
      </div>
    </div>
  )
}

interface CaseRunSummary {
  id: number; status: string; case_title: string
  passed_steps: number; total_steps: number
}

const primaryBtn: React.CSSProperties = { background: "var(--accent)", color: "var(--bg-base)", border: 'none', borderRadius: 4, padding: '4px 12px', cursor: 'pointer', fontSize: 12, fontWeight: 600 }
const secondaryBtn: React.CSSProperties = { background: "var(--bg-card)", border: '1px solid var(--bg-elevated)', color: "var(--text-secondary)", borderRadius: 4, padding: '4px 12px', cursor: 'pointer', fontSize: 12 }
