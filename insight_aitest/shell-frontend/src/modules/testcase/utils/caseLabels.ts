export const CASE_TYPE_LABELS: Record<string, string> = {
  functional: '功能用例',
  api: '接口用例',
  ui: 'UI用例',
  performance: '性能用例',
};

export const TEST_DESIGN_LABELS: Record<string, string> = {
  positive: '正向场景',
  negative: '异常场景',
  boundary: '边界值',
  edge: '极端场景',
  boundary_value: '边界值',
  equivalence: '等价类',
  equivalence_partitioning: '等价类',
  scenario: '场景法',
  decision_table: '判定表',
  state_transition: '状态迁移',
  error_guessing: '错误推测',
  orthogonal: '正交分析',
  pairwise: '两两组合',
  security: '安全测试',
  compatibility: '兼容测试',
};

export const CASE_SOURCE_LABELS: Record<string, string> = {
  ai_generate: 'AI 生成',
  manual: '手动创建',
  import: '批量导入',
};

export const CASE_PRIORITY_LABELS: Record<string, string> = {
  p0: 'P0 - 核心必测',
  p1: 'P1 - 重要功能',
  p2: 'P2 - 一般场景',
  p3: 'P3 - 边界可选',
};

/** 格式化用例类型为规范中文名称 */
export function formatCaseType(type?: string | null): string {
  if (!type) return '—';
  const raw = String(type).trim();
  const lower = raw.toLowerCase();
  return CASE_TYPE_LABELS[lower] || raw;
}

/** 格式化测试设计方法为规范中文名称 */
export function formatTestDesign(design?: string | null): string {
  if (!design) return '—';
  const raw = String(design).trim();
  const lower = raw.toLowerCase();
  return TEST_DESIGN_LABELS[lower] || raw;
}

/** 格式化用例来源为规范中文名称 */
export function formatCaseSource(source?: string | null): string {
  if (!source) return '—';
  const raw = String(source).trim();
  const lower = raw.toLowerCase();
  return CASE_SOURCE_LABELS[lower] || raw;
}

