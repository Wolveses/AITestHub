import { useEffect, useState } from 'react';
import { CheckCircle2, Copy, RefreshCw, Smartphone, Unlock, Wifi } from 'lucide-react';
import { toast } from 'sonner';
import { Btn, StatusBadge } from './common';
import { useMobileStore } from '../store/mobileStore';

export function DevicePanel() {
  const {
    devices,
    appiumReady,
    appiumDetail,
    devicesLoading,
    loadDevices,
    enableWireless,
    releaseDevice,
  } = useMobileStore();
  const [busyId, setBusyId] = useState<string | null>(null);
  const [wirelessMap, setWirelessMap] = useState<Record<string, string>>({});

  useEffect(() => {
    void loadDevices();
  }, [loadDevices]);

  const handleWireless = async (deviceId: string) => {
    setBusyId(deviceId);
    try {
      const res = await enableWireless(deviceId);
      setWirelessMap((prev) => ({ ...prev, [deviceId]: res.endpoint }));
      toast.success(`已开启无线投屏端口: ${res.endpoint}`);
    } catch (e) {
      toast.error(`开启无线调试失败: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusyId(null);
    }
  };

  const handleRelease = async (deviceId: string) => {
    setBusyId(deviceId);
    try {
      await releaseDevice(deviceId);
      toast.success(`设备 ${deviceId} 租约已强制释放`);
    } catch (e) {
      toast.error(`释放失败: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusyId(null);
    }
  };

  const copyAddr = async (addr: string) => {
    await navigator.clipboard.writeText(addr);
    toast.success(`已复制 ${addr}，可在 QtScrcpy / adb connect 中使用`);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '12px 16px',
          borderRadius: 10,
          background: 'var(--bg-card)',
          border: '1px solid var(--border)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <CheckCircle2 size={16} style={{ color: appiumReady ? 'var(--success)' : 'var(--warning)' }} />
          <div>
            <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>
              平台主机 Appium 状态: {appiumReady ? '已就绪' : '未检测到在线服务'}
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
              {appiumDetail || '请确保平台主机已运行 appium --port 4723'}
            </div>
          </div>
        </div>
        <Btn variant="ghost" onClick={() => void loadDevices()} disabled={devicesLoading}>
          <RefreshCw size={13} /> {devicesLoading ? '扫描中...' : '刷新设备'}
        </Btn>
      </div>

      {devices.length === 0 ? (
        <div
          style={{
            padding: 40,
            textAlign: 'center',
            background: 'var(--bg-card)',
            border: '1px solid var(--border)',
            borderRadius: 10,
            color: 'var(--text-muted)',
            fontSize: 13,
          }}
        >
          平台主机暂未检测到连接的移动设备。请用 USB 将 Android 手机连接到平台主机并开启 USB 调试后点击“刷新设备”。
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))', gap: 12 }}>
          {devices.map((d) => {
            const addr = wirelessMap[d.device_id] || d.wireless_endpoint;
            const isBusy = busyId === d.device_id;
            const leased = d.busy && !!d.lease;
            return (
              <div
                key={d.device_id}
                style={{
                  background: 'var(--bg-card)',
                  border: '1px solid var(--border)',
                  borderRadius: 10,
                  padding: 14,
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 10,
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <Smartphone size={16} style={{ color: 'var(--accent)' }} />
                    <div>
                      <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>
                        {d.model || d.name || d.device_id}
                      </div>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'monospace' }}>
                        {d.device_id} · {d.type} {d.sdk_version || ''}
                      </div>
                    </div>
                  </div>
                  <StatusBadge status={leased ? 'running' : d.status === 'online' ? 'passed' : 'failed'} />
                </div>

                {leased && d.lease && (
                  <div
                    style={{
                      padding: '8px 10px',
                      borderRadius: 6,
                      background: 'var(--bg-base)',
                      border: '1px solid var(--border)',
                      fontSize: 11,
                      color: 'var(--text-secondary)',
                    }}
                  >
                    占用中: {d.lease.holder_type} · Case #{d.lease.case_id}
                  </div>
                )}

                {addr && (
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      padding: '6px 10px',
                      borderRadius: 6,
                      background: 'var(--surface-tint)',
                      border: '1px solid var(--accent)',
                      fontSize: 12,
                      color: 'var(--text-primary)',
                    }}
                  >
                    <span>
                      QtScrcpy 连接地址: <code>{addr}</code>
                    </span>
                    <button
                      onClick={() => void copyAddr(addr)}
                      style={{
                        background: 'none',
                        border: 'none',
                        cursor: 'pointer',
                        color: 'var(--accent)',
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: 4,
                        fontSize: 11,
                      }}
                    >
                      <Copy size={12} /> 复制
                    </button>
                  </div>
                )}

                <div style={{ display: 'flex', gap: 8, marginTop: 'auto' }}>
                  {d.type === 'android' && (
                    <Btn
                      variant="ghost"
                      disabled={isBusy}
                      onClick={() => void handleWireless(d.device_id)}
                      style={{ flex: 1, fontSize: 12 }}
                    >
                      <Wifi size={13} /> 开启无线投屏 IP
                    </Btn>
                  )}
                  {leased && (
                    <Btn
                      variant="danger"
                      disabled={isBusy}
                      onClick={() => void handleRelease(d.device_id)}
                      style={{ fontSize: 12 }}
                    >
                      <Unlock size={13} /> 强制释放
                    </Btn>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
