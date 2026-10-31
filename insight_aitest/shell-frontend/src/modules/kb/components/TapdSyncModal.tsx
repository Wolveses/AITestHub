import { useEffect, useRef, useState, type CSSProperties } from 'react';
import { AlertTriangle, Bug, ListChecks, RefreshCw, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useProjectStore } from '../../../shared/store/projectStore';
import { useKnowledgeStore } from '../store/knowledgeStore';

export interface TapdProgress {
  running: boolean;
  /** scan=扫描源数据（total 未知）/ folders=同步目录 / sync=写入需更新条目 / done=结束 */
  phase?: string;
  /** 扫描阶段已拉取条目数 */
  scanned?: number;
  /** 用例同步的目录阶段计数 */
  folders_total?: number;
  folders_done?: number;
  /** 需更新条目数（新增 + 源已变更） */
  total: number;
  done: number;
  created: number;
  updated: number;
  skipped: number;
  failed: number;
  message: string;
}

interface TapdConfig {
  configured: boolean;
  backfill_days: number;
  progress: TapdProgress;
}

interface TapdSyncModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** 同步对象：缺陷（默认）或用例 */
  mode?: 'bug' | 'case';
  /** 同步结束（running=false 且 total>0）后回调，用于刷新缺陷/用例列表 */
  onSynced?: () => void;
}

async function readError(r: Response): Promise<string> {
  let msg = `HTTP ${r.status}`;
  try {
    const body = await r.json();
    msg = body?.detail || body?.message || msg;
  } catch {
    try {
      const text = await r.text();
      if (text) msg = text;
    } catch {
      /* 非 JSON 响应，保留状态码信息 */
    }
  }
  return msg;
}

// 上次成功发起同步的参数：工作空间与回填天数，用于下次打开弹窗时默认回显。
// 缺陷与用例分开存储，避免互相覆盖。
const LAST_SYNC_KEY = 'insight_aitest.tapd_last_sync';
const LAST_SYNC_KEY_CASE = 'insight_aitest.tapd_last_sync.case';

function loadLastSync(key: string): { workspaceId: string; backfillDays: number | null } | null {
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return null;
    const data = JSON.parse(raw) as { workspace_id?: string; backfill_days?: number | null };
    const workspaceId = (data.workspace_id || '').trim();
    if (!workspaceId) return null;
    const days = Number(data.backfill_days);
    // 空值/非法值表示上次选择的是全量同步，回显时保持为空
    return { workspaceId, backfillDays: Number.isFinite(days) && days > 0 ? days : null };
  } catch {
    return null;
  }
}

function saveLastSync(key: string, workspaceId: string, backfillDays: number | null): void {
  try {
    window.localStorage.setItem(
      key,
      JSON.stringify({ workspace_id: workspaceId, backfill_days: backfillDays }),
    );
  } catch {
    /* localStorage 不可用时忽略 */
  }
}

