import { useState, useEffect } from 'react';
import { Zap, FileText, AlertCircle } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { text, RADIUS } from './agentStyles';
import { useProjectStore } from '../../../shared/store/projectStore';
import { DocPickerModal } from './DocPickerModal';

export type KbMode = 'off' | 'auto' | 'manual';

interface Props {
  mode: KbMode;
  onModeChange: (mode: KbMode) => void;
  selectedDocIds: number[];
  onDocIdsChange: (ids: number[]) => void;
}

const BASE = '/api/modules/ai/tasks';

export function KbToggle({ mode, onModeChange, selectedDocIds, onDocIdsChange }: Props) {
  const { t } = useTranslation();
  const { currentProjectId } = useProjectStore();
  const [stats, setStats] = useState({ total_docs: 0, total_chunks: 0, vector_enabled: false });
  const [modalOpen, setModalOpen] = useState(false);

  useEffect(() => {
    const params = currentProjectId != null ? `?project_id=${currentProjectId}` : '';
    fetch(`${BASE}/kb/stats${params}`)
      .then(r => r.ok ? r.json() : { total_docs: 0, total_chunks: 0, vector_enabled: false })
      .then(setStats)
      .catch(() => setStats({ total_docs: 0, total_chunks: 0, vector_enabled: false }));
  }, [currentProjectId]);

  const vectorReady = stats.vector_enabled;
  const iconSize = 13;

  return (
    <div style={{ display: 'inline-flex', alignItems: 'center', position: 'relative' }}>
      {/* 状态提示语：绝对定位悬浮在组件上方，不挤压高度 */}
      <div
        style={{
          position: 'absolute',
          bottom: 'calc(100% + 4px)',
          left: 0,
          whiteSpace: 'nowrap',
          fontSize: 10,
          lineHeight: '12px',
          pointerEvents: 'none',
        }}
      >
        {mode === 'auto' && (
          <span style={{ color: vectorReady ? text.accent : 'var(--warning)' }}>
            {vectorReady
              ? <>✅ {t('ai.kbVectorReady')} · {stats.total_docs} {t('ai.kbDocs')} / {stats.total_chunks} {t('ai.kbChunks')}</>
              : <>⚠️ {t('ai.kbVectorNotReady')}</>
            }
          </span>
        )}

        {mode === 'manual' && (
          <span style={{ color: selectedDocIds.length > 0 ? text.accent : 'var(--text-muted)' }}>
            {selectedDocIds.length > 0
              ? <>📎 已选择 <strong style={{ color: 'var(--primary, #3b82f6)' }}>{selectedDocIds.length}</strong> {t('ai.kbDocs')}</>
              : <>📎 未选文档 (点击手动选库)</>
            }
          </span>
        )}
      </div>

      {/* 按钮栏 */}
      <div style={{ display: 'inline-flex', alignItems: 'center', gap: 4, height: 28 }}>
        <div style={{
          display: 'inline-flex',
          height: 28,
          boxSizing: 'border-box',
          border: '1px solid var(--border-strong)',
          borderRadius: RADIUS.sm,
          overflow: 'hidden',
        }}>
          {/* 自动 (知识库) */}
          <button
            onClick={() => onModeChange('auto')}
            title={vectorReady ? t('ai.kbAutoTitle') : t('ai.kbAutoNeedConfig')}
            style={btnStyle(mode === 'auto', !vectorReady)}
          ><Zap size={iconSize} strokeWidth={1.5} /> {t('ai.kbAuto')}</button>

          {/* 手动选库 */}
          <button
            onClick={() => {
              if (mode !== 'manual') {
                onModeChange('manual');
              }
              setModalOpen(true);
            }}
            title={t('ai.kbManualTitle')}
            style={btnStyle(mode === 'manual', false)}
          >
            <FileText size={iconSize} strokeWidth={1.5} />
            {t('ai.kbManual')}
            {selectedDocIds.length > 0 ? ` (${selectedDocIds.length})` : ''}
          </button>
        </div>

        {!vectorReady && mode === 'auto' && (
          <AlertCircle size={iconSize} strokeWidth={1.5} style={{ color: 'var(--warning, var(--accent))' }} />
        )}
      </div>

      {/* 弹窗选择文档（目录树 + 级联全选） */}
      <DocPickerModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        selectedDocIds={selectedDocIds}
        onConfirm={onDocIdsChange}
      />
    </div>
  );
}

function btnStyle(active: boolean, warning: boolean): React.CSSProperties {
  return {
    height: '100%',
    padding: '0 8px',
    fontSize: 11,
    cursor: 'pointer',
    border: 'none',
    borderRight: '1px solid var(--border-strong)',
    background: active
      ? (warning ? 'rgba(250,173,20,0.14)' : 'rgba(16,185,129,0.14)')
      : 'transparent',
    color: active
      ? (warning ? 'var(--warning)' : 'var(--accent)')
      : 'var(--text-muted)',
    fontWeight: active ? 600 : 400,
    transition: 'all 0.15s cubic-bezier(0.16,1,0.3,1)',
    fontFamily: 'inherit',
    display: 'inline-flex',
    alignItems: 'center',
    boxSizing: 'border-box',
    gap: 3,
  };
}
