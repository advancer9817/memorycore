"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useSelector } from "react-redux";
import {
  AlertTriangle,
  ArrowDownToLine,
  ArrowRight,
  RefreshCw,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { RootState } from "@/store/store";
import { getApiBaseUrl } from "@/lib/api-url";
import { useI18n } from "@/hooks/useI18n";
import { AutoAppliedStrip } from "./intelligence/AutoAppliedStrip";
import { CurationTimeline } from "./intelligence/CurationTimeline";
import { HealthMetricsPanel } from "./intelligence/HealthMetricsPanel";
import { NeedsReviewQueue } from "./intelligence/NeedsReviewQueue";
import { ReviewQueuePanel } from "./intelligence/ReviewQueuePanel";
import { SourceBreakdown } from "./intelligence/SourceBreakdown";

const RECENT_MEMORY_LIMIT = 10;
const DAY_MS = 24 * 60 * 60 * 1000;

interface CuratorAction {
  id?: string;
  title?: string;
  action?: string;
  reason?: string;
}

interface CuratorStatusPayload {
  stats?: {
    total?: number;
    by_status?: Record<string, number>;
    by_type?: Record<string, number>;
    never_accessed_count?: number;
    link_count?: number;
  };
  curator?: {
    generated_at?: string;
    scanned?: number;
    summary?: Record<string, number>;
    planned_actions?: CuratorAction[];
  };
  llm_curator?: {
    last_run_at?: string;
    last_result?: string;
    summary?: {
      semantic_duplicates?: number;
      contradictions?: number;
      importance_reassessments?: number;
      split_candidates?: number;
    };
    errors?: string[];
    latest_job?: {
      status?: string;
      job_id?: string | null;
    };
  };
  schedules?: {
    rule_curator?: Record<string, string>;
    llm_curator?: Record<string, string>;
  };
  timer?: Record<string, string>;
  service?: Record<string, string>;
}

interface ApiEnvelope<T> {
  data?: T;
}

interface StatsPayload {
  total_memories?: number;
  total_apps?: number;
}

interface MemoryApiItem {
  id: string;
  content: string;
  created_at: string;
  state: string;
  categories?: string[];
  app_name?: string;
}

interface MemoriesPayload {
  items?: MemoryApiItem[];
  total?: number;
}

interface IntelligenceState {
  curatorStatus: CuratorStatusPayload | null;
  recentMemories: MemoryApiItem[];
  stats: StatsPayload | null;
  isLoading: boolean;
  error: string | null;
}

interface AttentionItem {
  label: string;
  detail: string;
  count: number;
  severity: "high" | "medium" | "low" | "good";
  group: "governance" | "operations";
  onRun?: () => void;
}

interface HealthSignal {
  label: string;
  value: number;
  detail: string;
}

interface RecommendationItem {
  title: string;
  detail: string;
  severity: AttentionItem["severity"];
}

interface ReviewQueueItem extends AttentionItem {
  href: string;
  actionLabel: string;
  workflow: string[];
  operationHint: string;
  primaryHref: string;
  primaryLabel: string;
}

const INITIAL_STATE: IntelligenceState = {
  curatorStatus: null,
  recentMemories: [],
  stats: null,
  isLoading: true,
  error: null,
};

const severityClassName: Record<AttentionItem["severity"], string> = {
  high: "border-red-800/70 bg-red-950/35 text-red-200",
  medium: "border-amber-800/70 bg-amber-950/35 text-amber-200",
  low: "border-sky-800/70 bg-sky-950/35 text-sky-200",
  good: "border-emerald-800/70 bg-emerald-950/35 text-emerald-200",
};

function asNumber(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function percentage(value: number, total: number): number {
  if (total <= 0) return 0;
  return Math.min(100, Math.round((value / total) * 100));
}

function inversePercentage(value: number, total: number): number {
  return 100 - percentage(value, total);
}

function clampScore(value: number): number {
  return Math.max(0, Math.min(100, Math.round(value)));
}

function weightedScore(signals: Array<{ value: number; weight: number }>): number {
  const totalWeight = signals.reduce((sum, signal) => sum + signal.weight, 0);
  if (totalWeight <= 0) return 0;
  const total = signals.reduce((sum, signal) => sum + clampScore(signal.value) * signal.weight, 0);
  return clampScore(total / totalWeight);
}

function formatDate(value?: string | number, locale: "en" | "zh" = "en"): string {
  if (!value || value === "n/a") return "n/a";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "n/a";
  return date.toLocaleString(locale === "zh" ? "zh-CN" : "en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function getMemoryTitle(memory: MemoryApiItem | undefined, fallback: string): string {
  const content = memory?.content?.trim();
  if (!content) return fallback;
  return content.length > 92 ? `${content.slice(0, 92)}...` : content;
}

function buildAttentionItems(curatorStatus: CuratorStatusPayload | null, t: ReturnType<typeof useI18n>["messages"]["dashboard"], onRunLlm: (() => void) | null): AttentionItem[] {
  const summary = curatorStatus?.curator?.summary ?? {};
  const llmSummary = curatorStatus?.llm_curator?.summary ?? {};
  const byStatus = curatorStatus?.stats?.by_status ?? {};
  const plannedActions = curatorStatus?.curator?.planned_actions ?? [];
  // llmSummary counts are patched by the backend to reflect actual actionable governance decisions
  const contradictionCount = asNumber(llmSummary.contradictions);
  const duplicateCount = asNumber(llmSummary.semantic_duplicates);
  const agingCount =
    asNumber(summary.stale_candidates) +
    asNumber(summary.archive_candidates) +
    asNumber(summary.stale) +
    asNumber(summary.archive);
  const candidateCount = asNumber(byStatus.candidate);
  const splitCount = asNumber(llmSummary.split_candidates);
  const importanceReviewCount = asNumber(llmSummary.importance_reassessments);

  const items: AttentionItem[] = [
    { label: t.attentionContradictions, detail: t.attentionContradictionsDetail, count: contradictionCount, severity: contradictionCount > 0 ? "high" : "good", group: "governance", onRun: onRunLlm ?? undefined },
    { label: t.attentionMergeOpportunities, detail: t.attentionMergeOpportunitiesDetail, count: duplicateCount, severity: duplicateCount > 0 ? "medium" : "good", group: "governance", onRun: onRunLlm ?? undefined },
    { label: t.attentionAgingKnowledge, detail: t.attentionAgingKnowledgeDetail, count: agingCount, severity: agingCount > 0 ? "medium" : "good", group: "operations" },
    { label: t.attentionPendingReview, detail: t.attentionPendingReviewDetail, count: candidateCount, severity: candidateCount > 0 ? "low" : "good", group: "operations" },
    { label: t.attentionPlannedActions, detail: t.attentionPlannedActionsDetail, count: plannedActions.length, severity: plannedActions.length > 0 ? "low" : "good", group: "operations" },
    { label: t.attentionImportanceReviews, detail: t.attentionImportanceReviewsDetail, count: importanceReviewCount, severity: importanceReviewCount > 0 ? "low" : "good", group: "governance" },
    { label: t.attentionSplitCandidates, detail: t.attentionSplitCandidatesDetail, count: splitCount, severity: splitCount > 0 ? "low" : "good", group: "governance" },
  ];

  const rank = { high: 0, medium: 1, low: 2, good: 3 };
  return items.sort((a, b) => rank[a.severity] - rank[b.severity] || b.count - a.count);
}

function buildRecommendations({
  t, contradictionCount, duplicateCount, staleCount, neverAccessedRatio, connectedCoverage, llmStatus,
}: {
  t: ReturnType<typeof useI18n>["messages"]["dashboard"];
  contradictionCount: number;
  duplicateCount: number;
  staleCount: number;
  neverAccessedRatio: number;
  connectedCoverage: number;
  llmStatus: string;
}): RecommendationItem[] {
  const items: RecommendationItem[] = [];
  if (contradictionCount > 0) items.push({ title: t.recommendReviewContradictions, detail: t.recommendReviewContradictionsDetail(contradictionCount), severity: "high" });
  if (duplicateCount > 0) items.push({ title: t.recommendConsolidateDuplicates, detail: t.recommendConsolidateDuplicatesDetail(duplicateCount), severity: "medium" });
  if (neverAccessedRatio >= 50) items.push({ title: t.recommendImproveRecall, detail: t.recommendImproveRecallDetail(neverAccessedRatio), severity: "medium" });
  if (connectedCoverage < 35) items.push({ title: t.recommendGrowLinks, detail: t.recommendGrowLinksDetail(connectedCoverage), severity: "low" });
  if (staleCount > 0) items.push({ title: t.recommendArchiveStale, detail: t.recommendArchiveStaleDetail(staleCount), severity: "low" });
  if (llmStatus !== "success") items.push({ title: t.recommendStabilizeLlm, detail: t.recommendStabilizeLlmDetail(llmStatus || t.unknown), severity: "low" });
  return items.slice(0, 4);
}

function getReviewWorkflow(item: AttentionItem, t: ReturnType<typeof useI18n>["messages"]["dashboard"]): string[] {
  if (item.label === t.attentionContradictions) return [t.reviewWorkflowOpenCandidates, t.reviewWorkflowCompareConflict, t.reviewWorkflowArchiveOrRewrite, t.reviewWorkflowVerifyContext];
  if (item.label === t.attentionMergeOpportunities) return [t.reviewWorkflowOpenOperations, t.reviewWorkflowRunLlmReview, t.reviewWorkflowAcceptSafeMerges, t.reviewWorkflowVerifyDuplicates];
  if (item.label === t.attentionAgingKnowledge) return [t.reviewWorkflowOpenCandidates, t.reviewWorkflowCheckStaleness, t.reviewWorkflowArchiveSmallBatch, t.reviewWorkflowVerifyHealth];
  return [t.reviewWorkflowOpenCandidates, t.reviewWorkflowInspectSample, t.reviewWorkflowApplyAction, t.reviewWorkflowVerifyHealth];
}

function getReviewOperationHint(item: AttentionItem, t: ReturnType<typeof useI18n>["messages"]["dashboard"]): string {
  if (item.label === t.attentionMergeOpportunities || item.label === t.attentionSplitCandidates || item.label === t.attentionImportanceReviews) return t.reviewOperationHintLlm;
  if (item.label === t.attentionPlannedActions || item.label === t.attentionAgingKnowledge) return t.reviewOperationHintRule;
  return t.reviewOperationHintManual;
}

function buildReviewQueue(attentionItems: AttentionItem[], curatorStatus: CuratorStatusPayload | null, t: ReturnType<typeof useI18n>["messages"]["dashboard"]): ReviewQueueItem[] {
  const hrefByLabel: Record<string, string> = {
    [t.attentionContradictions]: "/governance?decision_type=contradiction",
    [t.attentionMergeOpportunities]: "/governance?decision_type=semantic_duplicate",
    [t.attentionAgingKnowledge]: "#curator-panel",
    [t.attentionPendingReview]: "#curator-panel",
    [t.attentionPlannedActions]: "#curator-panel",
    [t.attentionImportanceReviews]: "/governance?decision_type=importance_reassessment",
    [t.attentionSplitCandidates]: "/governance?decision_type=split_candidate",
  };

  return attentionItems
    .filter((item) => item.count > 0)
    .slice(0, 5)
    .map((item) => {
      const isGovernance = item.group === "governance";
      return {
        ...item,
        href: hrefByLabel[item.label] ?? "#curator-panel",
        actionLabel: item.severity === "high" ? t.reviewNow : t.inspect,
        workflow: getReviewWorkflow(item, t),
        operationHint: getReviewOperationHint(item, t),
        primaryHref: hrefByLabel[item.label] ?? "#curator-panel",
        primaryLabel: isGovernance ? t.reviewOpenGovernance : t.viewCurator,
      };
    });
}

function downloadGovernanceReport(report: Record<string, unknown>): void {
  const blob = new Blob([JSON.stringify(report, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `memorycore-governance-${new Date().toISOString().slice(0, 10)}.json`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

const DASHBOARD_FETCH_TIMEOUT_MS = 15_000;

export function MemoryIntelligenceCenter() {
  const userId = useSelector((state: RootState) => state.profile.userId);
  const dashboardRefreshKey = useSelector((state: RootState) => state.ui.dashboardRefreshKey);
  const { messages, locale } = useI18n();
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
        const [curatorResponse, statsResponse, memoriesResponse] = await Promise.all([
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
        ]);

        if (!curatorResponse.ok || !statsResponse.ok || !memoriesResponse.ok) {
          throw new Error("Unable to load intelligence data");
        }

        const curatorPayload = (await curatorResponse.json()) as ApiEnvelope<CuratorStatusPayload> | CuratorStatusPayload;
        const statsPayload = (await statsResponse.json()) as StatsPayload;
        const memoriesPayload = (await memoriesResponse.json()) as MemoriesPayload;
        const curatorData = (curatorPayload as ApiEnvelope<CuratorStatusPayload>).data ?? (curatorPayload as CuratorStatusPayload);

        if (controller.signal.aborted) return;
        setState({
          curatorStatus: curatorData,
          recentMemories: memoriesPayload.items ?? [],
          stats: statsPayload,
          isLoading: false,
          error: null,
        });
      } catch (error: unknown) {
        if (controller.signal.aborted && !didTimeout) return;
        setState({
          ...INITIAL_STATE,
          isLoading: false,
          error: didTimeout || (error instanceof DOMException && error.name === "AbortError")
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

  const handleGovernanceRefresh = useCallback(() => {
    setLocalRefreshKey((k) => k + 1);
  }, []);

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
  const nonArchivedRatio = inversePercentage(archived, totalMemories);
  const attentionItems = useMemo(() => buildAttentionItems(curatorStatus, t, llmRunning ? null : handleRunLlm), [curatorStatus, t, llmRunning, handleRunLlm]);
  const highRiskCount = attentionItems.filter((item) => item.severity === "high").length;
  const curatorSummary = curatorStatus?.curator?.summary ?? {};
  const llmSummary = curatorStatus?.llm_curator?.summary ?? {};
  const contradictionCount = contradicted + asNumber(llmSummary.contradictions) + asNumber(curatorSummary.contradictions);
  const duplicateCount = asNumber(curatorSummary.duplicates) + asNumber(llmSummary.semantic_duplicates);
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
  const healthSignals: HealthSignal[] = [
    { label: t.riskControl, value: riskScore, detail: t.riskControlDetail(contradictionCount, duplicateCount) },
    { label: t.reuseCoverage, value: inversePercentage(neverAccessed, totalMemories), detail: t.reuseCoverageDetail(neverAccessed) },
    { label: t.linkedCoverage, value: connectedCoverage, detail: t.linkedCoverageDetail(linkCount) },
    { label: t.nonArchivedRatio, value: nonArchivedRatio, detail: t.nonArchivedRatioDetail(totalMemories - archived) },
    { label: t.llmGovernance, value: llmGovernanceScore, detail: llmStatus },
  ];
  const recommendations = buildRecommendations({
    t, contradictionCount, duplicateCount, staleCount: staleActionCount, neverAccessedRatio, connectedCoverage, llmStatus,
  });
  const reviewQueue = buildReviewQueue(attentionItems, curatorStatus, t);
  const typeEntries = Object.entries(byType).sort(([, a], [, b]) => asNumber(b) - asNumber(a)).slice(0, 5);
  const sourceEntries = Object.entries(
    state.recentMemories.reduce<Record<string, number>>((acc, memory) => {
      const source = memory.app_name || "Unknown";
      return { ...acc, [source]: (acc[source] ?? 0) + 1 };
    }, {}),
  ).sort(([, a], [, b]) => b - a);
  const recentCount = state.recentMemories.filter((memory) => Date.now() - new Date(memory.created_at).getTime() <= 7 * DAY_MS).length;
  const oldCount = state.recentMemories.filter((memory) => Date.now() - new Date(memory.created_at).getTime() > 30 * DAY_MS).length;
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

  if (state.isLoading) {
    return <MemoryIntelligenceSkeleton />;
  }

  return (
    <section className="space-y-4">
      <SectionHeader onExport={() => downloadGovernanceReport(governanceReport)} />

      {state.error && (
        <Card className="border-amber-900/60 bg-amber-950/20">
          <CardContent className="flex items-center justify-between gap-3 py-4 text-sm text-amber-200">
            <div className="flex items-center gap-3">
              <AlertTriangle className="h-4 w-4 flex-shrink-0" />
              <span>{state.error}</span>
            </div>
            <Button
              variant="outline"
              size="sm"
              className="border-amber-800/60 bg-amber-950/40 text-amber-200 hover:bg-amber-900/40 hover:text-amber-100 shrink-0"
              onClick={() => setLocalRefreshKey((k) => k + 1)}
            >
              <RefreshCw className="h-3 w-3 mr-1" />
              {messages.common.retry}
            </Button>
          </CardContent>
        </Card>
      )}

      {/* Auto-Applied Strip */}
      <AutoAppliedStrip refreshKey={localRefreshKey} onRefresh={handleGovernanceRefresh} />

      {/* Needs Human Review Queue */}
      <NeedsReviewQueue refreshKey={localRefreshKey} onRefresh={handleGovernanceRefresh} />

      {/* Recommended Actions */}
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

      {/* Row 1: Health + Review Flow */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-5">
        <HealthMetricsPanel qualityScore={qualityScore} healthSignals={healthSignals} />
        <ReviewQueuePanel
          reviewQueue={reviewQueue}
          selectedReviewLabel={selectedReviewLabel}
          onSelectReview={setSelectedReviewLabel}
          onExport={() => downloadGovernanceReport(governanceReport)}
        />
      </div>

      {/* Row 2: Activity + Source Breakdown */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-5">
        <CurationTimeline
          curatorGeneratedAt={curatorStatus?.curator?.generated_at}
          curatorScanned={curatorStatus?.curator?.scanned}
          totalMemories={totalMemories}
          serviceResult={curatorStatus?.service?.Result}
          recentMemoryTitle={getMemoryTitle(state.recentMemories[0], t.noRecentMemoryActivity)}
          recentMemoryTime={formatDate(state.recentMemories[0]?.created_at, locale)}
          timerNextElapse={curatorStatus?.timer?.NextElapseUSecRealtime}
          timerActiveState={curatorStatus?.timer?.ActiveState}
        />
        <SourceBreakdown
          typeEntries={typeEntries}
          sourceEntries={sourceEntries}
          totalMemories={totalMemories}
          recentMemoriesCount={state.recentMemories.length}
          recentCount={recentCount}
          oldCount={oldCount}
        />
      </div>
    </section>
  );
}

function SectionHeader({ onExport }: { onExport: () => void }) {
  const { messages } = useI18n();
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h2 className="text-base font-medium text-zinc-300">{messages.dashboard.intelligenceTitle}</h2>
        <p className="mt-1 max-w-3xl text-sm text-zinc-500">
          {messages.dashboard.intelligenceDescription}
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" size="sm" className="w-fit border-zinc-700/50 bg-zinc-900 text-zinc-300 hover:bg-zinc-800" onClick={onExport}>
          <ArrowDownToLine className="h-4 w-4" />
          {messages.dashboard.reportExport}
        </Button>
        <Button asChild variant="outline" size="sm" className="w-fit border-zinc-700/50 bg-zinc-900 text-zinc-300 hover:bg-zinc-800">
          <Link href="/memories">
            {messages.dashboard.openMemories}
            <ArrowRight className="h-4 w-4" />
          </Link>
        </Button>
      </div>
    </div>
  );
}

function MemoryIntelligenceSkeleton() {
  return (
    <section className="space-y-4">
      <SectionHeader onExport={() => undefined} />
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        {[0, 1, 2].map((item) => (
          <Card key={item} className="border-zinc-800 bg-zinc-900">
            <CardHeader>
              <div className="h-4 w-40 animate-pulse rounded bg-zinc-800" />
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="h-16 animate-pulse rounded bg-zinc-800/80" />
              <div className="h-16 animate-pulse rounded bg-zinc-800/70" />
              <div className="h-16 animate-pulse rounded bg-zinc-800/60" />
            </CardContent>
          </Card>
        ))}
      </div>
    </section>
  );
}

export default MemoryIntelligenceCenter;
