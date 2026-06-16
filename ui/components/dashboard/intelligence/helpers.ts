import { useI18n } from "@/hooks/useI18n";

export const RECENT_MEMORY_LIMIT = 10;
export const DAY_MS = 24 * 60 * 60 * 1000;
export const DASHBOARD_FETCH_TIMEOUT_MS = 15_000;

export interface CuratorAction {
  id?: string;
  title?: string;
  action?: string;
  reason?: string;
}

export interface CuratorStatusPayload {
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

export interface ApiEnvelope<T> {
  data?: T;
}

export interface StatsPayload {
  total_memories?: number;
  total_apps?: number;
}

export interface MemoryApiItem {
  id: string;
  content: string;
  created_at: string;
  state: string;
  categories?: string[];
  app_name?: string;
}

export interface MemoriesPayload {
  items?: MemoryApiItem[];
  total?: number;
}

export interface GovernanceCounts {
  contradiction: number;
  semantic_duplicate: number;
  importance_reassessment: number;
  split_candidate: number;
  total: number;
}

export interface IntelligenceState {
  curatorStatus: CuratorStatusPayload | null;
  recentMemories: MemoryApiItem[];
  stats: StatsPayload | null;
  governanceCounts: GovernanceCounts | null;
  isLoading: boolean;
  error: string | null;
}

export interface AttentionItem {
  label: string;
  detail: string;
  count: number;
  severity: "high" | "medium" | "low" | "good";
  onRun?: () => void;
}

export interface HealthSignal {
  label: string;
  value: number;
  detail: string;
}

export interface RecommendationItem {
  title: string;
  detail: string;
  severity: AttentionItem["severity"];
}

export interface ReviewQueueItem extends AttentionItem {
  href: string;
  actionLabel: string;
  workflow: string[];
  operationHint: string;
  primaryHref: string;
  primaryLabel: string;
}

export interface TrendPoint {
  label: string;
  value: number;
  detail: string;
  tone: "good" | "warn" | "danger";
}

export const INITIAL_STATE: IntelligenceState = {
  curatorStatus: null,
  recentMemories: [],
  stats: null,
  governanceCounts: null,
  isLoading: true,
  error: null,
};

export const severityClassName: Record<AttentionItem["severity"], string> = {
  high: "border-red-800/70 bg-red-950/35 text-red-200",
  medium: "border-amber-800/70 bg-amber-950/35 text-amber-200",
  low: "border-sky-800/70 bg-sky-950/35 text-sky-200",
  good: "border-emerald-800/70 bg-emerald-950/35 text-emerald-200",
};

export function asNumber(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

export function percentage(value: number, total: number): number {
  if (total <= 0) return 0;
  return Math.min(100, Math.round((value / total) * 100));
}

export function inversePercentage(value: number, total: number): number {
  return 100 - percentage(value, total);
}

export function clampScore(value: number): number {
  return Math.max(0, Math.min(100, Math.round(value)));
}

export function weightedScore(signals: Array<{ value: number; weight: number }>): number {
  const totalWeight = signals.reduce((sum, signal) => sum + signal.weight, 0);
  if (totalWeight <= 0) return 0;
  const total = signals.reduce((sum, signal) => sum + clampScore(signal.value) * signal.weight, 0);
  return clampScore(total / totalWeight);
}

export function formatNumber(value: number): string {
  return new Intl.NumberFormat("en-US").format(value);
}

export function formatDate(value?: string | number): string {
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

export function titleCase(value: string): string {
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

export function getMemoryTitle(memory?: MemoryApiItem): string {
  const content = memory?.content?.trim();
  if (!content) return "No recent memory activity";
  return content.length > 92 ? `${content.slice(0, 92)}…` : content;
}

export function buildAttentionItems(
  curatorStatus: CuratorStatusPayload | null,
  t: ReturnType<typeof useI18n>["messages"]["dashboard"],
  onRunLlm: (() => void) | null,
  governanceCounts?: GovernanceCounts | null
): AttentionItem[] {
  const summary = curatorStatus?.curator?.summary ?? {};
  const llmSummary = curatorStatus?.llm_curator?.summary ?? {};
  const byStatus = curatorStatus?.stats?.by_status ?? {};
  const plannedActions = curatorStatus?.curator?.planned_actions ?? [];
  const contradictionCount = governanceCounts != null
    ? governanceCounts.contradiction
    : asNumber(summary.contradiction_candidates) +
      asNumber(summary.contradictions) +
      asNumber(llmSummary.contradictions) +
      asNumber(byStatus.contradicted);
  const duplicateCount = governanceCounts != null
    ? governanceCounts.semantic_duplicate
    : asNumber(summary.duplicate_title_groups) +
      asNumber(summary.semantic_duplicates) +
      asNumber(summary.duplicates) +
      asNumber(llmSummary.semantic_duplicates);
  const agingCount =
    asNumber(summary.stale_candidates) +
    asNumber(summary.archive_candidates) +
    asNumber(summary.stale) +
    asNumber(summary.archive);
  const candidateCount = asNumber(byStatus.candidate);
  const splitCount = governanceCounts != null
    ? governanceCounts.split_candidate
    : asNumber(llmSummary.split_candidates);
  const importanceReviewCount = governanceCounts != null
    ? governanceCounts.importance_reassessment
    : asNumber(llmSummary.importance_reassessments);

  const items: AttentionItem[] = [
    {
      label: t.attentionContradictions,
      detail: t.attentionContradictionsDetail,
      count: contradictionCount,
      severity: contradictionCount > 0 ? "high" : "good",
      onRun: onRunLlm ?? undefined,
    },
    {
      label: t.attentionMergeOpportunities,
      detail: t.attentionMergeOpportunitiesDetail,
      count: duplicateCount,
      severity: duplicateCount > 0 ? "medium" : "good",
      onRun: onRunLlm ?? undefined,
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

export function buildRecommendations({
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

export function getReviewWorkflow(
  item: AttentionItem,
  t: ReturnType<typeof useI18n>["messages"]["dashboard"]
): string[] {
  if (item.label === t.attentionContradictions) {
    return [
      t.reviewWorkflowOpenCandidates,
      t.reviewWorkflowCompareConflict,
      t.reviewWorkflowArchiveOrRewrite,
      t.reviewWorkflowVerifyContext,
    ];
  }

  if (item.label === t.attentionMergeOpportunities) {
    return [
      t.reviewWorkflowOpenOperations,
      t.reviewWorkflowRunLlmReview,
      t.reviewWorkflowAcceptSafeMerges,
      t.reviewWorkflowVerifyDuplicates,
    ];
  }

  if (item.label === t.attentionAgingKnowledge) {
    return [
      t.reviewWorkflowOpenCandidates,
      t.reviewWorkflowCheckStaleness,
      t.reviewWorkflowArchiveSmallBatch,
      t.reviewWorkflowVerifyHealth,
    ];
  }

  return [
    t.reviewWorkflowOpenCandidates,
    t.reviewWorkflowInspectSample,
    t.reviewWorkflowApplyAction,
    t.reviewWorkflowVerifyHealth,
  ];
}

export function getReviewOperationHint(
  item: AttentionItem,
  t: ReturnType<typeof useI18n>["messages"]["dashboard"]
): string {
  if (
    item.label === t.attentionMergeOpportunities ||
    item.label === t.attentionSplitCandidates ||
    item.label === t.attentionImportanceReviews
  ) {
    return t.reviewOperationHintLlm;
  }

  if (item.label === t.attentionPlannedActions || item.label === t.attentionAgingKnowledge) {
    return t.reviewOperationHintRule;
  }

  return t.reviewOperationHintManual;
}

export function buildReviewQueue(
  attentionItems: AttentionItem[],
  curatorStatus: CuratorStatusPayload | null,
  t: ReturnType<typeof useI18n>["messages"]["dashboard"]
): ReviewQueueItem[] {
  const hrefByLabel: Record<string, string> = {
    [t.attentionContradictions]: "/memories?search=contradict&page=1&size=20&sort=created_at&dir=desc",
    [t.attentionMergeOpportunities]: "/memories?search=duplicate&page=1&size=20&sort=created_at&dir=desc",
    [t.attentionAgingKnowledge]: "/memories?search=stale&page=1&size=20&sort=created_at&dir=desc",
    [t.attentionPendingReview]: "/memories?search=candidate&page=1&size=20&sort=created_at&dir=desc",
    [t.attentionPlannedActions]: "/memories?search=candidate&page=1&size=20&sort=created_at&dir=desc",
    [t.attentionImportanceReviews]: "/governance",
    [t.attentionSplitCandidates]: "/governance",
  };

  const llmSummary = curatorStatus?.llm_curator?.summary ?? {};

  return attentionItems
    .filter((item) => item.count > 0)
    .slice(0, 5)
    .map((item) => {
      let primaryHref = hrefByLabel[item.label] ?? "/memories";
      let primaryLabel = t.openMemories;

      if (item.label === t.attentionImportanceReviews || item.label === t.attentionSplitCandidates) {
        primaryHref = item.label === t.attentionImportanceReviews ? "/governance?type=importance_reassessment" : "/governance?type=split_candidate";
        primaryLabel = t.reviewOpenGovernance;
      } else if (item.label === t.attentionContradictions && asNumber(llmSummary.contradictions) > 0) {
        primaryHref = "/governance?type=contradiction";
        primaryLabel = t.reviewOpenGovernance;
      } else if (item.label === t.attentionMergeOpportunities && asNumber(llmSummary.semantic_duplicates) > 0) {
        primaryHref = "/governance?type=semantic_duplicate";
        primaryLabel = t.reviewOpenGovernance;
      }

      return {
        ...item,
        href: hrefByLabel[item.label] ?? "/memories",
        actionLabel: item.severity === "high" ? t.reviewNow : t.inspect,
        workflow: getReviewWorkflow(item, t),
        operationHint: getReviewOperationHint(item, t),
        primaryHref,
        primaryLabel,
      };
    });
}

export function downloadGovernanceReport(report: Record<string, unknown>): void {
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
