"use client";

import { useEffect, useState } from "react";
import { Activity, HeartPulse, Link2, Sparkles } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useI18n } from "@/hooks/useI18n";
import { getApiBaseUrl } from "@/lib/api-url";

type HealthScore = {
  quality: number;
  risk: number;
  llmGovernance: number;
  llmStatus: string;
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

function scoreTone(score: number): string {
  if (score >= 80) return "text-emerald-400";
  if (score >= 60) return "text-amber-400";
  return "text-red-400";
}

export function HealthRadarWidget() {
  const { messages: t } = useI18n();
  const [health, setHealth] = useState<HealthScore | null>(null);

  useEffect(() => {
    let active = true;
    fetch(`${getApiBaseUrl()}/api/v1/health-score`)
      .then((res) => res.json() as Promise<HealthScore>)
      .then((payload) => {
        if (active) setHealth(payload);
      })
      .catch(() => {
        if (active) setHealth(null);
      });
    return () => {
      active = false;
    };
  }, []);

  if (!health) {
    return (
      <Card className="h-full border-zinc-800 bg-zinc-900">
        <CardContent className="flex items-center gap-3 py-8 text-sm text-zinc-500">
          <HeartPulse className="h-4 w-4 animate-pulse text-zinc-400" />
          <span>正在读取系统健康度...</span>
        </CardContent>
      </Card>
    );
  }

  const quality = Math.round(health.quality);
  const risk = Math.round(health.risk);
  const metrics = health.metrics;
  const actionable =
    (health.signals?.contradiction_actionable ?? 0) +
    (health.signals?.duplicate_actionable ?? 0);

  const statusConfig =
    quality >= 80
      ? { label: "状态卓越", dot: "bg-emerald-400", style: "border-emerald-500/30 bg-emerald-500/10 text-emerald-400" }
      : quality >= 60
      ? { label: "状态良好", dot: "bg-amber-400", style: "border-amber-500/30 bg-amber-500/10 text-amber-400" }
      : { label: "需要关注", dot: "bg-rose-400", style: "border-rose-500/30 bg-rose-500/10 text-rose-400" };

  return (
    <Card className="h-full border-zinc-800 bg-zinc-900">
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
        <CardTitle className="flex items-center gap-2 text-sm font-medium text-zinc-300">
          <HeartPulse className="h-4 w-4 text-violet-400 shrink-0" />
          <div className="flex flex-col">
            <span className="font-semibold text-zinc-200">系统健康雷达</span>
            <span className="text-[11px] font-normal text-zinc-500">遥测与安全合规加权评估</span>
          </div>
        </CardTitle>
        <div
          className={`flex shrink-0 items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-medium whitespace-nowrap ${statusConfig.style}`}
        >
          <span className={`h-1.5 w-1.5 rounded-full ${statusConfig.dot} animate-pulse`} />
          <span>{statusConfig.label}</span>
        </div>
      </CardHeader>
      <CardContent className="space-y-4 pt-1">
        {/* 双环核心大数字 */}
        <div className="grid grid-cols-2 gap-3 divide-x divide-zinc-800 rounded-lg bg-zinc-950/60 p-3">
          <div className="text-center">
            <div className={`text-3xl font-semibold tracking-tight ${scoreTone(quality)}`}>
              {quality}
            </div>
            <div className="mt-1 text-xs text-zinc-400">综合质量分</div>
            <div className="mt-1 text-[11px] text-zinc-500">
              复用率 {Math.round(metrics.active_reuse_coverage)}%
            </div>
          </div>
          <div className="text-center pl-3">
            <div className="text-3xl font-semibold tracking-tight text-sky-400">
              {risk}%
            </div>
            <div className="mt-1 text-xs text-zinc-400">{t.dashboard.riskControl}</div>
            <div className="mt-1 text-[11px] text-zinc-500">
              {actionable > 0 ? `${actionable} 项待决策` : "无高危风险"}
            </div>
          </div>
        </div>

        {/* 细分指标条目 */}
        <div className="space-y-2 text-xs">
          <div className="flex items-center justify-between text-zinc-400">
            <span className="flex items-center gap-1.5 text-zinc-400">
              <Link2 className="h-3.5 w-3.5 text-sky-400" />
              {t.dashboard.linkedCoverage}
            </span>
            <span className="font-semibold text-zinc-200">
              {Math.round(metrics.linked_coverage)}%
            </span>
          </div>
          <div className="flex items-center justify-between text-zinc-400">
            <span className="flex items-center gap-1.5 text-zinc-400">
              <Sparkles className="h-3.5 w-3.5 text-emerald-400" />
              可用池健康水位
            </span>
            <span className="font-semibold text-zinc-200">
              {metrics.usable_pool} 条
            </span>
          </div>
          <div className="flex items-center justify-between text-zinc-400">
            <span className="flex items-center gap-1.5 text-zinc-400">
              <Activity className="h-3.5 w-3.5 text-amber-400" />
              待治理积压 (Pending)
            </span>
            <span className="font-semibold text-amber-400">
              {metrics.pending_cleanup} 条 ({Math.round(metrics.pending_cleanup_share)}%)
            </span>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
