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
      color: 'var(--text-on-accent, #fff)',
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
        transition: 'opacity .15s ease',
      }}
    >
      {children}
    </button>
  );
}

export const STATUS_META: Record<string, { label: string; color: string; bg: string }> = {
  not_implemented: { label: '未实现', color: 'var(--text-muted)', bg: 'var(--bg-card)' },
  generating: { label: '生成中', color: 'var(--info, #3b82f6)', bg: 'rgba(59,130,246,.12)' },
  implemented: { label: '已实现', color: 'var(--success, #10b981)', bg: 'rgba(16,185,129,.12)' },
  fixing: { label: '修复中', color: 'var(--warning, #f59e0b)', bg: 'rgba(245,158,11,.12)' },
  running: { label: '执行中', color: 'var(--info, #3b82f6)', bg: 'rgba(59,130,246,.12)' },
  passed: { label: '通过', color: 'var(--success, #10b981)', bg: 'rgba(16,185,129,.12)' },
  failed: { label: '失败', color: 'var(--error, #ef4444)', bg: 'rgba(239,68,68,.12)' },
  error: { label: '异常', color: 'var(--error, #ef4444)', bg: 'rgba(239,68,68,.12)' },
  cancelled: { label: '已取消', color: 'var(--text-muted)', bg: 'var(--bg-card)' },
  success: { label: '成功', color: 'var(--success, #10b981)', bg: 'rgba(16,185,129,.12)' },
};

export function StatusBadge({ status, label }: { status: string; label?: string }) {
  const meta = STATUS_META[status] || { label: status, color: 'var(--text-muted)', bg: 'var(--bg-card)' };
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
      {label ?? meta.label}
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
  padding: '6px 9px',
  borderRadius: 6,
  border: '1px solid var(--border-strong)',
  background: 'var(--bg-base)',
  color: 'var(--text-primary)',
  fontSize: 12,
  outline: 'none',
};

export function ErrorCategoryTag({
  category,
  label,
}: {
  category: string | null;
  label?: string;
}) {
  if (!category) return null;
  const fallback: Record<string, string> = {
    environment: '环境问题',
    case_info: '用例信息不完善',
    model: '模型问题',
    script: '脚本缺陷',
  };
  const color =
    category === 'environment'
      ? 'var(--warning, #f59e0b)'
      : category === 'case_info'
        ? 'var(--error, #ef4444)'
        : category === 'model'
          ? 'var(--info, #3b82f6)'
          : 'var(--text-muted)';
  return (
    <span
      style={{
        fontSize: 10,
        padding: '1px 6px',
        borderRadius: 4,
        border: `1px solid ${color}`,
        color,
        whiteSpace: 'nowrap',
      }}
    >
      {label ?? fallback[category] ?? category}
    </span>
  );
}
