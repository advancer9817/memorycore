const API_URL_STORAGE_KEY = "memorycore.apiUrl";

export const DEFAULT_API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8318").replace(/\/+$/, "");

export function normalizeApiUrl(value: string): string {
  return value.trim().replace(/\/+$/, "");
}

export function getApiBaseUrl(): string {
  if (typeof window === "undefined") {
    return DEFAULT_API_URL;
  }
  return normalizeApiUrl(window.localStorage.getItem(API_URL_STORAGE_KEY) || DEFAULT_API_URL);
}

export function setApiBaseUrl(value: string): string {
  const normalized = normalizeApiUrl(value);
  if (typeof window !== "undefined") {
    window.localStorage.setItem(API_URL_STORAGE_KEY, normalized);
  }
  return normalized;
}
