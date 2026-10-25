import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Camera, AlertTriangle, Check, FolderInput, FileSpreadsheet } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import i18n from '../../../shared/i18n';
import { useCaseStore, type TestCase } from '../store/caseStore';
import { ImportToProjectModal } from './ImportToProjectModal';
import { exportTestCasesToExcel } from '../utils/exportExcel';

const inputStyle: React.CSSProperties = {
  background: "var(--bg-card)", border: '1px solid var(--bg-elevated)', borderRadius: 4,
  color: "var(--text-primary)", padding: '8px', fontFamily: 'inherit', fontSize: 13,
  width: '100%',
};
const labelStyle: React.CSSProperties = { fontSize: 12, color: "var(--text-secondary)", marginBottom: 6 };
const primaryBtn: React.CSSProperties = {
  background: "var(--accent)", color: "var(--bg-base)", border: 'none', borderRadius: 6,
  padding: '8px 20px', cursor: 'pointer', fontWeight: 600,
};

/** File 转纯 base64（去掉 data:...;base64, 前缀，后端 client.py 会重新拼回 data URL） */
function fileToBase64(file: File): Promise<{ data: string; mime: string }> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result as string;
      // result 形如 "data:image/png;base64,XXXX"，取逗号后
      const commaIdx = result.indexOf(',');
      resolve({
        data: commaIdx >= 0 ? result.slice(commaIdx + 1) : result,
        mime: file.type || 'image/png',
      });
    };
    reader.onerror = () => reject(new Error(i18n.t('testcase.fileReadFailed')));
    reader.readAsDataURL(file);
  });
}

/**
 * 监听 AI 任务 SSE 流（GET /api/modules/ai/tasks/{id}/stream）。
 * 沿用 taskStore.streamTask 的 fetch + ReadableStream 解析方式。
 * 收到 done/error/cancelled 事件后 resolve。
 */
async function streamImageTask(taskId: number): Promise<void> {
  const res = await fetch(`/api/modules/ai/tasks/${taskId}/stream`);
  if (!res.body) return;
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split('\n\n');
    buffer = events.pop()!;
    for (const evt of events) {
      const type = evt.match(/^event: (.+)$/m)?.[1];
      const dataStr = evt.match(/^data: (.+)$/m)?.[1] ?? '{}';
      let data: Record<string, unknown>;
      try { data = JSON.parse(dataStr); } catch { continue; }
      if (type === 'error' && typeof data.message === 'string') {
        throw new Error(data.message);
      }
      if (type === 'done' || type === 'error' || type === 'cancelled') return;
    }
  }
}

