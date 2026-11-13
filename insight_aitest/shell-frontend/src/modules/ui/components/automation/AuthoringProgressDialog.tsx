import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2, RefreshCw } from 'lucide-react';
import { Modal } from '../../../../components/ui/modal';
import {
  fetchAuthoringActive,
  type AuthoringActiveItem,
} from '../../store/automationStore';
import { Btn } from './common';

const STAGE_META: Record<string, { label: string; color: string }> = {
  waiting: { label: '等待 Agent', color: 'var(--text-muted)' },
  generating: { label: '生成中', color: '#0ea5e9' },
  validated: { label: '已校验', color: 'var(--accent)' },
  dry_run_ok: { label: '试跑通过', color: '#22c55e' },
};

function relTime(iso: string | null): string {
  if (!iso) return '—';
  const diff = Date.now() - new Date(iso).getTime();
  if (Number.isNaN(diff)) return '—';
  const min = Math.floor(diff / 60000);
  if (min < 1) return '刚刚';
  if (min < 60) return `${min} 分钟前`;
  const hour = Math.floor(min / 60);
  if (hour < 24) return `${hour} 小时前`;
  return `${Math.floor(hour / 24)} 天前`;
}

export function AuthoringProgressDialog({
  open,
  onClose,
  projectId,
  onCount,
}: {
  open: boolean;
  onClose: () => void;
  projectId: number | null;
  onCount?: (count: number) => void;
}) {
  const { t } = useTranslation();
  const [items, setItems] = useState<AuthoringActiveItem[]>([]);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    if (projectId === null) return;
    try {
      const list = await fetchAuthoringActive(projectId);
      setItems(list);
      onCount?.(list.length);
    } catch {
      /* 轮询失败静默，等下次 */
    }
  }, [projectId, onCount]);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    void refresh().finally(() => setLoading(false));
    const timer = window.setInterval(() => void refresh(), 3000);
    return () => window.clearInterval(timer);
  }, [open, refresh]);

  return (
    <Modal
      open={open}
      onOpenChange={(v) => !v && onClose()}
      width="min(760px, 95vw)"
      title={t('ui.auto.authoringActiveTitle', '进行中的编写任务（{{count}}）', { count: items.length })}
    >
      <div style={{ padding: '4px 20px 18px', maxHeight: '70vh', overflowY: 'auto' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
          <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            {t('ui.auto.authoringActiveHint', '含等待 Agent、已校验、试跑通过三类，入库后自动移出')}
          </span>
          <div style={{ flex: 1 }} />
          <Btn size="sm" variant="ghost" onClick={() => void refresh()}>
            <RefreshCw size={12} />
          </Btn>
        </div>

        {loading && items.length === 0 && (
          <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{t('ui.auto.loading', '加载中…')}</div>
        )}

        {!loading && items.length === 0 && (
          <div style={{ padding: '28px 0', textAlign: 'center', fontSize: 12, color: 'var(--text-muted)' }}>
            {t('ui.auto.authoringActiveEmpty', '暂无进行中的编写任务')}
          </div>
        )}

        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {items.map((item) => {
            const meta = STAGE_META[item.stage] || { label: item.stage, color: 'var(--text-muted)' };
            const detail = item.latest_event?.message || item.last_error || '';
            return (
              <div
                key={item.case_id}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                  padding: '8px 10px',
                  border: '1px solid var(--border)',
                  borderRadius: 6,
                  fontSize: 12,
                }}
              >
                <span style={{ color: 'var(--text-muted)', fontFamily: 'monospace' }}>#{item.case_id}</span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {item.title || '—'}
                    </span>
                    {item.busy && (
                      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 3, color: 'var(--accent)', fontSize: 11 }}>
                        <Loader2 size={11} className="animate-spin" /> {t('ui.auto.authoringBusy', '执行中')}
                      </span>
                    )}
                  </div>
                  {detail && (
                    <div
                      style={{ color: 'var(--text-muted)', fontSize: 11, marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                      title={detail}
                    >
                      {detail}
                    </div>
                  )}
                </div>
                <span style={{ color: 'var(--text-muted)', fontSize: 11, whiteSpace: 'nowrap' }}>{relTime(item.updated_at)}</span>
                <span style={{ color: meta.color, fontWeight: 600, whiteSpace: 'nowrap' }}>{meta.label}</span>
              </div>
            );
          })}
        </div>

        <div style={{ marginTop: 12, fontSize: 11, color: 'var(--text-muted)' }}>
          {t('ui.auto.authoringActiveFooter', '已入库与未发起的用例不在列表内；校验状态 30 分钟、试跑结果 24 小时后自动过期')}
        </div>
      </div>
    </Modal>
  );
}
