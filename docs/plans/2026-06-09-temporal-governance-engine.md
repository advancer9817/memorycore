# Temporal Governance Engine — 时间线记忆治理引擎

> Date: 2026-06-09
> Scope: MemoryCore architecture direction and implementation plan for temporal memory governance, LLM-assisted review, policy-gated automation, audit/rollback, and Auto-Governance Cockpit UI.

## 1. Architecture Direction

MemoryCore should evolve from:

```text
Memory storage + curator report
```

to:

```text
Temporal Governance Engine
```

Chinese name:

```text
时间线记忆治理引擎
```

The target architecture combines:

```text
Temporal Memory
+ Candidate Detector
+ LLM Judge
+ Deterministic Policy Gate
+ Mutation Executor
+ Audit / Rollback
+ Auto-Governance Cockpit
```

The core goal is to reduce frequent manual memory review. The system should automatically handle high-confidence, low-risk governance items, while the user only reviews a small number of high-risk, low-confidence, information-losing, or user-preference decisions.

---

## 2. Current Baseline and Gap

MemoryCore already has many required primitives. Current implementation evidence indicates that several items originally described as future additions are already present and should now be treated as hardening targets rather than greenfield work:

- `valid_from` / `valid_until`
- `decay_policy`
- `confidence` / `importance`
- `status`, including `superseded`
- `superseded_by` / `fact_lineage_root`
- `supersedes` / `contradicts` / `supports` / `related_to` / `part_of` links
- LLM curator and structured governance decisions
- `governance_decisions` table with LLM trace and before/after/rollback fields
- audit events
- review queue APIs
- rollback support
- `memory_lineage` / `memory_supersede` MCP tools
- Memory Intelligence Center UI shell
- context-pack ranking with a conservative recency term

The remaining gap is therefore not basic primitive availability. The gap is that these primitives do not yet form a strict, explainable, and trusted governance loop.

The current flow is closer to:

```text
Detect problem → show problem → ask user to review
```

The desired flow is:

```text
Detect problem
→ enrich with temporal / lineage / risk context
→ LLM judges semantic intent as structured JSON
→ deterministic policy gate routes the decision
→ low-risk reversible actions auto-apply
→ high-risk or ambiguous actions enter human review queue
→ every decision and execution is written to audit / timeline / rollback surfaces
→ metrics tune future automation thresholds
```

---

## 3. Four Pillars

### A. Temporal Memory: Memories as Fact Lineages

A memory should not be treated as an isolated static record. It should be treated as a version in a fact lineage:

```text
Old fact A
  └── superseded by new fact B
        └── superseded by new fact C
```

#### Existing foundation

The current MemoryCore schema already includes:

```sql
superseded_by TEXT,
fact_lineage_root TEXT
```

and the status set already includes:

```text
superseded
```

The implementation focus should be lineage invariants, migration hardening, query shape, and rollback behavior.

#### Lineage invariants

Every supersession operation should preserve these invariants:

1. A lineage is a directed chain from older facts to newer facts.
2. The newer memory links to the older memory with `relation_type = 'supersedes'`.
3. The older memory stores `superseded_by = <newer_id>`.
4. Every member of the same lineage stores the same `fact_lineage_root`.
5. `fact_lineage_root` is the earliest known memory in the lineage.
6. Ordinary auto-supersession should produce one active head.
7. Branches are allowed only as exceptional conflict cases and should be surfaced for review.
8. Ordinary retrieval excludes `superseded` records like `archived` records.
9. Lineage and audit views include superseded records.

#### Recommended `supersede_memory_record(old_id, new_id)` behavior

The existing `supersede_memory_record()` path should be hardened as follows:

- Reject missing records.
- Reject identical `old_id` / `new_id`.
- Reject ordinary attempts to supersede archived records.
- Reject or route to human review if `new_id` is already superseded by another memory.
- Calculate root as:

```text
root_id = old.fact_lineage_root or old.id
```

- If `new.fact_lineage_root` exists and differs from `root_id`, treat the operation as a lineage merge and require human review.
- Update records in the old chain that still have missing or local roots so they share the same root.
- Preserve link direction as:

```text
new -> old, relation_type = supersedes
```

- Make duplicate link creation idempotent.
- Capture before/after snapshots for both old and new records when the supersession comes from governance.

#### Recommended `memory_lineage(memory_id)` response

The public MCP/API response should normalize the lineage into a compact UI-friendly shape:

