"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { AlertTriangle, Check, ExternalLink, Loader2, SkipForward, X } from "lucide-react";
import { getApiBaseUrl } from "@/lib/api-url";
import { useI18n } from "@/hooks/useI18n";
import { useToast } from "@/hooks/use-toast";
import type { GovernanceDecision } from "./types";
import { confidenceTone, decisionTitle, decisionSummary, titleCase } from "./utils";

const REVIEW_LIMIT = 10;

interface NeedsReviewQueueProps {
  refreshKey: number;
  onRefresh: () => void;
}

export function NeedsReviewQueue({ refreshKey, onRefresh }: NeedsReviewQueueProps) {
  const { messages } = useI18n();
  const t = messages.dashboard;
  const { toast } = useToast();
  const [decisions, setDecisions] = useState<GovernanceDecision[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [actionPendingId, setActionPendingId] = useState<string | null>(null);

  const baseUrl = useMemo(() => getApiBaseUrl(), []);

  useEffect(() => {
    const controller = new AbortController();
    async function load(): Promise<void> {
      setIsLoading(true);
      try {
        const response = await fetch(
          `${baseUrl}/api/governance/decisions?review_status=needs_review&limit=${REVIEW_LIMIT}`,
          { signal: controller.signal },
        );
        if (!response.ok) throw new Error("Failed to load review queue");
        const data = await response.json();
        const items: GovernanceDecision[] = Array.isArray(data) ? data : data?.data ?? [];
        setDecisions(items);
      } catch (error: unknown) {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setDecisions([]);
      } finally {
        setIsLoading(false);
      }
    }
    void load();
    return () => controller.abort();
  }, [baseUrl, refreshKey]);

  const handleAction = useCallback(async (decisionId: string, action: "apply" | "reject"): Promise<void> => {
    setActionPendingId(decisionId);
    try {
      const response = await fetch(`${baseUrl}/api/governance/${encodeURIComponent(decisionId)}/${action}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source_agent: "frontend", reason: action === "reject" ? "Skipped from dashboard" : undefined }),
      });
      if (!response.ok) throw new Error(`${action} failed`);
      toast({ description: action === "apply" ? t.needsReviewAcceptSuccess : t.needsReviewRejectSuccess });
      setDecisions((prev) => prev.filter((d) => d.id !== decisionId));
      onRefresh();
    } catch {
      toast({ variant: "destructive", description: t.needsReviewActionError });
    } finally {
      setActionPendingId(null);
    }
  }, [baseUrl, toast, t, onRefresh]);

  if (isLoading) return null;
  if (decisions.length === 0) return null;

  return (
    <Card className="border-zinc-800 bg-zinc-900">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center justify-between text-sm font-medium text-zinc-300">
          <span className="flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-amber-400" />
            {t.needsReviewTitle}
            <Badge variant="outline" className="border-amber-700 bg-amber-500/10 text-amber-300">
              {decisions.length}
            </Badge>
          </span>
          <Button asChild variant="ghost" size="sm" className="h-7 text-xs text-zinc-500 hover:text-zinc-300">
            <Link href="/governance">
              {t.needsReviewOpenGovernance}
              <ExternalLink className="ml-1 h-3 w-3" />
            </Link>
          </Button>
        </CardTitle>
        <p className="text-xs text-zinc-500">{t.needsReviewDescription}</p>
      </CardHeader>
      <CardContent>
        <div className="space-y-2">
          {decisions.map((decision) => {
            const isPending = actionPendingId === decision.id;
            return (
              <div
                key={decision.id}
                className="flex items-center justify-between gap-3 rounded-lg border border-zinc-800 bg-zinc-950/45 px-3 py-2"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="truncate text-sm text-zinc-200">{decisionTitle(decision)}</span>
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-zinc-500">
                    <Badge variant="outline" className="border-zinc-700 bg-zinc-900 text-zinc-400">
                      {titleCase(decision.recommended_action)}
                    </Badge>
                    <Badge variant="outline" className={confidenceTone(decision.llm_confidence)}>
                      {Math.round(decision.llm_confidence * 100)}%
                    </Badge>
                    <span>{decisionSummary(decision)}</span>
                  </div>
                </div>
                <div className="flex shrink-0 gap-1">
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 text-xs text-emerald-400 hover:bg-emerald-950/40 hover:text-emerald-300"
                    disabled={isPending}
                    onClick={() => handleAction(decision.id, "apply")}
                  >
                    {isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <Check className="h-3 w-3" />}
                    {t.needsReviewAccept}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 text-xs text-zinc-400 hover:bg-zinc-800 hover:text-zinc-300"
                    disabled={isPending}
                    onClick={() => handleAction(decision.id, "reject")}
                  >
                    {isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <SkipForward className="h-3 w-3" />}
                    {t.needsReviewSkip}
                  </Button>
                </div>
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}
