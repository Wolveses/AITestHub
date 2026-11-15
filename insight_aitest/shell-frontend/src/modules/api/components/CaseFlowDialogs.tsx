import { useEffect, useMemo, useState, type CSSProperties } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Loader2, Search, X } from 'lucide-react';
import { Modal } from '../../../components/ui/modal';
import { useProjectStore } from '../../../shared/store/projectStore';
import { useCapabilitiesStore } from '@/shared/store/capabilitiesStore';
import { useAssetStore, type ApiAsset } from '../store/assetStore';
import { useRunStore, type ApiCase } from '../store/runStore';
import { ApiStepsEditor, type ApiContent, type ApiStep } from '../../testcase/components/ApiStepsEditor';

const METHODS = ['', 'GET', 'POST', 'PUT', 'PATCH', 'DELETE'];

const SYNONYM_GROUPS: string[][] = [
  ['新增', '创建', '添加', '新建'],
  ['修改', '更新', '编辑'],
  ['删除', '移除'],
  ['查询', '获取', '列表', '详情'],
];

function expandTokenSynonyms(token: string): string[] {
  const result = new Set<string>([token]);
  for (const group of SYNONYM_GROUPS) {
    for (const word of group) {
      if (token.includes(word)) {
        for (const alt of group) {
          result.add(token.replace(word, alt));
        }
      }
    }
  }
  return Array.from(result);
}

const inputStyle: CSSProperties = {
  width: '100%',
  background: 'var(--bg-card)',
  color: 'var(--text-primary)',
  border: '1px solid var(--bg-elevated)',
  borderRadius: 6,
  paddingTop: 7,
  paddingBottom: 7,
  paddingLeft: 10,
  paddingRight: 10,
  fontSize: 13,
  boxSizing: 'border-box',
};

const btnStyle = (primary = false, disabled = false): CSSProperties => ({
  background: primary ? 'var(--accent)' : 'none',
  color: primary ? 'var(--bg-base)' : 'var(--text-secondary)',
  border: primary ? 'none' : '1px solid var(--bg-elevated)',
  borderRadius: 6,
  padding: '6px 14px',
  fontSize: 13,
  fontWeight: primary ? 600 : 400,
  cursor: disabled ? 'not-allowed' : 'pointer',
  opacity: disabled ? 0.5 : 1,
  display: 'inline-flex',
  alignItems: 'center',
  gap: 6,
});

function methodColor(method: string) {
  switch (method.toUpperCase()) {
    case 'GET': return '#3b82f6';
    case 'POST': return '#16a34a';
    case 'PUT': return '#d97706';
    case 'PATCH': return '#a855f7';
    case 'DELETE': return '#dc2626';
    default: return 'var(--text-secondary)';
  }
}

