"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useSelector } from "react-redux";
import { AlertTriangle } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
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
  clampScore,
  inversePercentage,
  percentage,
  weightedScore,
} from "./intelligence/helpers";
import { MemoryIntelligenceSkeleton, SectionHeader } from "./intelligence/Primitives";
import { HealthMetricsPanel } from "./intelligence/HealthMetricsPanel";
import { CurationActivityPanel } from "./intelligence/CurationActivityPanel";
import { SourceBreakdownPanel } from "./intelligence/SourceBreakdownPanel";

export function MemoryIntelligenceCenter() {
  const userId = useSelector((state: RootState) => state.profile.userId);
  const dashboardRefreshKey = useSelector((state: RootState) => state.ui.dashboardRefreshKey);
  const { messages } = useI18n();
  const t = messages.dashboard;
  const [state, setState] = useState<IntelligenceState>(INITIAL_STATE);
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
          fetch(`${apiBaseUrl}/api/v1/curator/status`, { signal: controller.signal }),
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
          fetch(`${apiBaseUrl}/api/v1/governance/counts`, { signal: controller.signal }),
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
      await fetch(`${apiBaseUrl}/api/v1/curator/llm`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ dry_run: false }),
      });
      const poll = async (): Promise<void> => {
        const res = await fetch(`${apiBaseUrl}/api/v1/curator/llm/latest`);
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
  const active = asNumber(byStatus.active);
  const linkCount = asNumber(statusStats.link_count);
  const uniqueLinkedMemories = asNumber(statusStats.unique_linked_memories);
  const activeNeverAccessed = asNumber(statusStats.active_never_accessed_count);
  const contradicted = asNumber(byStatus.contradicted);
  const stale = asNumber(byStatus.stale);
  const superseded = asNumber(byStatus.superseded);
  const pendingCleanup =
    stale + superseded + contradicted;
  const usablePool =
    active + stale + contradicted + superseded;
  // B2: reuse coverage over the active pool only (archived dead data excluded)
  const activeReuseCoverage = active > 0 ? percentage(active - activeNeverAccessed, active) : 0;
  // B3: linked coverage uses real memory_links unique-coverage ratio, decoupled from reuse
  const linkedCoverageRatio = active > 0 ? percentage(uniqueLinkedMemories, active) : 0;
  // B4: non-archived ratio becomes "pending cleanup share of usable pool"
  const nonArchivedRatio = usablePool > 0 ? percentage(pendingCleanup, usablePool) : 0;
  const connectedCoverage = linkedCoverageRatio;
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
  void staleActionCount;
  const llmStatus = curatorStatus?.llm_curator?.last_result ?? curatorStatus?.llm_curator?.latest_job?.status ?? "unknown";
  const llmNeverRun = llmStatus === "unknown" || llmStatus === "idle";
  const riskScore = clampScore(100 - highRiskCount * 18 - Math.min(duplicateCount, 100) * 0.28 - Math.min(contradictionCount, 20) * 2);
  // B1: LLM governance score — neutral when never run (no hard-coded 45 penalty);
  // when run, recent success is 100 and running is a transient 62.
  const llmGovernanceScore = llmNeverRun
    ? 50
    : llmStatus === "success"
      ? 100
      : llmStatus === "running"
        ? 62
        : 50;
  const qualityScore = weightedScore([
    { value: riskScore, weight: 0.34 },
    { value: inversePercentage(pendingCleanup, usablePool), weight: 0.16 },
    { value: connectedCoverage, weight: 0.08 },
    { value: activeReuseCoverage, weight: 0.24 },
    { value: llmGovernanceScore, weight: 0.14 },
  ]);
  const healthSignals = [
    // B5: when LLM detection is unavailable, flag that risk numbers may be stale
    {
      label: t.riskControl,
      value: riskScore,
      detail: llmNeverRun || llmStatus !== "success"
        ? `${t.riskControlDetail(contradictionCount, duplicateCount)} · ${t.llmDataMayBeStale}`
        : t.riskControlDetail(contradictionCount, duplicateCount),
    },
    { label: t.reuseCoverage, value: activeReuseCoverage, detail: t.reuseCoverageDetail(activeNeverAccessed, active) },
    { label: t.linkedCoverage, value: linkedCoverageRatio, detail: t.linkedCoverageDetail(linkCount, uniqueLinkedMemories) },
    { label: t.nonArchivedRatio, value: nonArchivedRatio, detail: t.nonArchivedRatioDetail(pendingCleanup, usablePool) },
    { label: t.llmGovernance, value: llmGovernanceScore, detail: llmNeverRun ? t.llmNeverRun : llmStatus },
  ];
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
      <SectionHeader />

      {state.error && (
        <Card className="border-amber-900/60 bg-amber-950/20">
          <CardContent className="flex items-center gap-3 py-4 text-sm text-amber-200">
            <AlertTriangle className="h-4 w-4" />
            <span>{state.error}</span>
          </CardContent>
        </Card>
      )}

      <HealthMetricsPanel qualityScore={qualityScore} healthSignals={healthSignals} t={t} />

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