```json
{
  "root_id": "oldest-id",
  "current_head_id": "newest-active-id",
  "chain": [
    {
      "id": "old",
      "title": "Old fact",
      "type": "project",
      "status": "superseded",
      "created_at": "...",
      "updated_at": "...",
      "valid_from": "...",
      "valid_until": null,
      "confidence": 0.82,
      "importance": 0.7,
      "superseded_by": "new"
    },
    {
      "id": "new",
      "title": "New fact",
      "type": "project",
      "status": "active",
      "created_at": "...",
      "updated_at": "...",
      "valid_from": "...",
      "valid_until": null,
      "confidence": 0.91,
      "importance": 0.74,
      "superseded_by": null
    }
  ],
  "links": [
    {
      "source_id": "new",
      "target_id": "old",
      "relation_type": "supersedes"
    }
  ],
  "branches": []
}
```

Implementation details:

- Build adjacency from both `superseded_by` and `memory_links`.
- Sort the main chain by root-to-head traversal; timestamp sort is only a fallback.
- `current_head_id` is the non-superseded lineage member that is not targeted by a newer member.
- If multiple active heads exist, return `current_head_id = null` and list the heads under `branches`.

#### Lineage indexes

Add or ensure these indexes in the lazy migration/bootstrap path:

```sql
CREATE INDEX IF NOT EXISTS idx_memories_superseded_by
  ON memories(superseded_by);

CREATE INDEX IF NOT EXISTS idx_memories_lineage_root
  ON memories(fact_lineage_root);

CREATE INDEX IF NOT EXISTS idx_memories_status_lineage
  ON memories(status, fact_lineage_root);
```

SQLite cannot cheaply add foreign-key constraints to existing columns. For now, enforce lineage integrity in application code. If a future rebuilt schema is introduced, use:

```sql
FOREIGN KEY(superseded_by) REFERENCES memories(id) ON DELETE SET NULL
```

Do not cascade-delete lineage members.

---

### B. Auto-Supersession: High-Confidence New Facts Replace Old Facts

The user’s observation is that, in conflicts, newer memories are often more accurate. This should become system behavior, but conservatively.

#### Existing foundation

Write-time deterministic auto-supersession already exists, but the current detector is primarily local lexical similarity based. The target detector should evolve toward vector top-k retrieval plus lexical/entity guardrails.

#### Candidate detector pipeline

Use a layered detector rather than one similarity threshold:

```text
memory_add / memory_ingest
→ same-boundary prefilter
→ vector / lexical candidate retrieval
→ temporal and lineage enrichment
→ risk enrichment
→ LLM judge for ambiguous semantic intent
→ policy gate
```

Recommended stages:

1. **Write-time prefilter**
   - Restrict to `status = 'active'`.
   - Match on `type`, `scope`, and `project_path` before auto-apply.
   - Exclude self and non-comparable records.

2. **Candidate retrieval**
   - Query vector store top-5 or top-10 active memories.
   - If vector store is unavailable, fall back to lexical scanning.
   - Keep lexical similarity as a guardrail, not the only score.

3. **Temporal / lineage enrichment**
   - Include `created_at`, `updated_at`, `valid_from`, `valid_until`, `fact_lineage_root`, `superseded_by`, and source authority metadata.
   - Prefer newer records only when semantic similarity is already high.

4. **Risk enrichment**
   - Mark precious records early: `user_profile`, `decision`, `project_memory`, high importance, positive feedback, or decision-like content.
   - Route those to review even when similarity is high.

#### Candidate classes

Use these candidate buckets:

- `duplicate` — same fact, same meaning.
- `supersession` — newer fact replaces older fact.
- `contradiction` — semantically close, logically incompatible.
- `stale` — old record likely outside the useful validity window.
- `importance_reweight` — confidence/importance should be reweighted.
- `merge` — content should be merged, not replaced.

#### Threshold strategy

The original target threshold was:

```text
similarity >= 0.88 → auto-supersede candidate
0.75 <= similarity < 0.88 → review candidate
```

For first production rollout, use a safer threshold until rollback/revival metrics are available:

```text
auto_supersede_threshold = 0.96 initially
review_similarity_threshold = 0.82 initially
```

Then tune toward lower thresholds only when telemetry proves precision is high.

Key metric:

```text
If user revival rate for auto-superseded memories > 5%, raise the threshold.
```

#### Required auto-apply conditions

Auto-supersede only when all conditions hold:

- temporal governance is enabled;
- auto-supersede is enabled;
- old and new are both `active`;
- same `type`;
- same `scope`;
- same `project_path`, unless an explicit policy allows global-to-project supersession;
- neither record is precious (`user_profile`, `decision`, `project_memory`);
- neither record is high-importance;
- target record has no positive feedback signal;
- no conflicting lineage-root merge is required;
- before-state snapshot is stored;
- recommended action passes the deterministic policy gate.

If similarity is high but any safety condition fails, create a governance decision with `needs_review`; do not auto-apply.

#### Idempotent candidate generation

Candidate detection must be repeat-safe:

```text
candidate_hash = hash(decision_type + sorted(source_ids) + recommended_action + target/root ids + policy_version)
```

Rules:

