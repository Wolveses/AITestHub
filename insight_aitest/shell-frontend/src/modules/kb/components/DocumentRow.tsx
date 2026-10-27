import { FileText, Eye, Download, Tag as TagIcon, History, FolderInput, CheckCircle2, CircleDashed, AlertCircle, XCircle, RefreshCw, Scissors } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { isNonTerminal, type Document } from '../store/knowledgeStore';
import { useConfirmStore } from '../../../shared/store/confirmStore';

const STATUS_KEY: Record<string, string> = {
  pending: 'kb.statusWaiting',
  parsing: 'kb.statusParsing',
  chunking: 'kb.statusChunking',
  embedding: 'kb.statusEmbedding',
  ready: 'kb.statusReady',
  not_vectorized: 'kb.statusNotVectorized',
  parse_failed: 'kb.statusParseFailed',
  embed_failed: 'kb.statusEmbedFailed',
  embed_partial: 'kb.statusEmbedPartial',
};

const STATUS_COLOR: Record<string, string> = {
  pending: "var(--text-secondary)",
  parsing: "var(--accent)",
  chunking: "var(--accent)",
  embedding: "var(--accent)",
  ready: 'var(--success, #10b981)',
  not_vectorized: 'var(--text-muted, #64748b)',
  parse_failed: 'var(--error)',
  embed_failed: 'var(--error)',
  embed_partial: 'var(--chart-3)',
};

const DOC_TYPE_KEY: Record<string, string> = {
  requirement: 'kb.typeRequirement',
  design: 'kb.typeDesign',
  interface: 'kb.typeInterface',
  test: 'kb.typeTest',
  other: 'kb.typeOther',
};

// TAPD 缺陷状态色（后端已把状态转成中文展示名），未匹配时使用次要文字色
const DEFECT_STATUS_COLOR: Record<string, string> = {
  新建: 'var(--accent)',
  已确认: 'var(--accent)',
  处理中: 'var(--chart-3)',
  已解决: 'var(--success, #10b981)',
  已修复: 'var(--success, #10b981)',
  已验证: 'var(--success, #10b981)',
  已关闭: 'var(--text-muted, #64748b)',
  已拒绝: 'var(--error)',
  重新打开: 'var(--error)',
  已挂起: 'var(--text-muted, #64748b)',
  已延期: 'var(--text-muted, #64748b)',
  // 兼容未翻译的原始枚举值
  new: 'var(--accent)',
  acknowledged: 'var(--accent)',
  in_progress: 'var(--chart-3)',
  resolved: 'var(--success, #10b981)',
  verified: 'var(--success, #10b981)',
  closed: 'var(--text-muted, #64748b)',
  rejected: 'var(--error)',
  reopened: 'var(--error)',
  suspended: 'var(--text-muted, #64748b)',
};

const defectStatusColor = (status: string): string =>
  DEFECT_STATUS_COLOR[status] ?? DEFECT_STATUS_COLOR[status?.toLowerCase?.() ?? ''] ?? 'var(--text-secondary)';

interface DocumentRowProps {
  doc: Document;
  vectorEnabled?: boolean;
  folderPath?: { id: number; name: string }[];
  showFolderScope?: boolean;
  onDelete: (id: number) => void;
  onPreview: (doc: Document) => void;
  onEditMeta: (doc: Document) => void;
  onShowVersions: (doc: Document) => void;
  onMove?: (doc: Document) => void;
  onSelectFolder?: (folderId: number | null) => void;
  onReindex?: (id: number) => void;
  onPreviewChunks?: (doc: Document) => void;
}

