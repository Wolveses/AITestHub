import { useState, useEffect, type ReactNode } from 'react';
import { FolderInput, X, Info } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { useProjectStore, type ProjectVersion } from '../../../shared/store/projectStore';
import { useCaseStore, type FolderNode } from '../store/caseStore';

interface ImportToProjectModalProps {
  open: boolean;
  caseIds: number[];
  batchId?: string | null;
  onClose: () => void;
  onSuccess: (projectId: number) => void;
}

export function ImportToProjectModal({
  open,
  caseIds,
  batchId,
  onClose,
  onSuccess,
}: ImportToProjectModalProps) {
  const { t } = useTranslation();
  const { projects, loadProjects } = useProjectStore();
  const selectedProjectId = useCaseStore((s) => s.selectedProjectId);

  const [targetProjectId, setTargetProjectId] = useState<number | ''>('');
  const [targetVersionId, setTargetVersionId] = useState<number | ''>('');
  const [targetFolderId, setTargetFolderId] = useState<number | ''>('');
  const [deleteUnselected, setDeleteUnselected] = useState(true);

  const [projectVersions, setProjectVersions] = useState<ProjectVersion[]>([]);
  const [projectFolders, setProjectFolders] = useState<FolderNode[]>([]);
  const [loadingExtras, setLoadingExtras] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) {
      loadProjects();
      const initialPid = selectedProjectId ?? (projects.length > 0 ? projects[0].id : '');
      setTargetProjectId(initialPid);
      setTargetVersionId('');
      setTargetFolderId('');
      setDeleteUnselected(true);
    }
  }, [open, selectedProjectId, loadProjects, projects]);

  useEffect(() => {
    if (!open || targetProjectId === '') {
      setProjectVersions([]);
      setProjectFolders([]);
      return;
    }

    let isMounted = true;
    setLoadingExtras(true);

    Promise.all([
      fetch(`/api/platform/projects/${targetProjectId}/versions`)
        .then((r) => (r.ok ? r.json() : []))
        .catch(() => []),
      fetch(`/api/modules/testcase/testcases/folders?project_id=${targetProjectId}`)
        .then((r) => (r.ok ? r.json() : []))
        .catch(() => []),
    ]).then(([vers, folds]) => {
      if (isMounted) {
        setProjectVersions(Array.isArray(vers) ? vers : []);
        setProjectFolders(Array.isArray(folds) ? folds : []);
        setLoadingExtras(false);
      }
    });

    return () => {
      isMounted = false;
    };
  }, [open, targetProjectId]);

  if (!open) return null;

  const handleConfirm = async () => {
    if (targetProjectId === '') {
      toast.warning(t('testcase.selectTargetProjectWarning', '请选择目标项目'));
      return;
    }

    setSaving(true);
    try {
      const res = await fetch('/api/modules/testcase/testcases/batch-sync', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          case_ids: caseIds,
          project_id: Number(targetProjectId),
          version_id: targetVersionId === '' ? null : Number(targetVersionId),
          folder_id: targetFolderId === '' ? null : Number(targetFolderId),
          delete_unselected: Boolean(batchId && deleteUnselected),
          batch_id: batchId ?? null,
        }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: '导入失败' }));
        throw new Error(err.detail || '导入失败');
      }

      toast.success(t('testcase.importToProjectSuccess', '成功导入 {{count}} 条用例到项目', { count: caseIds.length }));
      onSuccess(Number(targetProjectId));
      onClose();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const renderFolderOptions = (nodes: FolderNode[], level = 0): ReactNode[] => {
    return nodes.flatMap((node) => [
      <option key={node.id} value={node.id}>
        {'\u00A0'.repeat(level * 4)}📁 {node.name}
      </option>,
      ...(node.children ? renderFolderOptions(node.children, level + 1) : []),
    ]);
  };

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 2100,
        background: 'rgba(0,0,0,0.5)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 16,
      }}
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: 460,
          maxWidth: '100%',
          background: 'var(--bg-base)',
          borderRadius: 8,
          boxShadow: '0 10px 25px rgba(0,0,0,0.25)',
          border: '1px solid var(--border)',
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        {/* 标题 */}
        <div
          style={{
            padding: '14px 16px',
            borderBottom: '1px solid var(--border)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <span
            style={{
              fontSize: 14,
              fontWeight: 600,
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              color: 'var(--text-primary)',
            }}
          >
            <FolderInput size={16} style={{ color: 'var(--accent)' }} />
            {t('testcase.importToProjectTitle', '导入用例到项目')}
          </span>
          <button
            onClick={onClose}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)' }}
          >
            <X size={16} />
          </button>
        </div>

        {/* 表单内容 */}
        <div style={{ padding: 20, display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
            {t('testcase.importToProjectHint', '已选择 {{count}} 条生成的用例，请指定目标项目以完成入库：', {
              count: caseIds.length,
            })}
          </div>

          {/* 目标项目（必填） */}
          <div>
            <label style={{ display: 'block', fontSize: 12, color: 'var(--text-muted)', marginBottom: 6 }}>
              {t('testcase.targetProject', '目标项目')} <span style={{ color: 'var(--error, #ef4444)' }}>*</span>
            </label>
            <select
              value={targetProjectId}
              onChange={(e) => setTargetProjectId(e.target.value === '' ? '' : Number(e.target.value))}
              style={selectStyle}
            >
              <option value="">{t('testcase.selectProjectPlaceholder', '请选择目标项目...')}</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>

          {/* 目标版本（可选） */}
          <div>
            <label style={{ display: 'block', fontSize: 12, color: 'var(--text-muted)', marginBottom: 6 }}>
              {t('testcase.targetVersion', '目标版本')}
            </label>
            <select
              value={targetVersionId}
              disabled={targetProjectId === '' || loadingExtras}
              onChange={(e) => setTargetVersionId(e.target.value === '' ? '' : Number(e.target.value))}
              style={{
                ...selectStyle,
                opacity: targetProjectId === '' ? 0.6 : 1,
              }}
            >
              <option value="">{t('testcase.noVersion', '未绑定版本')}</option>
              {projectVersions.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.name}
                </option>
              ))}
            </select>
          </div>

          {/* 目标目录（可选） */}
          <div>
            <label style={{ display: 'block', fontSize: 12, color: 'var(--text-muted)', marginBottom: 6 }}>
              {t('testcase.targetFolder', '目标目录')}
            </label>
            <select
              value={targetFolderId}
              disabled={targetProjectId === '' || loadingExtras}
              onChange={(e) => setTargetFolderId(e.target.value === '' ? '' : Number(e.target.value))}
              style={{
                ...selectStyle,
                opacity: targetProjectId === '' ? 0.6 : 1,
              }}
            >
              <option value="">{t('testcase.unclassifiedFolder', '未分类（根目录）')}</option>
              {renderFolderOptions(projectFolders)}
            </select>
          </div>

          {/* 未选中的清理选项（仅在批次存在时展示） */}
          {batchId && (
            <label
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
                fontSize: 12,
                color: 'var(--text-secondary)',
                cursor: 'pointer',
                marginTop: 2,
              }}
            >
              <input
                type="checkbox"
                checked={deleteUnselected}
                onChange={(e) => setDeleteUnselected(e.target.checked)}
                style={{ accentColor: 'var(--accent)', cursor: 'pointer' }}
              />
              {t('testcase.cleanUnselectedDrafts', '同时清理本生成批次中未勾选的草稿用例')}
            </label>
          )}

          {/* 提示信息 */}
          <div
            style={{
              padding: '8px 12px',
              borderRadius: 6,
              background: 'var(--bg-card)',
              border: '1px solid var(--border)',
              display: 'flex',
              alignItems: 'flex-start',
              gap: 8,
              fontSize: 12,
              color: 'var(--text-muted)',
              lineHeight: 1.5,
            }}
          >
            <Info size={14} style={{ color: 'var(--accent)', flexShrink: 0, marginTop: 2 }} />
            <span>
              {t(
                'testcase.importRuleNotice',
                '系统规则要求用例必须归属明确的项目。确认导入后，用例状态将自动转为就绪并进入该项目的用例库。'
              )}
            </span>
          </div>
        </div>

        {/* 底部操作按钮 */}
        <div
          style={{
            padding: '12px 16px',
            borderTop: '1px solid var(--border)',
            background: 'var(--bg-card)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'flex-end',
            gap: 10,
          }}
        >
          <button
            onClick={onClose}
            disabled={saving}
            style={{
              padding: '6px 14px',
              borderRadius: 6,
              border: '1px solid var(--border)',
              background: 'var(--bg-base)',
              color: 'var(--text-primary)',
              fontSize: 13,
              cursor: 'pointer',
            }}
          >
            {t('common.cancel', '取消')}
          </button>
          <button
            onClick={handleConfirm}
            disabled={saving || targetProjectId === ''}
            style={{
              padding: '6px 16px',
              borderRadius: 6,
              border: 'none',
              background: 'var(--accent)',
              color: '#fff',
              fontSize: 13,
              fontWeight: 500,
              cursor: saving || targetProjectId === '' ? 'not-allowed' : 'pointer',
              opacity: saving || targetProjectId === '' ? 0.6 : 1,
            }}
          >
            {saving ? t('common.importing', '导入中...') : t('testcase.confirmImport', '确认导入')}
          </button>
        </div>
      </div>
    </div>
  );
}

const selectStyle: React.CSSProperties = {
  width: '100%',
  background: 'var(--bg-card)',
  border: '1px solid var(--border)',
  color: 'var(--text-primary)',
  padding: '8px 10px',
  borderRadius: 6,
  fontSize: 13,
  outline: 'none',
  cursor: 'pointer',
};

