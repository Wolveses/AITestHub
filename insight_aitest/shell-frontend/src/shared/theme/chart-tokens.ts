/**
 * 图表指标色（TS 侧）—— echarts 配置用。
 *
 * 与 tokens.css 的 --chart-1..6 同源（高饱和，深底上鲜明可辨）。
 * UI 强调色锁 emerald 单色；图表多指标需可区分，故用 6 高饱和色。
 *
 * @see src/shared/theme/tokens.css
 */
export const chartColors = {
  cpu: "#10b981", // emerald（chart-1）
  memory: "#a855f7", // 紫高饱和（chart-2）
  fps: "#f59e0b", // amber（chart-3）
  networkUp: "#06b6d4", // cyan 高饱和（chart-4）
  networkDown: "#3b82f6", // blue（chart-5）
  gpu: "#ec4899", // pink 高饱和（chart-6，默认禁用）
} as const;

/** 网格线 / 坐标轴等图表中性色 —— 深底配套（暗黑主题） */
const chartNeutralDark: ChartNeutral = {
  axisLine: "#27272a", // zinc-700
  splitLine: "#1c1c22", // Raised
  axisLabel: "#a1a1aa", // zinc-400
  tooltipBg: "#121216", // Panel
  tooltipBorder: "rgba(255,255,255,0.2)",
  seriesLabel: "#fafafa",
};

/** 网格线 / 坐标轴等图表中性色 —— 浅底配套（浅色主题：需深色系保证可读）*/
const chartNeutralLight: ChartNeutral = {
  axisLine: "#d4d4d8", // zinc-300，浅底上可见的轴线
  splitLine: "#e4e4e7", // zinc-200，浅底上的网格线
  axisLabel: "#52525b", // zinc-600，浅底上可读的标签
  tooltipBg: "#ffffff", // 白底 tooltip
  tooltipBorder: "rgba(0,0,0,0.15)",
  seriesLabel: "#18181b", // zinc-900，浅底上数据标签
};

interface ChartNeutral {
  axisLine: string;
  splitLine: string;
  axisLabel: string;
  tooltipBg: string;
  tooltipBorder: string;
  seriesLabel: string;
}

/**
 * 按当前主题返回图表中性色。
 * 图表组件应订阅 useThemeStore 并在渲染时调用本函数，保证主题切换即时生效。
 */
export function getChartNeutral(theme: 'dark' | 'light'): ChartNeutral {
  return theme === 'light' ? chartNeutralLight : chartNeutralDark;
}

/**
 * @deprecated 保留向后兼容（固定暗黑）。新代码请用 getChartNeutral(theme)。
 */
export const chartNeutral: ChartNeutral = chartNeutralDark;

/**
 * 根据图表容器宽度与数据点数量计算 X 轴刻度间隔，避免时间标签重叠。
 */
export function getTimeAxisInterval(
  pointCount: number,
  containerWidth: number,
  horizontalPadding = 75,
  labelSlotPx = 80
): number {
  if (pointCount <= 1) return 0;
  const plotWidth = Math.max(120, containerWidth - horizontalPadding);
  const maxLabels = Math.max(2, Math.floor(plotWidth / labelSlotPx));
  const step = pointCount <= maxLabels ? 1 : Math.ceil(pointCount / maxLabels);
  return Math.max(0, step - 1);
}

/**
 * 将 MB 内存容量格式化为易读文本（>= 1024 MB 时按 GB 显示）。
 */
export function formatMemoryMb(mb: number): string {
  if (mb >= 1024) {
    return `${(mb / 1024).toFixed(2)} GB`;
  }
  return `${mb.toFixed(0)} MB`;
}
