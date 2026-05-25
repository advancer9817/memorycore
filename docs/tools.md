# MCP Tool Reference

All 23 tools exposed by `local-memory-mcp` via the MCP protocol.
Tools are grouped by functional area. Every tool returns JSON.
Errors are caught by `@_safe_tool` and returned as `{"error": "..."}`.

---

## Memory CRUD

### `memory_add`

Add a structured memory record to local SQLite memory.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `type` | `str` | **required** | Memory type (see [Memory Types](#memory-types)) |
| `title` | `str` | **required** | Short descriptive title |
| `content` | `str` | **required** | Full memory body |
| `scope` | `str` | `"global"` | Isolation scope (e.g. project name) |
| `tags` | `list[str]\|str\|None` | `None` | Searchable tags |
| `source` | `str` | `"manual"` | Source label |
| `source_agent` | `str` | `"agent"` | Agent identifier |
| `project_path` | `str` | `""` | Absolute path for project-scoped memories |
| `confidence` | `float` | `0.70` | Confidence score 0.0–1.0 |
| `importance` | `float` | `0.50` | Importance score 0.0–1.0 |
| `status` | `str` | `"active"` | Initial status (see [Statuses](#statuses)) |
| `decay_policy` | `str` | `"review"` | Decay policy |
| `related_ids` | `list[str]\|str\|None` | `None` | IDs of related records |
| `metadata` | `dict\|None` | `None` | Arbitrary key-value metadata |

**Returns:** Full memory record dict.

---

### `memory_get`

Get one memory record by ID.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `id` | `str` | **required** | Memory record UUID |

**Returns:** Memory record dict, or `null` if not found.

---

### `memory_update`

Update an existing memory record's fields. Only provided (non-`None`) fields are changed.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `id` | `str` | **required** | Memory record UUID |
| `content` | `str\|None` | `None` | New content text |
| `title` | `str\|None` | `None` | New title |
| `status` | `str\|None` | `None` | New status |
| `confidence` | `float\|None` | `None` | New confidence 0.0–1.0 |
| `importance` | `float\|None` | `None` | New importance 0.0–1.0 |

**Returns:** Updated memory record dict, or `{"error": "..."}` if not found.

---

### `memory_update_status`

Shortcut to change only the status of a memory record.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `id` | `str` | **required** | Memory record UUID |
| `status` | `str` | **required** | New status (see [Statuses](#statuses)) |

**Returns:** Updated memory record dict.

---

### `memory_list_recent`

List recently updated memory records.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | `int` | `10` | Max records to return (capped at 100) |

**Returns:** List of memory record dicts, ordered by `updated_at` desc.

---

### `memory_feedback`

Record whether a retrieved memory helped. Adjusts `feedback_score` and `effectiveness_score`.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `id` | `str` | **required** | Memory record UUID |
| `score` | `float` | **required** | Feedback score −10 to 10 (negative = unhelpful) |
| `note` | `str` | `""` | Optional explanation |
| `source_agent` | `str` | `"agent"` | Agent providing feedback |

**Returns:** `{"feedback_id": str, "memory": dict}`.

---

## Search & Retrieval

### `memory_search`

Search structured memory with SQLite FTS5 plus filters.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | `str` | `""` | Full-text search query |
| `types` | `list[str]\|str\|None` | `None` | Filter by memory type(s) |
| `scope` | `str` | `""` | Filter by scope (also matches `global`) |
| `project_path` | `str` | `""` | Filter by project path (also matches `""`) |
| `tags` | `list[str]\|str\|None` | `None` | Filter by tag(s) |
| `status` | `str` | `"active"` | Filter by status |
| `limit` | `int` | `10` | Max results (capped at 100) |

**Returns:** List of memory record dicts, ranked by importance / effectiveness / feedback.

---

### `memory_context`

Return a compact context pack for a task, grouped by memory class. Intended for injection into agent prompts.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `task` | `str` | **required** | Task description (used for FTS search) |
| `agent` | `str` | `"agent"` | Agent name (included in output header) |
| `project_path` | `str` | `""` | Project path filter |
| `scope` | `str` | `"global"` | Scope filter |
| `token_budget` | `int` | `2000` | Approximate token budget for the context text |

**Returns:** `{"context": str, "records": [...], "used_ids": [...], "warnings": [...], "quality": {...}, "sections": [...], "trace": {...}}`.

---

### `memory_timeline`

Return decision/timeline/feedback memories in chronological order.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | `str` | `""` | FTS filter query |
| `scope` | `str` | `""` | Scope filter |
| `limit` | `int` | `20` | Max records |

**Returns:** List of memory record dicts sorted by `created_at` asc.

---

## Vector Search (requires `[vector]` extra)

### `memory_vector_search`

Semantic search via Qdrant vector store (nomic-embed-text embeddings).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | `str` | **required** | Natural language search query |
| `top_k` | `int` | `10` | Maximum results to return |
| `score_threshold` | `float` | `0.0` | Minimum cosine similarity (0.0 = no filter) |

**Returns:** List of `{"id", "score", "text", "payload"}` dicts sorted by score desc.
Degraded response `[{"degraded": true, "reason": "..."}]` when Qdrant is unavailable.

---

### `memory_vector_status`

Return Qdrant vector store status.

**Returns:** `{"available": bool, "provider": str, "indexed_records": int, "total_records": int, ...}`.
Returns `{"available": false, "degraded": true, "reason": "..."}` when Qdrant is unavailable.

---

## Links & Warnings

### `memory_link_add`

Create a directed link between two memories. Upserts on `(source_id, target_id, relation_type)`.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `source_id` | `str` | **required** | Source memory UUID |
| `target_id` | `str` | **required** | Target memory UUID |
| `relation_type` | `str` | `"related_to"` | One of: `related_to`, `supersedes`, `contradicts`, `supports`, `part_of` |
| `weight` | `float` | `1.0` | Link strength 0.0–1.0 |
| `note` | `str` | `""` | Human-readable annotation |
| `source_agent` | `str` | `"agent"` | Agent creating the link |

**Returns:** The created/updated link record dict.

---

### `memory_link_query`

Return all links connected to a memory.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `memory_id` | `str` | **required** | Memory UUID to query |
| `direction` | `str` | `"both"` | `"outgoing"`, `"incoming"`, or `"both"` |
| `relation_type` | `str` | `""` | Filter by relation type (empty = all) |
| `limit` | `int` | `50` | Max links per direction |

**Returns:** `{"memory_id": str, "outgoing": [...], "incoming": [...], "total": int}`.

---

### `memory_warnings`

Return active `contradicts`/`supersedes` warnings for a set of memory IDs.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `memory_ids` | `list[str]` | **required** | Memory UUIDs to check |
| `min_weight` | `float` | `0.4` | Minimum link weight to include |
| `max_warnings` | `int` | `5` | Maximum warnings to return |

**Returns:** List of `{"source_id", "target_id", "relation_type", "severity", "weight", "reason"}` dicts, sorted by severity then weight desc.

---

## Curator

### `memory_consolidate`

Detect duplicate/stale candidates. v0 is report-only.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `dry_run` | `bool` | `true` | Always true in v0; no changes applied |
| `limit` | `int` | `50` | Max records to scan |

**Returns:** `{"dry_run": true, "duplicate_title_groups": [...], "low_feedback_candidates": [...], ...}`.

---

### `memory_curator_report`

Full curator analysis with optional lifecycle changes.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `dry_run` | `bool` | `true` | If `false`, marks stale/archived records |
| `limit` | `int` | `500` | Max records to scan |
| `stale_after_days` | `int` | `60` | Days of inactivity before marking stale |
| `archive_after_days` | `int` | `120` | Days stale before archiving |

**Returns:** `{"dry_run": bool, "scanned": int, "duplicate_title_groups": [...], "stale_candidates": [...], "archive_candidates": [...], "actions": [...], "summary": {...}}`.

---

## Ingest Pipeline (requires `[extraction]` extra)

### `memory_ingest`

Extract facts from a conversation and write deduplicated candidates to SQLite.
Pipeline: DeepSeek LLM extraction → Qdrant dedup → SQLite candidate.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `messages` | `list[dict]` | **required** | `[{"role": "user"\|"assistant", "content": "..."}]` |
| `user_id` | `str` | `"default"` | User scope for vector search filters |
| `agent_id` | `str` | `"agent"` | Agent that produced the conversation |
| `timeout_s` | `int` | `120` | Hard timeout in seconds |

**Returns:** `{"added": int, "updated": int, "skipped": int, "errors": int, "elapsed_s": float, "extraction_elapsed_s": float, "degraded": bool}`.
On timeout or pipeline failure: `degraded: true` with a `reason` field.

---

## Audit

### `memory_audit_log`

Return audit events for memory writes, updates, and status changes.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `memory_id` | `str\|None` | `None` | Filter by memory UUID |
| `event_type` | `str\|None` | `None` | e.g. `memory_add`, `memory_update`, `memory_status_change` |
| `limit` | `int` | `50` | Max events (capped at 500) |

**Returns:** List of audit event dicts ordered by `created_at` desc.

---

## Agent Mailbox

### `agent_send`

Send a message from one agent to another. Use `to_agent="*"` to broadcast.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `from_agent` | `str` | **required** | Sender agent identifier |
| `to_agent` | `str` | **required** | Recipient, or `"*"` to broadcast to all online/idle agents |
| `subject` | `str` | **required** | Message subject line |
| `body` | `str` | `""` | Message body text |
| `priority` | `str` | `"normal"` | `low`, `normal`, `high`, or `urgent` |
| `metadata` | `dict\|None` | `None` | Optional key-value metadata |
| `ttl_seconds` | `int\|None` | `None` | Message expires after this many seconds |

**Returns:** Message record dict, or `{"broadcast": true, "sent_to": [...], "count": int}`.

---

### `agent_inbox`

Retrieve messages for an agent.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `agent_id` | `str` | **required** | The agent whose inbox to read |
| `status` | `str` | `""` | `"unread"`, `"read"`, or `""` for all |
| `mark_read` | `bool` | `false` | Mark returned unread messages as read |
| `limit` | `int` | `50` | Max messages (capped at 500) |

**Returns:** List of message dicts, newest first.

---

### `agent_messages_cleanup`

Delete all expired agent messages.

**Returns:** `{"deleted": int}`.

---

## Agent Presence

### `agent_presence_update`

Update an agent's presence status (heartbeat).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `agent_id` | `str` | **required** | Agent identifier |
| `status` | `str` | `"online"` | `online`, `idle`, `busy`, or `offline` |
| `metadata` | `dict\|None` | `None` | Optional metadata (e.g. current task) |

**Returns:** Updated presence record dict.

---

### `agent_presence_list`

List agent presence entries.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `status` | `str` | `""` | Filter by presence status (`""` = all) |
| `limit` | `int` | `100` | Max entries (capped at 500) |

**Returns:** List of presence dicts, most recently seen first.

---

## Reference

### Memory Types

| Type | Purpose |
|------|---------|
| `user_profile` | User preferences, background, expertise |
| `project_memory` | Project facts, decisions, context |
| `environment_fact` | Environment/toolchain facts |
| `agent_architecture` | Agent design and capability notes |
| `decision` | Architectural or design decisions |
| `timeline_event` | Timestamped events |
| `episodic_memory` | Specific past interactions |
| `feedback` | Feedback on past actions |
| `skill_candidate` | Candidate skills for promotion |

### Statuses

| Status | Meaning |
|--------|---------|
| `active` | In use, appears in search results |
| `stale` | Not recently accessed, low importance |
| `archived` | Long-term storage, excluded from search |
| `contradicted` | Superseded by a newer record |
| `promoted` | Skill candidate that was promoted |
| `candidate` | Newly ingested, pending review |
