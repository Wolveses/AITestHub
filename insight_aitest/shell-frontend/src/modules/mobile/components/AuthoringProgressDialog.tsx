import { useCallback, useEffect, useState } from 'react';
import { Loader2, RefreshCw, Square } from 'lucide-react';
import { toast } from 'sonner';
import { Modal } from '../../../components/ui/modal';
import { useMobileStore, type MobileActiveGenerationItem } from '../store/mobileStore';
import { Btn } from './common';

const STAGE_META: Record<string, { label: string; color: string }> = {
  waiting: { label: '等待 Agent', color: 'var(--text-muted)' },
  generating: { label: '探索中', color: '#0ea5e9' },
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

function formatEventSummary(ev: MobileActiveGenerationItem['latest_event']): string {
  if (!ev) return '';
  if (ev.error) return String(ev.error);
  if (ev.filename) return `截图 ${ev.filename}`;
  if (ev.type === 'dry_run_finished') {
    return ev.passed ? `试跑通过 (Run #${ev.run_id})` : `试跑失败 (Run #${ev.run_id})`;
  }
  if (ev.type === 'session_started') return '会话已锁定设备，等待本地 Agent 接入';
  return ev.tool || ev.type || '';
}

export function AuthoringProgressDialog({
  open,
  onClose,
  projectId,
  onCount,
  onOpenSession,
}: {
  open: boolean;
  onClose: () => void;
  projectId: number | null;
  onCount?: (count: number) => void;
  onOpenSession?: (caseId: number) => void;
}) {
  const { getActiveGenerations, cancelGenerate } = useMobileStore();
  const [items, setItems] = useState<MobileActiveGenerationItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [stoppingId, setStoppingId] = useState<number | null>(null);

  const refresh = useCallback(async () => {
    if (projectId === null) return;
    try {
      const list = await getActiveGenerations(projectId);
      setItems(list);
      onCount?.(list.length);
    } catch {
      /* 轮询失败静默，等下次 */
    }
  }, [projectId, getActiveGenerations, onCount]);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    void refresh().finally(() => setLoading(false));
    const timer = window.setInterval(() => void refresh(), 3000);
    return () => window.clearInterval(timer);
  }, [open, refresh]);

  const handleStop = async (caseId: number, title: string) => {
    setStoppingId(caseId);
    try {
      await cancelGenerate(caseId);
      toast.info(`已停止「${title}」并释放设备`);
      await refresh();
    } catch (e) {
      toast.error(`停止失败: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setStoppingId(null);
    }
  };

  return (
    <Modal
      open={open}
      onOpenChange={(v) => !v && onClose()}
      width="min(760px, 95vw)"
      title={`进行中的编写任务（${items.length}）`}
    >
      <div style={{ padding: '4px 20px 18px', maxHeight: '70vh', overflowY: 'auto' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
          <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            含等待 Agent、探索中、试跑通过三类（入库、取消或设备租约超时后自动移出）
          </span>
          <div style={{ flex: 1 }} />
          <Btn size="sm" variant="ghost" onClick={() => void refresh()} title="刷新">
            <RefreshCw size={12} />
          </Btn>
        </div>

        {loading && items.length === 0 && (
          <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>加载中…</div>
        )}

        {!loading && items.length === 0 && (
          <div style={{ padding: '28px 0', textAlign: 'center', fontSize: 12, color: 'var(--text-muted)' }}>
            暂无进行中的编写任务
          </div>
        )}

        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {items.map((item) => {
            const meta = STAGE_META[item.stage] || { label: item.stage, color: 'var(--text-muted)' };
            const detail = formatEventSummary(item.latest_event) || item.last_error || '';
            return (
              <div
                key={item.case_id}
                onClick={() => {
                  if (onOpenSession) {
                    onClose();
                    onOpenSession(item.case_id);
                  }
                }}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                  padding: '8px 10px',
                  border: '1px solid var(--border)',
                  borderRadius: 6,
                  fontSize: 12,
                  cursor: onOpenSession ? 'pointer' : 'default',
                }}
              >
                <span style={{ color: 'var(--text-muted)', fontFamily: 'monospace', flexShrink: 0 }}>
                  #{item.case_id}
                </span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontWeight: 500 }}>
                      {item.title || '—'}
                    </span>
                    {item.tool_calls > 0 && (
                      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 3, color: 'var(--accent)', fontSize: 11, flexShrink: 0 }}>
                        <Loader2 size={11} className="animate-spin" /> {item.tool_calls} 次调用
                      </span>
                    )}
                    <code style={{ fontSize: 11, color: 'var(--text-muted)', flexShrink: 0 }}>
                      {item.device_id}
                    </code>
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
                <span style={{ color: 'var(--text-muted)', fontSize: 11, whiteSpace: 'nowrap' }}>
                  {relTime(item.started_at)}
                </span>
                <span style={{ color: meta.color, fontWeight: 600, whiteSpace: 'nowrap' }}>
                  {meta.label}
                </span>
                <Btn
                  size="sm"
                  variant="danger"
                  title="停止生成并释放设备"
                  disabled={stoppingId === item.case_id}
                  onClick={(e) => {
                    e.stopPropagation();
                    void handleStop(item.case_id, item.title);
                  }}
                >
                  <Square size={11} /> {stoppingId === item.case_id ? '停止中…' : '停止'}
                </Btn>
              </div>
            );
          })}
        </div>

        <div style={{ marginTop: 12, fontSize: 11, color: 'var(--text-muted)' }}>
          点击任意任务可重新打开会话弹窗继续复制提示词或查看实时截图；点击「停止」将立即取消会话并释放真机锁。
        </div>
      </div>
    </Modal>
  );
}
