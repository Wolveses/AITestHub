import { useState, useEffect } from 'react';
import * as XLSX from 'xlsx';
import { Download } from 'lucide-react';
import { useTranslation } from 'react-i18next';

interface XlsxViewerProps {
  url: string;
  filename: string;
  sourceUrl?: string;
}

interface SheetData {
  name: string;
  rows: (string | number | null)[][];
}

/** 拦截阈值：虚胖 xlsx（dimension 标称百万行）会让 SheetJS 主线程解析卡死。
 * ① 字节上限：fetch 后先看大小；② 单元格上限：read 拿到维度后、sheet_to_json 前判断。
 */
const MAX_BYTES = 8 * 1024 * 1024; // 8MB
const MAX_CELLS = 200_000; // 20 万单元格

/** 解析 sheet 维度字符串（如 "A1:C1048559"）得出行×列数。 */
function refToCells(ref: string | undefined): number {
  if (!ref) return 0;
  const m = ref.match(/:([A-Z]+)(\d+)$/);
  if (!m) return 1;
  const colLetters = m[1];
  const rows = parseInt(m[2], 10);
  let cols = 0;
  for (const ch of colLetters) cols = cols * 26 + (ch.charCodeAt(0) - 64);
  return rows * cols;
}

/** xlsx/pptx 预览器：用 SheetJS 读取电子表格，渲染为 HTML 表格（只读）。
 * 支持多 sheet 切换。编辑走下载→上传替换流程。
 * 超大/虚胖文件前置拦截，提示飞书原链或下载，避免主线程卡死。
 */
export function XlsxViewer({ url, filename, sourceUrl }: XlsxViewerProps) {
  const { t } = useTranslation();
  const [sheets, setSheets] = useState<SheetData[]>([]);
  const [activeSheet, setActiveSheet] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tooLarge, setTooLarge] = useState<string | null>(null); // 超限原因（人读）

  // url 变化时重置加载态——在 effect 里做，避免渲染期 setState 触发多余 commit
  useEffect(() => {
    setLoading(true);
    setError(null);
    setTooLarge(null);
    let cancelled = false;
    fetch(url)
      .then((r) => r.arrayBuffer())
      .then((buf) => {
        // ① 字节上限：虚胖 xlsx 压缩后 8MB+，解压成 XML 可达 70MB+，先挡
        if (buf.byteLength > MAX_BYTES) {
          throw { tooLarge: `${(buf.byteLength / 1024 / 1024).toFixed(1)}MB` };
        }
        const wb = XLSX.read(buf, { type: 'array' });
        // ② 单元格上限：拿到维度后判断，命中则跳过 sheet_to_json（真正卡死的一步）
        let totalCells = 0;
        let maxRows = 0;
        for (const name of wb.SheetNames) {
          const cells = refToCells(wb.Sheets[name]?.['!ref']);
          totalCells += cells;
          const rowMatch = wb.Sheets[name]?.['!ref']?.match(/:(\d+)$/);
          if (rowMatch) maxRows = Math.max(maxRows, parseInt(rowMatch[1], 10));
        }
        if (totalCells > MAX_CELLS) {
          throw { tooLarge: `约 ${maxRows.toLocaleString()} 行` };
        }
        const result: SheetData[] = wb.SheetNames.map((name) => {
          const ws = wb.Sheets[name];
          const rows = XLSX.utils.sheet_to_json<(string | number | null)[]>(ws, {
            header: 1,
            defval: null,
            blankrows: false,
          });
          return { name, rows: rows.slice(0, 500) }; // 限制最多 500 行
        });
        if (!cancelled) {
          setSheets(result);
          setActiveSheet(0);
          setLoading(false);
        }
      })
      .catch((e) => {
        if (!cancelled) {
          if (e && typeof e === 'object' && 'tooLarge' in e) {
            setTooLarge(e.tooLarge);
          } else {
            setError(e.message || t('kb.xlsxParseFailed'));
          }
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [url]);

  if (loading) return <div style={{ padding: 24, textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>{t('kb.parseFile', { name: filename })}</div>;
  if (tooLarge) {
    return (
      <div style={{ padding: 32, textAlign: 'center', fontSize: 13, color: 'var(--text-secondary)', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12 }}>
        <div style={{ fontSize: 28 }}>⚠</div>
        <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{t('kb.previewTooLarge', '文件过大，预览失败')}</div>
        <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>{filename}（{tooLarge}）</div>
        <div style={{ display: 'flex', gap: 16, marginTop: 8 }}>
          {sourceUrl && (
            <a href={sourceUrl} target="_blank" rel="noreferrer" style={{ color: '#2563eb', fontWeight: 500, textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 4 }}>
              {t('kb.openInFeishu', '在飞书中打开')}
            </a>
          )}
          <a href={url} download style={{ color: 'var(--accent)', textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 4 }}>
            <Download size={14} /> {t('kb.download')}
          </a>
        </div>
      </div>
    );
  }
  if (error) return <div style={{ padding: 24, textAlign: 'center', color: 'var(--error)', fontSize: 13 }}>{t('kb.fileParseFailed', { name: filename, error })}</div>;
  if (!sheets.length) return <div style={{ padding: 24, textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>{t('kb.emptyFile')}</div>;

  const sheet = sheets[activeSheet];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ padding: '6px 12px', borderBottom: '1px solid var(--bg-card)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
          {sheets.map((s, i) => (
            <button
              key={i}
              onClick={() => setActiveSheet(i)}
              style={{
                background: i === activeSheet ? 'var(--accent)' : 'none',
                color: i === activeSheet ? 'var(--text-on-accent)' : 'var(--text-secondary)',
                border: '1px solid var(--border-strong)',
                padding: '2px 8px',
                borderRadius: 4,
                cursor: 'pointer',
                fontSize: 12,
              }}
            >
              {s.name}
            </button>
          ))}
        </div>
        <a href={url} download style={{ display: 'inline-flex', alignItems: 'center', gap: 4, color: 'var(--accent)', fontSize: 12, flexShrink: 0 }}>
          <Download size={14} /> {t('kb.download')}
        </a>
      </div>
      <div style={{ flex: 1, overflow: 'auto', padding: 8 }}>
        <table style={{ borderCollapse: 'collapse', fontSize: 12, width: '100%' }}>
          <tbody>
            {sheet.rows.map((row, ri) => (
              <tr key={ri}>
                {row.map((cell, ci) => (
                  <td
                    key={ci}
                    style={{
                      border: '1px solid var(--bg-elevated)',
                      padding: '4px 8px',
                      background: ri === 0 ? 'var(--bg-card)' : 'transparent',
                      color: 'var(--text-primary)',
                      fontWeight: ri === 0 ? 600 : 400,
                      whiteSpace: 'nowrap',
                      maxWidth: 300,
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                    }}
                  >
                    {cell ?? ''}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
