/**
 * JMeter CLI 及内置压测引擎实时调度命令生成工具
 */

export interface PreviewCommandOptions {
  engineType: 'jmeter_cli' | 'builtin';
  execMode: 'local' | 'distributed';
  slaveHosts: string;
  scriptName?: string;
  customProperties: Record<string, string>;
}

export function buildJMeterCommand(options: PreviewCommandOptions): string {
  const { engineType, execMode, slaveHosts, scriptName, customProperties } = options;

  if (engineType === 'builtin') {
    const propsList = Object.entries(customProperties || {})
      .filter(([k, v]) => k.trim() && v !== undefined && String(v).trim() !== '')
      .map(([k, v]) => `${k.trim()}=${String(v).trim()}`)
      .join(', ');
    return `[内置 Python 异步高并发引擎] 脚本: ${scriptName || '默认脚本'} | 参数: ${propsList || '无'}`;
  }

  const isDistributed = execMode === 'distributed' && Boolean(slaveHosts?.trim());
  const propPrefix = isDistributed ? '-G' : '-J';
  const cleanScriptName = (scriptName || 'plan').replace(/[\\/:\*\?"<>\|]/g, '_');
  const parts: string[] = [
    'jmeter',
    '-n',
    '-t',
    `"${cleanScriptName}.jmx"`,
    '-l',
    `"result_${cleanScriptName}.jtl"`,
  ];

  if (isDistributed) {
    parts.push('-R', slaveHosts.trim(), '-X');
    parts.push('-Jserver.rmi.ssl.disable=true');
  }

  for (const [k, v] of Object.entries(customProperties || {})) {
    const key = k.trim();
    const val = String(v ?? '').trim();
    if (key && val !== '') {
      if (val.includes(' ') || val.includes('"')) {
        parts.push(`${propPrefix}${key}="${val.replace(/"/g, '\\"')}"`);
      } else {
        parts.push(`${propPrefix}${key}=${val}`);
      }
    }
  }

  return parts.join(' ');
}