- Do not create duplicate unresolved governance rows for the same candidate hash.
- Treat `needs_review`, `auto_approved`, and `applied` as existing active decisions.
- Re-evaluate only when source records changed materially.
- Store `policy_version`, `judge_schema_version`, and `candidate_hash` with the decision.

---

### C. LLM Judge + Policy Gate: LLM Judges, Rules Execute

The LLM must not directly execute governance actions.

The LLM only outputs structured decisions. A deterministic policy gate decides whether the action can auto-apply, must be reviewed, or is rejected.

#### Recommended LLM judge schema

```json
{
  "decision_type": "duplicate | contradiction | stale | importance_reweight | merge | supersession",
  "candidate_ids": ["..."],
  "recommended_action": {
    "action": "archive | mark_stale | mark_contradicted | reweight | link | promote | supersede | merge | no_op",
    "target_ids": ["..."],
    "survivor_id": "...",
    "new_importance": 0.72,
    "link_type": "supersedes",
    "valid_from": "...",
    "valid_until": "...",
    "rationale": "..."
  },
  "llm_confidence": 0.87,
  "risk_level": "low | medium | high",
  "evidence": {
    "semantic_overlap": 0.91,
    "contradiction_signals": [],
    "recency_signal": 0.64,
    "importance_signal": 0.52
  },
  "review_status": "pending | auto_approved | needs_review | human_approved | human_rejected | rolled_back",
  "raw_trace_ref": "..."
}
```

Schema constraints:

- `decision_type` must be one fixed enum value.
- `recommended_action.action` must map to a deterministic backend action.
- `target_ids` and `survivor_id` must be explicit.
- `llm_confidence` is normalized to `0..1`.
- `risk_level` is model evidence, not final authorization.
- Raw prompt, raw response, rationale, and trace metadata are stored separately from the parsed decision.

LLM output rules:

1. No SQL.
2. No direct mutation instruction.
3. No tool-call instruction.
4. No automatic delete recommendation.
5. Merge always requires human confirmation.
6. The deterministic policy reason is authoritative over the LLM rationale.

#### Deterministic policy gate inputs

The policy gate consumes:

- `decision_type`
- `recommended_action`
- `llm_confidence`
- `risk_level`
- similarity / semantic-overlap score
- source record `type`, `scope`, and `project_path`
- source record `importance` / `confidence`
- positive feedback flags
- precious-type flags
- whether the action is destructive
- whether the action may lose information
- whether before-state snapshot exists
- policy version

#### Policy gate outcomes

Separate outcomes explicitly:

```text
reject        → forbidden action; cannot proceed
needs_review  → human decision required
auto_approved → safe reversible action may execute automatically
```

Do not blur `reject` and `needs_review`.

Policy reasons should be structured:

```json
{
  "outcome": "needs_review",
  "reasons": [
    "high_importance_memory",
    "precious_type",
    "confidence_below_auto_threshold"
  ],
  "policy_version": "2026-06-09.1"
}
```

#### Suggested gate rules

| Type | Auto-apply condition | Human confirmation |
|---|---|---|
| exact duplicate | `confidence >= 0.95`, low risk, non-precious, reversible | survivor or target `importance >= 0.85` |
| near duplicate | `confidence >= 0.90`, low risk, same boundary | either side `importance >= 0.7` |
| supersession | `confidence >= initial threshold`, same type/scope/project, no precious/high-importance/positive-feedback target | any lineage merge or precious/high-importance record |
| contradiction | default review; optionally auto-mark only for low-risk, high-confidence, low-importance records | user preference, decision, high-importance, or ambiguous conflict |
| stale/archive | `confidence >= 0.80`, low risk, reversible | high-importance or positive-feedback record |
| importance reweight | `confidence >= 0.75` and small delta | `abs(delta) > 0.3` |
| merge | never automatic | always human |
| delete/hard-delete | never allowed | reject, not review |

#### Hard safety boundaries

MemoryCore must preserve these rules:

1. LLM does not write SQL.
2. LLM does not directly call mutation functions.
3. No automatic delete.
4. Merge is always human-confirmed.
5. High-importance memories default to human review.
6. User profile, user preference, decision, and project-memory conflicts default to human review.
7. Every execution writes audit.
8. Every execution stores `before_state` and supports rollback when possible.
9. Auto-apply is allowed only for reversible, low-risk, no-content-loss actions.
10. Cross-scope or cross-project actions require review unless explicitly whitelisted.

---

### D. Auto-Governance Cockpit: UI as Governance Cockpit, Not Todo Queue

The current UI problem is not missing widgets. The product philosophy is still manual-review-first.

The dashboard should become an Auto-Governance Cockpit with four zones:

```text
Zone 1: Auto-Applied
Zone 2: Needs Human Review
Zone 3: Health Metrics
Zone 4: Timeline / Audit
```

