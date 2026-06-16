"use client";

import { useCallback, useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Sparkles, Undo2 } from "lucide-react";
import { getApiBaseUrl } from "@/lib/api-url";
import { GovernanceDecision } from "@/components/dashboard/intelligence/types";
import { canRollbackDecision, decisionSummary, decisionTitle, formatGovernanceDate, titleCase } from "@/components/dashboard/intelligence/utils";

const ACTION_COLORS: Record<string, string> = {
  archive: "border-amber-700 bg-amber-500/10 text-amber-300",
  supersede: "border-blue-700 bg-blue-500/10 text-blue-300",
  stale: "border-zinc-700 bg-zinc-800 text-zinc-300",
  split: "border-violet-700 bg-violet-500/10 text-violet-300",
  promote: "border-emerald-700 bg-emerald-500/10 text-emerald-300",
  reweight: "border-sky-700 bg-sky-500/10 text-sky-300",
};

function actionBadgeClass(action: string): string {
  return ACTION_COLORS[action] ?? "border-zinc-700 bg-zinc-800 text-zinc-400";
}

type UndoState = "idle" | "loading" | "done" | "failed";

interface DecisionRowProps {
  decision: GovernanceDecision;
  onUndone: (id: string) => void;
}

function DecisionRow({ decision, onUndone }: DecisionRowProps) {
  const [undoState, setUndoState] = useState<UndoState>("idle");
  const [errorMsg, setErrorMsg] = useState<string>("");

  const handleUndo = useCallback(async () => {
    setUndoState("loading");
    setErrorMsg("");
    try {
      const res = await fetch(`${getApiBaseUrl()}/api/governance/${decision.id}/rollback`, {
        method: "POST",
        headers: { "content-type": "application/json" },
      });
      if (!res.ok) {
        throw new Error(`Rollback failed with ${res.status}`);
      }
      setUndoState("done");
      setTimeout(() => onUndone(decision.id), 600);
    } catch (err: unknown) {
      setUndoState("failed");
      setErrorMsg(err instanceof Error ? err.message : "Undo failed");
    }
  }, [decision.id, onUndone]);

  const action = decision.recommended_action ?? "";
  const title = decisionTitle(decision);
  const summary = decisionSummary(decision);
  const appliedAt = formatGovernanceDate(decision.applied_at);
  const canUndo = canRollbackDecision(decision);

  return (
    <div className="flex flex-wrap items-start gap-x-3 gap-y-1 rounded-md border border-zinc-800/60 bg-zinc-800/30 px-3 py-2 text-sm">
      <Badge variant="outline" className={`shrink-0 text-xs ${actionBadgeClass(action)}`}>
        {titleCase(action)}
      </Badge>
      <div className="min-w-0 flex-1">
        <span className="text-zinc-200 font-medium">{title}</span>
        {summary && summary !== titleCase(action) && (
          <span className="ml-2 text-zinc-500 text-xs">{summary}</span>
        )}
      </div>
      <span className="text-zinc-600 text-xs shrink-0">{appliedAt}</span>
      {canUndo && (
        <div className="shrink-0 flex items-center gap-1">
          {undoState === "failed" && (
            <span className="text-red-400 text-xs">{errorMsg || "Undo failed"}</span>
          )}
          {undoState === "done" ? (
            <span className="text-emerald-400 text-xs">Undone</span>
          ) : (
            <Button
              variant="ghost"
              size="sm"
              onClick={handleUndo}
              disabled={undoState === "loading"}
              className="h-6 px-2 text-xs text-zinc-400 hover:text-zinc-100 hover:bg-zinc-700"
            >
              <Undo2 className="h-3 w-3 mr-1" />
              {undoState === "loading" ? "Undoing..." : "Undo"}
            </Button>
          )}
        </div>
      )}
    </div>
  );
}

export function AutoAppliedStrip() {
  const [decisions, setDecisions] = useState<GovernanceDecision[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    fetch(`${getApiBaseUrl()}/api/governance/decisions?review_status=auto_approved&limit=10`)
      .then((res) => {
        if (!res.ok) throw new Error(`Request failed with ${res.status}`);
        return res.json();
      })
      .then((payload) => {
        if (cancelled) return;
        const items: GovernanceDecision[] = Array.isArray(payload?.data)
          ? payload.data
          : Array.isArray(payload)
            ? payload
            : [];
        setDecisions(items);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Failed to load");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleUndone = useCallback((id: string) => {
    setDecisions((prev) => prev.filter((d) => d.id !== id));
  }, []);

  return (
    <Card className="bg-zinc-900 border-zinc-800">
      <CardHeader className="pb-3">
        <CardTitle className="text-sm font-medium text-zinc-400 flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-zinc-500" />
          Auto-Applied Actions
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {loading && (
          <div className="space-y-2">
            {[0, 1, 2].map((i) => (
              <div key={i} className="h-9 rounded-md bg-zinc-800/50 animate-pulse" />
            ))}
          </div>
        )}
        {!loading && error && (
          <div className="rounded-md border border-red-800/50 bg-red-950/30 px-3 py-2 text-xs text-red-300">
            {error}
          </div>
        )}
        {!loading && !error && decisions.length === 0 && (
          <div className="flex items-center gap-2 rounded-md border border-emerald-800/40 bg-emerald-950/20 px-3 py-2 text-xs text-emerald-300">
            <span className="text-emerald-400">✓</span>
            No recent auto-applied actions
          </div>
        )}
        {!loading && !error && decisions.map((d) => (
          <DecisionRow key={d.id} decision={d} onUndone={handleUndone} />
        ))}
        <div className="pt-1">
          <a
            href="/governance"
            className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors"
          >
            View all in Governance →
          </a>
        </div>
      </CardContent>
    </Card>
  );
}
