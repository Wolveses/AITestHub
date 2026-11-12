import { useEffect, useState } from 'react';
import {
  X,
  Copy,
  Check,
  Terminal,
  Tag,
  FileCode,
  Play,
  BarChart2,
  Edit3,
  Calendar,
  Layers,
} from 'lucide-react';
import { toast } from 'sonner';
import { buildJMeterCommand } from './commandPreview';

interface PerfTaskDetailModalProps {
  isOpen: boolean;
  taskId: number | null;
  onClose: () => void;
  onEdit: (taskId: number) => void;
  onRun: (task: any) => void;
  onOpenReport?: (runId: number) => void;
}

export function PerfTaskDetailModal({
  isOpen,
  taskId,
  onClose,
  onEdit,
  onRun,
  onOpenReport,
}: PerfTaskDetailModalProps) {
  const [loading, setLoading] = useState(false);
  const [task, setTask] = useState<any>(null);
  const [baselineProps, setBaselineProps] = useState<{ name: string; default_value: string }[]>([]);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!isOpen || !taskId) {
      setTask(null);
      setBaselineProps([]);
      return;
    }
    setLoading(true);
    fetch(`/api/modules/performance/server/tasks/${taskId}`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data) => {
        setTask(data);
        const scriptIds = (data.scripts || []).map((s: any) => s.script_id).join(',');
        if (scriptIds) {
          fetch(`/api/modules/performance/server/scripts/batch/properties?script_ids=${scriptIds}`)
            .then((res) => (res.ok ? res.json() : { properties: [] }))
            .then((pData) => setBaselineProps(pData.properties || []))
            .catch(() => setBaselineProps([]));
        } else {
          setBaselineProps([]);
        }
      })
      .catch((err) => {
        console.error('加载任务详情失败', err);
        toast.error('加载任务详情失败: ' + err.message);
      })
      .finally(() => {
        setLoading(false);
      });
  }, [isOpen, taskId]);

  if (!isOpen) return null;

  // 合并全部参数：脚本动态嗅探参数 + 任务自定义参数，确保无任何遗漏
  const allPropertiesList: { name: string; value: string; isCustom: boolean; defaultValue?: string }[] = [];
  const processedKeys = new Set<string>();

  // 1. 优先包含脚本中提取的全部动态参数
  baselineProps.forEach((p) => {
    const val =
      task?.custom_properties?.[p.name] !== undefined
        ? String(task.custom_properties[p.name])
        : (p.default_value ?? '');
    allPropertiesList.push({
      name: p.name,
      value: val,
      isCustom: false,
      defaultValue: p.default_value,
    });
    processedKeys.add(p.name);
  });

  // 2. 追加用户额外添加的自定义 -J 参数
  Object.entries(task?.custom_properties || {}).forEach(([k, v]) => {
    if (!processedKeys.has(k)) {
      allPropertiesList.push({
        name: k,
        value: String(v ?? ''),
        isCustom: true,
      });
      processedKeys.add(k);
    }
  });

  const effectiveProps: Record<string, string> = {};
  allPropertiesList.forEach((item) => {
    effectiveProps[item.name] = item.value;
  });

  const firstScriptName = task?.scripts?.[0]?.script_name || '';
  const commandPreview = task
    ? buildJMeterCommand({
        engineType: task.engine_type || 'jmeter_cli',
        execMode: task.exec_mode || 'local',
        slaveHosts: task.slave_hosts || '',
        scriptName: firstScriptName,
        customProperties: effectiveProps,
      })
    : '';

  const handleCopy = () => {
    if (!commandPreview) return;
    navigator.clipboard.writeText(commandPreview);
    setCopied(true);
    toast.success('命令已复制到剪贴板');
    setTimeout(() => setCopied(false), 2000);
  };

  const statusColorMap: Record<string, { bg: string; text: string; label: string }> = {
    running: { bg: 'rgba(59,130,246,0.12)', text: '#3b82f6', label: '运行中' },
    completed: { bg: 'rgba(16,185,129,0.12)', text: '#10b981', label: '已完成' },
    failed: { bg: 'rgba(239,68,68,0.12)', text: '#ef4444', label: '执行失败' },
    stopped: { bg: 'rgba(245,158,11,0.12)', text: '#f59e0b', label: '已停止' },
    idle: { bg: 'var(--bg-base)', text: 'var(--text-muted)', label: '空闲' },
  };

  const statusStyle = statusColorMap[task?.last_status || 'idle'] || statusColorMap.idle;

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
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <Layers size={18} color="var(--accent)" />
            <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, color: 'var(--text-primary)' }}>
              性能测试任务详情
            </h3>
            {task && (
              <span
                style={{
                  fontSize: 11,
                  padding: '2px 8px',
                  borderRadius: 4,
                  fontWeight: 600,
                  background: statusStyle.bg,
                  color: statusStyle.text,
                }}
              >
                {statusStyle.label}
              </span>
            )}
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

        {/* Content */}
        <div style={{ padding: '18px 22px', overflowY: 'auto', flex: 1, display: 'flex', flexDirection: 'column', gap: 16 }}>
          {loading ? (
            <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
              正在加载任务详情...
            </div>
          ) : !task ? (
            <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
              暂未获取到任务信息
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
                  <span style={{ color: 'var(--text-muted)' }}>任务名称：</span>
                  <strong style={{ color: 'var(--text-primary)', marginLeft: 4 }}>{task.name}</strong>
                </div>
                <div>
                  <span style={{ color: 'var(--text-muted)' }}>任务 ID：</span>
                  <span style={{ color: 'var(--text-secondary)', marginLeft: 4 }}>#{task.id}</span>
                </div>
                {task.description && (
                  <div style={{ gridColumn: 'span 2' }}>
                    <span style={{ color: 'var(--text-muted)' }}>任务描述：</span>
                    <span style={{ color: 'var(--text-secondary)', marginLeft: 4 }}>{task.description}</span>
                  </div>
                )}
                <div>
                  <span style={{ color: 'var(--text-muted)' }}>压测引擎：</span>
                  <span
                    style={{
                      marginLeft: 4,
                      fontWeight: 500,
                      color: task.engine_type === 'builtin' ? '#10b981' : '#f59e0b',
                    }}
                  >
                    {task.engine_type === 'builtin' ? '内置 Python 异步' : '本地 JMeter CLI'}
                  </span>
                </div>
                <div>
                  <span style={{ color: 'var(--text-muted)' }}>执行模式：</span>
                  <span style={{ color: 'var(--text-primary)', marginLeft: 4 }}>
                    {task.exec_mode === 'distributed' ? '分布式集群模式' : '本机单机执行'}
                  </span>
                </div>
                {task.exec_mode === 'distributed' && (
                  <div style={{ gridColumn: 'span 2' }}>
                    <span style={{ color: 'var(--text-muted)' }}>从机节点：</span>
                    <span style={{ color: 'var(--accent)', marginLeft: 4 }}>
                      {task.slave_hosts || '未配置'}
                    </span>
                  </div>
                )}
                {task.last_run_at && (
                  <div style={{ gridColumn: 'span 2', display: 'flex', alignItems: 'center', gap: 6 }}>
                    <Calendar size={13} style={{ color: 'var(--text-muted)' }} />
                    <span style={{ color: 'var(--text-muted)' }}>最近运行：</span>
                    <span style={{ color: 'var(--text-secondary)' }}>{task.last_run_at}</span>
                  </div>
                )}
              </div>

              {/* 2. 关联压测脚本 */}
              <div>
                <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 8, display: 'flex', alignItems: 'center', gap: 6 }}>
                  <FileCode size={14} color="var(--accent)" />
                  关联压测脚本 ({task.scripts?.length || 0})
                </div>
                <div
                  style={{
                    border: '1px solid var(--border)',
                    borderRadius: 6,
                    overflow: 'hidden',
                  }}
                >
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                    <thead>
                      <tr style={{ background: 'var(--bg-base)', borderBottom: '1px solid var(--border)', color: 'var(--text-muted)' }}>
                        <th style={{ padding: '8px 12px', textAlign: 'left' }}>脚本名称</th>
                        <th style={{ padding: '8px 12px', textAlign: 'left', width: 90 }}>脚本 ID</th>
                        <th style={{ padding: '8px 12px', textAlign: 'left', width: 90 }}>流量权重</th>
                        <th style={{ padding: '8px 12px', textAlign: 'left', width: 100 }}>步骤/接口数</th>
                      </tr>
                    </thead>
                    <tbody>
                      {task.scripts?.map((sc: any) => {
                        const stepCount = sc.asset_ids?.length || sc.config?.steps?.length || sc.config?.samplers?.length || 0;
                        return (
                          <tr key={sc.script_id} style={{ borderBottom: '1px solid var(--border)' }}>
                            <td style={{ padding: '8px 12px', color: 'var(--text-primary)', fontWeight: 500 }}>
                              {sc.script_name}
                            </td>
                            <td style={{ padding: '8px 12px', color: 'var(--text-muted)' }}>
                              #{sc.script_id}
                            </td>
                            <td style={{ padding: '8px 12px', color: 'var(--accent)' }}>
                              {sc.weight}%
                            </td>
                            <td style={{ padding: '8px 12px', color: 'var(--text-secondary)' }}>
                              {stepCount} 个
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* 3. 脚本动态参数配置 (-J 属性) */}
              <div>
                <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 8, display: 'flex', alignItems: 'center', gap: 6 }}>
                  <Tag size={14} color="var(--accent)" />
                  脚本动态参数配置 (-J 属性)
                  <span style={{ fontSize: 11, fontWeight: 400, color: 'var(--text-muted)' }}>
                    (共 {allPropertiesList.length} 个参数)
                  </span>
                </div>
                {allPropertiesList.length === 0 ? (
                  <div style={{ padding: '12px', border: '1px dashed var(--border)', borderRadius: 6, color: 'var(--text-muted)', fontSize: 12, textAlign: 'center' }}>
                    未配置自定义动态参数，执行时将使用脚本内默认属性值。
                  </div>
                ) : (
                  <div
                    style={{
                      display: 'grid',
                      gridTemplateColumns: 'repeat(auto-fill, minmax(210px, 1fr))',
                      gap: 8,
                      maxHeight: 200,
                      overflowY: 'auto',
                    }}
                  >
                    {allPropertiesList.map((item) => (
                      <div
                        key={item.name}
                        style={{
                          background: 'var(--bg-base)',
                          border: '1px solid var(--border)',
                          borderRadius: 6,
                          padding: '6px 10px',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                          gap: 6,
                          fontSize: 12,
                        }}
                      >
                        <span style={{ fontWeight: 600, color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={item.name}>
                          {item.name}
                        </span>
                        <span
                          style={{
                            background: item.value !== '' ? 'rgba(59,130,246,0.1)' : 'var(--bg-card)',
                            color: item.value !== '' ? 'var(--accent)' : 'var(--text-muted)',
                            border: item.value !== '' ? 'none' : '1px dashed var(--border)',
                            padding: '1px 6px',
                            borderRadius: 4,
                            fontWeight: 500,
                            maxWidth: '50%',
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap',
                            fontSize: 11,
                          }}
                          title={item.value !== '' ? item.value : (item.defaultValue ? `默认值: ${item.defaultValue}` : '未设置/空值')}
                        >
                          {item.value !== '' ? item.value : '(空值)'}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* 4. 实时执行命令预览 */}
              <div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: 6 }}>
                    <Terminal size={14} color="var(--accent)" />
                    调度执行命令预览
                  </div>
                  <button
                    onClick={handleCopy}
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
                    padding: '10px 12px',
                    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
                    fontSize: 11,
                    color: '#38bdf8',
                    lineHeight: 1.5,
                    wordBreak: 'break-all',
                    maxHeight: 110,
                    overflowY: 'auto',
                  }}
                >
                  {commandPreview}
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>
                  启动压测时将执行上述命令，并通过动态参数 <code>-J</code> 实时透传覆盖脚本配置。
                </div>
              </div>
            </>
          )}
        </div>

        {/* Footer Actions */}
        <div
          style={{
            padding: '12px 20px',
            borderTop: '1px solid var(--border)',
            background: 'var(--bg-base)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <div style={{ display: 'flex', gap: 8 }}>
            {task && task.last_run_id && onOpenReport && (
              <button
                type="button"
                onClick={() => onOpenReport(task.last_run_id)}
                style={{
                  height: 30,
                  padding: '0 12px',
                  borderRadius: 5,
                  border: '1px solid var(--border)',
                  background: 'var(--bg-card)',
                  color: 'var(--text-primary)',
                  fontSize: 12,
                  display: 'flex',
                  alignItems: 'center',
                  gap: 5,
                  cursor: 'pointer',
                }}
              >
                <BarChart2 size={13} color="var(--accent)" />
                查看最新报告
              </button>
            )}
          </div>

          <div style={{ display: 'flex', gap: 10 }}>
            {task && (
              <button
                type="button"
                onClick={() => {
                  onClose();
                  onEdit(task.id);
                }}
                style={{
                  height: 30,
                  padding: '0 14px',
                  borderRadius: 5,
                  border: '1px solid var(--border)',
                  background: 'var(--bg-card)',
                  color: 'var(--text-primary)',
                  fontSize: 12,
                  display: 'flex',
                  alignItems: 'center',
                  gap: 5,
                  cursor: 'pointer',
                  fontWeight: 500,
                }}
              >
                <Edit3 size={13} />
                编辑任务
              </button>
            )}

            {task && (
              <button
                type="button"
                onClick={() => {
                  onClose();
                  onRun(task);
                }}
                disabled={task.last_status === 'running'}
                style={{
                  height: 30,
                  padding: '0 14px',
                  borderRadius: 5,
                  border: 'none',
                  background: 'var(--accent)',
                  color: '#fff',
                  fontSize: 12,
                  display: 'flex',
                  alignItems: 'center',
                  gap: 5,
                  cursor: task.last_status === 'running' ? 'not-allowed' : 'pointer',
                  opacity: task.last_status === 'running' ? 0.6 : 1,
                  fontWeight: 500,
                }}
              >
                <Play size={13} />
                立即执行
              </button>
            )}

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
              关闭
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
