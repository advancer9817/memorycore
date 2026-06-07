import { en } from "@/lib/i18n/dictionaries/en";

export const locales = ["en", "zh"] as const;

export type Locale = (typeof locales)[number];
export type Messages = typeof en;

export const DEFAULT_LOCALE: Locale = "en";
export const LOCALE_STORAGE_KEY = "memorycore.locale";

export function isLocale(value: unknown): value is Locale {
  return value === "en" || value === "zh";
}

export function toHtmlLang(locale: Locale): string {
  return locale === "zh" ? "zh-CN" : "en";
}