The default healthy state should be:

```text
All clear — MemoryCore handled routine governance automatically.
```

not:

```text
Please review more tasks.
```

#### Recommended component split

Use small cohesive files, for example:

```text
ui/components/dashboard/governance/
  GovernanceCockpit.tsx
  AutoAppliedStrip.tsx
  ReviewQueue.tsx
  ReviewQueueItemCard.tsx
  ConflictComparisonPanel.tsx
  BatchActionBar.tsx
  HealthMetricsPanel.tsx
  GovernanceTimeline.tsx
  TimelineAuditDrawer.tsx
  RawJudgeTraceDrawer.tsx
  GovernanceEmptyState.tsx
  GovernanceErrorState.tsx
  useGovernanceCockpit.ts
  api.ts
  formatters.ts
```

#### Header

The cockpit header should show:

- `Auto-Governance Cockpit`
- subtitle: `Policy-gated memory governance with audit and rollback.`
- status pill:
  - `All clear`
  - `Needs review`
  - `Auto-governing`
  - `Degraded`
- last governance run time
- primary action: `Run governance scan`
- secondary action: `View full audit`

#### Zone 1 — Auto-Applied

Shows what the system has already handled automatically:

```text
System applied 12 actions automatically:
- 5 duplicates archived
- 3 stale records downgraded
- 2 old facts superseded
- 2 importance scores adjusted
```

Recommended cards:

- `Duplicates archived`
- `Facts superseded`
- `Importance adjusted`
- `Stale records archived/downgraded`
- `Rolled back`

Clicking a card filters the timeline to that decision type or action.

#### Zone 2 — Needs Human Review

Only show items that truly require human decision:

- low-confidence conflicts;
- high-importance memory changes;
- merge proposals;
- user preference or decision conflicts;
- lineage merges;
- operations that generate new content or may lose information.

Each item should show:

```text
[Conflict] Memory A vs Memory B
Proposed: Supersede B with A
Confidence: 72%
Risk: medium
Policy gate: Held for review because B is high-importance.

[Accept] [Swap] [Keep Both] [Skip]
```

The queue must support non-binary decisions:

- `Accept`
- `Swap`
- `Keep Both`
- `Skip`
- `Open Trace`
- `Audit`

This is critical for trust. A binary accept/reject queue makes users choose between unsafe automation and manual cleanup.

##### Action semantics

- `Accept`
  - Calls the backend apply endpoint.
  - Moves item to timeline only after server success.

- `Skip`
  - Product label for backend rejection.
  - Sends a reason such as `user skipped in cockpit`.

- `Swap`
  - Reverses survivor/drop or old/new direction.
  - Requires backend validation.
  - Either leaves the updated decision in review or supports `Swap and Accept`.

- `Keep Both`
  - Marks the decision as human-resolved without mutating status.
  - Optionally creates a safe link such as `related_to`, `supports`, or `contradicts`.
  - Writes audit.

- `Open Trace`
  - Opens Raw Judge Trace drawer.

- `Audit`
  - Opens Timeline/Audit drawer scoped to the decision and source memories.

##### Batch actions

Batch actions are allowed only for low/medium-risk items.

- `Accept selected low-risk`
- `Skip selected`

Disable batch accept for:

- high-risk decisions;
- merge/split decisions;
- precious or high-importance memories;
- user-profile, preference, or decision memories;
- anything where policy gate says review is mandatory.

Server-side validation must reject unsafe batch operations even if the frontend enables them by mistake.

#### Zone 3 — Health Metrics

Health metrics should be observational and trust-building, not action-forcing.

Track:

- total candidates detected;
- candidates auto-approved;
- candidates sent to human review;
- candidates applied;
- candidates rejected/skipped;
- candidates rolled back;
- auto-apply rate;
- rollback rate;
- auto-supersede revival rate;
- review queue age;
- average time to decision;
- conflict density by scope/project;
- duplicate precision proxy;
- high-importance review rate;
- LLM governance status.

Guardrail metrics:

```text
If rollback rate rises, reduce auto-apply scope.
If auto-supersede revival rate > 5%, raise the supersession threshold.
If high-importance review volume is too large, tighten candidate detection.
```

#### Zone 4 — Timeline / Audit

Every governance action should be expandable:

```text
Before:
old.status = active
old.importance = 0.8

After:
old.status = superseded
old.superseded_by = new_id

Policy gate:
Auto-approved because records are same type/scope/project, low-importance, reversible, and confidence is 0.97.

[Undo]
```

Timeline sections:

1. decision created;
2. policy gate outcome;
3. auto-approval or human action;
4. mutation execution;
5. rollback event, if any;
6. related memory audit events;
7. lineage chain.

Show `Undo` only when:

- decision is applied;
- rollback snapshot exists;
- decision has not already been rolled back;
- current state is still compatible with rollback.

