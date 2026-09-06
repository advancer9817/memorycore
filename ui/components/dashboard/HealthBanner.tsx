"use client";

import { useEffect, useState } from "react";
import { Activity, HeartPulse, Link2, Recycle, ShieldCheck, Sparkles } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { useI18n } from "@/hooks/useI18n";
import { getApiBaseUrl } from "@/lib/api-url";

type HealthScore = {
  quality: number;
  risk: number;
  llmGovernance: number;
  llmStatus: string;
  llmStartedAt?: string;
  metrics: {
    active: number;
    active_reuse_coverage: number;
    linked_coverage: number;
    pending_cleanup_share: number;
    pending_cleanup: number;
    usable_pool: number;
    stale: number;
    superseded: number;
    contradicted: number;
    active_never_accessed: number;
  };
  signals: {
    high_risk_count: number;
    contradiction_actionable: number;
    duplicate_actionable: number;
  };
};

function scoreColor(score: number): { text: string; bg: string; border: string; label: string } {
  if (score >= 80) {
    return {
      text: "text-emerald-400",
      bg: "bg-emerald-500/10",
      border: "border-emerald-500/30",
      label: "状态卓越",
    };
  }
  if (score >= 60) {
    return {
      text: "text-amber-400",
      bg: "bg-amber-500/10",
      border: "border-amber-500/30",
      label: "状态良好",
    };
  }
  return {
    text: "text-rose-400",
    bg: "bg-rose-500/10",
    border: "border-rose-500/30",
    label: "需要关注",
  };
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

export function HealthBanner() {
  const { messages: t } = useI18n();
  const [health, setHealth] = useState<HealthScore | null>(null);
  const [llmElapsedMs, setLlmElapsedMs] = useState(0);

  useEffect(() => {
    let active = true;
    const fetchHealth = () => {
      fetch(`${getApiBaseUrl()}/api/v1/health-score`)
        .then((res) => res.json() as Promise<HealthScore>)
        .then((payload) => {
          if (active) setHealth(payload);
        })
        .catch(() => {
          if (active) setHealth(null);
        });
    };

    fetchHealth();
    const timer = setInterval(fetchHealth, 5000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    if (health?.llmStatus !== "running" || !health?.llmStartedAt) {
      setLlmElapsedMs(0);
      return;
    }
    const start = new Date(health.llmStartedAt).getTime();
    if (Number.isNaN(start)) return;

    const update = () => setLlmElapsedMs(Math.max(0, Date.now() - start));
    update();
    const timer = setInterval(update, 1000);
    return () => clearInterval(timer);
  }, [health?.llmStatus, health?.llmStartedAt]);

  if (!health) {
    return (
      <Card className="border-zinc-800 bg-zinc-900">
        <CardContent className="flex items-center gap-3 py-6 text-sm text-zinc-500">
          <HeartPulse className="h-5 w-5 animate-pulse text-zinc-400" />
          <span>正在实时评估系统健康水位与治理指标...</span>
        </CardContent>
      </Card>
    );
  }

  const quality = Math.round(health.quality);
  const risk = Math.round(health.risk);
  const metrics = health.metrics;
  const status = scoreColor(quality);
  const actionable =
    (health.signals?.contradiction_actionable ?? 0) +
    (health.signals?.duplicate_actionable ?? 0);

  return (
    <Card className="border-zinc-800 bg-zinc-900/90 shadow-sm backdrop-blur-md">
      <CardContent className="p-5">
        <div className="flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between">
          {/* 左侧：超大质量分与呼吸药丸 */}
          <div className="flex items-center gap-4 shrink-0">
            <div className="flex h-14 w-14 items-center justify-center rounded-xl border border-zinc-800 bg-zinc-950/80 shadow-inner">
              <span className={`text-3xl font-bold tracking-tight ${status.text}`}>
                {quality}
              </span>
            </div>
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <span className="text-base font-semibold text-zinc-100">记忆健康雷达</span>
                <div
                  className={`flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium ${status.border} ${status.bg} ${status.text}`}
                >
                  <span className={`h-1.5 w-1.5 rounded-full ${status.text.replace("text-", "bg-")} animate-pulse`} />
                  <span>{status.label}</span>
                </div>
              </div>
              <p className="text-xs text-zinc-400">
                按风险、复用、链接覆盖与 LLM curator 遥测加权实时计算
              </p>
            </div>
          </div>

          {/* 中间：4 核心指标迷你进度条 */}
          <div className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4 lg:flex-1 lg:max-w-2xl lg:px-6">
            <div className="space-y-1">
              <div className="flex justify-between text-xs">
                <span className="text-zinc-400 flex items-center gap-1">
                  <ShieldCheck className="h-3 w-3 text-sky-400" /> 风险控制
                </span>
                <span className="font-semibold text-zinc-200">{risk}%</span>
              </div>
              <div className="h-1.5 w-full overflow-hidden rounded-full bg-zinc-950">
                <div className="h-full rounded-full bg-sky-400" style={{ width: `${risk}%` }} />
              </div>
            </div>

            <div className="space-y-1">
              <div className="flex justify-between text-xs">
                <span className="text-zinc-400 flex items-center gap-1">
                  <Link2 className="h-3 w-3 text-indigo-400" /> 链接覆盖
                </span>
                <span className="font-semibold text-zinc-200">{Math.round(metrics.linked_coverage)}%</span>
              </div>
              <div className="h-1.5 w-full overflow-hidden rounded-full bg-zinc-950">
                <div className="h-full rounded-full bg-indigo-400" style={{ width: `${Math.round(metrics.linked_coverage)}%` }} />
              </div>
            </div>

            <div className="space-y-1">
              <div className="flex justify-between text-xs">
                <span className="text-zinc-400 flex items-center gap-1">
                  <Recycle className="h-3 w-3 text-emerald-400" /> 复用覆盖
                </span>
                <span className="font-semibold text-zinc-200">{Math.round(metrics.active_reuse_coverage)}%</span>
              </div>
              <div className="h-1.5 w-full overflow-hidden rounded-full bg-zinc-950">
                <div className="h-full rounded-full bg-emerald-400" style={{ width: `${Math.round(metrics.active_reuse_coverage)}%` }} />
              </div>
            </div>

            <div className="space-y-1">
              <div className="flex justify-between text-xs">
                <span className="text-zinc-400 flex items-center gap-1">
                  <Sparkles className="h-3 w-3 text-amber-400" /> 可用池健康
                </span>
                <span className="font-semibold text-zinc-200">{Math.round(100 - metrics.pending_cleanup_share)}%</span>
              </div>
              <div className="h-1.5 w-full overflow-hidden rounded-full bg-zinc-950">
                <div className="h-full rounded-full bg-amber-400" style={{ width: `${Math.round(100 - metrics.pending_cleanup_share)}%` }} />
              </div>
            </div>
          </div>

          {/* 右侧：状态指示徽章 */}
          <div className="flex items-center gap-2 shrink-0 border-t border-zinc-800 pt-3 lg:border-t-0 lg:pt-0">
            {actionable > 0 ? (
              <Badge variant="outline" className="border-amber-700/60 bg-amber-500/10 text-amber-300 text-xs">
                {actionable} 项待决策
              </Badge>
            ) : (
              <Badge variant="outline" className="border-emerald-700/60 bg-emerald-500/10 text-emerald-300 text-xs">
                合规安全
              </Badge>
            )}
            <Badge
              variant="outline"
              className={
                health.llmStatus === "success" || health.llmStatus === "succeeded"
                  ? "border-emerald-700 bg-emerald-500/10 text-emerald-300 text-xs"
                  : health.llmStatus === "running"
                  ? "border-sky-700 bg-sky-500/10 text-sky-300 text-xs animate-pulse"
                  : "border-zinc-700 bg-zinc-800 text-zinc-400 text-xs"
              }
            >
              LLM 治理:{" "}
              {health.llmStatus === "running"
                ? `运行中 (${formatDuration(llmElapsedMs)})`
                : health.llmStatus === "success" || health.llmStatus === "succeeded"
                ? "就绪"
                : health.llmStatus}
            </Badge>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
