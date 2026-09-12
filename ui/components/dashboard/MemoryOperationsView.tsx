"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import {
  Activity,
  Archive,
  Bot,
  CheckCircle2,
  Clock,
  Database,
  Play,
  Sparkles,
  Trash2,
  Wrench,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { useI18n } from "@/hooks/useI18n";
import type { Locale, Messages } from "@/lib/i18n/types";
import {
  type CuratorRunState,
  type CuratorStatus,
  type LlmRunState,
  type MaintenanceAction,
  type MaintenanceRunState,
  formatTime,
} from "./memory-operations-types";

// 格式化时间与相对倒计时
function formatScheduleTime(isoString?: string | null): string {
  if (!isoString) return "—";
  try {
    const d = new Date(isoString);
    if (isNaN(d.getTime())) return "—";
    const now = new Date();
    const isToday = d.toDateString() === now.toDateString();
    const timeStr = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    const prefix = isToday ? "今日 " : "次日 ";
    return `${prefix}${timeStr}`;
  } catch {
    return "—";
  }
}

function formatRelativeDiff(targetIso?: string | null): string {
  if (!targetIso) return "";
  try {
    const diffMs = new Date(targetIso).getTime() - Date.now();
    if (diffMs <= 0) return "(即将执行)";
    const mins = Math.floor(diffMs / 60000);
    if (mins < 1) return "(小于1分钟)";
    if (mins < 60) return `(约${mins}分钟后)`;
    const hrs = Math.floor(mins / 60);
    return `(约${hrs}小时后)`;
  } catch {
    return "";
  }
}

