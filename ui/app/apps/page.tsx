"use client";

import { AppFilters } from "./components/AppFilters";
import { AppGrid } from "./components/AppGrid";
import { useI18n } from "@/hooks/useI18n";
import { PageShell } from "@/components/shared/PageShell";

export default function AppsPage() {
  const { messages } = useI18n();

  return (
    <PageShell
      title={messages.apps.title}
      subtitle={messages.apps.description}
    >
      <div className="pb-4 animate-fade-slide-down delay-1">
        <AppFilters />
      </div>
      <div className="animate-fade-slide-down delay-2">
        <AppGrid />
      </div>
    </PageShell>
  );
}
