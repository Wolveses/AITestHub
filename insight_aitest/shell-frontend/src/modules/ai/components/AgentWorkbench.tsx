import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useTaskStore, type AgentMessage } from '../store/taskStore';
import { useAgentProfileStore } from '../store/agentProfileStore';
import { AgentInput } from './AgentInput';
import { UnderstandCard } from './UnderstandCard';
import { StrategyCard } from './StrategyCard';
import { TaskProgress } from './TaskProgress';
import { TaskResult } from './TaskResult';
import { AgentProgress } from './AgentProgress';
import { TestPointCard } from './cards/TestPointCard';
import { CaseReviewCard } from './cards/CaseReviewCard';
import { StepTrace } from './react/StepTrace';
import { RcaDialog } from './react/RcaDialog';
import { ThinkingPanel } from './ThinkingPanel';
import { ThinkingLevelControl, type ThinkingLevel } from './ThinkingLevelControl';
import { KbToggle } from './KbToggle';
import { ModelPicker } from './ModelPicker';
import { WorkModeSelector } from './WorkModeSelector';
import { glassInputBar, text, SPRING, RADIUS } from './agentStyles';
import { RotateCcw, ArrowDown, Paperclip } from 'lucide-react';
import agentAvatarDefault from '../../../assets/agent-avatar.jpg';
import { CitationCard, groupCitations } from './CitationCard';
import { DocumentViewer } from '../../kb/components/DocumentViewer';
import type { Document } from '../../kb/store/knowledgeStore';

