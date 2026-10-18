import { useState, useRef, useEffect } from 'react';
import * as Tooltip from '@radix-ui/react-tooltip';
import { useTranslation } from 'react-i18next';
import { Brain, ChevronDown, HelpCircle, Check } from 'lucide-react';
import { text, RADIUS, SPRING } from './agentStyles';

/**
 * 思考级别选择器（自动折叠/展开下拉式）。
 *
 * 级别：off（关）/ low（低）/ medium（中）/ high（高）。
 * 默认折叠：仅展示大脑图标 + 当前级别文案 + 下拉箭头。
 * 点击展开：展开轻量下拉浮层选择级别与规则提示。
 */

export type ThinkingLevel = 'off' | 'low' | 'medium' | 'high';

const LEVELS: { value: ThinkingLevel; labelKey: string }[] = [
  { value: 'off', labelKey: 'ai.thinkingOff' },
  { value: 'low', labelKey: 'ai.thinkingLevelLow' },
  { value: 'medium', labelKey: 'ai.thinkingLevelMedium' },
  { value: 'high', labelKey: 'ai.thinkingLevelHigh' },
];

interface Props {
  value: ThinkingLevel;
  onChange: (level: ThinkingLevel) => void;
  size?: 'sm' | 'md';
  isMobile?: boolean;
}

export function ThinkingLevelControl({
  value,
  onChange,
  size = 'sm',
  isMobile,
}: Props) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const { t } = useTranslation();

  const fontSize = size === 'sm' ? 11 : 12;
  const padding = isMobile ? '6px 10px' : '4px 8px';

  // 点击外部自动收起
  useEffect(() => {
    if (!open) return;
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [open]);

  const currentLevel = LEVELS.find((l) => l.value === value) || LEVELS[0];
  const isActive = value !== 'off';

  return (
    <Tooltip.Provider delayDuration={200}>
      <div ref={containerRef} style={{ position: 'relative', display: 'inline-flex' }}>
        {/* 折叠触发按钮 */}
        <button
          type="button"
          onClick={() => setOpen((prev) => !prev)}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            height: 28,
            boxSizing: 'border-box',
            gap: 5,
            padding,
            fontSize,
            cursor: 'pointer',
            border: `1px solid var(--border-strong)`,
            borderRadius: RADIUS.sm,
            background: isActive ? 'rgba(16,185,129,0.12)' : 'transparent',
            color: isActive ? text.accent : text.secondary,
            fontWeight: isActive ? 600 : 400,
            transition: `all 0.15s ${SPRING}`,
            fontFamily: 'inherit',
          }}
          title={t('ai.thinkingLevelAriaLabel', '思考级别')}
        >
          <Brain
            size={13}
            strokeWidth={1.5}
            style={{ color: isActive ? text.accent : text.muted, flexShrink: 0 }}
          />
          <span>思考: {t(currentLevel.labelKey)}</span>
          <ChevronDown
            size={12}
            strokeWidth={1.5}
            style={{
              transform: open ? 'rotate(180deg)' : 'none',
              transition: 'transform 0.15s ease',
              opacity: 0.6,
            }}
          />
        </button>

        {/* 展开浮层菜单 */}
        {open && (
          <div
            style={{
              position: 'absolute',
              bottom: 'calc(100% + 6px)',
              right: 0,
              minWidth: 150,
              backgroundColor: 'var(--bg-elevated, #fff)',
              border: '1px solid var(--border-strong)',
              borderRadius: 8,
              boxShadow: 'var(--shadow-elevated, 0 8px 20px rgba(0,0,0,0.15))',
              padding: 4,
              zIndex: 1100,
              display: 'flex',
              flexDirection: 'column',
              gap: 2,
            }}
          >
            {LEVELS.map((lv) => {
              const selected = value === lv.value;
              return (
                <div
                  key={lv.value}
                  onClick={() => {
                    onChange(lv.value);
                    setOpen(false);
                  }}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: '6px 10px',
                    borderRadius: 6,
                    fontSize: 12,
                    cursor: 'pointer',
                    color: selected ? text.accent : 'var(--text-primary)',
                    fontWeight: selected ? 600 : 400,
                    background: selected ? 'rgba(16,185,129,0.1)' : 'transparent',
                    transition: 'background 0.15s ease',
                  }}
                  className="hover-bg"
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <span>{t(lv.labelKey)}</span>
                  </div>
                  {selected && <Check size={13} strokeWidth={2} style={{ color: text.accent }} />}
                </div>
              );
            })}

            {/* 底部规则说明提示 */}
            <div
              style={{
                marginTop: 4,
                paddingTop: 6,
                borderTop: '1px solid var(--border)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                paddingLeft: 8,
                paddingRight: 6,
                fontSize: 11,
                color: text.muted,
              }}
            >
              <span>说明</span>
              <Tooltip.Root>
                <Tooltip.Trigger asChild>
                  <button
                    type="button"
                    onClick={(e) => e.stopPropagation()}
                    style={{
                      background: 'none',
                      border: 'none',
                      cursor: 'help',
                      padding: 2,
                      color: text.muted,
                      display: 'inline-flex',
                      alignItems: 'center',
                    }}
                  >
                    <HelpCircle size={13} strokeWidth={1.5} />
                  </button>
                </Tooltip.Trigger>
                <Tooltip.Portal>
                  <Tooltip.Content
                    sideOffset={6}
                    style={{
                      background: 'var(--bg-elevated)',
                      border: '1px solid var(--border-strong)',
                      borderRadius: RADIUS.sm,
                      padding: '10px 12px',
                      maxWidth: 280,
                      boxShadow: 'var(--shadow-elevated)',
                      zIndex: 1200,
                    }}
                  >
                    <ThinkingRules />
                    <Tooltip.Arrow style={{ fill: 'var(--bg-elevated)', stroke: 'var(--border-strong)' }} />
                  </Tooltip.Content>
                </Tooltip.Portal>
              </Tooltip.Root>
            </div>
          </div>
        )}
      </div>
    </Tooltip.Provider>
  );
}

