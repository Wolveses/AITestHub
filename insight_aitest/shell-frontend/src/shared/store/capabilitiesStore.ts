/**
 * 平台全局非敏感能力开关 store（由 /api/platform/capabilities 加载，
 * 并在设置页 updateConfig 保存后即时同步）。
 */
import { create } from 'zustand';

interface CapabilitiesState {
  aiAssistEnabled: boolean;
  loaded: boolean;
  loadCapabilities: () => Promise<void>;
  setAiAssistEnabled: (enabled: boolean) => void;
}

export const useCapabilitiesStore = create<CapabilitiesState>((set) => ({
  aiAssistEnabled: true,
  loaded: false,

  loadCapabilities: async () => {
    try {
      const r = await fetch('/api/platform/capabilities');
      if (!r.ok) return;
      const data = await r.json();
      set({
        aiAssistEnabled: typeof data.ai_assist_enabled === 'boolean' ? data.ai_assist_enabled : true,
        loaded: true,
      });
    } catch {
      // 网络失败时保持默认值 true，具体接口调用由后端兜底校验
    }
  },

  setAiAssistEnabled: (enabled) => set({ aiAssistEnabled: enabled, loaded: true }),
}));
