import { useEffect, useState } from 'react';
import {
  Users,
  X,
  Key,
  UserCheck,
  UserX,
  CheckCircle2,
  FileText,
  RotateCw,
  Search,
  Filter,
} from 'lucide-react';

interface UserItem {
  id: number;
  username: string;
  display_name: string;
  role: string;
  is_active: boolean;
  created_at: string;
}

interface AuditLogItem {
  id: number;
  user_id: number | null;
  username: string;
  action: string;
  target_type: string;
  target_id: string;
  detail: string;
  client_ip: string;
  status_code: number;
  created_at: string;
}

export function UserManageModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [activeTab, setActiveTab] = useState<'users' | 'logs'>('users');

  // 用户列表状态
  const [users, setUsers] = useState<UserItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  // 重置密码状态
  const [resetUserId, setResetUserId] = useState<number | null>(null);
  const [newPassword, setNewPassword] = useState('');
  const [resetting, setResetting] = useState(false);

  // 操作日志状态
  const [logs, setLogs] = useState<AuditLogItem[]>([]);
  const [logsTotal, setLogsTotal] = useState(0);
  const [logsLoading, setLogsLoading] = useState(false);
  const [searchUsername, setSearchUsername] = useState('');
  const [filterTargetType, setFilterTargetType] = useState('');

  const fetchUsers = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch('/api/platform/auth/users');
      if (!res.ok) {
        throw new Error('获取用户列表失败');
      }
      const data = await res.json();
      setUsers(data);
    } catch (err: any) {
      setError(err.message || '网络异常');
    } finally {
      setLoading(false);
    }
  };

  const fetchLogs = async () => {
    setLogsLoading(true);
    try {
      const params = new URLSearchParams();
      params.set('limit', '100');
      if (searchUsername) params.set('username', searchUsername);
      if (filterTargetType) params.set('target_type', filterTargetType);

      const res = await fetch(`/api/platform/auth/audit-logs?${params.toString()}`);
      if (!res.ok) {
        throw new Error('获取审计日志失败');
      }
      const data = await res.json();
      setLogs(data.items || []);
      setLogsTotal(data.total || 0);
    } catch (err: any) {
      console.error('Fetch logs error:', err);
    } finally {
      setLogsLoading(false);
    }
  };

  useEffect(() => {
    if (open) {
      fetchUsers();
      fetchLogs();
      setMessage(null);
      setError(null);
      setResetUserId(null);
    }
  }, [open]);

  useEffect(() => {
    if (open && activeTab === 'logs') {
      fetchLogs();
    }
  }, [activeTab, filterTargetType]);

  const handleResetPassword = async (userId: number) => {
    if (!newPassword || newPassword.length < 6) {
      alert('新密码长度至少 6 位');
      return;
    }
    setResetting(true);
    try {
      const res = await fetch(`/api/platform/auth/users/${userId}/reset-password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ new_password: newPassword }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || '重置密码失败');
      }
      setMessage(data.message || '密码重置成功');
      setResetUserId(null);
      setNewPassword('');
      fetchLogs();
    } catch (err: any) {
      alert(err.message || '操作失败');
    } finally {
      setResetting(false);
    }
  };

  const handleToggleActive = async (userId: number, currentActive: boolean) => {
    const targetStatus = !currentActive;
    const confirmMsg = targetStatus ? '确定要重新启用该用户吗？' : '确定要停用该用户吗？停用后该用户将无法登录。';
    if (!window.confirm(confirmMsg)) return;

    try {
      const res = await fetch(`/api/platform/auth/users/${userId}/toggle-active?active=${targetStatus}`, {
        method: 'POST',
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || '操作失败');
      }
      setMessage(data.message);
      fetchUsers();
      fetchLogs();
    } catch (err: any) {
      alert(err.message || '操作失败');
    }
  };

  if (!open) return null;

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 1000,
        background: 'rgba(0, 0, 0, 0.45)',
        backdropFilter: 'blur(3px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 20,
      }}
      onClick={onClose}
    >
      <div
        style={{
          width: '100%',
          maxWidth: 880,
          maxHeight: '88vh',
          background: 'var(--bg-card)',
          borderRadius: 14,
          border: '1px solid var(--border)',
          boxShadow: 'var(--shadow-popup, 0 16px 48px rgba(0,0,0,0.3))',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div
          style={{
            padding: '16px 20px',
            borderBottom: '1px solid var(--border)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <Users size={18} style={{ color: 'var(--accent)' }} />
              <h3 style={{ margin: 0, fontSize: 16, fontWeight: 600, color: 'var(--text-primary)' }}>
                平台系统管理
              </h3>
            </div>
            {/* 顶部 Tabs 切换 */}
            <div
              style={{
                display: 'flex',
                background: 'var(--bg-elevated)',
                padding: 3,
                borderRadius: 8,
                border: '1px solid var(--border)',
                gap: 4,
              }}
            >
              <button
                onClick={() => setActiveTab('users')}
                style={{
                  padding: '4px 12px',
                  borderRadius: 6,
                  border: 'none',
                  fontSize: 12,
                  fontWeight: activeTab === 'users' ? 600 : 400,
                  background: activeTab === 'users' ? 'var(--bg-card)' : 'transparent',
                  color: activeTab === 'users' ? 'var(--accent)' : 'var(--text-secondary)',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 5,
                  boxShadow: activeTab === 'users' ? '0 1px 3px rgba(0,0,0,0.1)' : 'none',
                }}
              >
                <Users size={14} />
                用户列表
              </button>
              <button
                onClick={() => setActiveTab('logs')}
                style={{
                  padding: '4px 12px',
                  borderRadius: 6,
                  border: 'none',
                  fontSize: 12,
                  fontWeight: activeTab === 'logs' ? 600 : 400,
                  background: activeTab === 'logs' ? 'var(--bg-card)' : 'transparent',
                  color: activeTab === 'logs' ? 'var(--accent)' : 'var(--text-secondary)',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 5,
                  boxShadow: activeTab === 'logs' ? '0 1px 3px rgba(0,0,0,0.1)' : 'none',
                }}
              >
                <FileText size={14} />
                操作审计日志
              </button>
            </div>
          </div>
          <button
            onClick={onClose}
            style={{
              background: 'none',
              border: 'none',
              color: 'var(--text-muted)',
              cursor: 'pointer',
              padding: 4,
            }}
          >
            <X size={18} />
          </button>
        </div>

        {/* 提示消息 */}
        {message && (
          <div
            style={{
              margin: '12px 20px 0',
              padding: '8px 12px',
              borderRadius: 6,
              background: 'rgba(16, 185, 129, 0.1)',
              border: '1px solid rgba(16, 185, 129, 0.25)',
              color: 'var(--accent)',
              fontSize: 13,
              display: 'flex',
              alignItems: 'center',
              gap: 8,
            }}
          >
            <CheckCircle2 size={16} />
            <span>{message}</span>
          </div>
        )}

        {/* Error message */}
        {error && (
          <div
            style={{
              margin: '12px 20px 0',
              padding: '8px 12px',
              borderRadius: 6,
              background: 'rgba(239, 68, 68, 0.1)',
              border: '1px solid rgba(239, 68, 68, 0.25)',
              color: '#ef4444',
              fontSize: 13,
            }}
          >
            {error}
          </div>
        )}

        {/* 内容主体 */}
        <div style={{ flex: 1, overflowY: 'auto', padding: 20 }}>
          {activeTab === 'users' ? (
            /* 用户列表 Tab */
            loading ? (
              <div style={{ textAlign: 'center', padding: '40px 0', color: 'var(--text-muted)' }}>
                加载中...
              </div>
            ) : (
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--border)', textAlign: 'left', color: 'var(--text-secondary)' }}>
                    <th style={{ padding: '8px 12px', width: 60 }}>ID</th>
                    <th style={{ padding: '8px 12px' }}>账号</th>
                    <th style={{ padding: '8px 12px' }}>显示名称</th>
                    <th style={{ padding: '8px 12px', width: 90 }}>角色</th>
                    <th style={{ padding: '8px 12px', width: 80 }}>状态</th>
                    <th style={{ padding: '8px 12px', width: 140 }}>注册时间</th>
                    <th style={{ padding: '8px 12px', textAlign: 'right' }}>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {users.map((u) => (
                    <tr
                      key={u.id}
                      style={{
                        borderBottom: '1px solid var(--border)',
                        color: 'var(--text-primary)',
                      }}
                    >
                      <td style={{ padding: '10px 12px', color: 'var(--text-muted)' }}>{u.id}</td>
                      <td style={{ padding: '10px 12px', fontWeight: 600 }}>
                        {u.username}
                        {u.username === 'admin' && (
                          <span
                            style={{
                              marginLeft: 6,
                              fontSize: 10,
                              padding: '1px 5px',
                              borderRadius: 4,
                              background: 'rgba(16, 185, 129, 0.15)',
                              color: 'var(--accent)',
                            }}
                          >
                            内置
                          </span>
                        )}
                      </td>
                      <td style={{ padding: '10px 12px' }}>{u.display_name || '-'}</td>
                      <td style={{ padding: '10px 12px' }}>
                        <span
                          style={{
                            fontSize: 11,
                            padding: '2px 6px',
                            borderRadius: 4,
                            background: u.role === 'admin' ? 'rgba(59, 130, 246, 0.12)' : 'rgba(107, 114, 128, 0.12)',
                            color: u.role === 'admin' ? '#3b82f6' : 'var(--text-secondary)',
                            fontWeight: 500,
                          }}
                        >
                          {u.role === 'admin' ? '管理员' : '测试人员'}
                        </span>
                      </td>
                      <td style={{ padding: '10px 12px' }}>
                        <span
                          style={{
                            fontSize: 11,
                            padding: '2px 6px',
                            borderRadius: 4,
                            background: u.is_active ? 'rgba(16, 185, 129, 0.12)' : 'rgba(239, 68, 68, 0.12)',
                            color: u.is_active ? 'var(--accent)' : '#ef4444',
                            fontWeight: 500,
                          }}
                        >
                          {u.is_active ? '正常' : '已停用'}
                        </span>
                      </td>
                      <td style={{ padding: '10px 12px', color: 'var(--text-muted)', fontSize: 12 }}>
                        {u.created_at ? u.created_at.replace('T', ' ').slice(0, 19) : '-'}
                      </td>
                      <td style={{ padding: '10px 12px', textAlign: 'right' }}>
                        <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                          <button
                            onClick={() => {
                              setResetUserId(resetUserId === u.id ? null : u.id);
                              setNewPassword('');
                            }}
                            title="重置密码"
                            style={{
                              padding: '4px 8px',
                              borderRadius: 4,
                              border: '1px solid var(--border)',
                              background: 'var(--bg-elevated)',
                              color: 'var(--text-primary)',
                              cursor: 'pointer',
                              display: 'flex',
                              alignItems: 'center',
                              gap: 4,
                              fontSize: 11,
                            }}
                          >
                            <Key size={12} />
                            重置密码
                          </button>
                          {u.username !== 'admin' && (
                            <button
                              onClick={() => handleToggleActive(u.id, u.is_active)}
                              title={u.is_active ? '停用用户' : '启用用户'}
                              style={{
                                padding: '4px 8px',
                                borderRadius: 4,
                                border: '1px solid var(--border)',
                                background: u.is_active ? 'rgba(239, 68, 68, 0.08)' : 'rgba(16, 185, 129, 0.08)',
                                color: u.is_active ? '#ef4444' : 'var(--accent)',
                                cursor: 'pointer',
                                display: 'flex',
                                alignItems: 'center',
                                gap: 4,
                                fontSize: 11,
                              }}
                            >
                              {u.is_active ? <UserX size={12} /> : <UserCheck size={12} />}
                              {u.is_active ? '停用' : '启用'}
                            </button>
                          )}
                        </div>

                        {/* 重置密码行内小面板 */}
                        {resetUserId === u.id && (
                          <div
                            style={{
                              marginTop: 8,
                              display: 'flex',
                              alignItems: 'center',
                              gap: 6,
                              justifyContent: 'flex-end',
                            }}
                          >
                            <input
                              type="password"
                              placeholder="至少6位"
                              value={newPassword}
                              onChange={(e) => setNewPassword(e.target.value)}
                              style={{
                                padding: '4px 8px',
                                borderRadius: 4,
                                border: '1px solid var(--border)',
                                background: 'var(--bg-card)',
                                color: 'var(--text-primary)',
                                fontSize: 12,
                                width: 130,
                              }}
                            />
                            <button
                              onClick={() => handleResetPassword(u.id)}
                              disabled={resetting}
                              style={{
                                padding: '4px 10px',
                                borderRadius: 4,
                                background: 'var(--accent)',
                                color: '#fff',
                                border: 'none',
                                fontSize: 12,
                                cursor: 'pointer',
                              }}
                            >
                              {resetting ? '提交…' : '确认修改'}
                            </button>
                            <button
                              onClick={() => setResetUserId(null)}
                              style={{
                                padding: '4px 8px',
                                borderRadius: 4,
                                background: 'none',
                                border: '1px solid var(--border)',
                                color: 'var(--text-muted)',
                                fontSize: 12,
                                cursor: 'pointer',
                              }}
                            >
                              取消
                            </button>
                          </div>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )
          ) : (
            /* 操作审计日志 Tab */
            <div>
              {/* 日志筛选栏 */}
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  marginBottom: 14,
                  gap: 12,
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 4, background: 'var(--bg-elevated)', padding: '4px 8px', borderRadius: 6, border: '1px solid var(--border)' }}>
                    <Search size={14} style={{ color: 'var(--text-muted)' }} />
                    <input
                      type="text"
                      placeholder="按操作人账号过滤"
                      value={searchUsername}
                      onChange={(e) => setSearchUsername(e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && fetchLogs()}
                      style={{
                        background: 'transparent',
                        border: 'none',
                        outline: 'none',
                        color: 'var(--text-primary)',
                        fontSize: 12,
                        width: 130,
                      }}
                    />
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 4, background: 'var(--bg-elevated)', padding: '4px 8px', borderRadius: 6, border: '1px solid var(--border)' }}>
                    <Filter size={14} style={{ color: 'var(--text-muted)' }} />
                    <select
                      value={filterTargetType}
                      onChange={(e) => setFilterTargetType(e.target.value)}
                      style={{
                        background: 'transparent',
                        border: 'none',
                        outline: 'none',
                        color: 'var(--text-primary)',
                        fontSize: 12,
                        cursor: 'pointer',
                      }}
                    >
                      <option value="">全部目标</option>
                      <option value="用户">用户</option>
                      <option value="用户认证">用户认证</option>
                      <option value="用户安全">用户安全</option>
                      <option value="个人设置">个人设置</option>
                      <option value="项目">项目</option>
                      <option value="测试任务">测试任务</option>
                      <option value="AI会话">AI会话</option>
                      <option value="知识库">知识库</option>
                    </select>
                  </div>
                  <button
                    onClick={fetchLogs}
                    style={{
                      padding: '4px 10px',
                      borderRadius: 6,
                      background: 'var(--accent)',
                      color: '#fff',
                      border: 'none',
                      fontSize: 12,
                      cursor: 'pointer',
                    }}
                  >
                    查询
                  </button>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>共 {logsTotal} 条记录</span>
                  <button
                    onClick={fetchLogs}
                    title="刷新"
                    style={{
                      background: 'none',
                      border: '1px solid var(--border)',
                      padding: 4,
                      borderRadius: 4,
                      cursor: 'pointer',
                      color: 'var(--text-secondary)',
                      display: 'flex',
                      alignItems: 'center',
                    }}
                  >
                    <RotateCw size={13} className={logsLoading ? 'spin' : ''} />
                  </button>
                </div>
              </div>

              {/* 日志列表表格 */}
              {logsLoading ? (
                <div style={{ textAlign: 'center', padding: '40px 0', color: 'var(--text-muted)' }}>
                  加载中...
                </div>
              ) : logs.length === 0 ? (
                <div style={{ textAlign: 'center', padding: '40px 0', color: 'var(--text-muted)', fontSize: 13 }}>
                  暂无审计日志记录
                </div>
              ) : (
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid var(--border)', textAlign: 'left', color: 'var(--text-secondary)' }}>
                      <th style={{ padding: '8px 10px', width: 60 }}>ID</th>
                      <th style={{ padding: '8px 10px', width: 100 }}>操作人</th>
                      <th style={{ padding: '8px 10px', width: 110 }}>操作目标</th>
                      <th style={{ padding: '8px 10px' }}>操作详情</th>
                      <th style={{ padding: '8px 10px', width: 120 }}>客户端 IP</th>
                      <th style={{ padding: '8px 10px', width: 60 }}>状态</th>
                      <th style={{ padding: '8px 10px', width: 140 }}>时间</th>
                    </tr>
                  </thead>
                  <tbody>
                    {logs.map((log) => (
                      <tr
                        key={log.id}
                        style={{
                          borderBottom: '1px solid var(--border)',
                          color: 'var(--text-primary)',
                        }}
                      >
                        <td style={{ padding: '8px 10px', color: 'var(--text-muted)' }}>{log.id}</td>
                        <td style={{ padding: '8px 10px', fontWeight: 600 }}>{log.username}</td>
                        <td style={{ padding: '8px 10px' }}>
                          <span
                            style={{
                              fontSize: 11,
                              padding: '2px 6px',
                              borderRadius: 4,
                              background: 'var(--bg-elevated)',
                              border: '1px solid var(--border)',
                              color: 'var(--text-primary)',
                              fontWeight: 500,
                            }}
                          >
                            {log.target_type || '-'}
                          </span>
                        </td>
                        <td
                          style={{
                            padding: '8px 10px',
                            color: 'var(--text-primary)',
                          }}
                          title={log.detail}
                        >
                          {log.detail}
                        </td>
                        <td style={{ padding: '8px 10px', color: 'var(--text-muted)', fontFamily: 'monospace' }}>
                          {log.client_ip || '-'}
                        </td>
                        <td style={{ padding: '8px 10px' }}>
                          <span
                            style={{
                              fontSize: 10,
                              padding: '1px 4px',
                              borderRadius: 3,
                              color: log.status_code >= 200 && log.status_code < 400 ? 'var(--accent)' : '#ef4444',
                              background:
                                log.status_code >= 200 && log.status_code < 400
                                  ? 'rgba(16, 185, 129, 0.1)'
                                  : 'rgba(239, 68, 68, 0.1)',
                              fontWeight: 600,
                            }}
                          >
                            {log.status_code}
                          </span>
                        </td>
                        <td style={{ padding: '8px 10px', color: 'var(--text-muted)', fontSize: 11 }}>
                          {log.created_at}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
