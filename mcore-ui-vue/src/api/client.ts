import axios, { type AxiosInstance } from 'axios';
import { useTenantStore } from '@/stores/tenant';

function getBaseUrl(): string {
  if (import.meta.env.VITE_API_BASE_URL) {
    return import.meta.env.VITE_API_BASE_URL;
  }
  if (typeof window !== 'undefined' && window.location && window.location.hostname) {
    const { protocol, hostname } = window.location;
    if (hostname.startsWith('mcore-ui.')) {
      return `${protocol}//${hostname.replace(/^mcore-ui\./, 'mcore.')}/api/v1`;
    }
    if (hostname === 'localhost' || hostname === '127.0.0.1') {
      return 'http://127.0.0.1:8318/api/v1';
    }
    return `${protocol}//${hostname}:8318/api/v1`;
  }
  return 'http://127.0.0.1:8318/api/v1';
}

const apiClient: AxiosInstance = axios.create({
  baseURL: getBaseUrl(),
  timeout: 15000,
});

apiClient.interceptors.request.use((config) => {
  try {
    const tenantStore = useTenantStore();
    if (tenantStore && tenantStore.currentTenantId) {
      config.headers.set('X-Tenant-Id', tenantStore.currentTenantId);
    }
  } catch {
    const stored = localStorage.getItem('mcore_tenant_id');
    if (stored) {
      config.headers.set('X-Tenant-Id', stored);
    }
  }
  return config;
});

export default apiClient;
