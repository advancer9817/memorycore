"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { Activity, Archive, Database, Play, Sparkles, Wrench, type LucideIcon } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useI18n } from "@/hooks/useI18n";
import type { Locale, Messages } from "@/lib/i18n/types";
import {
  type CuratorRunState,
  type CuratorStatus,
  type LlmRunState,
  type MaintenanceAction,
  type MaintenanceRunState,
  ellipsize,
  formatTime,
} from "./memory-operations-types";

type MemoryOperationsViewProps = {
  messages: Messages;
  locale: Locale;
  status: CuratorStatus | null;
  applying: boolean;
  llmRunning: boolean;
  runState: CuratorRunState;
  runActionsShowAll: boolean;
  llmRunState: LlmRunState;
  maintenanceRunState: MaintenanceRunState;
  maintenanceBusy: boolean;
  onApplyCurator: () => void;
  onRunLlmCurator: () => void;
  onShowAllActions: () => void;
  onGenerateMaintenancePlan: () => void;
  onExecuteMaintenance: () => void;
  onSelectMaintenanceAction: (action: MaintenanceAction) => void;
};

export function MemoryOperationsView({
  messages: t,
  locale,
  status,
  applying,
  llmRunning,
  runState,
  runActionsShowAll,
  llmRunState,
  maintenanceRunState,
  maintenanceBusy,
  onApplyCurator,
  onRunLlmCurator,
  onShowAllActions,
  onGenerateMaintenancePlan,
  onExecuteMaintenance,
  onSelectMaintenanceAction,
}: MemoryOperationsViewProps) {
  const byStatus = status?.stats.by_status || {};
  const nextRun = status?.timer.NextElapseUSecRealtime;
  const lastRun = status?.schedules?.rule_curator?.last_run_at || status?.service.ExecMainExitTimestamp || status?.timer.LastTriggerUSec;
  const llmLastRun = status?.llm_curator?.last_run_at || status?.schedules?.llm_curator?.last_run_at;
  const lastResult = status?.service.Result || "unknown";
  const llmLastResult = status?.llm_curator?.last_result || "unknown";

  return (
    <div id="memory-operations">
      <div className="mb-6">
        <h2 className="text-base font-medium text-zinc-400">{t.dashboard.operations}</h2>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        {([
          [t.dashboard.totalMemories, status?.stats.total ?? "-", Database],
          [t.dashboard.active, byStatus.active ?? 0, Activity],
          [t.dashboard.candidates, byStatus.candidate ?? 0, Sparkles],
          [t.dashboard.archived, byStatus.archived ?? 0, Archive],
        ] satisfies Array<[string, string | number, LucideIcon]>).map(([label, value, Icon]) => (
          <Card key={String(label)} className="bg-zinc-900 border-zinc-800">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-zinc-400 flex items-center justify-between">
                {label} <Icon className="h-4 w-4 text-zinc-500" />
              </CardTitle>
            </CardHeader>
            <CardContent><div className="text-2xl font-semibold text-white">{value}</div></CardContent>
          </Card>
        ))}
      </div>

      <div className="mt-4 rounded-lg border border-zinc-800 bg-zinc-900 px-4 py-3 text-sm space-y-2">
        <div className="flex items-center gap-3">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 min-w-0 flex-1 text-xs">
            <Badge variant="outline" className="border-emerald-700 bg-emerald-500/10 text-emerald-300 text-xs shrink-0">
              {t.dashboard.scheduled} · {status?.timer.ActiveState || t.dashboard.unknown}
            </Badge>
            <span className="text-zinc-500">{t.dashboard.ruleLast} <span className="text-zinc-200">{formatTime(lastRun, locale)}</span></span>
            <span className="text-zinc-500">{t.dashboard.llmLast} <span className="text-zinc-200">{formatTime(llmLastRun, locale)}</span></span>
            <span className="text-zinc-500">{t.dashboard.next} <span className="text-zinc-200">{formatTime(nextRun, locale)}</span></span>
            <span className="text-zinc-500">
              {t.dashboard.result} <span className="text-zinc-200">{lastResult}</span>
              <span className="text-zinc-600"> / </span><span className="text-violet-300">LLM {llmLastResult}</span>
            </span>
            <span className="text-zinc-500 hidden lg:inline">{t.dashboard.scanned} <span className="text-zinc-200">{status?.curator.scanned ?? "-"}</span></span>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <Button onClick={onApplyCurator} disabled={applying || llmRunning} variant="outline" size="sm" className="h-7 text-xs border-zinc-700/50 bg-zinc-800 text-zinc-300 hover:bg-zinc-700 transition-colors">
              <Play className="h-3 w-3 mr-1" />{applying ? t.dashboard.running : t.dashboard.runCurator}
            </Button>
            <Button onClick={onRunLlmCurator} disabled={applying || llmRunning} variant="outline" size="sm" className="h-7 text-xs border-zinc-700/50 bg-zinc-800 text-zinc-300 hover:bg-zinc-700 transition-colors">
              <Sparkles className="h-3 w-3 mr-1 text-violet-400" />{llmRunning ? t.dashboard.analyzing : t.dashboard.runLlm}
            </Button>
          </div>
        </div>

        {runState.state !== "idle" && (
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-zinc-800 pt-2">
            <span className="text-zinc-500">{t.dashboard.manualRun}</span>
            <Badge variant="outline" className={runState.state === "succeeded" ? "border-emerald-700 bg-emerald-500/10 text-emerald-300 text-xs" : runState.state === "failed" ? "border-red-700 bg-red-500/10 text-red-300 text-xs" : "border-sky-700 bg-sky-500/10 text-sky-300 text-xs"}>{runState.state}</Badge>
            {runState.startedAt && <span className="text-zinc-500">{formatTime(runState.startedAt, locale)}{runState.elapsedMs !== undefined && <span className="ml-2 text-zinc-400">{(runState.elapsedMs / 1000).toFixed(1)}s</span>}</span>}
            {runState.summary && (
              <span className="text-zinc-500 ml-2">
                {t.dashboard.actions} <span className="text-zinc-200">{runState.summary.actions ?? 0}</span>
                {" · "}{t.dashboard.promote} <span className="text-zinc-200">{runState.summary.skill_promotions ?? 0}</span>
                {" · "}{t.dashboard.archive} <span className="text-zinc-200">{runState.summary.archive ?? 0}</span>
              </span>
            )}
            {runState.error && <span className="text-red-300 ml-2">{runState.error}</span>}
          </div>
        )}
        {runState.actions && runState.actions.length > 0 && (
          <div className="flex flex-col gap-1 border-t border-zinc-800 pt-2">
            {(runActionsShowAll ? runState.actions : runState.actions.slice(0, 3)).map((action, index) => (
              <div key={action.id ?? index} className="rounded bg-zinc-800 px-2 py-1.5 text-xs flex items-start gap-2">
                <div className="min-w-0 flex-1">
                  <div className="truncate whitespace-nowrap" title={[action.action, action.title].filter(Boolean).join(" · ")}>
                    <span className="text-emerald-300 font-medium shrink-0">{ellipsize(action.action, 54)}</span>
                    {action.title && <span className="text-zinc-400"> · {ellipsize(action.title, 72)}</span>}
                  </div>
                  {action.reason && <div className="truncate whitespace-nowrap text-zinc-500 mt-0.5" title={action.reason}>{ellipsize(action.reason, 120)}</div>}
                </div>
                {action.id && <Link href={`/memory/${action.id}`} className="rounded px-1.5 py-0.5 text-[10px] transition-colors bg-zinc-700/50 text-zinc-400 hover:text-zinc-200 shrink-0">{t.common?.details ?? "详情"}</Link>}
              </div>
            ))}
            {!runActionsShowAll && runState.actions.length > 3 && <button onClick={onShowAllActions} className="w-full text-center text-xs text-zinc-400 hover:text-zinc-200 py-1.5 rounded bg-zinc-800/50 hover:bg-zinc-800 transition-colors">{t.dashboard.showAll(runState.actions.length)}</button>}
          </div>
        )}

        {llmRunState.state !== "idle" && (
          <div className="border-t border-zinc-800 pt-2 text-sm space-y-2">
            <div className="flex items-center gap-3">
              <span className="text-zinc-500">{t.dashboard.llmAnalysis}</span>
              <Badge variant="outline" className={llmRunState.state === "succeeded" ? "border-violet-600 bg-violet-500/10 text-violet-300 text-xs" : llmRunState.state === "failed" ? "border-red-700 bg-red-500/10 text-red-300 text-xs" : "border-sky-700 bg-sky-500/10 text-sky-300 text-xs"}>{llmRunState.state}</Badge>
              {llmRunState.state === "running" && llmRunState.startedAt ? <LlmElapsedTimer startedAt={llmRunState.startedAt} /> : llmRunState.elapsedMs !== undefined && <span className="text-zinc-500 text-xs">{(llmRunState.elapsedMs / 1000).toFixed(1)}s</span>}
              {llmRunState.summary && (
                <span className="text-zinc-500 text-xs ml-1">
                  {t.dashboard.duplicates} <span className="text-zinc-200">{llmRunState.summary.semantic_duplicates ?? 0}</span>
                  {" · "}{t.dashboard.contradictions} <span className="text-zinc-200">{llmRunState.summary.contradictions ?? 0}</span>
                  {" · "}{t.dashboard.reassessments} <span className="text-zinc-200">{llmRunState.summary.importance_reassessments ?? 0}</span>
                  {" · "}{t.dashboard.splits} <span className="text-zinc-200">{llmRunState.summary.split_candidates ?? 0}</span>
                  {llmRunState.progress?.stage && <span className="text-zinc-500 text-xs ml-1">stage <span className="text-zinc-200">{llmRunState.progress.stage}</span>{llmRunState.progress.batch_index !== undefined && <span> · batch <span className="text-zinc-200">{llmRunState.progress.batch_index}</span></span>}</span>}
                </span>
              )}
            </div>
            {llmRunState.errors && llmRunState.errors.length > 0 && <div className="space-y-1">{llmRunState.errors.map((error, index) => <div key={`err-${index}-${error.slice(0, 16)}`} className="rounded bg-amber-950/40 border border-amber-800/40 px-2 py-1 text-xs text-amber-300">{error}</div>)}</div>}
            {llmRunState.error && <div className="text-red-300">{llmRunState.error}</div>}
          </div>
        )}

        {/* D1-D3 — one-click manual maintenance (archive / merge / clean, preview → confirm → execute) */}
        <div className="border-t border-zinc-800 pt-2 mt-2">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className="text-zinc-500 text-sm">{t.dashboard.maintenanceRun}</span>
            {(["archive", "merge", "clean"] as MaintenanceAction[]).map((target) => (
              <button
                key={target}
                type="button"
                onClick={() => onSelectMaintenanceAction(target)}
                disabled={maintenanceBusy}
                className={`rounded px-2 py-1 text-xs transition-colors ${
                  (maintenanceRunState.action ?? "archive") === target
                    ? "bg-zinc-700 text-white"
                    : "bg-transparent text-zinc-500 hover:text-zinc-300"
                }`}
              >
                {target === "archive" ? t.dashboard.maintenanceActionArchive : target === "merge" ? t.dashboard.maintenanceActionMerge : t.dashboard.maintenanceActionClean}
              </button>
            ))}
            <Button onClick={onGenerateMaintenancePlan} disabled={maintenanceBusy} variant="outline" size="sm" className="h-7 text-xs border-zinc-700/50 bg-zinc-800 text-zinc-300 hover:bg-zinc-700 transition-colors">
              <Wrench className="h-3 w-3 mr-1" />{maintenanceRunState.state === "planning" ? t.dashboard.maintenancePlanning : t.dashboard.maintenancePlan}
            </Button>
            <Button onClick={onExecuteMaintenance} disabled={maintenanceBusy || maintenanceRunState.state !== "planReady" || maintenancePlanCount(maintenanceRunState) === 0} variant="outline" size="sm" className="h-7 text-xs border-amber-700/40 bg-amber-900/20 text-amber-300 hover:bg-amber-900/40 transition-colors">
              <Archive className="h-3 w-3 mr-1" />{maintenanceRunState.state === "running" ? t.dashboard.maintenanceExecuting : maintenanceExecuteLabel(t, maintenanceRunState)}
            </Button>
            {maintenanceRunState.state === "running" && <span className="text-xs text-sky-300 animate-pulse">{t.dashboard.maintenanceExecuting}...</span>}
          </div>

          {maintenanceRunState.state === "planReady" && maintenanceRunState.plan && (
            <div className="mt-2 rounded bg-zinc-800/60 px-2 py-1.5 text-xs space-y-1">
              {maintenancePlanPreview(maintenanceRunState).length > 0 ? (
                <div className="space-y-1">
                  <div className="flex items-center gap-2 text-zinc-300">
                    <Badge variant="outline" className="border-sky-700 bg-sky-500/10 text-sky-300 text-xs shrink-0">{t.dashboard.maintenancePreview}</Badge>
                    <span>{maintenancePlanPreview(maintenanceRunState).map((item) => `${item.reason} ${item.count}`).join(" · ")}</span>
                  </div>
                  {maintenancePlanPreview(maintenanceRunState).slice(0, 3).map((item) => (
                    <div key={item.reason} className="text-zinc-400">
                      <span className="text-zinc-300">{item.reason}</span> ({item.count})
                      {item.samples && item.samples.length > 0 && <span className="text-zinc-500"> — {item.samples.join(" / ")}</span>}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-emerald-300">{(maintenanceRunState.action ?? "archive") === "archive" ? t.dashboard.maintenanceNoCandidates : t.dashboard.maintenanceNoCandidatesAny}</div>
              )}
            </div>
          )}

          {maintenanceRunState.state === "succeeded" && maintenanceRunState.result && (
            <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
              <Badge variant="outline" className="border-emerald-700 bg-emerald-500/10 text-emerald-300 text-xs">✓ {t.dashboard.maintenanceRun}</Badge>
              <span className="text-zinc-400">{maintenanceSummaryLabel(t, maintenanceRunState.action ?? "archive")} <span className="text-zinc-200">{maintenanceSummaryCount(maintenanceRunState)}</span></span>
              {maintenanceRunState.elapsedMs !== undefined && <span className="text-zinc-500">{((maintenanceRunState.elapsedMs) / 1000).toFixed(1)}s</span>}
              {maintenanceRunState.result.replayed && <span className="text-zinc-500">{t.dashboard.maintenanceReplayed}</span>}
              {maintenanceRunState.result.backup_path && <div className="min-w-0 flex-1 truncate text-zinc-500">{t.dashboard.maintenanceBackup}: <span className="text-zinc-300 truncate">{maintenanceRunState.result.backup_path}</span></div>}
            </div>
          )}
          {maintenanceRunState.state === "failed" && (
            <div className="mt-2 text-xs text-red-300">{maintenanceRunState.error || t.dashboard.maintenanceStale}</div>
          )}
        </div>
      </div>
    </div>
  );
}

function maintenancePlanCount(state: MaintenanceRunState): number {
  const plan = state.plan;
  if (!plan) return 0;
  const action = state.action ?? "archive";
  if (action === "merge") return plan.merge_count ?? 0;
  if (action === "clean") return plan.clean_count ?? 0;
  return plan.archive_count ?? 0;
}

function maintenancePlanPreview(state: MaintenanceRunState): Array<{ reason: string; count: number; samples?: string[] }> {
  const plan = state.plan;
  if (!plan) return [];
  const action = state.action ?? "archive";
  if (action === "merge") {
    return (plan.merge_groups ?? []).map((group) => ({
      reason: group.key,
      count: group.count,
      samples: (group.loser_titles ?? []).slice(0, 3),
    }));
  }
  if (action === "clean") {
    const count = plan.clean_count ?? 0;
    return count > 0 ? [{ reason: "clean", count }] : [];
  }
  return (plan.groups ?? []).map((group) => ({
    reason: group.reason,
    count: group.count,
    samples: (group.samples ?? []).map((sample) => sample.title ?? "…").slice(0, 3),
  }));
}

function maintenanceExecuteLabel(t: Messages, state: MaintenanceRunState): string {
  const action = state.action ?? "archive";
  const count = maintenancePlanCount(state);
  if (action === "merge") return t.dashboard.maintenanceExecuteMerge(count);
  if (action === "clean") return t.dashboard.maintenanceExecuteClean(count);
  return t.dashboard.maintenanceExecute(count);
}

function maintenanceSummaryLabel(t: Messages, action: MaintenanceAction): string {
  if (action === "merge") return t.dashboard.maintenanceActionMerge;
  if (action === "clean") return t.dashboard.maintenanceActionClean;
  return t.dashboard.maintenanceActionArchive;
}

function maintenanceSummaryCount(state: MaintenanceRunState): number {
  const summary = state.result?.summary ?? {};
  const action = state.action ?? "archive";
  if (action === "merge") return summary.merge ?? 0;
  if (action === "clean") return summary.clean ?? 0;
  return summary.archive ?? 0;
}

function LlmElapsedTimer({ startedAt }: { startedAt: number }) {
  const { messages } = useI18n();
  const [elapsed, setElapsed] = useState(Date.now() - startedAt);
  useEffect(() => {
    const id = setInterval(() => setElapsed(Date.now() - startedAt), 100);
    return () => clearInterval(id);
  }, [startedAt]);
  return <div className="mt-1 text-sky-400 text-xs animate-pulse">{messages.dashboard.llmElapsed((elapsed / 1000).toFixed(1))}</div>;
}
