import { useEffect, useState } from 'react';
import { Download, Loader2, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import { Modal } from '../../../components/ui/modal';
import { Btn, StatusBadge, inputStyle } from './common';
import { useMobileStore, type ImportableCase } from '../store/mobileStore';

export function ImportCasesDialog({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const { projectId, importable, importCases } = useMobileStore();
  const [items, setItems] = useState<ImportableCase[]>([]);
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<Record<number, boolean>>({});
  const [platforms, setPlatforms] = useState<Record<number, string>>({});
  const [loading, setLoading] = useState(false);
  const [importing, setImporting] = useState(false);

  const loadList = async (kw = search) => {
    if (!projectId) return;
    setLoading(true);
    try {
      const res = await importable({ search: kw, categoryPath: null, page: 1, pageSize: 100 });
      setItems(res.items);
      const nextSel: Record<number, boolean> = {};
      const nextPlat: Record<number, string> = {};
      for (const item of res.items) {
        if (!item.imported && item.suggested_platform === 'android') {
          nextSel[item.document_id] = true;
        }
        nextPlat[item.document_id] = item.suggested_platform || 'android';
      }
      setSelected(nextSel);
      setPlatforms(nextPlat);
    } catch (e) {
      toast.error(`加载可导入用例失败: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (open) {
      void loadList();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, projectId]);

  const selectedIds = Object.entries(selected)
    .filter(([, checked]) => checked)
    .map(([id]) => Number(id));

  const handleImport = async () => {
    if (selectedIds.length === 0) {
      toast.warning('请至少勾选一条测试用例');
      return;
    }
    setImporting(true);
    try {
      const res = await importCases(selectedIds, platforms);
      toast.success(`已导入 ${res.created} 条用例${res.skipped > 0 ? `，跳过 ${res.skipped} 条` : ''}`);
      onClose();
    } catch (e) {
      toast.error(`导入失败: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setImporting(false);
    }
  };

  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} title="从测试设计导入移动 App 用例" width="min(780px, 92vw)">
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, fontSize: 12, color: 'var(--text-secondary)' }}>
          <input
            style={{ ...inputStyle, flex: 1 }}
            placeholder="搜索标题 / 用例编号..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') void loadList(search);
            }}
          />
          <Btn variant="ghost" onClick={() => void loadList(search)} disabled={loading} style={{ padding: '6px 10px', fontSize: 12 }}>
            <RefreshCw size={12} /> 搜索/刷新
          </Btn>
        </div>

        <div
          style={{
            maxHeight: 380,
            overflowY: 'auto',
            border: '1px solid var(--border)',
            borderRadius: 8,
            background: 'var(--bg-base)',
          }}
        >
          {loading ? (
            <div style={{ padding: 32, textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
              <Loader2 size={18} className="animate-spin" style={{ display: 'inline', marginRight: 6 }} />
              加载中...
            </div>
          ) : items.length === 0 ? (
            <div style={{ padding: 32, textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
              当前项目下暂无可导入的功能测试用例。
            </div>
          ) : (
            items.map((item) => {
              const checked = !!selected[item.document_id];
              const plat = platforms[item.document_id] || item.suggested_platform || 'android';
              return (
                <div
                  key={item.document_id}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 10,
                    padding: '10px 12px',
                    borderBottom: '1px solid var(--border)',
                    opacity: item.imported ? 0.6 : 1,
                  }}
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    disabled={item.imported}
                    onChange={(e) => setSelected((prev) => ({ ...prev, [item.document_id]: e.target.checked }))}
                  />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--text-primary)' }}>{item.title}</span>
                      {item.imported && <StatusBadge status="implemented" />}
                      {item.priority && (
                        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>[{item.priority}]</span>
                      )}
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
                      {item.category_path || '未分类'} · {item.step_count} 步
                    </div>
                  </div>
                  <select
                    value={plat}
                    disabled={item.imported}
                    onChange={(e) => setPlatforms((prev) => ({ ...prev, [item.document_id]: e.target.value }))}
                    style={{
                      background: 'var(--bg-card)',
                      border: '1px solid var(--border)',
                      borderRadius: 6,
                      padding: '4px 8px',
                      fontSize: 12,
                      color: 'var(--text-primary)',
                    }}
                  >
                    <option value="android">Android</option>
                    <option value="ios">iOS (Phase 3)</option>
                  </select>
                </div>
              );
            })
          )}
        </div>

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>已选择 {selectedIds.length} 条</span>
          <div style={{ display: 'flex', gap: 8 }}>
            <Btn variant="ghost" onClick={onClose}>
              取消
            </Btn>
            <Btn variant="primary" onClick={() => void handleImport()} disabled={importing || selectedIds.length === 0}>
              <Download size={13} /> {importing ? '导入中...' : '确认导入'}
            </Btn>
          </div>
        </div>
      </div>
    </Modal>
  );
}
