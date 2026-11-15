import { useMonitoringStore } from '@/modules/performance/store/monitoringStore';
import { useIsMobile } from '@/shared/hooks/useIsMobile';
import MenuBar from './MenuBar';
import DeviceSelectionPanel from '../panels/DeviceSelectionPanel';
import MonitorPanel from '../panels/MonitorPanel';
import ConfigPanel from '../panels/ConfigPanel';
import ReportPanel from '../panels/ReportPanel';

export default function MainWindow() {
  const { activeTab } = useMonitoringStore();
  const isMobile = useIsMobile();

  return (
    <div
      className="text-text-primary"
      style={{
        height: isMobile ? 'auto' : '100%',
        minHeight: 0,
        backgroundColor: "var(--bg-base)",
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      <MenuBar />
      <div
        className="flex-1 min-h-0"
        style={{
          paddingTop: '4px',
          paddingBottom: activeTab === 'report' ? '4px' : '16px',
          display: 'flex',
          flexDirection: 'column',
          overflowX: isMobile ? 'auto' : (activeTab === 'report' ? 'hidden' : 'auto'),
          overflowY: isMobile ? 'visible' : (activeTab === 'report' ? 'hidden' : 'auto'),
        }}
      >
        {/* 主内容区域 - 直接显示监控面板或报告面板 */}
        {activeTab === 'report' ? (
          <ReportPanel />
        ) : (
          <div className="flex gap-3" style={{ gap: '12px', alignItems: 'flex-start' }}>
            {/* 左侧：设备选择面板 - 20% */}
            <div style={{ flex: '0 0 20%', minWidth: '280px', maxWidth: '400px' }}>
              <DeviceSelectionPanel />
            </div>

            {/* 中间：监控面板 - 60% */}
            <div style={{ flex: '1 1 60%', minWidth: '360px' }}>
              <MonitorPanel />
            </div>

            {/* 右侧：配置面板 - 20% */}
            <div style={{ flex: '0 0 20%', minWidth: '280px', maxWidth: '400px' }}>
              <ConfigPanel />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
