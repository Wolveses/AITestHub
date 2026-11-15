import { useState, useEffect, useRef } from 'react';
import { toast } from 'sonner';
import { FileCode, Upload, Save, X, Code2 } from 'lucide-react';
import type { PerfScriptItem } from '../../store/serverPerfStore';

interface EditScriptModalProps {
  open: boolean;
  onClose: () => void;
  script: PerfScriptItem & { jmx_content?: string };
  onSuccess: () => void;
}

export function EditScriptModal({ open, onClose, script, onSuccess }: EditScriptModalProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [planDescription, setPlanDescription] = useState('');
  const [jmxContent, setJmxContent] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open && script) {
      setName(script.name || '');
      setDescription(script.description || '');
      setPlanDescription(script.plan_description || '');
      setJmxContent(script.jmx_content || '');
    }
  }, [open, script]);

  if (!open) return null;

  // 上传本地 JMX 文件覆盖
  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!file.name.endsWith('.jmx') && !file.name.endsWith('.xml')) {
      toast.error('请上传标准 JMeter .jmx 脚本文件');
      return;
    }
    const reader = new FileReader();
    reader.onload = (event) => {
      const content = event.target?.result as string;
      if (!content || !content.includes('<jmeterTestPlan')) {
        toast.warning('文件格式可能不是标准的 JMeter 测试计划 XML');
      }
      setJmxContent(content);
      toast.success(`已载入本地脚本: ${file.name}`);
    };
    reader.readAsText(file);
    e.target.value = '';
  };

  const handleSave = async () => {
    if (!name.trim()) {
      toast.error('脚本名称不能为空');
      return;
    }
    if (!jmxContent.trim()) {
      toast.error('JMX 脚本内容不能为空');
      return;
    }

    setSaving(true);
    try {
      const res = await fetch(`/api/modules/performance/server/scripts/${script.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: name.trim(),
          description: description.trim(),
          plan_description: planDescription.trim(),
          jmx_content: jmxContent,
        }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || '保存脚本失败');
      }

      toast.success('测试场景脚本已更新');
      onSuccess();
      onClose();
    } catch (err: any) {
      toast.error(err.message || '保存失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 120,
        background: 'rgba(0,0,0,0.6)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 24,
      }}
    >
      <div
        style={{
          width: '90%',
          maxWidth: 960,
          maxHeight: '90vh',
          background: 'var(--bg-card)',
          borderRadius: 8,
          border: '1px solid var(--border)',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          boxShadow: '0 20px 25px -5px rgba(0,0,0,0.3)',
        }}
      >
        {/* Modal 头部 */}
        <div
          style={{
            padding: '14px 20px',
            borderBottom: '1px solid var(--border)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            background: 'var(--bg-base)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <FileCode size={18} color="var(--accent)" />
            <strong style={{ fontSize: 15 }}>编辑测试脚本 - {script.name}</strong>
          </div>
          <button
            onClick={onClose}
            style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', padding: 4 }}
          >
            <X size={18} />
          </button>
        </div>

        {/* Modal 内容区 */}
        <div style={{ flex: 1, overflowY: 'auto', padding: 20, display: 'flex', flexDirection: 'column', gap: 16 }}>
          {/* 基本信息 */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
            <div>
              <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 6 }}>
                场景名称 <span style={{ color: '#ef4444' }}>*</span>
              </label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="例如：云平台批量新增用户"
                style={{
                  width: '100%',
                  padding: '8px 12px',
                  borderRadius: 6,
                  border: '1px solid var(--border)',
                  background: 'var(--bg-base)',
                  color: 'var(--text-primary)',
                  fontSize: 13,
                  outline: 'none',
                }}
              />
            </div>

            <div>
              <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 6 }}>
                场景描述 (可选)
              </label>
              <input
                type="text"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="简要描述场景业务目标与范围"
                style={{
                  width: '100%',
                  padding: '8px 12px',
                  borderRadius: 6,
                  border: '1px solid var(--border)',
                  background: 'var(--bg-base)',
                  color: 'var(--text-primary)',
                  fontSize: 13,
                  outline: 'none',
                }}
              />
            </div>
          </div>

          <div>
            <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 6 }}>
              关联测试方案描述 (Prompt 意图说明)
            </label>
            <textarea
              rows={2}
              value={planDescription}
              onChange={(e) => setPlanDescription(e.target.value)}
              placeholder="测试方案描述..."
              style={{
                width: '100%',
                padding: '8px 12px',
                borderRadius: 6,
                border: '1px solid var(--border)',
                background: 'var(--bg-base)',
                color: 'var(--text-primary)',
                fontSize: 12,
                outline: 'none',
                resize: 'vertical',
              }}
            />
          </div>

          {/* JMX 内容在线编辑 */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, flex: 1 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <label style={{ fontSize: 12, fontWeight: 600, display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                <Code2 size={14} color="var(--accent)" />
                JMX 脚本源码 (.jmx XML) <span style={{ color: '#ef4444' }}>*</span>
              </label>

              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                  {jmxContent ? `${jmxContent.length} 字符` : '空脚本'}
                </span>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".jmx,.xml"
                  onChange={handleFileUpload}
                  style={{ display: 'none' }}
                />
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  style={{
                    padding: '4px 10px',
                    borderRadius: 4,
                    border: '1px solid var(--border)',
                    background: 'var(--bg-base)',
                    color: 'var(--text-primary)',
                    fontSize: 11,
                    cursor: 'pointer',
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 4,
                  }}
                >
                  <Upload size={12} />
                  上传新 JMX 覆盖
                </button>
              </div>
            </div>

            <textarea
              rows={16}
              value={jmxContent}
              onChange={(e) => setJmxContent(e.target.value)}
              placeholder="请输入或粘贴标准的 JMeter JMX XML 脚本内容..."
              style={{
                width: '100%',
                padding: '12px',
                borderRadius: 6,
                border: '1px solid var(--border)',
                background: 'var(--bg-base)',
                color: 'var(--text-primary)',
                fontFamily: 'Consolas, Monaco, "Courier New", monospace',
                fontSize: 12,
                lineHeight: 1.5,
                outline: 'none',
                resize: 'vertical',
                whiteSpace: 'pre',
              }}
            />
          </div>
        </div>

        {/* Modal 底部 */}
        <div
          style={{
            padding: '12px 20px',
            borderTop: '1px solid var(--border)',
            background: 'var(--bg-base)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'flex-end',
            gap: 10,
          }}
        >
          <button
            onClick={onClose}
            disabled={saving}
            style={{
              padding: '6px 14px',
              borderRadius: 6,
              border: '1px solid var(--border)',
              background: 'var(--bg-card)',
              color: 'var(--text-primary)',
              fontSize: 13,
              cursor: 'pointer',
            }}
          >
            取消
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            style={{
              padding: '6px 16px',
              borderRadius: 6,
              border: 'none',
              background: 'var(--accent)',
              color: '#fff',
              fontSize: 13,
              fontWeight: 600,
              cursor: saving ? 'not-allowed' : 'pointer',
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
            }}
          >
            <Save size={14} />
            {saving ? '保存中...' : '保存更新'}
          </button>
        </div>
      </div>
    </div>
  );
}
