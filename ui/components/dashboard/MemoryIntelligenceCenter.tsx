"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useSelector } from "react-redux";
import { AlertTriangle, ArrowRight } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { RootState } from "@/store/store";
import { getApiBaseUrl } from "@/lib/api-url";
import { useI18n } from "@/hooks/useI18n";
import {
  DASHBOARD_FETCH_TIMEOUT_MS,
  DAY_MS,
  INITIAL_STATE,
  RECENT_MEMORY_LIMIT,
  ApiEnvelope,
  CuratorStatusPayload,
  GovernanceCounts,
  IntelligenceState,
  MemoriesPayload,
  StatsPayload,
  asNumber,
  buildAttentionItems,
  buildRecommendations,
  buildReviewQueue,
  clampScore,
  downloadGovernanceReport,
  inversePercentage,
  percentage,
  severityClassName,
  weightedScore,
} from "./intelligence/helpers";
import { MemoryIntelligenceSkeleton, SectionHeader } from "./intelligence/Primitives";
import { HealthMetricsPanel } from "./intelligence/HealthMetricsPanel";
import { ReviewFlowPanel } from "./intelligence/ReviewFlowPanel";
import { CurationActivityPanel } from "./intelligence/CurationActivityPanel";
import { SourceBreakdownPanel } from "./intelligence/SourceBreakdownPanel";

