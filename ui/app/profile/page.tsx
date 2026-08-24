"use client";

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Lock,
  RefreshCcw,
  Sparkles,
  UserRound,
} from "lucide-react";
import { PageShell } from "@/components/shared/PageShell";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useToast } from "@/hooks/use-toast";
import { useI18n } from "@/hooks/useI18n";
import { getApiBaseUrl } from "@/lib/api-url";

interface ProfileSource {
  id: string;
  title: string;
  snippet: string;
  updated_at: string;
}

interface ProfileAttribute {
  attribute: string;
  value: string;
  confidence: number;
  immutable: boolean;
  description: string;
  source_count: number;
  updated_at: string;
  sources?: ProfileSource[];
}

interface ProfilePayload {
  enabled: boolean;
  user_id: string;
  schema_count: number;
  covered: number;
  coverage: number;
  confidence_groups: { high: number; medium: number; low: number };
  immutable_locked: string[];
  latest_extract_at: string;
  extract_limit: number;
  min_confidence: number;
  max_snapshot_chars: number;
  attributes: ProfileAttribute[];
}

function formatTime(iso: string | undefined | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}

function confidenceLabel(conf: number): { label: string; cls: string } {
  if (conf >= 0.8) return { label: "high", cls: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30" };
  if (conf >= 0.6) return { label: "medium", cls: "bg-amber-500/15 text-amber-400 border-amber-500/30" };
  return { label: "low", cls: "bg-rose-500/15 text-rose-400 border-rose-500/30" };
}

export default function ProfilePage() {
  const { toast } = useToast();
  const { messages } = useI18n();
  const [payload, setPayload] = useState<ProfilePayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [extracting, setExtracting] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await fetch(`${getApiBaseUrl()}/api/v1/profile`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setPayload(data.data ?? data);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleExtract = useCallback(
    async (apply: boolean) => {
      setExtracting(true);
      try {
        const res = await fetch(`${getApiBaseUrl()}/api/v1/profile/extract`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ apply }),
        });
        const data = await res.json();
        if (!res.ok || data?.errors?.length) {
          throw new Error(data?.errors?.[0] ?? `HTTP ${res.status}`);
        }
        // Merge the returned (refreshed) profile into the view.
        if (data.profile) setPayload(data.profile);
        else if (apply) await load();
        toast({ description: messages.profilePage.extractSucceeded });
      } catch (e) {
        toast({
          title: messages.common.error,
          description: `${messages.profilePage.extractFailed}: ${e instanceof Error ? e.message : String(e)}`,
          variant: "destructive",
        });
      } finally {
        setExtracting(false);
      }
    },
    [load, messages, toast]
  );

  if (loading) {
    return (
      <PageShell title={messages.profilePage.title}>
        <div className="flex items-center justify-center py-20 text-zinc-500">{messages.common.loading}</div>
      </PageShell>
    );
  }

  if (error || !payload) {
    return (
      <PageShell title={messages.profilePage.title}>
        <Card className="border-zinc-800 bg-zinc-950">
          <CardContent className="flex items-center gap-3 py-6 text-rose-400">
            <AlertTriangle className="h-5 w-5" />
            {messages.common.error}: {error || "no data"}
          </CardContent>
        </Card>
      </PageShell>
    );
  }

  if (!payload.enabled) {
    return (
      <PageShell title={messages.profilePage.title} subtitle={messages.profilePage.subtitle}>
        <Card className="border-zinc-800 bg-zinc-950">
          <CardContent className="flex items-center gap-3 py-6 text-zinc-300">
            <AlertTriangle className="h-5 w-5 text-amber-400" />
            {messages.profilePage.disabled}
          </CardContent>
        </Card>
      </PageShell>
    );
  }

  const coveragePct = Math.round(payload.coverage * 100);
  const confGroups = payload.confidence_groups ?? { high: 0, medium: 0, low: 0 };
  const groupMap = [
    { key: "high" as const, label: messages.profilePage.highConfidence, cls: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30" },
    { key: "medium" as const, label: messages.profilePage.mediumConfidence, cls: "bg-amber-500/15 text-amber-400 border-amber-500/30" },
    { key: "low" as const, label: messages.profilePage.lowConfidence, cls: "bg-rose-500/15 text-rose-400 border-rose-500/30" },
  ];

  return (
    <PageShell
      eyebrow="MemoryCore"
      title={messages.profilePage.title}
      subtitle={messages.profilePage.subtitle}
      maxWidth="max-w-6xl"
      actions={
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => handleExtract(false)}
            disabled={extracting}
            className="border-zinc-700/50 bg-zinc-900 hover:bg-zinc-800 disabled:opacity-60"
          >
            <Sparkles className="h-4 w-4" />
            {extracting ? messages.profilePage.extracting : messages.profilePage.reExtract}
          </Button>
          <Button
            size="sm"
            onClick={() => handleExtract(true)}
            disabled={extracting}
            className="bg-violet-600 hover:bg-violet-500 text-white disabled:opacity-60"
          >
            <RefreshCcw className={`h-4 w-4 ${extracting ? "animate-spin" : ""}`} />
            {messages.profilePage.reExtractApply}
          </Button>
        </div>
      }
    >
      {/* Top stats row */}
      <div className="grid gap-4 md:grid-cols-4 animate-fade-slide-down">
        <Card className="border-zinc-800 bg-zinc-950/80">
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm font-medium text-zinc-400">
              <UserRound className="h-4 w-4 text-violet-400" />
              {messages.profilePage.coverage}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex items-end gap-2">
              <span className="text-3xl font-semibold">{coveragePct}%</span>
              <span className="pb-1 text-sm text-zinc-500">
                {payload.covered} {messages.profilePage.of} {payload.schema_count} {messages.profilePage.dimensions}
              </span>
            </div>
            <div className="mt-3 h-2 overflow-hidden rounded-full bg-zinc-800">
              <div className="h-full rounded-full bg-gradient-to-r from-violet-500 to-emerald-500" style={{ width: `${coveragePct}%` }} />
            </div>
            <p className="mt-2 text-xs text-zinc-500">{messages.profilePage.fillHint}</p>
          </CardContent>
        </Card>

        {groupMap.map((g) => (
          <Card key={g.key} className="border-zinc-800 bg-zinc-950/80">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-zinc-400">
                {g.label} {messages.profilePage.confidence}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <span className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-sm ${g.cls}`}>
                {confGroups[g.key]}
              </span>
              <p className="mt-2 text-xs text-zinc-600">
                min {Math.round(payload.min_confidence * 100)}%
              </p>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Attribute cards */}
      <div className="mt-4 grid gap-3 md:grid-cols-2">
        {payload.attributes.map((attr) => {
          const conf = confidenceLabel(attr.confidence);
          const isExpanded = expanded === attr.attribute;
          return (
            <Card key={attr.attribute} className={`border-zinc-800 bg-zinc-950/80 transition-colors hover:border-zinc-700`}>
              <CardHeader className="pb-1">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <CardTitle className="flex items-center gap-2 text-sm font-semibold">
                      {attr.immutable && <Lock className="h-3.5 w-3.5 text-violet-400" />}
                      {attr.attribute}
                      {attr.immutable && (
                        <span className="rounded border border-violet-500/30 bg-violet-500/10 px-1.5 py-0.5 text-[10px] text-violet-300">
                          {messages.profilePage.immutableBadge}
                        </span>
                      )}
                    </CardTitle>
                    {attr.description && (
                      <CardDescription className="mt-1 text-xs text-zinc-500">{attr.description}</CardDescription>
                    )}
                  </div>
                  {attr.value && (
                    <span className={`shrink-0 rounded-md border px-2 py-0.5 text-xs ${conf.cls}`}>
                      {conf.label === "high" ? messages.profilePage.highConfidence
                        : conf.label === "medium" ? messages.profilePage.mediumConfidence
                        : messages.profilePage.lowConfidence} · {Math.round(attr.confidence * 100)}%
                    </span>
                  )}
                </div>
              </CardHeader>
              <CardContent>
                {attr.value ? (
                  <div>
                    <p className="text-sm leading-relaxed text-zinc-200">{attr.value}</p>
                    <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-zinc-500">
                      <span className="flex items-center gap-1">
                        <CheckCircle2 className="h-3 w-3 text-emerald-500/70" />
                        {attr.source_count} {messages.profilePage.sources}
                      </span>
                      {attr.updated_at && (
                        <span>{messages.profilePage.updated}: {formatTime(attr.updated_at)}</span>
                      )}
                      {attr.sources && attr.sources.length > 0 && (
                        <Button
                          variant="link"
                          size="sm"
                          className="h-auto p-0 text-xs text-violet-400"
                          onClick={() => setExpanded(isExpanded ? null : attr.attribute)}
                        >
                          {messages.profilePage.viewSource}
                        </Button>
                      )}
                    </div>
                    {isExpanded && attr.sources && (
                      <div className="mt-3 space-y-2 border-t border-zinc-800 pt-3">
                        {attr.sources.map((src) => (
                          <div key={src.id} className="rounded-md bg-zinc-900/80 px-3 py-2">
                            <p className="text-xs font-medium text-zinc-300">{src.title}</p>
                            <p className="mt-0.5 line-clamp-2 text-xs text-zinc-500">{src.snippet}</p>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-zinc-600">{messages.profilePage.noValue}</span>
                    <span className="text-xs text-zinc-700">{messages.profilePage.dynamic}</span>
                  </div>
                )}
              </CardContent>
            </Card>
          );
        })}
      </div>

      <p className="mt-4 flex items-center gap-1.5 text-xs text-zinc-600">
        <Lock className="h-3 w-3" />
        {messages.profilePage.lockInfo}
      </p>
    </PageShell>
  );
}