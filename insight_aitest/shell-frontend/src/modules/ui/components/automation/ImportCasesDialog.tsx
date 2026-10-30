import { useEffect, useMemo, useState, type DragEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { ArrowLeftRight, CheckSquare, Square, Search } from 'lucide-react';
import { Modal } from '../../../../components/ui/modal';
import { useAutomationStore, type ImportableCase } from '../../store/automationStore';
import { CategoryTree, matchCategory } from './CategoryTree';
import { Btn, inputStyle } from './common';

type Step = 'select' | 'classify';

const SITE_FRONTEND = 'frontend';
const SITE_BACKEND = 'backend';

export function ImportCasesDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation();
  const { importable, importCases } = useAutomationStore();
  const [items, setItems] = useState<ImportableCase[]>([]);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [search, setSearch] = useState('');
  const [folder, setFolder] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [step, setStep] = useState<Step>('select');
  /** document_id → frontend/backend；进入分类页时用后端推断结果初始化，人工调整后保留 */
  const [siteMap, setSiteMap] = useState<Record<number, string>>({});
  /** 分类页里用于批量拖动的勾选集合 */
  const [checked, setChecked] = useState<Set<number>>(new Set());
  const [dragOver, setDragOver] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setSearch('');
    setFolder(null);
    setSelected(new Set());
    setStep('select');
    setSiteMap({});
    setChecked(new Set());
    setDragOver(null);
    setLoading(true);
    importable()
      .then((rows) => setItems(rows))
      .catch((e) => toast.error((e as Error).message))
      .finally(() => setLoading(false));
  }, [open, importable]);

  /** 搜索命中的条目，目录树按它统计数量。 */
  const searched = useMemo(() => {
    const kw = search.trim().toLowerCase();
    if (!kw) return items;
    return items.filter(
      (i) =>
        i.title.toLowerCase().includes(kw) ||
        (i.category_path || '').toLowerCase().includes(kw) ||
        (i.case_id || '').toLowerCase().includes(kw)
    );
  }, [items, search]);

  /** 右侧列表：搜索命中 + 当前目录（含子目录）。 */
  const filtered = useMemo(
    () => searched.filter((i) => matchCategory(i.category_path, folder)),
    [searched, folder]
  );

  const available = filtered.filter((i) => !i.imported);
  const allSelected = available.length > 0 && available.every((i) => selected.has(i.document_id));

  const selectedItems = useMemo(
    () => items.filter((i) => selected.has(i.document_id)),
    [items, selected]
  );

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

  /** 下一步：打开分区确认页，未调整过的用例按后端推断归类。 */
  const goClassify = () => {
    const next: Record<number, string> = { ...siteMap };
    selectedItems.forEach((i) => {
      if (!next[i.document_id]) next[i.document_id] = i.suggested_site || SITE_FRONTEND;
    });
    setSiteMap(next);
    setChecked(new Set());
    setStep('classify');
  };

  const siteOf = (id: number) => siteMap[id] || SITE_FRONTEND;
  const frontItems = selectedItems.filter((i) => siteOf(i.document_id) === SITE_FRONTEND);
  const backItems = selectedItems.filter((i) => siteOf(i.document_id) === SITE_BACKEND);

  const moveTo = (ids: number[], site: string) => {
    if (ids.length === 0) return;
    const next = { ...siteMap };
    ids.forEach((id) => (next[id] = site));
    setSiteMap(next);
    setChecked((prev) => {
      const rest = new Set(prev);
      ids.forEach((id) => rest.delete(id));
      return rest;
    });
  };

  const toggleCheck = (id: number) => {
    const next = new Set(checked);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setChecked(next);
  };

  /** 拖动：已勾选的卡片一起移动，未勾选的只移动自身。 */
  const dragIds = (id: number) => (checked.has(id) ? Array.from(checked) : [id]);

  const onDropColumn = (site: string) => (e: DragEvent) => {
    e.preventDefault();
    setDragOver(null);
    const raw = e.dataTransfer.getData('text/plain');
    const ids = raw
      .split(',')
      .map((v) => Number(v))
      .filter((v) => Number.isFinite(v));
    moveTo(ids.filter((id) => selected.has(id)), site);
  };

  const submit = async () => {
    if (selected.size === 0) return;
    setSubmitting(true);
    try {
      const res = await importCases(Array.from(selected), siteMap);
      toast.success(
        t('ui.auto.importedSuccess', '导入完成：新增 {{created}} 条，跳过 {{skipped}} 条', {
          created: res.created,
          skipped: res.skipped,
        })
      );
      if (Array.isArray(res.failed) && res.failed.length > 0) {
        toast.warning(t('ui.auto.importedFailed', '{{count}} 条导入失败', { count: res.failed.length }));
      }
      onClose();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  const siteLabel = (site: string) =>
    site === SITE_BACKEND ? t('ui.auto.siteBackend', '后台') : t('ui.auto.siteFrontend', '前台');

  const renderCard = (i: ImportableCase, site: string) => {
    const isChecked = checked.has(i.document_id);
    const other = site === SITE_FRONTEND ? SITE_BACKEND : SITE_FRONTEND;
    return (
      <div
        key={i.document_id}
        draggable
        onDragStart={(e) => {
          const ids = dragIds(i.document_id);
          e.dataTransfer.setData('text/plain', ids.join(','));
          e.dataTransfer.effectAllowed = 'move';
        }}
        onClick={() => toggleCheck(i.document_id)}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          padding: '7px 10px',
          borderBottom: '1px solid var(--bg-card)',
          fontSize: 12,
          cursor: 'grab',
          background: isChecked ? 'var(--surface-hover)' : 'transparent',
        }}
      >
        <span style={{ color: isChecked ? 'var(--accent)' : 'var(--text-muted)', display: 'inline-flex' }}>
          {isChecked ? <CheckSquare size={14} /> : <Square size={14} />}
        </span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {i.title}
            <span style={{ marginLeft: 6, fontSize: 10, color: 'var(--text-muted)' }}>
              {t('ui.auto.suggestedByRule', '系统建议：{{site}}', {
                site: siteLabel(i.suggested_site || SITE_FRONTEND),
              })}
            </span>
          </div>
          <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {i.category_path || t('ui.auto.uncategorized', '未分类')}
            {i.case_id ? ` · #${i.case_id}` : ''}
          </div>
        </div>
        <span
          onClick={(e) => {
            e.stopPropagation();
            moveTo([i.document_id], other);
          }}
          title={t('ui.auto.moveToOther', '移到{{site}}', { site: siteLabel(other) })}
          style={{ display: 'inline-flex', color: 'var(--text-muted)', cursor: 'pointer' }}
        >
          <ArrowLeftRight size={13} />
        </span>
      </div>
    );
  };

  const renderColumn = (site: string, rows: ImportableCase[]) => (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        setDragOver(site);
      }}
      onDragLeave={() => setDragOver((prev) => (prev === site ? null : prev))}
      onDrop={onDropColumn(site)}
      style={{
        flex: 1,
        minWidth: 0,
        display: 'flex',
        flexDirection: 'column',
        border: `1px solid ${dragOver === site ? 'var(--accent)' : 'var(--border)'}`,
        borderRadius: 8,
        overflow: 'hidden',
        background: dragOver === site ? 'var(--surface-hover)' : 'transparent',
      }}
    >
      <div
        style={{
          padding: '7px 10px',
          fontSize: 12,
          fontWeight: 600,
          borderBottom: '1px solid var(--bg-card)',
          background: 'var(--bg-card)',
          display: 'flex',
          alignItems: 'center',
          gap: 6,
        }}
      >
        <span>{siteLabel(site)}</span>
        <span style={{ fontSize: 11, fontWeight: 400, color: 'var(--text-muted)' }}>（{rows.length}）</span>
        <span style={{ marginLeft: 'auto', fontSize: 10, fontWeight: 400, color: 'var(--text-muted)' }}>
          {site === SITE_BACKEND ? '/manage' : '/'}
        </span>
      </div>
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {rows.length === 0 ? (
          <div style={{ padding: 24, textAlign: 'center', fontSize: 11, color: 'var(--text-muted)' }}>
            {t('ui.auto.dragHereHint', '拖动用例到这里')}
          </div>
        ) : (
          rows.map((i) => renderCard(i, site))
        )}
      </div>
    </div>
  );

  return (
    <Modal
      open={open}
      onOpenChange={(v) => !v && onClose()}
      title={
        step === 'select'
          ? t('ui.auto.importTitle', '从用例库导入（快照，不随源同步）')
          : t('ui.auto.classifyTitle', '确认用例归属端（前台 / 后台）')
      }
      width="min(860px, 94vw)"
    >
      <div style={{ padding: '0 20px 16px', display: 'flex', flexDirection: 'column', height: 'min(70vh, 620px)' }}>
        {step === 'select' ? (
          <>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
              <div style={{ position: 'relative', flex: 1 }}>
                <Search size={13} style={{ position: 'absolute', left: 8, top: 8, color: 'var(--text-muted)' }} />
                <input
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder={t('ui.auto.searchPlaceholder', '搜索用例标题')}
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
                items={searched}
                active={folder}
                onSelect={setFolder}
                allLabel={t('ui.auto.allCases', '全部用例')}
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
                    aria-label={t('ui.auto.selectAll', '全选可导入')}
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
                      {t('ui.auto.loading', '加载中…')}
                    </div>
                  ) : searched.length === 0 ? (
                    <div style={{ padding: 32, textAlign: 'center', color: 'var(--text-muted)', fontSize: 12 }}>
                      {t('ui.auto.noImportable', '该项目下暂无可导入的知识库用例')}
                    </div>
                  ) : filtered.length === 0 ? (
                    <div style={{ padding: 32, textAlign: 'center', color: 'var(--text-muted)', fontSize: 12 }}>
                      {t('ui.auto.noCasesInFolder', '该目录下暂无用例')}
                    </div>
                  ) : (
                    filtered.map((i) => {
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
                                  {t('ui.auto.alreadyImported', '已导入')}
                                </span>
                              )}
                            </div>
                            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
                              {i.category_path || t('ui.auto.uncategorized', '未分类')}
                              {i.case_id ? ` · #${i.case_id}` : ''} ·{' '}
                              {t('ui.auto.stepCount', '{{count}} 步', { count: i.step_count })}
                            </div>
                          </div>
                        </div>
                      );
                    })
                  )}
                </div>
              </div>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 12 }}>
              <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                {t('ui.auto.selectedCount', '已选 {{count}} 条', { count: selected.size })}
              </span>
              <div style={{ flex: 1 }} />
              <Btn onClick={onClose}>{t('ui.auto.cancel', '取消')}</Btn>
              <Btn variant="primary" disabled={selected.size === 0 || submitting} onClick={goClassify}>
                {t('ui.auto.nextStep', '下一步')}
              </Btn>
            </div>
          </>
        ) : (
          <>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 8 }}>
              {t('ui.auto.classifyHint', '按关键字自动归类，可点击卡片或拖动调整；勾选后可批量拖动')}
            </div>
            <div style={{ flex: 1, display: 'flex', gap: 10, minHeight: 0 }}>
              {renderColumn(SITE_FRONTEND, frontItems)}
              {renderColumn(SITE_BACKEND, backItems)}
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 12 }}>
              <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                {t('ui.auto.selectedCount', '已选 {{count}} 条', { count: selected.size })}
              </span>
              <div style={{ flex: 1 }} />
              <Btn onClick={() => setStep('select')}>{t('ui.auto.prevStep', '上一步')}</Btn>
              <Btn variant="primary" disabled={submitting} onClick={submit}>
                {submitting ? t('ui.auto.importing', '导入中…') : t('ui.auto.confirmImport', '确认导入')}
              </Btn>
            </div>
          </>
        )}
      </div>
    </Modal>
  );
}
