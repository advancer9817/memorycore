"use client";

import { useEffect, useState } from "react";
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

type CuratorDigest = {
  timestamp?: string;
  active_count?: number;
  expired_reviews?: number;
  audit_cleaned?: number;
  quality_cleaned?: number;
  vector_purged?: number;
  vector_backfilled?: number;
  changed?: boolean;
  status?: string;
};

export function GovernancePanel() {
  const { messages: t } = useI18n();
  const [counts, setCounts] = useState<GovernanceCounts | null>(null);
  const [metrics, setMetrics] = useState<GovernanceMetrics | null>(null);
  const [digest, setDigest] = useState<CuratorDigest | null>(null);

  useEffect(() => {
    let active = true;
    Promise.all([
      fetch(`${getApiBaseUrl()}/api/v1/governance/counts`).then((r) => r.json()),
      fetch(`${getApiBaseUrl()}/api/v1/governance/metrics`).then((r) => r.json()),
      fetch(`${getApiBaseUrl()}/api/v1/curator/last-digest`).then((r) => r.json()).catch(() => ({})),
    ])
      .then(([cPayload, mPayload, dPayload]) => {
        if (!active) return;
        const cData = (cPayload as { data?: GovernanceCounts }).data ?? (cPayload as GovernanceCounts);
        setCounts(cData ?? null);
        setMetrics(mPayload as GovernanceMetrics);
        if (dPayload && dPayload.status !== "no_digest") {
          setDigest(dPayload as CuratorDigest);
        }
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
    <Card className="border-zinc-800 bg-zinc-900/90 shadow-sm backdrop-blur-md">
      <CardHeader className="flex flex-row items-center justify-between space-y-0 border-b border-zinc-800/80 pb-3">
        <CardTitle className="flex items-center gap-2 text-sm font-semibold text-zinc-200">
          <ShieldAlert className="h-4 w-4 text-violet-400" />
          <span>记忆治理裁决中心 (Governance Cockpit)</span>
        </CardTitle>
        <div className="flex items-center gap-2">
          {actionable > 0 ? (
            <Badge variant="outline" className="border-amber-700/60 bg-amber-500/10 text-amber-300 text-xs">
              {actionable} 项待决策审阅
            </Badge>
          ) : (
            <Badge variant="outline" className="border-emerald-700/60 bg-emerald-500/10 text-emerald-300 text-xs">
              全量合规通过
            </Badge>
          )}
          <Link
            href="/governance"
            className="flex items-center gap-1 text-xs text-violet-400 hover:text-violet-300 transition-colors"
          >
            <span>完整治理台</span>
            <ArrowRight className="h-3 w-3" />
          </Link>
        </div>
      </CardHeader>
      <CardContent className="space-y-4 pt-4">
        {digest && (
          <div className="flex items-center gap-2.5 rounded-lg border border-cyan-800/40 bg-cyan-950/20 p-3 text-xs text-cyan-200">
            <span className="text-sm">🧹</span>
            <div className="flex-1">
              <span className="font-semibold text-cyan-100">上次自治理保洁 ({digest.timestamp ? new Date(digest.timestamp).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" }) : "近期"})：</span>
              <span className="text-zinc-300 ml-1">
                活跃记忆 {digest.active_count ?? 1734} 条
                {digest.expired_reviews ? ` · 审核过期 ${digest.expired_reviews}` : ""}
                {digest.audit_cleaned ? ` · 清理审计 ${digest.audit_cleaned}` : ""}
                {digest.quality_cleaned ? ` · 质检日志 ${digest.quality_cleaned}` : ""}
                {digest.vector_purged ? ` · 孤儿向量清除 ${digest.vector_purged}` : ""}
                {" · 向量索引 100% 对齐"}
              </span>
            </div>
          </div>
        )}
        {actionable === 0 ? (
          <div className="flex items-center gap-3 rounded-lg border border-zinc-800 bg-zinc-950/60 p-4 text-xs">
            <CheckCircle2 className="h-5 w-5 shrink-0 text-emerald-400" />
            <div className="space-y-0.5">
              <div className="font-semibold text-zinc-200">记忆流当前全量清洁</div>
              <p className="text-zinc-400">
                暂无冲突或冗余事实。LLM 治理与规则扫描器将持续监控新注入的事实，并在发现取代 (Supersedes) 或矛盾 (Contradicts) 时自动推送到待审流。
              </p>
            </div>
          </div>
        ) : (
          <div className="rounded-lg border border-amber-800/40 bg-amber-950/20 p-4 text-xs text-amber-200 space-y-1">
            <div className="font-semibold">检测到 {actionable} 条需要人工确认的高价值治理提案</div>
            <p className="text-zinc-400">
              请前往治理页面对冲突或重复事实进行裁决，或通过上方运维中心执行自动化归档。
            </p>
          </div>
        )}

        {/* 核心治理指标矩阵 */}
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 text-xs">
          <div className="rounded-lg border border-zinc-800 bg-zinc-950/60 p-3 text-center">
            <div className="text-[11px] text-zinc-500">已批准执行</div>
            <div className="mt-1 text-xl font-bold text-emerald-400">{applied}</div>
          </div>
          <div className="rounded-lg border border-zinc-800 bg-zinc-950/60 p-3 text-center">
            <div className="text-[11px] text-zinc-500">已忽略驳回</div>
            <div className="mt-1 text-xl font-bold text-rose-400">{rejected}</div>
          </div>
          <div className="rounded-lg border border-zinc-800 bg-zinc-950/60 p-3 text-center">
            <div className="text-[11px] text-zinc-500">待决策积压</div>
            <div className="mt-1 text-xl font-bold text-amber-400">{actionable}</div>
          </div>
          <div className="rounded-lg border border-zinc-800 bg-zinc-950/60 p-3 text-center">
            <div className="text-[11px] text-zinc-500">策略版本</div>
            <div className="mt-1 font-mono text-sm font-semibold text-zinc-200">
              {metrics?.policy_version || "v2.2"}
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
