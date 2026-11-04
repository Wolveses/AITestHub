import { useState } from 'react';
import { useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Menu, X, Users, LogOut, Sun, Moon } from 'lucide-react';
import { platformIcons } from './icons';
import { SettingsPanel } from '../modules/ai/components/SettingsPanel';
import { useIsMobile } from '../shared/hooks/useIsMobile';
import LanguageSwitcher from '../shared/components/LanguageSwitcher';
import { useAuthStore } from '../shared/store/authStore';
import { useThemeStore } from '../shared/store/themeStore';
import { UserManageModal } from './UserManageModal';
import { ProjectSelector } from './ProjectSelector';

/**
 * 判断当前路由是否属于项目作用域页面（用例库、缺陷库、UI/API 自动化、用例管理等）。
 * 全局资源（知识库本地/飞书文档、Agent 对话、系统概览等）不属于项目作用域。
 */
export function isProjectScopedRoute(pathname: string): boolean {
  if (pathname.startsWith('/kb/defect') || pathname.startsWith('/kb/case')) {
    return true;
  }
  if (
    pathname.startsWith('/testcase') ||
    pathname.startsWith('/ui-runner') ||
    pathname.startsWith('/api-runner') ||
    pathname.startsWith('/performance')
  ) {
    return true;
  }
  return false;
}

interface TopBarProps {
  onToggleSidebar: () => void;
}

export function TopBar({ onToggleSidebar }: TopBarProps) {
  const { t } = useTranslation();
  const location = useLocation();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [userManageOpen, setUserManageOpen] = useState(false);
  const { user, logout } = useAuthStore();
  const { theme, toggleTheme } = useThemeStore();
  const isMobile = useIsMobile();
  const isProjectScoped = isProjectScopedRoute(location.pathname);

  return (
    <>
      <header
        style={{
          height: 60,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0 16px',
          background: "var(--bg-base)",
          borderBottom: '1px solid var(--bg-card)',
          color: "var(--text-primary)",
          flexShrink: 0,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <button
            onClick={onToggleSidebar}
            style={{
              background: 'none',
              border: 'none',
              color: "var(--text-primary)",
              cursor: 'pointer',
              fontSize: 18,
              ...(isMobile ? { minWidth: 44, minHeight: 44, display: 'flex', alignItems: 'center', justifyContent: 'center', borderRadius: 4 } : {}),
            }}
            aria-label={t('topbar.toggleSidebar')}
          >
            <Menu size={18} strokeWidth={1.5} />
          </button>
          <strong style={{ whiteSpace: 'nowrap' }}>AITest 平台</strong>

          {/* 仅在项目相关页面生效并展示顶部项目选择器 */}
          {isProjectScoped && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginLeft: 6 }}>
              <div
                style={{
                  width: 1,
                  height: 16,
                  background: 'var(--border, rgba(255,255,255,0.15))',
                }}
              />
              <ProjectSelector />
            </div>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          <LanguageSwitcher />

          {/* 主题切换（对所有用户开放） */}
          <button
            onClick={toggleTheme}
            title={theme === 'dark' ? '切换为浅色模式' : '切换为深色模式'}
            style={{
              background: 'none',
              border: 'none',
              color: 'var(--text-secondary)',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              padding: 4,
              ...(isMobile ? { minWidth: 44, minHeight: 44, justifyContent: 'center', borderRadius: 4 } : {}),
            }}
            aria-label="切换主题"
          >
            {theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
          </button>

          {/* 平台设置（仅管理员可见） */}
          {user?.role === 'admin' && (
            <button
              onClick={() => setSettingsOpen(true)}
              title={t('topbar.modelAndPlatformSettings')}
              style={{
                background: 'none',
                border: 'none',
                color: settingsOpen ? "var(--accent)" : "var(--text-secondary)",
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                padding: 4,
                ...(isMobile ? { minWidth: 44, minHeight: 44, justifyContent: 'center', borderRadius: 4 } : {}),
              }}
              aria-label={t('topbar.settings')}
            >
              <platformIcons.Settings size={18} />
            </button>
          )}

          {/* 用户管理入口（仅管理员可见） */}
          {user?.role === 'admin' && (
            <button
              onClick={() => setUserManageOpen(true)}
              title="用户管理（管理员）"
              style={{
                background: 'none',
                border: 'none',
                color: userManageOpen ? 'var(--accent)' : 'var(--text-secondary)',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                padding: 4,
              }}
            >
              <Users size={18} />
            </button>
          )}

          {/* 用户信息与登出 */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, paddingLeft: 6, borderLeft: '1px solid var(--border)' }}>
            <div
              style={{
                width: 28,
                height: 28,
                borderRadius: '50%',
                background: user?.role === 'admin' ? 'rgba(16,185,129,0.2)' : 'rgba(59,130,246,0.2)',
                color: user?.role === 'admin' ? 'var(--accent)' : 'var(--primary, #3b82f6)',
                border: '1px solid currentColor',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: 12,
                fontWeight: 600,
              }}
            >
              {(user?.display_name || user?.username || 'U').slice(0, 1).toUpperCase()}
            </div>
            {!isMobile && (
              <span style={{ fontSize: 13, color: 'var(--text-primary)', fontWeight: 500, maxWidth: 100, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {user?.display_name || user?.username}
              </span>
            )}
            <button
              onClick={() => logout()}
              title="退出登录"
              style={{
                background: 'none',
                border: 'none',
                color: 'var(--text-muted)',
                cursor: 'pointer',
                padding: '4px',
                display: 'flex',
                alignItems: 'center',
              }}
            >
              <LogOut size={16} />
            </button>
          </div>
        </div>
      </header>

      {/* 管理员用户管理弹窗 */}
      <UserManageModal
        open={userManageOpen}
        onClose={() => setUserManageOpen(false)}
      />

      {settingsOpen && (
        <div
          onClick={() => setSettingsOpen(false)}
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0,0,0,0.6)',
            zIndex: 1000,
            display: 'flex',
            alignItems: 'flex-start',
            justifyContent: 'center',
            paddingTop: 40,
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              width: 'min(640px, 92vw)',
              maxHeight: '85vh',
              background: "var(--bg-base)",
              border: '1px solid var(--bg-elevated)',
              borderRadius: 10,
              overflow: 'hidden',
              display: 'flex',
              flexDirection: 'column',
              boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
            }}
          >
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '12px 20px',
                borderBottom: '1px solid var(--bg-card)',
                flexShrink: 0,
              }}
            >
              <strong style={{ color: "var(--text-primary)", fontSize: 14 }}>{t('topbar.platformSettings')}</strong>
              <button
                onClick={() => setSettingsOpen(false)}
                style={{
                  background: 'none',
                  border: 'none',
                  color: "var(--text-secondary)",
                  cursor: 'pointer',
                  fontSize: 18,
                }}
                aria-label={t('common.close')}
              >
                <X size={16} strokeWidth={1.5} />
              </button>
            </div>
            <div style={{ overflow: 'auto' }}>
              <SettingsPanel />
            </div>
          </div>
        </div>
      )}
    </>
  );
}
