import { en } from "@/lib/i18n/dictionaries/en";

export const locales = ["en", "zh"] as const;

export type Locale = (typeof locales)[number];

type WidenMessageValue<T> = T extends (...args: infer Args) => infer Return
  ? (...args: Args) => Return
  : T extends string
    ? string
    : T extends object
      ? { readonly [Key in keyof T]: WidenMessageValue<T[Key]> }
      : T;

export type Messages = WidenMessageValue<typeof en>;

export const DEFAULT_LOCALE: Locale = "en";
export const LOCALE_STORAGE_KEY = "memorycore.locale";

export function isLocale(value: unknown): value is Locale {
  return value === "en" || value === "zh";
}

export function toHtmlLang(locale: Locale): string {
  return locale === "zh" ? "zh-CN" : "en";
}
