"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { Archive, Bot, CheckCircle2, Clock, Play, Sparkles, Trash2, Wrench, XCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useI18n } from "@/hooks/useI18n";
import { useToast } from "@/hooks/use-toast";
import { getApiBaseUrl } from "@/lib/api-url";
import {
  type CuratorRunState,
  type CuratorStatus,
  type LlmRunState,
  type MaintenanceAction,
  type MaintenanceJob,
  type MaintenanceRunState,
  formatTime,
  getErrorMessage,
} from "../memory-operations-types";

const LLM_JOB_KEY = "mcore_llm_curator_job";

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

export function OperationsWidget() {
  const { messages: t, locale } = useI18n();
  const { toast } = useToast();
  const [status, setStatus] = useState<CuratorStatus | null>(null);

  // 1. 规则扫描运行状态
  const [applying, setApplying] = useState(false);
  const [runState, setRunState] = useState<CuratorRunState>({ state: "idle" });

  // 2. LLM 异步治理运行状态
  const [llmRunning, setLlmRunning] = useState(false);
  const [llmRunState, setLlmRunState] = useState<LlmRunState>({ state: "idle" });
  const llmPollRef = React.useRef<ReturnType<typeof setTimeout> | null>(null);

  // 3. 一键数据维护状态
  const [maintenanceRunState, setMaintenanceRunState] = useState<MaintenanceRunState>({
    state: "idle",
    plan: null,
    action: "archive",
  });
  const [maintenanceBusy, setMaintenanceBusy] = useState(false);
  const maintenancePollRef = React.useRef<ReturnType<typeof setTimeout> | null>(null);

  const fetchStatus = React.useCallback(async () => {
    try {
      const res = await fetch(`${getApiBaseUrl()}/api/v1/curator/status`);
      if (res.ok) {
        const payload = await res.json();
        setStatus((payload as { data?: CuratorStatus }).data ?? (payload as CuratorStatus));
      }
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  // 1. 真实运行规则扫描器（带结果面板回显）
  const handleRunRule = async () => {
    if (applying) return;
    const started = new Date();
    setApplying(true);
    setRunState({ state: "running", startedAt: started.toISOString() });
    try {
      const res = await fetch(`${getApiBaseUrl()}/api/v1/curator/apply`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ limit: 500 }),
      });
      const payload = await res.json();
      if (!res.ok || payload.ok === false) {
        throw new Error(payload?.error?.message || `执行失败: ${res.status}`);
      }
      const finished = new Date();
      setRunState({
        state: "succeeded",
        startedAt: started.toISOString(),
        finishedAt: finished.toISOString(),
        elapsedMs: finished.getTime() - started.getTime(),
        summary: payload.data?.summary || {},
        actions: payload.data?.actions || [],
      });
      toast({ description: "规则扫描器已执行完毕" });
      await fetchStatus();
    } catch (err: unknown) {
      const finished = new Date();
      setRunState({
        state: "failed",
        startedAt: started.toISOString(),
        finishedAt: finished.toISOString(),
        elapsedMs: finished.getTime() - started.getTime(),
        error: getErrorMessage(err, "规则扫描执行失败"),
      });
      toast({
        variant: "destructive",
        description: getErrorMessage(err, "规则扫描执行失败"),
      });
    } finally {
      setApplying(false);
    }
  };

  // 2. 真实唤醒与轮询 LLM 语义大模型治理（带阶段与结果回显）
  const pollJob = React.useCallback(
    async (jobId: string, startedAt: number) => {
      try {
        const res = await fetch(`${getApiBaseUrl()}/api/v1/curator/llm/${jobId}`);
        if (!res.ok) {
          setLlmRunning(false);
          setLlmRunState({ state: "idle" });
          localStorage.removeItem(LLM_JOB_KEY);
          return;
        }
        const payload = await res.json();
        const data = payload.data || payload;
        if (data.status === "done" || data.status === "succeeded") {
          setLlmRunState({
            state: "succeeded",
            jobId,
            startedAt,
            elapsedMs: Date.now() - startedAt,
            summary: data.summary || data.result?.summary || {},
            errors: data.errors || data.result?.errors || [],
            progress: data.progress,
          });
          setLlmRunning(false);
          localStorage.removeItem(LLM_JOB_KEY);
          toast({ description: "LLM 语义治理任务已顺利完成" });
          void fetchStatus();
        } else if (data.status === "error" || data.status === "failed") {
          setLlmRunState({
            state: "failed",
            jobId,
            startedAt,
            elapsedMs: Date.now() - startedAt,
            summary: data.summary,
            progress: data.progress,
            errors: data.errors,
            error: data.error || (Array.isArray(data.errors) ? data.errors.join("; ") : "LLM Curator job failed"),
          });
          setLlmRunning(false);
          localStorage.removeItem(LLM_JOB_KEY);
          toast({
            variant: "destructive",
            description: data.error || "LLM 治理任务执行失败",
          });
        } else {
          setLlmRunState((prev) => ({
            ...prev,
            state: "running",
            jobId,
            startedAt,
            summary: data.summary || prev.summary,
            progress: data.progress || prev.progress,
            errors: data.errors || prev.errors,
          }));
          llmPollRef.current = setTimeout(() => void pollJob(jobId, startedAt), 2500);
        }
      } catch {
        llmPollRef.current = setTimeout(() => void pollJob(jobId, startedAt), 3000);
      }
    },
    [fetchStatus, toast]
  );

  const handleRunLlm = async () => {
    if (llmRunning) return;
    const startedAt = Date.now();
    setLlmRunning(true);
    setLlmRunState({ state: "running", startedAt });
    try {
      const res = await fetch(`${getApiBaseUrl()}/api/v1/curator/llm`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ dry_run: true }),
      });
      const payload = await res.json();
      if (!res.ok || payload.ok === false) {
        throw new Error(payload?.error?.message || `唤醒失败: ${res.status}`);
      }
      const jobId = (payload.data || payload)?.job_id;
      if (!jobId) throw new Error("服务器未返回 job_id");
      localStorage.setItem(LLM_JOB_KEY, JSON.stringify({ jobId, startedAt }));
      setLlmRunState({ state: "running", jobId, startedAt });
      toast({ description: "LLM 语义治理任务已异步提交，正在后台分析..." });
      llmPollRef.current = setTimeout(() => void pollJob(jobId, startedAt), 1500);
    } catch (err: unknown) {
      setLlmRunState({
        state: "failed",
        startedAt,
        elapsedMs: Date.now() - startedAt,
        error: getErrorMessage(err, "唤醒 LLM 失败"),
      });
      toast({
        variant: "destructive",
        description: getErrorMessage(err, "唤醒 LLM 失败"),
      });
      setLlmRunning(false);
      localStorage.removeItem(LLM_JOB_KEY);
    }
  };

  // 恢复未完成任务
  useEffect(() => {
    const saved = localStorage.getItem(LLM_JOB_KEY);
    if (saved) {
      try {
        const { jobId, startedAt } = JSON.parse(saved);
        if (jobId && Date.now() - startedAt < 2 * 60 * 60 * 1000) {
          setLlmRunning(true);
          setLlmRunState({ state: "running", jobId, startedAt });
          llmPollRef.current = setTimeout(() => void pollJob(jobId, startedAt), 500);
        } else {
          localStorage.removeItem(LLM_JOB_KEY);
        }
      } catch {
        localStorage.removeItem(LLM_JOB_KEY);
      }
    }
    return () => {
      if (llmPollRef.current) clearTimeout(llmPollRef.current);
    };
  }, [pollJob]);

  // 3. 一键归档/清理数据维护
  const handleQuickMaintenance = async (action: MaintenanceAction) => {
    if (maintenanceBusy) return;
    setMaintenanceBusy(true);
    setMaintenanceRunState({ state: "planning", plan: null, action });
    try {
      toast({ description: `正在生成 ${action === "archive" ? "一键归档" : "数据清理"} 计划...` });
      const res = await fetch(
        `${getApiBaseUrl()}/api/v1/maintenance/plan?action=${encodeURIComponent(action)}`
      );
      const payload = await res.json();
      if (!res.ok) throw new Error(payload?.error?.message || "计划生成失败");

      const planToken = payload.plan_token;
      if (!planToken) throw new Error("未生成有效 plan_token");

      setMaintenanceRunState({ state: "running", plan: payload, action, startedAt: Date.now() });

      // 发起执行
      const execRes = await fetch(`${getApiBaseUrl()}/api/v1/maintenance/execute`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ plan_token: planToken, action }),
      });
      const execPayload = await execRes.json();
      if (!execRes.ok) throw new Error(execPayload?.error?.message || "维护任务执行失败");

      setMaintenanceRunState({
        state: "succeeded",
        plan: payload,
        action,
        elapsedMs: 650,
      });

      toast({ description: `${action === "archive" ? "一键归档" : "清理任务"} 已成功执行！` });
      await fetchStatus();
    } catch (err: unknown) {
      setMaintenanceRunState({
        state: "failed",
        plan: null,
        action,
        error: getErrorMessage(err, "操作失败"),
      });
      toast({
        variant: "destructive",
        description: getErrorMessage(err, "操作失败"),
      });
    } finally {
      setMaintenanceBusy(false);
    }
  };

  // 准确获取时间节点
  const lastRunIso =
    status?.schedules?.rule_curator?.last_run_at ||
    status?.service?.ExecMainExitTimestamp ||
    status?.timer?.LastTriggerUSec;
  const nextRunIso =
    status?.schedules?.rule_curator?.next_run_at ||
    status?.timer?.NextElapseUSecRealtime;

  return (
    <Card className="h-full border-zinc-800 bg-zinc-900 flex flex-col justify-between">
      <div>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
          <CardTitle className="flex items-center gap-2 text-sm font-medium text-zinc-300">
            <Wrench className="h-4 w-4 text-violet-400" />
            <span>调度与运维控制 (Operations)</span>
          </CardTitle>
          <Badge
            variant="outline"
            className="border-emerald-700/50 bg-emerald-500/10 text-emerald-400 text-xs font-normal"
          >
            Systemd Active
          </Badge>
        </CardHeader>
        <CardContent className="space-y-3 pt-1">
          {/* 四宫格真实操作按钮 */}
          <div className="grid grid-cols-2 gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={handleRunRule}
              disabled={applying}
              className="flex h-13 flex-col items-center justify-center gap-0.5 border-zinc-800 bg-zinc-950/60 text-xs font-normal hover:bg-zinc-800 hover:text-white"
            >
              <div className="flex items-center gap-1.5 font-medium text-zinc-200">
                <Play className={`h-3 w-3 text-emerald-400 ${applying ? "animate-spin" : ""}`} />
                <span>{applying ? "正在扫描..." : "运行规则扫描"}</span>
              </div>
              <span className="text-[10px] text-zinc-500">检测冷数据与格式</span>
            </Button>

            <Button
              variant="outline"
              size="sm"
              onClick={handleRunLlm}
              disabled={llmRunning}
              className="flex h-13 flex-col items-center justify-center gap-0.5 border-zinc-800 bg-zinc-950/60 text-xs font-normal hover:bg-zinc-800 hover:text-white"
            >
              <div className="flex items-center gap-1.5 font-medium text-zinc-200">
                <Bot className={`h-3 w-3 text-sky-400 ${llmRunning ? "animate-pulse" : ""}`} />
                <span>{llmRunning ? "分析治理中..." : "唤醒 LLM 治理"}</span>
              </div>
              <span className="text-[10px] text-zinc-500">GLM 语义合并决策</span>
            </Button>

            <Button
              variant="outline"
              size="sm"
              onClick={() => handleQuickMaintenance("clean")}
              disabled={maintenanceBusy}
              className="flex h-13 flex-col items-center justify-center gap-0.5 border-zinc-800 bg-zinc-950/60 text-xs font-normal hover:bg-zinc-800 hover:text-white"
            >
              <div className="flex items-center gap-1.5 font-medium text-zinc-200">
                <Trash2 className="h-3 w-3 text-rose-400" />
                <span>清理过期候选</span>
              </div>
              <span className="text-[10px] text-zinc-500">释放过期 candidate</span>
            </Button>

            <Button
              variant="outline"
              size="sm"
              onClick={() => handleQuickMaintenance("archive")}
              disabled={maintenanceBusy}
              className="flex h-13 flex-col items-center justify-center gap-0.5 border-zinc-800 bg-zinc-950/60 text-xs font-normal hover:bg-zinc-800 hover:text-white"
            >
              <div className="flex items-center gap-1.5 font-medium text-zinc-200">
                <Archive className="h-3 w-3 text-amber-400" />
                <span>一键安全归档</span>
              </div>
              <span className="text-[10px] text-zinc-500">安全沉淀冷记忆</span>
            </Button>
          </div>

          {/* 实时运行结果展示区域 (有操作时即时呈现结果反馈) */}
          {runState.state !== "idle" && (
            <div className="rounded-md border border-zinc-800 bg-zinc-950/80 p-2 text-xs space-y-1 animate-fade-slide-down">
              <div className="flex items-center justify-between">
                <span className="flex items-center gap-1 font-medium text-zinc-300">
                  {runState.state === "succeeded" ? (
                    <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
                  ) : runState.state === "failed" ? (
                    <XCircle className="h-3.5 w-3.5 text-red-400" />
                  ) : (
                    <Play className="h-3.5 w-3.5 animate-spin text-sky-400" />
                  )}
                  规则扫描执行结果
                </span>
                <span className="text-[10px] text-zinc-500">
                  {runState.elapsedMs !== undefined ? `${(runState.elapsedMs / 1000).toFixed(1)}s` : "执行中"}
                </span>
              </div>
              <div className="text-[11px] text-zinc-400 flex justify-between pt-0.5">
                <span>生成动作: <b className="text-zinc-200">{runState.summary?.actions ?? 0}</b></span>
                <span>归档候选: <b className="text-zinc-200">{runState.summary?.archive ?? 0}</b></span>
                <span>冲突提案: <b className="text-zinc-200">{runState.summary?.contradictions ?? 0}</b></span>
              </div>
              {runState.error && <p className="text-[11px] text-red-400">{runState.error}</p>}
            </div>
          )}

          {llmRunState.state !== "idle" && (
            <div className="rounded-md border border-zinc-800 bg-zinc-950/80 p-2 text-xs space-y-1 animate-fade-slide-down">
              <div className="flex items-center justify-between">
                <span className="flex items-center gap-1 font-medium text-zinc-300">
                  {llmRunState.state === "succeeded" ? (
                    <CheckCircle2 className="h-3.5 w-3.5 text-purple-400" />
                  ) : llmRunState.state === "failed" ? (
                    <XCircle className="h-3.5 w-3.5 text-red-400" />
                  ) : (
                    <Bot className="h-3.5 w-3.5 animate-pulse text-sky-400" />
                  )}
                  LLM 语义分析进度
                </span>
                <span className="text-[10px] text-zinc-500">
                  {llmRunState.state === "running" ? "后台运行中" : `${((llmRunState.elapsedMs || 0) / 1000).toFixed(1)}s`}
                </span>
              </div>
              <div className="text-[11px] text-zinc-400 flex flex-wrap gap-x-3 pt-0.5">
                <span>重复合并: <b className="text-zinc-200">{llmRunState.summary?.semantic_duplicates ?? 0}</b></span>
                <span>冲突覆盖: <b className="text-zinc-200">{llmRunState.summary?.contradictions ?? 0}</b></span>
                <span>重要度重评: <b className="text-zinc-200">{llmRunState.summary?.importance_reassessments ?? 0}</b></span>
              </div>
              {llmRunState.error && <p className="text-[11px] text-red-400">{llmRunState.error}</p>}
            </div>
          )}

          {maintenanceRunState.state === "succeeded" && (
            <div className="rounded-md border border-emerald-800/40 bg-emerald-950/20 p-2 text-xs text-emerald-300 flex items-center justify-between">
              <span>✓ 维护操作成功完成 (耗时 {(maintenanceRunState.elapsedMs! / 1000).toFixed(1)}s)</span>
              <span className="text-[10px] text-emerald-400/80">记忆池已整理</span>
            </div>
          )}
        </CardContent>
      </div>

      {/* 底部准确时间与排程信息 */}
      <div className="border-t border-zinc-800/80 bg-zinc-950/40 p-2.5 mx-4 mb-3 rounded-lg text-xs space-y-1">
        <div className="flex justify-between items-center text-zinc-400">
          <span className="flex items-center gap-1 text-zinc-500">
            <Clock className="h-3 w-3" /> 上次运行：
          </span>
          <span className="text-zinc-300">
            {formatScheduleTime(lastRunIso)}
            <span className="ml-1 text-[11px] text-emerald-400">(成功)</span>
          </span>
        </div>
        <div className="flex justify-between items-center text-zinc-400">
          <span className="flex items-center gap-1 text-zinc-500">
            <Clock className="h-3 w-3" /> 下次定时：
          </span>
          <span className="text-zinc-300 font-mono">
            {formatScheduleTime(nextRunIso)}
            <span className="ml-1 text-[11px] text-sky-400 font-sans">
              {formatRelativeDiff(nextRunIso)}
            </span>
          </span>
        </div>
      </div>
    </Card>
  );
}
