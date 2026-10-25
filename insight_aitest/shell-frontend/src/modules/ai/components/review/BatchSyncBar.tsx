import { useState } from 'react';
import { useTranslation, Trans } from 'react-i18next';
import { Check, FileSpreadsheet, FolderInput } from 'lucide-react';
import { primaryButton, text } from '../agentStyles';
import { ImportToProjectModal } from '../../../testcase/components/ImportToProjectModal';
import { exportTestCasesToExcel } from '../../../testcase/utils/exportExcel';

/** 用例审阅底部同步栏：展示生成用例统计，提供「导入到项目」和「导出到 Excel」两个选项。
 */
export function BatchSyncBar({
  selectedCount,
  totalCount,
  syncStatus,
  caseIds,
  batchId,
  onImportSuccess,
}: {
  selectedCount: number;
  totalCount: number;
  syncStatus: 'idle' | 'confirming' | 'syncing' | 'done';
  caseIds: number[];
  batchId: string | null;
  onImportSuccess?: (projectId: number) => void;
}) {
  const [importModalOpen, setImportModalOpen] = useState(false);
  const { t } = useTranslation();

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        flexWrap: 'wrap',
        padding: '10px 14px',
        borderTop: '1px solid var(--border)',
        background: 'var(--bg-card)',
        borderRadius: '0 0 12px 12px',
      }}
    >
      <span style={{ fontSize: 12, color: text.secondary }}>
        <Trans
          t={t}
          i18nKey="ai.selectedCountLabel"
          components={{ b: <b style={{ color: text.primary }} /> }}
          values={{ selected: selectedCount, total: totalCount }}
        />
        <span style={{ marginLeft: 6, fontSize: 11, color: text.muted }}>
          {t('testcase.notImportedYetHint', '（生成用例尚未入库，请选择导入或导出）')}
        </span>
      </span>

      <div style={{ flex: 1 }} />

      {syncStatus === 'done' ? (
        <span style={{ fontSize: 12, color: text.success, display: 'inline-flex', alignItems: 'center', gap: 4 }}>
          <Check size={14} strokeWidth={2} /> {t('testcase.importDone', '已成功导入项目')}
        </span>
      ) : (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {/* 导出到 Excel */}
          <button
            onClick={() => exportTestCasesToExcel({ batch_id: batchId ?? undefined, case_ids: caseIds })}
            disabled={selectedCount === 0}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 5,
              padding: '6px 14px',
              borderRadius: 6,
              background: 'var(--bg-base)',
              border: '1px solid var(--border)',
              color: 'var(--text-primary)',
              fontSize: 12,
              cursor: selectedCount === 0 ? 'not-allowed' : 'pointer',
              opacity: selectedCount === 0 ? 0.5 : 1,
            }}
          >
            <FileSpreadsheet size={14} strokeWidth={1.8} style={{ color: 'var(--success, #10b981)' }} />
            {t('testcase.exportToExcel', '导出到 Excel（TAPD）')}
          </button>

          {/* 导入到项目 */}
          <button
            onClick={() => setImportModalOpen(true)}
            disabled={selectedCount === 0}
            style={{
              ...primaryButton,
              display: 'inline-flex',
              alignItems: 'center',
              gap: 5,
              padding: '6px 16px',
              fontSize: 12,
              opacity: selectedCount === 0 ? 0.5 : 1,
              cursor: selectedCount === 0 ? 'not-allowed' : 'pointer',
            }}
          >
            <FolderInput size={14} strokeWidth={1.8} />
            {t('testcase.importToProject', '导入到项目')}
          </button>
        </div>
      )}

      {/* 导入到项目弹窗 */}
      <ImportToProjectModal
        open={importModalOpen}
        caseIds={caseIds}
        batchId={batchId}
        onClose={() => setImportModalOpen(false)}
        onSuccess={(pid) => {
          onImportSuccess?.(pid);
        }}
      />
    </div>
  );
}
