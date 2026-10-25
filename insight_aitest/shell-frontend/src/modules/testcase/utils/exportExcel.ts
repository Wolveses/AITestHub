import { toast } from 'sonner';

interface ExportExcelOptions {
  case_ids?: number[];
  batch_id?: string;
  task_id?: number;
  filename?: string;
}

function formatMinuteTimestamp(d: Date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  const YYYY = d.getFullYear();
  const MM = pad(d.getMonth() + 1);
  const DD = pad(d.getDate());
  const HH = pad(d.getHours());
  const mm = pad(d.getMinutes());
  return `${YYYY}${MM}${DD}_${HH}${mm}`;
}

export async function exportTestCasesToExcel(options: ExportExcelOptions) {
  try {
    toast.info('正在准备导出 Excel...');
    const res = await fetch('/api/modules/testcase/testcases/export-excel', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        case_ids: options.case_ids,
        batch_id: options.batch_id,
        task_id: options.task_id,
      }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: '导出失败' }));
      throw new Error(err.detail || '导出失败');
    }

    let downloadFilename = options.filename;
    if (!downloadFilename) {
      const disposition = res.headers.get('Content-Disposition') || res.headers.get('content-disposition');
      if (disposition) {
        const utf8Match = disposition.match(/filename\*=UTF-8''([^;]+)/i);
        if (utf8Match && utf8Match[1]) {
          downloadFilename = decodeURIComponent(utf8Match[1].replace(/["']/g, ''));
        } else {
          const fnMatch = disposition.match(/filename=["']?([^"';]+)["']?/i);
          if (fnMatch && fnMatch[1]) {
            downloadFilename = decodeURIComponent(fnMatch[1]);
          }
        }
      }
    }
    if (!downloadFilename) {
      downloadFilename = `测试用例_${formatMinuteTimestamp()}.xlsx`;
    }

    const blob = await res.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = downloadFilename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    window.URL.revokeObjectURL(url);
    toast.success('导出 Excel 成功（TAPD 规范格式）');
  } catch (e) {
    toast.error((e as Error).message);
  }
}

