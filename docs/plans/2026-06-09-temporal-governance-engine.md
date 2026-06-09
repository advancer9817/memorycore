# Temporal Governance Engine — 时间线记忆治理引擎

> Date: 2026-06-09
> Scope: MemoryCore architecture direction for temporal memory governance, LLM-assisted review, policy-gated automation, audit/rollback, and Auto-Governance Cockpit UI.

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
+ LLM Judge
+ Policy Gate
+ Audit / Rollback
+ Auto-Governance Cockpit
```

The core goal is to reduce frequent manual memory review. The system should automatically handle high-confidence, low-risk governance items, while the user only reviews a small number of high-risk, low-confidence, or information-losing decisions.

---

## 2. Overall Assessment

MemoryCore already has many required primitives:

- `valid_from` / `valid_until`
- `decay_policy`
- `confidence` / `importance`
- `status`
- `supersedes` / `contradicts` / `supports` / `related_to` / `part_of`
- LLM curator
- audit log
- review queue
- Memory Intelligence Center UI

However, these features do not yet form a closed governance loop. The current flow is closer to:

```text
Detect problem → show problem → ask user to review
```

The desired flow is:

```text
Detect problem
→ LLM judges semantic intent
→ deterministic policy gate routes the decision
→ low-risk actions auto-apply
→ high-risk actions enter human review queue
→ every action is written to timeline / audit / rollback surfaces
```

---

## 3. Four Pillars

### A. Temporal Memory: Memories as Fact Lineages

The key problem is that MemoryCore lacks a clear model for fact evolution when old and new memories conflict.

A memory should not be treated as an isolated static record. It should be treated as a version in a fact lineage:

```text
Old fact A
  └── superseded by new fact B
        └── superseded by new fact C
```

#### Schema additions

```sql
ALTER TABLE memories ADD COLUMN superseded_by TEXT;
ALTER TABLE memories ADD COLUMN fact_lineage_root TEXT;
```

Meaning:

- `superseded_by`: the newer memory that replaces this memory.
- `fact_lineage_root`: the root memory of this fact lineage.

#### Status addition

```text
superseded
```

#### State machine

```text
active ──[auto-supersede]──► superseded
active ──[decay]──────────► stale ──► archived
active ──[conflict]───────► contradicted
```

`superseded` is excluded from ordinary retrieval like `archived`, but remains visible through lineage queries.

---

### B. Auto-Supersession: High-Confidence New Facts Replace Old Facts

The user’s observation is that, in conflicts, newer memories are often more accurate. This should become system behavior, but conservatively.

#### Suggested write-time rule

When writing a new memory:

1. Run vector search for top-5 similar active memories.
2. If all conditions hold:
   - `similarity >= 0.88`
   - same `type`
   - same `scope` / `project_path`
   - old memory `status = active`
3. Automatically:
   - set `old.status = superseded`
   - set `old.superseded_by = new.id`
   - create `new -> old` link with `relation_type = supersedes`
   - set `new.fact_lineage_root = old.fact_lineage_root or old.id`

If similarity is between `0.75` and `0.87`:

```text
Create contradiction / review candidate only; do not auto-replace.
```

This provides:

- automatic handling for obvious duplicate/update cases;
- human review for ambiguous conflicts;
- no hard deletion;
- preserved lineage for old facts.

---

### C. LLM Judge + Policy Gate: LLM Judges, Rules Execute

The LLM must not directly execute governance actions.

The LLM only outputs structured decisions, for example:

```json
{
  "decision_type": "duplicate | contradiction | stale | importance_reweight | merge",
  "recommended_action": {
    "action": "archive | mark_stale | mark_contradicted | reweight | link | promote | no_op",
    "target_ids": ["..."],
    "survivor_id": "...",
    "new_importance": 0.72,
    "link_type": "supersedes",
    "rationale": "..."
  },
  "llm_confidence": 0.87,
  "risk_level": "low | medium | high",
  "review_status": "pending | auto_approved | human_approved | human_rejected | rolled_back"
}
```

A deterministic policy gate then decides whether the action can be auto-applied.

#### Suggested auto-apply thresholds

| Type | Auto-apply condition | Human confirmation |
|---|---|---|
| exact duplicate | `confidence >= 0.95` and low risk | survivor `importance >= 0.85` |
| near duplicate | `confidence >= 0.90` and low risk | both sides `importance >= 0.7` |
| contradiction | `confidence >= 0.88` and medium/low risk | both sides `importance >= 0.8` |
| stale/archive | `confidence >= 0.80` and low risk | usually not required |
| importance reweight | `confidence >= 0.75` | `delta > 0.3` |
| merge | never automatic | always human |

#### Hard safety boundaries

MemoryCore must preserve these rules:

1. LLM does not write SQL.
2. LLM does not directly call mutation functions.
3. No automatic delete.
4. Merge is always human-confirmed.
5. High-importance memories default to human review.
6. Every execution writes audit.
7. Every execution stores `before_state` and supports rollback.

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

#### Zone 1 — Auto-Applied

Shows what the system has already handled automatically:

```text
System applied 12 actions automatically:
- 5 duplicates archived
- 3 stale records downgraded
- 2 old facts superseded
- 2 importance scores adjusted
```

This is a retrospective status area, not a todo list.

#### Zone 2 — Needs Human Review

Only show items that truly require human decision:

- low-confidence conflicts;
- high-importance memory changes;
- merge proposals;
- user preference or decision conflicts;
- operations that generate new content or may lose information.

Each item should show:

```text
[Conflict] Memory A vs Memory B
Proposed: Archive B as superseded by A
Confidence: 72%
Risk: medium

