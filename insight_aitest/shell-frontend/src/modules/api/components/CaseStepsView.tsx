import { useTranslation } from 'react-i18next';
import type { ApiCase, ApiStep } from '../store/runStore';

const METHOD_COLORS: Record<string, string> = {
  GET: '#3b82f6',
  POST: '#16a34a',
  PUT: '#d97706',
  PATCH: '#a855f7',
  DELETE: '#dc2626',
};

function methodColor(method: string) {
  return METHOD_COLORS[(method || '').toUpperCase()] || 'var(--text-secondary)';
}

function pretty(value: unknown): string {
  if (value == null || value === '') return '';
  if (typeof value === 'string') {
    try {
      return JSON.stringify(JSON.parse(value), null, 2);
    } catch {
      return value;
    }
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

const sectionLabel: React.CSSProperties = {
  fontSize: 12,
  color: 'var(--text-muted)',
  marginTop: 10,
  marginBottom: 4,
};

const codeBox: React.CSSProperties = {
  background: 'var(--bg-base)',
  border: '1px solid var(--bg-card)',
  borderRadius: 4,
  padding: '6px 8px',
  fontSize: 13,
  fontFamily: 'monospace',
  whiteSpace: 'pre-wrap',
  wordBreak: 'break-all',
  maxHeight: 220,
  overflow: 'auto',
  color: 'var(--text-secondary)',
};

/** 用例步骤详情（只读）：展示每一步的接口、请求参数、断言与依赖提取。 */
export function CaseStepsView({ caseItem }: { caseItem: ApiCase | null }) {
  const { t } = useTranslation();
  if (!caseItem) {
    return (
      <div style={{ padding: 24, fontSize: 14, color: 'var(--text-muted)' }}>{t('api.selectCase')}</div>
    );
  }
  const steps = (caseItem.content?.steps || []) as ApiStep[];
  const baseUrl = caseItem.content?.base_url || '';

  return (
    <div style={{ padding: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 15, fontWeight: 600, color: 'var(--text-primary)' }}>{t('api.caseStepsTitle')}</span>
        <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{steps.length}</span>
        {baseUrl && (
          <span style={{ fontSize: 12, color: 'var(--text-muted)', fontFamily: 'monospace' }}>{baseUrl}</span>
        )}
      </div>

      {steps.length === 0 && (
        <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>{t('api.noStepsInCase')}</div>
      )}

      {steps.map((step, index) => {
        const headers = Object.entries(step.headers || {});
        const assertions = step.assertions || [];
        const extract = Object.entries(step.extract || {});
        return (
          <div
            key={index}
            style={{
              border: '1px solid var(--bg-card)',
              borderRadius: 6,
              padding: 12,
              marginBottom: 10,
              background: 'var(--bg-primary)',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <span style={{ fontSize: 13, color: 'var(--accent)', width: 20, flexShrink: 0 }}>{index + 1}</span>
              <span style={{
                fontSize: 12, fontWeight: 600, color: methodColor(step.method), width: 56, flexShrink: 0,
              }}>
                {step.method}
              </span>
              <span style={{ fontSize: 14, color: 'var(--text-primary)', fontWeight: 500 }}>
                {step.name || `${step.method} ${step.path}`}
              </span>
            </div>
            <div style={{ fontSize: 13, fontFamily: 'monospace', color: 'var(--text-secondary)', marginTop: 4, wordBreak: 'break-all' }}>
              {step.path}
            </div>

            {headers.length > 0 && (
              <>
                <div style={sectionLabel}>Headers</div>
                <div style={codeBox}>{pretty(Object.fromEntries(headers))}</div>
              </>
            )}
            {step.body != null && step.body !== '' && (
              <>
                <div style={sectionLabel}>Body</div>
                <div style={codeBox}>{pretty(step.body)}</div>
              </>
            )}
            {extract.length > 0 && (
              <>
                <div style={sectionLabel}>{t('api.extractLabel')}</div>
                <div style={codeBox}>
                  {extract.map(([name, path]) => `${name} ← ${path}`).join('\n')}
                </div>
              </>
            )}
            {assertions.length > 0 && (
              <>
                <div style={sectionLabel}>{t('api.assertionsShort')}</div>
                <div style={codeBox}>
                  {assertions
                    .map((a) => (a.path ? `${a.type} ${a.path} = ${String(a.expected)}` : `${a.type} = ${String(a.expected)}`))
                    .join('\n')}
                </div>
              </>
            )}
          </div>
        );
      })}
    </div>
  );
}
