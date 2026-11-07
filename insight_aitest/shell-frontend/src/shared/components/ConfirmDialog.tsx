import { useConfirmStore } from '../store/confirmStore';
import { Modal } from '../../components/ui/modal';
import { useTranslation } from 'react-i18next';

/**
 * 全局确认弹窗。挂载在 AppShell 根节点，全局唯一实例。
 * 任何组件通过 useConfirmStore().confirm({ message, onConfirm }) 触发。
 * 渲染层走共享 Modal（Radix focus trap / Esc / scroll lock）。
 */
export function ConfirmDialog() {
  const { open, title, message, confirmText, cancelText, variant, resolve, cancel } = useConfirmStore();
  const { t } = useTranslation();
  const isDanger = variant === 'danger';
  const displayTitle = title ?? (isDanger ? t('dialogs.confirmDelete', '确认删除') : t('dialogs.confirmTitle', '操作确认'));

  return (
    <Modal open={open} onOpenChange={(o) => { if (!o) cancel(); }} title={displayTitle}>
      <div style={{ padding: '0 20px 16px' }}>
        <p style={{ margin: 0, color: 'var(--text-secondary)', fontSize: 13, lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>
          {message}
        </p>
      </div>
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, padding: '0 20px 16px' }}>
        <button
          onClick={cancel}
          style={{
            background: 'none',
            border: '1px solid var(--border)',
            color: 'var(--text-secondary)',
            borderRadius: 6,
            padding: '6px 16px',
            cursor: 'pointer',
            fontSize: 13,
          }}
        >
          {cancelText ?? t('common.cancel', '取消')}
        </button>
        <button
          onClick={resolve}
          style={{
            background: isDanger ? '#ef4444' : 'var(--accent)',
            color: '#fff',
            border: 'none',
            borderRadius: 6,
            padding: '6px 16px',
            cursor: 'pointer',
            fontSize: 13,
            fontWeight: 600,
          }}
        >
          {confirmText ?? (isDanger ? t('dialogs.confirmDelete', '确认删除') : t('common.confirm', '确认'))}
        </button>
      </div>
    </Modal>
  );
}
