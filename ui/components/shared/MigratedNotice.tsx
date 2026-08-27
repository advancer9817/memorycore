"use client";

import Link from "next/link";
import { Info } from "lucide-react";
import { useI18n } from "@/hooks/useI18n";

/** Amber notice shown on legacy pages that were folded into the Dashboard. */
export function MigratedNotice() {
  const { messages: t } = useI18n();
  return (
    <div className="mb-4 flex items-center gap-2 rounded-lg border border-amber-700/50 bg-amber-500/10 px-3 py-2 text-xs text-amber-200 animate-fade-slide-down">
      <Info className="h-3.5 w-3.5 shrink-0" />
      <span>{t.common.migratedToDashboard}</span>
      <Link href="/" className="ml-auto shrink-0 whitespace-nowrap text-violet-300 transition-colors hover:text-violet-200">
        {t.nav.dashboard} →
      </Link>
    </div>
  );
}