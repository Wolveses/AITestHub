import { useEffect, useState } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { X, ChevronDown, ChevronUp } from 'lucide-react';
import { useTranslation } from 'react-i18next';

interface ChunkItem {
  chunk_index: number;
  text: string;
  char_start: number;
  char_end: number;
  embed_status: string | null;
}

interface ChunksResponse {
  document_id: number;
  filename: string;
  total: number;
  by_status: Record<string, number>;
  items: ChunkItem[];
}

interface ChunksViewerProps {
  docId: number;
  filename: string;
  onOpenChange: (open: boolean) => void;
}

const PREVIEW_LINES = 6; // chunk 文本默认折叠到前 6 行

/** 分块预览弹窗：只读展示一个文档的 chunks 列表，用于诊断分块效果。
 * 顶部统计（总数 + embed_status 分色计数）、内容过滤、逐块卡片（索引/状态徽标/字符区间/可展开文本）。
 */
export function ChunksViewer({ docId, filename, onOpenChange }: ChunksViewerProps) {
  const { t } = useTranslation();
  const [data, setData] = useState<ChunksResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState('');
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [page, setPage] = useState(1);
  const PAGE_SIZE = 20;

  useEffect(() => {
    setLoading(true);
    setError(null);
    setFilter('');
    setExpanded(new Set());
    let cancelled = false;
    fetch(`/api/modules/kb/documents/${docId}/chunks`)
      .then(async (r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json() as Promise<ChunksResponse>;
      })
      .then((res) => {
        if (!cancelled) {
          setData(res);
          setLoading(false);
        }
      })
      .catch((e) => {
        if (!cancelled) {
          setError(e.message || 'load failed');
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [docId]);

  const toggleExpand = (idx: number) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  const filtered = (data?.items ?? []).filter((c) =>
    filter ? c.text.toLowerCase().includes(filter.toLowerCase()) : true,
  );
  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const items = filtered.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);

  const statusBadgeStyle = (status: string | null): React.CSSProperties => {
    const s = status || 'pending';
    if (s === 'ok') return { background: 'rgba(34,197,94,0.12)', color: '#16a34a' };
    if (s === 'failed') return { background: 'rgba(239,68,68,0.12)', color: '#dc2626' };
    return { background: 'var(--bg-secondary, #f1f5f9)', color: 'var(--text-muted)' };
  };

  const statusLabel = (status: string | null): string => {
    const s = status || 'pending';
    if (s === 'ok') return t('kb.embedOk', '已向量化');
    if (s === 'failed') return t('kb.embedFailed', '向量化失败');
    return t('kb.embedPending', '未向量化');
  };

  return (
    <Dialog.Root open onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', zIndex: 2000 }} />
        <Dialog.Content
          style={{
            position: 'fixed', top: '50%', left: '50%', transform: 'translate(-50%, -50%)',
            width: '80vw', maxWidth: 900, height: '88vh', maxHeight: '88vh',
            background: 'var(--bg-card)',
            border: '1px solid var(--bg-elevated)', borderRadius: 10,
            boxShadow: '0 8px 32px rgba(0,0,0,0.5)', zIndex: 2001,
            display: 'flex', flexDirection: 'column', overflow: 'hidden', outline: 'none',
          }}
        >
          {/* 标题栏 */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '10px 16px', borderBottom: '1px solid var(--bg-card)' }}>
            <Dialog.Title style={{ flex: 1, fontSize: 14, fontWeight: 600, color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {t('kb.chunksViewerTitle', '分块预览')}：{filename}
            </Dialog.Title>
            <Dialog.Close asChild>
              <button title={t('common.close', '关闭')} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-secondary)', padding: 4 }}>
                <X size={16} />
              </button>
            </Dialog.Close>
          </div>

          {/* 统计 + 过滤条 */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '8px 16px', borderBottom: '1px solid var(--bg-card)', flexWrap: 'wrap' }}>
            <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
              {t('kb.chunksTotal', '共 {{n}} 块', { n: data?.total ?? 0 })}
            </span>
            {data && Object.entries(data.by_status).map(([s, n]) => (
              <span key={s} style={{ fontSize: 11, padding: '1px 8px', borderRadius: 10, fontWeight: 500, ...statusBadgeStyle(s) }}>
                {statusLabel(s)} {n}
              </span>
            ))}
            <input
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder={t('kb.chunksFilter', '过滤分块内容…')}
              style={{
                marginLeft: 'auto', padding: '3px 8px', fontSize: 12, width: 200,
                border: '1px solid var(--bg-elevated)', borderRadius: 4,
                background: 'var(--bg-card)', color: 'var(--text-primary)', outline: 'none',
              }}
            />
          </div>

          {/* 列表 */}
          <div style={{ flex: 1, overflowY: 'auto', padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: 10 }}>
            {loading && <div style={{ textAlign: 'center', color: 'var(--text-muted)', fontSize: 13, padding: 24 }}>{t('common.loading', '加载中…')}</div>}
            {error && <div style={{ textAlign: 'center', color: 'var(--error, #dc2626)', fontSize: 13, padding: 24 }}>{t('kb.chunksLoadFailed', '分块加载失败')}: {error}</div>}
            {!loading && !error && items.length === 0 && (
              <div style={{ textAlign: 'center', color: 'var(--text-muted)', fontSize: 13, padding: 24 }}>
                {filter ? t('kb.chunksNoMatch', '没有匹配的分块') : t('kb.chunksEmpty', '该文档暂无分块')}
              </div>
            )}
            {!loading && !error && items.map((c) => {
              const isOpen = expanded.has(c.chunk_index);
              const lines = c.text.split('\n');
              const needFold = lines.length > PREVIEW_LINES;
              return (
                <div key={c.chunk_index} style={{ flexShrink: 0, border: '1px solid var(--bg-elevated)', borderRadius: 6, overflow: 'hidden' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '6px 10px', background: 'var(--bg-secondary, #f8fafc)', fontSize: 11, color: 'var(--text-muted)' }}>
                    <span style={{ fontWeight: 700, color: 'var(--text-primary)', fontSize: 12 }}>#{c.chunk_index}</span>
                    <span style={{ padding: '1px 8px', borderRadius: 10, fontWeight: 500, ...statusBadgeStyle(c.embed_status) }}>
                      {statusLabel(c.embed_status)}
                    </span>
                    <span>char {c.char_start}-{c.char_end} · {c.text.length} {t('kb.chars', '字符')}</span>
                  </div>
                  <pre style={{
                    display: 'block',
                    margin: 0, padding: '8px 10px', fontSize: 12, lineHeight: 1.6,
                    color: 'var(--text-primary)', background: 'var(--bg-card)',
                    whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                    fontFamily: 'monospace',
                    maxHeight: isOpen ? 'none' : `${PREVIEW_LINES * 1.6}em`,
                    overflow: isOpen ? 'visible' : 'hidden',
                  }}>
                    {c.text}
                  </pre>
                  {needFold && (
                    <button
                      onClick={() => toggleExpand(c.chunk_index)}
                      style={{
                        width: '100%', background: 'none', border: 'none', borderTop: '1px solid var(--bg-card)',
                        padding: '4px 0', fontSize: 11, color: 'var(--accent)', cursor: 'pointer',
                        display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 4,
                      }}
                    >
                      {isOpen ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                      {isOpen ? t('kb.chunksCollapse', '收起') : t('kb.chunksExpand', '展开全部')}
                    </button>
                  )}
                </div>
              );
            })}
          </div>

          {/* 分页条 */}
          {filtered.length > PAGE_SIZE && (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, padding: '8px 16px', borderTop: '1px solid var(--bg-card)', fontSize: 12, color: 'var(--text-secondary)' }}>
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={safePage <= 1}
                style={{ padding: '2px 10px', border: '1px solid var(--bg-elevated)', borderRadius: 4, background: 'var(--bg-card)', color: 'var(--text-primary)', cursor: safePage <= 1 ? 'not-allowed' : 'pointer', opacity: safePage <= 1 ? 0.5 : 1 }}
              >
                ‹
              </button>
              <span>
                {t('kb.chunksPageInfo', '第 {{page}} / {{total}} 页', { page: safePage, total: totalPages })}
                {filter && ` (${filtered.length} / ${data?.total ?? 0})`}
              </span>
              <button
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={safePage >= totalPages}
                style={{ padding: '2px 10px', border: '1px solid var(--bg-elevated)', borderRadius: 4, background: 'var(--bg-card)', color: 'var(--text-primary)', cursor: safePage >= totalPages ? 'not-allowed' : 'pointer', opacity: safePage >= totalPages ? 0.5 : 1 }}
              >
                ›
              </button>
            </div>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