#### Raw LLM Trace drawer

The user previously requested visibility into raw LLM analysis. Each LLM decision should include a Raw Judge Trace drawer showing:

- prompt;
- raw response;
- parsed structured decision;
- rationale;
- thinking/trace content if captured;
- raw response reference;
- model/provider metadata;
- schema version;
- policy version;
- token counts if available;
- prompt hash if available.

Safety/UX details:

- Render trace as escaped text/code blocks, never HTML.
- Collapse very large prompt/response sections by default.
- Add `Copy trace` with accessible status text.
- Visually emphasize: `Raw trace is diagnostic; policy gate is authoritative.`

#### Accessibility requirements

- All action buttons need clear text labels or `aria-label`.
- Review cards should be keyboard navigable.
- Drawers must trap focus, close on Escape, and restore focus on close.
- Risk/confidence must not be color-only.
- Before/after diffs need text labels.
- Batch selection should use accessible checkboxes.
- Loading skeletons should use `aria-busy`.
- Mutation completion should use polite live-region announcements.

---

## 4. Target Architecture Diagram

```text
                 ┌──────────────────────────┐
                 │ memory_add / memory_ingest│
                 └─────────────┬────────────┘
                               │
                               v
                 ┌──────────────────────────┐
                 │ Candidate Detector        │
                 │ - duplicate               │
                 │ - supersession            │
                 │ - contradiction           │
                 │ - stale                   │
                 │ - importance drift        │
                 └─────────────┬────────────┘
                               │
                               v
                 ┌──────────────────────────┐
                 │ Temporal / Risk Enricher  │
                 │ - recency                 │
                 │ - lineage                 │
                 │ - valid_from/until        │
                 │ - source authority        │
                 │ - precious type flags     │
                 └─────────────┬────────────┘
                               │
                               v
                 ┌──────────────────────────┐
                 │ LLM Judge                 │
                 │ structured JSON only      │
                 └─────────────┬────────────┘
                               │
                               v
                 ┌──────────────────────────┐
                 │ Policy Gate               │
                 │ deterministic thresholds  │
                 │ structured reasons        │
                 └───────┬───────────┬──────┘
                         │           │
              auto apply │           │ needs review
                         v           v
        ┌────────────────────┐   ┌────────────────────┐
        │ Mutation Executor   │   │ Human Review Queue │
        │ memory_update/link  │   │ Cockpit Actions    │
        └─────────┬──────────┘   └─────────┬──────────┘
                  │                        │
                  v                        v
        ┌─────────────────────────────────────────────┐
        │ Governance Decisions / Audit / Rollback      │
        │ Timeline / Lineage / Raw LLM Trace           │
        └─────────────────────────────────────────────┘
```

---

## 5. Retrieval Ranking Change

Context-pack ranking should include recency as a soft signal, but recency must not allow recently written low-quality memories to outrank long-lived high-quality memories.

The original conceptual formula was:

```python
recency_score = max(0, 1 - recency_days / 365)

score = (
    0.35 * text_rank
  + 0.25 * importance
  + 0.20 * effectiveness
  + 0.10 * feedback
  + 0.10 * recency_score
)
```

However, the current ranker already has a conservative recency term and is not normalized exactly like this formula. Do not blindly increase recency to `0.10` in the current hybrid ranker.

Recommended current-production direction:

```text
rank_score = vector*0.42 + lexical*0.36 + entity_boost + source_bonus
           + atomic_bonus + parent_penalty
           + importance*0.07 + effectiveness*0.05 + feedback*0.02
           + recency*0.03
```

Implementation guidance:

- Keep recency as a soft additive term between `0.03` and `0.05` in the current ranker.
- Make recency configurable, e.g. `context_pack.recency_weight`, default `0.03`.
- Preserve relevance dominance: vector, lexical, and entity evidence should dominate freshness.
- Continue filtering ordinary context packs to active records only.
- Allow `include_superseded=true` only in lineage/audit/debug views, not ordinary retrieval.
- If MemoryCore later moves to a normalized formula, first normalize all components to `[0, 1]` and run retrieval-quality tests before changing production defaults.

---

## 6. MCP and API Surface

Avoid significant MCP tool expansion. Keep the MCP surface focused on agent-useful primitives, and keep cockpit-specific workflows behind backend REST APIs.

### MCP tools

#### `memory_lineage(memory_id, limit=100)`

Read-only lineage query.

Recommended response:

```json
{
  "root_id": "...",
  "current_head_id": "...",
  "chain": [
    {"id": "old", "status": "superseded", "superseded_by": "new"},
    {"id": "new", "status": "active", "superseded_by": null}
  ],
  "links": [],
  "branches": []
}
```

Requirements:

- side-effect free;
- includes superseded records;
- exposes branch ambiguity;
- includes compact fields needed by UI and agents.

