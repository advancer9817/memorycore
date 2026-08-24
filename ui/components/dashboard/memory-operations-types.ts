export type CuratorAction = {
  id: string;
  title?: string;
  action: string;
  reason?: string;
};

export type CuratorStatus = {
  stats: {
    total: number;
    by_status: Record<string, number>;
    by_type: Record<string, number>;
    never_accessed_count: number;
    link_count: number;
  };
  curator: {
    generated_at?: string;
    scanned: number;
    summary: Record<string, number>;
    planned_actions: CuratorAction[];
  };
  llm_curator?: {
    last_run_at?: string;
    last_result?: string;
    summary?: Record<string, number>;
    errors?: string[];
    latest_job?: { status?: string; job_id?: string | null };
  };
  timer: Record<string, string>;
  service: Record<string, string>;
  schedules?: {
    rule_curator?: Record<string, string>;
    llm_curator?: Record<string, string>;
  };
};

export type CuratorRunState = {
  state: "idle" | "running" | "succeeded" | "failed";
  startedAt?: string;
  finishedAt?: string;
  elapsedMs?: number;
  summary?: Record<string, number>;
  actions?: CuratorAction[];
  error?: string;
};

export type LlmRunState = {
  state: "idle" | "running" | "succeeded" | "failed";
  jobId?: string;
  startedAt?: number;
  elapsedMs?: number;
  summary?: Record<string, number>;
  progress?: { stage?: string; batch_index?: number };
  errors?: string[];
  error?: string;
};

export type MaintenanceGroup = {
  reason: string;
  count: number;
  samples?: Array<{ id: string; title?: string }>;
};

export type MaintenancePlan = {
  dry_run: boolean;
  generated_at: string;
  scanned: number;
  plan_token: string;
  archive_count: number;
  archive_ids: string[];
  groups: MaintenanceGroup[];
  summary: Record<string, number>;
};

export type MaintenanceJob = {
  job_id?: string | null;
  plan_token?: string;
  kind?: string;
  status: "running" | "succeeded" | "failed" | "none";
  created_at?: string;
  finished_at?: string;
  summary?: Record<string, number>;
  backup_path?: string | null;
  error?: string | null;
  replayed?: boolean;
};

export type MaintenanceRunState = {
  state: "idle" | "planning" | "planReady" | "running" | "succeeded" | "failed";
  plan?: MaintenancePlan | null;
  jobId?: string;
  startedAt?: number;
  elapsedMs?: number;
  result?: MaintenanceJob;
  error?: string;
};

export function getErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error) return error.message;
  if (typeof error === "string") return error;
  return fallback;
}

export function ellipsize(value: string | undefined, maxChars: number): string | undefined {
  if (!value) return value;
  const chars = Array.from(value);
  if (chars.length <= maxChars) return value;
  return `${chars.slice(0, Math.max(0, maxChars - 3)).join("")}...`;
}

export function formatTime(value?: string, locale: "en" | "zh" = "en") {
  if (!value || value === "n/a") return "n/a";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(locale === "zh" ? "zh-CN" : "en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