export function MemoryIntelligenceCenter() {
  const userId = useSelector((state: RootState) => state.profile.userId);
  const dashboardRefreshKey = useSelector((state: RootState) => state.ui.dashboardRefreshKey);
  const { messages } = useI18n();
  const t = messages.dashboard;
  const [state, setState] = useState<IntelligenceState>(INITIAL_STATE);
  const [selectedReviewLabel, setSelectedReviewLabel] = useState<string | null>(null);
  const [llmRunning, setLlmRunning] = useState(false);
  const [localRefreshKey, setLocalRefreshKey] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let didTimeout = false;
    const timeoutId = setTimeout(() => {
      didTimeout = true;
      controller.abort();
    }, DASHBOARD_FETCH_TIMEOUT_MS);

    async function loadIntelligence(): Promise<void> {
      setState((current) => ({ ...current, isLoading: true, error: null }));
      try {
        const apiBaseUrl = getApiBaseUrl();
        const [curatorResponse, statsResponse, memoriesResponse, governanceCountsResponse] = await Promise.all([
          fetch(`${apiBaseUrl}/api/curator/status`, { signal: controller.signal }),
          fetch(`${apiBaseUrl}/api/v1/stats?user_id=${encodeURIComponent(userId)}`, { signal: controller.signal }),
          fetch(`${apiBaseUrl}/api/v1/memories/filter`, {
            method: "POST",
            headers: { "content-type": "application/json" },
            signal: controller.signal,
            body: JSON.stringify({
              user_id: userId,
              page: 1,
              size: RECENT_MEMORY_LIMIT,
              sort_column: "created_at",
              sort_direction: "desc",
              show_archived: true,
            }),
          }),
          fetch(`${apiBaseUrl}/api/governance/counts`, { signal: controller.signal }),
        ]);

        if (!curatorResponse.ok || !statsResponse.ok || !memoriesResponse.ok) {
          throw new Error("Unable to load intelligence data");
        }

        const curatorPayload = (await curatorResponse.json()) as ApiEnvelope<CuratorStatusPayload> | CuratorStatusPayload;
        const statsPayload = (await statsResponse.json()) as StatsPayload;
        const memoriesPayload = (await memoriesResponse.json()) as MemoriesPayload;
        const governanceCounts = governanceCountsResponse.ok
          ? ((await governanceCountsResponse.json()) as { data?: GovernanceCounts }).data ?? null
          : null;

        const curatorData = (curatorPayload as ApiEnvelope<CuratorStatusPayload>).data ?? (curatorPayload as CuratorStatusPayload);

        if (controller.signal.aborted) return;
        setState({
          curatorStatus: curatorData,
          recentMemories: memoriesPayload.items ?? [],
          stats: statsPayload,
          governanceCounts,
          isLoading: false,
          error: null,
        });
      } catch (error: unknown) {
        if (controller.signal.aborted && !didTimeout) return;
        setState({
          ...INITIAL_STATE,
          isLoading: false,
          error:
            didTimeout || (error instanceof DOMException && error.name === "AbortError")
              ? "Dashboard data load timed out. Please try Refresh again."
              : error instanceof Error
                ? error.message
                : "Unable to load intelligence data",
        });
      } finally {
        clearTimeout(timeoutId);
      }
    }

    loadIntelligence();
    return () => {
      controller.abort();
      clearTimeout(timeoutId);
    };
  }, [dashboardRefreshKey, localRefreshKey, userId]);

  const handleRunLlm = useCallback(async () => {
    if (llmRunning) return;
    setLlmRunning(true);
    try {
      const apiBaseUrl = getApiBaseUrl();
      await fetch(`${apiBaseUrl}/api/curator/llm`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ dry_run: false }),
      });
      const poll = async (): Promise<void> => {
        const res = await fetch(`${apiBaseUrl}/api/curator/llm/latest`);
        if (!res.ok) return;
        const data = (await res.json()) as { status?: string };
        if (data.status === "running") {
          await new Promise<void>((resolve) => setTimeout(resolve, 2000));
          return poll();
        }
      };
      await poll();
    } finally {
      setLlmRunning(false);
      setLocalRefreshKey((k) => k + 1);
    }
  }, [llmRunning]);

  const curatorStatus = state.curatorStatus;
  const statusStats = curatorStatus?.stats ?? {};
  const byStatus = statusStats.by_status ?? {};
  const byType = statusStats.by_type ?? {};
  const totalMemories = asNumber(statusStats.total) || asNumber(state.stats?.total_memories) || state.recentMemories.length;
  const totalApps = asNumber(state.stats?.total_apps);
  const active = asNumber(byStatus.active);
  const archived = asNumber(byStatus.archived);
  const candidates = asNumber(byStatus.candidate);
  const linkCount = asNumber(statusStats.link_count);
  const neverAccessed = asNumber(statusStats.never_accessed_count);
  const contradicted = asNumber(byStatus.contradicted);
  const stale = asNumber(byStatus.stale);
  const connectedCoverage = percentage(Math.max(totalMemories - neverAccessed, 0), totalMemories);
  const neverAccessedRatio = percentage(neverAccessed, totalMemories);
  const activeRatio = percentage(active, totalMemories);
  const archivedRatio = percentage(archived, totalMemories);
  const nonArchivedRatio = inversePercentage(archived, totalMemories);
  const attentionItems = useMemo(
    () => buildAttentionItems(curatorStatus, t, llmRunning ? null : handleRunLlm, state.governanceCounts),
    [curatorStatus, t, llmRunning, handleRunLlm, state.governanceCounts]
  );
  const highRiskCount = attentionItems.filter((item) => item.severity === "high").length;
  const curatorSummary = curatorStatus?.curator?.summary ?? {};
  const llmSummary = curatorStatus?.llm_curator?.summary ?? {};
  const contradictionCount = state.governanceCounts != null
    ? state.governanceCounts.contradiction
    : contradicted + asNumber(llmSummary.contradictions) + asNumber(curatorSummary.contradictions);
  const duplicateCount = state.governanceCounts != null
    ? state.governanceCounts.semantic_duplicate
    : asNumber(curatorSummary.duplicates) + asNumber(llmSummary.semantic_duplicates);
  const staleActionCount = stale + asNumber(curatorSummary.archive) + asNumber(curatorSummary.stale);
  const llmStatus = curatorStatus?.llm_curator?.last_result ?? curatorStatus?.llm_curator?.latest_job?.status ?? "unknown";
  const riskScore = clampScore(100 - highRiskCount * 18 - Math.min(duplicateCount, 100) * 0.28 - Math.min(contradictionCount, 20) * 2);
  const llmGovernanceScore = llmStatus === "success" ? 100 : llmStatus === "running" ? 62 : 45;
  const qualityScore = weightedScore([
    { value: riskScore, weight: 0.34 },
    { value: nonArchivedRatio, weight: 0.16 },
    { value: connectedCoverage, weight: 0.18 },
    { value: inversePercentage(neverAccessed, totalMemories), weight: 0.18 },
    { value: llmGovernanceScore, weight: 0.14 },
  ]);
  const healthSignals = [
    { label: t.riskControl, value: riskScore, detail: t.riskControlDetail(contradictionCount, duplicateCount) },
    { label: t.reuseCoverage, value: inversePercentage(neverAccessed, totalMemories), detail: t.reuseCoverageDetail(neverAccessed) },
    { label: t.linkedCoverage, value: connectedCoverage, detail: t.linkedCoverageDetail(linkCount) },
    { label: t.nonArchivedRatio, value: nonArchivedRatio, detail: t.nonArchivedRatioDetail(totalMemories - archived) },
    { label: t.llmGovernance, value: llmGovernanceScore, detail: llmStatus },
  ];
  const recommendations = buildRecommendations({
    t,
    contradictionCount,
    duplicateCount,
    staleCount: staleActionCount,
    neverAccessedRatio,
    connectedCoverage,
    llmStatus,
  });
  const reviewQueue = buildReviewQueue(attentionItems, curatorStatus, t);
  const selectedReviewItem = reviewQueue.find((item) => item.label === selectedReviewLabel) ?? reviewQueue[0];
  const governanceReport = {
    generated_at: new Date().toISOString(),
    quality_score: qualityScore,
    totals: { total_memories: totalMemories, total_apps: totalApps, active, archived, candidates, link_count: linkCount },
    risks: { contradictions: contradictionCount, duplicates: duplicateCount, stale: staleActionCount, never_accessed: neverAccessed },
    health_signals: healthSignals,
    review_queue: reviewQueue,
    recommendations,
    curator: curatorStatus?.curator,
    llm_curator: curatorStatus?.llm_curator,
  };
  const recentCount = state.recentMemories.filter((memory) => Date.now() - new Date(memory.created_at).getTime() <= 7 * DAY_MS).length;
  const oldCount = state.recentMemories.filter((memory) => Date.now() - new Date(memory.created_at).getTime() > 30 * DAY_MS).length;
  const typeEntries = Object.entries(byType)
    .sort(([, a], [, b]) => asNumber(b) - asNumber(a))
    .slice(0, 5);
  const sourceEntries = Object.entries(
    state.recentMemories.reduce<Record<string, number>>((acc, memory) => {
      const source = memory.app_name || "Unknown";
      return { ...acc, [source]: (acc[source] ?? 0) + 1 };
    }, {})
  ).sort(([, a], [, b]) => b - a);

  if (state.isLoading) {
    return <MemoryIntelligenceSkeleton />;
  }

  return (
    <section className="space-y-4">
      <SectionHeader onExport={() => downloadGovernanceReport(governanceReport)} />

      {state.error && (
        <Card className="border-amber-900/60 bg-amber-950/20">
          <CardContent className="flex items-center gap-3 py-4 text-sm text-amber-200">
            <AlertTriangle className="h-4 w-4" />
            <span>{state.error}</span>
          </CardContent>
        </Card>
      )}

      {recommendations.length > 0 && (
        <Card className="border-zinc-800 bg-zinc-900">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center justify-between text-sm font-medium text-zinc-300">
              {t.recommendedActions}
              <ArrowRight className="h-4 w-4 text-zinc-500" />
            </CardTitle>
          </CardHeader>
          <CardContent className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
            {recommendations.map((item) => (
              <div key={item.title} className={`rounded-xl border px-3 py-3 ${severityClassName[item.severity]}`}>
                <p className="text-sm font-medium">{item.title}</p>
                <p className="mt-1 text-xs leading-relaxed text-current/75">{item.detail}</p>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-5">
        <HealthMetricsPanel qualityScore={qualityScore} healthSignals={healthSignals} t={t} />
        <ReviewFlowPanel
          reviewQueue={reviewQueue}
          selectedReviewItem={selectedReviewItem}
          onSelectLabel={setSelectedReviewLabel}
          onExportReport={() => downloadGovernanceReport(governanceReport)}
          t={t}
        />
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-5">
        <CurationActivityPanel
          curatorStatus={curatorStatus}
          recentMemories={state.recentMemories}
          totalMemories={totalMemories}
          t={t}
        />
        <SourceBreakdownPanel
          typeEntries={typeEntries}
          sourceEntries={sourceEntries}
          totalMemories={totalMemories}
          recentMemoriesCount={state.recentMemories.length}
          recentCount={recentCount}
          oldCount={oldCount}
          t={t}
        />
      </div>
    </section>
  );
}

export default MemoryIntelligenceCenter;
