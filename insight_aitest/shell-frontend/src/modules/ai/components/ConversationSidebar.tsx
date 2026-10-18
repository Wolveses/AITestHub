import { useTranslation } from 'react-i18next';
import { useTaskStore } from '../store/taskStore';
import { useConfirmStore } from '../../../shared/store/confirmStore';
import { useAgentProfileStore } from '../store/agentProfileStore';
import { AgentIdentityCard } from './AgentIdentityCard';
import { Bot, Check, X, Loader, Circle, CircleDot, Cog, MessageSquare } from 'lucide-react';

export interface ConversationSidebarProps {
  isMobile?: boolean;
}

/** Task 状态 → 显示颜色 + 图标 */
const STATUS_BADGE: Record<string, { labelKey: string; color: string; bg: string; Icon: typeof Check }> = {
  done: { labelKey: 'ai.statusDone', color: 'var(--chart-4)', bg: 'rgba(82,196,26,0.12)', Icon: Check },
  failed: { labelKey: 'ai.statusFailed', color: 'var(--error)', bg: 'rgba(255,77,79,0.12)', Icon: X },
  cancelled: { labelKey: 'ai.statusCancelled', color: "var(--text-secondary)", bg: 'rgba(136,136,136,0.12)', Icon: X },
  running: { labelKey: 'ai.statusRunning', color: "var(--accent)", bg: 'rgba(16,185,129,0.12)', Icon: Loader },
  pending_select: { labelKey: 'ai.statusPendingSelect', color: 'var(--chart-3)', bg: 'rgba(250,173,20,0.12)', Icon: CircleDot },
  pending_confirm: { labelKey: 'ai.statusPendingConfirm', color: 'var(--chart-3)', bg: 'rgba(250,173,20,0.12)', Icon: CircleDot },
  strategizing: { labelKey: 'ai.statusStrategizing', color: "var(--accent)", bg: 'rgba(16,185,129,0.12)', Icon: Cog },
  understanding: { labelKey: 'ai.statusUnderstanding', color: "var(--accent)", bg: 'rgba(16,185,129,0.12)', Icon: Cog },
};

