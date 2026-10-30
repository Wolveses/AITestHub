import type { CSSProperties, MouseEvent, ReactNode } from 'react';

/** 自动化页通用小部件（内联样式 + CSS 变量，与项目其它页面保持一致）。 */

export type BtnVariant = 'default' | 'primary' | 'danger' | 'ghost';

export function Btn({
  children,
  onClick,
  disabled,
  variant = 'default',
  title,
  size = 'md',
  style,
}: {
  children: ReactNode;
  onClick?: (e: MouseEvent) => void;
  disabled?: boolean;
  variant?: BtnVariant;
  title?: string;
  size?: 'sm' | 'md';
  style?: CSSProperties;
}) {
  const palette: Record<BtnVariant, CSSProperties> = {
    default: {
      background: 'var(--bg-card)',
      color: 'var(--text-primary)',
      border: '1px solid var(--border-strong)',
    },
    primary: { background: 'var(--accent)', color: '#fff', border: 'none' },
    danger: {
      background: 'transparent',
      color: 'var(--error)',
      border: '1px solid var(--error)',
    },
    ghost: {
      background: 'transparent',
      color: 'var(--text-muted)',
      border: '1px solid transparent',
    },
  };
  return (
    <button
      title={title}
      onClick={onClick}
      disabled={disabled}
      style={{
        ...palette[variant],
        ...style,
        display: 'inline-flex',
        alignItems: 'center',
        gap: 5,
        padding: size === 'sm' ? '3px 9px' : '6px 12px',
        borderRadius: 6,
        fontSize: size === 'sm' ? 12 : 13,
        fontWeight: 500,
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.45 : 1,
        whiteSpace: 'nowrap',
        transition: 'opacity .15s ease',
      }}
    >
      {children}
    </button>
  );
}

export const STATUS_META: Record<string, { labelKey: string; color: string; bg: string }> = {
  not_implemented: { labelKey: 'ui.auto.statusNotImplemented', color: 'var(--text-muted)', bg: 'var(--bg-card)' },
  generating: { labelKey: 'ui.auto.statusGenerating', color: 'var(--info, #3b82f6)', bg: 'rgba(59,130,246,.12)' },
  implemented: { labelKey: 'ui.auto.statusImplemented', color: 'var(--success, #10b981)', bg: 'rgba(16,185,129,.12)' },
  fixing: { labelKey: 'ui.auto.statusFixing', color: 'var(--warning, #f59e0b)', bg: 'rgba(245,158,11,.12)' },
  running: { labelKey: 'ui.auto.statusRunning', color: 'var(--info, #3b82f6)', bg: 'rgba(59,130,246,.12)' },
};

export function StatusBadge({ status, label }: { status: string; label: string }) {
  const meta = STATUS_META[status] || STATUS_META.not_implemented;
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
        padding: '2px 8px',
        borderRadius: 999,
        fontSize: 11,
        color: meta.color,
        background: meta.bg,
        border: `1px solid ${meta.color}`,
        whiteSpace: 'nowrap',
      }}
    >
      {(status === 'generating' || status === 'fixing' || status === 'running') && (
        <span
          style={{
            width: 6,
            height: 6,
            borderRadius: '50%',
            background: meta.color,
            animation: 'pulse 1.2s ease-in-out infinite',
          }}
        />
      )}
      {label}
    </span>
  );
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 5, fontSize: 12 }}>
      <span style={{ color: 'var(--text-muted)' }}>{label}</span>
      {children}
      {hint && <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>{hint}</span>}
    </label>
  );
}

export const inputStyle: CSSProperties = {
  width: '100%',
  padding: '6px 9px',
  borderRadius: 6,
  border: '1px solid var(--border-strong)',
  background: 'var(--bg-base)',
  color: 'var(--text-primary)',
  fontSize: 12,
  outline: 'none',
  boxSizing: 'border-box',
};

export function ErrorCategoryTag({
  category,
  label,
}: {
  category: string | null;
  label: string;
}) {
  if (!category) return null;
  const color =
    category === 'environment'
      ? 'var(--warning, #f59e0b)'
      : category === 'case_info'
        ? 'var(--info, #3b82f6)'
        : category === 'model'
          ? 'var(--chart-4, #a855f7)'
          : 'var(--error)';
  return (
    <span style={{ fontSize: 11, color, border: `1px solid ${color}`, borderRadius: 4, padding: '1px 6px' }}>
      {label}
    </span>
  );
}