export function ImageGeneratePanel({ onDone }: { onDone?: () => void }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { createQuickTask, loadCases, selectedProjectId } = useCaseStore();
  const [files, setFiles] = useState<File[]>([]);
  const [baseUrl, setBaseUrl] = useState('');
  const [pointSummary, setPointSummary] = useState('');
  const [error, setError] = useState('');
  const [imageGenerating, setImageGenerating] = useState(false);
  const [genStatus, setGenStatus] = useState('');
  const [createdTaskId, setCreatedTaskId] = useState<number | null>(null);
  const [generatedCases, setGeneratedCases] = useState<TestCase[]>([]);
  const [importModalOpen, setImportModalOpen] = useState(false);
  const [imported, setImported] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const addFiles = (newFiles: File[]) => {
    const images = newFiles.filter((f) => f.type.startsWith('image/'));
    if (images.length) setFiles((p) => [...p, ...images]);
  };

  const onPaste = (e: React.ClipboardEvent) => {
    const pasted = Array.from(e.clipboardData.files).filter((f) => f.type.startsWith('image/'));
    if (pasted.length) {
      e.preventDefault();
      addFiles(pasted);
    }
  };

  // object URL memo + cleanup（防内存泄漏：每次 files 变化重建，旧的 revoke）
  const thumbs = useMemo(() => files.map((f) => URL.createObjectURL(f)), [files]);
  useEffect(() => () => thumbs.forEach((url) => URL.revokeObjectURL(url)), [thumbs]);

  const submit = async () => {
    setError('');
    setGenStatus('');
    setImported(false);
    setCreatedTaskId(null);
    setGeneratedCases([]);
    if (files.length === 0) {
      setError(t('testcase.selectAtLeastOneScreenshot'));
      return;
    }
    if (!baseUrl.trim()) {
      setError(t('testcase.fillBaseUrl'));
      return;
    }

    setImageGenerating(true);
    try {
      const images = await Promise.all(files.map(fileToBase64));
      setGenStatus(t('testcase.submittingTask'));
      const { task_id } = await createQuickTask('image_generate', {
        images: images.map((img) => ({ data: img.data, mime: img.mime })),
        base_url: baseUrl.trim(),
        point_summary: pointSummary.trim(),
        project_id: selectedProjectId,
        version_id: null,
      });
      setCreatedTaskId(task_id);

      setGenStatus(t('testcase.visionAnalyzing'));
      await streamImageTask(task_id);
      setGenStatus(t('testcase.generateComplete'));

      try {
        const r = await fetch(`/api/modules/testcase/testcases?task_id=${task_id}`);
        if (r.ok) {
          const list = await r.json();
          if (Array.isArray(list)) {
            setGeneratedCases(list);
          }
        }
      } catch {
        // 保持现状
      }
    } catch (e) {
      setError((e as Error).message);
      setGenStatus('');
    } finally {
      setImageGenerating(false);
    }
  };

  return (
    <div
      style={{ padding: 24, maxWidth: 720, overflow: 'auto' }}
      onPaste={onPaste}
      tabIndex={0}  // 让 div 可获焦点接收 paste 事件
      autoFocus     // 进入面板自动获焦，Ctrl+V 直接粘贴图片
    >
      <h2 style={{ fontSize: 16, color: "var(--text-primary)", marginBottom: 4, display: 'inline-flex', alignItems: 'center', gap: 6 }}>
        <Camera size={16} strokeWidth={1.5} /> {t('testcase.screenshotGenerateUi')}
      </h2>
      <p style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 20, whiteSpace: 'pre-line' }}>
        {t('testcase.imageUploadHint')}
      </p>

      {/* 截图选择 + 预览 */}
      <div style={{ marginBottom: 16 }}>
        <div style={labelStyle}>{t('testcase.uiScreenshotsLabel')}</div>
        <input
          ref={fileRef}
          type="file"
          multiple
          accept="image/*"
          style={{ display: 'none' }}
          onChange={(e) => {
            addFiles(Array.from(e.target.files ?? []));
            if (fileRef.current) fileRef.current.value = '';
          }}
        />
        <button
          onClick={() => fileRef.current?.click()}
          style={{
            background: "var(--bg-card)", border: '1px dashed var(--border-strong)', color: "var(--text-secondary)",
            padding: '12px 20px', borderRadius: 6, cursor: 'pointer', fontSize: 13,
          }}
        >
          {t('testcase.selectScreenshots')}
        </button>

        {files.length > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 12 }}>
            {files.map((f, i) => (
              <div
                key={i}
                style={{
                  position: 'relative', width: 100, height: 80,
                  border: '1px solid var(--bg-elevated)', borderRadius: 4, overflow: 'hidden',
                }}
              >
                <img
                  src={thumbs[i]}
                  alt={f.name}
                  style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                />
                <button
                  onClick={() => setFiles((p) => p.filter((_, idx) => idx !== i))}
                  style={{
                    position: 'absolute', top: 2, right: 2,
                    background: 'rgba(0,0,0,0.7)', color: 'var(--error)',
                    border: 'none', borderRadius: '50%', width: 18, height: 18,
                    cursor: 'pointer', fontSize: 11, lineHeight: '18px', padding: 0,
                  }}
                >
                  ×
                </button>
                <div style={{
                  position: 'absolute', bottom: 0, left: 0, right: 0,
                  background: 'rgba(0,0,0,0.6)', color: "var(--text-secondary)",
                  fontSize: 9, padding: '1px 4px', textAlign: 'center',
                  overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                }}>
                  {i + 1}. {f.name}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* base_url */}
      <div style={{ marginBottom: 16 }}>
        <div style={labelStyle}>{t('testcase.targetBaseUrlLabel')}</div>
        <input
          style={inputStyle}
          placeholder="https://example.com/app"
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)}
        />
      </div>

      {/* point_summary */}
      <div style={{ marginBottom: 16 }}>
        <div style={labelStyle}>{t('testcase.testFocusLabel')}</div>
        <textarea
          style={{ ...inputStyle, minHeight: 60, resize: 'vertical' }}
          placeholder={t('testcase.testFocusPlaceholder')}
          value={pointSummary}
          onChange={(e) => setPointSummary(e.target.value)}
        />
      </div>

      {/* 错误提示 */}
      {error && (
        <div style={{ color: 'var(--error)', fontSize: 12, marginBottom: 12, display: 'inline-flex', alignItems: 'center', gap: 4 }}>
          <AlertTriangle size={12} strokeWidth={1.5} /> {error}
        </div>
      )}

      {/* 提交 */}
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <button
          onClick={submit}
          disabled={imageGenerating || files.length === 0 || !baseUrl.trim()}
          style={{
            ...primaryBtn,
            opacity: imageGenerating || files.length === 0 || !baseUrl.trim() ? 0.4 : 1,
          }}
        >
          {imageGenerating ? t('testcase.generatingVision') : t('testcase.generateUiCase')}
        </button>
        {genStatus && (
          <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{genStatus}</span>
        )}
      </div>

      {/* 生成完成后的审阅与导入/导出区 */}
      {createdTaskId !== null && !imageGenerating && (
        <div style={{ marginTop: 24, padding: 16, background: 'var(--bg-card)', borderRadius: 8, border: '1px solid var(--border)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, color: 'var(--success)', fontWeight: 600, fontSize: 14, marginBottom: 8 }}>
            <Check size={16} strokeWidth={2} />
            {t('testcase.generateComplete', '用例生成完成')}
            <span style={{ fontSize: 12, fontWeight: 'normal', color: 'var(--text-secondary)' }}>
              ({t('testcase.totalCasesCount', `共 {{count}} 条用例`, { count: generatedCases.length })})
            </span>
          </div>

          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 14 }}>
            {imported
              ? t('testcase.casesImportedNotice', '用例已成功导入目标项目，可前往用例列表查看。')
              : t('testcase.casesGeneratedNotice', '已完成测试用例生成（尚未入库）。请选择将用例导入到项目，或导出为 TAPD 规范 Excel 文件：')}
          </div>

          {generatedCases.length > 0 && (
            <div style={{ maxHeight: 200, overflowY: 'auto', border: '1px solid var(--border)', borderRadius: 6, marginBottom: 16, background: 'var(--bg-base)' }}>
              {generatedCases.map((c, idx) => (
                <div key={c.id} style={{ padding: '8px 12px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
                  <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>#{idx + 1}</span>
                  <span style={{ flex: 1, fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{c.title}</span>
                  <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{c.type}</span>
                  <span style={{ fontSize: 10, padding: '1px 5px', borderRadius: 3, border: '1px solid var(--border)' }}>{c.priority.toUpperCase()}</span>
                </div>
              ))}
            </div>
          )}

          <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            {!imported && (
              <>
                <button
                  onClick={() => setImportModalOpen(true)}
                  disabled={generatedCases.length === 0}
                  style={{ ...primaryBtn, display: 'inline-flex', alignItems: 'center', gap: 6 }}
                >
                  <FolderInput size={14} strokeWidth={1.8} />
                  {t('testcase.importToProject', '导入到项目')}
                </button>

                <button
                  onClick={() => exportTestCasesToExcel({
                    task_id: createdTaskId,
                    case_ids: generatedCases.map((c) => c.id),
                  })}
                  disabled={generatedCases.length === 0}
                  style={{
                    background: 'var(--bg-base)',
                    border: '1px solid var(--border)',
                    color: 'var(--text-primary)',
                    borderRadius: 6,
                    padding: '8px 16px',
                    cursor: 'pointer',
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 6,
                  }}
                >
                  <FileSpreadsheet size={14} strokeWidth={1.8} style={{ color: 'var(--success, #10b981)' }} />
                  {t('testcase.exportToExcel', '导出到 Excel（TAPD）')}
                </button>
              </>
            )}

            <button
              onClick={() => {
                if (onDone) onDone();
                else navigate('/testcase');
              }}
              style={{
                background: 'none',
                border: '1px solid var(--border)',
                color: 'var(--text-secondary)',
                borderRadius: 6,
                padding: '8px 16px',
                cursor: 'pointer',
              }}
            >
              {t('testcase.backToList', '返回用例列表')}
            </button>
          </div>
        </div>
      )}

      <ImportToProjectModal
        open={importModalOpen}
        caseIds={generatedCases.map((c) => c.id)}
        onClose={() => setImportModalOpen(false)}
        onSuccess={async () => {
          setImported(true);
          await loadCases();
        }}
      />
    </div>
  );
}
