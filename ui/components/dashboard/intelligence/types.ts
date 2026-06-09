export interface GovernanceMemorySnapshot {
  id?: string;
  title?: string;
  content?: string;
  type?: string;
  status?: string;
  importance?: number;
  confidence?: number;
  source_agent?: string;
  app_name?: string;
  created_at?: string;
  updated_at?: string;
  superseded_by?: string | null;
  fact_lineage_root?: string | null;
}

export interface GovernanceDecision {
  id: string;
  decision_type: string;
  recommended_action: string;
  source_ids: string[];
  llm_confidence: number;
  risk_level: string;
  review_status: string;
  policy_reason: string;
  finding?: Record<string, unknown>;
  llm_trace?: Record<string, unknown>;
  before_state?: GovernanceMemorySnapshot[];
  after_state?: GovernanceMemorySnapshot[];
  created_at?: string;
  updated_at?: string;
  applied_at?: string | null;
  rolled_back_at?: string | null;
  source_agent?: string;
}

export interface AuditEvent {
  id?: string;
  event_type?: string;
  memory_id?: string | null;
  agent?: string;
  detail?: Record<string, unknown>;
  created_at?: string;
}

export interface LineagePayload {
  memory_id: string;
  root_id: string;
  records: GovernanceMemorySnapshot[];
  links: Array<{ source_id?: string; target_id?: string; relation_type?: string }>;
}

export type GovernanceAction = "accept" | "skip" | "swap" | "keepBoth" | "rollback";

export interface GovernanceMetrics {
  applied_count: number;
  rolled_back_count: number;
  needs_review_count: number;
  rejected_count: number;
  rollback_rate: number;
  revival_rate: number;
  review_queue_age_hours: number;
  rejection_rate_by_type: Record<string, number>;
  auto_supersede_enabled: boolean;
  degraded_warning: boolean;
  policy_version: string;
}
