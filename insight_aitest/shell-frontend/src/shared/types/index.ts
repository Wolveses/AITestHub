// 设备全局性能监控专用目标标识（与后端 DEVICE_GLOBAL_TARGET 保持一致）
export const DEVICE_GLOBAL_TARGET = '__device__';

export function isDeviceGlobalTarget(target?: string | null): boolean {
  return target === DEVICE_GLOBAL_TARGET;
}

export interface Device {
  device_id: string;
  name: string;
  type: 'android' | 'ios';
  status: 'online' | 'offline' | 'unauthorized';
  sdk_version?: string;
  model?: string;
}

export interface Session {
  id: number;
  device_id: string;
  app_package: string;
  app_name?: string;  // 应用友好名称，用于显示
  platform: string;
  status: 'created' | 'running' | 'stopped' | 'error';
  start_time: string;
  end_time?: string;
  duration?: number;
}

export interface AppInfo {
  package_name: string;   // 包名或 Bundle ID
  name: string;           // 应用友好名称（匹配API返回）
  pid?: number;           // 进程ID
  is_running?: boolean;   // 是否正在运行
  status?: string;        // 运行状态
}

export interface AlarmRecord {
  id: string;
  time: string;
  level: '严重' | '警告';
  content: string;
}

export interface MetricsData {
  timestamp: string;
  cpu?: number;
  memory?: number;
  memory_total_mb?: number;
  memory_percent?: number;
  fps?: number;
  network_up?: number;
  network_down?: number;
  gpu?: number;
  battery?: number;
  temperature?: number;
}

export interface MetricCardConfig {
  metricId: keyof MetricsData;
  title: string;
  color: string;
  yMin?: number;
  yMax?: number;
  decimals: number;
  unit: string;
  enabled: boolean;
  priority: number;
}
