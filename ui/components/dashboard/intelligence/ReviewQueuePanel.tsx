"use client";

import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ArrowDownToLine, CheckSquare, FileSearch, Shield, Wrench } from "lucide-react";
import { useI18n } from "@/hooks/useI18n";

interface AttentionItem {
  label: string;
  detail: string;
  count: number;
  severity: "high" | "medium" | "low" | "good";
  group: "governance" | "operations";
  onRun?: () => void;
}

interface ReviewQueueItem extends AttentionItem {
  href: string;
  actionLabel: string;
  workflow: string[];
  operationHint: string;
  primaryHref: string;
  primaryLabel: string;
}

interface ReviewQueueProps {
  reviewQueue: ReviewQueueItem[];
  selectedReviewLabel: string | null;
  onSelectReview: (label: string) => void;
  onExport: () => void;
}

const severityClassName: Record<AttentionItem["severity"], string> = {
  high: "border-red-800/70 bg-red-950/35 text-red-200",
  medium: "border-amber-800/70 bg-amber-950/35 text-amber-200",
  low: "border-sky-800/70 bg-sky-950/35 text-sky-200",
  good: "border-emerald-800/70 bg-emerald-950/35 text-emerald-200",
};

function GroupSection({
  title,
  icon,
  items,
  allClearLabel,
  selectedLabel,
  onSelect,
}: {
  title: string;
  icon: React.ReactNode;
  items: ReviewQueueItem[];
  allClearLabel: string;
  selectedLabel: string | null;
  onSelect: (label: string) => void;
}) {
  const hasActive = items.some((item) => item.count > 0);

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-1.5 text-xs font-medium text-zinc-400">
        {icon}
        {title}
      </div>
      {hasActive ? (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {items.map((item) => {
            const isSelected = selectedLabel === item.label;
            return (
              <button
                key={item.label}
                type="button"
                aria-pressed={isSelected}
                onClick={() => onSelect(item.label)}
                className={`rounded-lg border px-3 py-2.5 text-left transition hover:brightness-110 ${
                  isSelected ? "ring-1 ring-primary/70" : ""
                } ${severityClassName[item.severity]}`}
              >
                <div className="flex items-center justify-between gap-3">
                  <span className="text-sm font-medium">{item.label}</span>
                  <Badge variant="outline" className="border-current/30 bg-black/20 text-current">
                    {item.count}
                  </Badge>
                </div>
                <p className="mt-1 line-clamp-2 text-xs text-current/75">{item.detail}</p>
              </button>
            );
          })}
        </div>
      ) : (
        <div className="rounded-lg border border-emerald-800/50 bg-emerald-950/20 px-3 py-2 text-xs text-emerald-300/80">
          {allClearLabel}
        </div>
      )}
    </div>
  );
}

export function ReviewQueuePanel({ reviewQueue, selectedReviewLabel, onSelectReview, onExport }: ReviewQueueProps) {
  const { messages } = useI18n();
  const t = messages.dashboard;

  const governanceItems = reviewQueue.filter((item) => item.group === "governance");
  const operationsItems = reviewQueue.filter((item) => item.group === "operations");
  const selectedReviewItem = reviewQueue.find((item) => item.label === selectedReviewLabel) ?? reviewQueue[0];

  return (
    <Card className="border-zinc-800 bg-zinc-900 xl:col-span-3">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center justify-between text-sm font-medium text-zinc-300">
          {t.reviewFlow}
          <FileSearch className="h-4 w-4 text-amber-400" />
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {reviewQueue.length > 0 ? (
          <>
            <p className="text-xs leading-relaxed text-zinc-500">{t.reviewFlowDescription}</p>
            <div className="space-y-4">
              <GroupSection
                title={t.groupGovernance}
                icon={<Shield className="h-3.5 w-3.5" />}
                items={governanceItems}
                allClearLabel={t.groupAllClear}
                selectedLabel={selectedReviewLabel}
                onSelect={onSelectReview}
              />
              <GroupSection
                title={t.groupOperations}
                icon={<Wrench className="h-3.5 w-3.5" />}
                items={operationsItems}
                allClearLabel={t.groupAllClear}
                selectedLabel={selectedReviewLabel}
                onSelect={onSelectReview}
              />
            </div>
            {selectedReviewItem && (
              <div className={`rounded-xl border p-3 ${severityClassName[selectedReviewItem.severity]}`}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <p className="text-sm font-semibold">{selectedReviewItem.label}</p>
                    <p className="mt-1 text-xs text-current/75">
                      {t.reviewQueueItemDetail(selectedReviewItem.count, selectedReviewItem.detail)}
                    </p>
                  </div>
                  <Badge variant="outline" className="border-current/30 bg-black/20 text-current">
                    {t.reviewSeverity}: {selectedReviewItem.severity}
                  </Badge>
                </div>
                <div className="mt-3 rounded-lg border border-current/20 bg-black/15 px-3 py-2 text-xs leading-relaxed text-current/80">
                  {selectedReviewItem.operationHint}
                </div>
                <ol className="mt-3 space-y-2">
                  {selectedReviewItem.workflow.map((step, index) => (
                    <li key={step} className="flex gap-2 text-xs leading-relaxed text-current/80">
                      <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-current/30 bg-black/20 text-[10px] font-semibold">
                        {index + 1}
                      </span>
                      <span>{step}</span>
                    </li>
                  ))}
                </ol>
                <div className="mt-3 flex flex-wrap gap-2">
                  <Button asChild size="sm" variant="outline" className="h-8 border-current/30 bg-black/20 text-current hover:bg-black/35">
                    <Link href={selectedReviewItem.primaryHref}>
                      <CheckSquare className="h-3.5 w-3.5" />
                      {selectedReviewItem.primaryLabel}
                    </Link>
                  </Button>
                  <Button size="sm" variant="outline" className="h-8 border-current/30 bg-black/20 text-current hover:bg-black/35" onClick={onExport}>
                    <ArrowDownToLine className="h-3.5 w-3.5" />
                    {t.reviewExportReport}
                  </Button>
                </div>
              </div>
            )}
          </>
        ) : (
          <div className="rounded-lg border border-emerald-800/70 bg-emerald-950/25 px-3 py-3 text-sm text-emerald-200">{t.noActiveReviewQueue}</div>
        )}
      </CardContent>
    </Card>
  );
}
