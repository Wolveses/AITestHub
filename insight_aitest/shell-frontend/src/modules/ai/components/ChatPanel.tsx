import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useConversationStore } from '../store/conversationStore';
import { MessageBubble } from './MessageBubble';
import { ChatInput } from './ChatInput';
import { EmptyState } from '../../../shared/components/EmptyState';
import { ThinkingLevelControl, migrateThinkingLevel, type ThinkingLevel } from './ThinkingLevelControl';
import { useIsMobile } from '../../../shared/hooks/useIsMobile';
import { DocumentViewer } from '../../kb/components/DocumentViewer';
import type { Document } from '../../kb/store/knowledgeStore';

export function ChatPanel() {
  const {
    activeId,
    messages,
    streamingMessage,
    streamingThinking,
    streaming,
    conversations,
    setThinkingLevel,
    sendMessage,
    stopStreaming,
  } = useConversationStore();
  const isMobile = useIsMobile();
  const endRef = useRef<HTMLDivElement>(null);
  const { t } = useTranslation();

  // 文档预览状态
  const [previewDoc, setPreviewDoc] = useState<Document | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);

  const handlePreviewDoc = async (docId: number, docName: string) => {
    try {
      const res = await fetch(`/api/modules/kb/documents/${docId}`);
      if (res.ok) {
        const d: Document = await res.json();
        setPreviewDoc(d);
        setPreviewOpen(true);
        return;
      }
    } catch {
      /* 静默 */
    }
    setPreviewDoc({
      id: docId,
      filename: docName,
      status: 'ready',
      char_count: 0,
      chunk_count: 0,
      error_message: null,
      project_id: null,
      version_id: null,
      folder_id: null,
      tags: [],
      doc_type: '',
      description: '',
      created_at: new Date().toISOString(),
    });
    setPreviewOpen(true);
  };

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamingMessage]);

  if (!activeId) {
    return <EmptyState message={t('ai.emptyNew')} />;
  }
  const msgs = messages[activeId] ?? [];
  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', position: 'relative' }}>
      {activeId && (() => {
        const conv = conversations.find((c) => c.id === activeId);
        return conv ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 16px', borderBottom: '1px solid var(--bg-card)', fontSize: 12, color: "var(--text-secondary)" }}>
            <ThinkingLevelControl
              value={migrateThinkingLevel(conv.thinking_level)}
              onChange={(lv: ThinkingLevel) => setThinkingLevel(activeId, lv)}
              isMobile={isMobile}
            />
          </div>
        ) : null;
      })()}
      <div style={{ flex: 1, overflow: 'auto', padding: 16 }}>
        {msgs.length === 0 && !streamingMessage && (
          <EmptyState message={t('ai.emptyAsk')} />
        )}
        {msgs.map((m, i) => (
          <MessageBubble key={i} message={m} onPreviewDoc={handlePreviewDoc} />
        ))}
        {streamingMessage !== null && (
          <MessageBubble
            message={{
              role: 'assistant',
              content: streamingMessage + ' ▌',
              thinking: streamingThinking || undefined,
            }}
            onPreviewDoc={handlePreviewDoc}
          />
        )}
        <div ref={endRef} />
      </div>
      <ChatInput onSend={sendMessage} disabled={streaming} />
      {streaming && (
        <button
          onClick={stopStreaming}
          style={{
            position: 'absolute', bottom: 60, right: 24, background: "var(--border-strong)",
            border: '1px solid var(--border-strong)', color: 'var(--text-primary)', borderRadius: 4, padding: '4px 12px', cursor: 'pointer',
          }}
        >
          {t('ai.stop')}
        </button>
      )}
      <DocumentViewer doc={previewDoc} open={previewOpen} onOpenChange={setPreviewOpen} />
    </div>
  );
}
