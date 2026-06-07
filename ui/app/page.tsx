"use client";

import { Install } from "@/components/dashboard/Install";
import { MemoryIntelligenceCenter } from "@/components/dashboard/MemoryIntelligenceCenter";
import "@/styles/animation.css";

export default function DashboardPage() {
  return (
    <div className="text-white py-6">
      <div className="container">
        <div className="w-full mx-auto space-y-6">
          <div>
            <div className="animate-fade-slide-down">
              <Install />
            </div>
          </div>

          <div className="animate-fade-slide-down delay-2">
            <MemoryIntelligenceCenter />
          </div>
        </div>
      </div>
    </div>
  );
}
