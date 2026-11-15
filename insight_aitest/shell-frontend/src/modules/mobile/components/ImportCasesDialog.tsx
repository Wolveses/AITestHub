import { useCallback, useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';
import { CheckSquare, Search, Square } from 'lucide-react';
import { Modal } from '../../../components/ui/modal';
import { CategoryTree } from '../../ui/components/automation/CategoryTree';
import { useMobileStore, type ImportableCase } from '../store/mobileStore';
import { Btn, inputStyle } from './common';

/** 每页条数：服务端分页，目录树计数与搜索都在后端做（用例库可达数万条） */
const PAGE_SIZE = 200;

export function ImportCasesDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { projectId, importable, importCases } = useMobileStore();
  const [items, setItems] = useState<ImportableCase[]>([]);
  const [total, setTotal] = useState(0);
  const [allTotal, setAllTotal] = useState(0);
  const [folders, setFolders] = useState<{ path: string; count: number }[]>([]);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [search, setSearch] = useState('');
  const [folder, setFolder] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  /** 请求序号：搜索/目录切换时丢弃过期响应 */
  const seqRef = useRef(0);

  const load = useCallback(
    async (opts: { page: number; append: boolean; search: string; categoryPath: string | null }) => {
      if (projectId === null) return;
      const seq = ++seqRef.current;
      if (opts.append) setLoadingMore(true);
      else setLoading(true);
      try {
        const res = await importable({
          search: opts.search,
          categoryPath: opts.categoryPath,
          page: opts.page,
          pageSize: PAGE_SIZE,
        });
        if (seq !== seqRef.current) return;
        setItems((prev) => (opts.append ? [...prev, ...res.items] : res.items));
        setTotal(res.total);
        setAllTotal(res.all_total);
        setFolders(res.folders || []);
        setPage(res.page);
      } catch (e) {
        if (seq === seqRef.current) toast.error((e as Error).message);
      } finally {
        if (seq === seqRef.current) {
          setLoading(false);
          setLoadingMore(false);
        }
      }
    },
    [importable, projectId]
  );

  useEffect(() => {
    if (!open) return;
    setSearch('');
    setFolder(null);
    setSelected(new Set());
    setItems([]);
    setTotal(0);
    setAllTotal(0);
    setFolders([]);
    setLoading(true);
  }, [open]);

  // 搜索 300ms 防抖；打开弹窗后的首次加载与目录切换也走这里
  useEffect(() => {
    if (!open || projectId === null) return;
    const timer = window.setTimeout(() => {
      load({ page: 1, append: false, search, categoryPath: folder });
    }, 300);
    return () => window.clearTimeout(timer);
  }, [open, projectId, search, folder, load]);

  const loadMore = () => load({ page: page + 1, append: true, search, categoryPath: folder });

  const available = items.filter((i) => !i.imported);
  const allSelected = available.length > 0 && available.every((i) => selected.has(i.document_id));

  const toggle = (id: number) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelected(next);
  };

  const toggleAll = () => {
    if (allSelected) setSelected(new Set());
    else setSelected(new Set(available.map((i) => i.document_id)));
  };

  const submit = async () => {
    if (selected.size === 0) return;
    setSubmitting(true);
    try {
      const res = await importCases(Array.from(selected));
      toast.success(`已导入 ${res.created} 条，跳过 ${res.skipped} 条`);
      onClose();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      open={open}
      onOpenChange={(v) => !v && onClose()}
      title="从用例库导入（快照，不随源同步）"
      width="min(860px, 94vw)"
    >
      <div style={{ padding: '0 20px 16px', display: 'flex', flexDirection: 'column', height: 'min(70vh, 620px)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
          <div style={{ position: 'relative', flex: 1 }}>
            <Search size={13} style={{ position: 'absolute', left: 8, top: 8, color: 'var(--text-muted)' }} />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="搜索用例标题"
              style={{ ...inputStyle, paddingLeft: 26 }}
            />
          </div>
        </div>

        <div
          style={{
            flex: 1,
            display: 'flex',
            minHeight: 0,
            border: '1px solid var(--border)',
            borderRadius: 8,
            overflow: 'hidden',
          }}
        >
          <CategoryTree
            items={folders.map((f) => ({ category_path: f.path, count: f.count }))}
            allCount={allTotal}
            active={folder}
            onSelect={setFolder}
            allLabel="全部用例"
          />

          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
            {/* 全选：仅图标无文案，作用于当前目录下可导入的用例 */}
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                padding: '5px 12px',
                borderBottom: '1px solid var(--bg-card)',
                flexShrink: 0,
              }}
            >
              <span
                role="checkbox"
                aria-checked={allSelected}
                aria-label="全选可导入"
                onClick={() => available.length > 0 && toggleAll()}
                style={{
                  display: 'inline-flex',
                  cursor: available.length === 0 ? 'not-allowed' : 'pointer',
                  opacity: available.length === 0 ? 0.5 : 1,
                  color: allSelected ? 'var(--accent)' : 'var(--text-muted)',
                }}
              >
                {allSelected ? <CheckSquare size={15} /> : <Square size={15} />}
              </span>
            </div>

            <div style={{ flex: 1, overflowY: 'auto' }}>
              {loading ? (
                <div style={{ padding: 32, textAlign: 'center', color: 'var(--text-muted)', fontSize: 12 }}>
                  加载中…
                </div>
              ) : items.length === 0 ? (
                <div style={{ padding: 32, textAlign: 'center', color: 'var(--text-muted)', fontSize: 12 }}>
                  {search.trim() || folder ? '该目录下暂无用例' : '该项目下暂无可导入的知识库用例'}
                </div>
              ) : (
                items.map((i) => {
                  const disabled = i.imported;
                  const isChecked = selected.has(i.document_id);
                  return (
                    <div
                      key={i.document_id}
                      onClick={() => !disabled && toggle(i.document_id)}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 10,
                        padding: '8px 12px',
                        borderBottom: '1px solid var(--bg-card)',
                        cursor: disabled ? 'not-allowed' : 'pointer',
                        opacity: disabled ? 0.45 : 1,
                        fontSize: 12,
                      }}
                    >
                      <span style={{ color: isChecked ? 'var(--accent)' : 'var(--text-muted)', display: 'inline-flex' }}>
                        {isChecked ? <CheckSquare size={15} /> : <Square size={15} />}
                      </span>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {i.title}
                          {disabled && (
                            <span style={{ marginLeft: 8, fontSize: 11, color: 'var(--text-muted)' }}>
                              已导入
                            </span>
                          )}
                        </div>
                        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
                          {i.category_path || '未分类'}
                          {i.case_id ? ` · #${i.case_id}` : ''} · {i.step_count} 步
                        </div>
                      </div>
                    </div>
                  );
                })
              )}
              {!loading && items.length > 0 && items.length < total && (
                <div style={{ padding: '10px 12px', textAlign: 'center' }}>
                  <Btn size="sm" onClick={loadMore} disabled={loadingMore}>
                    {loadingMore ? '加载中…' : `加载更多（剩余 ${total - items.length} 条）`}
                  </Btn>
                </div>
              )}
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 12 }}>
          <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            已选 {selected.size} 条
          </span>
          <div style={{ flex: 1 }} />
          <Btn onClick={onClose}>取消</Btn>
          <Btn variant="primary" disabled={selected.size === 0 || submitting} onClick={submit}>
            {submitting ? '导入中…' : '确认导入'}
          </Btn>
        </div>
      </div>
    </Modal>
  );
}
