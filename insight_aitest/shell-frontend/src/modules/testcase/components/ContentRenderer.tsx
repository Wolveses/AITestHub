import { useTranslation } from 'react-i18next';

/** API/性能/UI 用例只读视图（首版预埋，待对应子系统就绪后激活编辑器）。 */
export function ContentRenderer({ type, content }: {
  type: string; content: Record<string, unknown>;
}) {
  const { t } = useTranslation();

  if (type === 'ui' && content && Array.isArray((content as any).steps)) {
    const steps = (content as any).steps as Array<{ kind?: string; action?: string; assert?: string; prompt?: string }>;
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, fontSize: 13 }}>
        {(content as any).base_url && (
          <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            Base URL: <span style={{ fontFamily: 'monospace', color: 'var(--text-primary)' }}>{String((content as any).base_url)}</span>
          </div>
        )}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {steps.map((st, idx) => (
            <div
              key={idx}
              style={{
                padding: '6px 10px',
                background: 'var(--bg-card)',
                border: '1px solid var(--border)',
                borderRadius: 6,
                display: 'flex',
                alignItems: 'center',
                gap: 8,
              }}
            >
              <span style={{ color: 'var(--accent)', fontWeight: 600, fontSize: 12 }}>#{idx + 1}</span>
              <span
                style={{
                  fontSize: 11,
                  padding: '1px 6px',
                  borderRadius: 4,
                  background: st.kind === 'assert' ? 'rgba(16,185,129,0.12)' : 'rgba(59,130,246,0.12)',
                  color: st.kind === 'assert' ? '#10b981' : '#3b82f6',
                  fontWeight: 600,
                }}
              >
                {st.kind === 'assert' ? '断言' : '操作'}
              </span>
              <span style={{ color: 'var(--text-primary)', flex: 1 }}>{st.action || st.assert || st.prompt || ''}</span>
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div style={{ padding: 12, background: 'var(--bg-base)', borderRadius: 6, color: "var(--text-secondary)", fontSize: 13 }}>
      <div style={{ marginBottom: 8, color: "var(--text-muted)" }}>
        {t('testcase.readonlyTypePreview', { type })}
      </div>
      <pre style={{ whiteSpace: 'pre-wrap', margin: 0, fontSize: 12, color: "var(--text-secondary)" }}>
        {JSON.stringify(content, null, 2)}
      </pre>
    </div>
  );
}