#### `memory_supersede(old_id, new_id, note='', source_agent='agent')`

Explicit manual supersession.

Atomic behavior:

- validate both IDs;
- validate compatible type/scope/project unless future `force=true` is introduced;
- set `old.status = superseded`;
- set `old.superseded_by = new_id`;
- create `new -> old` link with `relation_type = supersedes`;
- set lineage root consistently;
- write `memory_supersede` audit event;
- return `{old, new, root_id, link}`.

Other LLM governance capabilities should prefer backend API/UI internals rather than exposing many new MCP tools.

### REST APIs for Cockpit MVP

Existing or minimal MVP APIs:

```text
GET  /api/governance/decisions?review_status=needs_review&limit=100
GET  /api/governance/decisions?review_status=applied&limit=100
POST /api/governance/{decision_id}/apply
POST /api/governance/{decision_id}/reject
POST /api/governance/{decision_id}/rollback
GET  /api/audit?memory_id={memory_id}&limit=50
GET  /api/lineage/{memory_id}?limit=100
GET  /api/memories/{memory_id}
GET  /api/curator/status
POST /api/curator/llm
```

Recommended Phase 4 additions:

```text
GET  /api/governance/summary?window=24h|7d|30d
GET  /api/governance/timeline?limit=100&status=&decision_type=&action=&memory_id=
GET  /api/governance/{decision_id}
GET  /api/governance/{decision_id}/audit
PATCH /api/governance/{decision_id}
POST /api/governance/{decision_id}/swap
POST /api/governance/{decision_id}/keep-both
POST /api/governance/batch/apply
POST /api/governance/batch/reject
```

Use a consistent response envelope:

```ts
interface ApiResponse<T> {
  success: boolean;
  data?: T;
  error?: string;
  meta?: {
    total: number;
    page: number;
    limit: number;
  };
}
```

For batch endpoints, return per-decision results rather than failing the whole batch:

```ts
interface BatchGovernanceResult {
  accepted: string[];
  rejected: string[];
  failed: Array<{ decisionId: string; error: string }>;
}
```

---

## 7. Database Direction

### Memories table

Already present or required columns:

```sql
superseded_by TEXT,
fact_lineage_root TEXT
```

Required indexes:

```sql
CREATE INDEX IF NOT EXISTS idx_memories_superseded_by
  ON memories(superseded_by);

CREATE INDEX IF NOT EXISTS idx_memories_lineage_root
  ON memories(fact_lineage_root);

CREATE INDEX IF NOT EXISTS idx_memories_status_lineage
  ON memories(status, fact_lineage_root);
```

### Governance decisions table

`governance_decisions` is the correct persistence boundary.

Semantics:

- candidate/judgment state lives here;
- policy-gate outcome lives here;
- execution evidence lives here;
- before/after/rollback snapshots live here;
- raw prompt/response/trace references live here;
- audit trail lives in `audit_events`;
- lineage state lives in `memories` and `memory_links`.

Important fields to preserve or add:

- `candidate_hash`
- `source_ids`
- `decision_type`
- `recommended_action`
- `llm_confidence`
- `risk_level`
- `review_status`
- `policy_reason`
- `policy_reasons_json`
- `finding_json`
- `llm_trace_json`
- `raw_response_ref`
- `before_state_json`
- `after_state_json`
- `rollback_json`
- `policy_version`
- `judge_model`
- `judge_schema_version`
- `decision_version`
- `execution_id`
- `applied_by`
- `rolled_back_by`
- `approval_kind`
- timestamps

Recommended indexes:

```sql
CREATE INDEX IF NOT EXISTS idx_governance_review_status
  ON governance_decisions(review_status);

CREATE INDEX IF NOT EXISTS idx_governance_created_at
  ON governance_decisions(created_at);

CREATE INDEX IF NOT EXISTS idx_governance_decision_type
  ON governance_decisions(decision_type);

CREATE INDEX IF NOT EXISTS idx_governance_applied_at
  ON governance_decisions(applied_at);

CREATE INDEX IF NOT EXISTS idx_governance_rolled_back_at
  ON governance_decisions(rolled_back_at);

CREATE UNIQUE INDEX IF NOT EXISTS idx_governance_candidate_hash_open
  ON governance_decisions(candidate_hash)
  WHERE review_status IN ('needs_review', 'auto_approved', 'applied');
```

If SQLite partial-index support is not acceptable for compatibility, enforce candidate-hash dedupe in application code.

### Review status mapping

Current storage values may differ from product labels. Prefer stable storage values with a public mapping:

| Storage status | UI/API product label |
|---|---|
| `needs_review` | `pending` |
| `auto_approved` | `auto_approved` |
| `applied` with auto approval | `auto_applied` |
| `applied` after human accept | `human_approved` |
| `rejected` | `human_rejected` / `skipped` |
| `rolled_back` | `rolled_back` |
| `kept_both` | `kept_both` |

