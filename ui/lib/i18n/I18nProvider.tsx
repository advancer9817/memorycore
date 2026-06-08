"use client";

import { createContext, ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import { useDispatch } from "react-redux";
import { en } from "@/lib/i18n/dictionaries/en";
import { zh } from "@/lib/i18n/dictionaries/zh";
import {
  DEFAULT_LOCALE,
  isLocale,
  Locale,
  LOCALE_STORAGE_KEY,
  Messages,
  toHtmlLang,
} from "@/lib/i18n/types";
import { AppDispatch } from "@/store/store";
import { setLocale as setObservedLocale } from "@/store/uiSlice";

export interface I18nContextValue {
  locale: Locale;
  messages: Messages;
  setLocale: (locale: Locale) => void;
}

interface I18nProviderProps {
  children: ReactNode;
}

const dictionaries: Record<Locale, Messages> = {
  en,
  zh,
};

export const I18nContext = createContext<I18nContextValue | null>(null);

function detectInitialLocale(): Locale {
  if (typeof window === "undefined") return DEFAULT_LOCALE;

  const storedLocale = window.localStorage.getItem(LOCALE_STORAGE_KEY);
  if (isLocale(storedLocale)) return storedLocale;

  const browserLanguage = window.navigator.language.toLowerCase();
  return browserLanguage.startsWith("zh") ? "zh" : DEFAULT_LOCALE;
}

export function I18nProvider({ children }: I18nProviderProps) {
  const dispatch = useDispatch<AppDispatch>();
  const [locale, setLocaleState] = useState<Locale>(detectInitialLocale);

  useEffect(() => {
    document.documentElement.lang = toHtmlLang(locale);
    window.localStorage.setItem(LOCALE_STORAGE_KEY, locale);
    dispatch(setObservedLocale(locale));
  }, [dispatch, locale]);

  const setLocale = useCallback((nextLocale: Locale) => {
    setLocaleState(nextLocale);
  }, []);

  const value = useMemo<I18nContextValue>(
    () => ({
      locale,
      messages: dictionaries[locale],
      setLocale,
    }),
    [locale, setLocale]
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}