/** 接口资产多选列表：用例新建/编辑时导入步骤的唯一来源。 */
function AssetPicker({
  assets,
  selected,
  onToggle,
  loading,
}: {
  assets: ApiAsset[];
  selected: number[];
  onToggle: (id: number) => void;
  loading: boolean;
}) {
  const { t } = useTranslation();
  const [keyword, setKeyword] = useState('');
  const [method, setMethod] = useState('');

  const filtered = useMemo(() => {
    const m = method.trim().toUpperCase();
    const tokens = keyword.trim().toLowerCase().split(/\s+/).filter(Boolean);
    return assets.filter((a) => {
      if (m && (a.method || '').toUpperCase() !== m) return false;
      if (tokens.length === 0) return true;
      const haystack = [
        a.title,
        a.path,
        a.method,
        a.path_template,
        a.base_url,
        a.fingerprint,
        a.ai_meta?.title,
        a.ai_meta?.summary,
        a.ai_meta?.path_template,
        ...(a.tags || []),
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase();
      return tokens.every((tok) =>
        expandTokenSynonyms(tok).some((alt) => haystack.includes(alt)),
      );
    });
  }, [assets, keyword, method]);

  return (
    <div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
        <select
          style={{ ...inputStyle, width: 108, flexShrink: 0, cursor: 'pointer' }}
          value={method}
          onChange={(e) => setMethod(e.target.value)}
        >
          {METHODS.map((m) => (
            <option key={m} value={m}>
              {m || t('api.allMethods')}
            </option>
          ))}
        </select>
        <div style={{ position: 'relative', flex: 1 }}>
          <Search
            size={13}
            strokeWidth={1.5}
            style={{ position: 'absolute', left: 9, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)', pointerEvents: 'none' }}
          />
          <input
            style={{ ...inputStyle, paddingLeft: 28, paddingRight: keyword ? 28 : 10 }}
            placeholder={t('api.assetSearch')}
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
          />
          {keyword && (
            <button
              type="button"
              onClick={() => setKeyword('')}
              style={{
                position: 'absolute',
                right: 6,
                top: '50%',
                transform: 'translateY(-50%)',
                background: 'none',
                border: 'none',
                color: 'var(--text-muted)',
                cursor: 'pointer',
                padding: 2,
                display: 'inline-flex',
                alignItems: 'center',
              }}
            >
              <X size={13} strokeWidth={1.5} />
            </button>
          )}
        </div>
      </div>
      <div style={{
        maxHeight: 240, overflow: 'auto', border: '1px solid var(--bg-elevated)', borderRadius: 6, background: 'var(--bg-card)',
      }}>
        {loading && <div style={{ padding: 12, fontSize: 12, color: 'var(--text-muted)' }}>{t('api.loading')}</div>}
        {!loading && filtered.length === 0 && (
          <div style={{ padding: 12, fontSize: 12, color: 'var(--text-muted)' }}>{t('api.noAssets')}</div>
        )}
        {filtered.map((a) => {
          const checked = selected.includes(a.id);
          const displayTitle = a.title || a.ai_meta?.title || a.path_template || a.path;
          const displayPath = a.path_template || a.path;
          return (
            <label
              key={a.id}
              title={`${a.method} ${displayPath}${a.ai_meta?.summary ? `\n${a.ai_meta.summary}` : ''}`}
              style={{
                display: 'flex', alignItems: 'center', gap: 8, padding: '6px 10px', cursor: 'pointer',
                borderBottom: '1px solid var(--bg-base)',
                background: checked ? 'var(--bg-elevated)' : 'transparent',
              }}
            >
              <input type="checkbox" checked={checked} onChange={() => onToggle(a.id)} style={{ flexShrink: 0 }} />
              <span style={{ color: methodColor(a.method), fontSize: 11, fontWeight: 600, width: 52, flexShrink: 0 }}>
                {a.method}
              </span>
              <span style={{ fontSize: 12, color: 'var(--text-primary)', flex: 1, minWidth: 120, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {displayTitle}
              </span>
              <span style={{ fontSize: 11, color: 'var(--text-muted)', maxWidth: 260, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontFamily: 'monospace' }}>
                {displayPath}
              </span>
            </label>
          );
        })}
      </div>
    </div>
  );
}

/** 新建用例：填写名称并导入接口资产（不选资产则创建空用例后手动编辑）。 */
export function NewCaseDialog({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (caseId: number) => void;
}) {
  const { t } = useTranslation();
  const currentProjectId = useProjectStore((s) => s.currentProjectId);
  const aiAssistEnabled = useCapabilitiesStore((s) => s.aiAssistEnabled);
  const { fetchAssets, importCase } = useAssetStore();
  const createCase = useRunStore((s) => s.createCase);

  const [title, setTitle] = useState('');
  const [assets, setAssets] = useState<ApiAsset[]>([]);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<number[]>([]);
  const [aiOrder, setAiOrder] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const effectiveAiOrder = aiAssistEnabled && aiOrder;

  useEffect(() => {
    if (!open) return;
    setTitle('');
    setSelected([]);
    setAiOrder(aiAssistEnabled);
    setLoading(true);
    fetchAssets(currentProjectId)
      .then(setAssets)
      .catch((e) => toast.error(String(e)))
      .finally(() => setLoading(false));
  }, [open, currentProjectId, fetchAssets, aiAssistEnabled]);

  const toggle = (id: number) =>
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));

  const submit = async () => {
    const name = title.trim();
    if (!name) {
      toast.error(t('api.caseNameRequired'));
      return;
    }
    setSubmitting(true);
    try {
      if (selected.length > 0) {
        const result = await importCase(selected, name, effectiveAiOrder);
        toast.success(t('api.composeDone', { id: result.case_id, steps: result.step_count }));
        onCreated(result.case_id);
      } else {
        const id = await createCase(name);
        onCreated(id);
      }
      onClose();
    } catch (e) {
      toast.error(String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal open={open} onOpenChange={(o) => { if (!o) onClose(); }} title={t('api.newCase')} width="min(640px, 92vw)">
      <div style={{ padding: '0 20px 20px', display: 'flex', flexDirection: 'column', gap: 10 }}>
        <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{t('api.caseName')}</div>
        <input
          style={inputStyle}
          placeholder={t('api.caseTitlePlaceholder')}
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
        <div style={{ fontSize: 12, color: 'var(--text-secondary)', display: 'flex', justifyContent: 'space-between' }}>
          <span>{t('api.importAssetsHint')}</span>
          <span>{t('api.assetSelectedCount', { count: selected.length })}</span>
        </div>
        <AssetPicker assets={assets} selected={selected} onToggle={toggle} loading={loading} />
        <label
          title={!aiAssistEnabled ? '系统设置已关闭 LLM 自动化辅助能力' : undefined}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            fontSize: 12,
            color: aiAssistEnabled ? 'var(--text-secondary)' : 'var(--text-muted)',
            cursor: aiAssistEnabled ? 'pointer' : 'not-allowed',
            opacity: aiAssistEnabled ? 1 : 0.7,
          }}
        >
          <input
            type="checkbox"
            checked={effectiveAiOrder}
            disabled={!aiAssistEnabled}
            onChange={(e) => setAiOrder(e.target.checked)}
          />
          {t('api.aiArrange')}{!aiAssistEnabled ? '（设置已关闭，将按规则编排）' : ''}
        </label>
        <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
          {aiAssistEnabled ? t('api.aiArrangeHint') : '当前已关闭内置 AI 辅助，将使用接口参数依赖规则自动编排步骤与依赖。'}
        </div>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 4 }}>
          <button onClick={onClose} style={btnStyle()}>{t('common.cancel')}</button>
          <button onClick={submit} disabled={submitting} style={btnStyle(true, submitting)}>
            {submitting && <Loader2 size={12} strokeWidth={1.5} />}
            {submitting ? t('api.composing') : t('api.createCase')}
          </button>
        </div>
      </div>
    </Modal>
  );
}

