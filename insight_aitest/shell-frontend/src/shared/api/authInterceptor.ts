/**
 * 全局 HTTP 请求拦截与鉴权注入。
 * 包装原生 window.fetch 与 axios，自动在 Authorization 头带上 Bearer Token。
 */
import axios from 'axios';

const TOKEN_KEY = 'insight_auth_token';

export function setupAuthInterceptor() {
  // 1. 给 axios 注入请求拦截器
  axios.interceptors.request.use((config) => {
    const token = localStorage.getItem(TOKEN_KEY);
    if (token && config.headers) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  });

  // 2. 包装 window.fetch 自动注入 Authorization 头
  const originalFetch = window.fetch;
  window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const token = localStorage.getItem(TOKEN_KEY);
    if (token) {
      const headers = new Headers(init?.headers || {});
      if (!headers.has('Authorization')) {
        headers.set('Authorization', `Bearer ${token}`);
      }
      init = { ...init, headers };
    }
    return originalFetch(input, init);
  };
}