[Accept] [Swap] [Keep Both] [Skip]
```

The queue must support:

- Accept
- Swap
- Keep Both
- Skip

It should not be limited to binary accept/reject; otherwise users cannot trust the system.

#### Zone 3 — Health Metrics

Health metrics remain, but become observational rather than action-forcing:

- Risk Control
- Reuse Coverage
- Link Coverage
- Non-archived Ratio
- LLM Governance Status

#### Zone 4 — Timeline / Audit

Every governance action should be expandable:

```text
Before:
old.status = active
old.importance = 0.8

After:
old.status = superseded
old.superseded_by = new_id

Reason:
New memory is more recent and semantically equivalent.

[Undo]
```

The user previously requested visibility into raw LLM analysis. Each LLM decision should therefore include a Raw Judge Trace drawer showing raw prompt, response, rationale, and any captured thinking/trace content.

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
                 │ - contradiction           │
                 │ - stale                   │
                 │ - importance drift        │
                 └─────────────┬────────────┘
                               │
                               v
                 ┌──────────────────────────┐
                 │ Temporal Enricher         │
                 │ - recency                 │
                 │ - lineage                 │
                 │ - valid_from/until        │
                 │ - source authority        │
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
                 └───────┬───────────┬──────┘
                         │           │
              auto apply │           │ needs review
                         v           v
        ┌────────────────────┐   ┌────────────────────┐
        │ Mutation Executor   │   │ Human Review Queue │
        │ memory_update/link  │   │ UI Cockpit         │
        └─────────┬──────────┘   └─────────┬──────────┘
                  │                        │
                  v                        v
        ┌─────────────────────────────────────────────┐
        │ Audit / Timeline / Rollback / Raw LLM Trace │
        └─────────────────────────────────────────────┘
```

---

## 5. Retrieval Ranking Change

Context pack ranking should include recency as a soft signal:

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

Recency must remain a soft signal. It must not allow recently written low-quality memories to outrank long-lived high-quality memories. Start with weight `0.10` and tune based on observed retrieval quality.

---

## 6. MCP Tool Surface

Avoid significant MCP tool expansion.

The minimal additions are:

### `memory_lineage(memory_id)`

Read-only lineage query.

Example response:

```json
{
  "root_id": "...",
  "current_head_id": "...",
  "chain": [
    {"id": "old", "status": "superseded"},
    {"id": "new", "status": "active"}
  ],
  "links": []
}
```

Used by UI and agents to understand how a fact evolved.

### `memory_supersede(old_id, new_id, note="")`

Explicit manual supersession.

Atomic behavior:

- set `old.status = superseded`
- set `old.superseded_by = new_id`
- create `new -> old` link with `relation_type = supersedes`
- write audit event

Other LLM governance capabilities should prefer backend API / UI internals rather than exposing many new MCP tools, to avoid MCP surface bloat.

---

## 7. Database Direction

Minimal memory table changes:

```sql
ALTER TABLE memories ADD COLUMN superseded_by TEXT;
ALTER TABLE memories ADD COLUMN fact_lineage_root TEXT;
```

Recommended governance decision table:

```text
governance_decisions
```

Purpose:

- store LLM judge structured output;
- track review status;
- preserve policy-gate decision;
- store before/after states;
- preserve rollback metadata;
- keep raw prompt/response references.

A separate `governance_audit` table may be considered, but if `audit_events` is already sufficient, it can be extended instead. The key distinction is that `governance_decisions` represents candidates, judgments, and approval state, while `audit_events` records what already happened.

---

## 8. Phased Implementation Plan

### Phase 1 — Temporal Foundation

Goal: build the fact evolution model without enabling automatic replacement.

Tasks:

- add `superseded` status;
- add `superseded_by` / `fact_lineage_root`;
- add `memory_lineage`;
- add recency score to context pack ranking;
- show lineage in memory detail UI.

Risk: low. This phase mostly adds structure and read surfaces.

### Phase 2 — Policy-Gated LLM Governance

Goal: make LLM curator emit structured decisions, without allowing large-scale unsafe auto-apply.

Tasks:

- add `governance_decisions`;
- define LLM judge schema;
- implement deterministic policy gate;
- add human review queue API;
- expose raw LLM prompt / response / rationale;
- only allow low-risk stale/archive/reweight auto-apply.

### Phase 3 — Auto-Supersession

Goal: enable high-confidence newer memories to supersede older facts.

Tasks:

- vector search top-5 at write time;
- `similarity >= 0.88` auto-supersedes;
- `0.75 <= similarity < 0.88` enters review queue;
- support rollback;
- track auto-supersede revival rate.

Key metric:

```text
If user revival rate for auto-superseded memories > 5%, raise the threshold.
```

### Phase 4 — Auto-Governance Cockpit

Goal: upgrade UI from manual review panel to governance cockpit.

Tasks:

- `AutoAppliedStrip`
- `ReviewQueue`
- `ConflictComparisonPanel`
- `BatchActionBar`
- `CurationTimeline` with Undo
- `HealthMetricsPanel`
- Raw LLM trace drawer

---

## 9. Final Principles

1. Default to no deletion; change status and links instead.
2. New facts get recency boost, but not unconditional override.
3. High-confidence, low-risk governance should auto-apply.
4. High-importance, preferences, decisions, and merge operations require human confirmation.
5. LLM judges only; it does not execute.
6. Execution must pass a deterministic policy gate.
7. Every governance action must be auditable, reversible, and explainable.
8. The UI default state should be “All clear,” not “please review more tasks.”

---

## 10. One-Sentence Summary

MemoryCore should evolve into a Temporal Governance Engine: a timeline-driven memory governance system that turns “newer memories are often more correct” into a safe, auditable system capability; turns LLM review into controlled policy-gated automation; and turns the UI from a review panel into an automatic governance cockpit.