export function TapdSyncModal({ open, onOpenChange, mode = 'bug', onSynced }: TapdSyncModalProps) {
  const { t } = useTranslation();
  // 绑定项目由缺陷库/用例库页面选定，弹窗不再单独选择项目
  // 两个库各自使用独立的项目上下文，避免影响知识库文档列表的项目过滤
  const isCase = mode === 'case';
  const { projects, loadProjects } = useProjectStore();
  const currentProjectId = useKnowledgeStore((s) => (isCase ? s.caseProjectId : s.defectProjectId));

  // 缺陷与用例使用不同的 TAPD 接口
  const apiBase = isCase ? '/api/modules/kb/tapd/cases' : '/api/modules/kb/tapd';
  const syncUrl = `${apiBase}/sync`;
  const progressUrl = `${apiBase}/progress`;
  const lastSyncKey = isCase ? LAST_SYNC_KEY_CASE : LAST_SYNC_KEY;

  const [configured, setConfigured] = useState<boolean | null>(null);
  const [loadingConfig, setLoadingConfig] = useState(false);
  const [workspaceId, setWorkspaceId] = useState('');
  // 空值表示全量同步（不按天数过滤）
  const [backfillDays, setBackfillDays] = useState<number | ''>('');
  const [submitting, setSubmitting] = useState(false);
  const [polling, setPolling] = useState(false);
  const [progress, setProgress] = useState<TapdProgress | null>(null);
  const [error, setError] = useState('');

  // onSynced 每次父组件渲染都可能是新函数，用 ref 避免轮询 effect 被反复重建
  const onSyncedRef = useRef(onSynced);
  useEffect(() => {
    onSyncedRef.current = onSynced;
  }, [onSynced]);

  // 打开弹窗：拉取 TAPD 配置与项目列表，并按上次成功参数回显输入
  useEffect(() => {
    if (!open) {
      setPolling(false);
      return;
    }
    let cancelled = false;
    setError('');
    setProgress(null);
    loadProjects();
    const last = loadLastSync(lastSyncKey);
    if (last) {
      setWorkspaceId(last.workspaceId);
      setBackfillDays(last.backfillDays ?? '');
    }

    setLoadingConfig(true);
    fetch(apiBase)
      .then(async (r) => {
        if (!r.ok) throw new Error(await readError(r));
        return (await r.json()) as TapdConfig;
      })
      .then((cfg) => {
        if (cancelled) return;
        setConfigured(!!cfg.configured);
        // 有历史成功记录时以历史值为准，后端默认天数只作为首次使用的兜底
        if (!last && typeof cfg.backfill_days === 'number' && cfg.backfill_days > 0) {
          setBackfillDays(cfg.backfill_days);
        }
        if (cfg.progress) {
          setProgress(cfg.progress);
          // 已有任务在跑：打开弹窗即继续展示进度
          if (cfg.progress.running) setPolling(true);
        }
      })
      .catch((e: Error) => {
        if (cancelled) return;
        setConfigured(null);
        setError(t('kb.tapdLoadFailed', '加载 TAPD 配置失败: {{msg}}', { msg: e.message }));
      })
      .finally(() => {
        if (!cancelled) setLoadingConfig(false);
      });

    return () => {
      cancelled = true;
    };
  }, [open, loadProjects, t, apiBase, lastSyncKey]);

  // 每 2 秒轮询进度；关闭弹窗或轮询结束时清理定时器
  useEffect(() => {
    if (!open || !polling) return;
    let stopped = false;
    const tick = async () => {
      try {
        const r = await fetch(progressUrl);
        if (!r.ok) return;
        const p = (await r.json()) as TapdProgress;
        if (stopped) return;
        setProgress(p);
        // running=false 即结束；total=0 且 message 已生成也算结束（零缺陷场景）
        if (!p.running && (p.total > 0 || !!p.message)) {
          setPolling(false);
          onSyncedRef.current?.();
        }
      } catch {
        /* 单次轮询失败忽略，下次再试 */
      }
    };
    const timer = window.setInterval(tick, 2000);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [open, polling, progressUrl]);

  if (!open) return null;

  // 扫描阶段（总量未知）显示不确定态；写入阶段用「需更新条目数」作分母，百分比取整
  const phase = progress?.phase ?? '';
  const scanning = !!progress?.running && (phase === 'scan' || phase === 'folders');
  const progressPercent = progress && progress.total > 0
    ? Math.min(100, Math.floor((progress.done / progress.total) * 100))
    : 0;
  // 后端初始进度是全零（未开跑）：此时既不算「无需更新」也不算「已完成」，整块隐藏
  const hasProgress = !!progress && (progress.running || progress.total > 0 || !!progress.message);
  const canStart = !!configured && !submitting && !polling && !!workspaceId.trim() && currentProjectId !== null;

  const handleStart = async () => {
    if (!workspaceId.trim()) {
      setError(t('kb.tapdRequireWorkspace', '请填写工作空间 ID'));
      return;
    }
    if (currentProjectId === null) {
      setError(
        isCase
          ? t('kb.tapdCaseSelectProject', '请先在用例库选择项目')
          : t('kb.tapdSelectProject', '请先在缺陷库选择项目'),
      );
      return;
    }
    setSubmitting(true);
    setError('');
    const days = backfillDays === '' ? null : Number(backfillDays);
    try {
      const r = await fetch(syncUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          workspace_id: workspaceId.trim(),
          project_id: currentProjectId,
          backfill_days: days,
        }),
      });
      if (!r.ok) {
        const detail = await readError(r);
        setError(r.status === 409 ? detail : t('kb.tapdSyncFailed', '同步失败: {{msg}}', { msg: detail }));
        return;
      }
      // 仅在成功发起后记忆参数，下次打开弹窗默认回显
      saveLastSync(lastSyncKey, workspaceId.trim(), days);
      setProgress(null);
      setPolling(true);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(t('kb.tapdSyncFailed', '同步失败: {{msg}}', { msg }));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.5)',
        zIndex: 3000,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 16,
      }}
      onClick={() => onOpenChange(false)}
    >
      <div
        style={{
          width: 480,
          maxWidth: '100%',
          background: 'var(--bg-base, #fff)',
          borderRadius: 8,
          boxShadow: '0 8px 30px rgba(0,0,0,0.2)',
          border: '1px solid var(--border, var(--bg-card))',
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* 标题栏 */}
        <div
          style={{
            padding: '14px 16px',
            borderBottom: '1px solid var(--border, var(--bg-card))',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <span style={{ fontSize: 14, fontWeight: 600, display: 'flex', alignItems: 'center', gap: 6 }}>
            {isCase ? <ListChecks size={16} style={{ color: 'var(--accent)' }} /> : <Bug size={16} style={{ color: 'var(--accent)' }} />}
            {isCase
              ? t('kb.tapdCaseModalTitle', '从 TAPD 同步用例')
              : t('kb.tapdModalTitle', '从 TAPD 同步缺陷')}
          </span>
          <button
            onClick={() => onOpenChange(false)}
            aria-label={t('kb.close', '关闭')}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)', padding: 0, display: 'flex' }}
          >
            <X size={16} />
          </button>
        </div>

        <div style={{ padding: 20, display: 'flex', flexDirection: 'column', gap: 14 }}>
          {/* 凭证未配置提示 */}
          {configured === false && (
            <div
              style={{
                display: 'flex',
                gap: 8,
                alignItems: 'flex-start',
                background: 'rgba(239, 68, 68, 0.08)',
                border: '1px solid rgba(239, 68, 68, 0.3)',
                borderRadius: 6,
                padding: '10px 12px',
                fontSize: 12,
                color: '#dc2626',
                lineHeight: 1.5,
              }}
            >
              <AlertTriangle size={14} style={{ flexShrink: 0, marginTop: 1 }} />
              <span>{t('kb.tapdNotConfigured', 'TAPD 凭证未配置，请联系管理员在服务器配置文件填写')}</span>
            </div>
          )}

          {error && (
            <div
              style={{
                background: 'rgba(239, 68, 68, 0.08)',
                border: '1px solid rgba(239, 68, 68, 0.3)',
                borderRadius: 6,
                padding: '8px 12px',
                fontSize: 12,
                color: '#dc2626',
                lineHeight: 1.5,
                wordBreak: 'break-word',
              }}
            >
              {error}
            </div>
          )}

          {/* 工作空间 ID */}
          <div>
            <label style={{ display: 'block', fontSize: 12, color: 'var(--text-muted)', marginBottom: 6 }}>
              {t('kb.tapdWorkspaceId', '工作空间 ID')}
            </label>
            <input
              type="text"
              value={workspaceId}
              onChange={(e) => setWorkspaceId(e.target.value)}
              placeholder={t('kb.tapdWorkspacePlaceholder', '请输入 TAPD 工作空间 ID')}
              style={inputStyle}
            />
          </div>

          {/* 绑定项目：由缺陷库/用例库页面选择，弹窗只读展示 */}
          <div>
            <label style={{ display: 'block', fontSize: 12, color: 'var(--text-muted)', marginBottom: 6 }}>
              {t('kb.tapdBindProject', '绑定项目')}
            </label>
            <div
              style={{
                ...inputStyle,
                display: 'flex',
                alignItems: 'center',
                background: 'var(--bg-card)',
                color: currentProjectId === null ? 'var(--text-muted)' : 'var(--text-primary)',
              }}
            >
              {currentProjectId === null
                ? isCase
                  ? t('kb.tapdCaseSelectProject', '请先在用例库选择项目')
                  : t('kb.tapdSelectProject', '请先在缺陷库选择项目')
                : projects.find((p) => p.id === currentProjectId)?.name || `#${currentProjectId}`}
            </div>
          </div>

          {/* 回填天数 */}
          <div>
            <label style={{ display: 'block', fontSize: 12, color: 'var(--text-muted)', marginBottom: 6 }}>
              {t('kb.tapdBackfillDays', '回填天数')}
            </label>
            <input
              type="number"
              min={1}
              value={backfillDays}
              placeholder={t('kb.tapdBackfillPlaceholder', '留空 = 全量同步')}
              onChange={(e) => setBackfillDays(e.target.value === '' ? '' : Number(e.target.value))}
              style={inputStyle}
            />
            <span style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4, display: 'block' }}>
              {backfillDays === ''
                ? isCase
                  ? t('kb.tapdCaseFullSyncHint', '留空将全量同步所有用例（范围大时耗时较长）')
                  : t('kb.tapdFullSyncHint', '留空将全量同步所有缺陷（范围大时耗时较长）')
                : isCase
                  ? t('kb.tapdCaseBackfillHint', '仅同步最近 {{days}} 天内更新的用例', { days: backfillDays })
                  : t('kb.tapdBackfillHint', '仅同步最近 {{days}} 天内更新的缺陷', { days: backfillDays })}
            </span>
          </div>

          {/* 进度 */}
          {progress && hasProgress && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: 'var(--text-secondary)' }}>
                <span>
                  {progress.running
                    ? scanning
                      ? phase === 'folders'
                        ? t('kb.tapdPhaseFolders', '同步目录 {{done}}/{{total}}', {
                            done: progress.folders_done ?? 0,
                            total: progress.folders_total ?? 0,
                          })
                        : t('kb.tapdPhaseScan', '扫描中 · 已读取 {{n}} 条', { n: progress.scanned ?? 0 })
                      : t('kb.tapdProgressPct', '进度 {{done}}/{{total}}（{{pct}}%）', {
                          done: progress.done,
                          total: progress.total,
                          pct: progressPercent,
                        })
                    : progress.total === 0
                      ? t('kb.tapdNoChanges', '无需更新')
                      : t('kb.tapdProgressPct', '进度 {{done}}/{{total}}（{{pct}}%）', {
                          done: progress.done,
                          total: progress.total,
                          pct: progressPercent,
                        })}
                </span>
                {progress.running ? (
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, color: 'var(--accent)' }}>
                    <RefreshCw size={11} className="animate-spin" />
                    {t('kb.tapdSyncing', '同步中…')}
                  </span>
                ) : (
                  <span style={{ color: 'var(--success, #10b981)' }}>{t('kb.tapdDone', '已完成')}</span>
                )}
              </div>
              <div style={{ height: 6, borderRadius: 3, background: 'var(--bg-card, #f1f5f9)', overflow: 'hidden' }}>
                {progress.running && (scanning || progress.total === 0) ? (
                  // 总量未知（扫描中）时用脉冲满条表达「正在进行」，避免长时间停在 0%
                  <div
                    className="animate-pulse"
                    style={{ width: '100%', height: '100%', background: 'var(--accent, #3b82f6)', opacity: 0.4 }}
                  />
                ) : (
                  <div
                    style={{
                      width: `${progressPercent}%`,
                      height: '100%',
                      background: 'var(--accent, #3b82f6)',
                      transition: 'width 0.3s ease',
                    }}
                  />
                )}
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, fontSize: 11, color: 'var(--text-muted)' }}>
                <span>{t('kb.tapdCreated', '新增 {{n}}', { n: progress.created })}</span>
                <span>{t('kb.tapdUpdated', '更新 {{n}}', { n: progress.updated })}</span>
                <span>{t('kb.tapdSkipped', '跳过 {{n}}', { n: progress.skipped })}</span>
                <span style={{ color: progress.failed > 0 ? 'var(--error)' : undefined }}>
                  {t('kb.tapdFailed', '失败 {{n}}', { n: progress.failed })}
                </span>
              </div>
              {progress.message && (
                <div style={{ fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.5 }}>{progress.message}</div>
              )}
            </div>
          )}

          {loadingConfig && (
            <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{t('kb.loading', '加载中…')}</div>
          )}
        </div>

        {/* 底部按钮 */}
        <div
          style={{
            padding: '12px 16px',
            borderTop: '1px solid var(--border, var(--bg-card))',
            background: 'var(--bg-card)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'flex-end',
            gap: 10,
          }}
        >
          <button
            onClick={() => onOpenChange(false)}
            disabled={submitting}
            style={{
              padding: '6px 14px',
              borderRadius: 6,
              border: '1px solid var(--border)',
              background: 'var(--bg-base)',
              color: 'var(--text-primary)',
              fontSize: 13,
              cursor: submitting ? 'not-allowed' : 'pointer',
            }}
          >
            {t('kb.close', '关闭')}
          </button>
          <button
            onClick={handleStart}
            disabled={!canStart}
            style={{
              padding: '6px 16px',
              borderRadius: 6,
              border: 'none',
              background: 'var(--accent)',
              color: '#fff',
              fontSize: 13,
              fontWeight: 500,
              display: 'inline-flex',
              alignItems: 'center',
              gap: 5,
              cursor: canStart ? 'pointer' : 'not-allowed',
              opacity: canStart ? 1 : 0.6,
            }}
          >
            {(submitting || polling) && <RefreshCw size={12} className="animate-spin" />}
            {polling
              ? t('kb.tapdSyncing', '同步中…')
              : submitting
                ? t('kb.saving', '保存中…')
                : t('kb.tapdStartSync', '开始同步')}
          </button>
        </div>
      </div>
    </div>
  );
}

const inputStyle: CSSProperties = {
  width: '100%',
  background: 'var(--bg-card)',
  border: '1px solid var(--border)',
  color: 'var(--text-primary)',
  padding: '8px 10px',
  borderRadius: 6,
  fontSize: 13,
  outline: 'none',
  boxSizing: 'border-box',
};
