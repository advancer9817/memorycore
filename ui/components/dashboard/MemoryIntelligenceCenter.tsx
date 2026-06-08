"use client";

import Link from "next/link";
import { ReactNode, useEffect, useMemo, useState } from "react";
import { useSelector } from "react-redux";
import {
  Activity,
  AlertTriangle,
  ArrowDownToLine,
  ArrowRight,
  BrainCircuit,
  CheckCircle2,
  Clock3,
  GitBranch,
  Network,
  RadioTower,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  Workflow,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { RootState } from "@/store/store";
import { getApiBaseUrl } from "@/lib/api-url";
import { useI18n } from "@/hooks/useI18n";

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
}

interface TrendPoint {
  label: string;
  value: number;
  detail: string;
  tone: "good" | "warn" | "danger";
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

function formatNumber(value: number): string {
  return new Intl.NumberFormat("en-US").format(value);
}

function formatDate(value?: string | number): string {
  if (!value || value === "n/a") return "n/a";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "n/a";
  return date.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function titleCase(value: string): string {
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function getMemoryTitle(memory?: MemoryApiItem): string {
  const content = memory?.content?.trim();
  if (!content) return "No recent memory activity";
  return content.length > 92 ? `${content.slice(0, 92)}…` : content;
}

function buildAttentionItems(curatorStatus: CuratorStatusPayload | null, t: ReturnType<typeof useI18n>["messages"]["dashboard"]): AttentionItem[] {
  const summary = curatorStatus?.curator?.summary ?? {};
  const llmSummary = curatorStatus?.llm_curator?.summary ?? {};
  const byStatus = curatorStatus?.stats?.by_status ?? {};
  const plannedActions = curatorStatus?.curator?.planned_actions ?? [];
  const contradictionCount =
    asNumber(summary.contradiction_candidates) +
    asNumber(summary.contradictions) +
    asNumber(llmSummary.contradictions) +
    asNumber(byStatus.contradicted);
  const duplicateCount =
    asNumber(summary.duplicate_title_groups) +
    asNumber(summary.semantic_duplicates) +
    asNumber(summary.duplicates) +
    asNumber(llmSummary.semantic_duplicates);
  const agingCount =
    asNumber(summary.stale_candidates) +
    asNumber(summary.archive_candidates) +
    asNumber(summary.stale) +
    asNumber(summary.archive);
  const candidateCount = asNumber(byStatus.candidate);
  const splitCount = asNumber(llmSummary.split_candidates);
  const importanceReviewCount = asNumber(llmSummary.importance_reassessments);

  const items: AttentionItem[] = [
    {
      label: t.attentionContradictions,
      detail: t.attentionContradictionsDetail,
      count: contradictionCount,
      severity: contradictionCount > 0 ? "high" : "good",
    },
    {
      label: t.attentionMergeOpportunities,
      detail: t.attentionMergeOpportunitiesDetail,
      count: duplicateCount,
      severity: duplicateCount > 0 ? "medium" : "good",
    },
    {
      label: t.attentionAgingKnowledge,
      detail: t.attentionAgingKnowledgeDetail,
      count: agingCount,
      severity: agingCount > 0 ? "medium" : "good",
    },
    {
      label: t.attentionPendingReview,
      detail: t.attentionPendingReviewDetail,
      count: candidateCount,
      severity: candidateCount > 0 ? "low" : "good",
    },
    {
      label: t.attentionPlannedActions,
      detail: t.attentionPlannedActionsDetail,
      count: plannedActions.length,
      severity: plannedActions.length > 0 ? "low" : "good",
    },
    {
      label: t.attentionImportanceReviews,
      detail: t.attentionImportanceReviewsDetail,
      count: importanceReviewCount,
      severity: importanceReviewCount > 0 ? "low" : "good",
    },
    {
      label: t.attentionSplitCandidates,
      detail: t.attentionSplitCandidatesDetail,
      count: splitCount,
      severity: splitCount > 0 ? "low" : "good",
    },
  ];

  const rank = { high: 0, medium: 1, low: 2, good: 3 };
  return items.sort((a, b) => rank[a.severity] - rank[b.severity] || b.count - a.count);
}

function buildRecommendations({
  t,
  contradictionCount,
  duplicateCount,
  staleCount,
  neverAccessedRatio,
  connectedCoverage,
  llmStatus,
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

  if (contradictionCount > 0) {
    items.push({
      title: t.recommendReviewContradictions,
      detail: t.recommendReviewContradictionsDetail(contradictionCount),
      severity: "high",
    });
  }

  if (duplicateCount > 0) {
    items.push({
      title: t.recommendConsolidateDuplicates,
      detail: t.recommendConsolidateDuplicatesDetail(duplicateCount),
      severity: "medium",
    });
  }

  if (neverAccessedRatio >= 50) {
    items.push({
      title: t.recommendImproveRecall,
      detail: t.recommendImproveRecallDetail(neverAccessedRatio),
      severity: "medium",
    });
  }

  if (connectedCoverage < 35) {
    items.push({
      title: t.recommendGrowLinks,
      detail: t.recommendGrowLinksDetail(connectedCoverage),
      severity: "low",
    });
  }

  if (staleCount > 0) {
    items.push({
      title: t.recommendArchiveStale,
      detail: t.recommendArchiveStaleDetail(staleCount),
      severity: "low",
    });
  }

  if (llmStatus !== "success") {
    items.push({
      title: t.recommendStabilizeLlm,
      detail: t.recommendStabilizeLlmDetail(llmStatus || t.unknown),
      severity: "low",
    });
  }

  return items.slice(0, 4);
}

function buildReviewQueue(attentionItems: AttentionItem[], t: ReturnType<typeof useI18n>["messages"]["dashboard"]): ReviewQueueItem[] {
  const hrefByLabel: Record<string, string> = {
    [t.attentionContradictions]: "/memories?state=contradicted",
    [t.attentionMergeOpportunities]: "/memories?search=duplicate",
    [t.attentionAgingKnowledge]: "/memories?state=stale",
    [t.attentionPendingReview]: "/memories?state=candidate",
    [t.attentionPlannedActions]: "/memories?state=candidate",
    [t.attentionImportanceReviews]: "/memories?search=importance",
    [t.attentionSplitCandidates]: "/memories?search=split",
  };

  return attentionItems
    .filter((item) => item.count > 0)
    .slice(0, 5)
    .map((item) => ({
      ...item,
      href: hrefByLabel[item.label] ?? "/memories",
      actionLabel: item.severity === "high" ? t.reviewNow : t.inspect,
    }));
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

export function MemoryIntelligenceCenter() {
  const userId = useSelector((state: RootState) => state.profile.userId);
  const { messages } = useI18n();
  const t = messages.dashboard;
  const [state, setState] = useState<IntelligenceState>(INITIAL_STATE);

  useEffect(() => {
    let isMounted = true;

    async function loadIntelligence(): Promise<void> {
      setState((current) => ({ ...current, isLoading: true, error: null }));
      try {
        const apiBaseUrl = getApiBaseUrl();
        const [curatorResponse, statsResponse, memoriesResponse] = await Promise.all([
          fetch(`${apiBaseUrl}/api/curator/status`),
          fetch(`${apiBaseUrl}/api/v1/stats?user_id=${encodeURIComponent(userId)}`),
          fetch(`${apiBaseUrl}/api/v1/memories/filter`, {
            method: "POST",
            headers: { "content-type": "application/json" },
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

        if (!isMounted) return;
        setState({
          curatorStatus: curatorData,
          recentMemories: memoriesPayload.items ?? [],
          stats: statsPayload,
          isLoading: false,
          error: null,
        });
      } catch (error: unknown) {
        if (!isMounted) return;
        setState({
          ...INITIAL_STATE,
          isLoading: false,
          error: error instanceof Error ? error.message : "Unable to load intelligence data",
        });
      }
    }

    loadIntelligence();
    return () => {
      isMounted = false;
    };
  }, [userId]);

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
  const attentionItems = useMemo(() => buildAttentionItems(curatorStatus, t), [curatorStatus, t]);
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
    t,
    contradictionCount,
    duplicateCount,
    staleCount: staleActionCount,
    neverAccessedRatio,
    connectedCoverage,
    llmStatus,
  });
  const reviewQueue = buildReviewQueue(attentionItems, t);
  const trendPoints: TrendPoint[] = [
    { label: t.trendHealth, value: qualityScore, detail: t.trendHealthDetail(connectedCoverage), tone: qualityScore >= 70 ? "good" : "warn" },
    { label: t.trendDuplicates, value: duplicateCount, detail: t.trendDuplicatesDetail(duplicateCount), tone: duplicateCount > 0 ? "warn" : "good" },
    { label: t.trendConflicts, value: contradictionCount, detail: t.trendConflictsDetail(contradictionCount), tone: contradictionCount > 0 ? "danger" : "good" },
    { label: t.trendDormant, value: neverAccessedRatio, detail: t.trendDormantDetail(neverAccessed), tone: neverAccessedRatio >= 50 ? "warn" : "good" },
  ];
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

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Card className="border-zinc-800 bg-zinc-900">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center justify-between text-sm font-medium text-zinc-300">
              {t.needsAttention}
              <AlertTriangle className="h-4 w-4 text-amber-400" />
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {attentionItems.map((item) => (
              <div key={item.label} className={`rounded-lg border px-3 py-2.5 ${severityClassName[item.severity]}`}>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-sm font-medium">{item.label}</span>
                  <Badge variant="outline" className="border-current/30 bg-black/20 text-current">
                    {item.count}
                  </Badge>
                </div>
                <p className="mt-1 text-xs leading-relaxed text-current/75">{item.detail}</p>
              </div>
            ))}
          </CardContent>
        </Card>

        <Card className="border-zinc-800 bg-zinc-900">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center justify-between text-sm font-medium text-zinc-300">
              {t.memoryHealth}
              <ShieldCheck className="h-4 w-4 text-emerald-400" />
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="rounded-xl border border-zinc-800 bg-zinc-950/55 p-4">
              <div className="flex items-end justify-between">
                <div>
                  <p className="text-xs uppercase tracking-[0.2em] text-zinc-500">{t.governanceScore}</p>
                  <div className="mt-2 text-3xl font-semibold text-white">{qualityScore}</div>
                </div>
                <Badge
                  className={qualityScore >= 70 ? "border-emerald-700 bg-emerald-500/10 text-emerald-300" : "border-amber-700 bg-amber-500/10 text-amber-300"}
                  variant="outline"
                >
                  {qualityScore >= 70 ? t.healthy : t.needsWork}
                </Badge>
              </div>
              <Progress value={qualityScore} className="mt-4 h-2 bg-zinc-800" />
              <p className="mt-2 text-xs leading-relaxed text-zinc-500">
                {t.healthScoreDescription}
              </p>
            </div>
            {healthSignals.map((signal) => (
              <MetricBar key={signal.label} label={signal.label} value={signal.value} detail={signal.detail} />
            ))}
          </CardContent>
        </Card>

        <Card className="border-zinc-800 bg-zinc-900">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center justify-between text-sm font-medium text-zinc-300">
              {t.graphSnapshot}
              <Network className="h-4 w-4 text-violet-300" />
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-3">
              <GraphMetric icon={<BrainCircuit className="h-4 w-4" />} label={t.nodes} value={totalMemories} />
              <GraphMetric icon={<GitBranch className="h-4 w-4" />} label={t.links} value={linkCount} />
              <GraphMetric icon={<Sparkles className="h-4 w-4" />} label={t.candidates} value={candidates} />
              <GraphMetric icon={<RadioTower className="h-4 w-4" />} label={t.apps} value={totalApps} />
            </div>
            <div className="mt-4 rounded-xl border border-violet-900/40 bg-violet-950/20 p-3 text-xs leading-relaxed text-violet-100/80">
              {t.graphSnapshotDescription}
            </div>
            <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
              <MiniMetric label={t.active} value={`${activeRatio}%`} />
              <MiniMetric label={t.archived} value={`${archivedRatio}%`} />
            </div>
          </CardContent>
        </Card>
      </div>

      <Card className="border-zinc-800 bg-zinc-900">
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center justify-between text-sm font-medium text-zinc-300">
            {t.recommendedActions}
            <ArrowRight className="h-4 w-4 text-zinc-500" />
          </CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
          {recommendations.length > 0 ? (
            recommendations.map((item) => (
              <div key={item.title} className={`rounded-xl border px-3 py-3 ${severityClassName[item.severity]}`}>
                <p className="text-sm font-medium">{item.title}</p>
                <p className="mt-1 text-xs leading-relaxed text-current/75">{item.detail}</p>
              </div>
            ))
          ) : (
            <div className="rounded-xl border border-emerald-800/70 bg-emerald-950/25 px-3 py-3 text-sm text-emerald-200">
              {t.noRecommendations}
            </div>
          )}
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-5">
        <Card className="border-zinc-800 bg-zinc-900 xl:col-span-3">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center justify-between text-sm font-medium text-zinc-300">
              {t.healthTrendSnapshot}
              <TrendingUp className="h-4 w-4 text-emerald-400" />
            </CardTitle>
          </CardHeader>
          <CardContent className="grid grid-cols-2 gap-3 md:grid-cols-4">
            {trendPoints.map((point) => (
              <TrendTile key={point.label} point={point} />
            ))}
          </CardContent>
        </Card>
        <Card className="border-zinc-800 bg-zinc-900 xl:col-span-2">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center justify-between text-sm font-medium text-zinc-300">
              {t.reviewQueue}
              <AlertTriangle className="h-4 w-4 text-amber-400" />
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {reviewQueue.length > 0 ? reviewQueue.map((item) => (
              <Link key={item.label} href={item.href} className={`block rounded-lg border px-3 py-2.5 transition hover:brightness-110 ${severityClassName[item.severity]}`}>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-sm font-medium">{item.label}</span>
                  <span className="text-xs text-current/75">{item.actionLabel} →</span>
                </div>
                <p className="mt-1 text-xs text-current/75">{t.reviewQueueItemDetail(item.count, item.detail)}</p>
              </Link>
            )) : (
              <div className="rounded-lg border border-emerald-800/70 bg-emerald-950/25 px-3 py-3 text-sm text-emerald-200">{t.noActiveReviewQueue}</div>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-5">
        <Card className="border-zinc-800 bg-zinc-900 xl:col-span-3">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center justify-between text-sm font-medium text-zinc-300">
              {t.curationActivity}
              <Clock3 className="h-4 w-4 text-zinc-500" />
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <TimelineItem
              icon={<Workflow className="h-4 w-4" />}
              title="Curator scan completed"
              detail={`${curatorStatus?.curator?.scanned ?? totalMemories} memories scanned · ${curatorStatus?.service?.Result ?? "unknown"}`}
              time={formatDate(curatorStatus?.curator?.generated_at)}
            />
            <TimelineItem
              icon={<Activity className="h-4 w-4" />}
              title="Recent memory signal"
              detail={getMemoryTitle(state.recentMemories[0])}
              time={formatDate(state.recentMemories[0]?.created_at)}
            />
            <TimelineItem
              icon={<CheckCircle2 className="h-4 w-4" />}
              title="Background schedule"
              detail={`Next run ${formatDate(curatorStatus?.timer?.NextElapseUSecRealtime)}`}
              time={curatorStatus?.timer?.ActiveState ?? "unknown"}
            />
          </CardContent>
        </Card>

        <Card className="border-zinc-800 bg-zinc-900 xl:col-span-2">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center justify-between text-sm font-medium text-zinc-300">
              {t.sourceBreakdown}
              <RadioTower className="h-4 w-4 text-zinc-500" />
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <BreakdownList title={t.memoryTypes} entries={typeEntries} total={totalMemories} />
            <BreakdownList title={t.recentSources} entries={sourceEntries} total={Math.max(state.recentMemories.length, 1)} />
            <div className="rounded-lg border border-zinc-800 bg-zinc-950/45 px-3 py-2 text-xs text-zinc-500">
              {t.freshSignals(recentCount, oldCount)}
            </div>
          </CardContent>
        </Card>
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

function TrendTile({ point }: { point: TrendPoint }) {
  const toneClass = point.tone === "danger" ? "text-red-300 bg-red-950/30 border-red-900/60" : point.tone === "warn" ? "text-amber-300 bg-amber-950/30 border-amber-900/60" : "text-emerald-300 bg-emerald-950/30 border-emerald-900/60";
  return (
    <div className={`rounded-xl border p-3 ${toneClass}`}>
      <div className="text-xs uppercase tracking-[0.16em] text-current/70">{point.label}</div>
      <div className="mt-2 text-2xl font-semibold">{formatNumber(point.value)}</div>
      <p className="mt-1 text-xs leading-relaxed text-current/75">{point.detail}</p>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-black/20">
        <div className="h-full rounded-full bg-current" style={{ width: `${Math.min(100, Math.max(8, point.value))}%` }} />
      </div>
    </div>
  );
}

function MetricBar({ label, value, detail }: { label: string; value: number; detail: string }) {
  return (
    <div>
      <div className="mb-2 flex items-center justify-between text-xs">
        <span className="text-zinc-400">{label}</span>
        <span className="text-zinc-500">{detail}</span>
      </div>
      <Progress value={value} className="h-1.5 bg-zinc-800" />
    </div>
  );
}

function GraphMetric({ icon, label, value }: { icon: ReactNode; label: string; value: number }) {
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-950/55 p-3">
      <div className="flex items-center justify-between text-zinc-500">
        <span className="text-xs">{label}</span>
        {icon}
      </div>
      <div className="mt-2 text-xl font-semibold text-white">{formatNumber(value)}</div>
    </div>
  );
}

function MiniMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950/45 px-3 py-2">
      <div className="text-[10px] uppercase tracking-[0.16em] text-zinc-600">{label}</div>
      <div className="mt-1 text-sm font-medium text-zinc-200">{value}</div>
    </div>
  );
}

function TimelineItem({ icon, title, detail, time }: { icon: ReactNode; title: string; detail: string; time: string }) {
  return (
    <div className="flex gap-3 rounded-xl border border-zinc-800 bg-zinc-950/45 p-3">
      <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-zinc-700 bg-zinc-900 text-zinc-400">
        {icon}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-sm font-medium text-zinc-200">{title}</p>
          <span className="text-xs text-zinc-500">{time}</span>
        </div>
        <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-zinc-500">{detail}</p>
      </div>
    </div>
  );
}

function BreakdownList({ title, entries, total }: { title: string; entries: [string, number][]; total: number }) {
  return (
    <div>
      <div className="mb-2 text-xs uppercase tracking-[0.16em] text-zinc-500">{title}</div>
      <div className="space-y-2">
        {entries.length > 0 ? (
          entries.map(([label, count]) => (
            <div key={label}>
              <div className="mb-1 flex items-center justify-between text-xs">
                <span className="text-zinc-300">{titleCase(label)}</span>
                <span className="text-zinc-500">{count}</span>
              </div>
              <Progress value={percentage(count, total)} className="h-1.5 bg-zinc-800" />
            </div>
          ))
        ) : (
          <div className="rounded-lg border border-zinc-800 bg-zinc-950/40 px-3 py-2 text-xs text-zinc-500">
            No distribution data yet.
          </div>
        )}
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