Add `approval_kind` if the UI needs to distinguish human choices without reconstructing history:

```text
auto | human_accept | human_swap | human_keep_both | human_skip
```

### Migration strategy

Recommended bootstrap order:

1. Ensure `superseded` status exists.
2. Ensure `memories.superseded_by` and `memories.fact_lineage_root` exist.
3. Backfill `fact_lineage_root` only for existing `supersedes` links.
4. Do not infer roots from `related_ids_json` or tags.
5. Create lineage indexes.
6. Ensure `governance_decisions` columns.
7. Create governance indexes.
8. Store schema/policy version for future migrations.

---

## 8. Audit, Rollback, and Idempotency

### Required audit event types

Emit these events at minimum:

- `governance_decision_create`
- `governance_policy_gate`
- `governance_decision_apply`
- `governance_decision_reject`
- `governance_decision_keep_both`
- `governance_decision_swap`
- `governance_decision_rollback`
- `memory_supersede`
- `memory_update`
- `memory_status_change`

Each audit event should include:

- `decision_id`
- `action`
- `memory_ids`
- `review_status`
- `policy_reason`
- `policy_reasons`
- `before_state`
- `after_state`
- `rollback_available`
- `source_agent`
- timestamp

Prefer one high-level governance event plus normal memory mutation events. That keeps the timeline readable while preserving forensic detail.

### Rollback properties

Rollback should be:

- **idempotent** — running it twice returns `already_rolled_back` rather than duplicating side effects;
- **snapshot-based** — restore from stored `before_state`, not recomputed state;
- **status-safe** — restore `status`, `superseded_by`, `fact_lineage_root`, and importance/confidence fields;
- **link-safe** — restore affected `memory_links` or remove rolled-back `supersedes` links;
- **index-safe** — resync vector/entity indexes after restore;
- **audit-safe** — every rollback attempt writes success or failure evidence.

### Rollback edge cases

Handle explicitly:

1. Decision was never applied.
   - Return clear error or no-op response.
2. Target memory changed after application.
   - Block rollback or restore only if the decision owns the latest mutation chain.
3. Same rollback requested twice.
   - Return idempotent `already_rolled_back`.
4. Restored memory no longer exists.
   - Record failed rollback; do not silently succeed.
5. Links changed after application.
   - Require link snapshots or block rollback if safe restoration is impossible.

### Execution locking

Use one transaction or execution lock per decision apply/rollback so concurrent requests cannot apply or roll back the same decision twice.

Recommended transaction shape:

```text
BEGIN IMMEDIATE
  load decision
  verify status and execution_id
  verify policy outcome
  capture before_state if not already captured
  apply mutation
  capture after_state
  update decision status/timestamps/execution_id
  write audit events
COMMIT
```

### Snapshot content

`before_state_json` and `after_state_json` should capture at least:

- memory id;
- title;
- content;
- status;
- importance;
- confidence;
- valid_from / valid_until;
- superseded_by;
- fact_lineage_root;
- affected links;
- related ids if mutated;
- affected index keys if index resync needs them.

---

## 9. Phased Implementation Plan

### Phase 1 — Temporal Foundation Hardening

Goal: stabilize the fact evolution model and retrieval semantics.

Tasks:

- confirm `superseded` status is present everywhere status validation occurs;
- ensure `superseded_by` / `fact_lineage_root` exist in migration/bootstrap;
- add lineage indexes;
- harden `supersede_memory_record()` invariants;
- normalize `memory_lineage()` response to include `chain`, `current_head_id`, and `branches`;
- ensure ordinary retrieval excludes `superseded` records;
- keep recency weight conservative and configurable;
- show lineage in memory detail UI.

Tests:

- supersession sets old status, old `superseded_by`, both lineage roots, and `supersedes` link;
- three-record lineage returns ordered chain and current head;
- ordinary search/context pack excludes `superseded` records;
- recency never lets irrelevant fresh memory outrank a clearly relevant older memory.

Risk: low. This phase mostly hardens structure and read surfaces.

### Phase 2 — Policy-Gated LLM Governance Contract

Goal: make LLM curator output explicit structured decisions, while the backend policy gate remains the only authorization boundary.

Tasks:

- version the LLM judge schema;
- add or enforce `candidate_hash` dedupe;
- store `policy_version`, `judge_model`, `judge_schema_version`, and `execution_id`;
- separate `reject`, `needs_review`, and `auto_approved` outcomes;
- store structured policy reasons;
- expose raw LLM prompt / response / rationale / trace metadata;
- only allow low-risk stale/archive/small-reweight auto-apply at first.

Tests:

- LLM decision with SQL/tool instructions is rejected or ignored;
- merge always routes to human review;
- delete/hard-delete is rejected;
- precious/high-importance records route to review;
- duplicate candidate generation is idempotent.

