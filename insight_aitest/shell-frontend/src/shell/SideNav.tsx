import { useState } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { ChevronDown, ChevronRight, FileText, Globe, Bug, ListChecks } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { moduleIcons, platformIcons } from './icons';
import type { ModuleManifest } from './types';
import type { ComponentType } from 'react';

interface SideNavProps {
  modules: ModuleManifest[];
  collapsed: boolean;
  isMobile?: boolean;
  onNavigate?: () => void;
}

// 分组渲染顺序
const CATEGORY_ORDER = ['agent', 'assets', 'testing', 'ai', 'infra'];

export function SideNav({ modules, collapsed, isMobile, onNavigate }: SideNavProps) {
  const { t, i18n } = useTranslation();
  const location = useLocation();
  const [kbExpanded, setKbExpanded] = useState(true);

  // 分组标题。agent 组无标题（直接放顶部），其余组显示标题。
  const CATEGORY_LABELS: Record<string, string> = {
    agent: '',
    assets: t('nav.assets'),
    testing: t('nav.capabilities'),
    ai: t('nav.aiGroup'),
    infra: t('nav.infrastructure'),
  };

  // 当前语言的模块名（优先从 i18n 字典匹配 nav.{moduleId}，如未配置则降级使用 manifest 名称）
  const moduleName = (m: ModuleManifest) => {
    const key = `nav.${m.id}`;
    const translated = t(key);
    if (translated && translated !== key) return translated;
    if (i18n.language === 'en-US') return m.name.en ?? m.name.zh ?? m.id;
    return m.name.zh ?? m.name.en ?? m.id;
  };

  // 移动端：覆盖式抽屉（fixed，280 宽，避 TopBar 60px）；桌面：原 200↔0 in-flow
  const width = isMobile ? 280 : collapsed ? 0 : 200;

  // 临时屏蔽 API 自动化、性能监控、UI 自动化菜单
  const HIDDEN_MODULE_IDS = new Set(['api', 'performance', 'ui']);

  const grouped = modules
    .filter((m) => !HIDDEN_MODULE_IDS.has(m.id))
    .reduce<Record<string, ModuleManifest[]>>((acc, m) => {
      (acc[m.category] ??= []).push(m);
      return acc;
    }, {});

  // 移动端与桌面：collapsed=true 时不渲染内容
  const hidden = collapsed;

  return (
    <nav
      style={{
        width,
        minWidth: collapsed && !isMobile ? 0 : 200,
        background: 'var(--bg-base)',
        borderRight: '1px solid var(--bg-card)',
        overflow: 'hidden',
        transition: 'width 0.2s',
        padding: hidden ? 0 : '12px 0',
        flexShrink: 0,
        ...(isMobile
          ? {
              position: 'fixed',
              top: 60,
              bottom: 0,
              left: 0,
              zIndex: 50,
              boxShadow: '2px 0 12px rgba(0,0,0,0.4)',
            }
          : {}),
      }}
    >
      {hidden ? null : (
        <>
          {/* Agent 为核心：直接放顶部，无分组标题 */}
          {(grouped['agent'] ?? [])
            .filter((m) => m.frontend)
            .sort((a, b) => a.order - b.order)
            .map((m) => {
              const Icon = moduleIcons[m.icon];
              return (
                <NavItem
                  key={m.id}
                  to={m.frontend!.route}
                  icon={Icon}
                  label={moduleName(m)}
                  isMobile={isMobile}
                  onNavigate={onNavigate}
                />
              );
            })}

          {/* 平台级：首页 + 总览 */}
          <div style={{ marginTop: 16 }}>
            <NavItem to="/" icon={platformIcons.Home} label={t('nav.home')} end isMobile={isMobile} onNavigate={onNavigate} />
            <NavItem to="/overview" icon={platformIcons.Overview} label={t('nav.overview')} isMobile={isMobile} onNavigate={onNavigate} />
          </div>

          {/* 其余分组（按 CATEGORY_ORDER 渲染） */}
          {CATEGORY_ORDER.filter((cat) => cat !== 'agent').map((cat) => {
            const mods = (grouped[cat] ?? []).filter((m) => m.frontend);
            if (mods.length === 0) return null;
            return (
              <div key={cat} style={{ marginTop: 16 }}>
                <div
                  style={{
                    padding: isMobile ? '6px 20px' : '4px 16px',
                    fontSize: 11,
                    color: 'var(--text-muted)',
                    textTransform: 'uppercase',
                  }}
                >
                  {CATEGORY_LABELS[cat] ?? cat}
                </div>
                {mods
                  .sort((a, b) => a.order - b.order)
                  .map((m) => {
                    const Icon = moduleIcons[m.icon];

                    // 针对知识库模块：渲染可展开/收起的二级子菜单（本地文档、飞书文档）
                    if (m.id === 'kb') {
                      // 缺陷库、用例库已提升为与知识库同级的一级入口，知识库不再高亮 /kb/defect 与 /kb/case
                      const isKbActive =
                        location.pathname.startsWith('/kb') &&
                        !location.pathname.startsWith('/kb/defect') &&
                        !location.pathname.startsWith('/kb/case');
                      return (
                        <div key={m.id}>
                          <div
                            onClick={() => setKbExpanded((prev) => !prev)}
                            style={{
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'space-between',
                              padding: isMobile ? '14px 20px' : '8px 16px',
                              color: isKbActive ? 'var(--accent)' : 'var(--text-secondary)',
                              cursor: 'pointer',
                              fontSize: 14,
                              background: isKbActive ? 'color-mix(in srgb, var(--accent) 5%, transparent)' : 'transparent',
                              userSelect: 'none',
                            }}
                          >
                            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                              {Icon ? <Icon size={16} /> : null}
                              <span>{moduleName(m)}</span>
                            </div>
                            <span style={{ opacity: 0.6 }}>
                              {kbExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                            </span>
                          </div>

                          {/* 知识库子菜单：本地文档 & 飞书文档 */}
                          {kbExpanded && (
                            <div style={{ display: 'flex', flexDirection: 'column' }}>
                              <SubNavItem
                                to="/kb/local"
                                icon={FileText}
                                label={t('nav.kbLocal', '本地文档')}
                                isMobile={isMobile}
                                onNavigate={onNavigate}
                              />
                              <SubNavItem
                                to="/kb/feishu"
                                icon={Globe}
                                label={t('nav.kbFeishu', '飞书文档')}
                                isMobile={isMobile}
                                onNavigate={onNavigate}
                              />
                            </div>
                          )}

                          {/* 缺陷库：与知识库同级的一级入口 */}
                          <NavItem
                            to="/kb/defect"
                            icon={Bug}
                            label={t('nav.defectLibrary', '缺陷库')}
                            isMobile={isMobile}
                            onNavigate={onNavigate}
                          />

                          {/* 用例库：与知识库同级的一级入口 */}
                          <NavItem
                            to="/kb/case"
                            icon={ListChecks}
                            label={t('nav.caseLibrary', '用例库')}
                            isMobile={isMobile}
                            onNavigate={onNavigate}
                          />
                        </div>
                      );
                    }

                    return (
                      <NavItem
                        key={m.id}
                        to={m.frontend!.route}
                        icon={Icon}
                        label={moduleName(m)}
                        isMobile={isMobile}
                        onNavigate={onNavigate}
                      />
                    );
                  })}
              </div>
            );
          })}

          {/* 项目管理（平台级页面） */}
          <div style={{ marginTop: 16 }}>
            <NavItem to="/projects" icon={platformIcons.FolderKanban} label={t('nav.projectManagement')} isMobile={isMobile} onNavigate={onNavigate} />
          </div>
        </>
      )}
    </nav>
  );
}

function SubNavItem({
  to,
  icon: Icon,
  label,
  isMobile,
  onNavigate,
}: {
  to: string;
  icon?: ComponentType<{ size?: number }>;
  label: string;
  isMobile?: boolean;
  onNavigate?: () => void;
}) {
  return (
    <NavLink
      to={to}
      onClick={onNavigate}
      style={({ isActive }) => ({
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: isMobile ? '10px 20px 10px 42px' : '6px 16px 6px 36px',
        color: isActive ? 'var(--accent)' : 'var(--text-secondary)',
        textDecoration: 'none',
        fontSize: 13,
        fontWeight: isActive ? 500 : 400,
        background: isActive ? 'color-mix(in srgb, var(--accent) 10%, transparent)' : 'transparent',
        borderLeft: isActive ? '2px solid var(--accent)' : '2px solid transparent',
        transition: 'all 0.15s ease',
      })}
    >
      {Icon ? <Icon size={14} /> : null}
      {label}
    </NavLink>
  );
}

function NavItem({
  to,
  icon: Icon,
  label,
  end,
  isMobile,
  onNavigate,
}: {
  to: string;
  icon?: ComponentType<{ size?: number }>;
  label: string;
  end?: boolean;
  isMobile?: boolean;
  onNavigate?: () => void;
}) {
  return (
    <NavLink
      to={to}
      end={end}
      onClick={onNavigate}
      style={({ isActive }) => ({
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        padding: isMobile ? '14px 20px' : '8px 16px',
        color: isActive ? 'var(--accent)' : 'var(--text-secondary)',
        textDecoration: 'none',
        fontSize: 14,
        minHeight: isMobile ? 48 : undefined, // 触控目标 ≥44px
        background: isActive ? 'color-mix(in srgb, var(--accent) 8%, transparent)' : 'transparent',
        borderLeft: isActive ? '2px solid var(--accent)' : '2px solid transparent',
      })}
    >
      {Icon ? <Icon size={16} /> : null}
      {label}
    </NavLink>
  );
}
