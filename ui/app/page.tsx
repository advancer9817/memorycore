"use client";

import { AppsPanel } from "@/components/dashboard/AppsPanel";
import { ContextLab } from "@/components/dashboard/ContextLab";
import { CuratorTuningPanel } from "@/components/dashboard/CuratorTuningPanel";
import { GovernancePanel } from "@/components/dashboard/GovernancePanel";
import { HealthBanner } from "@/components/dashboard/HealthBanner";
import { MemoryIntelligenceCenter } from "@/components/dashboard/MemoryIntelligenceCenter";
import { MemoryOperationsPanel } from "@/components/dashboard/MemoryOperationsPanel";
import { PageShell } from "@/components/shared/PageShell";

export default function DashboardPage() {
  return (
    <PageShell>
      <div className="space-y-6">
        <div className="animate-fade-slide-down">
          <HealthBanner />
        </div>

        <div className="animate-fade-slide-down delay-1">
          <MemoryOperationsPanel />
        </div>

        <div className="animate-fade-slide-down delay-2">
          <GovernancePanel />
        </div>

        <div className="animate-fade-slide-down delay-3">
          <AppsPanel />
        </div>

        <div className="animate-fade-slide-down delay-4">
          <MemoryIntelligenceCenter />
        </div>

        <div className="animate-fade-slide-down delay-5">
          <ContextLab />
        </div>

        <div className="animate-fade-slide-down delay-6">
          <CuratorTuningPanel />
        </div>
      </div>
    </PageShell>
  );
}