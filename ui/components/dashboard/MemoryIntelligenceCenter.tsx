"use client";

import Link from "next/link";
import { ReactNode, useEffect, useMemo, useState } from "react";
import { useSelector } from "react-redux";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  BrainCircuit,
  CheckCircle2,
  Clock3,
  GitBranch,
  Network,
  RadioTower,
  ShieldCheck,
  Sparkles,
  Workflow,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { RootState } from "@/store/store";
import { getApiBaseUrl } from "@/lib/api-url";

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

function buildAttentionItems(curatorStatus: CuratorStatusPayload | null): AttentionItem[] {
  const summary = curatorStatus?.curator?.summary ?? {};
  const byStatus = curatorStatus?.stats?.by_status ?? {};
  const plannedActions = curatorStatus?.curator?.planned_actions ?? [];
  const contradictionCount =
    asNumber(summary.contradiction_candidates) +
    asNumber(summary.contradictions) +
    asNumber(byStatus.contradicted);
  const duplicateCount =
    asNumber(summary.duplicate_title_groups) +
    asNumber(summary.semantic_duplicates) +
    asNumber(summary.duplicates);
  const agingCount =
    asNumber(summary.stale_candidates) +
    asNumber(summary.archive_candidates) +
    asNumber(summary.stale) +
    asNumber(summary.archive);
  const candidateCount = asNumber(byStatus.candidate);

  const items: AttentionItem[] = [
    {
      label: "Contradictions",
      detail: "Conflicting memories should be reviewed before reuse.",
      count: contradictionCount,
      severity: contradictionCount > 0 ? "high" : "good",
    },
    {
      label: "Merge opportunities",
      detail: "Potential duplicates that can be consolidated.",
      count: duplicateCount,
      severity: duplicateCount > 0 ? "medium" : "good",
    },
    {
      label: "Aging knowledge",
      detail: "Stale or archival candidates waiting for curation.",
      count: agingCount,
      severity: agingCount > 0 ? "medium" : "good",
    },
    {
      label: "Pending review",
      detail: "Candidate memories waiting for promotion or cleanup.",
      count: candidateCount,
      severity: candidateCount > 0 ? "low" : "good",
    },
    {
      label: "Planned actions",
      detail: "Rule-based curator actions ready to inspect.",
      count: plannedActions.length,
      severity: plannedActions.length > 0 ? "low" : "good",
    },
  ];

  const rank = { high: 0, medium: 1, low: 2, good: 3 };
  return items.sort((a, b) => rank[a.severity] - rank[b.severity] || b.count - a.count);
}

export function MemoryIntelligenceCenter() {
  const userId = useSelector((state: RootState) => state.profile.userId);
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
  const connectedCoverage = percentage(Math.max(totalMemories - neverAccessed, 0), totalMemories);
  const activeRatio = percentage(active, totalMemories);
  const archivedRatio = percentage(archived, totalMemories);
  const attentionItems = useMemo(() => buildAttentionItems(curatorStatus), [curatorStatus]);
  const highRiskCount = attentionItems.filter((item) => item.severity === "high").length;
  const openIssueCount = attentionItems.reduce((sum, item) => sum + (item.severity === "good" ? 0 : item.count), 0);
  const qualityScore = Math.max(0, Math.min(100, 92 - highRiskCount * 14 - Math.min(openIssueCount, 40)));
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

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Card className="border-zinc-800 bg-zinc-900">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center justify-between text-sm font-medium text-zinc-300">
              Needs Attention
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
              Memory Health
              <ShieldCheck className="h-4 w-4 text-emerald-400" />
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="rounded-xl border border-zinc-800 bg-zinc-950/55 p-4">
              <div className="flex items-end justify-between">
                <div>
                  <p className="text-xs uppercase tracking-[0.2em] text-zinc-500">Quality Score</p>
                  <div className="mt-2 text-3xl font-semibold text-white">{qualityScore}</div>
                </div>
                <Badge className="border-violet-700 bg-violet-500/10 text-violet-300" variant="outline">
                  monitored
                </Badge>
              </div>
              <Progress value={qualityScore} className="mt-4 h-2 bg-zinc-800" />
            </div>
            <MetricBar label="Active ratio" value={activeRatio} detail={`${active} active`} />
            <MetricBar label="Connected coverage" value={connectedCoverage} detail={`${linkCount} links`} />
            <MetricBar label="Archive ratio" value={archivedRatio} detail={`${archived} archived`} />
          </CardContent>
        </Card>

        <Card className="border-zinc-800 bg-zinc-900">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center justify-between text-sm font-medium text-zinc-300">
              Knowledge Graph Snapshot
              <Network className="h-4 w-4 text-violet-300" />
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-3">
              <GraphMetric icon={<BrainCircuit className="h-4 w-4" />} label="Nodes" value={totalMemories} />
              <GraphMetric icon={<GitBranch className="h-4 w-4" />} label="Links" value={linkCount} />
              <GraphMetric icon={<Sparkles className="h-4 w-4" />} label="Candidates" value={candidates} />
              <GraphMetric icon={<RadioTower className="h-4 w-4" />} label="Apps" value={totalApps} />
            </div>
            <div className="mt-4 rounded-xl border border-violet-900/40 bg-violet-950/20 p-3 text-xs leading-relaxed text-violet-100/80">
              Graph details stay in the Graph page; this card summarizes topology and routes deeper exploration.
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-5">
        <Card className="border-zinc-800 bg-zinc-900 xl:col-span-3">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center justify-between text-sm font-medium text-zinc-300">
              Curation & Audit Activity
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
              Source & Type Breakdown
              <RadioTower className="h-4 w-4 text-zinc-500" />
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <BreakdownList title="Memory types" entries={typeEntries} total={totalMemories} />
            <BreakdownList title="Recent sources" entries={sourceEntries} total={Math.max(state.recentMemories.length, 1)} />
            <div className="rounded-lg border border-zinc-800 bg-zinc-950/45 px-3 py-2 text-xs text-zinc-500">
              {recentCount} fresh signals in the sample · {oldCount} aging records over 30 days.
            </div>
          </CardContent>
        </Card>
      </div>
    </section>
  );
}

function SectionHeader() {
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h2 className="text-base font-medium text-zinc-300">Memory Intelligence Center</h2>
        <p className="mt-1 max-w-3xl text-sm text-zinc-500">
          Operational health, curation signals, and knowledge topology without duplicating the Memories browser.
        </p>
      </div>
      <Button
        asChild
        variant="outline"
        size="sm"
        className="w-fit border-zinc-700/50 bg-zinc-900 text-zinc-300 hover:bg-zinc-800"
      >
        <Link href="/memories">
          Open Memories
          <ArrowRight className="h-4 w-4" />
        </Link>
      </Button>
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
      <div className="mt-2 text-xl font-semibold text-white">{value}</div>
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
      <SectionHeader />
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