function formatDuration(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  if (m > 0) {
    return `${m}m ${s.toString().padStart(2, "0")}s`;
  }
  return `${s}s`;
}

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
  cleanConfirmCount: number | null;
  onConfirmClean: () => void;
  onCancelClean: () => void;
  cleanCandidatesOpen: boolean;
  cleanCandidatesLoading: boolean;
  cleanCandidatesItems: Array<{ id: string; title: string; reason: string }>;
  cleanCandidatesTotal: number;
  cleanCandidatesOffset: number;
  cleanPageSize: number;
  onOpenCleanCandidates: () => void;
  onCloseCleanCandidates: () => void;
  onPrevCleanCandidates: () => void;
  onNextCleanCandidates: () => void;
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
  llmRunState,
  maintenanceRunState,
  maintenanceBusy,
  cleanConfirmCount,
  onConfirmClean,
  onCancelClean,
  cleanCandidatesOpen,
  cleanCandidatesLoading,
  cleanCandidatesItems,
  cleanCandidatesTotal,
  cleanCandidatesOffset,
  cleanPageSize,
  onOpenCleanCandidates,
  onCloseCleanCandidates,
  onPrevCleanCandidates,
  onNextCleanCandidates,
  onApplyCurator,
  onRunLlmCurator,
  onGenerateMaintenancePlan,
  onExecuteMaintenance,
  onSelectMaintenanceAction,
}: MemoryOperationsViewProps) {
  const [liveLlmElapsedMs, setLiveLlmElapsedMs] = useState(0);
  const [decisionFilter, setDecisionFilter] = useState<"all" | "semantic_duplicate" | "contradiction">("all");

  useEffect(() => {
    if (!llmRunning && llmRunState.state !== "running") {
      setLiveLlmElapsedMs(0);
      return;
    }
    const start = llmRunState.startedAt || Date.now();
    const update = () => {
      setLiveLlmElapsedMs(Math.max(0, Date.now() - start));
    };
    update();
    const timer = setInterval(update, 1000);
    return () => clearInterval(timer);
  }, [llmRunning, llmRunState.state, llmRunState.startedAt]);

  const rawDecisions = llmRunState.decisions || [];
  const dupDecisions = rawDecisions.filter((d) => d.decision_type === "semantic_duplicate");
  const contraDecisions = rawDecisions.filter((d) => d.decision_type === "contradiction");
  const filteredDecisions =
    decisionFilter === "semantic_duplicate"
      ? dupDecisions
      : decisionFilter === "contradiction"
      ? contraDecisions
      : rawDecisions;

  const byStatus = status?.stats?.by_status || {};
  const lastRunIso =
    status?.schedules?.rule_curator?.last_run_at ||
    status?.service?.ExecMainExitTimestamp ||
    status?.timer?.LastTriggerUSec;
  const nextRunIso =
    status?.schedules?.rule_curator?.next_run_at ||
    status?.timer?.NextElapseUSecRealtime;

  return (
    <div className="space-y-4">
      {/* 顶部四大核心指标卡 (经典大气舒展) */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <Card className="border-zinc-800 bg-zinc-900/90 backdrop-blur-md">
          <CardHeader className="pb-2">
            <CardTitle className="text-xs font-medium text-zinc-400 flex items-center justify-between">
              <span>{t.dashboard.totalMemories}</span>
              <Database className="h-4 w-4 text-violet-400" />
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold tracking-tight text-white">
              {status?.stats?.total ?? "—"}
            </div>
            <p className="mt-1 text-[11px] text-zinc-500">已沉淀持久事实</p>
          </CardContent>
        </Card>

        <Card className="border-zinc-800 bg-zinc-900/90 backdrop-blur-md">
          <CardHeader className="pb-2">
            <CardTitle className="text-xs font-medium text-zinc-400 flex items-center justify-between">
              <span>{t.dashboard.active}</span>
              <Activity className="h-4 w-4 text-emerald-400" />
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold tracking-tight text-emerald-400">
              {byStatus.active ?? 0}
            </div>
            <p className="mt-1 text-[11px] text-zinc-500">活跃召回池</p>
          </CardContent>
        </Card>

        <Card className="border-zinc-800 bg-zinc-900/90 backdrop-blur-md">
          <CardHeader className="pb-2">
            <CardTitle className="text-xs font-medium text-zinc-400 flex items-center justify-between">
              <span>{t.dashboard.candidates}</span>
              <Sparkles className="h-4 w-4 text-amber-400" />
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold tracking-tight text-amber-400">
              {byStatus.candidate ?? 0}
            </div>
            <p className="mt-1 text-[11px] text-zinc-500">待评估候选</p>
          </CardContent>
        </Card>

        <Card className="border-zinc-800 bg-zinc-900/90 backdrop-blur-md">
          <CardHeader className="pb-2">
            <CardTitle className="text-xs font-medium text-zinc-400 flex items-center justify-between">
              <span>{t.dashboard.archived}</span>
              <Archive className="h-4 w-4 text-zinc-400" />
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold tracking-tight text-zinc-300">
              {byStatus.archived ?? 0}
            </div>
            <p className="mt-1 text-[11px] text-zinc-500">安全冷归档</p>
          </CardContent>
        </Card>
      </div>

      {/* 核心运维与调度指挥中心 (带完整操作、实时回显与准确时间) */}
      <Card className="border-zinc-800 bg-zinc-900/90 backdrop-blur-md">
        <CardHeader className="flex flex-row items-center justify-between border-b border-zinc-800/80 pb-3">
          <div className="flex items-center gap-2">
            <Wrench className="h-4 w-4 text-violet-400" />
            <span className="text-sm font-semibold text-zinc-200">
              运维调度与治理执行中枢 (Memory Operations)
            </span>
          </div>
          <div className="flex items-center gap-2">
            <Badge
              variant="outline"
              className="border-emerald-700/60 bg-emerald-500/10 text-xs font-normal text-emerald-300"
            >
              Systemd Timer Active
            </Badge>
          </div>
        </CardHeader>
        <CardContent className="space-y-4 pt-4">
          {/* 四核心动作大按钮组 */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Button
              variant="outline"
              onClick={onApplyCurator}
              disabled={applying || llmRunning}
              className="flex h-16 flex-col items-center justify-center gap-1 border-zinc-800 bg-zinc-950/60 text-xs hover:bg-zinc-800 hover:text-white"
            >
              <div className="flex items-center gap-1.5 font-medium text-zinc-200">
                <Play className={`h-4 w-4 text-emerald-400 ${applying ? "animate-spin" : ""}`} />
                <span>{applying ? "正在扫描..." : "运行规则扫描"}</span>
              </div>
              <span className="text-[11px] text-zinc-500">清理冷数据与格式</span>
            </Button>

            <Button
              variant="outline"
              onClick={onRunLlmCurator}
              disabled={applying || llmRunning}
              className="flex h-16 flex-col items-center justify-center gap-1 border-zinc-800 bg-zinc-950/60 text-xs hover:bg-zinc-800 hover:text-white"
            >
              <div className="flex items-center gap-1.5 font-medium text-zinc-200">
                <Bot className={`h-4 w-4 text-sky-400 ${llmRunning ? "animate-pulse" : ""}`} />
                <span>{llmRunning ? `语义分析中 (${formatDuration(liveLlmElapsedMs)})...` : "唤醒 LLM 治理"}</span>
              </div>
              <span className="text-[11px] text-zinc-500">
                {llmRunning ? `已运行 ${formatDuration(liveLlmElapsedMs)}` : "语义深度合并决策"}
              </span>
            </Button>

            <Button
              variant="outline"
              onClick={() => {
                onSelectMaintenanceAction("clean");
                onGenerateMaintenancePlan();
              }}
              disabled={maintenanceBusy}
              className="flex h-16 flex-col items-center justify-center gap-1 border-zinc-800 bg-zinc-950/60 text-xs hover:bg-zinc-800 hover:text-white"
            >
              <div className="flex items-center gap-1.5 font-medium text-zinc-200">
                <Trash2 className="h-4 w-4 text-rose-400" />
                <span>清理过期候选</span>
              </div>
              <span className="text-[11px] text-zinc-500">释放过期 candidate</span>
            </Button>

            <Button
              variant="outline"
              onClick={() => {
                onSelectMaintenanceAction("archive");
                onGenerateMaintenancePlan();
              }}
              disabled={maintenanceBusy}
              className="flex h-16 flex-col items-center justify-center gap-1 border-zinc-800 bg-zinc-950/60 text-xs hover:bg-zinc-800 hover:text-white"
            >
              <div className="flex items-center gap-1.5 font-medium text-zinc-200">
                <Archive className="h-4 w-4 text-indigo-400" />
                <span>一键安全归档</span>
              </div>
              <span className="text-[11px] text-zinc-500">沉淀冷记忆与冲突项</span>
            </Button>
          </div>

          {/* 实时运行结果反馈卡片（执行后就地回显） */}
          {runState.state !== "idle" && (
            <div className="rounded-lg border border-zinc-800 bg-zinc-950/80 p-3 text-xs space-y-2 animate-fade-slide-down">
              <div className="flex items-center justify-between border-b border-zinc-800 pb-2">
                <span className="flex items-center gap-1.5 font-medium text-zinc-200">
                  {runState.state === "succeeded" ? (
                    <CheckCircle2 className="h-4 w-4 text-emerald-400" />
                  ) : runState.state === "failed" ? (
                    <XCircle className="h-4 w-4 text-rose-400" />
                  ) : (
                    <Play className="h-4 w-4 animate-spin text-sky-400" />
                  )}
                  规则扫描器执行报告
                </span>
                <span className="font-mono text-xs text-zinc-400">
                  {runState.elapsedMs !== undefined ? `耗时 ${(runState.elapsedMs / 1000).toFixed(1)}s` : "执行中..."}
                </span>
              </div>
              <div className="grid grid-cols-3 gap-2 text-zinc-400">
                <div>生成动作：<b className="text-zinc-200">{runState.summary?.actions ?? 0}</b></div>
                <div>归档沉淀：<b className="text-zinc-200">{runState.summary?.archive ?? 0}</b></div>
                <div>技能晋升：<b className="text-zinc-200">{runState.summary?.skill_promotions ?? 0}</b></div>
              </div>
              {runState.error && <p className="text-rose-400 font-mono text-[11px]">{runState.error}</p>}
            </div>
          )}

          {llmRunState.state !== "idle" && (
            <div className="rounded-lg border border-zinc-800 bg-zinc-950/80 p-3 text-xs space-y-2 animate-fade-slide-down">
              <div className="flex items-center justify-between border-b border-zinc-800 pb-2">
                <span className="flex items-center gap-1.5 font-medium text-zinc-200">
                  {llmRunState.state === "succeeded" ? (
                    <CheckCircle2 className="h-4 w-4 text-purple-400" />
                  ) : llmRunState.state === "failed" ? (
                    <XCircle className="h-4 w-4 text-rose-400" />
                  ) : (
                    <Bot className="h-4 w-4 animate-pulse text-sky-400" />
                  )}
                  LLM 语义大模型治理报告
                </span>
                <span className="font-mono text-xs text-zinc-400">
                  {llmRunState.state === "running"
                    ? `后台深度分析中 · 已运行 ${formatDuration(liveLlmElapsedMs)}`
                    : `耗时 ${((llmRunState.elapsedMs || 0) / 1000).toFixed(1)}s`}
                </span>
              </div>
              <div className="grid grid-cols-2 gap-2 text-zinc-400 sm:grid-cols-4">
                <div>重复合并：<b className="text-zinc-200">{llmRunState.summary?.semantic_duplicates ?? 0}</b></div>
                <div>矛盾覆盖：<b className="text-zinc-200">{llmRunState.summary?.contradictions ?? 0}</b></div>
                <div>重要度重估：<b className="text-zinc-200">{llmRunState.summary?.importance_reassessments ?? 0}</b></div>
                <div>拆分建议：<b className="text-zinc-200">{llmRunState.summary?.split_candidates ?? 0}</b></div>
              </div>

              {/* 实时增长的详细决策列表 */}
              <div className="space-y-2 border-t border-zinc-800/80 pt-2.5">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-zinc-200 flex items-center gap-1.5">
                      <Bot className="h-3.5 w-3.5 text-sky-400" />
                      治理决策与发现明细
                    </span>
                    <Badge variant="outline" className="border-zinc-700 bg-zinc-900 text-[10px] text-zinc-300">
                      已捕获 {rawDecisions.length} 条
                    </Badge>
                  </div>

                  <div className="flex items-center gap-1.5 text-[11px]">
                    {rawDecisions.length > 0 && (
                      <div className="flex items-center gap-1 bg-zinc-950/80 rounded border border-zinc-800 p-0.5 mr-2">
                        <button
                          type="button"
                          onClick={() => setDecisionFilter("all")}
                          className={`px-2 py-0.5 rounded transition-colors ${
                            decisionFilter === "all"
                              ? "bg-zinc-800 text-zinc-100 font-medium"
                              : "text-zinc-400 hover:text-zinc-200"
                          }`}
                        >
                          全部 ({rawDecisions.length})
                        </button>
                        {dupDecisions.length > 0 && (
                          <button
                            type="button"
                            onClick={() => setDecisionFilter("semantic_duplicate")}
                            className={`px-2 py-0.5 rounded transition-colors ${
                              decisionFilter === "semantic_duplicate"
                                ? "bg-purple-900/60 text-purple-200 font-medium"
                                : "text-zinc-400 hover:text-purple-300"
                            }`}
                          >
                            去重 ({dupDecisions.length})
                          </button>
                        )}
                        {contraDecisions.length > 0 && (
                          <button
                            type="button"
                            onClick={() => setDecisionFilter("contradiction")}
                            className={`px-2 py-0.5 rounded transition-colors ${
                              decisionFilter === "contradiction"
                                ? "bg-rose-900/60 text-rose-200 font-medium"
                                : "text-zinc-400 hover:text-rose-300"
                            }`}
                          >
                            冲突 ({contraDecisions.length})
                          </button>
                        )}
                      </div>
                    )}
                    {llmRunState.state === "running" && (
                      <span className="text-[11px] text-sky-400 flex items-center gap-1.5">
                        <span className="h-1.5 w-1.5 rounded-full bg-sky-400 animate-pulse" />
                        批次计算中 · 实时推入
                      </span>
                    )}
                  </div>
                </div>

                {filteredDecisions.length > 0 ? (
                  <div className="max-h-72 overflow-y-auto space-y-2 pr-1">
                    {filteredDecisions.map((dec, idx) => {
                      const isDup = dec.decision_type === "semantic_duplicate";
                      const isContra = dec.decision_type === "contradiction";
                      const finding = dec.finding || {};
                      const keepTitle =
                        finding.keep_title || dec.before_state?.[0]?.title || "基准记忆";
                      const dropTitle =
                        finding.drop_title || dec.before_state?.[1]?.title || "";
                      const reason = finding.reason || dec.policy_reason || "";
                      const scoreVal = finding.score ?? dec.llm_confidence;
                      const scoreStr =
                        scoreVal !== undefined && scoreVal !== null
                          ? `${Math.round(Number(scoreVal) * 100)}%`
                          : null;
                      const actionLabel =
                        dec.recommended_action === "archive_duplicate"
                          ? "归档副本"
                          : dec.recommended_action === "archive_and_merge_duplicate"
                          ? "归档并合并"
                          : dec.recommended_action === "mark_contradicted"
                          ? "标记冲突"
                          : dec.recommended_action;

                      return (
                        <div
                          key={dec.id || idx}
                          className="rounded-md border border-zinc-800/90 bg-zinc-950/70 p-2.5 transition-all hover:border-zinc-700/80 space-y-1.5 text-xs shadow-sm"
                        >
                          <div className="flex flex-wrap items-center justify-between gap-1.5">
                            <div className="flex items-center gap-1.5 min-w-0 flex-1">
                              <Badge
                                variant="outline"
                                className={
                                  isDup
                                    ? "border-purple-800/60 bg-purple-500/10 text-purple-300 text-[10px] px-1.5 py-0"
                                    : isContra
                                    ? "border-rose-800/60 bg-rose-500/10 text-rose-300 text-[10px] px-1.5 py-0"
                                    : "border-sky-800/60 bg-sky-500/10 text-sky-300 text-[10px] px-1.5 py-0"
                                }
                              >
                                {isDup ? "语义去重" : isContra ? "事实冲突" : dec.decision_type}
                              </Badge>

                              <div className="font-medium text-zinc-200 truncate flex-1 text-[12px]">
                                {isDup ? (
                                  <span>
                                    <span className="text-emerald-400 font-semibold">[保留]</span> {keepTitle}
                                    {dropTitle && (
                                      <>
                                        <span className="text-zinc-500 mx-1.5">⟵</span>
                                        <span className="text-rose-400/90">[合并归档]</span> {dropTitle}
                                      </>
                                    )}
                                  </span>
                                ) : isContra ? (
                                  <span>
                                    <span className="text-rose-400 font-semibold">[冲突项]</span> {keepTitle}
                                    {dropTitle && (
                                      <>
                                        <span className="text-zinc-500 mx-1.5">⚡</span>
                                        <span className="text-amber-400">{dropTitle}</span>
                                      </>
                                    )}
                                  </span>
                                ) : (
                                  keepTitle
                                )}
                              </div>
                            </div>

                            <div className="flex items-center gap-1.5 shrink-0 text-[10px] text-zinc-400">
                              {scoreStr && (
                                <span className="font-mono text-zinc-300 bg-zinc-900 border border-zinc-800 px-1.5 py-0.5 rounded">
                                  相似度 {scoreStr}
                                </span>
                              )}
                              <Badge variant="outline" className="border-zinc-800 bg-zinc-900 text-zinc-400 text-[10px] px-1.5 py-0">
                                {actionLabel}
                              </Badge>
                              <span className="text-zinc-500 font-mono text-[10px]">
                                {dec.created_at ? formatTime(dec.created_at, locale) : ""}
                              </span>
                            </div>
                          </div>

                          {reason && (
                            <p className="text-[11px] text-zinc-400 pl-2 border-l-2 border-zinc-800 leading-relaxed font-sans">
                              {reason}
                            </p>
                          )}
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <div className="py-5 text-center text-zinc-500 text-xs flex flex-col items-center justify-center gap-1.5 border border-dashed border-zinc-800/80 rounded-md bg-zinc-950/40">
                    {llmRunState.state === "running" ? (
                      <>
                        <Bot className="h-4 w-4 text-sky-400 animate-pulse" />
                        <span>大模型正逐批分析记忆候选对，发现重复或冲突将实时在此展示...</span>
                      </>
                    ) : (
                      <span>当前治理分析未发现重复或冲突项。</span>
                    )}
                  </div>
                )}
              </div>

              {llmRunState.error && <p className="text-rose-400 font-mono text-[11px]">{llmRunState.error}</p>}
            </div>
          )}

          {maintenanceRunState.state === "planReady" && maintenanceRunState.plan && (() => {
            const plan = maintenanceRunState.plan;
            const count =
              (maintenanceRunState.action === "clean" ? plan.clean_count : plan.archive_count) ??
              plan.clean_count ??
              plan.archive_count ??
              0;

            if (count === 0) {
              return (
                <div className="rounded-lg border border-emerald-800/40 bg-emerald-950/20 p-3 text-xs text-emerald-300 flex items-center justify-between animate-fade-slide-down">
                  <div className="flex items-center gap-2">
                    <CheckCircle2 className="h-4 w-4 text-emerald-400" />
                    <span>
                      {maintenanceRunState.action === "clean"
                        ? "记忆池当前全量清洁，无过期候选需要清理"
                        : "记忆池状态优良，当前无需归档的冷记忆"}
                    </span>
                  </div>
                  <span className="text-[11px] text-zinc-500">检测完成 · 0 条待处理</span>
                </div>
              );
            }

            return (
              <div className="rounded-lg border border-zinc-800 border-l-4 border-l-violet-500 bg-zinc-950/90 p-3.5 text-xs space-y-3 shadow-md animate-fade-slide-down">
                <div className="flex flex-wrap items-center justify-between gap-2 border-b border-zinc-800/80 pb-2.5">
                  <div className="flex items-center gap-2">
                    <Wrench className="h-4 w-4 text-violet-400" />
                    <span className="font-semibold text-zinc-100">
                      数据维护计划已就绪 ({maintenanceRunState.action === "clean" ? "深度清理" : "安全归档"})
                    </span>
                  </div>
                  <Badge
                    variant="outline"
                    className="border-violet-500/30 bg-violet-500/10 text-violet-300 font-mono text-[11px]"
                  >
                    待处理 {count} 条候选
                  </Badge>
                </div>

                <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 pt-0.5">
                  <div className="text-zinc-400 text-xs space-y-1">
                    <p className="flex items-center gap-1.5 text-zinc-300">
                      <span>可沉淀优化：</span>
                      <b className="text-violet-300 font-semibold">{count}</b>
                      <span>条无访问或冲突事实</span>
                    </p>
                    <p className="text-[11px] text-zinc-500">
                      🛡️ 自动安全保障：系统执行前将创建完整 SQLite 镜像备份与审计血缘
                    </p>
                  </div>

                  <div className="flex items-center gap-2 shrink-0">
                    {maintenanceRunState.action === "clean" && (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={onOpenCleanCandidates}
                        className="h-8 border-zinc-800 bg-zinc-900 px-3 text-xs text-zinc-300 hover:bg-zinc-800 hover:text-white"
                      >
                        查看候选清单
                      </Button>
                    )}
                    <Button
                      size="sm"
                      onClick={onExecuteMaintenance}
                      className="h-8 bg-violet-600 hover:bg-violet-500 text-white text-xs px-3.5 font-medium shadow-sm transition-colors"
                    >
                      <Play className="mr-1.5 h-3 w-3 fill-current" />
                      确认立即执行
                    </Button>
                  </div>
                </div>
              </div>
            );
          })()}

          {maintenanceRunState.state === "succeeded" && (
            <div className="rounded-lg border border-zinc-800 border-l-4 border-l-emerald-500 bg-zinc-950/90 p-3 text-xs text-zinc-300 flex items-center justify-between shadow-sm animate-fade-slide-down">
              <div className="flex items-center gap-2">
                <CheckCircle2 className="h-4 w-4 text-emerald-400" />
                <span className="font-medium text-zinc-200">
                  维护任务执行成功：记忆池已规整沉淀完毕
                </span>
              </div>
              <span className="text-[11px] text-zinc-500 font-mono">
                {maintenanceRunState.elapsedMs !== undefined
                  ? `耗时 ${(maintenanceRunState.elapsedMs / 1000).toFixed(1)}s`
                  : "执行完毕"}
              </span>
            </div>
          )}

          {/* 底部准确时间与排程信息栏 */}
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-zinc-800/80 bg-zinc-950/60 px-4 py-2.5 text-xs text-zinc-400">
            <div className="flex items-center gap-2">
              <Clock className="h-3.5 w-3.5 text-zinc-500" />
              <span>上次运行：</span>
              <span className="text-zinc-200 font-medium">
                {formatScheduleTime(lastRunIso)}
              </span>
              <span className="text-emerald-400 text-[11px]">(执行成功)</span>
            </div>

            <div className="flex items-center gap-2">
              <Clock className="h-3.5 w-3.5 text-zinc-500" />
              <span>下次排程：</span>
              <span className="font-mono text-zinc-200">
                {formatScheduleTime(nextRunIso)}
              </span>
              <span className="text-sky-400 text-[11px]">
                {formatRelativeDiff(nextRunIso)}
              </span>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* 清理确认对话框 */}
      <AlertDialog open={cleanConfirmCount !== null} onOpenChange={(open) => !open && onCancelClean()}>
        <AlertDialogContent className="border-zinc-800 bg-zinc-900 text-zinc-100">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-base font-semibold">确认硬删除归档候选？</AlertDialogTitle>
            <AlertDialogDescription className="text-xs text-zinc-400">
              本次将永久删除 {cleanConfirmCount} 条已过期的无用候选记忆。系统将在执行前自动创建安全备份。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={onCancelClean} className="border-zinc-800 bg-zinc-900 text-zinc-300 hover:bg-zinc-800">取消</AlertDialogCancel>
            <AlertDialogAction onClick={onConfirmClean} className="bg-rose-600 text-white hover:bg-rose-500">确认删除</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
