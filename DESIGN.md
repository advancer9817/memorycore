# Memory Intelligence Center — Design Review & Product Flow

> Produced by designer-3 for the memory-architecture-design team, 2026-06-09.
> Source files reviewed: `ui/MEMORY_INTELLIGENCE_CENTER_DESIGN.md`, `ui/components/dashboard/MemoryIntelligenceCenter.tsx` (1008 lines), `ui/components/dashboard/Install.tsx` (806 lines).

---

## Current State Assessment

### What already exists and works well

- Attention items panel (contradictions / duplicates / stale / candidates) with severity-colored rows
- Memory Health widget with composite quality score:
  - riskScore 34%, connectivity 18%, reuse coverage 18%, non-archived ratio 16%, LLM governance 14%
- Graph Snapshot (nodes / links / candidates / apps metrics)
- Recommended Actions panel (up to 4 items, severity-sorted)
- Health Trend Snapshot (4 tiles: health, duplicates, conflicts, dormant)
- Review Flow panel: queue selector + 4-step workflow + action buttons
- Curation Activity timeline (last scan, last memory signal, next scheduled run)
- Source and type breakdown with mini progress bars
- LLM curator panel (`Install.tsx`): per-finding accept/reject, batch accept-all/reject-all, job polling, recovery on reload

### Core problem

The existing UI is a **manual-review-first interface**. Every detected issue surfaces to the user as a call to action. The product flow philosophy must be inverted: the system should handle everything it is confident about automatically, and manual review should be an occasional, deliberate, and rewarding activity — not a daily chore.

---

## Design Direction: Auto-Governance Cockpit

### Governing Principle

> The UI's job is to prove the system is working — not to ask the user to do the system's job.

Manual review should be **rare** (target: 1–5 items per week for a normal user), **explainable** (confidence score + system reasoning always shown), and **always reversible** (undo available on every auto-applied action).

---

## Information Architecture

### Zone 1 — Auto-Applied (read-only, no user action needed)

A single horizontal status strip at the top of the Intelligence Center. Shows what the system handled automatically since the last user visit:

- N memories archived (stale / contradicted below confidence threshold)
- N duplicates merged
- N atomic facts split from long memories
- N candidates promoted to active

**Visual treatment:** Muted emerald-toned pills in a single row. Feels like a status bar, not a to-do list. Collapses to "System applied 12 actions automatically — View log" when the count is high. "View log" links to the audit timeline (Zone 4).

**Empty state:** Hidden entirely — no strip shown when nothing was auto-applied since last visit.

---

### Zone 2 — Needs Human Review

A compact queue of items that scored below the system's auto-confidence threshold. These are cases where:

- Two memories conflict and the system cannot determine which is more recent or accurate
- An importance reassessment targets a precious memory type (user_profile, decision, project_memory)
- A split candidate contains ambiguous fact boundaries
- A contradiction involves a decision memory (system always defers high-stakes conflicts)

**Each queue item shows:**
- Category pill: `conflict` / `duplicate` / `importance` / `split`
- Memory title (truncated to 80 chars)
- Confidence badge with percentage-to-color scale: green (>80%), amber (60–80%), red (<60%)
- Proposed action in plain language: "Archive this as superseded by X"
- Buttons: **Accept** (applies action) / **Skip** (defers, re-queues after 7 days)
- Expand chevron: opens the Conflict Comparison Panel (see below)

**Empty queue state:** Large affirming display with emerald icon.
Text: "System is current. All 1,044 memories are governed."
Last-check timestamp shown below. This is the **expected default state** for a healthy system.

**Navbar badge:** Shows count of pending review items. Zero badge = green. Non-zero = amber.

#### Batch Action Toolbar (above queue when items > 1)

- "Accept all high-confidence (>80%)" — applies all items above threshold
- "Skip all — review later" — defers all items
- "Export review batch" — JSON download for offline review

---

### Zone 3 — Health Metrics (observatory, not actionable)

Reorganization of the existing health widget:

- **Quality score ring gauge** (prominent, left): current 1–100 score with Healthy / Needs Work badge
- **Four supporting metric bars** below the gauge: Risk Control, Reuse Coverage, Link Coverage, Non-archived ratio
- **LLM governance status** as a small inline badge on the score card (not a separate bar)
- **Health Trend tiles** (keep existing 4): health / duplicates / conflicts / dormant. Add 7-day sparkline micro-charts if the backend exposes historical context_quality_events data; otherwise keep static progress bars.

---

### Zone 4 — Curation Timeline (audit trail)

Upgrade of the existing CurationActivity timeline:

- Auto-applied actions shown with a muted `auto` badge
- User-reviewed actions shown with a `reviewed` badge
- Rollup events (episodic → durable promotions) included as timeline entries
- Each entry is **expandable** to show before/after memory content diff
- Each auto-applied entry has an **Undo** button that calls the rollback endpoint using the curator_apply audit rollback metadata already stored in the backend

