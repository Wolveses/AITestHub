import { useTranslation } from 'react-i18next'
import type { SuiteRunDetail } from '../../store/suiteStore'

interface CaseRunSummary {
  id: number; status: string; case_title: string
  passed_steps: number; total_steps: number
}

export function SuiteRunDetail({ run, caseRuns }: {
  run: SuiteRunDetail | null
  caseRuns: CaseRunSummary[]
}) {
  const { t } = useTranslation()
  if (!run) return <div style={{ padding: 24, color: 'var(--text-muted)', fontSize: 13 }}>{t('api.selectRunRecord')}</div>
  const color = run.status === 'completed' ? "var(--success)" : run.status === 'failed' ? "var(--error)" : run.status === 'interrupted' ? 'var(--chart-3)' : "var(--accent)"
  const statusLabel = (s: string | null | undefined) => {
    if (!s) return t('api.setupNone')
    if (s === 'completed' || s === 'passed') return t('api.passed', '通过')
    if (s === 'failed') return t('api.failed', '失败')
    if (s === 'running') return t('api.executing', '执行中')
    if (s === 'interrupted') return t('api.abnormal', '已中断')
    return s
  }

  return (
    <div style={{ padding: 16, overflow: 'auto', color: "var(--text-primary)" }}>
      <div style={{ fontSize: 13, color, marginBottom: 8, display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
        <span>{statusLabel(run.status)} · {run.done}/{run.total} · 前置步骤: {statusLabel(run.setup_status)}</span>
        {run.case_run_ids.length > 0 && (
          <div style={{ display: 'flex', gap: 6 }}>
            <a href={`/api/modules/api/suites/runs/${run.id}/report.html`} target="_blank" rel="noreferrer"
              style={reportBtnStyle}>
              {t('api.suiteReport')}
            </a>
            <a href={`/api/modules/api/suites/runs/${run.id}/report.junit.xml`} download
              style={{ ...reportBtnStyle, color: 'var(--chart-3)', borderColor: 'color-mix(in srgb, var(--chart-3) 30%, transparent)' }}>
              导出 XML
            </a>
          </div>
        )}
      </div>
      {run.error && <div style={{ color: 'var(--chart-3)', fontSize: 12, marginBottom: 8 }}>{run.error}</div>}
      {caseRuns.length > 0 && (
        <div>
          {caseRuns.map((cr) => (
            <div key={cr.id} style={{ padding: 8, marginBottom: 6, border: '1px solid var(--bg-card)', borderRadius: 6, background: 'var(--bg-base)', display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{
                display: 'inline-block', width: 8, height: 8, borderRadius: '50%',
                background: cr.status === 'passed' ? 'var(--success)' : 'var(--error)',
              }} />
              <span style={{ color: "var(--text-secondary)", fontSize: 12, flex: 1 }}>{cr.case_title}</span>
              <span style={{ color: cr.status === 'passed' ? 'var(--success)' : 'var(--error)', fontSize: 11 }}>{statusLabel(cr.status)}</span>
              <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>{t('api.stepsPassed', { passed: cr.passed_steps, total: cr.total_steps })}</span>
              <a href={`/api/modules/api/runs/${cr.id}/report.html`} target="_blank" rel="noreferrer"
                style={{ fontSize: 11, color: 'var(--accent)', textDecoration: 'none' }}>
                {t('api.detail')}
              </a>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

const reportBtnStyle: React.CSSProperties = {
  fontSize: 12, padding: '4px 10px', background: "var(--bg-card)", color: "var(--accent)",
  border: '1px solid color-mix(in srgb, var(--accent) 30%, transparent)', borderRadius: 4,
  cursor: 'pointer', textDecoration: 'none', display: 'inline-flex',
}
