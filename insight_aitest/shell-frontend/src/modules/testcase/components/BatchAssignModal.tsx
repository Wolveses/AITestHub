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

export function BatchAssignModal({
  open,
  caseIds,
  onClose,
  onSuccess,
}: BatchAssignModalProps) {
  const { t } = useTranslation();
  const { projects, loadProjects } = useProjectStore();
  const { batchAssign } = useCaseStore();

  // 项目为必选项（null = 尚未选择）；版本/目录 null 表示「空」（--）
  const [projectId, setProjectId] = useState<number | null>(null);
  const [versionId, setVersionId] = useState<number | null>(null);
  const [folderId, setFolderId] = useState<number | null>(null);

  const [projectVersions, setProjectVersions] = useState<ProjectVersion[]>([]);
  const [projectFolders, setProjectFolders] = useState<FolderNode[]>([]);
  const [loadingExtras, setLoadingExtras] = useState(false);
  const [saving, setSaving] = useState(false);

  // caseIds 每次渲染都是新数组，依赖用稳定的字符串
  const caseIdKey = caseIds.join(',');

  // 打开弹窗：默认回显所选用例当前的归属值
  useEffect(() => {
    if (!open) return;
    loadProjects();

    const ids = caseIdKey ? caseIdKey.split(',').map(Number) : [];
    const selected = useCaseStore.getState().cases.filter((c) => ids.includes(c.id));
    // 所有选中用例该属性一致时返回该值；不一致返回 undefined
    const commonOf = (key: 'project_id' | 'version_id' | 'folder_id') => {
      if (!selected.length) return undefined;
      const first = selected[0][key];
      return selected.every((c) => c[key] === first) ? first : undefined;
    };

    const commonProject = commonOf('project_id');
    const pid = commonProject === undefined ? null : commonProject;

    setProjectId(pid);
    if (pid === null) {
      // 未归属项目（或跨项目混选）：版本/目录无归属上下文
      setVersionId(null);
      setFolderId(null);
    } else {
      setVersionId(commonOf('version_id') ?? null);
      setFolderId(commonOf('folder_id') ?? null);
    }
  }, [open, caseIdKey, loadProjects]);

  // 项目确定后加载该项目的版本与目录（切换项目时在 onChange 中重置版本/目录）
  useEffect(() => {
    if (!open || projectId === null) {
      setProjectVersions([]);
      setProjectFolders([]);
      return;
    }

    let isMounted = true;
    setLoadingExtras(true);
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

  const handleConfirm = async () => {
    if (projectId === null) {
      toast.error(t('testcase.selectProjectRequired', '请选择所属项目'));
      return;
    }

    setSaving(true);
    try {
      // 版本/目录为 null 时传 -1，表示置空
      await batchAssign(caseIds, {
        project_id: projectId,
        version_id: versionId ?? -1,
        folder_id: folderId ?? -1,
      });
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

          {/* 1. 所属项目（必选，仅展示系统中已添加的项目） */}
          <div>
            <label style={{ display: 'block', fontSize: 12, color: 'var(--text-muted)', marginBottom: 6 }}>
              {t('testcase.belongProject', '所属项目')}
            </label>
            <select
              value={projectId === null ? '' : String(projectId)}
              onChange={(e) => {
                setProjectId(e.target.value === '' ? null : Number(e.target.value));
                // 切换项目后，版本与目录的归属上下文变化，重置为空
                setVersionId(null);
                setFolderId(null);
              }}
              style={selectStyle}
            >
              {projectId === null && (
                <option value="" disabled>
                  {t('testcase.selectProjectPlaceholder', '请选择项目')}
                </option>
              )}
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
            {projectId === null && (
              <span style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4, display: 'block' }}>
                {t('testcase.selectProjectRequired', '请选择所属项目')}
              </span>
            )}
          </div>

          {/* 2. 所属版本（-- 表示空） */}
          <div>
            <label style={{ display: 'block', fontSize: 12, color: 'var(--text-muted)', marginBottom: 6 }}>
              {t('testcase.belongVersion', '所属版本')}
            </label>
            <select
              value={versionId === null ? '' : String(versionId)}
              disabled={projectId === null || loadingExtras}
              onChange={(e) => {
                setVersionId(e.target.value === '' ? null : Number(e.target.value));
              }}
              style={{
                ...selectStyle,
                opacity: projectId === null ? 0.6 : 1,
              }}
            >
              <option value="">--</option>
              {projectVersions.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.name}
                </option>
              ))}
            </select>
          </div>

          {/* 3. 所属目录（-- 表示空） */}
          <div>
            <label style={{ display: 'block', fontSize: 12, color: 'var(--text-muted)', marginBottom: 6 }}>
              {t('testcase.belongFolder', '所属目录')}
            </label>
            <select
              value={folderId === null ? '' : String(folderId)}
              disabled={projectId === null || loadingExtras}
              onChange={(e) => {
                setFolderId(e.target.value === '' ? null : Number(e.target.value));
              }}
              style={{
                ...selectStyle,
                opacity: projectId === null ? 0.6 : 1,
              }}
            >
              <option value="">--</option>
              {renderFolderOptions(projectFolders)}
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
                '确认后将覆盖所选用例的项目、版本与目录；版本、目录选择「--」表示置空。'
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
            disabled={saving || projectId === null}
            style={{
              padding: '6px 16px',
              borderRadius: 6,
              border: 'none',
              background: 'var(--accent)',
              color: '#fff',
              fontSize: 13,
              fontWeight: 500,
              cursor: saving || projectId === null ? 'not-allowed' : 'pointer',
              opacity: saving || projectId === null ? 0.6 : 1,
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
