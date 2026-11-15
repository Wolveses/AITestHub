import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import {
  Server,
  Plus,
  RefreshCw,
  Trash2,
  Activity,
  CheckCircle2,
  XCircle,
  Radio,
  Info,
  Clock,
  Loader2,
  X,
} from 'lucide-react';
import { useProjectStore } from '../../../../shared/store/projectStore';
import { useConfirmStore } from '../../../../shared/store/confirmStore';
import { useServerPerfStore, type PerfSlaveNodeItem } from '../../store/serverPerfStore';

export function PerfSlaveNodeList() {
  const currentProjectId = useProjectStore((s) => s.currentProjectId);
  const confirm = useConfirmStore((s) => s.confirm);
  const { slaveNodes, loadSlaveNodes, pingSlaveNode } = useServerPerfStore();

  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [pingingMap, setPingingMap] = useState<Record<number, boolean>>({});
  const [testingPing, setTestingPing] = useState(false);
  const [testPingResult, setTestPingResult] = useState<{ ok: boolean; msg: string } | null>(null);
  const [guideTooltipOpen, setGuideTooltipOpen] = useState(false);

  // 表单状态
  const [name, setName] = useState('');
  const [host, setHost] = useState('');
  const [port, setPort] = useState(1099);
  const [desc, setDesc] = useState('');

  useEffect(() => {
    loadSlaveNodes(currentProjectId || undefined);
  }, [currentProjectId, loadSlaveNodes]);

  const handlePing = async (node: PerfSlaveNodeItem) => {
    setPingingMap((prev) => ({ ...prev, [node.id]: true }));
    try {
      const ok = await pingSlaveNode(node.id);
      if (ok) {
        toast.success(`节点「${node.name} (${node.host}:${node.port})」TCP 连通探测成功！`);
      } else {
        toast.error(`节点「${node.name} (${node.host}:${node.port})」未连通，请检查网络与 jmeter-server`);
      }
    } finally {
      setPingingMap((prev) => ({ ...prev, [node.id]: false }));
    }
  };

  const handlePingAll = async () => {
    if (slaveNodes.length === 0) return;
    toast.info(`正在测试全部 ${slaveNodes.length} 台从机节点连通性...`);
    for (const node of slaveNodes) {
      await handlePing(node);
    }
  };

  const handleTestPing = async () => {
    if (!host.trim()) {
      toast.error('请先输入节点 IP 地址或域名');
      return;
    }
    setTestingPing(true);
    setTestPingResult(null);
    try {
      const res = await fetch('/api/modules/performance/server/slave-nodes/test-ping', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          host: host.trim(),
          port: Number(port) || 1099,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || '连通性测试接口请求失败');
      }
      if (data.ok) {
        setTestPingResult({ ok: true, msg: `连接成功 (RMI 端口 ${data.port} 畅通)` });
        toast.success(`从机 ${data.host}:${data.port} 连通测试成功！`);
      } else {
        const errDetail = data.error ? ` (${data.error})` : '';
        setTestPingResult({ ok: false, msg: `连接失败: 无法连通 RMI 端口 ${data.port}${errDetail}` });
        toast.error(`从机 ${data.host}:${data.port} 连通测试失败`);
      }
    } catch (err: any) {
      setTestPingResult({ ok: false, msg: `测试异常: ${err.message || '网络错误'}` });
      toast.error(err.message || '连通测试发生错误');
    } finally {
      setTestingPing(false);
    }
  };

  const handleCreate = async () => {
    if (!name.trim()) {
      toast.error('请输入节点名称');
      return;
    }
    if (!host.trim()) {
      toast.error('请输入节点 IP 地址或主机名');
      return;
    }

    try {
      const res = await fetch('/api/modules/performance/server/slave-nodes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_id: currentProjectId,
          name: name.trim(),
          host: host.trim(),
          port: Number(port) || 1099,
          description: desc.trim(),
        }),
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || '创建节点失败');

      if (data.status === 'online') {
        toast.success(`从机节点添加成功，且连通正常 (在线)`);
      } else {
        toast.warning(`从机节点已添加，但当前无法连通 RMI 端口 (离线)`);
      }

      setCreateModalOpen(false);
      setName('');
      setHost('');
      setPort(1099);
      setDesc('');
      setTestPingResult(null);
      await loadSlaveNodes(currentProjectId || undefined);
    } catch (err: any) {
      toast.error(err.message || '添加节点异常');
    }
  };

  const handleDelete = (node: PerfSlaveNodeItem) => {
    confirm({
      title: '删除从机节点',
      message: `确定要删除分布式从机「${node.name} (${node.host}:${node.port})」吗？`,
      variant: 'danger',
      onConfirm: async () => {
        try {
          const res = await fetch(`/api/modules/performance/server/slave-nodes/${node.id}`, {
            method: 'DELETE',
          });
          if (res.ok) {
            toast.success('节点已删除');
            loadSlaveNodes(currentProjectId || undefined);
          } else {
            toast.error('删除节点失败');
          }
        } catch {
          toast.error('删除节点异常');
        }
      },
    });
  };

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
      {/* 顶栏控制条 */}
      <div
        style={{
          padding: '10px 16px',
          borderBottom: '1px solid var(--border)',
          background: 'var(--bg-card)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexShrink: 0,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div
            style={{
              width: 32,
              height: 32,
              borderRadius: 6,
              background: 'rgba(59, 130, 246, 0.1)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: 'var(--accent)',
            }}
          >
            <Server size={18} />
          </div>
          <div>
            <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)' }}>
              JMeter 分布式从机节点池 (Slave Nodes)
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: 6 }}>
              <span>维护远程执行从机集群，压测时由服务器（Master）通过 RMI 1099 端口统筹下发施压指令</span>
              {/* 从机准备指引 感叹号 Tooltip */}
              <div style={{ position: 'relative', display: 'inline-flex', alignItems: 'center' }}>
                <span
                  onMouseEnter={() => setGuideTooltipOpen(true)}
                  onMouseLeave={() => setGuideTooltipOpen(false)}
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    cursor: 'pointer',
                    color: 'var(--accent)',
                  }}
                  title="查看从机准备指引"
                >
                  <Info size={13} />
                </span>

                {guideTooltipOpen && (
                  <div
                    onMouseEnter={() => setGuideTooltipOpen(true)}
                    onMouseLeave={() => setGuideTooltipOpen(false)}
                    style={{
                      position: 'absolute',
                      top: '100%',
                      left: 0,
                      marginTop: 6,
                      width: 360,
                      padding: '12px 14px',
                      borderRadius: 8,
                      background: 'var(--bg-card)',
                      border: '1px solid var(--border)',
                      boxShadow: '0 10px 25px rgba(0,0,0,0.25)',
                      fontSize: 12,
                      lineHeight: 1.6,
                      color: 'var(--text-primary)',
                      zIndex: 50,
                      textAlign: 'left',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 600, color: 'var(--accent)', marginBottom: 6 }}>
                      <Info size={14} />
                      JMeter 分布式 Slave 准备指引
                    </div>
                    <div style={{ color: 'var(--text-secondary)', fontSize: 11 }}>
                      <p style={{ margin: '0 0 6px 0' }}>
                        1. <strong>版本要求</strong>：从机需安装与 Master 一致的 JMeter 和 Java 运行环境。
                      </p>
                      <p style={{ margin: '0 0 6px 0' }}>
                        2. <strong>关闭 SSL</strong>：编辑从机 <code>bin/jmeter.properties</code>，设置：
                        <br />
                        <code style={{ background: 'var(--bg-base)', padding: '2px 6px', borderRadius: 4, display: 'inline-block', marginTop: 2 }}>
                          server.rmi.ssl.disable=true
                        </code>
                      </p>
                      <p style={{ margin: 0 }}>
                        3. <strong>启动服务</strong>：在从机 <code>bin/</code> 目录下执行 <code>./jmeter-server</code>（默认端口 1099）。
                      </p>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <button
            onClick={handlePingAll}
            disabled={slaveNodes.length === 0}
            style={{
              padding: '6px 12px',
              borderRadius: 6,
              border: '1px solid var(--border)',
              background: 'var(--bg-base)',
              color: 'var(--text-primary)',
              fontSize: 12,
              cursor: slaveNodes.length === 0 ? 'not-allowed' : 'pointer',
              display: 'inline-flex',
              alignItems: 'center',
              gap: 5,
            }}
          >
            <Activity size={13} color="var(--accent)" />
            一键测试连通
          </button>

          <button
            onClick={() => loadSlaveNodes(currentProjectId || undefined)}
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
            <RefreshCw size={13} />
            刷新
          </button>

          <button
            onClick={() => setCreateModalOpen(true)}
            style={{
              padding: '6px 14px',
              borderRadius: 6,
              border: 'none',
              background: 'var(--accent)',
              color: '#fff',
              fontSize: 12,
              fontWeight: 500,
              cursor: 'pointer',
              display: 'inline-flex',
              alignItems: 'center',
              gap: 5,
            }}
          >
            <Plus size={14} />
            添加从机节点
          </button>
        </div>
      </div>

      {/* 列表区域 */}
      <div style={{ flex: 1, overflow: 'auto', padding: 16 }}>
        {slaveNodes.length === 0 ? (
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              height: '60%',
              color: 'var(--text-muted)',
              gap: 12,
            }}
          >
            <Server size={42} strokeWidth={1.2} style={{ opacity: 0.5 }} />
            <div style={{ fontSize: 13 }}>暂无分布式 Slave 节点</div>
            <button
              onClick={() => setCreateModalOpen(true)}
              style={{
                padding: '6px 14px',
                borderRadius: 6,
                border: '1px solid var(--border)',
                background: 'var(--bg-card)',
                color: 'var(--text-primary)',
                fontSize: 12,
                cursor: 'pointer',
                display: 'inline-flex',
                alignItems: 'center',
                gap: 5,
              }}
            >
              <Plus size={13} /> 立即录入第一台从机
            </button>
          </div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 14 }}>
            {slaveNodes.map((node) => {
              const isPinging = pingingMap[node.id];
              return (
                <div
                  key={node.id}
                  style={{
                    background: 'var(--bg-card)',
                    borderRadius: 8,
                    border: '1px solid var(--border)',
                    padding: 16,
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 12,
                    boxShadow: '0 2px 8px rgba(0,0,0,0.03)',
                  }}
                >
                  {/* 卡片头部 */}
                  <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
                    <div>
                      <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: 6 }}>
                        <Radio size={14} color="var(--accent)" />
                        {node.name}
                      </div>
                      <div style={{ fontSize: 12, fontFamily: 'monospace', color: 'var(--text-secondary)', marginTop: 2 }}>
                        {node.host}:{node.port}
                      </div>
                    </div>

                    <div
                      style={{
                        fontSize: 11,
                        padding: '2px 8px',
                        borderRadius: 999,
                        fontWeight: 600,
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: 4,
                        background:
                          node.status === 'online'
                            ? 'rgba(16, 185, 129, 0.12)'
                            : 'rgba(239, 68, 68, 0.12)',
                        color: node.status === 'online' ? '#10b981' : '#ef4444',
                      }}
                    >
                      {node.status === 'online' ? <CheckCircle2 size={11} /> : <XCircle size={11} />}
                      {node.status === 'online' ? '在线' : '离线'}
                    </div>
                  </div>

                  {/* 心跳时间与描述 */}
                  {node.last_heartbeat_at && (
                    <div style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, color: 'var(--text-muted)' }}>
                      <Clock size={11} />
                      上次心跳: {new Date(node.last_heartbeat_at).toLocaleTimeString()}
                    </div>
                  )}

                  {node.description && (
                    <div style={{ fontSize: 12, color: 'var(--text-muted)', background: 'var(--bg-base)', padding: '6px 8px', borderRadius: 4 }}>
                      {node.description}
                    </div>
                  )}

                  {/* 卡片底部操作栏 */}
                  <div
                    style={{
                      marginTop: 'auto',
                      paddingTop: 10,
                      borderTop: '1px solid var(--border)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'flex-end',
                      gap: 8,
                    }}
                  >
                    <button
                      onClick={() => handlePing(node)}
                      disabled={isPinging}
                      style={{
                        padding: '4px 10px',
                        borderRadius: 4,
                        border: '1px solid var(--border)',
                        background: 'var(--bg-base)',
                        color: 'var(--text-primary)',
                        fontSize: 11,
                        cursor: isPinging ? 'not-allowed' : 'pointer',
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: 4,
                      }}
                    >
                      {isPinging ? <Loader2 size={11} className="animate-spin" /> : <Activity size={11} color="var(--accent)" />}
                      {isPinging ? '探测中...' : '心跳探测'}
                    </button>

                    <button
                      onClick={() => handleDelete(node)}
                      style={{
                        padding: '4px 10px',
                        borderRadius: 4,
                        border: '1px solid var(--border)',
                        background: 'var(--bg-base)',
                        color: '#ef4444',
                        fontSize: 11,
                        cursor: 'pointer',
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: 4,
                      }}
                    >
                      <Trash2 size={11} />
                      删除
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* 添加节点弹窗 */}
      {createModalOpen && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 1000,
            background: 'rgba(0,0,0,0.6)',
            backdropFilter: 'blur(3px)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: 24,
          }}
          onClick={(e) => {
            if (e.target === e.currentTarget) setCreateModalOpen(false);
          }}
        >
          <div
            style={{
              width: '92%',
              maxWidth: 480,
              background: 'var(--bg-card)',
              borderRadius: 10,
              border: '1px solid var(--border)',
              boxShadow: '0 20px 40px rgba(0,0,0,0.3)',
              overflow: 'hidden',
              display: 'flex',
              flexDirection: 'column',
            }}
          >
            <div
              style={{
                padding: '14px 20px',
                borderBottom: '1px solid var(--border)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
              }}
            >
              <div style={{ fontSize: 15, fontWeight: 600, color: 'var(--text-primary)' }}>
                添加 JMeter 从机节点
              </div>
              <button
                onClick={() => setCreateModalOpen(false)}
                style={{ border: 'none', background: 'transparent', cursor: 'pointer', color: 'var(--text-muted)' }}
              >
                <X size={16} />
              </button>
            </div>

            <div style={{ padding: 20, display: 'flex', flexDirection: 'column', gap: 14 }}>
              <div>
                <label style={{ fontSize: 12, color: 'var(--text-secondary)', display: 'block', marginBottom: 4 }}>
                  节点名称 <span style={{ color: '#ef4444' }}>*</span>
                </label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="例如: 华东从机-01 / Slave-Node-1"
                  style={{
                    width: '100%',
                    height: 32,
                    padding: '0 10px',
                    borderRadius: 4,
                    border: '1px solid var(--border)',
                    background: 'var(--bg-base)',
                    color: 'var(--text-primary)',
                    fontSize: 12,
                  }}
                />
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 100px', gap: 10 }}>
                <div>
                  <label style={{ fontSize: 12, color: 'var(--text-secondary)', display: 'block', marginBottom: 4 }}>
                    IP 地址 / 域名 <span style={{ color: '#ef4444' }}>*</span>
                  </label>
                  <input
                    type="text"
                    value={host}
                    onChange={(e) => setHost(e.target.value)}
                    placeholder="例如: 192.168.1.101"
                    style={{
                      width: '100%',
                      height: 32,
                      padding: '0 10px',
                      borderRadius: 4,
                      border: '1px solid var(--border)',
                      background: 'var(--bg-base)',
                      color: 'var(--text-primary)',
                      fontFamily: 'monospace',
                      fontSize: 12,
                    }}
                  />
                </div>

                <div>
                  <label style={{ fontSize: 12, color: 'var(--text-secondary)', display: 'block', marginBottom: 4 }}>
                    RMI 端口
                  </label>
                  <input
                    type="number"
                    value={port}
                    onChange={(e) => setPort(Number(e.target.value))}
                    style={{
                      width: '100%',
                      height: 32,
                      padding: '0 8px',
                      borderRadius: 4,
                      border: '1px solid var(--border)',
                      background: 'var(--bg-base)',
                      color: 'var(--text-primary)',
                      fontFamily: 'monospace',
                      fontSize: 12,
                    }}
                  />
                </div>
              </div>

              <div>
                <label style={{ fontSize: 12, color: 'var(--text-secondary)', display: 'block', marginBottom: 4 }}>
                  备注说明 (可选)
                </label>
                <input
                  type="text"
                  value={desc}
                  onChange={(e) => setDesc(e.target.value)}
                  placeholder="例如: 仅限内网测试集群，最大支持 500 并发"
                  style={{
                    width: '100%',
                    height: 32,
                    padding: '0 10px',
                    borderRadius: 4,
                    border: '1px solid var(--border)',
                    background: 'var(--bg-base)',
                    color: 'var(--text-primary)',
                    fontSize: 12,
                  }}
                />
              </div>

              {/* 连通性测试即时反馈条 */}
              {testPingResult && (
                <div
                  style={{
                    padding: '8px 12px',
                    borderRadius: 6,
                    fontSize: 12,
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    background: testPingResult.ok ? 'rgba(34, 197, 94, 0.1)' : 'rgba(239, 68, 68, 0.1)',
                    border: `1px solid ${testPingResult.ok ? 'rgba(34, 197, 94, 0.3)' : 'rgba(239, 68, 68, 0.3)'}`,
                    color: testPingResult.ok ? 'var(--success, #22c55e)' : '#ef4444',
                  }}
                >
                  {testPingResult.ok ? <CheckCircle2 size={15} /> : <XCircle size={15} />}
                  <span>{testPingResult.msg}</span>
                </div>
              )}
            </div>

            <div
              style={{
                padding: '12px 20px',
                borderTop: '1px solid var(--border)',
                background: 'var(--bg-base)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: 10,
              }}
            >
              <div>
                <button
                  type="button"
                  onClick={handleTestPing}
                  disabled={testingPing || !host.trim()}
                  style={{
                    padding: '6px 14px',
                    borderRadius: 6,
                    border: '1px solid var(--border)',
                    background: 'var(--bg-card)',
                    color: 'var(--text-primary)',
                    fontSize: 12,
                    cursor: testingPing || !host.trim() ? 'not-allowed' : 'pointer',
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 6,
                  }}
                >
                  {testingPing ? (
                    <Loader2 size={13} className="animate-spin" />
                  ) : (
                    <Activity size={13} color="var(--accent)" />
                  )}
                  {testingPing ? '正在测试...' : '测试连通'}
                </button>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <button
                  onClick={() => setCreateModalOpen(false)}
                  style={{
                    padding: '6px 14px',
                    borderRadius: 6,
                    border: '1px solid var(--border)',
                    background: 'var(--bg-card)',
                    color: 'var(--text-primary)',
                    fontSize: 12,
                    cursor: 'pointer',
                  }}
                >
                  取消
                </button>
                <button
                  onClick={handleCreate}
                  style={{
                    padding: '6px 16px',
                    borderRadius: 6,
                    border: 'none',
                    background: 'var(--accent)',
                    color: '#fff',
                    fontSize: 12,
                    fontWeight: 500,
                    cursor: 'pointer',
                  }}
                >
                  保存并连接
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
