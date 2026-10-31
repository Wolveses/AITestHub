import { useMemo, useState } from 'react';
import { ChevronDown, ChevronRight, Folder, FolderOpen } from 'lucide-react';

interface Node {
  name: string;
  path: string;
  count: number;
  children: Node[];
}

interface CountedItem {
  category_path: string;
  /** 该路径自身条目数；缺省按 1 条（逐条传入条目时） */
  count?: number;
}

/** 目录树直接由条目的 category_path（"A / B / C"）聚合，避免依赖知识库目录接口。 */
function buildTree(items: ReadonlyArray<CountedItem>): Node[] {
  const root: Node = { name: '', path: '', count: 0, children: [] };
  const ensure = (parent: Node, name: string, path: string): Node => {
    let node = parent.children.find((n) => n.name === name);
    if (!node) {
      node = { name, path, count: 0, children: [] };
      parent.children.push(node);
    }
    return node;
  };
  for (const c of items) {
    const raw = (c.category_path || '').trim();
    if (!raw) continue; // 无目录的条目只在「全部」里展示
    const weight = c.count ?? 1;
    const parts = raw.split(/\s*\/\s*/).filter(Boolean);
    let parent = root;
    let path = '';
    for (const part of parts) {
      path = path ? `${path} / ${part}` : part;
      parent = ensure(parent, part, path);
      parent.count += weight;
    }
  }
  const sort = (nodes: Node[]) => {
    nodes.sort((a, b) => a.name.localeCompare(b.name));
    nodes.forEach((n) => sort(n.children));
  };
  sort(root.children);
  return root.children;
}

function TreeRow({
  node,
  depth,
  active,
  onSelect,
}: {
  node: Node;
  depth: number;
  active: string | null;
  onSelect: (path: string | null) => void;
}) {
  const [open, setOpen] = useState(depth < 1);
  const hasChildren = node.children.length > 0;
  const selected = active === node.path;
  return (
    <>
      <div
        onClick={() => onSelect(selected ? null : node.path)}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 4,
          padding: `5px 8px 5px ${8 + depth * 14}px`,
          borderRadius: 5,
          cursor: 'pointer',
          fontSize: 12,
          color: selected ? 'var(--accent)' : 'var(--text-primary)',
          background: selected ? 'var(--surface-hover)' : 'transparent',
        }}
      >
        <span
          onClick={(e) => {
            e.stopPropagation();
            if (hasChildren) setOpen((v) => !v);
          }}
          style={{ display: 'inline-flex', width: 14, color: 'var(--text-muted)' }}
        >
          {hasChildren ? open ? <ChevronDown size={13} /> : <ChevronRight size={13} /> : null}
        </span>
        {hasChildren && open ? (
          <FolderOpen size={13} style={{ color: 'var(--warning, #f59e0b)' }} />
        ) : (
          <Folder size={13} style={{ color: 'var(--text-muted)' }} />
        )}
        <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {node.name}
        </span>
        <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>{node.count}</span>
      </div>
      {open &&
        node.children.map((child) => (
          <TreeRow
            key={child.path || child.name}
            node={child}
            depth={depth + 1}
            active={active}
            onSelect={onSelect}
          />
        ))}
    </>
  );
}

export function CategoryTree({
  items,
  active,
  onSelect,
  allLabel,
  allCount,
}: {
  items: CountedItem[];
  active: string | null;
  onSelect: (path: string | null) => void;
  allLabel: string;
  /** 「全部」计数；缺省用条目数（树内无目录条目不计入） */
  allCount?: number;
}) {
  const tree = useMemo(() => buildTree(items), [items]);
  const total = allCount ?? items.reduce((sum, i) => sum + (i.count ?? 1), 0);
  return (
    <div style={{ width: 230, flexShrink: 0, borderRight: '1px solid var(--border)', overflowY: 'auto', padding: '8px 6px' }}>
      <div
        onClick={() => onSelect(null)}
        style={{
          padding: '6px 8px',
          borderRadius: 5,
          cursor: 'pointer',
          fontSize: 12,
          fontWeight: 500,
          color: active === null ? 'var(--accent)' : 'var(--text-primary)',
          background: active === null ? 'var(--surface-hover)' : 'transparent',
          marginBottom: 4,
        }}
      >
        {allLabel}（{total}）
      </div>
      {tree.map((n) => (
        <TreeRow key={n.path || n.name} node={n} depth={0} active={active} onSelect={onSelect} />
      ))}
    </div>
  );
}
