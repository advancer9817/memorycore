const API_URL_STORAGE_KEY = "memorycore.apiUrl";

export const DEFAULT_API_URL = "";

export function normalizeApiUrl(value: string): string {
  return value.trim().replace(/\/+$/, "");
}

function _migrateAndGet(): string {
  if (typeof window !== "undefined" && window.location) {
    const { hostname } = window.location;
    const stored = window.localStorage.getItem(API_URL_STORAGE_KEY);
    if (stored && (stored.includes("127.0.0.1") || stored.includes("localhost") || stored.includes(":38318") || stored.includes(":8318"))) {
      window.localStorage.removeItem(API_URL_STORAGE_KEY);
    }
    if (hostname !== "localhost" && hostname !== "127.0.0.1") {
      return "";
    }
  }
  const stored = window.localStorage.getItem(API_URL_STORAGE_KEY);
  if (!stored) return "";
  const normalized = normalizeApiUrl(stored);
  if (normalized.includes(":38318") || normalized.includes("127.0.0.1") || normalized.includes("localhost")) {
    window.localStorage.removeItem(API_URL_STORAGE_KEY);
    return "";
  }
  return normalized;
}

export function getApiBaseUrl(): string {
  if (typeof window === "undefined") {
    return "";
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
