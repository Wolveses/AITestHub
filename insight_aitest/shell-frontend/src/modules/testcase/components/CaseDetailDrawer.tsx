import { useState, useEffect, type CSSProperties, type ReactNode } from 'react';
import {
  X,
  Edit2,
  Check,
  RotateCcw,
  Tag,
  Clock,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { useCaseStore, type TestCase, type FolderNode } from '../store/caseStore';
import { useProjectStore } from '../../../shared/store/projectStore';
import { useConfirmStore } from '../../../shared/store/confirmStore';
import { FunctionalStepsEditor, type FunctionalContent } from './FunctionalStepsEditor';
import { ApiStepsEditor, type ApiContent } from './ApiStepsEditor';
import { UiStepsEditor, type UiContent } from './UiStepsEditor';
import { ContentRenderer } from './ContentRenderer';
import { formatCaseType, formatTestDesign, formatCaseSource } from '../utils/caseLabels';

interface CaseDetailDrawerProps {
  caseId: number | null;
  open: boolean;
  onClose: () => void;
}

const STATUS_COLOR: Record<string, string> = {
  draft: 'var(--warning, #f59e0b)',
  reviewed: 'var(--info, #3b82f6)',
  ready: 'var(--success, #10b981)',
  deprecated: 'var(--text-muted, #94a3b8)',
};

const PRIORITY_COLOR: Record<string, string> = {
  p0: 'var(--error, #ef4444)',
  p1: 'var(--warning, #f59e0b)',
  p2: 'var(--text-muted, #94a3b8)',
  p3: 'var(--border-strong, #64748b)',
};

export function CaseDetailDrawer({ caseId, open, onClose }: CaseDetailDrawerProps) {
  const { t } = useTranslation();
  const { confirm } = useConfirmStore();
  const { cases, folders, updateCase, updateStatus, deleteCase, assignCase } = useCaseStore();
  const { projects, versions, loadProjects, loadVersions } = useProjectStore();

  const currentCase = cases.find((c) => c.id === caseId) || null;
  const [isEditing, setIsEditing] = useState(false);
  const [form, setForm] = useState<TestCase | null>(null);
  const [saving, setSaving] = useState(false);

  // 当选中的用例改变时同步表单数据，且重置为只读模式
  useEffect(() => {
    if (currentCase) {
      setForm({ ...currentCase });
      setIsEditing(false);
    } else {
      setForm(null);
    }
  }, [currentCase]);

  useEffect(() => {
    if (open) {
      loadProjects();
      if (currentCase?.project_id) {
        loadVersions(currentCase.project_id);
      }
    }
  }, [open, currentCase?.project_id, loadProjects, loadVersions]);

  if (!open || !currentCase || !form) return null;

  const curProject = projects.find((p) => p.id === form.project_id);
  const curVersion = versions.find((v) => v.id === form.version_id);
  const curFolder = findFolderById(folders, form.folder_id);

  const setField = <K extends keyof TestCase>(key: K, value: TestCase[K]) => {
    setForm((prev) => (prev ? { ...prev, [key]: value } : prev));
  };

  const handleStartEdit = () => {
    setForm({ ...currentCase });
    setIsEditing(true);
  };

  const handleCancelEdit = () => {
    setForm({ ...currentCase });
    setIsEditing(false);
  };

  const handleSave = async () => {
    if (!form.title.trim()) {
      toast.error(t('testcase.titleRequired', '用例标题不能为空'));
      return;
    }
    setSaving(true);
    try {
      await updateCase(form.id, {
        title: form.title,
        description: form.description,
        priority: form.priority,
        test_design: form.test_design,
        preconditions: form.preconditions,
        content: form.content,
        tags: form.tags,
        project_id: form.project_id,
        version_id: form.version_id,
        folder_id: form.folder_id,
      });

      // 如果修改了归属，同步更新归属接口
      if (
        form.project_id !== currentCase.project_id ||
        form.version_id !== currentCase.version_id
      ) {
        await assignCase(
          form.id,
          form.project_id === null ? undefined : form.project_id,
          form.version_id === null ? undefined : form.version_id
        );
      }

      toast.success(t('testcase.saveSuccess', '用例保存成功'));
      setIsEditing(false);
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
        zIndex: 9998,
        background: 'rgba(0,0,0,0.4)',
        display: 'flex',
        justifyContent: 'flex-end',
        animation: 'fade-in 0.2s ease',
      }}
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: 620,
          maxWidth: '92vw',
          height: '100dvh',
          background: 'var(--bg-base)',
          borderLeft: '1px solid var(--border)',
          display: 'flex',
          flexDirection: 'column',
          boxShadow: '-8px 0 24px rgba(0,0,0,0.25)',
        }}
      >
        {/* 顶部标题与状态栏 */}
        <div
          style={{
            padding: '14px 20px',
            borderBottom: '1px solid var(--border)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            background: 'var(--bg-card)',
            gap: 12,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flex: 1, minWidth: 0 }}>
            <span
              style={{
                fontSize: 11,
                fontWeight: 700,
                color: PRIORITY_COLOR[form.priority] || 'var(--text-muted)',
                background: 'var(--bg-elevated)',
                padding: '2px 6px',
                borderRadius: 4,
                border: `1px solid ${PRIORITY_COLOR[form.priority] || 'var(--border)'}`,
              }}
            >
              {form.priority.toUpperCase()}
            </span>
            <span
              style={{
                fontSize: 11,
                color: STATUS_COLOR[form.status] || 'var(--text-muted)',
                background: 'var(--bg-elevated)',
                padding: '2px 6px',
                borderRadius: 4,
                border: `1px solid ${STATUS_COLOR[form.status] || 'var(--border)'}`,
              }}
            >
              {form.status}
            </span>
            <span
              style={{
                fontSize: 11,
                color: 'var(--text-secondary)',
                background: 'var(--bg-elevated)',
                padding: '2px 6px',
                borderRadius: 4,
              }}
            >
              {formatCaseType(form.type)}
            </span>
            <span
              style={{
                fontSize: 13,
                fontWeight: 600,
                color: 'var(--text-primary)',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
                flex: 1,
              }}
              title={form.title}
            >
              #{form.id} {form.title}
            </span>
          </div>

          {/* 模式操作按钮 */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
            {!isEditing ? (
              <button
                onClick={handleStartEdit}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 4,
                  padding: '5px 12px',
                  borderRadius: 6,
                  fontSize: 12,
                  fontWeight: 500,
                  background: 'var(--accent)',
                  color: '#fff',
                  border: 'none',
                  cursor: 'pointer',
                }}
              >
                <Edit2 size={13} strokeWidth={1.8} /> {t('testcase.edit', '编辑')}
              </button>
            ) : (
              <>
                <button
                  onClick={handleCancelEdit}
                  disabled={saving}
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 4,
                    padding: '5px 10px',
                    borderRadius: 6,
                    fontSize: 12,
                    background: 'transparent',
                    color: 'var(--text-secondary)',
                    border: '1px solid var(--border)',
                    cursor: 'pointer',
                  }}
                >
                  <RotateCcw size={13} strokeWidth={1.5} /> {t('testcase.cancel', '取消')}
                </button>
                <button
                  onClick={handleSave}
                  disabled={saving}
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 4,
                    padding: '5px 14px',
                    borderRadius: 6,
                    fontSize: 12,
                    fontWeight: 500,
                    background: 'var(--accent)',
                    color: '#fff',
                    border: 'none',
                    cursor: saving ? 'not-allowed' : 'pointer',
                    opacity: saving ? 0.7 : 1,
                  }}
                >
                  <Check size={14} strokeWidth={2} /> {saving ? t('testcase.saving', '保存中...') : t('testcase.save', '保存')}
                </button>
              </>
            )}

            <button
              onClick={onClose}
              style={{
                background: 'none',
                border: 'none',
                color: 'var(--text-muted)',
                cursor: 'pointer',
                display: 'inline-flex',
                alignItems: 'center',
                padding: 4,
                borderRadius: 4,
              }}
              onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--text-primary)')}
              onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--text-muted)')}
            >
              <X size={18} strokeWidth={1.5} />
            </button>
          </div>
        </div>

        {/* 内容滚动区域 */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '20px 24px', display: 'flex', flexDirection: 'column', gap: 20 }}>
          {!isEditing ? (
            /* ===== 只读查看模式 ===== */
            <>
              {/* 核心元数据卡片 */}
              <div
                style={{
                  background: 'var(--bg-card)',
                  border: '1px solid var(--border)',
                  borderRadius: 8,
                  padding: '14px 16px',
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))',
                  gap: 12,
                  fontSize: 12,
                }}
              >
                <div>
                  <span style={{ color: 'var(--text-muted)', display: 'block', marginBottom: 2 }}>所属项目</span>
                  <span style={{ color: 'var(--text-primary)', fontWeight: 500 }}>
                    {curProject?.name || '未指定'}
                  </span>
                </div>
                <div>
                  <span style={{ color: 'var(--text-muted)', display: 'block', marginBottom: 2 }}>所属版本</span>
                  <span style={{ color: 'var(--text-primary)', fontWeight: 500 }}>
                    {curVersion?.name || '未绑定'}
                  </span>
                </div>
                <div>
                  <span style={{ color: 'var(--text-muted)', display: 'block', marginBottom: 2 }}>所属目录</span>
                  <span style={{ color: 'var(--text-primary)', fontWeight: 500 }}>
                    {curFolder ? `📁 ${curFolder.name}` : '未分类'}
                  </span>
                </div>
                <div>
                  <span style={{ color: 'var(--text-muted)', display: 'block', marginBottom: 2 }}>测试设计</span>
                  <span style={{ color: 'var(--text-primary)', fontWeight: 500 }}>
                    {formatTestDesign(form.test_design)}
                  </span>
                </div>
                <div>
                  <span style={{ color: 'var(--text-muted)', display: 'block', marginBottom: 2 }}>用例来源</span>
                  <span style={{ color: 'var(--text-secondary)' }}>
                    {formatCaseSource(form.source)}
                  </span>
                </div>
                <div>
                  <span style={{ color: 'var(--text-muted)', display: 'block', marginBottom: 2 }}>最近执行结果</span>
                  <span style={{ color: form.last_result === 'passed' ? 'var(--success)' : 'var(--text-secondary)', fontWeight: 500 }}>
                    {form.last_result || '未执行'}
                  </span>
                </div>
              </div>

              {/* 前置条件 */}
              <div>
                <h4 style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 6 }}>
                  前置条件
                </h4>
                <div
                  style={{
                    background: 'var(--bg-card)',
                    border: '1px solid var(--border)',
                    borderRadius: 6,
                    padding: '8px 12px',
                    fontSize: 13,
                    color: form.preconditions ? 'var(--text-primary)' : 'var(--text-muted)',
                  }}
                >
                  {form.preconditions || '无'}
                </div>
              </div>

              {/* 用例描述（若有） */}
              {form.description && (
                <div>
                  <h4 style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 6 }}>
                    用例描述
                  </h4>
                  <div
                    style={{
                      background: 'var(--bg-card)',
                      border: '1px solid var(--border)',
                      borderRadius: 6,
                      padding: '8px 12px',
                      fontSize: 13,
                      color: 'var(--text-primary)',
                      whiteSpace: 'pre-wrap',
                    }}
                  >
                    {form.description}
                  </div>
                </div>
              )}

              {/* 测试步骤展示 */}
              <div>
                <h4 style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 8 }}>
                  测试步骤与预期
                </h4>
                {form.type === 'functional' ? (
                  <ReadOnlyFunctionalSteps content={form.content as unknown as FunctionalContent} />
                ) : form.type === 'api' ? (
                  <ReadOnlyApiSteps content={form.content as unknown as ApiContent} />
                ) : (
                  <ContentRenderer type={form.type} content={form.content} />
                )}
              </div>

              {/* 标签 */}
              {form.tags && form.tags.length > 0 && (
                <div>
                  <h4 style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 6, display: 'flex', alignItems: 'center', gap: 4 }}>
                    <Tag size={13} /> 标签
                  </h4>
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                    {form.tags.map((t, idx) => (
                      <span
                        key={idx}
                        style={{
                          fontSize: 11,
                          padding: '2px 8px',
                          borderRadius: 999,
                          background: 'var(--bg-card)',
                          border: '1px solid var(--border)',
                          color: 'var(--text-secondary)',
                        }}
                      >
                        {t}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </>
          ) : (
            /* ===== 编辑模式 ===== */
            <>
              {/* 用例标题 */}
              <div>
                <label style={{ display: 'block', fontSize: 12, fontWeight: 500, color: 'var(--text-muted)', marginBottom: 4 }}>
                  用例标题 *
                </label>
                <input
                  value={form.title}
                  onChange={(e) => setField('title', e.target.value)}
                  style={{
                    width: '100%',
                    padding: '8px 10px',
                    borderRadius: 6,
                    background: 'var(--bg-card)',
                    border: '1px solid var(--border)',
                    color: 'var(--text-primary)',
                    fontSize: 13,
                    outline: 'none',
                  }}
                />
              </div>

              {/* 核心属性下拉选择组 */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: 12 }}>
                <div>
                  <label style={{ display: 'block', fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>
                    优先级
                  </label>
                  <select
                    value={form.priority}
                    onChange={(e) => setField('priority', e.target.value)}
                    style={selectStyle}
                  >
                    <option value="p0">P0 - 紧急</option>
                    <option value="p1">P1 - 高</option>
                    <option value="p2">P2 - 中</option>
                    <option value="p3">P3 - 低</option>
                  </select>
                </div>

                <div>
                  <label style={{ display: 'block', fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>
                    状态
                  </label>
                  <select
                    value={form.status}
                    onChange={(e) => setField('status', e.target.value)}
                    style={selectStyle}
                  >
                    <option value="draft">待审阅 (draft)</option>
                    <option value="reviewed">已审阅 (reviewed)</option>
                    <option value="ready">就绪 (ready)</option>
                    <option value="deprecated">废弃 (deprecated)</option>
                  </select>
                </div>

                <div>
                  <label style={{ display: 'block', fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>
                    测试设计方法
                  </label>
                  <select
                    value={form.test_design}
                    onChange={(e) => setField('test_design', e.target.value)}
                    style={selectStyle}
                  >
                    <option value="positive">正向场景</option>
                    <option value="negative">异常场景</option>
                    <option value="boundary">边界值</option>
                    <option value="edge">极端场景</option>
                    {!['positive', 'negative', 'boundary', 'edge'].includes(form.test_design) && form.test_design && (
                      <option value={form.test_design}>{formatTestDesign(form.test_design)}</option>
                    )}
                  </select>
                </div>
              </div>

              {/* 归属迁移（项目、版本、目录） */}
              <div
                style={{
                  background: 'var(--bg-card)',
                  border: '1px solid var(--border)',
                  borderRadius: 8,
                  padding: '12px 14px',
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))',
                  gap: 12,
                }}
              >
                <div>
                  <label style={{ display: 'block', fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>
                    所属项目
                  </label>
                  <select
                    value={form.project_id ?? ''}
                    onChange={(e) => {
                      const pid = e.target.value === '' ? null : Number(e.target.value);
                      setField('project_id', pid);
                      setField('version_id', null);
                      if (pid !== null) loadVersions(pid);
                    }}
                    style={selectStyle}
                  >
                    <option value="">未指定项目</option>
                    {projects.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label style={{ display: 'block', fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>
                    所属版本
                  </label>
                  <select
                    value={form.version_id ?? ''}
                    disabled={!form.project_id}
                    onChange={(e) => {
                      const vid = e.target.value === '' ? null : Number(e.target.value);
                      setField('version_id', vid);
                    }}
                    style={selectStyle}
                  >
                    <option value="">未绑定版本</option>
                    {versions
                      .filter((v) => !form.project_id || v.project_id === form.project_id)
                      .map((v) => (
                        <option key={v.id} value={v.id}>
                          {v.name}
                        </option>
                      ))}
                  </select>
                </div>

                <div>
                  <label style={{ display: 'block', fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>
                    所属目录
                  </label>
                  <select
                    value={form.folder_id ?? ''}
                    onChange={(e) => {
                      const fid = e.target.value === '' ? null : Number(e.target.value);
                      setField('folder_id', fid);
                    }}
                    style={selectStyle}
                  >
                    <option value="">未分类</option>
                    {renderFolderOptions(folders)}
                  </select>
                </div>
              </div>

              {/* 前置条件输入 */}
              <div>
                <label style={{ display: 'block', fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>
                  前置条件
                </label>
                <input
                  value={form.preconditions}
                  onChange={(e) => setField('preconditions', e.target.value)}
                  placeholder="例如：用户已登录且账号正常"
                  style={{
                    width: '100%',
                    padding: '8px 10px',
                    borderRadius: 6,
                    background: 'var(--bg-card)',
                    border: '1px solid var(--border)',
                    color: 'var(--text-primary)',
                    fontSize: 13,
                    outline: 'none',
                  }}
                />
              </div>

              {/* 用例描述输入 */}
              <div>
                <label style={{ display: 'block', fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>
                  用例描述
                </label>
                <textarea
                  value={form.description}
                  rows={2}
                  onChange={(e) => setField('description', e.target.value)}
                  placeholder="简要描述测试场景目的..."
                  style={{
                    width: '100%',
                    padding: '8px 10px',
                    borderRadius: 6,
                    background: 'var(--bg-card)',
                    border: '1px solid var(--border)',
                    color: 'var(--text-primary)',
                    fontSize: 13,
                    outline: 'none',
                    resize: 'vertical',
                  }}
                />
              </div>

              {/* 步骤编辑器 */}
              <div>
                <label style={{ display: 'block', fontSize: 13, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 6 }}>
                  测试步骤与预期
                </label>
                {form.type === 'functional' ? (
                  <FunctionalStepsEditor
                    content={form.content as unknown as FunctionalContent}
                    onChange={(c) => setField('content', c as unknown as Record<string, unknown>)}
                  />
                ) : form.type === 'api' ? (
                  <ApiStepsEditor
                    content={(form.content as unknown as ApiContent) ?? { base_url: '', steps: [] }}
                    onChange={(c) => setField('content', c as unknown as Record<string, unknown>)}
                  />
                ) : form.type === 'ui' ? (
                  <UiStepsEditor
                    content={(form.content as unknown as UiContent) ?? { base_url: '', steps: [] }}
                    onChange={(c) => setField('content', c as unknown as Record<string, unknown>)}
                  />
                ) : (
                  <ContentRenderer type={form.type} content={form.content} />
                )}
              </div>
            </>
          )}
        </div>

        {/* 底部只读状态下的辅助工具栏 */}
        {!isEditing && (
          <div
            style={{
              padding: '12px 20px',
              borderTop: '1px solid var(--border)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              background: 'var(--bg-card)',
              fontSize: 12,
            }}
          >
            <span style={{ color: 'var(--text-muted)', display: 'inline-flex', alignItems: 'center', gap: 4 }}>
              <Clock size={12} /> 更新于: {form.updated_at ? new Date(form.updated_at).toLocaleString() : '-'}
            </span>
            <div style={{ display: 'flex', gap: 8 }}>
              {form.status === 'draft' && (
                <button
                  onClick={async () => {
                    await updateStatus(form.id, 'reviewed');
                    setField('status', 'reviewed');
                    toast.success('已标记为已审阅');
                  }}
                  style={{
                    background: 'transparent',
                    border: '1px solid var(--border)',
                    padding: '4px 10px',
                    borderRadius: 4,
                    color: 'var(--info, #3b82f6)',
                    cursor: 'pointer',
                  }}
                >
                  标记已审阅
                </button>
              )}
              <button
                onClick={() =>
                  confirm({
                    title: '确认删除',
                    message: `确定要删除用例「${form.title}」吗？`,
                    variant: 'danger',
                    onConfirm: async () => {
                      await deleteCase(form.id);
                      toast.success('用例已删除');
                      onClose();
                    },
                  })
                }
                style={{
                  background: 'transparent',
                  border: '1px solid var(--border)',
                  padding: '4px 10px',
                  borderRadius: 4,
                  color: 'var(--error, #ef4444)',
                  cursor: 'pointer',
                }}
              >
                删除用例
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

const selectStyle: CSSProperties = {
  width: '100%',
  padding: '6px 8px',
  borderRadius: 6,
  background: 'var(--bg-elevated)',
  border: '1px solid var(--border)',
  color: 'var(--text-primary)',
  fontSize: 13,
  outline: 'none',
};

function findFolderById(nodes: FolderNode[], id: number | null): FolderNode | null {
  if (!id) return null;
  for (const node of nodes) {
    if (node.id === id) return node;
    if (node.children) {
      const found = findFolderById(node.children, id);
      if (found) return found;
    }
  }
  return null;
}

function ReadOnlyFunctionalSteps({ content }: { content: FunctionalContent }) {
  const steps = content?.steps || [];
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div
        style={{
          border: '1px solid var(--border)',
          borderRadius: 6,
          overflow: 'hidden',
          fontSize: 13,
        }}
      >
        <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
          <thead>
            <tr style={{ background: 'var(--bg-card)', borderBottom: '1px solid var(--border)', color: 'var(--text-secondary)' }}>
              <th style={{ padding: '8px 12px', width: 44 }}>#</th>
              <th style={{ padding: '8px 12px' }}>操作步骤</th>
              <th style={{ padding: '8px 12px', width: 150 }}>测试数据</th>
            </tr>
          </thead>
          <tbody>
            {steps.length === 0 ? (
              <tr>
                <td colSpan={3} style={{ padding: 12, textAlign: 'center', color: 'var(--text-muted)' }}>
                  暂无步骤
                </td>
              </tr>
            ) : (
              steps.map((s, idx) => (
                <tr key={idx} style={{ borderBottom: idx < steps.length - 1 ? '1px solid var(--border)' : 'none' }}>
                  <td style={{ padding: '8px 12px', color: 'var(--accent)', fontWeight: 600 }}>{s.no || idx + 1}</td>
                  <td style={{ padding: '8px 12px', color: 'var(--text-primary)' }}>{s.action}</td>
                  <td style={{ padding: '8px 12px', color: 'var(--text-secondary)', fontFamily: 'monospace', fontSize: 12 }}>
                    {s.data || '-'}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div>
        <span style={{ fontSize: 12, color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>
          预期结果
        </span>
        <div
          style={{
            background: 'var(--bg-card)',
            border: '1px solid var(--border)',
            borderRadius: 6,
            padding: '8px 12px',
            fontSize: 13,
            color: content?.expected ? 'var(--text-primary)' : 'var(--text-muted)',
          }}
        >
          {content?.expected || '无'}
        </div>
      </div>
    </div>
  );
}

function ReadOnlyApiSteps({ content }: { content: ApiContent }) {
  const steps = content?.steps || [];
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, fontSize: 13 }}>
      {content?.base_url && (
        <div style={{ color: 'var(--text-secondary)', fontSize: 12 }}>
          <span style={{ color: 'var(--text-muted)' }}>Base URL: </span>
          <span style={{ fontFamily: 'monospace' }}>{content.base_url}</span>
        </div>
      )}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {steps.map((st, idx) => (
          <div
            key={idx}
            style={{
              background: 'var(--bg-card)',
              border: '1px solid var(--border)',
              borderRadius: 6,
              padding: '8px 12px',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
              <span style={{ color: 'var(--accent)', fontWeight: 600 }}>#{idx + 1}</span>
              <span
                style={{
                  fontSize: 11,
                  fontWeight: 700,
                  padding: '2px 6px',
                  borderRadius: 4,
                  background: 'var(--bg-elevated)',
                  color: st.method === 'GET' ? '#3b82f6' : st.method === 'POST' ? '#10b981' : '#f59e0b',
                }}
              >
                {st.method}
              </span>
              <span style={{ fontFamily: 'monospace', color: 'var(--text-primary)', flex: 1 }}>{st.path}</span>
            </div>
            {st.assertions && st.assertions.length > 0 && (
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>
                断言: {st.assertions.map((a) => `${a.type}=${a.expected}`).join(', ')}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