export function ConversationSidebar({ isMobile }: ConversationSidebarProps) {
  const {
    tasks,
    conversations,
    currentTask,
    chatConversationId,
    deleteTask,
    deleteConversation,
    resetConversation,
    selectTask,
    selectConversation,
  } = useTaskStore();
  const { confirm } = useConfirmStore();
  const agentName = useAgentProfileStore((s) => s.name);
  const { t } = useTranslation();

  return (
    <div
      style={{
        width: isMobile ? '100%' : 240,
        borderRight: '1px solid var(--bg-card)',
        display: 'flex',
        flexDirection: 'column',
        background: "var(--bg-base)",
        ...(isMobile ? { maxHeight: 240, overflowY: 'auto' } : {}),
      }}
    >
      {/* 新建任务/会话 */}
      <div style={{ padding: '12px 12px 8px' }}>
        <button
          onClick={() => resetConversation()}
          style={{
            width: '100%',
            background: 'var(--bg-card)',
            border: '1px solid var(--bg-elevated)',
            color: 'var(--accent)',
            padding: '8px',
            borderRadius: 6,
            cursor: 'pointer',
            fontSize: 13,
            fontWeight: 500,
            transition: 'background 0.15s ease',
          }}
        >
          {t('ai.newTask')}
        </button>
      </div>

      {/* 历史列表：展示任务与对话 */}
      <div style={{ flex: 1, overflow: 'auto' }}>
        {tasks.length === 0 && conversations.length === 0 && (
          <div style={{ padding: '24px 16px', color: 'var(--text-muted)', fontSize: 12, textAlign: 'center', lineHeight: 1.8 }}>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}><Bot size={13} strokeWidth={1.5} /> {agentName}</span><br />
            <span style={{ color: 'var(--text-muted)', whiteSpace: 'pre-line' }}>
              {t('ai.taskFlowHint')}
            </span>
          </div>
        )}
        {(() => {
          // 渲染单条 Task
          const renderTaskItem = (task: typeof tasks[0]) => {
            const badge = STATUS_BADGE[task.status] || { labelKey: '', color: "var(--text-secondary)", bg: 'transparent', Icon: Circle };
            const active = currentTask?.id === task.id;
            return (
              <div
                key={`task-${task.id}`}
                onClick={() => selectTask(task.id)}
                title={t('ai.viewTaskHint')}
                style={{
                  padding: '8px 12px',
                  cursor: 'pointer',
                  background: active ? 'rgba(91,140,123,0.08)' : 'transparent',
                  borderLeft: active ? '2px solid var(--accent)' : '2px solid transparent',
                  display: 'flex', flexDirection: 'column', gap: 2,
                  transition: 'background 0.15s ease',
                }}
                onMouseEnter={(e) => { if (!active) e.currentTarget.style.background = 'rgba(136,136,136,0.06)'; }}
                onMouseLeave={(e) => { if (!active) e.currentTarget.style.background = 'transparent'; }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span style={{
                    flex: 1, fontSize: 11, color: active ? "var(--accent)" : 'var(--text-secondary)',
                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  }} title={task.intent}>
                    {task.intent?.slice(0, 30) || t('ai.noIntent')}
                  </span>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      confirm({
                        title: t('ai.confirmDeleteTaskTitle'),
                        message: t('ai.confirmDeleteTaskMsg', { name: task.intent?.slice(0, 30) || '' }),
                        variant: 'danger',
                        onConfirm: () => deleteTask(task.id),
                      });
                    }}
                    style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: 12,
                      ...(isMobile ? { minWidth: 44, minHeight: 44, padding: 10, display: 'flex', alignItems: 'center', justifyContent: 'center' } : {}) }}
                  >×</button>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span style={{
                    fontSize: 9, padding: '1px 5px', borderRadius: 8,
                    color: badge.color, background: badge.bg, border: `1px solid ${badge.color}33`,
                    display: 'inline-flex', alignItems: 'center', gap: 2,
                  }}>
                    <badge.Icon size={9} strokeWidth={1.5} />
                    {t(badge.labelKey)}
                  </span>
                  <span style={{ fontSize: 9, color: 'var(--text-muted)', marginLeft: 'auto' }}>
                    {task.created_at ? new Date(task.created_at).toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' }) : ''}
                  </span>
                </div>
              </div>
            );
          };

          // 渲染纯对话会话
          const renderPureConversationItem = (conv: typeof conversations[0]) => {
            const active = chatConversationId === conv.id && currentTask === null;
            return (
              <div
                key={`conv-item-${conv.id}`}
                onClick={() => selectConversation(conv.id)}
                title={conv.title}
                style={{
                  padding: '8px 12px',
                  cursor: 'pointer',
                  background: active ? 'rgba(91,140,123,0.08)' : 'transparent',
                  borderLeft: active ? '2px solid var(--accent)' : '2px solid transparent',
                  display: 'flex', flexDirection: 'column', gap: 2,
                  transition: 'background 0.15s ease',
                }}
                onMouseEnter={(e) => { if (!active) e.currentTarget.style.background = 'rgba(136,136,136,0.06)'; }}
                onMouseLeave={(e) => { if (!active) e.currentTarget.style.background = 'transparent'; }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span style={{
                    flex: 1, fontSize: 11, color: active ? "var(--accent)" : 'var(--text-secondary)',
                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  }} title={conv.title}>
                    {conv.title?.slice(0, 30) || t('ai.noIntent')}
                  </span>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      confirm({
                        title: t('ai.confirmDeleteConvTitle'),
                        message: t('ai.confirmDeleteConvMsg', { name: conv.title?.slice(0, 30) || '' }),
                        variant: 'danger',
                        onConfirm: () => deleteConversation(conv.id),
                      });
                    }}
                    style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: 12,
                      ...(isMobile ? { minWidth: 44, minHeight: 44, padding: 10, display: 'flex', alignItems: 'center', justifyContent: 'center' } : {}) }}
                  >×</button>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span style={{
                    fontSize: 9, padding: '1px 5px', borderRadius: 8,
                    color: 'var(--accent)', background: 'rgba(16,185,129,0.12)', border: '1px solid rgba(16,185,129,0.25)',
                    display: 'inline-flex', alignItems: 'center', gap: 2,
                  }}>
                    <MessageSquare size={9} strokeWidth={1.5} />
                    {t('ai.pureChat', '对话')}
                  </span>
                  <span style={{ fontSize: 9, color: 'var(--text-muted)', marginLeft: 'auto' }}>
                    {conv.created_at ? new Date(conv.created_at).toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' }) : ''}
                  </span>
                </div>
              </div>
            );
          };

          // 合并 tasks 和纯 conversations，统一平铺单级展示
          // 关联到已有 task 的 conversation 不重复展示，只有纯对话会话才展示
          const taskConvIds = new Set<number>();
          for (const task of tasks) {
            if (task.conversation_id != null) {
              taskConvIds.add(task.conversation_id);
            }
          }

          type FlatItem =
            | { type: 'task'; data: typeof tasks[0]; time: number }
            | { type: 'conv'; data: typeof conversations[0]; time: number };

          const flatList: FlatItem[] = [];

          // 1. 任务项
          for (const task of tasks) {
            const time = task.created_at ? new Date(task.created_at).getTime() : 0;
            flatList.push({ type: 'task', data: task, time });
          }

          // 2. 纯对话项（无关联 task 的 conversation）
          for (const conv of conversations) {
            if (!taskConvIds.has(conv.id)) {
              const time = conv.created_at ? new Date(conv.created_at).getTime() : 0;
              flatList.push({ type: 'conv', data: conv, time });
            }
          }

          // 3. 统一按创建时间降序排序
          flatList.sort((a, b) => b.time - a.time);

          return flatList.map((item) => {
            if (item.type === 'task') {
              return renderTaskItem(item.data);
            }
            return renderPureConversationItem(item.data);
          });
        })()}
      </div>

      <AgentIdentityCard isMobile={isMobile} />
    </div>
  );
}
