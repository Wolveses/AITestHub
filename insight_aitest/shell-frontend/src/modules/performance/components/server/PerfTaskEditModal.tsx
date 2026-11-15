import { useEffect, useState } from 'react';
import {
  X,
  Copy,
  Check,
  Terminal,
  Cpu,
  Search,
  CheckSquare,
  Square,
  FileCode,
  Tag,
  Plus,
  Trash2,
} from 'lucide-react';
import { toast } from 'sonner';
import { useServerPerfStore } from '../../store/serverPerfStore';
import { buildJMeterCommand } from './commandPreview';

interface PerfTaskEditModalProps {
  isOpen: boolean;
  taskId: number | null;
  onClose: () => void;
  onSuccess: () => void;
}

export function PerfTaskEditModal({
  isOpen,
  taskId,
  onClose,
  onSuccess,
}: PerfTaskEditModalProps) {
  const { scripts, slaveNodes, loadSlaveNodes } = useServerPerfStore();
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  // 表单状态
  const [name, setName] = useState('');
  const [desc, setDesc] = useState('');
  const [engineType, setEngineType] = useState<'builtin' | 'jmeter_cli'>('jmeter_cli');
  const [execMode, setExecMode] = useState<'local' | 'distributed'>('local');
  const [slaveHosts, setSlaveHosts] = useState('');
  const [selectedScripts, setSelectedScripts] = useState<{ script_id: number; weight: number }[]>([]);
  const [scriptSearch, setScriptSearch] = useState('');

  // 动态属性管理
  const [customProperties, setCustomProperties] = useState<Record<string, string>>({});
  const [extractedProps, setExtractedProps] = useState<{ name: string; default_value: string }[]>([]);
  const [deletedPropKeys, setDeletedPropKeys] = useState<string[]>([]);
  const [loadingProps, setLoadingProps] = useState(false);
  const [newPropKey, setNewPropKey] = useState('');
  const [newPropVal, setNewPropVal] = useState('');

  // 命令复制状态
  const [copied, setCopied] = useState(false);

  // 1. 打开时拉取任务详情并初始化表单
  useEffect(() => {
    if (!isOpen || !taskId) {
      return;
    }
    loadSlaveNodes();
    setLoading(true);
    fetch(`/api/modules/performance/server/tasks/${taskId}`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data) => {
        setName(data.name || '');
        setDesc(data.description || '');
        setEngineType(data.engine_type || 'jmeter_cli');
        setExecMode(data.exec_mode || 'local');
        setSlaveHosts(data.slave_hosts || '');
        setCustomProperties(data.custom_properties || {});
        setDeletedPropKeys([]);

        const scriptItems = (data.scripts || []).map((s: any) => ({
          script_id: s.script_id,
          weight: s.weight || 100,
        }));
        setSelectedScripts(scriptItems);
      })
      .catch((err) => {
        console.error('加载任务详情失败', err);
        toast.error('加载任务详情失败: ' + err.message);
      })
      .finally(() => {
        setLoading(false);
      });
  }, [isOpen, taskId]);

  // 2. 当选中脚本改变时，调用后端接口获取脚本基础动态参数
  useEffect(() => {
    if (!isOpen || selectedScripts.length === 0) {
      setExtractedProps([]);
      setCustomProperties((prev) => {
        const next: Record<string, string> = {};
        Object.entries(prev).forEach(([k, v]) => {
          if (!extractedProps.some((p) => p.name === k)) {
            next[k] = v;
          }
        });
        return next;
      });
      return;
    }
    const ids = selectedScripts.map((s) => s.script_id).join(',');
    setLoadingProps(true);
    fetch(`/api/modules/performance/server/scripts/batch/properties?script_ids=${ids}`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data) => {
        const newExtracted: { name: string; default_value: string }[] = data.properties || [];
        const newExtractedNames = new Set(newExtracted.map((p) => p.name));

        setExtractedProps(newExtracted);
        setCustomProperties((prev) => {
          const next: Record<string, string> = {};
          // 1. 保留原本属于用户手动添加的非脚本探测参数，或仍在新提取列表中的参数值
          Object.entries(prev).forEach(([k, v]) => {
            const wasExtracted = extractedProps.some((p) => p.name === k);
            if (!wasExtracted) {
              next[k] = v;
            } else if (newExtractedNames.has(k)) {
              next[k] = v;
            }
          });

          // 2. 将新检测到的脚本参数填入（若未设置则使用 default_value）
          newExtracted.forEach((p) => {
            if (next[p.name] === undefined) {
              next[p.name] = p.default_value ?? '';
            }
          });
          return next;
        });
      })
      .catch((err) => {
        console.error('从后端接口获取脚本动态参数失败', err);
      })
      .finally(() => {
        setLoadingProps(false);
      });
  }, [isOpen, selectedScripts]);

  if (!isOpen) return null;

  // 查找主脚本名称
  const primaryScript = scripts.find((s) => s.id === selectedScripts[0]?.script_id);
  const primaryScriptName = primaryScript?.name || 'plan';

  // 实时生成命令预览
  const commandPreview = buildJMeterCommand({
    engineType,
    execMode,
    slaveHosts,
    scriptName: primaryScriptName,
    customProperties,
  });

  const handleCopyCommand = () => {
    if (!commandPreview) return;
    navigator.clipboard.writeText(commandPreview);
    setCopied(true);
    toast.success('命令已复制到剪贴板');
    setTimeout(() => setCopied(false), 2000);
  };

  const toggleScriptSelection = (scriptId: number) => {
    if (selectedScripts.some((s) => s.script_id === scriptId)) {
      setSelectedScripts(selectedScripts.filter((s) => s.script_id !== scriptId));
    } else {
      setSelectedScripts([...selectedScripts, { script_id: scriptId, weight: 100 }]);
    }
  };

  const handleDeleteProp = (propName: string) => {
    setCustomProperties((prev) => {
      const next = { ...prev };
      delete next[propName];
      return next;
    });
    setDeletedPropKeys((prev) => (prev.includes(propName) ? prev : [...prev, propName]));
  };

  const handleSave = async () => {
    if (!name.trim()) {
      toast.error('任务名称不能为空');
      return;
    }
    if (selectedScripts.length === 0) {
      toast.error('请至少关联一个压测脚本');
      return;
    }

    setSaving(true);
    const finalProps: Record<string, string> = { ...customProperties };
    extractedProps.forEach((p) => {
      if (!deletedPropKeys.includes(p.name) && finalProps[p.name] === undefined) {
        finalProps[p.name] = p.default_value ?? '';
      }
    });

    try {
      const res = await fetch(`/api/modules/performance/server/tasks/${taskId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: name.trim(),
          description: desc.trim(),
          engine_type: engineType,
          exec_mode: execMode,
          slave_hosts: execMode === 'distributed' ? slaveHosts : '',
          custom_properties: finalProps,
          script_items: selectedScripts,
        }),
      });
      const ret = await res.json();
      if (!res.ok) throw new Error(ret.detail || '更新失败');

      toast.success('性能测试任务更新成功');
      onSuccess();
      onClose();
    } catch (err: any) {
      toast.error(err.message || '更新任务失败');
    } finally {
      setSaving(false);
    }
  };

  // 整合全部动态参数列表
  const allPropertyKeys = Array.from(
    new Set([
      ...extractedProps.map((p) => p.name).filter((k) => !deletedPropKeys.includes(k)),
      ...Object.keys(customProperties),
    ])
  );

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.6)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
        backdropFilter: 'blur(3px)',
      }}
      onClick={onClose}
    >
      <div
        style={{
          background: 'var(--bg-card)',
          border: '1px solid var(--border)',
          borderRadius: 10,
          width: '90%',
          maxWidth: 780,
          maxHeight: '90vh',
          display: 'flex',
          flexDirection: 'column',
          boxShadow: '0 20px 25px -5px rgba(0,0,0,0.3)',
          overflow: 'hidden',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div
          style={{
            padding: '14px 20px',
            borderBottom: '1px solid var(--border)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            background: 'var(--bg-base)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Cpu size={17} color="var(--accent)" />
            <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, color: 'var(--text-primary)' }}>
              编辑性能测试任务 (#{taskId})
            </h3>
          </div>
          <button
            onClick={onClose}
            style={{
              background: 'transparent',
              border: 'none',
              cursor: 'pointer',
              color: 'var(--text-muted)',
              display: 'flex',
              padding: 4,
            }}
          >
            <X size={18} />
          </button>
        </div>

        {/* Content Body */}
        <div style={{ padding: '18px 22px', overflowY: 'auto', flex: 1, display: 'flex', flexDirection: 'column', gap: 16 }}>
          {loading ? (
            <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
              正在加载任务配置...
            </div>
          ) : (
            <>
              {/* 1. 任务基础信息 */}
              <div
                style={{
                  background: 'var(--bg-base)',
                  border: '1px solid var(--border)',
                  borderRadius: 6,
                  padding: '12px 16px',
                  display: 'grid',
                  gridTemplateColumns: 'repeat(2, 1fr)',
                  gap: '10px 16px',
                  fontSize: 12,
                }}
              >
                <div>
                  <label style={{ color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>
                    任务名称 <span style={{ color: '#ef4444' }}>*</span>
                  </label>
                  <input
                    type="text"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="输入任务名称"
                    style={{
                      width: '100%',
                      height: 30,
                      padding: '0 8px',
                      borderRadius: 4,
                      border: '1px solid var(--border)',
                      background: 'var(--bg-card)',
                      color: 'var(--text-primary)',
                      fontSize: 12,
                    }}
                  />
                </div>

                <div>
                  <label style={{ color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>压测引擎</label>
                  <select
                    value={engineType}
                    onChange={(e: any) => setEngineType(e.target.value)}
                    style={{
                      width: '100%',
                      height: 30,
                      padding: '0 6px',
                      borderRadius: 4,
                      border: '1px solid var(--border)',
                      background: 'var(--bg-card)',
                      color: 'var(--text-primary)',
                      fontSize: 12,
                      cursor: 'pointer',
                    }}
                  >
                    <option value="jmeter_cli">本地 JMeter CLI (推荐)</option>
                    <option value="builtin">内置 Python 异步 (备用)</option>
                  </select>
                </div>

                <div style={{ gridColumn: 'span 2' }}>
                  <label style={{ color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>任务描述</label>
                  <input
                    type="text"
                    value={desc}
                    onChange={(e) => setDesc(e.target.value)}
                    placeholder="任务的场景说明与测试目标描述（选填）"
                    style={{
                      width: '100%',
                      height: 30,
                      padding: '0 8px',
                      borderRadius: 4,
                      border: '1px solid var(--border)',
                      background: 'var(--bg-card)',
                      color: 'var(--text-primary)',
                      fontSize: 12,
                    }}
                  />
                </div>

                <div>
                  <label style={{ color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>执行模式</label>
                  <select
                    value={execMode}
                    onChange={(e: any) => setExecMode(e.target.value)}
                    style={{
                      width: '100%',
                      height: 30,
                      padding: '0 6px',
                      borderRadius: 4,
                      border: '1px solid var(--border)',
                      background: 'var(--bg-card)',
                      color: 'var(--text-primary)',
                      fontSize: 12,
                      cursor: 'pointer',
                    }}
                  >
                    <option value="local">🖥️ 本机单机执行</option>
                    <option value="distributed">🌐 Master 分布式从机</option>
                  </select>
                </div>

                {execMode === 'distributed' && (
                  <div style={{ gridColumn: 'span 2', display: 'flex', flexDirection: 'column', gap: 6 }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <label style={{ color: 'var(--text-muted)' }}>选择从机节点</label>
                        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                          (已选 {slaveHosts.split(',').map((h) => h.trim()).filter(Boolean).length} / {slaveNodes.length})
                        </span>
                      </div>
                      {slaveNodes.length > 0 && (
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                          <button
                            type="button"
                            onClick={() => {
                              const onlineHosts = slaveNodes.filter((n) => n.status === 'online').map((n) => `${n.host}:${n.port}`);
                              if (onlineHosts.length === 0) {
                                toast.warning('暂无在线从机节点');
                                return;
                              }
                              setSlaveHosts(onlineHosts.join(', '));
                            }}
                            style={{ background: 'none', border: 'none', color: 'var(--accent)', cursor: 'pointer', padding: 0, fontSize: 11 }}
                          >
                            全选在线从机 ({slaveNodes.filter((n) => n.status === 'online').length})
                          </button>
                          {slaveHosts && (
                            <button
                              type="button"
                              onClick={() => setSlaveHosts('')}
                              style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', padding: 0, fontSize: 11 }}
                            >
                              清空
                            </button>
                          )}
                        </div>
                      )}
                    </div>

                    {/* 可用从机节点勾选列表（取消手动输入） */}
                    {slaveNodes.length > 0 ? (
                      <div
                        style={{
                          display: 'flex',
                          flexWrap: 'wrap',
                          gap: 6,
                          padding: '8px 10px',
                          background: 'var(--bg-card)',
                          border: '1px solid var(--border)',
                          borderRadius: 6,
                          maxHeight: 120,
                          overflowY: 'auto',
                        }}
                      >
                        {slaveNodes.map((node) => {
                          const hostPort = `${node.host}:${node.port}`;
                          const currentHosts = slaveHosts
                            .split(',')
                            .map((h) => h.trim())
                            .filter(Boolean);
                          const isChecked = currentHosts.includes(hostPort);

                          return (
                            <label
                              key={node.id}
                              style={{
                                display: 'inline-flex',
                                alignItems: 'center',
                                gap: 6,
                                fontSize: 11,
                                cursor: 'pointer',
                                padding: '4px 8px',
                                borderRadius: 4,
                                background: isChecked ? 'rgba(59, 130, 246, 0.12)' : 'var(--bg-base)',
                                border: `1px solid ${isChecked ? 'var(--accent)' : 'var(--border)'}`,
                                color: isChecked ? 'var(--accent)' : 'var(--text-primary)',
                                transition: 'all 0.15s ease',
                              }}
                            >
                              <input
                                type="checkbox"
                                checked={isChecked}
                                onChange={(e) => {
                                  if (e.target.checked) {
                                    const next = Array.from(new Set([...currentHosts, hostPort]));
                                    setSlaveHosts(next.join(', '));
                                  } else {
                                    const next = currentHosts.filter((h) => h !== hostPort);
                                    setSlaveHosts(next.join(', '));
                                  }
                                }}
                                style={{ margin: 0 }}
                              />
                              <span
                                style={{
                                  display: 'inline-block',
                                  width: 7,
                                  height: 7,
                                  borderRadius: '50%',
                                  background: node.status === 'online' ? '#10b981' : '#94a3b8',
                                }}
                                title={node.status === 'online' ? '在线' : '离线'}
                              />
                              <span style={{ fontWeight: 500 }}>{node.name || node.host}</span>
                              <span style={{ color: 'var(--text-muted)', fontSize: 10, fontFamily: 'monospace' }}>({hostPort})</span>
                            </label>
                          );
                        })}
                      </div>
                    ) : (
                      <div
                        style={{
                          fontSize: 12,
                          color: 'var(--text-muted)',
                          padding: '12px 14px',
                          background: 'var(--bg-card)',
                          border: '1px dashed var(--border)',
                          borderRadius: 6,
                          textAlign: 'center',
                        }}
                      >
                        暂无已注册的从机节点，请先在「从机节点管理」中添加并启动从机服务
                      </div>
                    )}
                  </div>
                )}
              </div>

              {/* 2. 关联压测脚本 */}
              <div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: 6 }}>
                    <FileCode size={14} color="var(--accent)" />
                    关联压测脚本
                    <span
                      style={{
                        fontSize: 11,
                        padding: '1px 7px',
                        borderRadius: 10,
                        background: selectedScripts.length > 0 ? 'rgba(59,130,246,0.12)' : 'var(--bg-base)',
                        color: selectedScripts.length > 0 ? 'var(--accent)' : 'var(--text-muted)',
                        fontWeight: 500,
                      }}
                    >
                      已选 {selectedScripts.length} / {scripts.length}
                    </span>
                  </div>

                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    {scripts.length > 0 && (
                      <button
                        type="button"
                        onClick={() => {
                          if (selectedScripts.length === scripts.length) {
                            setSelectedScripts([]);
                          } else {
                            setSelectedScripts(scripts.map((s) => ({ script_id: s.id, weight: 100 })));
                          }
                        }}
                        style={{ background: 'none', border: 'none', color: 'var(--accent)', fontSize: 11, cursor: 'pointer', padding: 0 }}
                      >
                        {selectedScripts.length === scripts.length ? '取消全选' : '全选全部'}
                      </button>
                    )}
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 4,
                        background: 'var(--bg-base)',
                        border: '1px solid var(--border)',
                        borderRadius: 4,
                        padding: '0 6px',
                        height: 24,
                      }}
                    >
                      <Search size={12} style={{ color: 'var(--text-muted)' }} />
                      <input
                        type="text"
                        placeholder="搜索脚本..."
                        value={scriptSearch}
                        onChange={(e) => setScriptSearch(e.target.value)}
                        style={{
                          background: 'transparent',
                          border: 'none',
                          outline: 'none',
                          fontSize: 11,
                          color: 'var(--text-primary)',
                          width: 100,
                        }}
                      />
                    </div>
                  </div>
                </div>

                <div
                  style={{
                    border: '1px solid var(--border)',
                    borderRadius: 6,
                    maxHeight: 160,
                    overflowY: 'auto',
                    background: 'var(--bg-base)',
                  }}
                >
                  {scripts.length === 0 ? (
                    <div style={{ padding: 20, textAlign: 'center', color: 'var(--text-muted)', fontSize: 12 }}>
                      暂无压测脚本
                    </div>
                  ) : (
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                      <thead>
                        <tr style={{ background: 'var(--bg-card)', borderBottom: '1px solid var(--border)', color: 'var(--text-muted)' }}>
                          <th style={{ padding: '6px 12px', width: 36, textAlign: 'center' }}></th>
                          <th style={{ padding: '6px 12px', textAlign: 'left' }}>脚本名称</th>
                          <th style={{ padding: '6px 12px', textAlign: 'left', width: 90 }}>脚本 ID</th>
                          <th style={{ padding: '6px 12px', textAlign: 'left', width: 100 }}>接口数</th>
                        </tr>
                      </thead>
                      <tbody>
                        {scripts
                          .filter((sc) => !scriptSearch.trim() || sc.name.toLowerCase().includes(scriptSearch.toLowerCase()))
                          .map((sc) => {
                            const isSelected = selectedScripts.some((s) => s.script_id === sc.id);
                            const stepCount = (sc.asset_ids && sc.asset_ids.length > 0)
                              ? sc.asset_ids.length
                              : (Array.isArray(sc.config?.steps) ? sc.config.steps.length : (Array.isArray(sc.config?.samplers) ? sc.config.samplers.length : 0));
                            return (
                              <tr
                                key={sc.id}
                                onClick={() => toggleScriptSelection(sc.id)}
                                style={{
                                  borderBottom: '1px solid var(--border)',
                                  background: isSelected ? 'rgba(59, 130, 246, 0.05)' : 'transparent',
                                  cursor: 'pointer',
                                }}
                              >
                                <td style={{ padding: '6px 12px', textAlign: 'center' }}>
                                  {isSelected ? <CheckSquare size={14} color="var(--accent)" /> : <Square size={14} color="var(--text-muted)" />}
                                </td>
                                <td style={{ padding: '6px 12px', color: isSelected ? 'var(--accent)' : 'var(--text-primary)', fontWeight: isSelected ? 600 : 400 }}>
                                  {sc.name}
                                </td>
                                <td style={{ padding: '6px 12px', color: 'var(--text-muted)' }}>
                                  #{sc.id}
                                </td>
                                <td style={{ padding: '6px 12px', color: 'var(--text-secondary)' }}>
                                  {stepCount} 个
                                </td>
                              </tr>
                            );
                          })}
                      </tbody>
                    </table>
                  )}
                </div>
              </div>

              {/* 3. 脚本动态参数配置 (-J 属性) */}
              <div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: 6 }}>
                    <Tag size={14} color="var(--accent)" />
                    脚本动态参数配置 (-J 属性)
                    <span style={{ fontSize: 11, fontWeight: 400, color: 'var(--text-muted)' }}>
                      (共 {allPropertyKeys.length} 个参数)
                    </span>
                  </div>
                  {loadingProps && <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>解析中...</span>}
                </div>

                <div
                  style={{
                    background: 'var(--bg-base)',
                    border: '1px solid var(--border)',
                    borderRadius: 6,
                    padding: '10px 12px',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 10,
                  }}
                >
                  {allPropertyKeys.length === 0 ? (
                    <div style={{ padding: '8px', color: 'var(--text-muted)', fontSize: 12, textAlign: 'center' }}>
                      未配置动态参数，您可在下方添加自定义 -J 属性。
                    </div>
                  ) : (
                    <div
                      style={{
                        display: 'grid',
                        gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
                        gap: 8,
                        maxHeight: 180,
                        overflowY: 'auto',
                      }}
                    >
                      {allPropertyKeys.map((propName) => {
                        const rawExt = extractedProps.find((p) => p.name === propName);
                        const val = customProperties[propName] !== undefined ? customProperties[propName] : (rawExt?.default_value ?? '');
                        const isExtracted = !!rawExt;

                        return (
                          <div
                            key={propName}
                            style={{
                              background: 'var(--bg-card)',
                              border: '1px solid var(--border)',
                              borderRadius: 6,
                              padding: '6px 8px',
                              display: 'flex',
                              alignItems: 'center',
                              gap: 6,
                            }}
                          >
                            <span
                              style={{
                                fontSize: 11,
                                fontWeight: 600,
                                color: isExtracted ? 'var(--text-primary)' : 'var(--accent)',
                                flex: 1,
                                overflow: 'hidden',
                                textOverflow: 'ellipsis',
                                whiteSpace: 'nowrap',
                              }}
                              title={propName}
                            >
                              {propName}
                            </span>
                            <input
                              type="text"
                              value={val}
                              placeholder={rawExt?.default_value ? `默认: ${rawExt.default_value}` : '空值'}
                              onChange={(e) => setCustomProperties({ ...customProperties, [propName]: e.target.value })}
                              style={{
                                width: 90,
                                height: 22,
                                padding: '0 6px',
                                borderRadius: 4,
                                border: '1px solid var(--border)',
                                background: 'var(--bg-base)',
                                color: 'var(--text-primary)',
                                fontSize: 11,
                              }}
                            />
                            <button
                              type="button"
                              onClick={() => handleDeleteProp(propName)}
                              title="移除该动态参数"
                              style={{
                                background: 'none',
                                border: 'none',
                                color: '#ef4444',
                                cursor: 'pointer',
                                padding: 2,
                                display: 'flex',
                              }}
                            >
                              <Trash2 size={12} />
                            </button>
                          </div>
                        );
                      })}
                    </div>
                  )}

                  {/* 快捷追加新参数 */}
                  <div style={{ display: 'flex', gap: 6, paddingTop: 4, borderTop: '1px solid var(--border)' }}>
                    <input
                      type="text"
                      placeholder="自定义参数名 (如 threads)"
                      value={newPropKey}
                      onChange={(e) => setNewPropKey(e.target.value)}
                      style={{
                        flex: 1,
                        height: 26,
                        padding: '0 8px',
                        borderRadius: 4,
                        border: '1px solid var(--border)',
                        background: 'var(--bg-card)',
                        color: 'var(--text-primary)',
                        fontSize: 11,
                      }}
                    />
                    <input
                      type="text"
                      placeholder="属性值"
                      value={newPropVal}
                      onChange={(e) => setNewPropVal(e.target.value)}
                      style={{
                        flex: 1,
                        height: 26,
                        padding: '0 8px',
                        borderRadius: 4,
                        border: '1px solid var(--border)',
                        background: 'var(--bg-card)',
                        color: 'var(--text-primary)',
                        fontSize: 11,
                      }}
                    />
                    <button
                      type="button"
                      onClick={() => {
                        if (!newPropKey.trim()) return;
                        const key = newPropKey.trim();
                        setDeletedPropKeys((prev) => prev.filter((k) => k !== key));
                        setCustomProperties({ ...customProperties, [key]: newPropVal.trim() });
                        setNewPropKey('');
                        setNewPropVal('');
                      }}
                      style={{
                        height: 26,
                        padding: '0 10px',
                        borderRadius: 4,
                        border: '1px solid var(--border)',
                        background: 'var(--bg-card)',
                        color: 'var(--text-primary)',
                        fontSize: 11,
                        cursor: 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        gap: 3,
                      }}
                    >
                      <Plus size={12} /> 添加
                    </button>
                  </div>
                </div>
              </div>

              {/* 4. 实时调度命令预览 */}
              <div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: 6 }}>
                    <Terminal size={14} color="#38bdf8" />
                    调度执行命令实时预览
                  </div>
                  <button
                    type="button"
                    onClick={handleCopyCommand}
                    style={{
                      background: 'none',
                      border: 'none',
                      color: copied ? '#10b981' : 'var(--accent)',
                      fontSize: 11,
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      gap: 4,
                      padding: 0,
                    }}
                  >
                    {copied ? <Check size={12} /> : <Copy size={12} />}
                    {copied ? '已复制' : '复制命令'}
                  </button>
                </div>
                <div
                  style={{
                    background: '#090d16',
                    border: '1px solid rgba(255,255,255,0.1)',
                    borderRadius: 6,
                    padding: '10px 14px',
                    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
                    fontSize: 11,
                    color: '#38bdf8',
                    lineHeight: 1.5,
                    wordBreak: 'break-all',
                    maxHeight: 80,
                    overflowY: 'auto',
                  }}
                >
                  {commandPreview}
                </div>
              </div>
            </>
          )}
        </div>

        {/* Footer */}
        <div
          style={{
            padding: '12px 20px',
            borderTop: '1px solid var(--border)',
            background: 'var(--bg-base)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'flex-end',
            gap: 10,
          }}
        >
          <button
            type="button"
            onClick={onClose}
            style={{
              height: 30,
              padding: '0 14px',
              borderRadius: 5,
              border: '1px solid var(--border)',
              background: 'var(--bg-card)',
              color: 'var(--text-secondary)',
              fontSize: 12,
              cursor: 'pointer',
            }}
          >
            取消
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={saving}
            style={{
              height: 30,
              padding: '0 16px',
              borderRadius: 5,
              border: 'none',
              background: 'var(--accent)',
              color: '#fff',
              fontSize: 12,
              fontWeight: 500,
              cursor: saving ? 'not-allowed' : 'pointer',
              opacity: saving ? 0.6 : 1,
            }}
          >
            {saving ? '保存中...' : '保存更改'}
          </button>
        </div>
      </div>
    </div>
  );
}