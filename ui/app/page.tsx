"use client";

import { MemoryOperationsPanel } from "@/components/dashboard/MemoryOperationsPanel";
import { CuratorTuningPanel } from "@/components/dashboard/CuratorTuningPanel";
import { MemoryIntelligenceCenter } from "@/components/dashboard/MemoryIntelligenceCenter";
import "@/styles/animation.css";

export default function DashboardPage() {
  return (
    <div className="text-white py-6">
      <div className="container">
        <div className="w-full mx-auto space-y-6">
          <div className="animate-fade-slide-down">
            <MemoryOperationsPanel />
          </div>

          <div className="animate-fade-slide-down delay-1">
            <CuratorTuningPanel />
          </div>

          <div className="animate-fade-slide-down delay-2">
            <MemoryIntelligenceCenter />
          </div>
        </div>
      </div>
    </div>
  );
}
