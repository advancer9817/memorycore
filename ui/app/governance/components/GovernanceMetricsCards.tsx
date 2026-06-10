import type { ReactNode } from "react";
import { AlertTriangle, CheckCircle2, RotateCcw, ShieldAlert } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { GovernanceMetrics } from "@/components/dashboard/intelligence/types";
import { formatPercent } from "@/components/dashboard/intelligence/utils";
import type { Messages } from "@/lib/i18n/types";

interface GovernanceMetricsCardsProps {
  metrics: GovernanceMetrics | null;
  messages: Messages["governance"];
}

interface MetricCard {
  label: string;
  value: string;
  detail: string;
  icon: ReactNode;
  tone: string;
}

export function GovernanceMetricsCards({ metrics, messages }: GovernanceMetricsCardsProps) {
  const cards: MetricCard[] = [
    {
      label: messages.needsReview,
      value: String(metrics?.needs_review_count ?? 0),
      detail: messages.decisionQueue,
      icon: <ShieldAlert className="h-4 w-4" />,
      tone: "text-amber-300",
    },
    {
      label: messages.applied,
      value: String(metrics?.applied_count ?? 0),
      detail: messages.policyVersionValue(metrics?.policy_version || "n/a"),
      icon: <CheckCircle2 className="h-4 w-4" />,
      tone: "text-emerald-300",
    },
    {
      label: messages.rollbackRate,
      value: formatPercent(metrics?.rollback_rate),
      detail: messages.rolledBackCount(metrics?.rolled_back_count ?? 0),
      icon: <RotateCcw className="h-4 w-4" />,
      tone: "text-violet-300",
    },
    {
      label: messages.revivalRate,
      value: formatPercent(metrics?.revival_rate),
      detail: messages.reviewQueueAge(Math.round(metrics?.review_queue_age_hours ?? 0)),
      icon: <AlertTriangle className="h-4 w-4" />,
      tone: metrics?.degraded_warning ? "text-red-300" : "text-sky-300",
    },
  ];

  return (
    <section aria-label={messages.metrics} className="space-y-2">
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        {cards.map((card) => (
          <Card key={card.label} className="border-zinc-800 bg-zinc-950/80">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium text-zinc-300">{card.label}</CardTitle>
              <span className={card.tone}>{card.icon}</span>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-semibold text-white">{card.value}</div>
              <p className="mt-1 text-xs text-zinc-500">{card.detail}</p>
            </CardContent>
          </Card>
        ))}
        {metrics?.degraded_warning ? (
          <div className="md:col-span-2 xl:col-span-4">
            <Badge className="border-red-800/70 bg-red-950/40 text-red-200">{messages.degradedWarning}</Badge>
          </div>
        ) : null}
      </div>
    </section>
  );
}
