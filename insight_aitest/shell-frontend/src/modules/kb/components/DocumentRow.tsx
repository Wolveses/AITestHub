import { FileText, Eye, Download, Tag as TagIcon, History, FolderInput, CheckCircle2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { Document } from '../store/knowledgeStore';
import { useConfirmStore } from '../../../shared/store/confirmStore';

const STATUS_KEY: Record<string, string> = {
  pending: 'kb.statusWaiting',
  parsing: 'kb.statusParsing',
  chunking: 'kb.statusChunking',
  embedding: 'kb.statusEmbedding',
  ready: 'kb.statusReady',
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

interface DocumentRowProps {
  doc: Document;
  folderPath?: { id: number; name: string }[];
  showFolderScope?: boolean;
  onDelete: (id: number) => void;
  onPreview: (doc: Document) => void;
  onEditMeta: (doc: Document) => void;
  onShowVersions: (doc: Document) => void;
  onMove?: (doc: Document) => void;
  onSelectFolder?: (folderId: number | null) => void;
}

export function DocumentRow({
  doc,
  folderPath,
  showFolderScope = false,
  onDelete,
  onPreview,
  onEditMeta,
  onShowVersions,
  onMove,
  onSelectFolder,
}: DocumentRowProps) {
  const { t } = useTranslation();
  const statusKey = STATUS_KEY[doc.status];
  const statusColor = STATUS_COLOR[doc.status] ?? "var(--text-secondary)";
  const st = { text: statusKey ? t(statusKey) : doc.status, color: statusColor };
  const { confirm } = useConfirmStore();
  const typeLabel = doc.doc_type && DOC_TYPE_KEY[doc.doc_type] ? t(DOC_TYPE_KEY[doc.doc_type]) : '';

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 12, padding: '10px 12px',
      borderBottom: '1px solid var(--bg-card)',
    }}>
      <span style={{ color: "var(--text-secondary)", display: 'inline-flex', alignItems: 'center', cursor: 'pointer' }} onClick={() => onPreview(doc)}>
        <FileText size={16} strokeWidth={1.5} />
      </span>
      <div style={{ flex: 1, minWidth: 0, cursor: 'pointer' }} onClick={() => onPreview(doc)}>
        <div style={{ fontSize: 13, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: 'var(--text-primary)' }}>
          {doc.filename}
        </div>
        <div style={{ fontSize: 11, color: "var(--text-muted)", display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
          {/* 仅在「全部文档」视图下展示所属目录面包屑或未归属标识 */}
          {showFolderScope && (
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
          {doc.status === 'ready' && <span>{t('kb.chunkCharCount', { chunks: doc.chunk_count, chars: doc.char_count })}</span>}
          {typeLabel && <span style={{ background: 'var(--bg-card)', padding: '0 5px', borderRadius: 3 }}>{typeLabel}</span>}
          {doc.tags?.length > 0 && (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 3 }}>
              <TagIcon size={10} /> {doc.tags.join(', ')}
            </span>
          )}
          {doc.error_message ? ` · ${doc.error_message}` : ''}
          {doc.description ? ` · ${doc.description}` : ''}
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
          fontWeight: doc.status === 'ready' ? 500 : 400,
        }}
      >
        {doc.status === 'ready' && <CheckCircle2 size={13} style={{ color: 'var(--success, #10b981)' }} />}
        {st.text}
      </span>

      {/* 操作按钮 */}
      <div style={{ display: 'flex', gap: 4, flexShrink: 0 }}>
        <button onClick={() => onPreview(doc)} title={t('kb.preview')} style={iconBtnStyle}>
          <Eye size={14} />
        </button>
        <a href={`/api/modules/kb/documents/${doc.id}/raw`} download title={t('kb.download')} style={{ ...iconBtnStyle, textDecoration: 'none', display: 'inline-flex' }}>
          <Download size={14} />
        </a>
        <button onClick={() => onEditMeta(doc)} title={t('kb.metaInfo')} style={iconBtnStyle}>
          <TagIcon size={14} />
        </button>
        <button onClick={() => onShowVersions(doc)} title={t('kb.versionHistory')} style={iconBtnStyle}>
          <History size={14} />
        </button>
        {onMove && (
          <button onClick={() => onMove(doc)} title={t('kb.moveToFolder', '移动到目录')} style={iconBtnStyle}>
            <FolderInput size={14} />
          </button>
        )}
        <button
          onClick={() => confirm({
            title: t('kb.confirmDeleteTitle'),
            message: t('kb.confirmDeleteName', { name: doc.filename }),
            variant: 'danger',
            onConfirm: () => onDelete(doc.id),
          })}
          style={{ background: 'none', border: '1px solid var(--border-strong)', color: "var(--text-secondary)", padding: '2px 8px', borderRadius: 4, cursor: 'pointer', fontSize: 12 }}
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
