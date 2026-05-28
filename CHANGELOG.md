# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.24.0] - 2026-05-28

### Added
- **v3 State Machine** (`storage/curator.py` rewrite):
  - Tiered candidate TTL: episodic 7d, precious types 30d, others 7d (replaces flat 48h window)
  - `stale → active` revival: records injected within 7d with good effectiveness auto-revive
  - `contradicted` auto-archive: no access in 90 days → archived
  - `decay_policy='freeze'`: curator skips all auto-rules entirely
  - `decay_policy='stable'`: stale only when `feedback < -2.0 AND importance < 0.3`; no confidence decay
  - Precious-type protection: `user_profile`/`environment_fact`/`decision`/`project_memory`/`skill_candidate` immune to default stale rules
  - `injected_count >= 3` candidate promotion (evidence-of-utility path)
  - Decay condition adds `injected_count > 0` (never-used records don't decay)
  - `curator_report` returns new `revival_candidates` field
- **20 new tests** in `tests/test_curator_v3.py`

### Changed
- `STATUSES` removes `promoted` (no auto-trigger existed; records map to `active`)
- `rollup.py`: scan includes all `episodic_memory` regardless of `source` field (previously only `source='extraction'`)
- `tests/test_curator.py`: dead_candidate test uses 8-day window (aligns with new 7d TTL)
- `tests/test_temporal.py`: decay helper sets `injected_count=1` (aligns with new decay condition)

## [0.23.0] - 2026-05-28

### Added
- **Unified agent session-end hooks** (`scripts/hooks/lmmcp-ingest.py`): single Python
  script replaces three separate session-end scripts for Claude / Codex / Hermes.
  - `--agent claude`: reads `CLAUDE_SESSION_FILE` or `~/.claude/projects/**/*.jsonl`
  - `--agent codex`: reads `CODEX_SESSION_FILE` or `~/.codex/sessions/**/*.jsonl`
  - `--agent hermes`: reads hook stdin `session_id`, parses Hermes session JSON
  - Calls `memory_ingest` via `curl --max-time 10` fire-and-forget, non-blocking
- **`scripts/setup-hooks.sh`**: unified deployment entry point — writes Claude/Codex/Hermes
  hook configs and auto-cleans stale entries from previous hook scripts.
- **`scripts/connect_agents.py`** updated: `--register-hooks` now deploys the unified
  ingest script for all three agents; Codex `hooks.json` auto-written.

### Removed
- `scripts/hooks/session-end.sh` (replaced by unified `lmmcp-ingest.py`)
- `scripts/hooks/codex-session-end.sh` (replaced by unified `lmmcp-ingest.py`)
- `scripts/hermes/lmmcp-session-end.py` (replaced by unified `lmmcp-ingest.py`)

## [0.22.0] - 2026-05-27

### Added
- **`memory_rollup_report` MCP tool**: scans accumulated `episodic_memory` candidates
  and, when a group reaches threshold (`min_count=30` or age-based `min_age_count`),
  calls an LLM to distill them into durable long-term memories
  (`user_profile`, `environment_fact`, `agent_architecture`, `project_memory`,
  `timeline_event`, `decision`, `feedback`, `skill_candidate`).
  `dry_run=True` returns a plan; `dry_run=False` creates memories and archives sources.
- **`local_memory_mcp/storage/rollup.py`**: new module with `rollup_report()`.
- **CLI `rollup` subcommand**: `python -m local_memory_mcp rollup [--apply] [--force] [--summary-only]`.
- Auto-curator thread now runs `rollup_report(dry_run=False)` before each `curator_report` pass.
- Audit event `memory_rollup_apply` records source/created IDs, trigger reason, proposal count.
- **Tests**: `tests/test_rollup.py` — threshold not met, dry-run proposal, apply + archive,
  small-batch age trigger.

## [0.21.0] - 2026-05-27

### Added
- **Temporal Memory Layer**: `memory_add` now accepts `valid_from` and `valid_until`
  ISO-8601 string fields. Expired memories (`valid_until < now()`) are automatically
  excluded from `memory_search` and `memory_context` results while remaining in the DB.
- **Auto-decay**: `curator_report` now identifies `decay_policy='review'` memories
  not accessed for 30+ days and reduces their `confidence` by 0.05 per curator run
  (floor: 0.10). `dry_run=True` lists candidates without applying changes.
- **`memory_stats` MCP tool**: Returns per-type, per-status, per-agent counts
  plus aggregate confidence/importance/feedback_score averages. Previously only
  accessible via the `/metrics` observability endpoint.
- **Contradiction detection tests**: 3 new tests covering title-key-based
  contradiction candidate detection in `curator_report`.
- **Temporal tests**: 13 new tests in `tests/test_temporal.py`.

### Changed
- `curator_report` summary now includes `auto_decay_candidates` count.
- README tool table updated to list `memory_stats`; tool count updated to 35.



### Added
- **P2 Observability**: `serve --obs-port N` starts a lightweight HTTP sidecar
  with `/health` (JSON status + total record count) and `/metrics` (full stats
  + uptime) endpoints running in a daemon thread alongside the MCP server.
- **P2 Robustness**: `memory_ingest` gains a `timeout_s` parameter (default
  120 s); the ingest pipeline runs in a `ThreadPoolExecutor` and returns
  `degraded=True` on timeout instead of hanging indefinitely.
- **P2 Tests**: 5 new concurrent-write and schema-migration tests
  (`tests/test_concurrent_and_migration.py`) covering 20-thread write storms,
  concurrent read/write interleaving, `schema_version` row creation, and
  `_ensure_column` idempotence.
- `pyyaml>=6.0` added as a runtime dependency.
- Docker deployment assets: `Dockerfile` + `docker-compose.yml` with
  `INSTALL_VECTOR` build-arg for optional Qdrant support.
- `schema_version` table tracks applied migration version in the DB.

### Changed
- **P1-5 Storage split**: `storage.py` (1421 lines) replaced by a proper
  package `storage/` with 8 focused submodules (`db`, `audit`, `crud`,
  `search`, `links`, `curator`, `agents`, `dashboard`). All existing import
  sites unchanged via `storage/__init__.py` re-exports.
- **P1-6 YAML parser**: Removed hand-rolled `_parse_yaml_scalar` /
  `_parse_simple_yaml`; `load_config()` now uses `yaml.safe_load()`.
- **P1-1 Thread-local connections**: SQLite connections are now reused
  per-thread (WAL mode, `busy_timeout=5000 ms`). `managed_conn()` commits /
  rolls back without closing.
- **P1-1 Retry**: `managed_conn()` retries up to 3 times on
  `OperationalError: database is locked` with exponential back-off.
- `vector_store.py` Ollama URL default corrected to port 11434.
- `qdrant-client` moved from runtime `requirements.txt` to optional extra
  `[vector]` — base install has zero heavyweight dependencies.

### Fixed
- `test_vector_sync.py` patch targets updated to `storage.crud._get_vector_store`
  after the storage split.

## [0.19.0] - 2025-XX-XX

> Prior releases were not formally versioned in this file.
> See `git log` for the full history of earlier iterations.
