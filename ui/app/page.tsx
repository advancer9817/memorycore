"use client";

import { ContextLab } from "@/components/dashboard/ContextLab";
import { MemoryOperationsPanel } from "@/components/dashboard/MemoryOperationsPanel";
import { CuratorTuningPanel } from "@/components/dashboard/CuratorTuningPanel";
import { MemoryIntelligenceCenter } from "@/components/dashboard/MemoryIntelligenceCenter";
import { PageShell } from "@/components/shared/PageShell";

export default function DashboardPage() {
  return (
    <PageShell>
      <div className="space-y-6">
        <div className="animate-fade-slide-down">
          <MemoryOperationsPanel />
        </div>

        <div className="animate-fade-slide-down delay-1">
          <MemoryIntelligenceCenter />
        </div>

        <div className="animate-fade-slide-down delay-2">
          <ContextLab />
        </div>

        <div className="animate-fade-slide-down delay-3">
          <CuratorTuningPanel />
        </div>
      </div>
    </PageShell>
  );
}