export function AgentWorkbench() {
  const {
    messages, phase, phaseMessage, streamingThinking, streamingMessage,
    resetConversation, stopStreaming, thinkingLevel, setThinkingLevel,
    kbMode, setKbMode, selectedDocIds, setSelectedDocIds,
    workMode, setWorkMode,
  } = useTaskStore();

  const agentName = useAgentProfileStore((s) => s.name);
  const agentAvatar = useAgentProfileStore((s) => s.avatar);
  const avatarSrc = agentAvatar ?? agentAvatarDefault;
  const scrollRef = useRef<HTMLDivElement>(null);
  const isAtBottomRef = useRef(true);
  const [showScrollBottomBtn, setShowScrollBottomBtn] = useState(false);
  const prevMsgCountRef = useRef(messages.length);
  const { t } = useTranslation();

  // 文档预览弹窗状态
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
    // 降级兜底：构造基础 Document 对象直接供 DocumentViewer 使用
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

  const handleScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const distanceToBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    const atBottom = distanceToBottom <= 60;
    isAtBottomRef.current = atBottom;
    setShowScrollBottomBtn(!atBottom);
  };

  const scrollToBottom = (smooth = false) => {
    const el = scrollRef.current;
    if (!el) return;
    isAtBottomRef.current = true;
    setShowScrollBottomBtn(false);
    if (smooth) {
      el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
    } else {
      el.scrollTop = el.scrollHeight;
    }
  };

  // 当用户发了新消息时：强制复位到吸底并滚动到底部
  useEffect(() => {
    if (messages.length > prevMsgCountRef.current) {
      isAtBottomRef.current = true;
      setShowScrollBottomBtn(false);
      scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
    }
    prevMsgCountRef.current = messages.length;
  }, [messages.length]);

  // 当处于吸底状态时跟随流式更新；若用户主动向上滚动阅读则不打断
  useEffect(() => {
    if (isAtBottomRef.current) {
      const el = scrollRef.current;
      if (el) {
        el.scrollTop = el.scrollHeight;
      }
    }
  }, [messages, phase, streamingMessage, streamingThinking]);

  const busy = phase === 'uploading' || phase === 'understanding' || phase === 'strategizing' || phase === 'executing';
  const showStreamingBubble = typeof streamingMessage === 'string' && streamingMessage.length > 0;
  const showThinkingChain = busy && thinkingLevel !== 'off' && typeof streamingThinking === 'string' && streamingThinking.trim().length > 0;

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', position: 'relative' }}>
      <style>{aiKeyframes}</style>
      {/* 对话区域 */}
      <div ref={scrollRef} onScroll={handleScroll} style={{ flex: 1, overflow: 'auto', padding: '24px 0' }}>
        <div style={{ maxWidth: 720, margin: '0 auto', padding: '0 24px' }}>
          {messages.length === 0 && !busy && <AgentWelcomeState name={agentName} avatar={avatarSrc} />}
          {messages.map((msg, i) => (
            <MessageBubble key={i} msg={msg} onPreviewDoc={handlePreviewDoc} />
          ))}
          {/* 思维链（仅在思考级别未关闭且有思考内容时展示） */}
          {showThinkingChain && (
            <ThinkingPanel thinking={streamingThinking!} streaming />
          )}
          {/* 流式文本气泡（仅在已有 token 内容时展示，避免展示空内容+光标气泡） */}
          {showStreamingBubble && (
            <MessageBubble
              msg={{ role: 'agent', card: 'chat', content: streamingMessage + ' ▌' }}
              onPreviewDoc={handlePreviewDoc}
            />
          )}
          {/* 等待首个 token 的微提示 */}
          {busy && !showStreamingBubble && !showThinkingChain && (
            <div style={{ marginBottom: 16, color: text.muted, fontSize: 13, display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{ display: 'inline-block', width: 6, height: 6, borderRadius: '50%', background: 'var(--accent)', animation: 'agent-pulse 1.2s ease-in-out infinite' }} />
              {workMode === 'chat'
                ? (thinkingLevel !== 'off' ? '正在思考…' : '正在组织回答…')
                : (phaseMessage || t('ai.thinkingDefault'))}
            </div>
          )}
          {/* 任务进度（仅任务模式展示三阶段计时步骤卡片） */}
          {busy && workMode === 'task' && (
            <>
              <AgentProgress phase={phase} message={phaseMessage} thinking={thinkingLevel !== 'off' ? streamingThinking : null} />
              {(phase === 'understanding' || phase === 'strategizing') && (
                <div style={{ textAlign: 'center', marginBottom: 12 }}>
                  <button
                    onClick={stopStreaming}
                    style={{
                      background: 'none', border: '1px solid var(--border-strong)', color: 'var(--text-secondary)',
                      borderRadius: 999, padding: '4px 16px', cursor: 'pointer', fontSize: 11,
                    }}
                  >
                    {t('ai.stopGen')}
                  </button>
                </div>
              )}
            </>
          )}
          {/* 流式中可中断 */}
          {busy && (showStreamingBubble || showThinkingChain) && (
            <div style={{ textAlign: 'center', marginBottom: 12 }}>
              <button
                onClick={stopStreaming}
                style={{
                  background: 'none', border: '1px solid var(--border-strong)', color: 'var(--text-secondary)',
                  borderRadius: 999, padding: '4px 16px', cursor: 'pointer', fontSize: 11,
                }}
              >
                {t('ai.stopGen')}
              </button>
            </div>
          )}
        </div>
      </div>

      {/* 滚动到底部快捷悬浮按钮 */}
      {showScrollBottomBtn && (
        <button
          onClick={() => scrollToBottom(true)}
          style={{
            position: 'absolute',
            bottom: 84,
            left: '50%',
            transform: 'translateX(-50%)',
            zIndex: 20,
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            background: 'var(--bg-elevated)',
            color: 'var(--text-secondary)',
            border: '1px solid var(--border)',
            borderRadius: 999,
            padding: '6px 14px',
            fontSize: 12,
            fontWeight: 500,
            cursor: 'pointer',
            boxShadow: 'var(--shadow-popup, 0 4px 12px rgba(0,0,0,0.15))',
            transition: 'all 0.2s ease',
          }}
        >
          <ArrowDown size={13} strokeWidth={2} />
          <span>{t('ai.scrollToBottom')}</span>
        </button>
      )}

      {/* 浮动输入栏（Spotlight 风格，悬浮在对话区上方） */}
      <div style={{ padding: '0 24px 16px' }}>
        <div style={{ maxWidth: 720, margin: '0 auto' }}>
          {/* 模式选择 + 思考级别 + 知识库检索 + 模型切换控制（输入栏上方） */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, marginBottom: 8 }}>
            <WorkModeSelector
              value={workMode}
              onChange={setWorkMode}
              disabled={busy}
            />
            <div style={{ display: 'inline-flex', gap: 8, alignItems: 'center' }}>
              <ModelPicker size="sm" />
              <KbToggle
                mode={kbMode}
                onModeChange={setKbMode}
                selectedDocIds={selectedDocIds}
                onDocIdsChange={setSelectedDocIds}
              />
              <ThinkingLevelControl
                value={thinkingLevel}
                onChange={(lv: ThinkingLevel) => setThinkingLevel(lv)}
                size="sm"
              />
            </div>
          </div>

          <div style={{ ...glassInputBar, padding: 12 }}>
            <AgentInput />
          </div>
          {messages.length > 0 && (
            <button
              onClick={() => resetConversation()}
              style={{
                background: 'none', border: 'none', color: text.muted,
                cursor: 'pointer', fontSize: 11, marginTop: 8, padding: 0,
                transition: `color 0.2s ${SPRING}`,
              }}
              onMouseEnter={(e) => (e.currentTarget.style.color = text.secondary)}
              onMouseLeave={(e) => (e.currentTarget.style.color = text.muted)}
            >
              <RotateCcw size={11} strokeWidth={1.5} style={{ verticalAlign: '-1px', marginRight: 4 }} />{t('ai.startNew')}
            </button>
          )}
        </div>
      </div>

      {/* 文档全屏预览/查看器弹窗 */}
      <DocumentViewer doc={previewDoc} open={previewOpen} onOpenChange={setPreviewOpen} />
    </div>
  );
}

