import { useState, useEffect, type ReactNode } from 'react';
import { Layers, X, Info } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { useProjectStore, type ProjectVersion } from '../../../shared/store/projectStore';
import { useCaseStore, type FolderNode } from '../store/caseStore';

interface BatchAssignModalProps {
  open: boolean;
  caseIds: number[];
  onClose: () => void;
  onSuccess: () => void;
}

type AssignValue = 'keep' | number;

export function BatchAssignModal({
  open,
  caseIds,
  onClose,
  onSuccess,
}: BatchAssignModalProps) {
  const { t } = useTranslation();
  const { projects, versions: currentVersions, loadProjects, loadVersions } = useProjectStore();
  const { folders: currentFolders, selectedProjectId, batchAssign } = useCaseStore();

  const [projectId, setProjectId] = useState<AssignValue>('keep');
  const [versionId, setVersionId] = useState<AssignValue>('keep');
  const [folderId, setFolderId] = useState<AssignValue>('keep');

  const [projectVersions, setProjectVersions] = useState<ProjectVersion[]>([]);
  const [projectFolders, setProjectFolders] = useState<FolderNode[]>([]);
  const [loadingExtras, setLoadingExtras] = useState(false);
  const [saving, setSaving] = useState(false);

  // 打开弹窗时重置表单为默认 "保持不变"
  useEffect(() => {
    if (open) {
      loadProjects();
      setProjectId('keep');
      setVersionId('keep');
      setFolderId('keep');
      if (selectedProjectId !== null) {
        loadVersions(selectedProjectId);
      }
    }
  }, [open, selectedProjectId, loadProjects, loadVersions]);

  // 当选择的项目变化时，若选择了具体项目，动态加载该项目专属的版本和目录列表
  useEffect(() => {
    if (!open) return;

    if (projectId === 'keep') {
      setProjectVersions([]);
      setProjectFolders([]);
      return;
    }

    if (projectId === -1) {
      // 清空项目，同时版本和目录自动设为清空
      setProjectVersions([]);
      setProjectFolders([]);
      setVersionId(-1);
      setFolderId(-1);
      return;
    }

    // 选择了新的具体项目，拉取该项目的版本与目录
    let isMounted = true;
    setLoadingExtras(true);
    // 切换到新项目时，建议默认将版本和目录重置为未绑定/未分类
    setVersionId(-1);
    setFolderId(-1);

    Promise.all([
      fetch(`/api/platform/projects/${projectId}/versions`)
        .then((r) => (r.ok ? r.json() : []))
        .catch(() => []),
      fetch(`/api/modules/testcase/testcases/folders?project_id=${projectId}`)
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
  }, [open, projectId]);

  if (!open) return null;

  // 计算可供选择的版本列表
  const availableVersions: ProjectVersion[] =
    projectId === 'keep' ? (selectedProjectId !== null ? currentVersions : []) : projectVersions;

  // 计算可供选择的目录列表
  const availableFolders: FolderNode[] =
    projectId === 'keep' ? currentFolders : projectFolders;

  const handleConfirm = async () => {
    if (projectId === 'keep' && versionId === 'keep' && folderId === 'keep') {
      toast.info(t('testcase.noChangesMade', '未修改任何归属属性'));
      onClose();
      return;
    }

    setSaving(true);
    try {
      const payload: { project_id?: number | null; version_id?: number | null; folder_id?: number | null } = {};
      if (projectId !== 'keep') {
        payload.project_id = projectId === -1 ? -1 : projectId;
      }
      if (versionId !== 'keep') {
        payload.version_id = versionId === -1 ? -1 : versionId;
      }
      if (folderId !== 'keep') {
        payload.folder_id = folderId === -1 ? -1 : folderId;
      }

      await batchAssign(caseIds, payload);
      toast.success(t('testcase.batchAssignmentSuccess', '成功修改 {{count}} 条用例归属', { count: caseIds.length }));
      onSuccess();
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
        zIndex: 2000,
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
          width: 480,
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
        {/* 标题栏 */}
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
            <Layers size={16} style={{ color: 'var(--accent)' }} />
            {t('testcase.batchAssignTitle', '批量修改用例归属')}
          </span>
          <button
            onClick={onClose}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)' }}
          >
            <X size={16} />
          </button>
        </div>

        {/* 内容表单 */}
        <div style={{ padding: 20, display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
            {t('testcase.batchAssignSubtitle', '已勾选 {{count}} 条用例，可批量设置所属项目、版本或目录：', {
              count: caseIds.length,
            })}
          </div>

          {/* 1. 所属项目 */}
          <div>
            <label style={{ display: 'block', fontSize: 12, color: 'var(--text-muted)', marginBottom: 6 }}>
              {t('testcase.belongProject', '所属项目')}
            </label>
            <select
              value={projectId}
              onChange={(e) => {
                const val = e.target.value;
                setProjectId(val === 'keep' ? 'keep' : Number(val));
              }}
              style={selectStyle}
            >
              <option value="keep">{t('testcase.keepUnchanged', '保持不变（不修改所属项目）')}</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>

          {/* 2. 所属版本 */}
          <div>
            <label style={{ display: 'block', fontSize: 12, color: 'var(--text-muted)', marginBottom: 6 }}>
              {t('testcase.belongVersion', '所属版本')}
            </label>
            <select
              value={versionId}
              disabled={projectId === -1 || (projectId === 'keep' && selectedProjectId === null && availableVersions.length === 0)}
              onChange={(e) => {
                const val = e.target.value;
                setVersionId(val === 'keep' ? 'keep' : Number(val));
              }}
              style={{
                ...selectStyle,
                opacity: projectId === -1 ? 0.6 : 1,
              }}
            >
              <option value="keep">{t('testcase.keepVersionUnchanged', '保持不变（不修改版本）')}</option>
              <option value="-1">{t('testcase.noVersion', '未绑定版本（清空版本）')}</option>
              {availableVersions.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.name}
                </option>
              ))}
            </select>
            {projectId === 'keep' && selectedProjectId === null && availableVersions.length === 0 && (
              <span style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4, display: 'block' }}>
                {t('testcase.selectProjectFirstForVersion', '（当前为全部项目视图，如需分配版本请先在上方指定具体项目）')}
              </span>
            )}
          </div>

          {/* 3. 所属目录 */}
          <div>
            <label style={{ display: 'block', fontSize: 12, color: 'var(--text-muted)', marginBottom: 6 }}>
              {t('testcase.belongFolder', '所属目录')}
            </label>
            <select
              value={folderId}
              disabled={projectId === -1 || loadingExtras}
              onChange={(e) => {
                const val = e.target.value;
                setFolderId(val === 'keep' ? 'keep' : Number(val));
              }}
              style={{
                ...selectStyle,
                opacity: projectId === -1 ? 0.6 : 1,
              }}
            >
              <option value="keep">{t('testcase.keepFolderUnchanged', '保持不变（不修改目录）')}</option>
              <option value="-1">{t('testcase.unclassifiedFolder', '未分类（移出原目录）')}</option>
              {renderFolderOptions(availableFolders)}
            </select>
          </div>

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
                'testcase.batchAssignTips',
                '设为「保持不变」的属性将保留原有用例的归属值；切换至新项目时，建议同时确认或重置目标版本与目录。'
              )}
            </span>
          </div>
        </div>

        {/* 底部按钮 */}
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
            disabled={saving}
            style={{
              padding: '6px 16px',
              borderRadius: 6,
              border: 'none',
              background: 'var(--accent)',
              color: '#fff',
              fontSize: 13,
              fontWeight: 500,
              cursor: saving ? 'not-allowed' : 'pointer',
              opacity: saving ? 0.6 : 1,
            }}
          >
            {saving ? t('common.saving', '保存中...') : t('common.confirm', '确认修改')}
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

