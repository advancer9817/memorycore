"use client";

import Link from "next/link";
import { ArrowDownToLine, CheckSquare, FileSearch } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useI18n } from "@/hooks/useI18n";
import { ReviewQueueItem, severityClassName } from "./helpers";

interface ReviewFlowPanelProps {
  reviewQueue: ReviewQueueItem[];
  selectedReviewItem: ReviewQueueItem | undefined;
  onSelectLabel: (label: string) => void;
  onExportReport: () => void;
  t: ReturnType<typeof useI18n>["messages"]["dashboard"];
}

export function ReviewFlowPanel({
  reviewQueue,
  selectedReviewItem,
  onSelectLabel,
  onExportReport,
  t,
}: ReviewFlowPanelProps) {
  return (
    <Card className="border-zinc-800 bg-zinc-900 xl:col-span-3">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center justify-between text-sm font-medium text-zinc-300">
          {t.reviewFlow}
          <FileSearch className="h-4 w-4 text-amber-400" />
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {selectedReviewItem ? (
          <>
            <p className="text-xs leading-relaxed text-zinc-500">{t.reviewFlowDescription}</p>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {reviewQueue.map((item) => {
                const isSelected = selectedReviewItem.label === item.label;
                return (
                  <button
                    key={item.label}
                    type="button"
                    aria-pressed={isSelected}
                    onClick={() => onSelectLabel(item.label)}
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
                <Button
                  size="sm"
                  variant="outline"
                  className="h-8 border-current/30 bg-black/20 text-current hover:bg-black/35"
                  onClick={onExportReport}
                >
                  <ArrowDownToLine className="h-3.5 w-3.5" />
                  {t.reviewExportReport}
                </Button>
              </div>
            </div>
          </>
        ) : (
          <div className="rounded-lg border border-emerald-800/70 bg-emerald-950/25 px-3 py-3 text-sm text-emerald-200">
            {t.noActiveReviewQueue}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
