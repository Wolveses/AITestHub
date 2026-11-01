import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { X, Clock } from 'lucide-react';
import { Btn, Field, inputStyle } from './common';
import { useAutomationStore } from '../../store/automationStore';
import { useTaskStore, type UiTaskItem } from '../../store/taskStore';

interface TaskEditModalProps {
  open: boolean;
  onClose: () => void;
  task: UiTaskItem | null;
  projectId: number;
  onSaved: () => void;
}

const CRON_PRESETS = [
  { label: '每天 02:00', expr: '0 2 * * *' },
  { label: '工作日 09:00', expr: '0 9 * * 1-5' },
  { label: '每天 00:00', expr: '0 0 * * *' },
  { label: '每小时整点', expr: '0 * * * *' },
];

export function TaskEditModal({ open, onClose, task, projectId, onSaved }: TaskEditModalProps) {
  const { envs, loadEnvs } = useAutomationStore();
  const { createTask, updateTask } = useTaskStore();

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [envId, setEnvId] = useState<number | null>(null);
  const [cronEnabled, setCronEnabled] = useState(false);
  const [cronExpression, setCronExpression] = useState('0 2 * * *');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (open) {
      loadEnvs();
      if (task) {
        setName(task.name);
        setDescription(task.description || '');
        setEnvId(task.env_id);
        setCronEnabled(task.cron_enabled);
        setCronExpression(task.cron_expression || '0 2 * * *');
      } else {
        setName('');
        setDescription('');
        setEnvId(envs.length > 0 ? envs[0].id : null);
        setCronEnabled(false);
        setCronExpression('0 2 * * *');
      }
    }
  }, [open, task, envs.length, loadEnvs]);

  if (!open) return null;

  const handleSubmit = async () => {
    if (!name.trim()) {
      toast.warning('请输入任务名称');
      return;
    }
    const finalEnvId = envId ?? (envs.length > 0 ? envs[0].id : null);
    if (!finalEnvId) {
      toast.warning('请先在「环境管理」中配置至少一个运行环境');
      return;
    }
    if (cronEnabled && !cronExpression.trim()) {
      toast.warning('启用定时执行时必须填写 Cron 表达式');
      return;
    }

    setSubmitting(true);
    try {
      if (task) {
        await updateTask(task.id, {
          name: name.trim(),
          description: description.trim(),
          env_id: finalEnvId,
          cron_enabled: cronEnabled,
          cron_expression: cronExpression.trim(),
        });
        toast.success('任务修改成功');
      } else {
        await createTask({
          project_id: projectId,
          name: name.trim(),
          description: description.trim(),
          env_id: finalEnvId,
          cron_enabled: cronEnabled,
          cron_expression: cronExpression.trim(),
        });
        toast.success('任务创建成功');
      }
      onSaved();
      onClose();
    } catch (err: any) {
      toast.error(err.message || '保存失败');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,.6)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: 540,
          maxWidth: '92vw',
          background: 'var(--bg-card)',
          border: '1px solid var(--border)',
          borderRadius: 10,
          boxShadow: '0 12px 36px rgba(0,0,0,.45)',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
        }}
      >
        {/* Header */}
        <div
          style={{
            padding: '14px 18px',
            borderBottom: '1px solid var(--border)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <strong style={{ fontSize: 15, color: 'var(--text-primary)' }}>
            {task ? '编辑任务' : '新建测试任务'}
          </strong>
          <button
            onClick={onClose}
            style={{
              background: 'transparent',
              border: 'none',
              cursor: 'pointer',
              color: 'var(--text-muted)',
              display: 'flex',
              padding: 4,
            }}
          >
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div style={{ padding: 18, display: 'flex', flexDirection: 'column', gap: 14 }}>
          <Field label="任务名称 *">
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="例如：主流程每日自动化回归"
              style={inputStyle}
              maxLength={100}
            />
          </Field>

          <Field label="执行环境 *">
            <select
              value={envId ?? (envs.length > 0 ? envs[0].id : '')}
              onChange={(e) => setEnvId(Number(e.target.value))}
              style={inputStyle}
            >
              {envs.length === 0 ? (
                <option value="">暂无环境（请先在环境管理添加）</option>
              ) : (
                envs.map((env) => (
                  <option key={env.id} value={env.id}>
                    {env.name} ({env.base_url})
                  </option>
                ))
              )}
            </select>
          </Field>

          <Field label="任务描述 (可选)">
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="简要说明此任务的测试范围或执行目标"
              rows={2}
              style={{ ...inputStyle, resize: 'vertical' }}
            />
          </Field>

          {/* 定时配置卡片 */}
          <div
            style={{
              padding: 12,
              background: 'var(--bg-base)',
              border: '1px solid var(--border)',
              borderRadius: 8,
              display: 'flex',
              flexDirection: 'column',
              gap: 10,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, fontWeight: 500, color: 'var(--text-primary)' }}>
                <Clock size={15} style={{ color: cronEnabled ? 'var(--accent)' : 'var(--text-muted)' }} />
                <span>定时自动执行</span>
              </div>
              <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontSize: 12, color: 'var(--text-secondary)' }}>
                <input
                  type="checkbox"
                  checked={cronEnabled}
                  onChange={(e) => setCronEnabled(e.target.checked)}
                />
                <span>启用定时</span>
              </label>
            </div>

            {cronEnabled && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 4 }}>
                <Field label="Cron 表达式 (分 时 日 月 周)">
                  <input
                    type="text"
                    value={cronExpression}
                    onChange={(e) => setCronExpression(e.target.value)}
                    placeholder="0 2 * * *"
                    style={{ ...inputStyle, fontFamily: 'monospace' }}
                  />
                </Field>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                  <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>常用预设:</span>
                  {CRON_PRESETS.map((p) => (
                    <button
                      key={p.expr}
                      type="button"
                      onClick={() => setCronExpression(p.expr)}
                      style={{
                        background: cronExpression === p.expr ? 'rgba(59,130,246,0.15)' : 'var(--bg-card)',
                        border: `1px solid ${cronExpression === p.expr ? 'var(--accent)' : 'var(--border)'}`,
                        color: cronExpression === p.expr ? 'var(--accent)' : 'var(--text-secondary)',
                        fontSize: 11,
                        padding: '2px 7px',
                        borderRadius: 4,
                        cursor: 'pointer',
                      }}
                    >
                      {p.label}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <div
          style={{
            padding: '12px 18px',
            borderTop: '1px solid var(--border)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'flex-end',
            gap: 10,
            background: 'var(--bg-base)',
          }}
        >
          <Btn onClick={onClose} disabled={submitting}>
            取消
          </Btn>
          <Btn variant="primary" onClick={handleSubmit} disabled={submitting}>
            {submitting ? '保存中...' : '确认保存'}
          </Btn>
        </div>
      </div>
    </div>
  );
}