---

## Conflict Comparison Panel (Drill-down)

Triggered by expanding a conflict item in the review queue. Two-column layout:

```
[Memory A — proposed keep]         [Memory B — proposed archive]
Title: …                           Title: …
Content (highlighted diff)         Content (highlighted diff)
Created: Jun 1                     Created: May 15
Accessed: 47 times                 Accessed: 3 times
Importance: 0.8                    Importance: 0.4
Source: claude                     Source: gemini

System reasoning:
"Memory A is more recent and has higher access frequency.
 Memory B contradicts A on point X. Confidence: 84%"

[ Accept — Archive B ]  [ Swap — Archive A instead ]  [ Keep Both ]  [ Skip ]
```

**Accept / Swap / Keep Both / Skip** — the user is never forced into a binary. Keep Both prevents the system from auto-resolving the conflict in future curator runs until the user explicitly resolves it.

---

## Product Flow: How Manual Review Becomes Rare

1. **Rule curator runs automatically** (systemd timer, ~every 60 min). All rule-based actions (stale archive, candidate promotion, confidence decay) are applied silently.

2. **LLM curator runs** (less frequently; currently manual-triggered from Install.tsx). Output enters a holding queue with confidence scores — it does not immediately surface to the user.

3. **High-confidence findings (>threshold, default 80%) are auto-applied** and written to the audit log. The UI shows them retrospectively in Zone 1.

4. **Low-confidence findings land in the Needs Review queue** (Zone 2). The navbar badge count updates. User reviews at their own pace.

5. **Every auto-applied action is reversible** via the Undo button in the audit timeline (Zone 4). The rollback metadata is already stored in curator_apply audit events.

The user only opens the review queue when they choose to. The system never blocks on user input.

---

## Key Product Decisions

| Decision | Rationale |
|---|---|
| Auto-apply high-confidence curator findings | Reduces daily review burden to near-zero for healthy systems |
| Default confidence threshold 80%, configurable in Settings | User retains control over automation aggressiveness |
| Precious memory types always deferred to review queue | Prevents accidental loss of high-value memories regardless of confidence |
| Keep Both and Swap as alternatives to binary accept/reject | Preserves user trust and control during conflict resolution |
| Contradiction queue items expire to keep-both after 14 days if unreviewed | System never auto-loses contested content |
| Zone 1 strip is read-only and retrospective | Audit trail is not a to-do list |
| Undo on every auto-applied action | Reversibility is required for trust in automation |
| Navbar badge shows pending review count | Makes review burden visible without forcing immediate action |
| Empty queue state is affirming text, not neutral | Reframes the UX from "work remaining" to "system healthy" |

---

## Component Hierarchy (proposed refactor)

The existing `MemoryIntelligenceCenter.tsx` is 1008 lines. Extract:

```
components/dashboard/
  MemoryIntelligenceCenter.tsx       — orchestrator, keeps data fetching
  intelligence/
    AutoAppliedStrip.tsx             — Zone 1 (new)
    ReviewQueue.tsx                  — Zone 2 (replaces ReviewFlow panel)
      ReviewQueueItem.tsx
      ConflictComparisonPanel.tsx    — drill-down (new)
      BatchActionBar.tsx             — (new)
    HealthMetricsPanel.tsx           — Zone 3 (refactor of existing Health widget)
      QualityScoreGauge.tsx          — ring/donut gauge (new)
    CurationTimeline.tsx             — Zone 4 (upgrade of existing TimelineItem)
      TimelineEntry.tsx              — with undo button (new)
```

`Install.tsx` (manual-run panel) stays unchanged below the Intelligence Center. It serves power users who want to trigger curator runs on demand — that is separate from the governance cockpit flow.

---

## Visual Style

**Review queue (Zone 2):** Keep the existing dark zinc/violet severity coloring — it conveys appropriate weight for items requiring human judgment.

**Auto-applied strip (Zone 1):** Muted emerald-zinc treatment (`bg-emerald-950/20 border-emerald-900/40 text-emerald-300`) to signal "done, no action needed."

**Confidence badge color scale:**
- Green: `bg-emerald-500/10 text-emerald-300 border-emerald-700` (>80%)
- Amber: `bg-amber-500/10 text-amber-300 border-amber-700` (60–80%)
- Red: `bg-red-500/10 text-red-300 border-red-700` (<60%)

**Overall page theme:** The warm-beige Claude design language (already applied per TODO.md iteration log) is the page wrapper. The intelligence center widget cards keep the `bg-zinc-900 border-zinc-800` dark treatment as contrast islands within the warmer page background. No change to card-level colors.

