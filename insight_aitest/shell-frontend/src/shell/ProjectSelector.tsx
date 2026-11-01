import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { FolderKanban } from 'lucide-react';
import { useProjectStore } from '../shared/store/projectStore';
import { useIsMobile } from '../shared/hooks/useIsMobile';

/**
 * 全局 Project 切换器，嵌入 TopBar。
 * 仅在项目相关页面生效（用例库、缺陷库、自动化、用例管理等），全局资源（知识库、Agent 对话）不受影响。
 */
export function ProjectSelector() {
  const { projects, currentProjectId, loadProjects, setProject } = useProjectStore();
  const { i18n } = useTranslation();
  const isMobile = useIsMobile();

  useEffect(() => {
    loadProjects();
  }, [loadProjects]);

  const selectStyle: React.CSSProperties = {
    background: 'var(--bg-card)',
    border: '1px solid var(--border)',
    color: 'var(--text-primary)',
    padding: '4px 10px',
    borderRadius: 6,
    fontSize: 13,
    fontWeight: 500,
    cursor: 'pointer',
    outline: 'none',
    maxWidth: isMobile ? 120 : 180,
  };

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 5,
          color: 'var(--text-secondary)',
          fontSize: 13,
          fontWeight: 500,
          whiteSpace: 'nowrap',
        }}
      >
        <FolderKanban size={15} style={{ opacity: 0.85 }} />
        {!isMobile && <span>{i18n.language === 'en-US' ? 'Project' : '项目'}:</span>}
      </div>
      <select
        value={currentProjectId ?? ''}
        onChange={(e) => {
          const v = e.target.value;
          if (v) setProject(Number(v));
        }}
        style={selectStyle}
        title={i18n.language === 'en-US' ? 'Select project' : '选择项目'}
      >
        {projects.length === 0 ? (
          <option value="">{i18n.language === 'en-US' ? 'No projects' : '暂无项目'}</option>
        ) : (
          projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))
        )}
      </select>
    </div>
  );
}
