"use client";

import { useEffect, useState } from "react";
import { CheckCircle2, ShieldCheck, XCircle } from "lucide-react";
import Link from "next/link";
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
  degraded_warning?: boolean;
};

export function GovernancePanel() {
  const { messages: t } = useI18n();
  const [counts, setCounts] = useState<GovernanceCounts | null>(null);
  const [metrics, setMetrics] = useState<GovernanceMetrics | null>(null);

  useEffect(() => {
    let active = true;
    Promise.all([
      fetch(`${getApiBaseUrl()}/api/v1/governance/counts`).then((response) => response.json()),
      fetch(`${getApiBaseUrl()}/api/v1/governance/metrics`).then((response) => response.json()),
    ])
      .then(([countsPayload, metricsPayload]) => {
        if (!active) return;
        const data = (countsPayload as { data?: GovernanceCounts }).data ?? (countsPayload as GovernanceCounts);
        setCounts(data ?? null);
        setMetrics(metricsPayload as GovernanceMetrics);
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
  const done = metrics?.applied_count ?? 0;

  return (
    <Card className="border-zinc-800 bg-zinc-900">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center justify-between text-sm font-medium text-zinc-300">
          <span className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-violet-400" /> {t.nav.governance}
          </span>
          {actionable > 0 ? (
            <Badge variant="outline" className="border-amber-700/60 bg-amber-500/10 text-amber-300 text-xs">
              {actionable} {t.governance.pending}
            </Badge>
          ) : (
            <Badge variant="outline" className="border-emerald-700 bg-emerald-500/10 text-emerald-300 text-xs">
              {t.governance.cockpit.allClear}
            </Badge>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="text-sm">
        {actionable === 0 && done === 0 ? (
          <div className="flex items-center gap-2 text-zinc-500 py-2">
            <CheckCircle2 className="h-4 w-4 text-emerald-500" /> {t.governance.cockpit.allClearDetail}
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
            <Stat label={t.governance.applied} value={done} tone="text-emerald-300" />
            <Stat label={t.governance.rejected} value={metrics?.rejected_count ?? 0} tone="text-red-300" />
            <Stat label={t.governance.pending} value={actionable} tone="text-amber-300" />
            <span className="text-xs text-zinc-500">{t.governance.policyVersionValue(String(metrics?.policy_version ?? "—"))}</span>
          </div>
        )}
        <div className="mt-3 flex items-center justify-between border-t border-zinc-800 pt-2">
          <span className="text-xs text-zinc-600">
            <XCircle className="mr-1 inline h-3 w-3 text-zinc-600" />
            {t.governance.rejectionRate}: {metrics && (metrics.rejected_count + (metrics.applied_count ?? 0)) > 0 ? `${Math.round((metrics.rejected_count / (metrics.rejected_count + (metrics.applied_count ?? 0))) * 100)}%` : "—"}
          </span>
          <Link href="/governance" className="text-xs text-violet-400 hover:text-violet-300">
            {t.governance.openDetails} →
          </Link>
        </div>
      </CardContent>
    </Card>
  );
}

function Stat({ label, value, tone }: { label: string; value: number; tone: string }) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-xs text-zinc-500">{label}</span>
      <span className={`text-base font-semibold ${tone}`}>{value}</span>
    </div>
  );
}