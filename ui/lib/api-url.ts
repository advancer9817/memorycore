const API_URL_STORAGE_KEY = "memorycore.apiUrl";
const LEGACY_KEYS = ["lmmcp.openmemory.apiUrl", "lmmcp.apiUrl"];

export const DEFAULT_API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8318").replace(/\/+$/, "");

export function normalizeApiUrl(value: string): string {
  return value.trim().replace(/\/+$/, "");
}

function _migrateAndGet(): string {
  // 清理旧 localStorage key，避免旧值（如 :38318）干扰
  for (const oldKey of LEGACY_KEYS) {
    if (window.localStorage.getItem(oldKey)) {
      window.localStorage.removeItem(oldKey);
    }
  }
  const stored = window.localStorage.getItem(API_URL_STORAGE_KEY);
  if (!stored) return DEFAULT_API_URL;
  const normalized = normalizeApiUrl(stored);
  // 如果存储的是旧端口（38318），重置为默认
  if (normalized.includes(":38318")) {
    window.localStorage.removeItem(API_URL_STORAGE_KEY);
    return DEFAULT_API_URL;
  }
  return normalized;
}

export function getApiBaseUrl(): string {
  if (typeof window === "undefined") {
    return DEFAULT_API_URL;
  }
  return _migrateAndGet();
}

export function setApiBaseUrl(value: string): string {
  const normalized = normalizeApiUrl(value);
  if (typeof window !== "undefined") {
    window.localStorage.setItem(API_URL_STORAGE_KEY, normalized);
  }
  return normalized;
}
