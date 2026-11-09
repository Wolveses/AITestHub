import { useState, useEffect, useRef } from 'react';
import {
  Server,
  Cpu,
  HardDrive,
  Activity,
  RefreshCw,
  Search,
  Layers,
  Clock,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  TrendingUp,
  Settings,
} from 'lucide-react';
import * as echarts from 'echarts';
import { PrometheusConfigModal } from './PrometheusConfigModal';

interface HostItem {
  job: string;
  instance: string;
  online: boolean;
}

interface HostOverview {
  job: string;
  cpu_percent: number;
  mem_total_gb: number;
  mem_used_gb: number;
  mem_percent: number;
  disk_total_gb: number;
  disk_used_gb: number;
  disk_percent: number;
  load1: number;
  cpu_cores: number;
}

interface ContainerStat {
  name: string;
  short_name: string;
  cpu_max: number;
  cpu_avg: number;
  cpu_current: number;
  rss_max_mb: number;
  rss_avg_mb: number;
  rss_current_mb: number;
  usage_max_mb: number;
  usage_avg_mb: number;
  usage_current_mb: number;
}

export function SystemMonitorPanel() {
  const [hosts, setHosts] = useState<HostItem[]>([]);
  const [selectedHost, setSelectedHost] = useState<string>('cloud_8.130');
  const [overview, setOverview] = useState<HostOverview | null>(null);
  const [containers, setContainers] = useState<ContainerStat[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [searchTerm, setSearchTerm] = useState<string>('');
  const [timeRange, setTimeRange] = useState<number>(3600); // 1h in seconds
  const [autoRefresh, setAutoRefresh] = useState<boolean>(true);
  const [sortField, setSortField] = useState<keyof ContainerStat>('cpu_max');
  const [sortAsc, setSortAsc] = useState<boolean>(false);
  const [configModalOpen, setConfigModalOpen] = useState<boolean>(false);
  const [activePromUrl, setActivePromUrl] = useState<string>('');

  // 折线图
  const chartRef = useRef<HTMLDivElement>(null);
  const chartInstance = useRef<echarts.ECharts | null>(null);

  // 获取主机列表与配置信息
  const loadHosts = () => {
    fetch('/api/modules/performance/system_monitor/hosts')
      .then((res) => res.json())
      .then((data: HostItem[]) => {
        if (Array.isArray(data) && data.length > 0) {
          setHosts(data);
          const hasSelected = data.some((h) => h.job === selectedHost);
          if (!hasSelected) {
            setSelectedHost(data[0].job);
          }
        }
      })
      .catch((err) => console.error('加载监控主机列表失败:', err));

    fetch('/api/modules/performance/system_monitor/config')
      .then((res) => res.json())
      .then((cfg) => {
        if (cfg?.active_url) {
          setActivePromUrl(cfg.active_url);
        }
      })
      .catch(() => {});
  };

  useEffect(() => {
    loadHosts();
  }, []);

  // 加载所选主机的概览与容器详情
  const fetchData = async () => {
    if (!selectedHost) return;
    setLoading(true);
    try {
      const now = Math.floor(Date.now() / 1000);
      const start = now - timeRange;

      const [overviewRes, containersRes, trendRes] = await Promise.all([
        fetch(`/api/modules/performance/system_monitor/overview?job=${encodeURIComponent(selectedHost)}`).then((r) => r.json()),
        fetch(`/api/modules/performance/system_monitor/containers?job=${encodeURIComponent(selectedHost)}&start=${start}&end=${now}&step=60`).then((r) => r.json()),
        fetch(`/api/modules/performance/system_monitor/trend?job=${encodeURIComponent(selectedHost)}&metric_type=cpu&start=${start}&end=${now}&step=60`).then((r) => r.json()),
      ]);

      setOverview(overviewRes);
      if (Array.isArray(containersRes)) {
        setContainers(containersRes);
      }

      // 渲染 ECharts 趋势图
      if (chartInstance.current && Array.isArray(trendRes)) {
        chartInstance.current.setOption({
          title: {
            text: '宿主机 CPU 使用率走势 (%)',
            textStyle: { fontSize: 13, color: 'var(--text-primary)' },
          },
          tooltip: {
            trigger: 'axis',
            formatter: (params: any) => {
              if (!params || !params[0]) return '';
              const date = new Date(params[0].value[0]);
              const timeStr = date.toLocaleTimeString();
              return `${timeStr}<br/>CPU: <b>${params[0].value[1]}%</b>`;
            },
          },
          grid: { top: 35, right: 20, bottom: 25, left: 45 },
          xAxis: {
            type: 'time',
            axisLabel: { color: 'var(--text-secondary)', fontSize: 11 },
            splitLine: { show: false },
          },
          yAxis: {
            type: 'value',
            min: 0,
            max: 100,
            axisLabel: { color: 'var(--text-secondary)', fontSize: 11, formatter: '{value}%' },
            splitLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } },
          },
          series: [
            {
              name: 'CPU 使用率',
              type: 'line',
              smooth: true,
              showSymbol: false,
              data: trendRes,
              itemStyle: { color: '#3b82f6' },
              areaStyle: {
                color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                  { offset: 0, color: 'rgba(59, 130, 246, 0.35)' },
                  { offset: 1, color: 'rgba(59, 130, 246, 0.02)' },
                ]),
              },
            },
          ],
        });
      }
    } catch (err) {
      console.error('获取监控数据失败:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, [selectedHost, timeRange]);

  // 初始化图表实例
  useEffect(() => {
    if (chartRef.current) {
      chartInstance.current = echarts.init(chartRef.current);
      const handleResize = () => chartInstance.current?.resize();
      window.addEventListener('resize', handleResize);
      return () => {
        window.removeEventListener('resize', handleResize);
        chartInstance.current?.dispose();
      };
    }
  }, []);

  // 自动刷新定时器 (15s)
  useEffect(() => {
    if (!autoRefresh) return;
    const interval = setInterval(fetchData, 15000);
    return () => clearInterval(interval);
  }, [autoRefresh, selectedHost, timeRange]);

  // 排序与过滤
  const handleSort = (field: keyof ContainerStat) => {
    if (sortField === field) {
      setSortAsc(!sortAsc);
    } else {
      setSortField(field);
      setSortAsc(false); // 默认降序（从大到小），看高资源占用更自然
    }
  };

  // 渲染表头排序指示图标
  const renderSortIcon = (field: keyof ContainerStat) => {
    if (sortField !== field) {
      return <ArrowUpDown size={12} style={{ opacity: 0.35 }} />;
    }
    return sortAsc ? (
      <ArrowUp size={13} style={{ color: 'var(--accent)', strokeWidth: 2.5 }} />
    ) : (
      <ArrowDown size={13} style={{ color: 'var(--accent)', strokeWidth: 2.5 }} />
    );
  };

  const filteredContainers = containers
    .filter((c) => c.name.toLowerCase().includes(searchTerm.toLowerCase()) || c.short_name.toLowerCase().includes(searchTerm.toLowerCase()))
    .sort((a, b) => {
      const valA = (a[sortField] as number) ?? 0;
      const valB = (b[sortField] as number) ?? 0;
      return sortAsc ? valA - valB : valB - valA;
    });

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden', padding: 16, gap: 16 }}>
      {/* 顶部控制栏 */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          background: 'var(--bg-card)',
          border: '1px solid var(--border)',
          borderRadius: 8,
          padding: '10px 16px',
          gap: 12,
          flexWrap: 'wrap',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, color: 'var(--text-secondary)', fontSize: 13, fontWeight: 500 }}>
            <Server size={16} />
            <span>监控主机:</span>
          </div>

          <select
            value={selectedHost}
            onChange={(e) => setSelectedHost(e.target.value)}
            style={{
              background: 'var(--bg-base)',
              color: 'var(--text-primary)',
              border: '1px solid var(--border)',
              borderRadius: 6,
              padding: '5px 12px',
              fontSize: 13,
              cursor: 'pointer',
              outline: 'none',
              minWidth: 160,
            }}
          >
            {hosts.map((h) => (
              <option key={h.job} value={h.job}>
                {h.job} ({h.instance}) {h.online ? '🟢' : '⚪'}
              </option>
            ))}
          </select>

          {/* 时间段切换 */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginLeft: 8 }}>
            <Clock size={15} color="var(--text-secondary)" />
            <select
              value={timeRange}
              onChange={(e) => setTimeRange(Number(e.target.value))}
              style={{
                background: 'var(--bg-base)',
                color: 'var(--text-primary)',
                border: '1px solid var(--border)',
                borderRadius: 6,
                padding: '5px 10px',
                fontSize: 13,
                cursor: 'pointer',
                outline: 'none',
              }}
            >
              <option value={900}>最近 15 分钟</option>
              <option value={3600}>最近 1 小时</option>
              <option value={21600}>最近 6 小时</option>
              <option value={86400}>最近 24 小时</option>
              <option value={259200}>最近 3 天</option>
            </select>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <button
            onClick={() => setConfigModalOpen(true)}
            title="配置 Prometheus 主机地址"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 5,
              background: 'rgba(255, 255, 255, 0.05)',
              border: '1px solid var(--border)',
              borderRadius: 6,
              color: 'var(--text-primary)',
              padding: '6px 12px',
              fontSize: 12,
              cursor: 'pointer',
              transition: 'all 0.15s ease',
            }}
          >
            <Settings size={13} color="var(--accent)" />
            <span>配置数据源</span>
            {activePromUrl && (
              <span style={{ fontSize: 10, color: 'var(--text-muted)', maxWidth: 140, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                ({activePromUrl.replace(/^https?:\/\//, '')})
              </span>
            )}
          </button>

          <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--text-secondary)', cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
              style={{ cursor: 'pointer' }}
            />
            <span>自动刷新 (15s)</span>
          </label>

          <button
            onClick={fetchData}
            disabled={loading}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 5,
              background: 'var(--accent)',
              color: '#fff',
              border: 'none',
              borderRadius: 6,
              padding: '6px 12px',
              fontSize: 12,
              fontWeight: 500,
              cursor: loading ? 'not-allowed' : 'pointer',
              opacity: loading ? 0.7 : 1,
            }}
          >
            <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
            <span>刷新</span>
          </button>
        </div>
      </div>

      {/* 4 个主机概览状态卡片 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 12 }}>
        <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 8, padding: '12px 16px', display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{ width: 40, height: 40, borderRadius: 8, background: 'rgba(59, 130, 246, 0.12)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#3b82f6' }}>
            <Cpu size={22} />
          </div>
          <div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>主机 CPU 利用率 ({overview?.cpu_cores ?? 1} 核)</div>
            <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text-primary)' }}>{overview?.cpu_percent ?? 0}%</div>
          </div>
        </div>

        <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 8, padding: '12px 16px', display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{ width: 40, height: 40, borderRadius: 8, background: 'rgba(16, 185, 129, 0.12)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#10b981' }}>
            <Activity size={22} />
          </div>
          <div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>主机内存占用 ({overview?.mem_used_gb ?? 0} / {overview?.mem_total_gb ?? 0} GB)</div>
            <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text-primary)' }}>{overview?.mem_percent ?? 0}%</div>
          </div>
        </div>

        <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 8, padding: '12px 16px', display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{ width: 40, height: 40, borderRadius: 8, background: 'rgba(245, 158, 11, 0.12)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#f59e0b' }}>
            <HardDrive size={22} />
          </div>
          <div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>根分区磁盘占用 ({overview?.disk_used_gb ?? 0} / {overview?.disk_total_gb ?? 0} GB)</div>
            <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text-primary)' }}>{overview?.disk_percent ?? 0}%</div>
          </div>
        </div>

        <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 8, padding: '12px 16px', display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{ width: 40, height: 40, borderRadius: 8, background: 'rgba(139, 92, 246, 0.12)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#8b5cf6' }}>
            <TrendingUp size={22} />
          </div>
          <div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>系统 1m 负载</div>
            <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text-primary)' }}>{overview?.load1 ?? 0}</div>
          </div>
        </div>
      </div>

      {/* 折线图与容器列表容器 */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0, gap: 12 }}>
        {/* CPU 实时曲线图卡片 */}
        <div
          style={{
            height: 180,
            background: 'var(--bg-card)',
            border: '1px solid var(--border)',
            borderRadius: 8,
            padding: '12px 16px',
            flexShrink: 0,
          }}
        >
          <div ref={chartRef} style={{ width: '100%', height: '100%' }} />
        </div>

        {/* Docker 容器列表卡片 */}
        <div
          style={{
            flex: 1,
            background: 'var(--bg-card)',
            border: '1px solid var(--border)',
            borderRadius: 8,
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden',
          }}
        >
          {/* 容器列表工具栏 */}
          <div
            style={{
              padding: '10px 16px',
              borderBottom: '1px solid var(--border)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 12,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Layers size={16} color="var(--accent)" />
              <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>
                Docker 容器服务性能排行 ({filteredContainers.length} 个服务)
              </span>
            </div>

            <div style={{ position: 'relative', width: 220 }}>
              <Search size={14} style={{ position: 'absolute', left: 8, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
              <input
                type="text"
                placeholder="搜索容器服务名称..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                style={{
                  width: '100%',
                  background: 'var(--bg-base)',
                  border: '1px solid var(--border)',
                  borderRadius: 6,
                  padding: '5px 8px 5px 28px',
                  fontSize: 12,
                  color: 'var(--text-primary)',
                  outline: 'none',
                }}
              />
            </div>
          </div>

          {/* 表格 */}
          <div style={{ flex: 1, overflowY: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: 12 }}>
              <thead style={{ position: 'sticky', top: 0, background: 'var(--bg-base)', zIndex: 1, borderBottom: '1px solid var(--border)' }}>
                <tr>
                  <th
                    onClick={() => handleSort('short_name')}
                    style={{
                      padding: '8px 12px',
                      color: sortField === 'short_name' ? 'var(--accent)' : 'var(--text-secondary)',
                      fontWeight: 600,
                      cursor: 'pointer',
                      userSelect: 'none',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                      <span>容器服务</span>
                      {renderSortIcon('short_name')}
                    </div>
                  </th>
                  <th
                    onClick={() => handleSort('cpu_max')}
                    style={{
                      padding: '8px 12px',
                      color: sortField === 'cpu_max' ? 'var(--accent)' : 'var(--text-secondary)',
                      fontWeight: 600,
                      cursor: 'pointer',
                      userSelect: 'none',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                      <span>CPU 最大值</span>
                      {renderSortIcon('cpu_max')}
                    </div>
                  </th>
                  <th
                    onClick={() => handleSort('cpu_avg')}
                    style={{
                      padding: '8px 12px',
                      color: sortField === 'cpu_avg' ? 'var(--accent)' : 'var(--text-secondary)',
                      fontWeight: 600,
                      cursor: 'pointer',
                      userSelect: 'none',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                      <span>CPU 均值</span>
                      {renderSortIcon('cpu_avg')}
                    </div>
                  </th>
                  <th
                    onClick={() => handleSort('cpu_current')}
                    style={{
                      padding: '8px 12px',
                      color: sortField === 'cpu_current' ? 'var(--accent)' : 'var(--text-secondary)',
                      fontWeight: 600,
                      cursor: 'pointer',
                      userSelect: 'none',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                      <span>CPU 当前</span>
                      {renderSortIcon('cpu_current')}
                    </div>
                  </th>
                  <th
                    onClick={() => handleSort('rss_max_mb')}
                    style={{
                      padding: '8px 12px',
                      color: sortField === 'rss_max_mb' ? 'var(--accent)' : 'var(--text-secondary)',
                      fontWeight: 600,
                      cursor: 'pointer',
                      userSelect: 'none',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                      <span>内存 RSS 最大 (MB)</span>
                      {renderSortIcon('rss_max_mb')}
                    </div>
                  </th>
                  <th
                    onClick={() => handleSort('rss_avg_mb')}
                    style={{
                      padding: '8px 12px',
                      color: sortField === 'rss_avg_mb' ? 'var(--accent)' : 'var(--text-secondary)',
                      fontWeight: 600,
                      cursor: 'pointer',
                      userSelect: 'none',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                      <span>内存 RSS 均值 (MB)</span>
                      {renderSortIcon('rss_avg_mb')}
                    </div>
                  </th>
                  <th
                    onClick={() => handleSort('usage_max_mb')}
                    style={{
                      padding: '8px 12px',
                      color: sortField === 'usage_max_mb' ? 'var(--accent)' : 'var(--text-secondary)',
                      fontWeight: 600,
                      cursor: 'pointer',
                      userSelect: 'none',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                      <span>内存 Usage 峰值 (MB)</span>
                      {renderSortIcon('usage_max_mb')}
                    </div>
                  </th>
                </tr>
              </thead>
              <tbody>
                {filteredContainers.map((c, index) => {
                  const isHighCpu = c.cpu_max > 50;
                  const isHighMem = c.rss_max_mb > 500;
                  return (
                    <tr
                      key={c.name}
                      style={{
                        borderBottom: '1px solid var(--border)',
                        background: index % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.015)',
                        transition: 'background 0.15s',
                      }}
                    >
                      <td style={{ padding: '8px 12px', color: 'var(--text-primary)' }}>
                        <div style={{ fontWeight: 600, color: 'var(--accent)' }}>{c.short_name}</div>
                        <div style={{ fontSize: 10, color: 'var(--text-muted)', maxWidth: 260, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {c.name}
                        </div>
                      </td>
                      <td style={{ padding: '8px 12px', fontWeight: 600, color: isHighCpu ? '#ef4444' : 'var(--text-primary)' }}>
                        {c.cpu_max}%
                      </td>
                      <td style={{ padding: '8px 12px', color: 'var(--text-primary)' }}>{c.cpu_avg}%</td>
                      <td style={{ padding: '8px 12px', color: 'var(--text-secondary)' }}>{c.cpu_current}%</td>
                      <td style={{ padding: '8px 12px', fontWeight: 600, color: isHighMem ? '#f59e0b' : 'var(--text-primary)' }}>
                        {c.rss_max_mb} MB
                      </td>
                      <td style={{ padding: '8px 12px', color: 'var(--text-primary)' }}>{c.rss_avg_mb} MB</td>
                      <td style={{ padding: '8px 12px', color: 'var(--text-muted)' }}>{c.usage_max_mb} MB</td>
                    </tr>
                  );
                })}
                {filteredContainers.length === 0 && (
                  <tr>
                    <td colSpan={7} style={{ textAlign: 'center', padding: '32px 0', color: 'var(--text-muted)' }}>
                      暂无容器性能数据
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* Prometheus 数据源配置弹窗 */}
      <PrometheusConfigModal
        open={configModalOpen}
        onClose={() => setConfigModalOpen(false)}
        onConfigSaved={(newUrl) => {
          setActivePromUrl(newUrl);
          loadHosts();
        }}
      />
    </div>
  );
}

export default SystemMonitorPanel;
