import React, { useRef, useState } from 'react';
import { toast } from 'sonner';
import {
  Upload,
  CheckCircle2,
  Sparkles,
  ArrowRight,
  X,
  Loader2,
  FileCode,
  FileUp,
  FileCheck,
  ChevronLeft,
} from 'lucide-react';

interface HarCandidate {
  fingerprint: string;
  method: string;
  path: string;
  path_template: string;
  base_url: string;
  title: string;
  headers: Record<string, string>;
  body: any;
  response_status: number;
  response_headers: Record<string, string>;
  response_body: any;
  response_content_type: string;
  is_duplicate_in_har?: boolean;
  is_exists?: boolean;
}

interface HarImportModalProps {
  isOpen: boolean;
  onClose: () => void;
  projectId: number | null;
  onImportSuccess: () => void;
}

function methodBadgeColor(method: string) {
  switch (method.toUpperCase()) {
    case 'GET':
      return { bg: 'rgba(59, 130, 246, 0.12)', text: '#3b82f6', border: 'rgba(59, 130, 246, 0.25)' };
    case 'POST':
      return { bg: 'rgba(16, 185, 129, 0.12)', text: '#10b981', border: 'rgba(16, 185, 129, 0.25)' };
    case 'PUT':
      return { bg: 'rgba(245, 158, 11, 0.12)', text: '#f59e0b', border: 'rgba(245, 158, 11, 0.25)' };
    case 'DELETE':
      return { bg: 'rgba(239, 68, 68, 0.12)', text: '#ef4444', border: 'rgba(239, 68, 68, 0.25)' };
    default:
      return { bg: 'rgba(168, 85, 247, 0.12)', text: '#a855f7', border: 'rgba(168, 85, 247, 0.25)' };
  }
}

