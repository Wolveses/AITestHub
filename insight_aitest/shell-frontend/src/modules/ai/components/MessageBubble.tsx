import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { Message } from '../store/conversationStore';
import { AttachmentChips } from './AttachmentChips';
import { CitationCard, groupCitations } from './CitationCard';
import { ThinkingPanel } from './ThinkingPanel';
import { Paperclip } from 'lucide-react';


export function MessageBubble({
  message,
  onPreviewDoc,
}: {
  message: Message;
  onPreviewDoc?: (documentId: number, documentName: string) => void;
}) {
  const isUser = message.role === 'user';
  const [highlightedCite, setHighlightedCite] = useState<number | null>(null);
  const [flashKey, setFlashKey] = useState(0); // 重启闪烁动画用
  const { t } = useTranslation();

  const citeCount = message.citations?.length ?? 0;
  const referencedIndices = new Set<number>();
  let rendered = message.content || '';
  if (!isUser && citeCount > 0) {
    rendered = rendered.replace(/\[(\d+)\]/g, (m, n) => {
      const idx = parseInt(n, 10);
      if (idx >= 1 && idx <= citeCount) {
        referencedIndices.add(idx);
        return `[[${idx}]](#cite-${idx})`;
      }
      return m;
    });
  }

  const groupedCitations = !isUser && message.citations && message.citations.length > 0
    ? groupCitations(message.citations, referencedIndices)
    : [];

  const handleCitationClick = (n: number) => {
    setHighlightedCite(n);
    setFlashKey((k) => k + 1); // 重复点击同一引用时重新触发动画
    // 滚动到对应卡片并展示片段
    requestAnimationFrame(() => {
      const el = document.querySelector(`[data-cite-index="${n}"]`);
      el?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    });
  };

  return (
    <div style={{ marginBottom: 16 }}>
      <div
        style={{
          maxWidth: '80%',
          padding: 12,
          borderRadius: 8,
          background: isUser ? 'var(--bg-elevated)' : "var(--bg-card)",
          border: isUser ? '1px solid var(--bg-elevated)' : '1px solid var(--bg-card)',
          marginLeft: isUser ? 'auto' : 0,
        }}
      >
        <div style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 4 }}>
          {isUser ? t('ai.you') : t('ai.aiAssistant')}
        </div>
        {!isUser && message.thinking && (
          <ThinkingPanel thinking={message.thinking} />
        )}
        <div className="markdown-body">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              a({ href, children, ...props }) {
                const m = href?.match(/^#cite-(\d+)$/);
                if (m) {
                  const n = parseInt(m[1], 10);
                  return (
                    <a
                      href={href}
                      className="cite-mark"
                      onClick={(e) => {
                        e.preventDefault();
                        handleCitationClick(n);
                      }}
                      {...props}
                    >
                      {children}
                    </a>
                  );
                }
                return (
                  <a href={href} target="_blank" rel="noreferrer" {...props}>
                    {children}
                  </a>
                );
              },
            }}
          >
            {rendered}
          </ReactMarkdown>
        </div>
      </div>
      {!isUser && groupedCitations.length > 0 && (
        <div style={{ marginTop: 8 }}>
          <div style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 4, display: 'inline-flex', alignItems: 'center', gap: 4 }}>
            <Paperclip size={12} strokeWidth={1.5} />
            {t('ai.referenceSource', '引用来源')}
          </div>
          {groupedCitations.map((group, i) => (
            <CitationCard
              key={`${group.document_id ?? group.document_name}-${i}`}
              group={group}
              highlightIndex={highlightedCite}
              flashKey={flashKey}
              onPreview={onPreviewDoc}
            />
          ))}
        </div>
      )}
      {message.attachments && message.attachments.length > 0 && (
        <AttachmentChips attachments={message.attachments} />
      )}
    </div>
  );
}
