"use client";

import { AlertTriangle, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function GraphError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="flex h-[calc(100vh-64px)] items-center justify-center bg-zinc-950">
      <div className="flex flex-col items-center gap-4 text-center max-w-md px-6">
        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-red-500/10">
          <AlertTriangle className="h-6 w-6 text-red-500" />
        </div>
        <h2 className="text-lg font-semibold text-white">Graph rendering failed</h2>
        <p className="text-sm text-zinc-400">
          {error.message || "The 3D graph could not be rendered. This may be due to WebGL support."}
        </p>
        <Button
          onClick={reset}
          variant="outline"
          className="mt-2 border-zinc-700 bg-zinc-900 text-zinc-300 hover:bg-zinc-800"
        >
          <RotateCcw className="mr-2 h-4 w-4" />
          Reload graph
        </Button>
      </div>
    </div>
  );
}