export const HarImportModal: React.FC<HarImportModalProps> = ({
  isOpen,
  onClose,
  projectId,
  onImportSuccess,
}) => {
  const [step, setStep] = useState<'upload' | 'select'>('upload');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [parsing, setParsing] = useState(false);
  const [importing, setImporting] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const [candidates, setCandidates] = useState<HarCandidate[]>([]);
  const [selectedFps, setSelectedFps] = useState<string[]>([]);
  const [autoEnhance, setAutoEnhance] = useState<boolean>(true);
  const [methodFilter, setMethodFilter] = useState<string>('ALL');
  const [searchPath, setSearchPath] = useState<string>('');
  const [conflictStrategy, setConflictStrategy] = useState<'overwrite' | 'skip'>('skip');

  if (!isOpen) return null;

  const handleFileChange = (file: File) => {
    if (!file.name.toLowerCase().endsWith('.har') && !file.name.toLowerCase().endsWith('.json')) {
      toast.error('请选择有效的 .har 文件');
      return;
    }
    setSelectedFile(file);
  };

  const handleParse = async () => {
    if (!selectedFile) {
      toast.error('请先选择要上传的 .har 文件');
      return;
    }

    setParsing(true);
    try {
      const fileText = await selectedFile.text();
      const res = await fetch('/api/modules/api/assets/parse-har', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          har_text: fileText,
          project_id: projectId,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || '解析 HAR 失败');
      }

      const list: HarCandidate[] = data.items || [];
      if (list.length === 0) {
        toast.warning('未解析到任何符合规则的 HTTP 接口');
        return;
      }

      setCandidates(list);
      // 默认选择策略：若当前是 skip（默认），已存在的接口默认不勾选，全新接口默认勾选
      if (conflictStrategy === 'skip') {
        setSelectedFps(list.filter((it) => !it.is_exists).map((it) => it.fingerprint));
      } else {
        setSelectedFps(list.map((it) => it.fingerprint));
      }
      setStep('select');
      const existsCount = data.exists_count || 0;
      if (existsCount > 0) {
        toast.info(`解析完成，检测到 ${existsCount} 个接口已存在于当前项目接口库中`);
      } else {
        toast.success(`成功解析出 ${list.length} 个全新接口`);
      }
    } catch (err: any) {
      toast.error(err.message || '解析 HAR 格式错误，请检查');
    } finally {
      setParsing(false);
    }
  };

  const handleStrategyChange = (newStrategy: 'overwrite' | 'skip') => {
    setConflictStrategy(newStrategy);
    if (newStrategy === 'skip') {
      // 切换为跳过时，已存在的接口取消勾选状态
      setSelectedFps((prev) => {
        const existSet = new Set(candidates.filter((c) => c.is_exists).map((c) => c.fingerprint));
        return prev.filter((fp) => !existSet.has(fp));
      });
    }
  };

  const handleSelectAll = (checked: boolean) => {
    if (checked) {
      const selectable = filteredCandidates.filter(
        (it) => !(conflictStrategy === 'skip' && it.is_exists)
      );
      setSelectedFps(selectable.map((it) => it.fingerprint));
    } else {
      setSelectedFps([]);
    }
  };

  const toggleSelect = (candidate: HarCandidate) => {
    if (conflictStrategy === 'skip' && candidate.is_exists) {
      // 置灰跳过，不可勾选
      return;
    }
    const fp = candidate.fingerprint;
    setSelectedFps((prev) =>
      prev.includes(fp) ? prev.filter((item) => item !== fp) : [...prev, fp]
    );
  };

  const filteredCandidates = candidates.filter((item) => {
    if (methodFilter !== 'ALL' && item.method.toUpperCase() !== methodFilter) {
      return false;
    }
    if (searchPath.trim()) {
      const q = searchPath.toLowerCase();
      const matchPath = item.path.toLowerCase().includes(q);
      const matchTmpl = (item.path_template || '').toLowerCase().includes(q);
      if (!matchPath && !matchTmpl) return false;
    }
    return true;
  });

  const handleImport = async () => {
    const toImport = candidates.filter((c) => selectedFps.includes(c.fingerprint));
    if (toImport.length === 0) {
      toast.error('请至少勾选一个要导入的接口');
      return;
    }

    setImporting(true);
    try {
      const res = await fetch('/api/modules/api/assets/import-har', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_id: projectId,
          items: toImport,
          conflict_strategy: conflictStrategy,
          auto_enhance: autoEnhance,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || '导入接口库失败');
      }

      const msg = `导入完成：新增 ${data.imported || 0} 个，覆盖更新 ${data.updated || 0} 个${
        data.skipped ? `，跳过已存在 ${data.skipped} 个` : ''
      }！${autoEnhance ? '后台已触发 AI 自动整理。' : ''}`;
      toast.success(msg);
      onImportSuccess();
      handleClose();
    } catch (err: any) {
      toast.error(err.message || '导入异常');
    } finally {
      setImporting(false);
    }
  };

  const handleClose = () => {
    setStep('upload');
    setSelectedFile(null);
    setCandidates([]);
    setSelectedFps([]);
    onClose();
  };

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 1000,
        background: 'rgba(0, 0, 0, 0.65)',
        backdropFilter: 'blur(3px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 24,
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) handleClose();
      }}
    >
      <div
        style={{
          width: '92%',
          maxWidth: step === 'upload' ? 620 : 980,
          height: step === 'upload' ? 490 : 700,
          background: 'var(--bg-card)',
          borderRadius: 12,
          border: '1px solid var(--border)',
          boxShadow: '0 20px 45px rgba(0,0,0,0.4)',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          transition: 'max-width 0.2s ease, height 0.2s ease',
        }}
      >
        {/* 顶部标题栏 */}
        <div
          style={{
            padding: '14px 20px',
            borderBottom: '1px solid var(--border)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            background: 'var(--bg-card)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div
              style={{
                width: 32,
                height: 32,
                borderRadius: 8,
                background: 'rgba(59, 130, 246, 0.1)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: 'var(--accent)',
              }}
            >
              <Upload size={18} />
            </div>
            <div>
              <div style={{ fontSize: 15, fontWeight: 600, color: 'var(--text-primary)' }}>
                导入 HAR 抓包接口
              </div>
              <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                {step === 'upload'
                  ? '上传浏览器或抓包工具导出的 .har 文件，解析接口并自动提取响应数据'
                  : `已解析出 ${candidates.length} 个候选接口，勾选确认后导入接口库`}
              </div>
            </div>
          </div>

          <button
            onClick={handleClose}
            style={{
              padding: 6,
              background: 'transparent',
              border: 'none',
              borderRadius: 6,
              cursor: 'pointer',
              color: 'var(--text-muted)',
              display: 'flex',
              alignItems: 'center',
            }}
          >
            <X size={18} />
          </button>
        </div>

        {/* 步骤 1: 上传 HAR 文件 */}
        {step === 'upload' ? (
          <div style={{ flex: 1, padding: 24, display: 'flex', flexDirection: 'column', gap: 16 }}>
            <input
              type="file"
              ref={fileInputRef}
              accept=".har,.json"
              style={{ display: 'none' }}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) handleFileChange(file);
              }}
            />

            {/* 拖拽或点击上传区域 */}
            <div
              onDragOver={(e) => {
                e.preventDefault();
                setIsDragging(true);
              }}
              onDragLeave={(e) => {
                e.preventDefault();
                setIsDragging(false);
              }}
              onDrop={(e) => {
                e.preventDefault();
                setIsDragging(false);
                const file = e.dataTransfer.files?.[0];
                if (file) handleFileChange(file);
              }}
              onClick={() => fileInputRef.current?.click()}
              style={{
                flex: 1,
                border: `2px dashed ${isDragging ? 'var(--accent)' : 'var(--border)'}`,
                borderRadius: 10,
                background: isDragging ? 'rgba(59, 130, 246, 0.05)' : 'var(--bg-base)',
                cursor: 'pointer',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 12,
                padding: 24,
                transition: 'all 0.15s ease',
              }}
            >
              <div
                style={{
                  width: 54,
                  height: 54,
                  borderRadius: '50%',
                  background: selectedFile ? 'rgba(16, 185, 129, 0.12)' : 'rgba(59, 130, 246, 0.1)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  color: selectedFile ? '#10b981' : 'var(--accent)',
                }}
              >
                {selectedFile ? <FileCheck size={28} /> : <FileUp size={28} />}
              </div>

              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 4 }}>
                  {selectedFile ? selectedFile.name : '点击或将 .har 文件拖拽至此'}
                </div>
                <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                  {selectedFile
                    ? `文件大小: ${(selectedFile.size / 1024 / 1024).toFixed(2)} MB（点击可更换文件）`
                    : '支持 Chrome、Edge、Charles、Fiddler 导出的标准 .har 文件'}
                </div>
              </div>

              <div
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 6,
                  padding: '5px 12px',
                  borderRadius: 6,
                  background: 'var(--bg-card)',
                  border: '1px solid var(--border)',
                  fontSize: 12,
                  color: 'var(--text-muted)',
                  marginTop: 6,
                }}
              >
                <FileCode size={13} />
                仅读取客户端本地文件，不会泄露无关隐私
              </div>
            </div>

            {/* 底部按钮栏 */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 10 }}>
              <button
                onClick={handleClose}
                style={{
                  padding: '7px 16px',
                  borderRadius: 6,
                  border: '1px solid var(--border)',
                  background: 'var(--bg-base)',
                  color: 'var(--text-primary)',
                  fontSize: 13,
                  cursor: 'pointer',
                }}
              >
                取消
              </button>
              <button
                onClick={handleParse}
                disabled={parsing || !selectedFile}
                style={{
                  padding: '7px 20px',
                  borderRadius: 6,
                  border: 'none',
                  background: 'var(--accent)',
                  color: '#fff',
                  fontSize: 13,
                  fontWeight: 500,
                  cursor: parsing || !selectedFile ? 'not-allowed' : 'pointer',
                  opacity: parsing || !selectedFile ? 0.6 : 1,
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 6,
                }}
              >
                {parsing ? <Loader2 size={14} className="animate-spin" /> : <ArrowRight size={14} />}
                {parsing ? '正在解析 HAR 文件...' : '解析接口数据'}
              </button>
            </div>
          </div>
        ) : (
          /* 步骤 2: 过滤、全选、选择与导入 */
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
            {/* 顶栏控制条 */}
            <div
              style={{
                padding: '10px 20px',
                borderBottom: '1px solid var(--border)',
                background: 'var(--bg-base)',
                display: 'flex',
                alignItems: 'center',
                flexWrap: 'wrap',
                gap: 12,
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>请求方式:</span>
                <select
                  value={methodFilter}
                  onChange={(e) => setMethodFilter(e.target.value)}
                  style={{
                    padding: '4px 8px',
                    borderRadius: 5,
                    border: '1px solid var(--border)',
                    background: 'var(--bg-card)',
                    color: 'var(--text-primary)',
                    fontSize: 12,
                  }}
                >
                  <option value="ALL">全部 Method</option>
                  <option value="GET">GET</option>
                  <option value="POST">POST</option>
                  <option value="PUT">PUT</option>
                  <option value="DELETE">DELETE</option>
                </select>
              </div>

              <input
                type="text"
                value={searchPath}
                onChange={(e) => setSearchPath(e.target.value)}
                placeholder="搜索接口 Path..."
                style={{
                  padding: '4px 10px',
                  borderRadius: 5,
                  border: '1px solid var(--border)',
                  background: 'var(--bg-card)',
                  color: 'var(--text-primary)',
                  fontSize: 12,
                  width: 220,
                  outline: 'none',
                }}
              />

              <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 14 }}>
                <label
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 6,
                    fontSize: 12,
                    color: 'var(--text-primary)',
                    cursor: 'pointer',
                  }}
                >
                  <input
                    type="checkbox"
                    checked={autoEnhance}
                    onChange={(e) => setAutoEnhance(e.target.checked)}
                  />
                  <Sparkles size={14} color="#d97706" />
                  导入后自动触发 AI 整理
                </label>

                <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                  已选 <strong>{selectedFps.length}</strong> / {candidates.length}
                </div>
              </div>
            </div>

            {/* 接口候选列表 */}
            <div style={{ flex: 1, overflowY: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12, textAlign: 'left' }}>
                <thead>
                  <tr style={{ background: 'var(--bg-base)', borderBottom: '1px solid var(--border)', color: 'var(--text-muted)' }}>
                    <th style={{ width: 44, padding: '9px 12px', textAlign: 'center' }}>
                      <input
                        type="checkbox"
                        checked={
                          filteredCandidates.length > 0 &&
                          filteredCandidates.filter((it) => !(conflictStrategy === 'skip' && it.is_exists)).length > 0 &&
                          filteredCandidates
                            .filter((it) => !(conflictStrategy === 'skip' && it.is_exists))
                            .every((it) => selectedFps.includes(it.fingerprint))
                        }
                        onChange={(e) => handleSelectAll(e.target.checked)}
                      />
                    </th>
                    <th style={{ width: 75, padding: '9px 12px' }}>Method</th>
                    <th style={{ padding: '9px 12px' }}>归一化路径 / 实际路径</th>
                    <th style={{ width: 110, minWidth: 100, padding: '9px 12px', whiteSpace: 'nowrap' }}>库内状态</th>
                    <th style={{ width: 85, padding: '9px 12px' }}>状态码</th>
                    <th style={{ width: 80, padding: '9px 12px' }}>请求体</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredCandidates.length === 0 ? (
                    <tr>
                      <td colSpan={6} style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>
                        无符合条件的接口记录
                      </td>
                    </tr>
                  ) : (
                    filteredCandidates.map((item, idx) => {
                      const isChecked = selectedFps.includes(item.fingerprint);
                      const isSkippedDisabled = conflictStrategy === 'skip' && !!item.is_exists;
                      const badge = methodBadgeColor(item.method);

                      return (
                        <tr
                          key={item.fingerprint + idx}
                          onClick={() => toggleSelect(item)}
                          style={{
                            borderBottom: '1px solid var(--border)',
                            background: isChecked ? 'rgba(59, 130, 246, 0.04)' : 'transparent',
                            cursor: isSkippedDisabled ? 'not-allowed' : 'pointer',
                            opacity: isSkippedDisabled ? 0.45 : 1,
                          }}
                        >
                          <td
                            style={{ padding: '9px 12px', textAlign: 'center' }}
                            onClick={(e) => e.stopPropagation()}
                          >
                            <input
                              type="checkbox"
                              checked={isChecked}
                              disabled={isSkippedDisabled}
                              onChange={() => toggleSelect(item)}
                              title={isSkippedDisabled ? '规则为跳过时，已存在接口不可勾选' : undefined}
                              style={{ cursor: isSkippedDisabled ? 'not-allowed' : 'pointer' }}
                            />
                          </td>
                          <td style={{ padding: '9px 12px' }}>
                            <span
                              style={{
                                fontSize: 10,
                                fontWeight: 700,
                                padding: '2px 6px',
                                borderRadius: 4,
                                background: badge.bg,
                                color: badge.text,
                                border: `1px solid ${badge.border}`,
                              }}
                            >
                              {item.method}
                            </span>
                          </td>
                          <td style={{ padding: '9px 12px' }}>
                            <div style={{ fontWeight: 600, color: 'var(--text-primary)', fontFamily: 'monospace' }}>
                              {item.path_template || item.path}
                            </div>
                            {item.path_template && item.path !== item.path_template && (
                              <div style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'monospace', marginTop: 2 }}>
                                示例: {item.path}
                              </div>
                            )}
                          </td>
                          <td style={{ width: 110, minWidth: 100, padding: '9px 12px', whiteSpace: 'nowrap' }}>
                            {item.is_exists ? (
                              <span
                                style={{
                                  display: 'inline-block',
                                  fontSize: 11,
                                  fontWeight: 600,
                                  padding: '3px 8px',
                                  borderRadius: 4,
                                  background: 'rgba(245, 158, 11, 0.12)',
                                  color: '#f59e0b',
                                  border: '1px solid rgba(245, 158, 11, 0.3)',
                                  whiteSpace: 'nowrap',
                                }}
                              >
                                已存在
                              </span>
                            ) : (
                              <span
                                style={{
                                  display: 'inline-block',
                                  fontSize: 11,
                                  fontWeight: 600,
                                  padding: '3px 8px',
                                  borderRadius: 4,
                                  background: 'rgba(16, 185, 129, 0.12)',
                                  color: '#10b981',
                                  border: '1px solid rgba(16, 185, 129, 0.3)',
                                  whiteSpace: 'nowrap',
                                }}
                              >
                                新增
                              </span>
                            )}
                          </td>
                          <td style={{ padding: '9px 12px', fontFamily: 'monospace' }}>
                            <span
                              style={{
                                padding: '1px 6px',
                                borderRadius: 4,
                                background: item.response_status < 400 ? 'rgba(16, 185, 129, 0.1)' : 'rgba(239, 68, 68, 0.1)',
                                color: item.response_status < 400 ? '#10b981' : '#ef4444',
                                fontSize: 11,
                              }}
                            >
                              {item.response_status || '--'}
                            </span>
                          </td>
                          <td style={{ padding: '9px 12px', color: 'var(--text-muted)', fontSize: 11 }}>
                            {item.body ? '有 Payload' : '无'}
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>

            {/* 底部操作栏 */}
            <div
              style={{
                padding: '12px 20px',
                borderTop: '1px solid var(--border)',
                background: 'var(--bg-card)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
                <button
                  type="button"
                  onClick={() => setStep('upload')}
                  style={{
                    padding: '7px 14px',
                    borderRadius: 6,
                    border: '1px solid var(--border)',
                    background: 'var(--bg-base)',
                    color: 'var(--text-primary)',
                    fontSize: 12,
                    cursor: 'pointer',
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 4,
                  }}
                >
                  <ChevronLeft size={13} />
                  重新选文件
                </button>

                {/* 重复接口处理策略 */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
                  <span style={{ color: 'var(--text-muted)' }}>重复接口处理:</span>
                  <div style={{ display: 'inline-flex', border: '1px solid var(--border)', borderRadius: 6, overflow: 'hidden' }}>
                    <button
                      type="button"
                      onClick={() => handleStrategyChange('overwrite')}
                      style={{
                        padding: '4px 10px',
                        border: 'none',
                        background: conflictStrategy === 'overwrite' ? 'var(--accent)' : 'var(--bg-base)',
                        color: conflictStrategy === 'overwrite' ? '#fff' : 'var(--text-primary)',
                        fontSize: 12,
                        cursor: 'pointer',
                        fontWeight: conflictStrategy === 'overwrite' ? 600 : 400,
                      }}
                      title="若接口库中已存在相同 Method+URL，则覆盖更新其 Header/Payload 并累加命中次数"
                    >
                      存在则覆盖
                    </button>
                    <button
                      type="button"
                      onClick={() => handleStrategyChange('skip')}
                      style={{
                        padding: '4px 10px',
                        border: 'none',
                        background: conflictStrategy === 'skip' ? 'var(--accent)' : 'var(--bg-base)',
                        color: conflictStrategy === 'skip' ? '#fff' : 'var(--text-primary)',
                        fontSize: 12,
                        cursor: 'pointer',
                        fontWeight: conflictStrategy === 'skip' ? 600 : 400,
                      }}
                      title="若接口库中已存在相同 Method+URL，则保留已有接口不变，直接跳过"
                    >
                      存在则跳过
                    </button>
                  </div>
                </div>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <button
                  onClick={handleClose}
                  style={{
                    padding: '7px 16px',
                    borderRadius: 6,
                    border: '1px solid var(--border)',
                    background: 'var(--bg-base)',
                    color: 'var(--text-primary)',
                    fontSize: 12,
                    cursor: 'pointer',
                  }}
                >
                  取消
                </button>
                <button
                  onClick={handleImport}
                  disabled={importing || selectedFps.length === 0}
                  style={{
                    padding: '7px 22px',
                    borderRadius: 6,
                    border: 'none',
                    background: 'var(--accent)',
                    color: '#fff',
                    fontSize: 12,
                    fontWeight: 500,
                    cursor: importing || selectedFps.length === 0 ? 'not-allowed' : 'pointer',
                    opacity: importing || selectedFps.length === 0 ? 0.6 : 1,
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 6,
                  }}
                >
                  {importing ? <Loader2 size={13} className="animate-spin" /> : <CheckCircle2 size={13} />}
                  {importing ? '正在导入入库...' : `导入选中的 ${selectedFps.length} 个接口`}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