function ThinkingRules() {
  const { t } = useTranslation();
  return (
    <div style={{ fontSize: 11, lineHeight: 1.7, color: text.secondary }}>
      <div style={{ fontWeight: 600, color: text.primary, marginBottom: 6 }}>{t('ai.thinkingRulesTitle')}</div>
      <Rule label={t('ai.thinkingOff')} desc={t('ai.thinkingRuleOffDesc')} />
      <Rule label={t('ai.thinkingLevelLow')} desc={t('ai.thinkingRuleLowDesc')} />
      <Rule label={t('ai.thinkingLevelMedium')} desc={t('ai.thinkingRuleMediumDesc')} />
      <Rule label={t('ai.thinkingLevelHigh')} desc={t('ai.thinkingRuleHighDesc')} />
      <div style={{ marginTop: 6, paddingTop: 6, borderTop: '1px solid var(--bg-card)', color: text.muted }}>
        {t('ai.thinkingRuleFooter')}
      </div>
    </div>
  );
}

function Rule({ label, desc }: { label: string; desc: string }) {
  return (
    <div style={{ display: 'flex', gap: 6, marginBottom: 2 }}>
      <span style={{ color: text.accent, fontWeight: 600, flexShrink: 0, width: 28 }}>{label}</span>
      <span style={{ color: text.secondary }}>{desc}</span>
    </div>
  );
}

/** 把旧的 thinking_enabled (bool) 迁移到 thinking_level（兼容历史数据）。 */
export function migrateThinkingLevel(raw: unknown): ThinkingLevel {
  if (raw === true) return 'medium';
  if (raw === false) return 'off';
  if (typeof raw === 'string' && ['off', 'low', 'medium', 'high'].includes(raw)) {
    return raw as ThinkingLevel;
  }
  return 'off';
}
