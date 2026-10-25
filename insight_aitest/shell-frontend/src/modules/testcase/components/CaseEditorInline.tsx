import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { ReviewCase } from '../../ai/store/taskStore';
import { FunctionalStepsEditor, type FunctionalContent, type FunctionalStep } from './FunctionalStepsEditor';
import { ApiStepsEditor, type ApiContent, type ApiStep } from './ApiStepsEditor';
import { UiStepsEditor, type UiContent, type UiStep } from './UiStepsEditor';
import { formatCaseType, formatTestDesign } from '../utils/caseLabels';

/** 用例 API 基址（与 ai/store/taskStore 的 CASE_BASE 保持一致）。 */
const CASE_BASE = '/api/modules/testcase/testcases';

const inputStyle: React.CSSProperties = {
  background: 'var(--bg-card)',
  border: '1px solid var(--border)',
  borderRadius: 6,
  color: 'var(--text-primary)',
  padding: '6px 10px',
  fontFamily: 'inherit',
  fontSize: 13,
  width: '100%',
  outline: 'none',
};

const labelStyle: React.CSSProperties = {
  fontSize: 12,
  color: 'var(--text-secondary)',
  width: 68,
  flexShrink: 0,
  paddingTop: 6,
  fontWeight: 500,
};

function toFunctionalContent(raw: Record<string, unknown> | undefined): FunctionalContent {
  if (!raw || typeof raw !== 'object') return { steps: [], expected: '' };
  const rawSteps: unknown[] = Array.isArray(raw.steps) ? raw.steps : [];
  const steps: FunctionalStep[] = rawSteps.map((st: any, idx: number) => {
    if (typeof st === 'string') {
      return { no: idx + 1, action: st, data: '' };
    }
    if (st && typeof st === 'object') {
      return {
        no: Number(st.no ?? st.step_no ?? idx + 1),
        action: String(st.action ?? st.step ?? st.desc ?? st.description ?? ''),
        data: String(st.data ?? st.input ?? st.params ?? ''),
      };
    }
    return { no: idx + 1, action: '', data: '' };
  });

  const expected = typeof raw.expected === 'string' ? raw.expected : '';
  return { steps, expected };
}

function toApiContent(raw: Record<string, unknown> | undefined): ApiContent {
  if (!raw || typeof raw !== 'object') return { base_url: '', steps: [] };
  return {
    base_url: typeof raw.base_url === 'string' ? raw.base_url : '',
    steps: Array.isArray(raw.steps) ? (raw.steps as ApiStep[]) : [],
  };
}

function toUiContent(raw: Record<string, unknown> | undefined): UiContent {
  if (!raw || typeof raw !== 'object') return { base_url: '', steps: [] };
  return {
    base_url: typeof raw.base_url === 'string' ? raw.base_url : '',
    steps: Array.isArray(raw.steps) ? (raw.steps as UiStep[]) : [],
  };
}

/**
 * 行内用例编辑器（用于用例审阅面板 ReviewRow 展开后编辑）。
 * 步骤与预期结果默认结构化渲染展示，同时支持按需查看原始 JSON。
 */
