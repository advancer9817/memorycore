"use client";

import { MemoryIntelligenceCenter } from "@/components/dashboard/MemoryIntelligenceCenter";
import { ContextLab } from "@/components/dashboard/ContextLab";
import "@/styles/animation.css";

export default function DashboardPage() {
  return (
    <div className="text-white py-6">
      <div className="container">
        <div className="w-full mx-auto space-y-6">
          <div className="animate-fade-slide-down">
            <MemoryIntelligenceCenter />
          </div>

          <div className="animate-fade-slide-down delay-1">
            <ContextLab />
          </div>
        </div>
      </div>
    </div>
  );
}
