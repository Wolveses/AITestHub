import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { Citation } from '../store/conversationStore';

export interface CitationItem {
  index: number;
  citation: Citation;
}

export interface GroupedCitation {
  document_id: number;
  document_name: string;
  items: CitationItem[];
}

/**
 * 将平铺的 citations 数组按 document_id（相同文档）分组归纳，
 * 保持原本的 1-based 序号与出现顺序
 */
export function groupCitations(citations: Citation[]): GroupedCitation[] {
  const groups: GroupedCitation[] = [];
  const map = new Map<number | string, GroupedCitation>();

  citations.forEach((c, idx) => {
    const key = c.document_id ?? c.document_name;
    let group = map.get(key);
    if (!group) {
      group = {
        document_id: c.document_id,
        document_name: c.document_name,
        items: [],
      };
      map.set(key, group);
      groups.push(group);
    }
    group.items.push({
      index: idx + 1,
      citation: c,
    });
  });

  return groups;
}

export function CitationCard({
  group,
  highlightIndex,
  flashKey,
  onPreview,
}: {
  group: GroupedCitation;
  /** 触发高亮且对应到该组内的某个具体引用序号（1-based） */
  highlightIndex?: number | null;
  /** 每次点击重新触发动画与展开的自增 key */
  flashKey?: number;
  /** 点击文档名或整篇预览按钮预览该文档 */
  onPreview?: (documentId: number, documentName: string) => void;
}) {
  const { t } = useTranslation();

  // 当前展开预览片段的 index（若外部传入 highlightIndex 且命中本组，则初始展开它）
  const [activeSnippetIdx, setActiveSnippetIdx] = useState<number | null>(() => {
    if (highlightIndex && group.items.some((it) => it.index === highlightIndex)) {
      return highlightIndex;
    }
    return null;
  });

  // 当外部 highlightIndex 或 flashKey 变化且属于当前分组时，自动激活并展开对应片段
  const [lastTriggerKey, setLastTriggerKey] = useState<string>(() => `${highlightIndex}-${flashKey}`);
  const currentTriggerKey = `${highlightIndex}-${flashKey}`;
  if (currentTriggerKey !== lastTriggerKey) {
    setLastTriggerKey(currentTriggerKey);
    if (highlightIndex && group.items.some((it) => it.index === highlightIndex)) {
      setActiveSnippetIdx(highlightIndex);
    }
  }

  const isCardHighlighted = Boolean(
    highlightIndex && group.items.some((it) => it.index === highlightIndex)
  );

  const toggleSnippet = (idx: number) => {
    setActiveSnippetIdx((current) => (current === idx ? null : idx));
  };

  const activeItem = group.items.find((it) => it.index === activeSnippetIdx);

  return (
    <div
      style={{
        background: isCardHighlighted ? 'var(--accent-deep)' : 'var(--bg-card)',
        border: isCardHighlighted ? '1px solid var(--accent)' : '1px solid var(--border)',
        borderRadius: 8,
        padding: '8px 12px',
        marginTop: 6,
        fontSize: 12,
        transition: 'background 0.3s, border-color 0.3s',
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: 8,
          color: 'var(--text-secondary)',
        }}
      >
        {/* 左侧：序号标签列表 + 文档名 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, overflow: 'hidden', flex: 1 }}>
          {/* 序号徽章列表 */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexShrink: 0 }}>
            {group.items.map((it) => {
              const isSelected = activeSnippetIdx === it.index;
              const isItemHighlighted = highlightIndex === it.index;
              return (
                <button
                  key={it.index}
                  data-cite-index={it.index}
                  onClick={() => toggleSnippet(it.index)}
                  title={t('ai.clickToPreviewSnippet', '点击预览片段')}
                  className={isItemHighlighted ? 'cite-flash' : undefined}
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    padding: '1px 6px',
                    borderRadius: 4,
                    fontSize: 11,
                    fontWeight: 600,
                    cursor: 'pointer',
                    border: isSelected
                      ? '1px solid var(--accent)'
                      : isItemHighlighted
                      ? '1px solid var(--accent)'
                      : '1px solid var(--border)',
                    background: isSelected
                      ? 'var(--accent)'
                      : isItemHighlighted
                      ? 'var(--accent-soft)'
                      : 'var(--bg-elevated)',
                    color: isSelected
                      ? '#ffffff'
                      : isItemHighlighted
                      ? 'var(--accent)'
                      : 'var(--text-primary)',
                    transition: 'all 0.15s ease',
                  }}
                >
                  [{it.index}]
                </button>
              );
            })}
          </div>

          {/* 文档名称 */}
          <span
            onClick={() => onPreview?.(group.document_id, group.document_name)}
            title={onPreview ? t('ai.clickToPreviewDoc', '点击预览文档') : undefined}
            style={{
              color: onPreview ? 'var(--accent)' : 'inherit',
              cursor: onPreview ? 'pointer' : 'default',
              textDecoration: onPreview ? 'underline' : 'none',
              textUnderlineOffset: 3,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
              fontWeight: 500,
            }}
          >
            {group.document_name}
          </span>
        </div>

        {/* 右侧：整篇预览与收起/展开 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
          {onPreview && (
            <button
              onClick={() => onPreview(group.document_id, group.document_name)}
              style={{
                background: 'none',
                border: 'none',
                color: 'var(--accent)',
                cursor: 'pointer',
                fontSize: 11,
                padding: '2px 4px',
              }}
            >
              {t('ai.docPreview', '预览文档')}
            </button>
          )}
          <button
            onClick={() => {
              if (activeSnippetIdx !== null) {
                setActiveSnippetIdx(null);
              } else {
                setActiveSnippetIdx(group.items[0]?.index ?? null);
              }
            }}
            style={{
              background: 'none',
              border: 'none',
              color: 'var(--text-muted)',
              cursor: 'pointer',
              fontSize: 11,
              padding: '2px 4px',
            }}
          >
            {activeSnippetIdx !== null ? t('ai.citationCollapse', '收起') : t('ai.citationExpand', '展开')}
          </button>
        </div>
      </div>

      {/* 展开的片段预览 */}
      {activeItem && (
        <div
          style={{
            marginTop: 8,
            padding: '8px 10px',
            borderRadius: 6,
            background: 'var(--bg-base)',
            border: '1px solid var(--border)',
            fontSize: 12,
            lineHeight: 1.5,
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              marginBottom: 4,
              fontSize: 11,
              color: 'var(--text-muted)',
            }}
          >
            <span>
              [{activeItem.index}] · {t('ai.citationSnippet', { index: activeItem.citation.chunk_index })}
            </span>
            <span style={{ fontSize: 10 }}>
              {activeItem.citation.score ? `score: ${activeItem.citation.score.toFixed(2)}` : ''}
            </span>
          </div>
          <div
            style={{
              color: 'var(--text-secondary)',
              maxHeight: 140,
              overflow: 'auto',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
            }}
          >
            {activeItem.citation.snippet}
          </div>
        </div>
      )}
    </div>
  );
}
