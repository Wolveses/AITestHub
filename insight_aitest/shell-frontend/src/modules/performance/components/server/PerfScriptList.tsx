import { useEffect, useState, useMemo } from 'react';
import { toast } from 'sonner';
import {
  Download,
  Trash2,
  RefreshCw,
  FileCode,
  Plus,
  Search,
  Copy,
  Check,
  Layers,
  Code2,
  Info,
  ChevronDown,
  ChevronUp,
  ChevronRight,
  Pencil,
  FolderTree,
} from 'lucide-react';
import { useProjectStore } from '../../../../shared/store/projectStore';
import { useConfirmStore } from '../../../../shared/store/confirmStore';
import { useServerPerfStore, type PerfScriptItem } from '../../store/serverPerfStore';
import { CreateScenarioModal } from './CreateScenarioModal';
import { EditScriptModal } from './EditScriptModal';

interface JmxTreeNode {
  tag: string;
  testclass: string;
  type_label: string;
  name: string;
  display: string;
  enabled: boolean;
  children: JmxTreeNode[];
}

interface FullScriptDetail extends PerfScriptItem {
  jmx_content?: string;
  parsed_steps?: any[];
  component_tree?: JmxTreeNode[];
}

export function PerfScriptList() {
  const currentProjectId = useProjectStore((s) => s.currentProjectId);
  const { scripts, loading, loadScripts } = useServerPerfStore();
  const confirm = useConfirmStore((s) => s.confirm);

  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [editModalOpen, setEditModalOpen] = useState(false);

  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [activeTab, setActiveTab] = useState<'samplers' | 'tree' | 'jmx' | 'plan'>('tree');

  const [fullScript, setFullScript] = useState<FullScriptDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [copied, setCopied] = useState(false);

  // 加载脚本列表
  useEffect(() => {
    if (currentProjectId !== null) {
      loadScripts(currentProjectId);
    }
  }, [currentProjectId, loadScripts]);

  // 当 scripts 列表更新且未选中任何项时，默认选中第一项
  useEffect(() => {
    if (scripts.length > 0) {
      if (selectedId === null || !scripts.some((s) => s.id === selectedId)) {
        setSelectedId(scripts[0].id);
      }
    } else {
      setSelectedId(null);
      setFullScript(null);
    }
  }, [scripts, selectedId]);

  // 当选中的 selectedId 改变时，请求单个脚本详情获取完整 jmx_content
  useEffect(() => {
    if (!selectedId) {
      setFullScript(null);
      return;
    }

    let isMounted = true;
    setLoadingDetail(true);

    fetch(`/api/modules/performance/server/scripts/${selectedId}`)
      .then((res) => {
        if (!res.ok) throw new Error('获取脚本详情失败');
        return res.json();
      })
      .then((data) => {
        if (isMounted) {
          setFullScript(data);
          setLoadingDetail(false);
        }
      })
      .catch((err) => {
        if (isMounted) {
          toast.error(err.message || '加载详情失败');
          setLoadingDetail(false);
        }
      });

    return () => {
      isMounted = false;
    };
  }, [selectedId]);

  // 搜索过滤后的脚本列表
  const filteredScripts = useMemo(() => {
    if (!searchTerm.trim()) return scripts;
    const term = searchTerm.toLowerCase();
    return scripts.filter(
      (s) =>
        s.name.toLowerCase().includes(term) ||
        (s.description && s.description.toLowerCase().includes(term)) ||
        (s.plan_description && s.plan_description.toLowerCase().includes(term))
    );
  }, [scripts, searchTerm]);

  // 复制 JMX
  const handleCopyJmx = () => {
    if (!fullScript?.jmx_content) return;
    navigator.clipboard.writeText(fullScript.jmx_content);
    setCopied(true);
    toast.success('JMX 脚本内容已复制到剪贴板');
    setTimeout(() => setCopied(false), 2000);
  };

  // 下载 JMX 文件
  const handleDownload = (scriptId: number) => {
    window.open(`/api/modules/performance/server/scripts/${scriptId}/download`, '_blank');
  };

  // 删除脚本
  const handleDelete = (script: PerfScriptItem) => {
    confirm({
      title: '确认删除测试场景',
      message: `确定要删除测试场景「${script.name}」吗？删除后相关配置与 JMX 脚本将被永久移除。`,
      confirmText: '确认删除',
      variant: 'danger',
      onConfirm: async () => {
        try {
          const res = await fetch(`/api/modules/performance/server/scripts/${script.id}`, {
            method: 'DELETE',
          });
          if (!res.ok) throw new Error('删除失败');
          toast.success('测试场景已删除');
          if (currentProjectId !== null) {
            await loadScripts(currentProjectId);
          }
        } catch (err: any) {
          toast.error(err.message || '删除失败');
        }
      },
    });
  };

  if (currentProjectId === null) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>
        请先在顶部选择项目
      </div>
    );
  }

  // 提取 Sampler 列表（优先后端自动解析的 parsed_steps，兼容 config.steps 与 config.samplers）
  const samplers = useMemo(() => {
    if (!fullScript) return [];
    if (Array.isArray(fullScript.parsed_steps) && fullScript.parsed_steps.length > 0) {
      return fullScript.parsed_steps;
    }
    if (Array.isArray(fullScript.config?.steps) && fullScript.config.steps.length > 0) {
      return fullScript.config.steps;
    }
    if (Array.isArray(fullScript.config?.samplers) && fullScript.config.samplers.length > 0) {
      return fullScript.config.samplers;
    }
    return [];
  }, [fullScript]);

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
      {/* 顶部主工具栏 */}
      <div
        style={{
          padding: '10px 16px',
          borderBottom: '1px solid var(--border)',
          background: 'var(--bg-card)',
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          flexShrink: 0,
        }}
      >
        <button
          onClick={() => setCreateModalOpen(true)}
          style={{
            padding: '7px 14px',
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
          <Plus size={15} /> 新增测试场景
        </button>

        <span style={{ color: 'var(--text-muted)', fontSize: 13 }}>
          已收录场景: <strong>{scripts.length}</strong>
        </span>

        <div style={{ flex: 1 }} />

        <button
          onClick={() => currentProjectId !== null && loadScripts(currentProjectId)}
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
            gap: 5,
          }}
        >
          <RefreshCw size={13} style={{ animation: loading ? 'spin 1s linear infinite' : 'none' }} />
          刷新
        </button>
      </div>

      {/* 左右分栏核心区域 */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        {/* 左侧：测试场景列表 */}
        <div
          style={{
            width: 320,
            borderRight: '1px solid var(--border)',
            background: 'var(--bg-card)',
            display: 'flex',
            flexDirection: 'column',
            flexShrink: 0,
          }}
        >
          {/* 搜索框 */}
          <div style={{ padding: '10px 12px', borderBottom: '1px solid var(--border)' }}>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                background: 'var(--bg-base)',
                border: '1px solid var(--border)',
                borderRadius: 6,
                padding: '4px 8px',
              }}
            >
              <Search size={14} color="var(--text-muted)" />
              <input
                type="text"
                placeholder="搜索场景名称或方案..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                style={{
                  border: 'none',
                  background: 'transparent',
                  color: 'var(--text-primary)',
                  fontSize: 12,
                  outline: 'none',
                  width: '100%',
                }}
              />
              {searchTerm && (
                <button
                  onClick={() => setSearchTerm('')}
                  style={{
                    border: 'none',
                    background: 'transparent',
                    color: 'var(--text-muted)',
                    cursor: 'pointer',
                    fontSize: 12,
                    padding: 0,
                  }}
                >
                  ✕
                </button>
              )}
            </div>
          </div>

          {/* 列表项 */}
          <div style={{ flex: 1, overflowY: 'auto', padding: '6px 8px' }}>
            {filteredScripts.length === 0 ? (
              <div
                style={{
                  padding: 40,
                  textAlign: 'center',
                  color: 'var(--text-muted)',
                  fontSize: 12,
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  gap: 8,
                }}
              >
                <FileCode size={30} opacity={0.4} />
                <span>{scripts.length === 0 ? '暂无场景，点击上方新增' : '未匹配到相关测试场景'}</span>
              </div>
            ) : (
              filteredScripts.map((item) => {
                const isSelected = item.id === selectedId;
                return (
                  <div
                    key={item.id}
                    onClick={() => setSelectedId(item.id)}
                    style={{
                      padding: '10px 12px',
                      borderRadius: 6,
                      marginBottom: 4,
                      cursor: 'pointer',
                      border: `1px solid ${isSelected ? 'var(--accent)' : 'transparent'}`,
                      background: isSelected ? 'var(--accent-subtle, rgba(59, 130, 246, 0.08))' : 'transparent',
                      transition: 'all 0.15s ease',
                      position: 'relative',
                    }}
                    onMouseEnter={(e) => {
                      if (!isSelected) e.currentTarget.style.background = 'var(--bg-base)';
                    }}
                    onMouseLeave={(e) => {
                      if (!isSelected) e.currentTarget.style.background = 'transparent';
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 6 }}>
                      <strong
                        style={{
                          fontSize: 13,
                          color: isSelected ? 'var(--accent)' : 'var(--text-primary)',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {item.name}
                      </strong>
                      <span
                        style={{
                          fontSize: 11,
                          padding: '1px 6px',
                          borderRadius: 10,
                          background: 'var(--bg-base)',
                          border: '1px solid var(--border)',
                          color: 'var(--text-muted)',
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {(item.asset_ids && item.asset_ids.length > 0)
                          ? item.asset_ids.length
                          : (Array.isArray(item.config?.steps) ? item.config.steps.length : (Array.isArray(item.config?.samplers) ? item.config.samplers.length : 0))} 接口
                      </span>
                    </div>

                    {item.description ? (
                      <div
                        style={{
                          fontSize: 11,
                          color: 'var(--text-muted)',
                          marginTop: 4,
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {item.description}
                      </div>
                    ) : item.plan_description ? (
                      <div
                        style={{
                          fontSize: 11,
                          color: 'var(--text-muted)',
                          marginTop: 4,
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {item.plan_description}
                      </div>
                    ) : null}

                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        marginTop: 6,
                        fontSize: 10,
                        color: 'var(--text-muted)',
                      }}
                    >
                      <span>{new Date(item.updated_at || item.created_at).toLocaleDateString()}</span>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* 右侧：场景详情与 JMX 预览 */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', background: 'var(--bg-base)', overflow: 'hidden' }}>
          {selectedId === null || !fullScript ? (
            <div
              style={{
                flex: 1,
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                color: 'var(--text-muted)',
                gap: 12,
              }}
            >
              <FileCode size={48} strokeWidth={1.2} style={{ opacity: 0.3 }} />
              <div style={{ fontSize: 14 }}>请从左侧列表选择一个测试场景查看详情与 JMX 脚本</div>
            </div>
          ) : (
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
              {/* 详情头部 */}
              <div
                style={{
                  padding: '14px 20px',
                  borderBottom: '1px solid var(--border)',
                  background: 'var(--bg-card)',
                  display: 'flex',
                  alignItems: 'flex-start',
                  justifyContent: 'space-between',
                  gap: 16,
                  flexShrink: 0,
                }}
              >
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <h2 style={{ margin: 0, fontSize: 16, fontWeight: 600, color: 'var(--text-primary)' }}>
                      {fullScript.name}
                    </h2>
                    <span
                      style={{
                        fontSize: 11,
                        padding: '2px 8px',
                        borderRadius: 12,
                        background: 'rgba(59, 130, 246, 0.1)',
                        color: 'var(--accent)',
                        border: '1px solid rgba(59, 130, 246, 0.2)',
                      }}
                    >
                      JMeter 5.x 规范
                    </span>
                  </div>

                  {fullScript.description && (
                    <p style={{ margin: '6px 0 0', fontSize: 12, color: 'var(--text-secondary)' }}>
                      {fullScript.description}
                    </p>
                  )}

                  <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginTop: 8, fontSize: 11, color: 'var(--text-muted)' }}>
                    <span>包含接口: <strong style={{ color: 'var(--text-primary)' }}>{fullScript.asset_ids?.length || 0} 个</strong></span>
                    <span>创建时间: {new Date(fullScript.created_at).toLocaleString()}</span>
                    <span>更新时间: {new Date(fullScript.updated_at).toLocaleString()}</span>
                  </div>
                </div>

                {/* 动作按钮组 */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
                  <button
                    onClick={() => setEditModalOpen(true)}
                    title="编辑脚本名称、描述与 JMX 源码"
                    style={{
                      padding: '6px 12px',
                      borderRadius: 6,
                      border: '1px solid var(--border)',
                      background: 'var(--bg-base)',
                      color: 'var(--text-primary)',
                      fontSize: 12,
                      fontWeight: 500,
                      cursor: 'pointer',
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: 5,
                    }}
                  >
                    <Pencil size={13} />
                    编辑
                  </button>

                  <button
                    onClick={() => handleDelete(fullScript)}
                    style={{
                      padding: '6px 12px',
                      borderRadius: 6,
                      border: '1px solid var(--border)',
                      background: 'var(--bg-base)',
                      color: '#ef4444',
                      fontSize: 12,
                      cursor: 'pointer',
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: 5,
                    }}
                  >
                    <Trash2 size={13} />
                    删除
                  </button>
                </div>
              </div>

              {/* 详情 Tab 切换栏 */}
              <div
                style={{
                  padding: '0 20px',
                  background: 'var(--bg-card)',
                  borderBottom: '1px solid var(--border)',
                  display: 'flex',
                  gap: 20,
                  flexShrink: 0,
                }}
              >
                <button
                  onClick={() => setActiveTab('tree')}
                  style={{
                    padding: '10px 4px',
                    border: 'none',
                    background: 'transparent',
                    borderBottom: activeTab === 'tree' ? '2px solid var(--accent)' : '2px solid transparent',
                    color: activeTab === 'tree' ? 'var(--accent)' : 'var(--text-secondary)',
                    fontWeight: activeTab === 'tree' ? 600 : 400,
                    fontSize: 13,
                    cursor: 'pointer',
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 6,
                  }}
                >
                  <FolderTree size={14} /> 脚本树状结构
                </button>

                <button
                  onClick={() => setActiveTab('samplers')}
                  style={{
                    padding: '10px 4px',
                    border: 'none',
                    background: 'transparent',
                    borderBottom: activeTab === 'samplers' ? '2px solid var(--accent)' : '2px solid transparent',
                    color: activeTab === 'samplers' ? 'var(--accent)' : 'var(--text-secondary)',
                    fontWeight: activeTab === 'samplers' ? 600 : 400,
                    fontSize: 13,
                    cursor: 'pointer',
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 6,
                  }}
                >
                  <Layers size={14} /> 接口链路步骤 ({samplers.length})
                </button>

                <button
                  onClick={() => setActiveTab('jmx')}
                  style={{
                    padding: '10px 4px',
                    border: 'none',
                    background: 'transparent',
                    borderBottom: activeTab === 'jmx' ? '2px solid var(--accent)' : '2px solid transparent',
                    color: activeTab === 'jmx' ? 'var(--accent)' : 'var(--text-secondary)',
                    fontWeight: activeTab === 'jmx' ? 600 : 400,
                    fontSize: 13,
                    cursor: 'pointer',
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 6,
                  }}
                >
                  <Code2 size={14} /> JMX 脚本预览
                </button>

                <button
                  onClick={() => setActiveTab('plan')}
                  style={{
                    padding: '10px 4px',
                    border: 'none',
                    background: 'transparent',
                    borderBottom: activeTab === 'plan' ? '2px solid var(--accent)' : '2px solid transparent',
                    color: activeTab === 'plan' ? 'var(--accent)' : 'var(--text-secondary)',
                    fontWeight: activeTab === 'plan' ? 600 : 400,
                    fontSize: 13,
                    cursor: 'pointer',
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 6,
                  }}
                >
                  <Info size={14} /> 测试方案与配置
                </button>
              </div>

              {/* 详情内容区域 */}
              <div style={{ flex: 1, overflowY: 'auto', padding: 20 }}>
                {loadingDetail ? (
                  <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
                    <RefreshCw size={18} style={{ animation: 'spin 1s linear infinite', marginBottom: 8 }} />
                    <div>正在加载脚本详情...</div>
                  </div>
                ) : activeTab === 'tree' ? (
                  /* 脚本树状结构预览：顶级为测试计划，按层级展示所有组件 */
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                    <div
                      style={{
                        padding: '12px 16px',
                        borderRadius: 8,
                        background: 'var(--bg-card)',
                        border: '1px solid var(--border)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>
                        <FolderTree size={16} color="var(--accent)" />
                        JMeter 完整组件树状层级结构
                      </div>
                      <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                        顶级为测试计划，各节点按 JMeter 真实父子层级关系展示（组件类型：组件名称）
                      </span>
                    </div>

                    {(!fullScript.component_tree || fullScript.component_tree.length === 0) ? (
                      <div
                        style={{
                          padding: 40,
                          textAlign: 'center',
                          color: 'var(--text-muted)',
                          background: 'var(--bg-card)',
                          borderRadius: 8,
                          border: '1px solid var(--border)',
                          fontSize: 13,
                        }}
                      >
                        暂无组件树解析数据，请检查 JMX 脚本格式
                      </div>
                    ) : (
                      <div
                        style={{
                          padding: '16px 20px',
                          background: 'var(--bg-card)',
                          borderRadius: 8,
                          border: '1px solid var(--border)',
                          display: 'flex',
                          flexDirection: 'column',
                          gap: 4,
                        }}
                      >
                        {fullScript.component_tree.map((node, idx) => (
                          <JmxTreeNodeView key={idx} node={node} level={0} />
                        ))}
                      </div>
                    )}
                  </div>
                ) : activeTab === 'samplers' ? (
                  /* 接口链路结构可视化 */
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                    {samplers.length === 0 ? (
                      <div
                        style={{
                          padding: 40,
                          textAlign: 'center',
                          color: 'var(--text-muted)',
                          background: 'var(--bg-card)',
                          borderRadius: 8,
                          border: '1px solid var(--border)',
                          fontSize: 13,
                        }}
                      >
                        该场景暂未记录结构化 Samplers 配置，可直接查看 JMX 源码
                      </div>
                    ) : (
                      samplers.map((s: any, idx: number) => (
                        <SamplerStepCard key={idx} sampler={s} index={idx} />
                      ))
                    )}
                  </div>
                ) : activeTab === 'jmx' ? (
                  /* JMX XML 代码预览 */
                  <div
                    style={{
                      border: '1px solid var(--border)',
                      borderRadius: 8,
                      background: 'var(--bg-card)',
                      overflow: 'hidden',
                      display: 'flex',
                      flexDirection: 'column',
                    }}
                  >
                    <div
                      style={{
                        padding: '8px 14px',
                        background: 'var(--bg-base)',
                        borderBottom: '1px solid var(--border)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        fontSize: 12,
                        color: 'var(--text-muted)',
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                        <span>XML 格式 (.jmx) · 标准 JMeter 5.x 测试计划</span>
                        <span>{fullScript.jmx_content ? `${fullScript.jmx_content.length} 字符` : '无内容'}</span>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <button
                          onClick={handleCopyJmx}
                          disabled={!fullScript.jmx_content}
                          style={{
                            padding: '3px 10px',
                            borderRadius: 5,
                            border: '1px solid var(--border)',
                            background: 'var(--bg-card)',
                            color: 'var(--text-primary)',
                            fontSize: 11,
                            cursor: 'pointer',
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: 4,
                          }}
                        >
                          {copied ? <Check size={12} color="#10b981" /> : <Copy size={12} />}
                          {copied ? '已复制' : '复制 JMX'}
                        </button>
                        <button
                          onClick={() => handleDownload(fullScript.id)}
                          disabled={!fullScript.jmx_content}
                          style={{
                            padding: '3px 10px',
                            borderRadius: 5,
                            border: '1px solid var(--border)',
                            background: 'var(--bg-card)',
                            color: 'var(--accent)',
                            fontSize: 11,
                            cursor: 'pointer',
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: 4,
                          }}
                        >
                          <Download size={12} />
                          下载 .jmx
                        </button>
                      </div>
                    </div>
                    <pre
                      style={{
                        margin: 0,
                        padding: 16,
                        fontFamily: 'Consolas, Monaco, "Courier New", monospace',
                        fontSize: 12,
                        lineHeight: 1.5,
                        color: 'var(--text-primary)',
                        background: 'var(--bg-card)',
                        overflowX: 'auto',
                        whiteSpace: 'pre',
                      }}
                    >
                      {fullScript.jmx_content || '暂无 JMX 脚本内容'}
                    </pre>
                  </div>
                ) : activeTab === 'plan' ? (
                  /* 测试方案与配置 */
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                    <div
                      style={{
                        border: '1px solid var(--border)',
                        borderRadius: 8,
                        background: 'var(--bg-card)',
                        padding: 16,
                      }}
                    >
                      <strong style={{ fontSize: 13, display: 'block', marginBottom: 8, color: 'var(--text-primary)' }}>
                        测试方案描述 (Prompt 意图)
                      </strong>
                      <div
                        style={{
                          fontSize: 13,
                          lineHeight: 1.6,
                          color: 'var(--text-secondary)',
                          whiteSpace: 'pre-wrap',
                          background: 'var(--bg-base)',
                          padding: 12,
                          borderRadius: 6,
                          border: '1px solid var(--border)',
                        }}
                      >
                        {fullScript.plan_description || '创建此场景时未提供附加方案描述文本'}
                      </div>
                    </div>

                    <div
                      style={{
                        border: '1px solid var(--border)',
                        borderRadius: 8,
                        background: 'var(--bg-card)',
                        padding: 16,
                      }}
                    >
                      <strong style={{ fontSize: 13, display: 'block', marginBottom: 8, color: 'var(--text-primary)' }}>
                        关联资产 API ID
                      </strong>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                        {fullScript.asset_ids && fullScript.asset_ids.length > 0 ? (
                          fullScript.asset_ids.map((aid) => (
                            <span
                              key={aid}
                              style={{
                                fontSize: 11,
                                padding: '2px 8px',
                                borderRadius: 4,
                                background: 'var(--bg-base)',
                                border: '1px solid var(--border)',
                                color: 'var(--text-primary)',
                              }}
                            >
                              API Asset #{aid}
                            </span>
                          ))
                        ) : (
                          <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>无关联资产 ID</span>
                        )}
                      </div>
                    </div>

                    {fullScript.config && (
                      <div
                        style={{
                          border: '1px solid var(--border)',
                          borderRadius: 8,
                          background: 'var(--bg-card)',
                          padding: 16,
                        }}
                      >
                        <strong style={{ fontSize: 13, display: 'block', marginBottom: 8, color: 'var(--text-primary)' }}>
                          完整配置元数据 (JSON)
                        </strong>
                        <pre
                          style={{
                            margin: 0,
                            padding: 12,
                            background: 'var(--bg-base)',
                            borderRadius: 6,
                            fontSize: 12,
                            fontFamily: 'monospace',
                            overflowX: 'auto',
                            color: 'var(--text-primary)',
                          }}
                        >
                          {JSON.stringify(fullScript.config, null, 2)}
                        </pre>
                      </div>
                    )}
                  </div>
                ) : null}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* 新增测试场景 Modal (支持 AI 方案生成与 JMX 手动上传) */}
      <CreateScenarioModal
        open={createModalOpen}
        onClose={() => setCreateModalOpen(false)}
        projectId={currentProjectId}
        onSuccess={() => {
          if (currentProjectId !== null) loadScripts(currentProjectId);
        }}
      />

      {/* 编辑脚本 Modal */}
      {fullScript && (
        <EditScriptModal
          open={editModalOpen}
          onClose={() => setEditModalOpen(false)}
          script={fullScript}
          onSuccess={() => {
            if (currentProjectId !== null) {
              loadScripts(currentProjectId);
            }
            if (selectedId) {
              fetch(`/api/modules/performance/server/scripts/${selectedId}`)
                .then((res) => res.json())
                .then((data) => setFullScript(data))
                .catch(() => {});
            }
          }}
        />
      )}
    </div>
  );
}

/**
 * 单个 Sampler 接口步骤卡片（支持 Headers 展开/复制、Body 展开/折叠与复制）。
 */
function SamplerStepCard({ sampler, index }: { sampler: any; index: number }) {
  const [bodyOpen, setBodyOpen] = useState(false);
  const [copiedBody, setCopiedBody] = useState(false);

  const method = (sampler.method || 'GET').toUpperCase();
  const methodColor =
    method === 'GET'
      ? '#10b981'
      : method === 'POST'
      ? '#3b82f6'
      : method === 'PUT'
      ? '#f59e0b'
      : method === 'DELETE'
      ? '#ef4444'
      : '#6b7280';

  const rawBody = sampler.body;
  const hasBody = typeof rawBody === 'string' && rawBody.trim().length > 0;

  // 格式化 Body 内容（如果是合法 JSON 自动缩进，否则展示原样）
  const formattedBody = useMemo(() => {
    if (!hasBody) return '';
    try {
      const obj = JSON.parse(rawBody);
      return JSON.stringify(obj, null, 2);
    } catch {
      return rawBody;
    }
  }, [rawBody, hasBody]);

  const handleCopyBody = () => {
    navigator.clipboard.writeText(formattedBody);
    setCopiedBody(true);
    toast.success('Body 内容已复制到剪贴板');
    setTimeout(() => setCopiedBody(false), 2000);
  };

  return (
    <div
      style={{
        border: '1px solid var(--border)',
        borderRadius: 8,
        background: 'var(--bg-card)',
        padding: 14,
        display: 'flex',
        flexDirection: 'column',
        gap: 10,
      }}
    >
      {/* 头部标题行 */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flex: 1, minWidth: 0 }}>
          <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', width: 24 }}>
            #{index + 1}
          </span>

          <span
            style={{
              fontSize: 11,
              fontWeight: 700,
              padding: '2px 8px',
              borderRadius: 4,
              background: `${methodColor}15`,
              color: methodColor,
              border: `1px solid ${methodColor}40`,
            }}
          >
            {method}
          </span>

          <strong
            style={{
              fontSize: 13,
              color: 'var(--text-primary)',
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}
          >
            {sampler.name || sampler.path}
          </strong>

          <span
            style={{
              fontSize: 12,
              color: 'var(--text-muted)',
              fontFamily: 'monospace',
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}
          >
            {sampler.path || sampler.url}
          </span>
        </div>
      </div>

      {/* 变量提取器（兼容字典格式与对象数组格式） */}
      {sampler.extract && typeof sampler.extract === 'object' && Object.keys(sampler.extract).length > 0 && (
        <div
          style={{
            background: 'var(--bg-base)',
            padding: '6px 10px',
            borderRadius: 4,
            fontSize: 11,
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            flexWrap: 'wrap',
          }}
        >
          <span style={{ color: 'var(--accent)', fontWeight: 600 }}>变量提取:</span>
          {Object.entries(sampler.extract).map(([k, v]) => (
            <span
              key={k}
              style={{
                background: 'var(--bg-card)',
                border: '1px solid var(--border)',
                padding: '1px 6px',
                borderRadius: 4,
                fontFamily: 'monospace',
              }}
            >
              ${`{${k}}`} ← {String(v)}
            </span>
          ))}
        </div>
      )}
      {sampler.extractors && Array.isArray(sampler.extractors) && sampler.extractors.length > 0 && (
        <div
          style={{
            background: 'var(--bg-base)',
            padding: '6px 10px',
            borderRadius: 4,
            fontSize: 11,
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            flexWrap: 'wrap',
          }}
        >
          <span style={{ color: 'var(--accent)', fontWeight: 600 }}>变量提取:</span>
          {sampler.extractors.map((ext: any, i: number) => (
            <span
              key={i}
              style={{
                background: 'var(--bg-card)',
                border: '1px solid var(--border)',
                padding: '1px 6px',
                borderRadius: 4,
                fontFamily: 'monospace',
              }}
            >
              ${`{${ext.variable_name}}`} ← {ext.json_path}
            </span>
          ))}
        </div>
      )}

      {/* 断言规则 */}
      {sampler.assertions && Array.isArray(sampler.assertions) && sampler.assertions.length > 0 && (
        <div
          style={{
            background: 'var(--bg-base)',
            padding: '6px 10px',
            borderRadius: 4,
            fontSize: 11,
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            flexWrap: 'wrap',
          }}
        >
          <span style={{ color: '#10b981', fontWeight: 600 }}>断言校验:</span>
          {sampler.assertions.map((ass: any, i: number) => (
            <span
              key={i}
              style={{
                background: 'var(--bg-card)',
                border: '1px solid var(--border)',
                padding: '1px 6px',
                borderRadius: 4,
              }}
            >
              {ass.type || ass.test_field || '校验'}: {ass.expected !== undefined ? ass.expected : ass.pattern || '200'}
            </span>
          ))}
        </div>
      )}

      {/* Body 详情面板（可展开折叠） */}
      {hasBody && (
        <div
          style={{
            border: '1px solid var(--border)',
            borderRadius: 6,
            background: 'var(--bg-base)',
            overflow: 'hidden',
          }}
        >
          {bodyOpen ? (
            /* 展开态：展示完整格式化代码、复制按钮和收起按钮 */
            <div>
              <div
                style={{
                  padding: '6px 10px',
                  borderBottom: '1px solid var(--border)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  fontSize: 11,
                  color: 'var(--text-muted)',
                  background: 'var(--bg-card)',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span style={{ fontWeight: 600 }}>Request Body</span>
                  <span>({formattedBody.length} 字符)</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <button
                    onClick={handleCopyBody}
                    style={{
                      border: 'none',
                      background: 'transparent',
                      color: 'var(--accent)',
                      cursor: 'pointer',
                      fontSize: 11,
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: 3,
                      padding: 0,
                    }}
                  >
                    {copiedBody ? <Check size={11} color="#10b981" /> : <Copy size={11} />}
                    {copiedBody ? '已复制' : '复制 Body'}
                  </button>
                  <button
                    onClick={() => setBodyOpen(false)}
                    style={{
                      border: 'none',
                      background: 'transparent',
                      color: 'var(--text-muted)',
                      cursor: 'pointer',
                      fontSize: 11,
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: 2,
                      padding: 0,
                    }}
                  >
                    <ChevronUp size={11} /> 折叠
                  </button>
                </div>
              </div>
              <pre
                style={{
                  margin: 0,
                  padding: 10,
                  fontSize: 11,
                  fontFamily: 'Consolas, Monaco, "Courier New", monospace',
                  lineHeight: 1.45,
                  maxHeight: 240,
                  overflow: 'auto',
                  background: 'var(--bg-base)',
                  color: 'var(--text-primary)',
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-all',
                }}
              >
                {formattedBody}
              </pre>
            </div>
          ) : (
            /* 折叠态：单行预览 + 展开按钮 */
            <div
              style={{
                padding: '6px 10px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: 10,
                fontSize: 11,
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, flex: 1, minWidth: 0 }}>
                <span style={{ color: 'var(--text-muted)', fontWeight: 600, flexShrink: 0 }}>Body:</span>
                <code
                  style={{
                    fontFamily: 'monospace',
                    color: 'var(--text-secondary)',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {rawBody}
                </code>
              </div>
              <button
                onClick={() => setBodyOpen(true)}
                style={{
                  border: 'none',
                  background: 'transparent',
                  color: 'var(--accent)',
                  cursor: 'pointer',
                  fontSize: 11,
                  flexShrink: 0,
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 2,
                  padding: '1px 4px',
                }}
              >
                <ChevronDown size={12} /> 展开
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * JMeter 组件树节点展示（支持展开/折叠、状态标识与组件类型徽章）。
 * 展示格式：组件类型：组件名称
 */
function JmxTreeNodeView({ node, level = 0 }: { node: JmxTreeNode; level?: number }) {
  const [expanded, setExpanded] = useState(true);
  const hasChildren = node.children && node.children.length > 0;

  // 组件徽章颜色分类
  const getBadgeStyle = (tag: string, testclass: string) => {
    if (tag === 'TestPlan' || testclass === 'TestPlan') {
      return { bg: 'rgba(59, 130, 246, 0.15)', text: '#3b82f6', border: 'rgba(59, 130, 246, 0.3)' };
    }
    if (tag.includes('ThreadGroup') || testclass.includes('ThreadGroup')) {
      return { bg: 'rgba(16, 185, 129, 0.15)', text: '#10b981', border: 'rgba(16, 185, 129, 0.3)' };
    }
    if (tag.includes('Sampler') || testclass.includes('Sampler') || tag.includes('Http')) {
      return { bg: 'rgba(245, 158, 11, 0.15)', text: '#f59e0b', border: 'rgba(245, 158, 11, 0.3)' };
    }
    if (tag.includes('Controller') || testclass.includes('Controller')) {
      return { bg: 'rgba(139, 92, 246, 0.15)', text: '#8b5cf6', border: 'rgba(139, 92, 246, 0.3)' };
    }
    if (tag.includes('Assertion') || testclass.includes('Assertion')) {
      return { bg: 'rgba(239, 68, 68, 0.15)', text: '#ef4444', border: 'rgba(239, 68, 68, 0.3)' };
    }
    if (tag.includes('PostProcessor') || tag.includes('Extractor')) {
      return { bg: 'rgba(14, 165, 233, 0.15)', text: '#0ea5e9', border: 'rgba(14, 165, 233, 0.3)' };
    }
    if (tag.includes('PreProcessor')) {
      return { bg: 'rgba(236, 72, 153, 0.15)', text: '#ec4899', border: 'rgba(236, 72, 153, 0.3)' };
    }
    if (tag.includes('Timer')) {
      return { bg: 'rgba(234, 179, 8, 0.15)', text: '#eab308', border: 'rgba(234, 179, 8, 0.3)' };
    }
    if (tag.includes('Collector') || tag.includes('Listener')) {
      return { bg: 'rgba(100, 116, 139, 0.15)', text: '#64748b', border: 'rgba(100, 116, 139, 0.3)' };
    }
    return { bg: 'var(--bg-base)', text: 'var(--text-secondary)', border: 'var(--border)' };
  };

  const badge = getBadgeStyle(node.tag, node.testclass);

  return (
    <div style={{ display: 'flex', flexDirection: 'column' }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          padding: '5px 8px',
          paddingLeft: level * 20 + 8,
          borderRadius: 5,
          transition: 'background 0.15s ease',
          fontSize: 12,
          color: node.enabled ? 'var(--text-primary)' : 'var(--text-muted)',
          opacity: node.enabled ? 1 : 0.6,
        }}
        onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--bg-base)')}
        onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
      >
        {/* 展开/折叠箭头 */}
        {hasChildren ? (
          <button
            onClick={() => setExpanded(!expanded)}
            style={{
              background: 'transparent',
              border: 'none',
              cursor: 'pointer',
              color: 'var(--text-muted)',
              padding: 0,
              display: 'flex',
              alignItems: 'center',
            }}
          >
            {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          </button>
        ) : (
          <span style={{ width: 14, height: 14, display: 'inline-block' }} />
        )}

        {/* 树状层级线引导点 */}
        <span
          style={{
            width: 6,
            height: 6,
            borderRadius: '50%',
            background: badge.text,
            flexShrink: 0,
          }}
        />

        {/* 组件类型徽章 */}
        <span
          style={{
            fontSize: 11,
            padding: '1px 6px',
            borderRadius: 4,
            fontWeight: 600,
            background: badge.bg,
            color: badge.text,
            border: `1px solid ${badge.border}`,
            flexShrink: 0,
          }}
        >
          {node.type_label}
        </span>

        {/* 冒号与组件名称展示（满足需求：组件类型：组件名称） */}
        <span style={{ color: 'var(--text-muted)', fontWeight: 600, margin: '0 1px' }}>:</span>
        <span
          style={{
            fontWeight: level === 0 ? 700 : 500,
            color: level === 0 ? 'var(--text-primary)' : 'var(--text-primary)',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
          title={node.name}
        >
          {node.name}
        </span>

        {!node.enabled && (
          <span style={{ fontSize: 10, color: '#ef4444', background: 'rgba(239,68,68,0.1)', padding: '0 4px', borderRadius: 2 }}>
            已禁用
          </span>
        )}

        {hasChildren && (
          <span style={{ fontSize: 10, color: 'var(--text-muted)', marginLeft: 'auto' }}>
            {node.children.length} 个子元件
          </span>
        )}
      </div>

      {/* 递归渲染子组件树 */}
      {hasChildren && expanded && (
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          {node.children.map((child, cIdx) => (
            <JmxTreeNodeView key={cIdx} node={child} level={level + 1} />
          ))}
        </div>
      )}
    </div>
  );
}
