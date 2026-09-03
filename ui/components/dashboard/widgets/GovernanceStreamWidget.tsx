"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowRight, CheckCircle2, ShieldAlert, ShieldCheck } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useI18n } from "@/hooks/useI18n";
import { getApiBaseUrl } from "@/lib/api-url";

type GovernanceCounts = {
  contradiction: number;
  semantic_duplicate: number;
  importance_reassessment: number;
  split_candidate: number;
  total: number;
};

type GovernanceMetrics = {
  applied_count: number;
  rejected_count: number;
  needs_review_count: number;
  review_queue_age_hours: number;
  rollback_rate: number;
  policy_version: string;
};

export function GovernanceStreamWidget() {
  const { messages: t } = useI18n();
  const [counts, setCounts] = useState<GovernanceCounts | null>(null);
  const [metrics, setMetrics] = useState<GovernanceMetrics | null>(null);

  useEffect(() => {
    let active = true;
    Promise.all([
      fetch(`${getApiBaseUrl()}/api/v1/governance/counts`).then((r) => r.json()),
      fetch(`${getApiBaseUrl()}/api/v1/governance/metrics`).then((r) => r.json()),
    ])
      .then(([cPayload, mPayload]) => {
        if (!active) return;
        const cData = (cPayload as { data?: GovernanceCounts }).data ?? (cPayload as GovernanceCounts);
        setCounts(cData ?? null);
        setMetrics(mPayload as GovernanceMetrics);
      })
      .catch(() => {
        if (active) {
          setCounts(null);
          setMetrics(null);
        }
      });
    return () => {
      active = false;
    };
  }, []);

  const actionable = counts?.total ?? 0;
  const applied = metrics?.applied_count ?? 0;
  const rejected = metrics?.rejected_count ?? 0;

  return (
    <Card className="h-full border-zinc-800 bg-zinc-900">
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
        <CardTitle className="flex items-center gap-2 text-sm font-medium text-zinc-300">
          <ShieldAlert className="h-4 w-4 text-violet-400" />
          <span>治理建议流与决策大盘</span>
        </CardTitle>
        <div className="flex items-center gap-2">
          {actionable > 0 ? (
            <Badge variant="outline" className="border-amber-700/60 bg-amber-500/10 text-amber-300 text-xs">
              {actionable} {t.governance.pending}
            </Badge>
          ) : (
            <Badge variant="outline" className="border-emerald-700 bg-emerald-500/10 text-emerald-300 text-xs">
              {t.governance.cockpit.allClear}
            </Badge>
          )}
          <Link
            href="/governance"
            className="flex items-center gap-1 text-xs text-violet-400 hover:text-violet-300 transition-colors"
          >
            <span>{t.governance.openDetails}</span>
            <ArrowRight className="h-3 w-3" />
          </Link>
        </div>
      </CardHeader>
      <CardContent className="space-y-4 pt-1">
        {actionable === 0 ? (
          <div className="flex flex-col items-center justify-center gap-2 rounded-lg border border-zinc-800/80 bg-zinc-950/40 py-6 text-center">
            <CheckCircle2 className="h-6 w-6 text-emerald-500" />
            <div className="text-xs font-medium text-zinc-300">
              {t.governance.cockpit.allClear}
            </div>
            <div className="text-[11px] text-zinc-500 max-w-sm">
              {t.governance.cockpit.allClearDetail || "当前没有待处理的治理建议。规则调度器与语义大模型将在发现冲突或冗余事实时自动推送到此。"}
            </div>
          </div>
        ) : (
          <div className="rounded-lg border border-amber-800/40 bg-amber-950/10 p-3 text-xs text-amber-300 space-y-1">
            <div className="font-semibold">发现 {actionable} 条需人工审阅的治理提案</div>
            <p className="text-[11px] text-zinc-400">
              包含语义重复、陈旧事实取代与潜在冲突，请前往治理页面或通过运维控制器批量确认。
            </p>
          </div>
        )}

        {/* 统计指标行 */}
        <div className="grid grid-cols-4 gap-2 pt-1 border-t border-zinc-800 text-xs">
          <div className="rounded border border-zinc-800 bg-zinc-950/60 p-2 text-center">
            <div className="text-[11px] text-zinc-500">{t.governance.applied}</div>
            <div className="mt-1 font-semibold text-emerald-400">{applied}</div>
          </div>
          <div className="rounded border border-zinc-800 bg-zinc-950/60 p-2 text-center">
            <div className="text-[11px] text-zinc-500">{t.governance.rejected}</div>
            <div className="mt-1 font-semibold text-red-400">{rejected}</div>
          </div>
          <div className="rounded border border-zinc-800 bg-zinc-950/60 p-2 text-center">
            <div className="text-[11px] text-zinc-500">{t.governance.pending}</div>
            <div className="mt-1 font-semibold text-amber-400">{actionable}</div>
          </div>
          <div className="rounded border border-zinc-800 bg-zinc-950/60 p-2 text-center">
            <div className="text-[11px] text-zinc-500">策略版本</div>
            <div className="mt-1 font-mono text-zinc-300">{metrics?.policy_version || "v2.2"}</div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
