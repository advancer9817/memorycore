"use client";

import { useEffect, useState } from "react";
import { HeartPulse, Activity, Link2, Recycle, Sparkles } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
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

export function HealthBanner() {
  const { messages: t } = useI18n();
  const [health, setHealth] = useState<HealthScore | null>(null);

  useEffect(() => {
    let active = true;
    fetch(`${getApiBaseUrl()}/api/v1/health-score`)
      .then((response) => response.json() as Promise<HealthScore>)
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
      <Card className="border-zinc-800 bg-zinc-900">
        <CardContent className="flex items-center gap-3 py-5 text-sm text-zinc-500">
          <HeartPulse className="h-4 w-4" /> {t.dashboard.healthScoreDescription}
        </CardContent>
      </Card>
    );
  }

  const quality = Math.round(health.quality);
  const metrics = health.metrics;
  const actionable = (health.signals?.contradiction_actionable ?? 0) + (health.signals?.duplicate_actionable ?? 0);

  return (
    <Card className="border-zinc-800 bg-zinc-900">
      <CardContent className="flex flex-wrap items-center gap-x-6 gap-y-3 py-4">
        <div className="flex items-center gap-3">
          <div className={`text-4xl font-semibold leading-none ${scoreTone(quality)}`}>{quality}</div>
          <div className="text-xs text-zinc-500">
            <div className="font-medium text-zinc-300">{t.dashboard.healthScoreDescription.split(".")[0]}.</div>
            <div className="mt-1">{t.dashboard.healthScoreDescription}</div>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-xs">
          <MetricChip icon={<Activity className="h-3.5 w-3.5 text-violet-400" />} label={t.dashboard.riskControl} value={Math.round(health.risk)} />
          <MetricChip icon={<Link2 className="h-3.5 w-3.5 text-sky-400" />} label={t.dashboard.linkedCoverage} value={Math.round(metrics.linked_coverage)} />
          <MetricChip icon={<Recycle className="h-3.5 w-3.5 text-emerald-400" />} label={t.dashboard.reuseCoverage} value={Math.round(metrics.active_reuse_coverage)} />
          <MetricChip icon={<Sparkles className="h-3.5 w-3.5 text-amber-400" />} label={t.dashboard.nonArchivedRatio} value={Math.round(100 - metrics.pending_cleanup_share)} describe={`${metrics.pending_cleanup}/${metrics.usable_pool} ${t.dashboard.nonArchivedRatioDetail(metrics.pending_cleanup, metrics.usable_pool)}`} />
        </div>

        <div className="ml-auto flex items-center gap-2">
          {actionable > 0 && (
            <Badge variant="outline" className="border-amber-700/60 bg-amber-500/10 text-amber-300 text-xs">
              {actionable} {t.nav.governance}
            </Badge>
          )}
          <Badge variant="outline" className={health.llmStatus === "success" || health.llmStatus === "succeeded" ? "border-emerald-700 bg-emerald-500/10 text-emerald-300 text-xs" : "border-zinc-700 bg-zinc-800 text-zinc-400 text-xs"}>
            {t.dashboard.llmGovernance}: {health.llmStatus}
          </Badge>
        </div>
      </CardContent>
    </Card>
  );
}

function MetricChip({ icon, label, value, describe }: { icon: React.ReactNode; label: string; value: number; describe?: string }) {
  return (
    <div className="flex items-center gap-1.5" title={describe}>
      {icon}
      <span className="text-zinc-500">{label}</span>
      <span className="font-semibold text-zinc-200">{value}</span>
    </div>
  );
}