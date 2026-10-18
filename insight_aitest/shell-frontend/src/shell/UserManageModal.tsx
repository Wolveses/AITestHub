import { useEffect, useState } from 'react';
import { Users, X, Key, UserCheck, UserX, CheckCircle2 } from 'lucide-react';

interface UserItem {
  id: number;
  username: string;
  display_name: string;
  role: string;
  is_active: boolean;
  created_at: string;
}

export function UserManageModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [users, setUsers] = useState<UserItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  // 重置密码状态
  const [resetUserId, setResetUserId] = useState<number | null>(null);
  const [newPassword, setNewPassword] = useState('');
  const [resetting, setResetting] = useState(false);

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

  useEffect(() => {
    if (open) {
      fetchUsers();
      setMessage(null);
      setError(null);
      setResetUserId(null);
    }
  }, [open]);

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
      if (!res.ok) throw new Error(data.detail || '重置密码失败');
      setMessage(data.message);
      setResetUserId(null);
      setNewPassword('');
    } catch (err: any) {
      alert(err.message);
    } finally {
      setResetting(false);
    }
  };

  const handleToggleActive = async (userId: number, currentActive: boolean) => {
    try {
      const res = await fetch(`/api/platform/auth/users/${userId}/toggle-active?active=${!currentActive}`, {
        method: 'POST',
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || '操作失败');
      setMessage(data.message);
      fetchUsers();
    } catch (err: any) {
      alert(err.message);
    }
  };

  if (!open) return null;

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 1000,
        background: 'rgba(0, 0, 0, 0.6)',
        backdropFilter: 'blur(4px)',
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
          maxWidth: 780,
          maxHeight: '85vh',
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
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Users size={18} style={{ color: 'var(--accent)' }} />
            <h3 style={{ margin: 0, fontSize: 16, fontWeight: 600, color: 'var(--text-primary)' }}>
              用户管理（管理员专属）
            </h3>
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
              gap: 6,
            }}
          >
            <CheckCircle2 size={15} />
            <span>{message}</span>
          </div>
        )}

        {/* 内容表格 */}
        <div style={{ flex: 1, overflow: 'auto', padding: '16px 20px' }}>
          {loading ? (
            <div style={{ textAlign: 'center', padding: '40px 0', color: 'var(--text-muted)' }}>
              加载用户列表中…
            </div>
          ) : error ? (
            <div style={{ textAlign: 'center', padding: '40px 0', color: 'var(--error)' }}>
              {error}
            </div>
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border)', color: 'var(--text-muted)', textAlign: 'left' }}>
                  <th style={{ padding: '8px 12px' }}>账号</th>
                  <th style={{ padding: '8px 12px' }}>显示名称</th>
                  <th style={{ padding: '8px 12px' }}>角色</th>
                  <th style={{ padding: '8px 12px' }}>状态</th>
                  <th style={{ padding: '8px 12px' }}>注册时间</th>
                  <th style={{ padding: '8px 12px', textAlign: 'right' }}>操作</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id} style={{ borderBottom: '1px solid var(--border-subtle, rgba(255,255,255,0.05))' }}>
                    <td style={{ padding: '10px 12px', fontWeight: 500, color: 'var(--text-primary)' }}>
                      {u.username}
                      {u.username === 'admin' && (
                        <span style={{ marginLeft: 6, fontSize: 10, background: 'rgba(16,185,129,0.15)', color: 'var(--accent)', padding: '1px 6px', borderRadius: 4 }}>
                          超级管理员
                        </span>
                      )}
                    </td>
                    <td style={{ padding: '10px 12px', color: 'var(--text-secondary)' }}>{u.display_name}</td>
                    <td style={{ padding: '10px 12px', color: 'var(--text-secondary)' }}>
                      {u.role === 'admin' ? '管理员' : '测试人员'}
                    </td>
                    <td style={{ padding: '10px 12px' }}>
                      <span style={{ color: u.is_active ? 'var(--accent)' : 'var(--error)' }}>
                        {u.is_active ? '正常' : '已停用'}
                      </span>
                    </td>
                    <td style={{ padding: '10px 12px', color: 'var(--text-muted)', fontSize: 12 }}>
                      {u.created_at ? u.created_at.replace('T', ' ').slice(0, 19) : '-'}
                    </td>
                    <td style={{ padding: '10px 12px', textAlign: 'right' }}>
                      <div style={{ display: 'inline-flex', gap: 8, alignItems: 'center' }}>
                        {/* 修改密码按钮 */}
                        <button
                          onClick={() => {
                            setResetUserId(u.id);
                            setNewPassword('');
                          }}
                          style={{
                            background: 'none',
                            border: '1px solid var(--border)',
                            color: 'var(--text-secondary)',
                            borderRadius: 6,
                            padding: '4px 8px',
                            fontSize: 12,
                            cursor: 'pointer',
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: 4,
                          }}
                        >
                          <Key size={13} /> 修改密码
                        </button>

                        {/* 启停按钮（admin 除外） */}
                        {u.username !== 'admin' && (
                          <button
                            onClick={() => handleToggleActive(u.id, u.is_active)}
                            style={{
                              background: 'none',
                              border: `1px solid ${u.is_active ? 'rgba(239, 68, 68, 0.3)' : 'rgba(16, 185, 129, 0.3)'}`,
                              color: u.is_active ? 'var(--error)' : 'var(--accent)',
                              borderRadius: 6,
                              padding: '4px 8px',
                              fontSize: 12,
                              cursor: 'pointer',
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: 4,
                            }}
                          >
                            {u.is_active ? <UserX size={13} /> : <UserCheck size={13} />}
                            {u.is_active ? '停用' : '启用'}
                          </button>
                        )}
                      </div>

                      {/* 内联重置密码输入浮层 */}
                      {resetUserId === u.id && (
                        <div
                          style={{
                            marginTop: 8,
                            padding: '8px 12px',
                            background: 'var(--bg-elevated)',
                            borderRadius: 8,
                            border: '1px solid var(--border)',
                            display: 'flex',
                            alignItems: 'center',
                            gap: 8,
                            justifyContent: 'flex-end',
                          }}
                        >
                          <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>新密码:</span>
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
          )}
        </div>
      </div>
    </div>
  );
}
