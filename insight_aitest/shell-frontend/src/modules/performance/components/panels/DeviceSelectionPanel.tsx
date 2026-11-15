import { useState, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { Bot, Apple, Smartphone, Circle, Search, ChevronDown, X, Check } from 'lucide-react';
import { useMonitoringStore } from '@/modules/performance/store/monitoringStore';
import { useProjectStore } from '@/shared/store/projectStore';
import { deviceApi } from '@/shared/api/api';
import { DEVICE_GLOBAL_TARGET, isDeviceGlobalTarget, type AppInfo, type Device } from '@/shared/types';

// 按 device_id 去重，保留首次出现的设备记录
function dedupeDevices(deviceList: Device[]): Device[] {
  const seen = new Set<string>();
  return deviceList.filter((device) => {
    if (seen.has(device.device_id)) return false;
    seen.add(device.device_id);
    return true;
  });
}

function getPlatformLabel(type: string): string {
  if (type === 'android') return 'Android';
  if (type === 'ios') return 'iOS';
  return type;
}

// 从应用列表中获取应用友好名称的辅助函数
function getAppNameFromList(apps: AppInfo[], packageName: string): string {
  if (!packageName) return '';
  const app = apps.find(a => a.package_name === packageName);
  return app?.name || packageName;
}

export default function DeviceSelectionPanel() {
  const { t } = useTranslation();
  const { devices, selectedDevice, selectDevice, isMonitoring, currentSession, batteryInfo, setDevices } = useMonitoringStore();
  const [apps, setApps] = useState<AppInfo[]>([]);
  const [monitorMode, setMonitorMode] = useState<'app' | 'device'>('app');
  const [selectedAppPackage, setSelectedAppPackage] = useState<string>('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showAppNotRunningWarning, setShowAppNotRunningWarning] = useState(false);
  const [showBackgroundAppWarning, setShowBackgroundAppWarning] = useState(false);
  const [pendingAppPackage, setPendingAppPackage] = useState<string | null>(null);
  const [pendingAppName, setPendingAppName] = useState<string>('');
  const [pendingAppPid, setPendingAppPid] = useState<number | undefined>(undefined);
  const [appSearchQuery, setAppSearchQuery] = useState<string>('');
  const [appDropdownOpen, setAppDropdownOpen] = useState(false);
  const appDropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (appDropdownRef.current && !appDropdownRef.current.contains(event.target as Node)) {
        setAppDropdownOpen(false);
        setAppSearchQuery('');
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const applyDeviceList = (deviceList: Device[]): string | null => {
    const uniqueDevices = dedupeDevices(deviceList);
    setDevices(uniqueDevices);

    const currentSelected = useMonitoringStore.getState().selectedDevice;
    const stillExists = Boolean(currentSelected && uniqueDevices.some((d) => d.device_id === currentSelected));
    if (stillExists) {
      return currentSelected;
    }

    const onlineDevices = uniqueDevices.filter((d) => d.status === 'online');
    if (onlineDevices.length === 1) {
      const targetId = onlineDevices[0].device_id;
      selectDevice(targetId);
      setSelectedAppPackage('');
      return targetId;
    }

    if (currentSelected) {
      selectDevice('');
      setSelectedAppPackage('');
    }
    return null;
  };

  // 初始加载设备列表
  useEffect(() => {
    const loadDevices = async () => {
      setLoading(true);
      setError(null);
      try {
        const deviceList = await deviceApi.getDevices();
        applyDeviceList(deviceList);
      } catch (err) {
        console.error('Failed to load devices:', err);
        setError(t('device.selectDeviceFirst'));
      } finally {
        setLoading(false);
      }
    };

    loadDevices();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 当选择的设备改变时，加载应用列表
  useEffect(() => {
    const loadApps = async () => {
      if (selectedDevice) {
        setLoading(true);
        try {
          const deviceApps = await deviceApi.getDeviceApps(selectedDevice);
          setApps(deviceApps);
        } catch (err) {
          console.error('Failed to load apps:', err);
          setApps([]);
        } finally {
          setLoading(false);
        }
      } else {
        setApps([]);
      }
    };

    loadApps();
  }, [selectedDevice]);

  // 当前是否处于设备全局监控模式
  const isGlobalMode = isMonitoring
    ? isDeviceGlobalTarget(currentSession?.app_package)
    : monitorMode === 'device';

  // 从会话中获取目标名称（设备全局模式显示本地化“设备全局监控”，否则显示应用名称）
  const currentAppName = isGlobalMode
    ? t('device.globalTarget')
    : (currentSession?.app_name ||
      (selectedAppPackage ? getAppNameFromList(apps, selectedAppPackage) : ''));
  const currentDevice = devices.find(d => d.device_id === selectedDevice);
  const currentDeviceName = currentDevice?.name || currentSession && devices.find(d => d.device_id === currentSession.device_id)?.name || '';

  const handleRefresh = async () => {
    setLoading(true);
    setError(null);
    try {
      const deviceList = await deviceApi.refreshDevices();
      const targetDevice = applyDeviceList(deviceList);
      // 刷新后重新加载应用列表（若已自动选中同一设备，selectedDevice useEffect 仅在变化时触发）
      if (targetDevice && targetDevice === selectedDevice) {
        try {
          const deviceApps = await deviceApi.getDeviceApps(targetDevice);
          setApps(deviceApps);
        } catch (err) {
          console.error('Failed to reload apps:', err);
        }
      }
    } catch (err) {
      console.error('Failed to refresh devices:', err);
      setError(t('device.refreshDevices'));
    } finally {
      setLoading(false);
    }
  };

  const handleDeviceChange = (deviceId: string) => {
    selectDevice(deviceId);
    setSelectedAppPackage('');
    setAppSearchQuery('');
    setAppDropdownOpen(false);
  };

  const handleAppChange = (appPackage: string) => {
    setSelectedAppPackage(appPackage);
    setAppSearchQuery('');
    setAppDropdownOpen(false);
  };

  const handleStartStopMonitoring = async () => {
    if (isMonitoring) {
      await useMonitoringStore.getState().stopMonitoring();
    } else if (selectedDevice && monitorMode === 'device') {
      const device = devices.find(d => d.device_id === selectedDevice);
      const platform = device?.type || 'android';
      try {
        setLoading(true);
        await useMonitoringStore.getState().startMonitoring(
          selectedDevice,
          DEVICE_GLOBAL_TARGET,
          platform,
          undefined,
          useProjectStore.getState().currentProjectId
        );
        if (useMonitoringStore.getState().currentSession) {
          useMonitoringStore.getState().currentSession!.app_name = t('device.globalTarget');
        }
      } catch (err) {
        console.error('Failed to start device global monitoring:', err);
        setError(`${t('device.startMonitorFailed')}: ${(err as Error).message}`);
      } finally {
        setLoading(false);
      }
    } else {
      if (selectedDevice && selectedAppPackage) {
        try {
          // ===== 启动前自动刷新应用列表以获取最新状态 =====
          setLoading(true);
          const latestApps = await deviceApi.getDeviceApps(selectedDevice);
          setApps(latestApps);

          // 检查应用是否在运行（匹配桌面版逻辑）
          const targetApp = latestApps.find(app => app.package_name === selectedAppPackage);
          const device = devices.find(d => d.device_id === selectedDevice);

          // 检查应用是否在运行（iOS 和 Android 统一处理）
          // 注意：iOS 进程检测需要开发者模式，如果未启用，is_running 会是 false
          if (!targetApp || !targetApp.is_running) {
            // 应用未运行，显示警告对话框
            setPendingAppPackage(selectedAppPackage);
            setShowAppNotRunningWarning(true);
            return;
          }

          // ===== 新增：检查应用是否在后台运行（匹配桌面版第1070-1087行）=====
          if (targetApp.status === 'background') {
            // 应用在后台运行，显示警告对话框
            setPendingAppPackage(selectedAppPackage);
            setPendingAppName(targetApp.name);
            setPendingAppPid(targetApp.pid);
            setShowBackgroundAppWarning(true);
            return;
          }

          // 应用正在前台运行，正常启动监控
          const platform = device?.type || 'android';
          const appName = getAppNameFromList(latestApps, selectedAppPackage);
          await useMonitoringStore.getState().startMonitoring(
            selectedDevice,
            selectedAppPackage,
            platform,
            undefined,
            useProjectStore.getState().currentProjectId
          );
          // 更新会话中的应用名称
          if (useMonitoringStore.getState().currentSession) {
            useMonitoringStore.getState().currentSession!.app_name = appName;
          }
        } catch (error) {
          console.error('刷新应用列表失败:', error);
          // 如果刷新失败，使用现有数据继续检查
          const targetApp = apps.find(app => app.package_name === selectedAppPackage);

          if (!targetApp || !targetApp.is_running) {
            setPendingAppPackage(selectedAppPackage);
            setShowAppNotRunningWarning(true);
            return;
          }

          // 检查后台应用
          if (targetApp.status === 'background') {
            setPendingAppPackage(selectedAppPackage);
            setPendingAppName(targetApp.name);
            setPendingAppPid(targetApp.pid);
            setShowBackgroundAppWarning(true);
            return;
          }

          const device = devices.find(d => d.device_id === selectedDevice);
          const platform = device?.type || 'android';
          const appName = getAppNameFromList(apps, selectedAppPackage);
          await useMonitoringStore.getState().startMonitoring(
            selectedDevice,
            selectedAppPackage,
            platform,
            undefined,
            useProjectStore.getState().currentProjectId
          );
          if (useMonitoringStore.getState().currentSession) {
            useMonitoringStore.getState().currentSession!.app_name = appName;
          }
        } finally {
          setLoading(false);
        }
      }
    }
  };

  // 取消启动
  const handleCancelStartNotRunning = () => {
    setShowAppNotRunningWarning(false);
    setPendingAppPackage(null);
  };

  // 确认启动后台应用
  const handleConfirmStartBackground = async () => {
    setShowBackgroundAppWarning(false);
    if (selectedDevice && pendingAppPackage) {
      const device = devices.find(d => d.device_id === selectedDevice);
      const platform = device?.type || 'android';
      try {
        await useMonitoringStore.getState().startMonitoring(
          selectedDevice,
          pendingAppPackage,
          platform,
          undefined,
          useProjectStore.getState().currentProjectId
        );
        if (useMonitoringStore.getState().currentSession) {
          useMonitoringStore.getState().currentSession!.app_name = pendingAppName;
        }
      } catch (error) {
        console.error(t('dialogs.operationFailed'), error);
      } finally {
        setPendingAppPackage(null);
        setPendingAppName('');
        setPendingAppPid(undefined);
      }
    }
  };

  // 取消启动后台应用
  const handleCancelStartBackground = () => {
    setShowBackgroundAppWarning(false);
    setPendingAppPackage(null);
    setPendingAppName('');
    setPendingAppPid(undefined);
  };

  const getPlatformIcon = (type: string) => {
    const Icon = type === 'android' ? Bot : type === 'ios' ? Apple : Smartphone;
    return <Icon size={13} strokeWidth={1.5} />;
  };

  const getStatusText = (status: string) => {
    const statusMap: Record<string, string> = {
      'online': t('device.deviceOnline'),
      'offline': t('device.deviceOffline'),
      'unauthorized': t('device.deviceUnauthorized'),
    };
    return statusMap[status] || status;
  };

  const canStart = Boolean(selectedDevice) && !isMonitoring && (monitorMode === 'device' || Boolean(selectedAppPackage));

  // 过滤并排序应用列表（模糊搜索，运行中应用优先靠前展示）
  const filteredApps = apps
    .filter(app => {
      if (!appSearchQuery.trim()) return true;
      const query = appSearchQuery.trim().toLowerCase();
      return (
        app.name.toLowerCase().includes(query) ||
        app.package_name.toLowerCase().includes(query)
      );
    })
    .sort((a, b) => {
      const rank = (item: AppInfo) =>
        item.is_running && item.status !== 'background' ? 0 : item.is_running ? 1 : 2;
      return rank(a) - rank(b);
    });

  return (
    <div style={{
      padding: '12px',
      display: 'flex',
      flexDirection: 'column',
      gap: '16px',
    }}>
      {/* === 标题 === */}
      <div style={{
        fontSize: '16pt',
        fontWeight: '700',
        color: "var(--accent)",
        padding: '4px 0px',
      }}>
        {t('device.currentTarget')}
      </div>

      {/* 错误提示 */}
      {error && (
        <div style={{
          padding: '8px 12px',
          backgroundColor: 'rgba(127, 29, 29, 0.3)',
          border: '1px solid var(--error)',
          borderRadius: '6px',
          color: 'var(--error)',
          fontSize: '10pt',
        }}>
          {error}
        </div>
      )}

      {/* === 设备选择 === */}
      <div>
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: '8px',
        }}>
          <label style={{
            fontSize: '11pt',
            fontWeight: '600',
            color: "var(--text-secondary)",
          }}>
            {t('device.title')}
          </label>
          <span style={{
            fontSize: '9pt',
            color: devices.some((d) => d.status === 'online') ? 'var(--success)' : 'var(--text-muted)',
          }}>
            {devices.length === 0
              ? t('device.noDevices')
              : `${t('device.deviceOnline')} ${devices.filter((d) => d.status === 'online').length}/${devices.length}`}
          </span>
        </div>
        {isMonitoring && currentDevice ? (
          // 监控中显示设备信息
          <div style={{
            width: '100%',
            backgroundColor: "var(--bg-card)",
            color: "var(--text-primary)",
            border: '1px solid var(--bg-card)',
            borderRadius: '6px',
            padding: '10px 12px',
            fontSize: '10pt',
            display: 'flex',
            alignItems: 'center',
            gap: 6,
          }}>
            {getPlatformIcon(currentDevice.type)}
            <span>{currentDevice.name} ({getStatusText(currentDevice.status)})</span>
          </div>
        ) : (
          // 未监控显示下拉框（原生 option 仅允许纯文本，不能嵌套 SVG）
          <select
            value={selectedDevice || ''}
            onChange={(e) => handleDeviceChange(e.target.value)}
            style={{
              width: '100%',
              backgroundColor: "var(--bg-card)",
              color: "var(--text-primary)",
              border: '1px solid var(--bg-card)',
              borderRadius: '6px',
              padding: '10px 12px',
              fontSize: '10pt',
            }}
          >
            <option value="">{devices.length === 0 ? t('device.noDevices') : t('device.selectDeviceFirst')}</option>
            {devices.map((device) => (
              <option key={device.device_id} value={device.device_id}>
                [{getPlatformLabel(device.type)}] {device.name} ({getStatusText(device.status)})
              </option>
            ))}
          </select>
        )}
      </div>

      {/* === 监控模式（应用监控 / 设备全局） === */}
      <div>
        <label style={{
          display: 'block',
          fontSize: '11pt',
          fontWeight: '600',
          color: "var(--text-secondary)",
          marginBottom: '8px',
        }}>
          {t('device.monitorScope')}
        </label>
        <div style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: '6px',
          backgroundColor: 'var(--bg-base)',
          padding: '4px',
          borderRadius: '8px',
          border: '1px solid var(--bg-card)',
        }}>
          {(['app', 'device'] as const).map((mode) => {
            const active = (isMonitoring ? (isGlobalMode ? 'device' : 'app') : monitorMode) === mode;
            return (
              <button
                key={mode}
                type="button"
                data-testid={`monitor-mode-${mode}`}
                disabled={isMonitoring}
                onClick={() => {
                  setMonitorMode(mode);
                  setAppDropdownOpen(false);
                  setAppSearchQuery('');
                }}
                style={{
                  padding: '8px 10px',
                  borderRadius: '6px',
                  border: 'none',
                  fontSize: '10pt',
                  fontWeight: active ? 600 : 500,
                  cursor: isMonitoring ? 'not-allowed' : 'pointer',
                  backgroundColor: active ? 'var(--accent)' : 'transparent',
                  color: active ? 'var(--bg-base)' : 'var(--text-secondary)',
                  opacity: isMonitoring && !active ? 0.5 : 1,
                  transition: 'all 0.15s ease',
                }}
              >
                {mode === 'app' ? t('device.appScope') : t('device.deviceGlobalScope')}
              </button>
            );
          })}
        </div>
      </div>

      {/* === 应用选择 / 设备全局说明 === */}
      {isGlobalMode ? (
        <div
          data-testid="device-global-info"
          style={{
            backgroundColor: 'var(--bg-card)',
            border: '1px solid var(--border-strong)',
            borderRadius: '6px',
            padding: '10px 12px',
            fontSize: '9.5pt',
            color: 'var(--text-secondary)',
            lineHeight: 1.5,
          }}
        >
          <div style={{ fontWeight: 600, color: 'var(--text-primary)', marginBottom: '4px' }}>
            {t('device.globalTarget')}
          </div>
          <div>{t('device.globalTargetDesc')}</div>
        </div>
      ) : (
      <div>
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: '8px',
        }}>
          <label style={{
            fontSize: '11pt',
            fontWeight: '600',
            color: "var(--text-secondary)",
          }}>
            {t('device.app')}
          </label>
          {selectedDevice && (
            <span style={{
              fontSize: '9pt',
              color: 'var(--text-muted)',
            }}>
              {t('stats.total')} {apps.length} {t('stats.items')}
            </span>
          )}
        </div>
        {isMonitoring && currentAppName ? (
          // 监控中显示应用名称
          <div style={{
            width: '100%',
            backgroundColor: "var(--bg-card)",
            color: "var(--text-primary)",
            border: '1px solid var(--bg-card)',
            borderRadius: '6px',
            padding: '10px 12px',
            fontSize: '10pt',
          }}>
            {currentAppName}
          </div>
        ) : (
          // 未监控显示一体化搜索下拉组合框
          <div ref={appDropdownRef} style={{ position: 'relative' }}>
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              width: '100%',
              backgroundColor: "var(--bg-card)",
              border: appDropdownOpen ? '1px solid var(--accent)' : '1px solid var(--bg-card)',
              borderRadius: '6px',
              padding: '0 8px 0 10px',
              opacity: !selectedDevice ? 0.6 : 1,
            }}>
              <Search size={14} style={{ color: 'var(--text-muted)', flexShrink: 0 }} />
              <input
                type="text"
                aria-label={t('device.app')}
                placeholder={
                  !selectedDevice
                    ? t('device.selectDeviceFirst')
                    : appDropdownOpen
                      ? (currentAppName || t('report.searchPlaceholder'))
                      : t('device.selectAppFirst')
                }
                value={appDropdownOpen ? appSearchQuery : (currentAppName || '')}
                onFocus={() => {
                  if (selectedDevice) {
                    setAppSearchQuery('');
                    setAppDropdownOpen(true);
                  }
                }}
                onClick={() => {
                  if (selectedDevice && !appDropdownOpen) {
                    setAppSearchQuery('');
                    setAppDropdownOpen(true);
                  }
                }}
                onChange={(e) => {
                  setAppSearchQuery(e.target.value);
                  if (!appDropdownOpen) {
                    setAppDropdownOpen(true);
                  }
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Escape') {
                    setAppDropdownOpen(false);
                    setAppSearchQuery('');
                  } else if (e.key === 'Enter' && appDropdownOpen && filteredApps.length > 0) {
                    e.preventDefault();
                    handleAppChange(filteredApps[0].package_name);
                  }
                }}
                disabled={!selectedDevice}
                style={{
                  flex: 1,
                  minWidth: 0,
                  backgroundColor: 'transparent',
                  color: "var(--text-primary)",
                  border: 'none',
                  outline: 'none',
                  padding: '9px 0',
                  fontSize: '10pt',
                  cursor: !selectedDevice ? 'not-allowed' : 'text',
                }}
              />
              {selectedDevice && (selectedAppPackage || appSearchQuery) && (
                <button
                  type="button"
                  title={t('common.clear')}
                  onClick={(e) => {
                    e.stopPropagation();
                    setSelectedAppPackage('');
                    setAppSearchQuery('');
                  }}
                  style={{
                    background: 'transparent',
                    border: 'none',
                    padding: '2px',
                    cursor: 'pointer',
                    color: 'var(--text-muted)',
                    display: 'inline-flex',
                    alignItems: 'center',
                  }}
                >
                  <X size={13} />
                </button>
              )}
              <button
                type="button"
                aria-label="Toggle app list"
                disabled={!selectedDevice}
                onClick={() => {
                  if (!selectedDevice) return;
                  if (appDropdownOpen) {
                    setAppDropdownOpen(false);
                    setAppSearchQuery('');
                  } else {
                    setAppSearchQuery('');
                    setAppDropdownOpen(true);
                  }
                }}
                style={{
                  background: 'transparent',
                  border: 'none',
                  padding: '2px',
                  cursor: !selectedDevice ? 'not-allowed' : 'pointer',
                  color: 'var(--text-secondary)',
                  display: 'inline-flex',
                  alignItems: 'center',
                  transform: appDropdownOpen ? 'rotate(180deg)' : 'none',
                  transition: 'transform 0.15s ease',
                }}
              >
                <ChevronDown size={14} />
              </button>
            </div>

            {appDropdownOpen && selectedDevice && (
              <div style={{
                position: 'absolute',
                top: 'calc(100% + 4px)',
                left: 0,
                right: 0,
                zIndex: 50,
                backgroundColor: 'var(--bg-elevated)',
                border: '1px solid var(--border-strong)',
                borderRadius: '6px',
                boxShadow: '0 8px 24px rgba(0, 0, 0, 0.35)',
                maxHeight: '240px',
                overflowY: 'auto',
              }}>
                <div style={{
                  padding: '6px 10px',
                  fontSize: '9pt',
                  color: 'var(--text-muted)',
                  borderBottom: '1px solid var(--border)',
                  display: 'flex',
                  justifyContent: 'space-between',
                }}>
                  <span>{t('stats.total')} {filteredApps.length} / {apps.length} {t('stats.items')}</span>
                </div>
                {filteredApps.length === 0 ? (
                  <div style={{
                    padding: '12px',
                    textAlign: 'center',
                    fontSize: '10pt',
                    color: 'var(--text-muted)',
                  }}>
                    {t('device.noApps')}
                  </div>
                ) : (
                  filteredApps.map((app) => {
                    const isSelected = app.package_name === selectedAppPackage;
                    const isForeground = app.is_running && app.status !== 'background';
                    const isBackground = app.is_running && app.status === 'background';
                    return (
                      <button
                        key={app.package_name}
                        type="button"
                        onClick={() => handleAppChange(app.package_name)}
                        style={{
                          width: '100%',
                          textAlign: 'left',
                          backgroundColor: isSelected ? 'var(--bg-card)' : 'transparent',
                          color: 'var(--text-primary)',
                          border: 'none',
                          borderBottom: '1px solid var(--border)',
                          padding: '8px 10px',
                          fontSize: '10pt',
                          cursor: 'pointer',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                          gap: '8px',
                        }}
                      >
                        <div style={{ minWidth: 0, flex: 1 }}>
                          <div style={{
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap',
                            fontWeight: isSelected ? 600 : 400,
                          }}>
                            {app.name}
                          </div>
                          {app.name !== app.package_name && (
                            <div style={{
                              fontSize: '8.5pt',
                              color: 'var(--text-muted)',
                              overflow: 'hidden',
                              textOverflow: 'ellipsis',
                              whiteSpace: 'nowrap',
                            }}>
                              {app.package_name}
                            </div>
                          )}
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexShrink: 0 }}>
                          {isForeground && (
                            <span style={{
                              fontSize: '8.5pt',
                              color: 'var(--success)',
                              fontWeight: 500,
                            }}>
                              ●
                            </span>
                          )}
                          {isBackground && (
                            <span style={{
                              fontSize: '8.5pt',
                              color: 'var(--chart-3)',
                              fontWeight: 500,
                            }}>
                              ●
                            </span>
                          )}
                          {isSelected && <Check size={13} style={{ color: 'var(--accent)' }} />}
                        </div>
                      </button>
                    );
                  })
                )}
              </div>
            )}
          </div>
        )}
      </div>
      )}

      {/* === 当前目标显示 === */}
      <div style={{
        backgroundColor: "var(--bg-base)",
        border: '1px solid var(--bg-card)',
        borderRadius: '8px',
        padding: '12px',
      }}>
        <div style={{
          fontSize: '11pt',
          fontWeight: '600',
          color: 'var(--accent)',
          marginBottom: '8px',
        }}>
          {t('device.currentTarget')}
        </div>
        <div style={{
          fontSize: '10pt',
          color: currentDeviceName ? "var(--text-primary)" : "var(--text-secondary)",
          padding: '4px 8px',
        }}>
          {t('device.title')}: {currentDeviceName || t('device.selectDeviceFirst')}
        </div>
        <div style={{
          fontSize: '10pt',
          color: currentAppName ? "var(--text-primary)" : "var(--text-secondary)",
          padding: '4px 8px',
        }}>
          {isGlobalMode ? t('device.monitorTarget') : t('device.app')}: {currentAppName || t('device.selectAppFirst')}
        </div>
      </div>

      {/* === 控制按钮 === */}
      <div style={{ display: 'flex', gap: '12px' }}>
        <button
          onClick={handleStartStopMonitoring}
          disabled={!canStart && !isMonitoring}
          style={{
            flex: 1,
            backgroundColor: isMonitoring ? 'var(--chart-5)' : canStart ? "var(--accent)" : "var(--bg-card)",
            color: isMonitoring ? "var(--bg-base)" : canStart ? "var(--bg-base)" : "var(--text-muted)",
            border: 'none',
            borderRadius: '6px',
            padding: '12px 24px',
            fontSize: '11pt',
            fontWeight: '600',
            cursor: canStart || isMonitoring ? 'pointer' : 'not-allowed',
          }}
        >
          {isMonitoring ? t('device.stopMonitor') : t('device.startMonitor')}
        </button>
        <button
          onClick={handleRefresh}
          disabled={loading}
          style={{
            flex: 1,
            backgroundColor: "var(--bg-card)",
            color: "var(--text-primary)",
            border: '1px solid var(--border-strong)',
            borderRadius: '6px',
            padding: '12px 24px',
            fontSize: '11pt',
            fontWeight: '600',
            opacity: loading ? 0.5 : 1,
          }}
        >
          {loading ? t('common.loading') : t('device.refreshDevices')}
        </button>
      </div>

      {/* === 状态显示 === */}
      <div style={{
        fontSize: '10pt',
        color: isMonitoring ? "var(--success)" : "var(--text-muted)",
        padding: '8px',
        backgroundColor: "var(--bg-base)",
        borderRadius: '6px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 4,
      }}>
        <Circle size={12} strokeWidth={1.5} fill={isMonitoring ? 'var(--success)' : 'var(--text-muted)'} style={{ flexShrink: 0 }} />
        {isMonitoring ? t('menu.monitoring') : t('menu.notMonitoring')}
      </div>

      {/* === 电池信息 === */}
      <div style={{
        backgroundColor: "var(--bg-base)",
        border: '1px solid var(--bg-card)',
        borderRadius: '8px',
        padding: '12px',
      }}>
        <div style={{
          fontSize: '11pt',
          fontWeight: '600',
          color: "var(--chart-4)",
          marginBottom: '8px',
        }}>
          {t('device.battery')}
        </div>
        <div style={{
          fontSize: '10pt',
          color: "var(--text-secondary)",
          padding: '4px 8px',
        }}>
          {t('device.batteryLevel')}: {batteryInfo.level}%
        </div>
        <div style={{
          fontSize: '10pt',
          color: "var(--text-secondary)",
          padding: '4px 8px',
        }}>
          {t('device.temperature')}: {batteryInfo.temperature}°C
        </div>
        <div style={{
          fontSize: '10pt',
          color: "var(--text-secondary)",
          padding: '4px 8px',
        }}>
          {t('device.capacity')}: {batteryInfo.capacity}
        </div>
      </div>

      {/* 应用未运行警告对话框 */}
      {showAppNotRunningWarning && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          backgroundColor: 'rgba(0, 0, 0, 0.7)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 9999,
        }}>
          <div style={{
            backgroundColor: "var(--bg-card)",
            border: '2px solid var(--chart-3)',
            borderRadius: '12px',
            padding: '24px',
            maxWidth: '500px',
            boxShadow: '0 8px 32px rgba(255, 180, 0, 0.3)',
          }}>
            <h3 style={{
              color: "var(--chart-3)",
              fontSize: '16pt',
              fontWeight: '700',
              marginBottom: '16px',
              marginTop: 0,
            }}>
              {t('device.appNotRunning')}
            </h3>
            <p style={{
              color: "var(--text-primary)",
              fontSize: '11pt',
              lineHeight: '1.6',
              marginBottom: '16px',
            }}>
              {t('device.appNotRunningMessage')}
            </p>
            <div style={{
              backgroundColor: "var(--bg-base)",
              borderRadius: '8px',
              padding: '12px',
              marginBottom: '16px',
            }}>
              <div style={{ color: "var(--text-secondary)", fontSize: '10pt', marginBottom: '4px' }}>
                {t('dialogs.confirmDelete')}:
              </div>
              <div style={{ color: "var(--text-primary)", fontSize: '10pt', fontWeight: '500', wordBreak: 'break-all' }}>
                {pendingAppPackage}
              </div>
            </div>
            <div style={{
              color: "var(--chart-3)",
              fontSize: '10pt',
              marginBottom: '16px',
              padding: '12px',
              backgroundColor: 'rgba(255, 180, 0, 0.1)',
              borderRadius: '6px',
            }}>
              <strong>{t('dialogs.confirmDelete')}：</strong>{t('device.appNotRunningMessage')}
            </div>
            <div style={{ display: 'flex', justifyContent: 'center' }}>
              <button
                onClick={handleCancelStartNotRunning}
                style={{
                  backgroundColor: 'var(--info)',
                  color: "var(--text-primary)",
                  border: 'none',
                  borderRadius: '6px',
                  padding: '10px 32px',
                  fontSize: '11pt',
                  fontWeight: '600',
                  cursor: 'pointer',
                }}
              >
                {t('common.ok')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 后台应用警告对话框 */}
      {showBackgroundAppWarning && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          backgroundColor: 'rgba(0, 0, 0, 0.7)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 9999,
        }}>
          <div style={{
            backgroundColor: "var(--bg-card)",
            border: '2px solid var(--chart-2)',
            borderRadius: '12px',
            padding: '24px',
            maxWidth: '500px',
            boxShadow: '0 8px 32px rgba(147, 112, 219, 0.3)',
          }}>
            <h3 style={{
              color: 'var(--chart-2)',
              fontSize: '16pt',
              fontWeight: '700',
              marginBottom: '16px',
              marginTop: 0,
            }}>
              {t('device.appInBackground')}
            </h3>
            <p style={{
              color: "var(--text-primary)",
              fontSize: '11pt',
              lineHeight: '1.6',
              marginBottom: '16px',
            }}>
              {t('device.appInBackgroundMessage')}
            </p>
            <div style={{
              backgroundColor: "var(--bg-base)",
              borderRadius: '8px',
              padding: '12px',
              marginBottom: '16px',
            }}>
              <div style={{ color: "var(--text-secondary)", fontSize: '10pt', marginBottom: '4px' }}>
                {t('device.app')}:
              </div>
              <div style={{ color: "var(--text-primary)", fontSize: '10pt', fontWeight: '500' }}>
                {pendingAppName}
              </div>
              <div style={{ color: "var(--text-secondary)", fontSize: '10pt', marginBottom: '4px', marginTop: '8px' }}>
                PID:
              </div>
              <div style={{ color: "var(--text-primary)", fontSize: '10pt', fontWeight: '500' }}>
                {pendingAppPid}
              </div>
            </div>
            <div style={{
              color: 'var(--chart-2)',
              fontSize: '10pt',
              marginBottom: '16px',
              padding: '12px',
              backgroundColor: 'rgba(147, 112, 219, 0.1)',
              borderRadius: '6px',
            }}>
              <strong>{t('dialogs.confirmDelete')}：</strong>{t('device.appInBackgroundMessage')}
            </div>
            <div style={{ display: 'flex', gap: '12px' }}>
              <button
                onClick={handleCancelStartBackground}
                style={{
                  flex: 1,
                  backgroundColor: 'var(--bg-elevated)',
                  color: "var(--text-primary)",
                  border: 'none',
                  borderRadius: '6px',
                  padding: '10px 24px',
                  fontSize: '11pt',
                  fontWeight: '600',
                  cursor: 'pointer',
                }}
              >
                {t('common.cancel')}
              </button>
              <button
                onClick={handleConfirmStartBackground}
                style={{
                  flex: 1,
                  backgroundColor: 'var(--chart-2)',
                  color: "var(--text-primary)",
                  border: 'none',
                  borderRadius: '6px',
                  padding: '10px 24px',
                  fontSize: '11pt',
                  fontWeight: '600',
                  cursor: 'pointer',
                }}
              >
                {t('dialogs.confirm')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
