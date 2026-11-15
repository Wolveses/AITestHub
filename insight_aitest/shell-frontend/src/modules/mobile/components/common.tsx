import type { CSSProperties, MouseEvent, ReactNode } from 'react';

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
    primary: {
      background: 'var(--accent)',
      color: 'var(--text-on-accent)',
      border: 'none',
    },
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
      }}
    >
      {children}
    </button>
  );
}

const STATUS_STYLE: Record<string, { label: string; color: string }> = {
  not_implemented: { label: '未实现', color: 'var(--text-muted)' },
  generating: { label: '生成中', color: 'var(--info)' },
  implemented: { label: '已实现', color: 'var(--success)' },
  fixing: { label: '修复中', color: 'var(--warning)' },
  running: { label: '执行中', color: 'var(--info)' },
  passed: { label: '通过', color: 'var(--success)' },
  failed: { label: '失败', color: 'var(--error)' },
  error: { label: '异常', color: 'var(--error)' },
  cancelled: { label: '已取消', color: 'var(--text-muted)' },
  success: { label: '成功', color: 'var(--success)' },
};

export function StatusBadge({ status }: { status: string }) {
  const meta = STATUS_STYLE[status] || { label: status, color: 'var(--text-muted)' };
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
        background: 'var(--surface-tint)',
        border: `1px solid ${meta.color}`,
        whiteSpace: 'nowrap',
      }}
    >
      {meta.label}
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
  boxSizing: 'border-box',
  padding: '6px 10px',
  borderRadius: 6,
  border: '1px solid var(--border-strong)',
  background: 'var(--bg-card)',
  color: 'var(--text-primary)',
  fontSize: 13,
  outline: 'none',
};
