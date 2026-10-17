import React, { useState } from 'react';
import { Folder, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useKnowledgeStore, type Document, type FolderNode } from '../store/knowledgeStore';

interface MoveDocModalProps {
  doc: Document | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function MoveDocModal({ doc, open, onOpenChange }: MoveDocModalProps) {
  const { t } = useTranslation();
  const { folders, moveDocument } = useKnowledgeStore();
  const [selectedFolderId, setSelectedFolderId] = useState<number | null>(doc?.folder_id ?? null);
  const [saving, setSaving] = useState(false);

  if (!open || !doc) return null;

  const handleConfirm = async () => {
    setSaving(true);
    try {
      await moveDocument(doc.id, selectedFolderId);
      onOpenChange(false);
    } finally {
      setSaving(false);
    }
  };

  const renderOptions = (nodes: FolderNode[], level = 0): React.ReactNode[] => {
    return nodes.flatMap((node) => [
      <option key={node.id} value={node.id}>
        {'\u00A0'.repeat(level * 4)}📁 {node.name}
      </option>,
      ...(node.children ? renderOptions(node.children, level + 1) : []),
    ]);
  };

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 1000,
        backgroundColor: 'rgba(0,0,0,0.4)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 16,
      }}
    >
      <div
        style={{
          width: 400,
          maxWidth: '100%',
          backgroundColor: 'var(--bg-surface, #fff)',
          borderRadius: 8,
          boxShadow: '0 10px 25px rgba(0,0,0,0.15)',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          border: '1px solid var(--border-color, #e5e7eb)',
        }}
      >
        {/* 头部 */}
        <div
          style={{
            padding: '12px 16px',
            borderBottom: '1px solid var(--border-color, #f0f0f0)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <span style={{ fontSize: 14, fontWeight: 600, display: 'flex', alignItems: 'center', gap: 6 }}>
            <Folder size={16} /> {t('kb.moveDocTitle', '移动文档')}
          </span>
          <button
            onClick={() => onOpenChange(false)}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted, #888)' }}
          >
            <X size={16} />
          </button>
        </div>

        {/* 内容 */}
        <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div style={{ fontSize: 13, color: 'var(--text-secondary, #666)' }}>
            {t('kb.movingDoc', '正在移动文档')}: <strong style={{ color: 'var(--text-primary, #111)' }}>{doc.filename}</strong>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <label style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-secondary, #666)' }}>
              {t('kb.targetFolder', '目标目录')}
            </label>
            <select
              value={selectedFolderId === null ? '' : selectedFolderId}
              onChange={(e) => {
                const val = e.target.value;
                setSelectedFolderId(val === '' ? null : Number(val));
              }}
              style={{
                padding: '8px 10px',
                borderRadius: 6,
                border: '1px solid var(--border-color, #d1d5db)',
                fontSize: 13,
                outline: 'none',
                backgroundColor: 'var(--bg-primary, #fff)',
                color: 'inherit',
              }}
            >
              <option value="">📁 {t('kb.allDocuments', '全部文档')}</option>
              {renderOptions(folders)}
            </select>
          </div>
        </div>

        {/* 底部按钮 */}
        <div
          style={{
            padding: '10px 16px',
            borderTop: '1px solid var(--border-color, #f0f0f0)',
            display: 'flex',
            justifyContent: 'flex-end',
            gap: 8,
            backgroundColor: 'var(--bg-secondary, #fafafa)',
          }}
        >
          <button
            onClick={() => onOpenChange(false)}
            style={{
              padding: '6px 14px',
              borderRadius: 6,
              border: '1px solid var(--border-color, #d1d5db)',
              background: 'transparent',
              cursor: 'pointer',
              fontSize: 13,
            }}
          >
            {t('common.cancel', '取消')}
          </button>
          <button
            onClick={handleConfirm}
            disabled={saving}
            style={{
              padding: '6px 14px',
              borderRadius: 6,
              border: 'none',
              background: 'var(--primary, #3b82f6)',
              color: '#fff',
              cursor: saving ? 'not-allowed' : 'pointer',
              fontSize: 13,
              fontWeight: 500,
            }}
          >
            {saving ? t('common.saving', '保存中…') : t('common.confirm', '确认')}
          </button>
        </div>
      </div>
    </div>
  );
}