export function DocumentRow({
  doc,
  vectorEnabled,
  folderPath,
  showFolderScope = false,
  onDelete,
  onPreview,
  onEditMeta,
  onShowVersions,
  onMove,
  onSelectFolder,
  onReindex,
  onPreviewChunks,
}: DocumentRowProps) {
  const { t } = useTranslation();
  const defect = doc.kind === 'defect' ? doc.defect : null;
  const statusKey = STATUS_KEY[doc.status];
  const statusColor = STATUS_COLOR[doc.status] ?? "var(--text-secondary)";
  const { confirm } = useConfirmStore();
  const typeLabel = doc.doc_type && DOC_TYPE_KEY[doc.doc_type] ? t(DOC_TYPE_KEY[doc.doc_type]) : '';
  // 解析中：后端内存标记（reindexing）早于状态落库，优先使用；其次看非终态状态。
  // 解析期间该行所有操作置灰，避免多用户/本用户对同一文档并发读写。
  const isParsing = !!doc.reindexing || isNonTerminal(doc.status);
  const st = isParsing
    ? { text: t('kb.statusParsing', '解析中'), color: 'var(--accent)' }
    : { text: statusKey ? t(statusKey) : doc.status, color: statusColor };
  const actionStyle: React.CSSProperties = isParsing
    ? { ...iconBtnStyle, opacity: 0.45, cursor: 'not-allowed' }
    : iconBtnStyle;

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 12, padding: '10px 12px',
      borderBottom: '1px solid var(--bg-card)',
    }}>
      <span style={{ color: "var(--text-secondary)", display: 'inline-flex', alignItems: 'center', cursor: isParsing ? 'default' : 'pointer' }} onClick={isParsing ? undefined : () => onPreview(doc)}>
        <FileText size={16} strokeWidth={1.5} />
      </span>
      <div style={{ flex: 1, minWidth: 0, cursor: isParsing ? 'default' : 'pointer' }} onClick={isParsing ? undefined : () => onPreview(doc)}>
        <div style={{ fontSize: 13, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: 'var(--text-primary)' }}>
          {doc.filename}
        </div>
        {/* 缺陷摘要：缺陷号 · 状态 · 优先级 · 模块 · 处理人 · 评论数 */}
        {defect && (
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 5,
              marginTop: 2,
              fontSize: 11,
              color: 'var(--text-secondary, #64748b)',
              minWidth: 0,
            }}
          >
            <span
              title={defect.status}
              style={{
                width: 6,
                height: 6,
                borderRadius: 2,
                background: defectStatusColor(defect.status),
                flexShrink: 0,
              }}
            />
            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {[
                `#${defect.defect_id}`,
                defect.status,
                defect.priority,
                defect.module,
                defect.owner,
                t('kb.defectComments', '评论{{n}}', { n: defect.comment_count }),
              ]
                .filter(Boolean)
                .join(' · ')}
            </span>
          </div>
        )}
        <div style={{ fontSize: 11, color: "var(--text-muted)", display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
          {/* 仅在「全部文档」视图下展示所属目录面包屑或未归属标识 */}
          {showFolderScope && !defect && (
            folderPath && folderPath.length > 0 && onSelectFolder ? (
              <span
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 2,
                  background: 'var(--bg-active, rgba(59, 130, 246, 0.08))',
                  color: 'var(--primary, #3b82f6)',
                  padding: '1px 6px',
                  borderRadius: 4,
                  fontSize: 11,
                  border: '1px solid rgba(59, 130, 246, 0.18)',
                }}
              >
                <span style={{ marginRight: 2 }}>📁</span>
                {folderPath.map((item, idx) => (
                  <span
                    key={item.id}
                    style={{ display: 'inline-flex', alignItems: 'center' }}
                  >
                    <span
                      onClick={(e) => {
                        e.stopPropagation();
                        onSelectFolder(item.id);
                      }}
                      title={t('kb.jumpToFolder', '点击跳转到此目录')}
                      style={{
                        cursor: 'pointer',
                        fontWeight: idx === folderPath.length - 1 ? 600 : 400,
                        textDecoration: 'underline',
                        textDecorationColor: 'transparent',
                        transition: 'text-decoration-color 0.15s ease',
                      }}
                      onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.textDecorationColor = 'currentColor'; }}
                      onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.textDecorationColor = 'transparent'; }}
                    >
                      {item.name}
                    </span>
                    {idx < folderPath.length - 1 && (
                      <span style={{ margin: '0 3px', opacity: 0.5 }}>/</span>
                    )}
                  </span>
                ))}
              </span>
            ) : (
              <span
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 3,
                  background: 'var(--bg-elevated, rgba(148, 163, 184, 0.12))',
                  color: 'var(--text-muted, #64748b)',
                  padding: '1px 6px',
                  borderRadius: 4,
                  fontSize: 11,
                  border: '1px solid var(--border-color, rgba(148, 163, 184, 0.2))',
                }}
                title={t('kb.unassignedFolder', '未归属')}
              >
                📁 {t('kb.unassignedFolder', '未归属')}
              </span>
            )
          )}
          {/* 来源标识（本地 / 飞书 / TAPD） */}
          {doc.source_type === 'feishu' ? (
            <span
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 2,
                background: 'rgba(59, 130, 246, 0.1)',
                color: '#2563eb',
                padding: '1px 5px',
                borderRadius: 4,
                fontSize: 10,
                fontWeight: 600,
                border: '1px solid rgba(59, 130, 246, 0.25)',
              }}
              title="飞书知识库同步文档"
            >
              飞书
            </span>
          ) : defect || doc.source_type === 'tapd' ? (
            <span
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 2,
                background: 'rgba(124, 58, 237, 0.1)',
                color: '#7c3aed',
                padding: '1px 5px',
                borderRadius: 4,
                fontSize: 10,
                fontWeight: 600,
                border: '1px solid rgba(124, 58, 237, 0.25)',
              }}
              title={t('kb.tapdSourceHint', '从 TAPD 同步的缺陷')}
            >
              {t('kb.sourceTapd', 'TAPD')}
            </span>
          ) : (
            <span
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 2,
                background: 'rgba(107, 114, 128, 0.1)',
                color: 'var(--text-secondary, #6b7280)',
                padding: '1px 5px',
                borderRadius: 4,
                fontSize: 10,
                border: '1px solid rgba(107, 114, 128, 0.2)',
              }}
              title="本地上传文档"
            >
              本地
            </span>
          )}
          {(doc.status === 'ready' || doc.status === 'not_vectorized') && <span>{t('kb.chunkCharCount', { chunks: doc.chunk_count, chars: doc.char_count })}</span>}
          {typeLabel && <span style={{ background: 'var(--bg-card)', padding: '0 5px', borderRadius: 3 }}>{typeLabel}</span>}
          {doc.tags?.length > 0 && (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 3 }}>
              <TagIcon size={10} /> {doc.tags.join(', ')}
            </span>
          )}
          {doc.error_message ? ` · ${doc.error_message}` : ''}
          {/* 缺陷行的结构化摘要已含状态/优先级/处理人，不再重复展示 description */}
          {!defect && doc.description ? ` · ${doc.description}` : ''}
        </div>
      </div>
      <span
        style={{
          color: st.color,
          fontSize: 12,
          flexShrink: 0,
          display: 'inline-flex',
          alignItems: 'center',
          gap: 4,
          fontWeight: (doc.status === 'ready' || doc.status === 'not_vectorized') ? 500 : 400,
        }}
      >
        {!isParsing && doc.status === 'ready' && <CheckCircle2 size={13} style={{ color: 'var(--success, #10b981)' }} />}
        {!isParsing && doc.status === 'not_vectorized' && <CircleDashed size={13} />}
        {!isParsing && doc.status === 'embed_partial' && <AlertCircle size={13} />}
        {!isParsing && doc.status === 'embed_failed' && <XCircle size={13} />}
        {isParsing && <RefreshCw size={13} className="animate-spin" />}
        {st.text}
      </span>

      {/* 操作按钮 */}
      <div style={{ display: 'flex', gap: 4, flexShrink: 0 }}>
        <button onClick={() => onPreview(doc)} title={t('kb.preview')} disabled={isParsing} style={actionStyle}>
          <Eye size={14} />
        </button>
        {onPreviewChunks && (doc.status === 'ready' || doc.status === 'not_vectorized' || doc.status === 'embed_failed' || doc.status === 'embed_partial') && (
          <button onClick={() => onPreviewChunks(doc)} title={t('kb.previewChunks', '预览分块')} disabled={isParsing} style={actionStyle}>
            <Scissors size={14} />
          </button>
        )}
        <a
          href={`/api/modules/kb/documents/${doc.id}/raw`}
          download
          title={t('kb.download')}
          aria-disabled={isParsing}
          tabIndex={isParsing ? -1 : 0}
          style={{
            ...iconBtnStyle,
            opacity: isParsing ? 0.45 : 1,
            pointerEvents: isParsing ? 'none' : 'auto',
            textDecoration: 'none',
            display: 'inline-flex',
          }}
        >
          <Download size={14} />
        </a>
        <button onClick={() => onEditMeta(doc)} title={t('kb.metaInfo')} disabled={isParsing} style={actionStyle}>
          <TagIcon size={14} />
        </button>
        <button onClick={() => onShowVersions(doc)} title={t('kb.versionHistory')} disabled={isParsing} style={actionStyle}>
          <History size={14} />
        </button>
        {onMove && (
          <button onClick={() => onMove(doc)} title={t('kb.moveToFolder', '移动到目录')} disabled={isParsing} style={actionStyle}>
            <FolderInput size={14} />
          </button>
        )}
        {onReindex && (doc.status === 'ready' || doc.status === 'parse_failed' || doc.status === 'not_vectorized' || doc.status === 'embed_failed' || doc.status === 'embed_partial') && (
          <button
            onClick={() => confirm({
              title: t('kb.confirmReindexTitle', '重新向量化'),
              message: vectorEnabled
                ? t('kb.confirmReindexMsg', '将重新解析并向量化文档「{{name}}」，需要调用 embedding API，确定？', { name: doc.filename })
                : t('kb.confirmReindexMsgRagOff', '当前 RAG 未开启，将重新解析文档「{{name}}」并重置分块（不执行向量化），确定？', { name: doc.filename }),
              onConfirm: () => onReindex(doc.id),
            })}
            title={t('kb.reindexHint', '重新解析（复用 reindex 接口）')}
            disabled={isParsing}
            style={actionStyle}
          >
            <RefreshCw size={14} />
          </button>
        )}
        <button
          onClick={() => confirm({
            title: t('kb.confirmDeleteTitle'),
            message: t('kb.confirmDeleteName', { name: doc.filename }),
            variant: 'danger',
            onConfirm: () => onDelete(doc.id),
          })}
          disabled={isParsing}
          style={{
            background: 'none',
            border: '1px solid var(--border-strong)',
            color: "var(--text-secondary)",
            padding: '2px 8px',
            borderRadius: 4,
            cursor: isParsing ? 'not-allowed' : 'pointer',
            opacity: isParsing ? 0.45 : 1,
            fontSize: 12,
          }}
        >{t('kb.delete')}</button>
      </div>
    </div>
  );
}

const iconBtnStyle: React.CSSProperties = {
  background: 'none',
  border: '1px solid var(--bg-elevated)',
  color: 'var(--text-secondary)',
  padding: 3,
  borderRadius: 4,
  cursor: 'pointer',
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
};
