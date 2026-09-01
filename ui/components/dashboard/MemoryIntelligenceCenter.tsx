"use client";

import { useCallback, useEffect, useState } from "react";
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
} from "./intelligence/helpers";
import { MemoryIntelligenceSkeleton, SectionHeader } from "./intelligence/Primitives";
import { HealthMetricsPanel } from "./intelligence/HealthMetricsPanel";
import { CurationActivityPanel } from "./intelligence/CurationActivityPanel";
import { SourceBreakdownPanel } from "./intelligence/SourceBreakdownPanel";

type HealthScorePayload = {
  quality: number;
  risk: number;
  llmGovernance: number;
  llmStatus: string;
  metrics: {
    active: number;
    active_never_accessed: number;
    active_reuse_coverage: number;
    linked_coverage: number;
    link_count: number;
    unique_linked_memories: number;
    pending_cleanup_share: number;
    pending_cleanup: number;
    usable_pool: number;
  };
  signals: {
    high_risk_count: number;
    contradiction_actionable: number;
    duplicate_actionable: number;
  };
};

export function MemoryIntelligenceCenter() {
  const userId = useSelector((state: RootState) => state.profile.userId);
  const dashboardRefreshKey = useSelector((state: RootState) => state.ui.dashboardRefreshKey);
  const { messages } = useI18n();
  const t = messages.dashboard;
  const [state, setState] = useState<IntelligenceState>(INITIAL_STATE);
  const [health, setHealth] = useState<HealthScorePayload | null>(null);
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
        const [curatorResponse, statsResponse, memoriesResponse, governanceCountsResponse, healthScoreResponse] = await Promise.all([
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
          fetch(`${apiBaseUrl}/api/v1/health-score`, { signal: controller.signal }),
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
        // 健康分走后端单一事实源；失败时不阻塞整个面板（保留上次数值）。
        const healthPayload = healthScoreResponse.ok
          ? ((await healthScoreResponse.json()) as ApiEnvelope<HealthScorePayload> | HealthScorePayload)
          : null;
        const healthScore = healthPayload
          ? (healthPayload as ApiEnvelope<HealthScorePayload>).data ?? (healthPayload as HealthScorePayload)
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
        if (healthScore) setHealth(healthScore);
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

  // 健康分与信号卡片统一消费后端 /api/v1/health-score（与顶部 HealthBanner 同源，口径永远一致）。
  const qualityScore = Math.round(health?.quality ?? 0);
  const healthSignals = health
    ? [
        {
          label: t.riskControl,
          value: Math.round(health.risk),
          detail: t.riskControlDetail(health.signals.contradiction_actionable, health.signals.duplicate_actionable),
        },
        {
          label: t.reuseCoverage,
          value: Math.round(health.metrics.active_reuse_coverage),
          detail: t.reuseCoverageDetail(health.metrics.active_never_accessed, health.metrics.active),
        },
        {
          label: t.linkedCoverage,
          value: Math.round(health.metrics.linked_coverage),
          detail: t.linkedCoverageDetail(health.metrics.link_count, health.metrics.unique_linked_memories),
        },
        {
          label: t.nonArchivedRatio,
          value: Math.round(health.metrics.pending_cleanup_share),
          detail: t.nonArchivedRatioDetail(health.metrics.pending_cleanup, health.metrics.usable_pool),
          inverted: true,
        },
        {
          label: t.llmGovernance,
          value: Math.round(health.llmGovernance),
          detail: health.llmStatus,
        },
      ]
    : [];
  const curatorStatus = state.curatorStatus;
  const statusStats = curatorStatus?.stats ?? {};
  const byType = statusStats.by_type ?? {};
  const totalMemories = asNumber(statusStats.total) || asNumber(state.stats?.total_memories) || state.recentMemories.length;
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