### Phase 3 — Safe Auto-Supersession

Goal: enable high-confidence newer memories to supersede older facts within strict boundaries.

Tasks:

- add vector top-k candidate retrieval with lexical fallback;
- start `auto_supersede_threshold` at `0.96`;
- start `review_similarity_threshold` at `0.82`;
- enforce same type/scope/project for auto-apply;
- route precious, high-importance, positive-feedback, and lineage-merge cases to review;
- capture before/after/link snapshots;
- support rollback;
- track auto-supersede revival rate and rollback rate.

Key metric:

```text
If user revival rate for auto-superseded memories > 5%, raise the threshold.
```

Tests:

- high-similarity low-risk pair auto-supersedes when enabled;
- high-similarity precious/high-importance pair enters review;
- lineage merge requires review;
- rollback restores status, lineage fields, and links;
- repeated detector runs do not create duplicate decisions.

### Phase 4 — Auto-Governance Cockpit MVP

Goal: upgrade UI from manual review panel to governance cockpit using existing APIs where possible.

Milestone 1: Read-only cockpit foundation

- add `GovernanceCockpit` with four zones;
- fetch needs-review and applied decisions;
- show all-clear empty state;
- add read-only Raw Judge Trace drawer;
- add read-only Timeline/Audit drawer using decision snapshots.

Milestone 2: Single-item review workflow

- wire `Accept` to apply endpoint;
- wire `Skip` to reject endpoint;
- wire `Undo` to rollback endpoint;
- add robust mutation loading/error states;
- update UI only after server success;
- add basic UI tests for all-clear, accept, skip, trace drawer, and rollback.

Milestone 3: Conflict comparison and lineage

- add `ConflictComparisonPanel`;
- fetch missing memory details and lineage;
- show survivor/drop direction;
- add `View lineage` in the panel and audit drawer.

Milestone 4: Non-binary review actions

- add backend support for `swap` and `keep-both`;
- add UI actions for `Swap`, `Swap and Accept`, and `Keep Both`;
- add audit events for human choices;
- ensure these actions do not delete data.

Milestone 5: Batch operations and governance summary

- add summary and batch endpoints;
- enable batch apply only for safe low-risk decisions;
- add confirmation dialog with exact action summary;
- add server-side validation for batch safety.

Milestone 6: Operational hardening

- add trace metadata: model, schema version, policy version, token counts, prompt hash;
- add timeline filters and date windows;
- add metrics for auto-supersede revival/rollback rate;
- tune thresholds based on metrics.

### Phase 5 — Operational Governance Tuning

Goal: use metrics to improve automation without losing trust.

Tasks:

- monitor rollback rate;
- monitor revival rate;
- monitor review queue age;
- monitor human rejection/skipped rate by decision type;
- adjust thresholds by policy version;
- keep old policy decisions auditable by version;
- add dashboard warnings when automation is degraded or disabled.

---

## 10. Acceptance Criteria

The Temporal Governance Engine is ready for broad use when:

1. Ordinary retrieval excludes superseded memories.
2. Lineage query shows root, current head, chain, links, and branches.
3. Auto-apply cannot delete memory content.
4. Merge always requires human review.
5. High-importance and precious memories require human review.
6. Every governance decision stores structured LLM output and deterministic policy reason.
7. Every applied decision stores before/after snapshots.
8. Rollback is idempotent and audit-backed.
9. Candidate generation is deduplicated by stable candidate hash.
10. The cockpit has a clear `All clear` state.
11. The review queue supports `Accept`, `Swap`, `Keep Both`, and `Skip`.
12. Raw LLM trace is visible but clearly diagnostic, not authoritative.
13. Auto-applied actions are visible in timeline and can be undone when rollback is valid.
14. Auto-supersession threshold is tuned by rollback/revival metrics, not intuition.

---

## 11. Final Principles

1. Default to no deletion; change status and links instead.
2. New facts get recency boost, but not unconditional override.
3. High-confidence, low-risk governance should auto-apply.
4. High-importance, preferences, decisions, user-profile facts, and merge operations require human confirmation.
5. LLM judges only; it does not execute.
6. Execution must pass a deterministic policy gate.
7. Every governance action must be auditable, reversible, and explainable.
8. Rollback must be idempotent and snapshot-based.
9. The UI should make automation visible, not invisible.
10. The UI default state should be “All clear,” not “please review more tasks.”

---

## 12. One-Sentence Summary

MemoryCore should evolve into a Temporal Governance Engine: a timeline-driven memory governance system that turns “newer memories are often more correct” into a safe, auditable, policy-gated capability; turns LLM review into controlled automation; and turns the UI from a review panel into an automatic governance cockpit with traceability, rollback, and non-binary human decisions.