/** 编辑用例：重命名用例、步骤可增删改名、可从接口资产追加步骤并保存。 */
export function CaseEditorDialog({
  open,
  caseItem,
  onClose,
  onSaved,
}: {
  open: boolean;
  caseItem: ApiCase | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const currentProjectId = useProjectStore((s) => s.currentProjectId);
  const aiAssistEnabled = useCapabilitiesStore((s) => s.aiAssistEnabled);
  const { fetchAssets, composeSteps } = useAssetStore();
  const updateCase = useRunStore((s) => s.updateCase);

  const [title, setTitle] = useState('');
  const [content, setContent] = useState<ApiContent>({ base_url: '', steps: [] });
  const [saving, setSaving] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [assets, setAssets] = useState<ApiAsset[]>([]);
  const [loadingAssets, setLoadingAssets] = useState(false);
  const [picked, setPicked] = useState<number[]>([]);
  const [importing, setImporting] = useState(false);

  useEffect(() => {
    if (!open || !caseItem) return;
    setTitle(caseItem.title || '');
    setPickerOpen(false);
    setContent({
      base_url: caseItem.content?.base_url || '',
      steps: (caseItem.content?.steps as ApiStep[]) || [],
    });
  }, [open, caseItem]);

  const openPicker = () => {
    setPicked([]);
    setPickerOpen(true);
    setImporting(false);
    setLoadingAssets(true);
    fetchAssets(currentProjectId)
      .then(setAssets)
      .catch((e) => toast.error(String(e)))
      .finally(() => setLoadingAssets(false));
  };

  const importSelected = async () => {
    if (picked.length === 0) {
      toast.error(t('api.pickAssetRequired'));
      return;
    }
    setImporting(true);
    try {
      const result = await composeSteps(picked, title.trim() || caseItem?.title || '', aiAssistEnabled);
      setContent((prev) => ({
        base_url: prev.base_url || result.base_url,
        steps: [...prev.steps, ...(result.steps as ApiStep[])],
      }));
      toast.success(t('api.assetImportDone', { count: result.steps.length }));
      setPickerOpen(false);
    } catch (e) {
      toast.error(String(e));
    } finally {
      setImporting(false);
    }
  };

  const save = async () => {
    if (!caseItem) return;
    if (!title.trim()) {
      toast.error(t('api.caseNameRequired'));
      return;
    }
    setSaving(true);
    try {
      await updateCase(caseItem.id, {
        title: title.trim(),
        content: { base_url: content.base_url, steps: content.steps },
      });
      toast.success(t('api.caseSaved'));
      onSaved();
      onClose();
    } catch (e) {
      toast.error(String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal open={open} onOpenChange={(o) => { if (!o) onClose(); }} title={t('api.editCase')} width="min(760px, 94vw)">
      <div style={{ padding: '0 20px 20px', maxHeight: pickerOpen ? '36vh' : '72vh', overflow: 'auto', display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{t('api.caseName')}</div>
        <input style={inputStyle} value={title} onChange={(e) => setTitle(e.target.value)} />
        <ApiStepsEditor
          content={content}
          onChange={setContent}
          hideBaseUrl
          extraActions={(
            <button onClick={openPicker} style={btnStyle()}>
              {t('api.importAssets')}
            </button>
          )}
        />
        {!pickerOpen && (
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
            <button onClick={onClose} style={btnStyle()}>{t('common.cancel')}</button>
            <button onClick={save} disabled={saving} style={btnStyle(true, saving)}>
              {saving && <Loader2 size={12} strokeWidth={1.5} />}
              {saving ? t('api.saving') : t('common.save')}
            </button>
          </div>
        )}
      </div>

      {pickerOpen && (
        <div style={{ borderTop: '1px solid var(--bg-elevated)', padding: '12px 20px 20px' }}>
          <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginBottom: 8, display: 'flex', justifyContent: 'space-between' }}>
            <span>{t('api.importAssetsHint')}</span>
            <span>{t('api.assetSelectedCount', { count: picked.length })}</span>
          </div>
          <AssetPicker
            assets={assets}
            selected={picked}
            loading={loadingAssets}
            onToggle={(id) => setPicked((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))}
          />
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 10 }}>
            <button onClick={() => setPickerOpen(false)} style={btnStyle()}>{t('common.cancel')}</button>
            <button onClick={importSelected} disabled={importing} style={btnStyle(true, importing)}>
              {importing && <Loader2 size={12} strokeWidth={1.5} />}
              {importing ? t('api.composing') : t('api.importSelected')}
            </button>
          </div>
        </div>
      )}
    </Modal>
  );
}
