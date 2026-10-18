import { create } from 'zustand';

export interface UserProfile {
  id: number;
  username: string;
  display_name: string;
  role: 'admin' | 'tester';
  is_active: boolean;
  created_at: string;
}

interface AuthState {
  token: string | null;
  user: UserProfile | null;
  loading: boolean;
  initialized: boolean;
  login: (token: string, user: UserProfile) => void;
  logout: () => void;
  setUser: (user: UserProfile) => void;
  checkAuth: () => Promise<boolean>;
}

const TOKEN_KEY = 'insight_auth_token';
const USER_KEY = 'insight_auth_user';

export const useAuthStore = create<AuthState>((set, get) => ({
  token: localStorage.getItem(TOKEN_KEY),
  user: (() => {
    try {
      const u = localStorage.getItem(USER_KEY);
      return u ? JSON.parse(u) : null;
    } catch {
      return null;
    }
  })(),
  loading: false,
  initialized: false,

  login: (token: string, user: UserProfile) => {
    localStorage.setItem(TOKEN_KEY, token);
    localStorage.setItem(USER_KEY, JSON.stringify(user));
    set({ token, user, initialized: true });
  },

  logout: () => {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    set({ token: null, user: null, initialized: true });
    // 强制刷新页面或触发重置，确保上一个用户的任何残留状态全部清空
    window.location.reload();
  },

  setUser: (user: UserProfile) => {
    localStorage.setItem(USER_KEY, JSON.stringify(user));
    set({ user });
  },

  checkAuth: async () => {
    const token = get().token;
    if (!token) {
      set({ initialized: true, user: null, token: null });
      return false;
    }
    set({ loading: true });
    try {
      const res = await fetch('/api/platform/auth/me', {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });
      if (res.ok) {
        const user = await res.json();
        localStorage.setItem(USER_KEY, JSON.stringify(user));
        set({ user, initialized: true, loading: false });
        return true;
      } else {
        // Token 失效
        get().logout();
        return false;
      }
    } catch {
      // 网络离线等异常保持原有本地状态
      set({ initialized: true, loading: false });
      return !!get().user;
    }
  },
}));

