import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { X } from 'lucide-react';

/** 执行产物预览的公共部件：执行记录页与测试报告页共用同一套日志/截图能力。 */

export interface ArtifactPreview {
  url: string;
  label: string;
}

/** 产物地址：按用例 + 执行记录 ID 取单次执行目录下的文件。 */
export function artifactUrl(caseId: number, runId: number, name: string) {
  return `/api/modules/ui/automation/cases/${caseId}/runs/${runId}/artifact/${encodeURIComponent(name)}`;
}

const preStyle: React.CSSProperties = {
  margin: 0,
  padding: 10,
  borderRadius: 6,
  background: 'var(--bg-card)',
  border: '1px solid var(--border)',
  fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
  fontSize: 11,
  lineHeight: 1.6,
  whiteSpace: 'pre-wrap',
  wordBreak: 'break-word',
  maxHeight: 280,
  overflowY: 'auto',
  overflowX: 'hidden',
};

/** 过程日志查看器：运行中按 2 秒轮询，结束后只拉一次。 */
export function LogViewer({ url, live }: { url: string; live: boolean }) {
  const { t } = useTranslation();
  const [text, setText] = useState(t('ui.auto.logLoading', '日志加载中…'));
  const boxRef = useRef<HTMLPreElement>(null);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        // 加时间戳绕过浏览器缓存，保证运行中每次都能拿到追加后的内容
        const r = await fetch(`${url}?_t=${Date.now()}`);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const body = await r.text();
        if (alive) setText(body || t('ui.auto.logEmpty', '（暂无输出）'));
      } catch (e) {
        if (alive) setText(t('ui.auto.logLoadFailed', '日志加载失败：{{msg}}', { msg: (e as Error).message }));
      }
    };
    tick();
    const timer = live ? setInterval(tick, 2000) : undefined;
    return () => {
      alive = false;
      if (timer) clearInterval(timer);
    };
  }, [url, live, t]);

  useEffect(() => {
    if (live && boxRef.current) boxRef.current.scrollTop = boxRef.current.scrollHeight;
  }, [text, live]);

  return (
    <pre
      ref={boxRef}
      style={{ ...preStyle, marginTop: 8, whiteSpace: 'pre-wrap' }}
    >
      {text}
    </pre>
  );
}

/** 截图大图预览浮层（点击遮罩或右上角关闭）。 */
export function ImagePreviewOverlay({
  preview,
  onClose,
}: {
  preview: ArtifactPreview | null;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  if (!preview) return null;
  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 1600,
        background: 'rgba(0,0,0,.8)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 24,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{ display: 'flex', flexDirection: 'column', gap: 8, maxWidth: '94vw', maxHeight: '94vh' }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: '#fff', fontSize: 12 }}>
          <span style={{ flex: 1 }}>{preview.label}</span>
          <a
            href={preview.url}
            target="_blank"
            rel="noreferrer"
            style={{ color: '#fff', fontSize: 11, textDecoration: 'none', opacity: 0.85 }}
          >
            {t('ui.auto.openOriginal', '新窗口打开')}
          </a>
          <button
            type="button"
            onClick={onClose}
            aria-label={t('common.close', '关闭')}
            style={{
              background: 'transparent',
              border: 'none',
              cursor: 'pointer',
              color: '#fff',
              display: 'flex',
              alignItems: 'center',
              padding: 0,
            }}
          >
            <X size={16} />
          </button>
        </div>
        <img
          src={preview.url}
          alt={preview.label}
          style={{ maxWidth: '94vw', maxHeight: '86vh', objectFit: 'contain', borderRadius: 8, background: '#111' }}
        />
      </div>
    </div>
  );
}
