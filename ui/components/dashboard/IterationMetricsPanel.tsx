"use client";

import React, { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Activity, AlertTriangle, BarChart3, Bot } from "lucide-react";
import { getApiBaseUrl } from "@/lib/api-url";

interface RecallMetrics {
  total_active: number;
  never_injected: number;
  injected: number;
  never_injected_pct: number;
  avg_injected_count: number;
  avg_effectiveness: number;
  by_source: Array<{
    source: string;
    total: number;
    never_injected: number;
    never_injected_pct: number;
  }>;
}

interface GovernanceMetrics {
  total_decisions: number;
  status_distribution: Record<string, number>;
  needs_review: number;
  needs_review_pct: number;
  recent_7d: {
    applied: number;
    needs_review: number;
    rolled_back: number;
  };
}

interface CuratorMetrics {
  latest_report: string | null;
  latest_report_size_kb: number;
  total_reports: number;
  total_reports_size_mb: number;
  memories_produced: number;
}

type MetricsState = {
  recall: RecallMetrics | null;
  governance: GovernanceMetrics | null;
  curator: CuratorMetrics | null;
  error: string | null;
  loading: boolean;
};

function MetricValue({ label, value, suffix, warn }: {
  label: string;
  value: string | number;
  suffix?: string;
  warn?: boolean;
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-xs text-zinc-500">{label}</span>
      <span className={`text-lg font-semibold tabular-nums ${warn ? "text-amber-400" : "text-zinc-100"}`}>
        {value}{suffix && <span className="text-sm font-normal text-zinc-500 ml-0.5">{suffix}</span>}
      </span>
    </div>
  );
}

function StatusDot({ ok }: { ok: boolean }) {
  return (
    <span className={`inline-block w-2 h-2 rounded-full ${ok ? "bg-emerald-400" : "bg-amber-400"}`} />
  );
}

export function IterationMetricsPanel() {
  const [state, setState] = useState<MetricsState>({
    recall: null, governance: null, curator: null, error: null, loading: true,
  });

  useEffect(() => {
    let cancelled = false;
    async function load() {
      const base = getApiBaseUrl();
      try {
        const [recallRes, govRes, curRes] = await Promise.all([
          fetch(`${base}/api/metrics/recall`),
          fetch(`${base}/api/metrics/governance`),
          fetch(`${base}/api/metrics/curator`),
        ]);
        const [recallJson, govJson, curJson] = await Promise.all([
          recallRes.json(),
          govRes.json(),
          curJson_parse(curRes),
        ]);
        if (cancelled) return;
        setState({
          recall: recallJson.data ?? recallJson,
          governance: govJson.data ?? govJson,
          curator: (curJson.data ?? curJson) as CuratorMetrics ?? null,
          error: null,
          loading: false,
        });
      } catch (err: unknown) {
        if (cancelled) return;
        setState((s) => ({ ...s, error: err instanceof Error ? err.message : "fetch failed", loading: false }));
      }
    }
    load();
    const timer = setInterval(load, 30_000);
    return () => { cancelled = true; clearInterval(timer); };
  }, []);

  if (state.loading) {
    return (
      <Card className="bg-zinc-900/60 border-zinc-800">
        <CardContent className="py-8 text-center text-zinc-500 text-sm">
          Loading iteration metrics...
        </CardContent>
      </Card>
    );
  }

  if (state.error) {
    return (
      <Card className="bg-zinc-900/60 border-zinc-800">
        <CardContent className="py-6 text-center text-amber-400 text-sm">
          Metrics unavailable: {state.error}
        </CardContent>
      </Card>
    );
  }

  const { recall, governance, curator } = state;

  const recallOk = (recall?.never_injected_pct ?? 100) < 40;
  const govOk = (governance?.needs_review ?? 999) < 200;

  return (
    <Card className="bg-zinc-900/60 border-zinc-800">
      <CardHeader className="pb-3">
        <CardTitle className="text-sm font-medium text-zinc-300 flex items-center gap-2">
          <BarChart3 className="w-4 h-4 text-zinc-500" />
          Iteration Metrics
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {/* Recall Efficiency */}
          <div className="space-y-3">
            <div className="flex items-center gap-2 text-xs font-medium text-zinc-400">
              <Activity className="w-3.5 h-3.5" />
              <StatusDot ok={recallOk} />
              Recall Efficiency
            </div>
            {recall && (
              <div className="grid grid-cols-2 gap-3">
                <MetricValue label="Active" value={recall.total_active} />
                <MetricValue
                  label="Never Recalled"
                  value={`${recall.never_injected_pct}%`}
                  warn={!recallOk}
                />
                <MetricValue label="Avg Injections" value={recall.avg_injected_count} />
                <MetricValue label="Effectiveness" value={recall.avg_effectiveness} />
              </div>
            )}
            {recall && recall.by_source.length > 0 && (
              <div className="text-xs text-zinc-600 space-y-0.5 pt-1 border-t border-zinc-800/50">
                {recall.by_source.slice(0, 4).map((s) => (
                  <div key={s.source} className="flex justify-between">
                    <span className="truncate mr-2">{s.source}</span>
                    <span className={s.never_injected_pct > 70 ? "text-amber-500" : "text-zinc-500"}>
                      {s.never_injected_pct}% unused
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Governance Health */}
          <div className="space-y-3">
            <div className="flex items-center gap-2 text-xs font-medium text-zinc-400">
              <AlertTriangle className="w-3.5 h-3.5" />
              <StatusDot ok={govOk} />
              Governance Health
            </div>
            {governance && (
              <div className="grid grid-cols-2 gap-3">
                <MetricValue label="Total Decisions" value={governance.total_decisions.toLocaleString()} />
                <MetricValue
                  label="Needs Review"
                  value={governance.needs_review}
                  warn={!govOk}
                />
                <MetricValue label="7d Applied" value={governance.recent_7d.applied} />
                <MetricValue label="7d Rollbacks" value={governance.recent_7d.rolled_back} />
              </div>
            )}
            {governance && Object.keys(governance.status_distribution).length > 0 && (
              <div className="text-xs text-zinc-600 space-y-0.5 pt-1 border-t border-zinc-800/50">
                {Object.entries(governance.status_distribution).slice(0, 4).map(([k, v]) => (
                  <div key={k} className="flex justify-between">
                    <span>{k}</span>
                    <span className="text-zinc-500">{v.toLocaleString()}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* LLM Curator */}
          <div className="space-y-3">
            <div className="flex items-center gap-2 text-xs font-medium text-zinc-400">
              <Bot className="w-3.5 h-3.5" />
              LLM Curator
            </div>
            {curator && (
              <div className="grid grid-cols-2 gap-3">
                <MetricValue label="Reports" value={curator.total_reports} />
                <MetricValue label="Disk" value={curator.total_reports_size_mb} suffix="MB" />
                <MetricValue label="Memories Made" value={curator.memories_produced} />
                <MetricValue
                  label="Latest"
                  value={curator.latest_report?.replace(/^llm-curator-|\.json$/g, "").slice(0, 10) ?? "—"}
                />
              </div>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

async function curJson_parse(res: Response): Promise<Record<string, unknown>> {
  try {
    return await res.json();
  } catch {
    return {};
  }
}