**Quality score gauge:** Ring or donut chart using the existing Recharts / shadcn chart.tsx. Score value in the center, Healthy/Needs Work badge below.

---

## Gap Analysis vs. Original Design Spec

The original `ui/MEMORY_INTELLIGENCE_CENTER_DESIGN.md` specified 5 widgets:
NeedsAttention, MemoryHealth, ActivityTimeline, KnowledgeGraphSnapshot, SourceAgentBreakdown.

The production code already exceeds this with: ReviewFlow, Recommendations, TrendSnapshot, CurationActivity, and a full LLM curator panel.

**The gap is not missing widgets. The gap is the product philosophy.**

The spec and the current implementation treat the dashboard as a monitoring tool where users must act on everything surfaced. The proposed upgrade inverts this to a proof-of-governance tool where the system acts and users occasionally supervise — with full visibility and reversibility at every step.

---

# Temporal Memory Architecture

> Produced by designer-1 for the memory-architecture-design team, 2026-06-09.
> Source files reviewed: `memorycore/storage/crud.py`, `memorycore/models.py`, `memorycore/storage/curator.py`, `ITERATION.md` (迭代 27, 31), `README.md`.

---

## Current temporal model: what exists

The current model is a single-axis, soft-expiry system:

```
memory {
  id, type, title, content
  status: active | candidate | stale | archived | contradicted | promoted
  confidence: float [0,1]     # decays over time via curator auto-decay
  importance: float [0,1]
  decay_policy: review | freeze | stable
  valid_from: ISO-8601 | null
  valid_until: ISO-8601 | null   # hard expiry; auto-filtered on search
  created_at, updated_at
}

memory_links {
  source_id -> target_id
  relation_type: supersedes | contradicts | supports | related_to | part_of
}
```

Shipped capabilities (confirmed in ITERATION.md 迭代 27/31, README.md line 424):
- `valid_from`/`valid_until` fields with ISO-8601 validation and timezone enforcement
- Auto-decay: 30-day window, -0.05 confidence per curator cycle, floor 0.10
- `supersedes`/`contradicts` link types exist and generate context-pack warnings
- Episodic rollup: raw episodic memories accumulate → LLM-summarized into durable facts → sources archived

Conflict resolution is **passive**: contradicts/supersedes links trigger warnings in the context pack, but retrieval still surfaces both sides. No "winner picks" logic is enforced at query time. Decay is confidence-based, not state-transition-based.

---

## The gap

The user's stated need is: **newer memories are often more correct during conflicts — reduce manual review burden.**

Three things are missing:

1. **Automatic supersession at write time** — when a new memory semantically contradicts an existing active one, the old one should be demoted automatically, not just linked with a warning.
2. **Retrieval bias toward recency** — `build_context_pack` scores by FTS5 rank, importance, effectiveness, and feedback, but not recency. Recent facts do not rank higher than older ones with equal importance.
3. **Auditability of the demotion chain** — what was superseded, when, and by what must be queryable for rollback and lineage inspection without full deletion.

---

## Proposed architecture: Temporal-First with Governed Auto-Supersession

### Core principle

Treat a memory not as a static record but as the current head of a fact lineage. Each write that touches an existing fact creates a new head and demotes the old one to `superseded` status via an explicit link. No hard deletion. The lineage is always traversable.

### Schema additions (minimal, non-breaking)

```sql
-- Fast-path demotion pointer. Write-once; null = still current head.
ALTER TABLE memories ADD COLUMN superseded_by TEXT REFERENCES memories(id);

-- Ancestry pointer to the original fact in the chain. Null = this is the root.
ALTER TABLE memories ADD COLUMN fact_lineage_root TEXT;
```

No new tables required. Both columns are `ALTER TABLE` additions, fully backward-compatible. `superseded_by` mirrors the `memory_links` supersedes relation but is queryable without a JOIN. `fact_lineage_root` enables "show me the full history of this belief" in one query.

### Status extension

Add one new status value: `superseded`.

Full status state machine:

```
active ──[auto-supersede, score >= threshold]──► superseded   (terminal, excluded from retrieval)
active ──[confidence decay]────────────────────► stale ──[curator]──► archived
active ──[user mark / low-confidence conflict]─► contradicted
superseded                                        (never deleted; traversable via lineage query)
```

`superseded` is excluded from all normal retrieval paths identically to `archived`. Non-active memories are already deleted from the Qdrant vector index (ITERATION.md line 620), so `superseded` records take no vector storage. Rollback = write a new `active` memory that supersedes the superseder.

### Auto-supersession trigger

Location: `memorycore/storage/dedup.py` (or a new `storage/temporal.py`), called after dedup at `memory_add` / `memory_ingest` time.

Logic:

