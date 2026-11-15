import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { useEnvStore } from '../store/envStore'
import { useProjectStore } from '../../../shared/store/projectStore'

export function EnvironmentSelect({ value, onChange, style }: {
  value: number | null; onChange: (id: number | null) => void; style?: React.CSSProperties
}) {
  const { envs, loadEnvs, updateEnv } = useEnvStore()
  const currentProjectId = useProjectStore((s) => s.currentProjectId)
  const { t } = useTranslation()

  useEffect(() => {
    loadEnvs(currentProjectId)
  }, [loadEnvs, currentProjectId])

  // 当外部 value 为 null 时，若当前列表有环境，自动选择已启用的环境或首个环境
  useEffect(() => {
    if (value === null && envs.length > 0) {
      const active = envs.find((e) => e.is_default) || envs[0]
      onChange(active.id)
    }
  }, [envs, value, onChange])

  return (
    <select
      style={{ ...selectStyle, ...style }}
      value={value ?? (envs[0]?.id ? String(envs[0].id) : '')}
      onChange={(e) => {
        const newId = e.target.value ? Number(e.target.value) : null
        onChange(newId)
        if (newId) {
          // 切换环境后双向同步启用状态 (is_default: true)
          updateEnv(newId, { is_default: true }).catch(() => {})
        }
      }}
    >
      {envs.length === 0 && <option value="">{t('api.noEnvs', '暂无环境')}</option>}
      {envs.map((e) => (
        <option key={e.id} value={e.id}>
          {e.name}{e.is_default ? t('api.defaultEnv') : ''}
        </option>
      ))}
    </select>
  )
}

const selectStyle: React.CSSProperties = {
  background: "var(--bg-card)", border: '1px solid var(--bg-elevated)', borderRadius: 4,
  color: "var(--text-primary)", padding: '4px 8px', fontSize: 12,
}
