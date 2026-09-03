"use client";

import React from "react";
import { LayoutGrid, RotateCcw, SlidersHorizontal } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

interface DashboardToolbarProps {
  onResetLayout?: () => void;
  onToggleCompact?: () => void;
  isCompact?: boolean;
}

export function DashboardToolbar({
  onResetLayout,
  onToggleCompact,
  isCompact = false,
}: DashboardToolbarProps) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-zinc-800 bg-zinc-900 px-4 py-3">
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2 text-sm font-medium text-zinc-200">
          <LayoutGrid className="h-4 w-4 text-violet-400" />
          <span>控制台概览 (Modular Grid)</span>
        </div>
        <div className="hidden h-3.5 w-px bg-zinc-800 sm:block" />
        <div className="hidden items-center gap-2 text-xs text-zinc-500 sm:flex">
          <span>核心模块：<b className="text-zinc-300 font-normal">5 个活跃部件</b></span>
          <span>•</span>
          <span>布局引擎：<b className="text-zinc-300 font-normal">12 栅格自适应</b></span>
        </div>
      </div>

      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={onToggleCompact}
          className="border-zinc-800 bg-zinc-950/60 text-xs text-zinc-300 hover:bg-zinc-800 hover:text-white"
        >
          <SlidersHorizontal className="mr-1.5 h-3.5 w-3.5 text-zinc-400" />
          <span>{isCompact ? "展开视图" : "紧凑视图"}</span>
        </Button>

        <Button
          variant="outline"
          size="sm"
          onClick={onResetLayout}
          className="border-zinc-800 bg-zinc-950/60 text-xs text-zinc-300 hover:bg-zinc-800 hover:text-white"
        >
          <RotateCcw className="mr-1.5 h-3.5 w-3.5 text-zinc-400" />
          <span>重置布局</span>
        </Button>

        <Badge
          variant="outline"
          className="border-zinc-700 bg-zinc-800 text-xs text-zinc-400 font-normal"
        >
          实时联动
        </Badge>
      </div>
    </div>
  );
}