function AgentWelcomeState({ name, avatar }: { name: string; avatar: string }) {
  const { t } = useTranslation();
  return (
    <div style={{ textAlign: 'center', padding: '60px 20px 40px' }}>
      <img
        src={avatar}
        alt={t('ai.agentAvatarAlt', { name })}
        style={{
          width: 120, height: 120, borderRadius: '50%', objectFit: 'cover',
          margin: '0 auto 20px', display: 'block',
          border: '1px solid var(--border)', boxShadow: 'var(--shadow-elevated)',
        }}
      />
      <p style={{ fontSize: 15, lineHeight: 1.4, color: text.primary, maxWidth: 360, margin: '0 auto 6px', fontWeight: 500 }}>
        {t('ai.welcomeHi', { name })}
      </p>
      <p style={{ fontSize: 13, lineHeight: 1.8, color: text.secondary, maxWidth: 360, margin: '0 auto' }}>
        {t('ai.welcomeDesc')}
        <br />
        {t('ai.welcomeUploadHint')}
      </p>
    </div>
  );
}

function MessageBubble({
  msg,
  onPreviewDoc,
}: {
  msg: AgentMessage;
  onPreviewDoc?: (documentId: number, documentName: string) => void;
}) {
  const isUser = msg.role === 'user';
  const { t } = useTranslation();
  // ReAct trace / rca：progress 卡片下展示 trace，中止时弹出 RCA
  const trace = useTaskStore((s) => (msg.taskId ? s.trace[msg.taskId] : undefined));
  const taskRca = useTaskStore((s) => (msg.taskId ? s.rca[msg.taskId] : undefined));
  const [rcaOpen, setRcaOpen] = useState(false);
  const [highlightedCite, setHighlightedCite] = useState<number | null>(null);
  const [flashKey, setFlashKey] = useState(0);
  const hasTrace = !!trace && Object.keys(trace).length > 0;
  // 当出现 rca 且尚未交互关闭时，默认展示
  const rcaVisible = !!taskRca && rcaOpen;

  // card 类消息（understand/strategies/progress/result）走卡片渲染；chat 走普通气泡
  if (!isUser && msg.card && msg.card !== 'chat') {
    return (
      <div style={{ marginBottom: 16, animation: 'agent-msg-enter 0.4s cubic-bezier(0.16,1,0.3,1)' }}>
        {msg.card === 'understand' && msg.content && <UnderstandCard summary={msg.content} />}
        {msg.card === 'strategies' && <StrategyCard />}
        {msg.card === 'progress' && <TaskProgress />}
        {msg.card === 'result' && <TaskResult />}
        {msg.card === 'test_points' && msg.taskId && <TestPointCard taskId={msg.taskId} />}
        {msg.card === 'case_review' && msg.taskId && <CaseReviewCard taskId={msg.taskId} />}
        {/* ReAct trace：progress 卡片下按 step 折叠展示 */}
        {msg.card === 'progress' && msg.taskId && hasTrace && (
          <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 4 }}>
            <div style={{ fontSize: 10, color: 'var(--text-muted)', fontWeight: 600, letterSpacing: '0.04em', marginBottom: 2, paddingLeft: 2 }}>
              {t('ai.reactTrace')}
            </div>
            {Object.entries(trace!)
              .sort(([a], [b]) => Number(a) - Number(b))
              .map(([idx, entries]) => (
                <StepTrace key={idx} stepIndex={Number(idx)} entries={entries} />
              ))}
          </div>
        )}
        {/* 中止时：在 trace 区下方放一个"查看根因分析"入口 */}
        {msg.card === 'progress' && msg.taskId && taskRca && (
          <div style={{ marginTop: 8 }}>
            <button
              onClick={() => setRcaOpen(true)}
              style={{
                background: 'rgba(220,38,38,0.08)',
                border: '1px solid rgba(220,38,38,0.3)',
                color: 'var(--error)',
                borderRadius: 999,
                padding: '4px 14px',
                cursor: 'pointer',
                fontSize: 11,
                fontWeight: 600,
              }}
            >
              {t('ai.abortedRca')}
            </button>
          </div>
        )}
        {msg.taskId && taskRca && (
          <RcaDialog open={rcaVisible} rca={taskRca} onClose={() => setRcaOpen(false)} />
        )}
      </div>
    );
  }

  const thinkingLevel = useTaskStore((s) => s.thinkingLevel);
  const citeCount = msg.citations?.length ?? 0;

  // 统计正文中实际引用的 [n] 序号
  const referencedIndices = new Set<number>();
  let renderedContent = msg.content || '';
  if (!isUser && citeCount > 0) {
    renderedContent = renderedContent.replace(/\[(\d+)\]/g, (match, n) => {
      const idx = parseInt(n, 10);
      if (idx >= 1 && idx <= citeCount) {
        referencedIndices.add(idx);
        return `[[${idx}]](#cite-${idx})`;
      }
      return match;
    });
  }

  const groupedCitations = !isUser && msg.citations && msg.citations.length > 0
    ? groupCitations(msg.citations, referencedIndices)
    : [];

  const handleCitationClick = (n: number) => {
    setHighlightedCite(n);
    setFlashKey((k) => k + 1);
    // 滚动到对应卡片并展示片段
    requestAnimationFrame(() => {
      const el = document.querySelector(`[data-cite-index="${n}"]`);
      el?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    });
  };

  return (
    <div
      style={{
        marginBottom: 16,
        display: 'flex',
        flexDirection: 'column',
        alignItems: isUser ? 'flex-end' : 'flex-start',
        animation: 'agent-msg-enter 0.35s cubic-bezier(0.16,1,0.3,1)',
      }}
    >
      <div
        style={{
          maxWidth: '80%',
          padding: '12px 16px',
          borderRadius: isUser ? `${RADIUS.lg}px ${RADIUS.lg}px 4px ${RADIUS.lg}px` : `${RADIUS.lg}px ${RADIUS.lg}px ${RADIUS.lg}px 4px`,
          background: isUser ? 'rgba(16,185,129,0.12)' : 'var(--bg-card)',
          border: isUser ? '1px solid rgba(16,185,129,0.25)' : '1px solid var(--border)',
          fontSize: 14,
          color: text.primary,
          lineHeight: 1.6,
          boxShadow: 'var(--shadow-card)',
        }}
      >
        {/* chat 模式的思考过程（落定后可折叠，仅在思考未关闭时展示） */}
        {!isUser && msg.thinking && thinkingLevel !== 'off' && <ThinkingPanel thinking={msg.thinking} />}
        {isUser ? (
          <span>{msg.content}</span>
        ) : (
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
              {renderedContent}
            </ReactMarkdown>
          </div>
        )}
        {msg.files && msg.files.length > 0 && (
          <div style={{ marginTop: 8, display: 'flex', gap: 4, flexWrap: 'wrap' }}>
            {msg.files.map((f, i) => (
              <span
                key={i}
                style={{
                  fontSize: 11,
                  color: text.accent,
                  background: 'rgba(16,185,129,0.08)',
                  border: '1px solid rgba(16,185,129,0.2)',
                  padding: '2px 8px',
                  borderRadius: RADIUS.sm,
                }}
              >
                {f}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* 引用来源卡片列表：仅当正文真正引用了参考资料时展示 */}
      {!isUser && groupedCitations.length > 0 && (
        <div style={{ marginTop: 8, maxWidth: '80%', width: '100%' }}>
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
    </div>
  );
}

/** AI 入场动画 keyframe（Stage 4：删呼吸/光球后只剩入场） */
const aiKeyframes = `
@keyframes agent-msg-enter {
  from { opacity: 0; transform: translateY(12px); }
  to { opacity: 1; transform: translateY(0); }
}
@keyframes agent-pulse {
  0%, 100% { opacity: 0.4; transform: scale(0.8); }
  50% { opacity: 1; transform: scale(1.2); }
}
`;
