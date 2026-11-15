import { useMemo, useState } from 'react';
import { ChevronDown, ChevronRight, Folder, FolderOpen } from 'lucide-react';
import type { MobileCase } from '../store/mobileStore';

interface TreeNode {
  name: string;
  fullPath: string;
  count: number;
  children: Map<string, TreeNode>;
}

function buildTree(cases: MobileCase[]): TreeNode {
  const root: TreeNode = { name: '全部用例', fullPath: '', count: cases.length, children: new Map() };
  for (const c of cases) {
    const raw = (c.category_path || '').trim();
    if (!raw) continue;
    const parts = raw.split('/').map((s) => s.trim()).filter(Boolean);
    let cur = root;
    let acc = '';
    for (const part of parts) {
      acc = acc ? `${acc}/${part}` : part;
      let child = cur.children.get(part);
      if (!child) {
        child = { name: part, fullPath: acc, count: 0, children: new Map() };
        cur.children.set(part, child);
      }
      child.count += 1;
      cur = child;
    }
  }
  return root;
}

function NodeRow({
  node,
  depth,
  selected,
  onSelect,
}: {
  node: TreeNode;
  depth: number;
  selected: string;
  onSelect: (path: string) => void;
}) {
  const [expanded, setExpanded] = useState(true);
  const children = Array.from(node.children.values());
  const hasChildren = children.length > 0;
  const isSelected = selected === node.fullPath;

  return (
    <div>
      <div
        onClick={() => onSelect(node.fullPath)}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          padding: '6px 8px',
          paddingLeft: 8 + depth * 14,
          borderRadius: 6,
          cursor: 'pointer',
          fontSize: 12,
          color: isSelected ? 'var(--accent)' : 'var(--text-primary)',
          background: isSelected ? 'var(--surface-tint)' : 'transparent',
          fontWeight: isSelected ? 600 : 400,
        }}
      >
        {hasChildren ? (
          <span
            onClick={(e) => {
              e.stopPropagation();
              setExpanded((v) => !v);
            }}
            style={{ display: 'inline-flex', color: 'var(--text-muted)' }}
          >
            {expanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
          </span>
        ) : (
          <span style={{ width: 13 }} />
        )}
        {hasChildren && expanded ? (
          <FolderOpen size={13} style={{ color: 'var(--warning)', flexShrink: 0 }} />
        ) : (
          <Folder size={13} style={{ color: 'var(--warning)', flexShrink: 0 }} />
        )}
        <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {node.name}
        </span>
        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{node.count}</span>
      </div>
      {hasChildren && expanded && (
        <div>
          {children.map((ch) => (
            <NodeRow key={ch.fullPath} node={ch} depth={depth + 1} selected={selected} onSelect={onSelect} />
          ))}
        </div>
      )}
    </div>
  );
}

export function CategoryTree({
  cases,
  selected,
  onSelect,
}: {
  cases: MobileCase[];
  selected: string;
  onSelect: (path: string) => void;
}) {
  const tree = useMemo(() => buildTree(cases), [cases]);

  return (
    <div
      style={{
        width: 220,
        flexShrink: 0,
        background: 'var(--bg-card)',
        border: '1px solid var(--border)',
        borderRadius: 10,
        padding: 10,
        alignSelf: 'stretch',
        overflowY: 'auto',
      }}
    >
      <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', padding: '2px 8px 8px' }}>
        用例目录
      </div>
      <NodeRow node={tree} depth={0} selected={selected} onSelect={onSelect} />
    </div>
  );
}
