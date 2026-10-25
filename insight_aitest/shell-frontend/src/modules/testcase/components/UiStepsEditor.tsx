import { ArrowUp, ArrowDown } from 'lucide-react';
import { useTranslation } from 'react-i18next';

export interface UiStep {
  kind: 'action' | 'assert' | 'extract';
  action?: string;
  assert?: string;
  prompt?: string;
  extract?: Record<string, string>;
}

export interface UiContent {
  base_url: string;
  steps: UiStep[];
}

export function UiStepsEditor({
  content,
  onChange,
}: {
  content: UiContent;
  onChange: (c: UiContent) => void;
}) {
  const { t } = useTranslation();
  const steps = content.steps || [];

  const update = (patch: Partial<UiContent>) => onChange({ ...content, ...patch });
  const updateStep = (i: number, patch: Partial<UiStep>) =>
    update({ steps: steps.map((s, idx) => (idx === i ? { ...s, ...patch } : s)) });

  const addStep = (kind: 'action' | 'assert' = 'action') =>
    update({
      steps: [
        ...steps,
        {
          kind,
          action: kind === 'action' ? '' : undefined,
          assert: kind === 'assert' ? '' : undefined,
        },
      ],
    });

  const delStep = (i: number) => update({ steps: steps.filter((_, idx) => idx !== i) });

  const moveStep = (i: number, dir: -1 | 1) => {
    const j = i + dir;
    if (j < 0 || j >= steps.length) return;
    const arr = [...steps];
    [arr[i], arr[j]] = [arr[j], arr[i]];
    update({ steps: arr });
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div>
        <label style={{ display: 'block', fontSize: 12, color: 'var(--text-secondary)', marginBottom: 4 }}>
          {t('testcase.targetBaseUrl', '目标应用/网站地址 (Base URL)')}
        </label>
        <input
          style={inputStyle}
          placeholder="https://example.com"
          value={content.base_url || ''}
          onChange={(e) => update({ base_url: e.target.value })}
        />
      </div>

      <div>
        <div
          style={{
            fontSize: 12,
            color: 'var(--text-secondary)',
            marginBottom: 8,
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
          }}
        >
          <span>{t('testcase.uiStepsTitle', 'UI 操作与验证步骤')}</span>
          <div style={{ display: 'flex', gap: 6 }}>
            <button
              type="button"
              onClick={() => addStep('action')}
              style={{ ...miniBtn, border: '1px dashed var(--border)' }}
            >
              + {t('testcase.addActionStep', '添加操作步骤')}
            </button>
            <button
              type="button"
              onClick={() => addStep('assert')}
              style={{ ...miniBtn, border: '1px dashed var(--border)', color: 'var(--accent)' }}
            >
              + {t('testcase.addAssertStep', '添加断言验证')}
            </button>
          </div>
        </div>

        {steps.map((s, i) => {
          const kind = s.kind || (s.assert ? 'assert' : 'action');
          const textVal = s.action || s.assert || s.prompt || '';
          return (
            <div key={i} style={{ display: 'flex', gap: 6, marginBottom: 8, alignItems: 'center' }}>
              <span style={{ color: 'var(--accent)', width: 22, fontSize: 12, fontWeight: 600 }}>#{i + 1}</span>
              <select
                style={{ ...inputStyle, width: 100, flexShrink: 0 }}
                value={kind}
                onChange={(e) => {
                  const newKind = e.target.value as 'action' | 'assert';
                  if (newKind === 'assert') {
                    updateStep(i, { kind: 'assert', assert: textVal, action: undefined });
                  } else {
                    updateStep(i, { kind: 'action', action: textVal, assert: undefined });
                  }
                }}
              >
                <option value="action">{t('testcase.kindAction', '操作 (Action)')}</option>
                <option value="assert">{t('testcase.kindAssert', '断言 (Assert)')}</option>
              </select>
              <input
                style={{ ...inputStyle, flex: 1 }}
                placeholder={
                  kind === 'assert'
                    ? t('testcase.assertPlaceholder', '输入断言预期，如：页面显示用户名或成功提示')
                    : t('testcase.actionPlaceholderUi', '输入页面操作，如：在输入框输入密码并点击登录')
                }
                value={textVal}
                onChange={(e) => {
                  if (kind === 'assert') {
                    updateStep(i, { assert: e.target.value });
                  } else {
                    updateStep(i, { action: e.target.value });
                  }
                }}
              />
              <button
                type="button"
                onClick={() => moveStep(i, -1)}
                style={{ ...miniBtn, display: 'inline-flex', alignItems: 'center' }}
                title={t('testcase.moveUp', '上移')}
              >
                <ArrowUp size={12} strokeWidth={1.5} />
              </button>
              <button
                type="button"
                onClick={() => moveStep(i, 1)}
                style={{ ...miniBtn, display: 'inline-flex', alignItems: 'center' }}
                title={t('testcase.moveDown', '下移')}
              >
                <ArrowDown size={12} strokeWidth={1.5} />
              </button>
              <button
                type="button"
                onClick={() => delStep(i)}
                style={{ ...miniBtn, color: 'var(--error)' }}
                title={t('testcase.deleteStep', '删除')}
              >
                ×
              </button>
            </div>
          );
        })}

        {steps.length === 0 && (
          <div
            style={{
              padding: 12,
              border: '1px dashed var(--border)',
              borderRadius: 6,
              textAlign: 'center',
              color: 'var(--text-muted)',
              fontSize: 12,
            }}
          >
            {t('testcase.noUiSteps', '暂无步骤，点击上方按钮添加操作或断言')}
          </div>
        )}
      </div>
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  background: 'var(--bg-card)',
  border: '1px solid var(--border)',
  borderRadius: 4,
  color: 'var(--text-primary)',
  padding: '6px 8px',
  fontFamily: 'inherit',
  fontSize: 13,
};

const miniBtn: React.CSSProperties = {
  background: 'none',
  border: '1px solid var(--border)',
  color: 'var(--text-secondary)',
  padding: '3px 8px',
  borderRadius: 4,
  cursor: 'pointer',
  fontSize: 12,
};

