"use client";

import { useState } from "react";
import { ChevronDown, ChevronUp, SlidersHorizontal } from "lucide-react";
import { ContextLab } from "@/components/dashboard/ContextLab";
import { MemoryOperationsPanel } from "@/components/dashboard/MemoryOperationsPanel";
import { CuratorTuningPanel } from "@/components/dashboard/CuratorTuningPanel";
import { MemoryIntelligenceCenter } from "@/components/dashboard/MemoryIntelligenceCenter";
import { Button } from "@/components/ui/button";
import { useI18n } from "@/hooks/useI18n";
import "@/styles/animation.css";

export default function DashboardPage() {
  const { messages } = useI18n();
  const [showAdvanced, setShowAdvanced] = useState(false);

  return (
    <div className="text-white py-6">
      <div className="container">
        <div className="w-full mx-auto space-y-6">
          {/* Context Lab: recall quality debugger */}
          <div className="animate-fade-slide-down">
            <ContextLab />
          </div>

          <div className="animate-fade-slide-down delay-1">
            <MemoryOperationsPanel />
          </div>

          <div className="animate-fade-slide-down delay-2">
            <MemoryIntelligenceCenter />
          </div>

          <div className="animate-fade-slide-down delay-3">
            <div className="flex items-center justify-center">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setShowAdvanced(!showAdvanced)}
                className="border-zinc-800 bg-zinc-900 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200 gap-2"
              >
                <SlidersHorizontal className="h-4 w-4" />
                {messages.dashboard.advancedOps ?? "高级操作"}
                {showAdvanced ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
              </Button>
            </div>
            {showAdvanced && (
              <div className="mt-4 space-y-6">
                <CuratorTuningPanel />
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
