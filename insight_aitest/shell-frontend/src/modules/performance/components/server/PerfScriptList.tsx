import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { Sparkles, Download, Trash2, Eye, RefreshCw, FileCode } from 'lucide-react';
import { useProjectStore } from '../../../../shared/store/projectStore';
import { useServerPerfStore, type PerfScriptItem } from '../../store/serverPerfStore';
import { PerfAIGenerateModal } from './PerfAIGenerateModal';

export function PerfScriptList() {
  const currentProjectId = useProjectStore((s) => s.currentProjectId);
  const { scripts, loading, loadScripts } = useServerPerfStore();
  const [generateModalOpen, setGenerateModalOpen] = useState(false);
  const [previewScript, setPreviewScript] = useState<PerfScriptItem | null>(null);

  useEffect(() => {
    if (currentProjectId !== null) {
      loadScripts(currentProjectId);
    }
  }, [currentProjectId, loadScripts]);

  const handleDelete = async (script: PerfScriptItem) => {
    if (!confirm(`确定要删除脚本「${script.name}」吗？`)) return;
    try {
      const res = await fetch(`/api/modules/performance/server/scripts/${script.id}`, {
        method: 'DELETE',
      });
      if (!res.ok) throw new Error('删除失败');
      toast.success('脚本已删除');
      if (currentProjectId !== null) loadScripts(currentProjectId);
    } catch (err: any) {
      toast.error(err.message || '删除失败');
    }
  };

  const handleDownload = (script: PerfScriptItem) => {
    window.open(`/api/modules/performance/server/scripts/${script.id}/download`, '_blank');
  };

  if (currentProjectId === null) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>
        请先在顶部选择项目
      </div>
    );
  }

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
      {/* 工具栏 */}
      <div
        style={{
          padding: '10px 16px',
          borderBottom: '1px solid var(--border)',
          background: 'var(--bg-card)',
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          flexShrink: 0,
        }}
      >
        <button
          onClick={() => setGenerateModalOpen(true)}
          style={{
            padding: '6px 14px',
            borderRadius: 6,
            border: 'none',
            background: 'var(--accent)',
            color: '#fff',
            fontSize: 13,
            fontWeight: 600,
            cursor: 'pointer',
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
          }}
        >
          <Sparkles size={14} /> 根据性能方案智能编写 JMeter 脚本
        </button>

        <div style={{ flex: 1 }} />

        <button
          onClick={() => loadScripts(currentProjectId)}
          style={{
            padding: '6px 12px',
            borderRadius: 6,
            border: '1px solid var(--border)',
            background: 'var(--bg-base)',
            color: 'var(--text-primary)',
            fontSize: 12,
            cursor: 'pointer',
            display: 'inline-flex',
            alignItems: 'center',
            gap: 4,
          }}
        >
          <RefreshCw size={13} style={{ animation: loading ? 'spin 1s linear infinite' : 'none' }} />
          刷新列表
        </button>
      </div>

      {/* 脚本列表 */}
      <div style={{ flex: 1, overflowY: 'auto', padding: 16 }}>
        {scripts.length === 0 ? (
          <div
            style={{
              padding: 60,
              textAlign: 'center',
              color: 'var(--text-muted)',
              fontSize: 13,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: 12,
            }}
          >
            <FileCode size={36} strokeWidth={1.2} style={{ opacity: 0.5 }} />
            <div>当前项目暂无性能脚本，点击上方按钮通过 AI 方案智能生成脚本</div>
          </div>
        ) : (
          <div
            style={{
              border: '1px solid var(--border)',
              borderRadius: 8,
              background: 'var(--bg-card)',
              overflow: 'hidden',
            }}
          >
            <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: 13 }}>
              <thead>
                <tr
                  style={{
                    background: 'var(--bg-base)',
                    borderBottom: '1px solid var(--border)',
                    color: 'var(--text-muted)',
                    fontSize: 12,
                  }}
                >
                  <th style={{ padding: '10px 16px' }}>脚本名称</th>
                  <th style={{ padding: '10px 14px', width: 220 }}>性能方案摘要</th>
                  <th style={{ padding: '10px 14px', width: 100 }}>包含接口</th>
                  <th style={{ padding: '10px 14px', width: 160 }}>创建时间</th>
                  <th style={{ padding: '10px 16px', width: 180, textAlign: 'right' }}>操作</th>
                </tr>
              </thead>
              <tbody>
                {scripts.map((script) => (
                  <tr
                    key={script.id}
                    style={{
                      borderBottom: '1px solid var(--border)',
                      transition: 'background 0.15s ease',
                    }}
                  >
                    <td style={{ padding: '12px 16px' }}>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                        <strong style={{ color: 'var(--text-primary)', fontSize: 13 }}>{script.name}</strong>
                        {script.description && (
                          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{script.description}</span>
                        )}
                      </div>
                    </td>
                    <td style={{ padding: '12px 14px', fontSize: 12, color: 'var(--text-secondary)' }}>
                      {script.plan_description || '-'}
                    </td>
                    <td style={{ padding: '12px 14px' }}>
                      <span
                        style={{
                          fontSize: 11,
                          padding: '2px 8px',
                          borderRadius: 12,
                          background: 'var(--bg-base)',
                          border: '1px solid var(--border)',
                          color: 'var(--text-primary)',
                        }}
                      >
                        {script.asset_ids?.length || 0} 个接口
                      </span>
                    </td>
                    <td style={{ padding: '12px 14px', fontSize: 11, color: 'var(--text-muted)' }}>
                      {new Date(script.created_at).toLocaleString()}
                    </td>
                    <td style={{ padding: '12px 16px', textAlign: 'right' }}>
                      <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                        <button
                          onClick={() => setPreviewScript(script)}
                          title="在线预览 JMX 内容"
                          style={{
                            background: 'transparent',
                            border: 'none',
                            color: 'var(--text-secondary)',
                            cursor: 'pointer',
                            padding: 5,
                            borderRadius: 4,
                          }}
                        >
                          <Eye size={15} />
                        </button>
                        <button
                          onClick={() => handleDownload(script)}
                          title="下载标准 .jmx 文件"
                          style={{
                            background: 'transparent',
                            border: 'none',
                            color: 'var(--accent)',
                            cursor: 'pointer',
                            padding: 5,
                            borderRadius: 4,
                          }}
                        >
                          <Download size={15} />
                        </button>
                        <button
                          onClick={() => handleDelete(script)}
                          title="删除脚本"
                          style={{
                            background: 'transparent',
                            border: 'none',
                            color: 'var(--text-muted)',
                            cursor: 'pointer',
                            padding: 5,
                            borderRadius: 4,
                          }}
                          onMouseEnter={(e) => (e.currentTarget.style.color = '#ef4444')}
                          onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--text-muted)')}
                        >
                          <Trash2 size={15} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* 智能生成 Modal */}
      <PerfAIGenerateModal
        open={generateModalOpen}
        onClose={() => setGenerateModalOpen(false)}
        projectId={currentProjectId}
        onSuccess={() => {
          if (currentProjectId !== null) loadScripts(currentProjectId);
        }}
      />

      {/* 预览抽屉/弹窗 */}
      {previewScript && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 110,
            background: 'rgba(0,0,0,0.6)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: 24,
          }}
        >
          <div
            style={{
              width: '80%',
              maxWidth: 800,
              maxHeight: '80vh',
              background: 'var(--bg-card)',
              borderRadius: 8,
              border: '1px solid var(--border)',
              display: 'flex',
              flexDirection: 'column',
              overflow: 'hidden',
            }}
          >
            <div
              style={{
                padding: '12px 16px',
                borderBottom: '1px solid var(--border)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                background: 'var(--bg-base)',
              }}
            >
              <strong style={{ fontSize: 14 }}>JMX 脚本预览 - {previewScript.name}</strong>
              <button
                onClick={() => setPreviewScript(null)}
                style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}
              >
                ✕
              </button>
            </div>
            <div style={{ flex: 1, overflowY: 'auto', padding: 16 }}>
              <pre
                style={{
                  background: 'var(--bg-base)',
                  padding: 12,
                  borderRadius: 6,
                  fontSize: 12,
                  fontFamily: 'monospace',
                  overflowX: 'auto',
                  color: 'var(--text-primary)',
                }}
              >
                {previewScript.config ? JSON.stringify(previewScript.config, null, 2) : '暂无详细编排配置'}
              </pre>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