export function CaseEditorInline({
  caseData,
  onSaved,
  onClose,
}: {
  caseData: ReviewCase;
  onSaved: () => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState<ReviewCase>(caseData);
  const [content, setContent] = useState<Record<string, unknown>>(() => {
    return caseData.content && typeof caseData.content === 'object' ? caseData.content : {};
  });
  const [viewMode, setViewMode] = useState<'rendered' | 'json'>('rendered');
  const [jsonText, setJsonText] = useState<string>(() => {
    try {
      return JSON.stringify(caseData.content ?? {}, null, 2);
    } catch {
      return '{}';
    }
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const setField = <K extends keyof ReviewCase>(k: K, v: ReviewCase[K]) =>
    setDraft((d) => ({ ...d, [k]: v }));

  const handleContentChange = (nextContent: Record<string, unknown>) => {
    setContent(nextContent);
    setJsonText(JSON.stringify(nextContent, null, 2));
  };

  const handleJsonChange = (text: string) => {
    setJsonText(text);
    try {
      const parsed = JSON.parse(text);
      if (parsed && typeof parsed === 'object') {
        setContent(parsed);
        setError(null);
      }
    } catch {
      // 允许输入过程中的临时未闭合语法
    }
  };

  const save = async () => {
    setSaving(true);
    setError(null);

    let finalContent = content;
    if (viewMode === 'json') {
      try {
        finalContent = JSON.parse(jsonText || '{}');
      } catch {
        setError(t('testcase.invalidJson', 'JSON 格式不合法，请检查后重试'));
        setSaving(false);
        return;
      }
    }

    try {
      const res = await fetch(`${CASE_BASE}/${caseData.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: draft.title,
          description: draft.description,
          preconditions: draft.preconditions,
          priority: draft.priority,
          test_design: draft.test_design,
          content: finalContent,
        }),
      });
      if (!res.ok) {
        const msg = await res.text().catch(() => `HTTP ${res.status}`);
        setError(t('testcase.saveFailed', { message: msg }));
        setSaving(false);
        return;
      }
      onSaved();
    } catch (e) {
      setError(t('testcase.networkError', { message: (e as Error).message }));
      setSaving(false);
    }
  };

  return (
    <div
      style={{
        padding: '16px 20px',
        background: 'var(--bg-elevated)',
        borderTop: '1px solid var(--border)',
        display: 'flex',
        flexDirection: 'column',
        gap: 12,
      }}
    >
      {/* 标题 */}
      <Row label={t('testcase.caseTitle', '用例标题')}>
        <input
          style={inputStyle}
          value={draft.title}
          onChange={(e) => setField('title', e.target.value)}
          placeholder={t('testcase.titlePlaceholder', '输入用例标题')}
        />
      </Row>

      {/* 前置条件与用例描述 */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <Row label={t('testcase.preconditions', '前置条件')}>
          <input
            style={inputStyle}
            value={draft.preconditions ?? ''}
            onChange={(e) => setField('preconditions', e.target.value)}
            placeholder={t('testcase.preconditionsPlaceholder', '例如：用户处于登录状态')}
          />
        </Row>
        <Row label={t('testcase.description', '用例描述')}>
          <input
            style={inputStyle}
            value={draft.description ?? ''}
            onChange={(e) => setField('description', e.target.value)}
            placeholder={t('testcase.descriptionPlaceholder', '描述测试目的与验证要点')}
          />
        </Row>
      </div>

      {/* 优先级与设计方法 */}
      <div style={{ display: 'flex', gap: 16 }}>
        <Row label={t('testcase.priority', '优先级')}>
          <select
            style={{ ...inputStyle, width: 140 }}
            value={draft.priority}
            onChange={(e) => setField('priority', e.target.value)}
          >
            <option value="p0">P0 - 核心必测</option>
            <option value="p1">P1 - 重要功能</option>
            <option value="p2">P2 - 一般场景</option>
            <option value="p3">P3 - 边界可选</option>
          </select>
        </Row>
        <Row label={t('testcase.testDesign', '设计方法')}>
          <select
            style={{ ...inputStyle, width: 140 }}
            value={draft.test_design}
            onChange={(e) => setField('test_design', e.target.value)}
          >
            <option value="positive">{t('testcase.designPositive', '正向场景')}</option>
            <option value="negative">{t('testcase.designNegative', '异常场景')}</option>
            <option value="boundary">{t('testcase.designBoundary', '边界值')}</option>
            <option value="edge">{t('testcase.designEdge', '极端场景')}</option>
            {!['positive', 'negative', 'boundary', 'edge'].includes(draft.test_design) && draft.test_design && (
              <option value={draft.test_design}>{formatTestDesign(draft.test_design)}</option>
            )}
          </select>
        </Row>
      </div>

      {/* 步骤与预期结果模块（核心改造） */}
      <div
        style={{
          background: 'var(--bg-card)',
          border: '1px solid var(--border)',
          borderRadius: 8,
          padding: '14px 16px',
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            marginBottom: 12,
            paddingBottom: 8,
            borderBottom: '1px solid var(--border)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>
              {t('testcase.stepsAndExpected', '测试步骤与预期结果')}
            </span>
            <span
              style={{
                fontSize: 11,
                padding: '1px 6px',
                borderRadius: 4,
                background: 'var(--bg-elevated)',
                color: 'var(--text-secondary)',
                fontWeight: 500,
              }}
            >
              {formatCaseType(draft.type)}
            </span>
          </div>

          {/* 模式切换：结构化编辑 vs 原始 JSON */}
          <div style={{ display: 'inline-flex', background: 'var(--bg-elevated)', borderRadius: 6, padding: 2 }}>
            <button
              type="button"
              onClick={() => {
                if (viewMode === 'json') {
                  try {
                    const parsed = JSON.parse(jsonText || '{}');
                    setContent(parsed);
                  } catch {}
                }
                setViewMode('rendered');
              }}
              style={{
                background: viewMode === 'rendered' ? 'var(--bg-card)' : 'transparent',
                color: viewMode === 'rendered' ? 'var(--text-primary)' : 'var(--text-muted)',
                border: 'none',
                borderRadius: 4,
                padding: '3px 10px',
                fontSize: 12,
                cursor: 'pointer',
                fontWeight: viewMode === 'rendered' ? 600 : 400,
                boxShadow: viewMode === 'rendered' ? '0 1px 2px rgba(0,0,0,0.1)' : 'none',
              }}
            >
              {t('testcase.modeRendered', '结构化渲染展示')}
            </button>
            <button
              type="button"
              onClick={() => {
                setJsonText(JSON.stringify(content, null, 2));
                setViewMode('json');
              }}
              style={{
                background: viewMode === 'json' ? 'var(--bg-card)' : 'transparent',
                color: viewMode === 'json' ? 'var(--text-primary)' : 'var(--text-muted)',
                border: 'none',
                borderRadius: 4,
                padding: '3px 10px',
                fontSize: 12,
                cursor: 'pointer',
                fontWeight: viewMode === 'json' ? 600 : 400,
                boxShadow: viewMode === 'json' ? '0 1px 2px rgba(0,0,0,0.1)' : 'none',
              }}
            >
              {t('testcase.modeJson', '原始 JSON')}
            </button>
          </div>
        </div>

        {viewMode === 'rendered' ? (
          <div>
            {draft.type === 'api' ? (
              <ApiStepsEditor
                content={toApiContent(content)}
                onChange={(next) => handleContentChange(next as unknown as Record<string, unknown>)}
              />
            ) : draft.type === 'ui' ? (
              <UiStepsEditor
                content={toUiContent(content)}
                onChange={(next) => handleContentChange(next as unknown as Record<string, unknown>)}
              />
            ) : (
              <FunctionalStepsEditor
                content={toFunctionalContent(content)}
                onChange={(next) => handleContentChange(next as unknown as Record<string, unknown>)}
              />
            )}
          </div>
        ) : (
          <textarea
            style={{
              ...inputStyle,
              fontFamily: 'ui-monospace, monospace',
              fontSize: 12,
              minHeight: 160,
              resize: 'vertical',
            }}
            value={jsonText}
            onChange={(e) => handleJsonChange(e.target.value)}
          />
        )}
      </div>

      {error && <div style={{ fontSize: 12, color: 'var(--error)' }}>{error}</div>}

      {/* 底部保存 / 取消 */}
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 4 }}>
        <button
          type="button"
          onClick={onClose}
          disabled={saving}
          style={{
            background: 'none',
            border: '1px solid var(--border)',
            color: 'var(--text-secondary)',
            borderRadius: 6,
            padding: '6px 16px',
            cursor: 'pointer',
            fontSize: 13,
          }}
        >
          {t('common.cancel', '取消')}
        </button>
        <button
          type="button"
          onClick={save}
          disabled={saving}
          style={{
            background: 'var(--accent)',
            color: '#fff',
            border: 'none',
            borderRadius: 6,
            padding: '6px 18px',
            cursor: 'pointer',
            fontSize: 13,
            fontWeight: 500,
            opacity: saving ? 0.6 : 1,
          }}
        >
          {saving ? t('testcase.saving', '保存中…') : t('testcase.save', '保存用例')}
        </button>
      </div>
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center' }}>
      <span style={labelStyle}>{label}</span>
      <div style={{ flex: 1, minWidth: 0 }}>{children}</div>
    </div>
  );
}