1. Vector search top-5 active memories of the same type against the new content.
2. For each candidate with `cosine_similarity >= auto_supersede_threshold` (default 0.88):
   - Write `memory_link(source=new_id, target=candidate_id, relation_type='supersedes')`.
   - Set `candidate.superseded_by = new_id`, `candidate.status = 'superseded'` in a single transaction.
   - Set `new.fact_lineage_root = candidate.fact_lineage_root or candidate.id`.
3. For candidates with similarity 0.75–0.87: emit a `contradicts` warning link as today. User reviews.
4. Threshold is configurable: `config.yaml: temporal.auto_supersede_threshold: 0.88`.

This means high-confidence semantic duplicates are auto-resolved; ambiguous conflicts still surface for human review. The 0.88 threshold is intentionally conservative to start.

### Retrieval scoring change

Add a `recency_score` component to `build_context_pack` in `memorycore/storage/search.py`:

```python
# Current weights (sum = 1.0):
# 0.40 * text_rank + 0.30 * importance + 0.20 * effectiveness + 0.10 * feedback

# Proposed weights (sum = 1.0):
recency_days = (now - updated_at).days
recency_score = max(0.0, 1.0 - recency_days / 365.0)  # linear decay, floor 0

score = (
    0.35 * text_rank
  + 0.25 * importance
  + 0.20 * effectiveness
  + 0.10 * feedback
  + 0.10 * recency_score
)
```

The recency weight (0.10) is small enough not to flood context with trivially recent but low-quality memories. It can be tuned upward if old memories continue crowding out new ones after Phase B ships. Weight is exposed as a config key: `temporal.recency_weight: 0.10`.

### New MCP tools (additive, no existing signatures changed)

| Tool | Description |
|---|---|
| `memory_lineage(memory_id)` | Return full supersession chain: current record + all ancestors in order. Enables the review UI lineage panel and rollback reasoning. |
| `memory_supersede(old_id, new_id)` | Explicit manual supersession for cases where auto-detection does not fire. Sets link + `superseded_by` + status atomically. |

---

## Tradeoffs

| Decision | Tradeoff |
|---|---|
| `superseded_by` denormalized column | Fast single-column filter at retrieval with no JOIN cost. Risk: drift if link is written without updating the column. Mitigation: single atomic transaction covering both writes. |
| 0.88 cosine threshold default | Conservative; reduces false auto-supersessions at the cost of missing some paraphrased updates. Mitigation: configurable; tune downward if users observe missed supersessions in practice. |
| No hard deletion of superseded records | DB rows grow over time. Mitigation: curator can archive superseded records older than N days; they remain traversable via lineage but hold no Qdrant vector slot. |
| Recency weight 0.10 | Small enough not to destabilize existing ranking behavior. Tune upward if recency signal proves weak in practice. |
| No Graphiti/Zep adoption | Full graph-native temporal engines add significant ops burden and a new dependency stack. Current SQLite + Qdrant + link graph covers the stated need. Defer evaluation until atomic facts + lineage retrieval is validated in production. |

---

## Phased adoption

**Phase A — Data model only (1–2 iterations, low risk, no behavior change):**
- Add `superseded` to `STATUSES` in `models.py`.
- Add `superseded_by` and `fact_lineage_root` columns via `ALTER TABLE` migration.
- Add `memory_lineage` MCP tool (read-only).
- Add recency weight to `build_context_pack` scoring (configurable, default 0.10).
- No auto-supersession fires yet. Existing data is unaffected.

**Phase B — Auto-supersession (2–3 iterations, moderate risk):**
- Implement auto-supersession trigger in `memory_ingest` / `memory_add` pipeline.
- Add `memory_supersede` MCP tool for explicit manual supersession.
- Unit tests: auto-supersede fires at threshold, does not fire below, lineage chain traversal, rollback scenario, no-Qdrant-vector-for-superseded invariant.

**Phase C — Feedback loop and UI (optional, future):**
- Track how often auto-superseded memories are revived by users. If revival rate exceeds 5%, raise threshold.
- Add memory detail page lineage panel (integrates with designer-3's Conflict Comparison Panel).
- Dashboard "Needs Attention" widget surfaces unresolved `contradicts` links (below auto-supersede threshold) for manual review.
- Evaluate Graphiti/Zep if lineage graph grows beyond comfortable SQLite traversal scale (10k+ nodes, multi-hop path queries).

---

## Connection to designer-3 UI design

Phase A's `memory_lineage` tool directly powers designer-3's **Conflict Comparison Panel** (DESIGN.md above): the "Memory A / Memory B" two-column layout can display the full lineage chain and system reasoning (`fact_lineage_root`, `superseded_by`, confidence score, `updated_at` delta). Phase B's auto-supersession feeds Zone 1 (Auto-Applied strip) with supersession events, keeping them out of Zone 2 (Needs Review queue) for high-confidence cases and routing only ambiguous conflicts (0.75–0.87 similarity) into the review queue.
