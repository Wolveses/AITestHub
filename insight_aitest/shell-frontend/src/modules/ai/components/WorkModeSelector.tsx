import { useTranslation } from 'react-i18next';
import { MessageSquare, Zap } from 'lucide-react';
import { SPRING } from './agentStyles';


export type WorkMode = 'chat' | 'task';

interface WorkModeSelectorProps {
  value: WorkMode;
  onChange: (mode: WorkMode) => void;
  disabled?: boolean;
}

export function WorkModeSelector({ value, onChange, disabled }: WorkModeSelectorProps) {
  const { t } = useTranslation();

  return (
    <div
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        height: 28,
        boxSizing: 'border-box',
        background: 'var(--bg-card)',
        border: '1px solid var(--border)',
        borderRadius: 999,
        padding: '2px',
        boxShadow: 'var(--shadow-card)',
        userSelect: 'none',
      }}
    >
      <button
        type="button"
        disabled={disabled}
        onClick={() => onChange('chat')}
        title={t('ai.modeChatDesc', '纯问答与知识库检索，不创建测试任务')}
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          height: 22,
          boxSizing: 'border-box',
          gap: 5,
          padding: '0 10px',
          borderRadius: 999,
          border: value === 'chat' ? '1px solid rgba(16,185,129,0.3)' : '1px solid transparent',
          background: value === 'chat' ? 'rgba(16,185,129,0.14)' : 'transparent',
          color: value === 'chat' ? 'var(--accent)' : 'var(--text-secondary)',
          fontSize: 12,
          fontWeight: value === 'chat' ? 600 : 400,
          cursor: disabled ? 'not-allowed' : 'pointer',
          transition: `all 0.2s ${SPRING}`,
          outline: 'none',
        }}
      >
        <MessageSquare size={13} strokeWidth={value === 'chat' ? 2 : 1.5} />
        <span>{t('ai.modeChat', '对话')}</span>
      </button>

      <button
        type="button"
        disabled={disabled}
        onClick={() => onChange('task')}
        title={t('ai.modeTaskDesc', '自动化测试任务，意图识别、规划策略并生成用例')}
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          height: 22,
          boxSizing: 'border-box',
          gap: 5,
          padding: '0 10px',
          borderRadius: 999,
          border: value === 'task' ? '1px solid rgba(16,185,129,0.3)' : '1px solid transparent',
          background: value === 'task' ? 'rgba(16,185,129,0.14)' : 'transparent',
          color: value === 'task' ? 'var(--accent)' : 'var(--text-secondary)',
          fontSize: 12,
          fontWeight: value === 'task' ? 600 : 400,
          cursor: disabled ? 'not-allowed' : 'pointer',
          transition: `all 0.2s ${SPRING}`,
          outline: 'none',
        }}
      >
        <Zap size={13} strokeWidth={value === 'task' ? 2 : 1.5} />
        <span>{t('ai.modeTask', '任务')}</span>
      </button>
    </div>
  );
}
