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
  current_head_id?: string | null;
  chain?: GovernanceMemorySnapshot[];
  branches?: GovernanceMemorySnapshot[];
  records: GovernanceMemorySnapshot[];
  links: Array<{ source_id?: string; target_id?: string; relation_type?: string }>;
}

export interface ContradictionFinding {
  newer_id: string;
  older_id: string;
  newer_title?: string;
  older_title?: string;
  reason?: string;
  score?: number;
}

export interface SemanticDuplicateFinding {
  keep_id: string;
  drop_id: string;
  keep_title?: string;
  drop_title?: string;
  merge_info?: string;
  reason?: string;
  score?: number;
}

export interface ImportanceReassessmentFinding {
  id: string;
  title?: string;
  old_importance?: number;
  new_importance?: number;
  reason?: string;
}

export interface SplitCandidateFinding {
  id: string;
  title?: string;
  reason?: string;
  sub_memories?: Array<{ title: string; content: string; importance?: number }>;
}

export type GovernanceDecisionType =
  | "contradiction"
  | "semantic_duplicate"
  | "importance_reassessment"
  | "split_candidate";

export type GovernanceReviewStatus = "actionable" | "all" | "auto_approved" | "applied" | "rejected" | "rolled_back";

export type GovernanceAction = "accept" | "skip" | "swap" | "keepBoth" | "rollback";

export interface GovernanceActionResult {
  decision?: GovernanceDecision;
  applied?: Record<string, unknown>;
  execution?: Record<string, unknown>;
  restored?: Array<Record<string, unknown>>;
  already_rolled_back?: boolean;
}

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
