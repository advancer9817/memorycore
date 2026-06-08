"use client";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useI18n } from "@/hooks/useI18n";
import { isLocale, Locale } from "@/lib/i18n/types";

export function LanguageSwitcher() {
  const { locale, messages, setLocale } = useI18n();

  function handleValueChange(value: string): void {
    if (isLocale(value)) {
      setLocale(value);
    }
  }

  const languageLabels: Record<Locale, string> = {
    en: messages.nav.english,
    zh: messages.nav.chinese,
  };

  return (
    <Select value={locale} onValueChange={handleValueChange}>
      <SelectTrigger
        aria-label={messages.nav.language}
        className="h-9 w-[116px] border-zinc-700/50 bg-zinc-900 text-zinc-200 hover:bg-zinc-800"
      >
        <SelectValue />
      </SelectTrigger>
      <SelectContent className="border-zinc-800 bg-zinc-900 text-zinc-100">
        <SelectItem value="en">{languageLabels.en}</SelectItem>
        <SelectItem value="zh">{languageLabels.zh}</SelectItem>
      </SelectContent>
    </Select>
  );
}
