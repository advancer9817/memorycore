"""Report generation: llm_curator_report, run_llm_curator_incremental, run_llm_curator."""
from __future__ import annotations

import logging
import time as _time
from typing import Any

from .core import (
    _cleanup_reviewed_ids,
    _fetch_active_memories,
    _find_candidate_pairs,
    _get_vector_store,
    _load_extraction_config,
    _mark_reviewed,
)
from .judges import (
    _find_link_candidates,
    _llm_discover_links,
    _llm_judge_contradictions,
    _llm_judge_duplicates,
)

logger = logging.getLogger(__name__)


def llm_curator_report(
    config: dict[str, Any] | None = None,
    limit: int = 10000,
    sim_threshold: float | None = None,
) -> dict[str, Any]:
    """Run LLM-enhanced curation analysis. Returns structured report (no writes)."""
    t_start = _time.monotonic()
    from memorycore.models import load_config
    full_config = config or load_config()
    cfg = full_config.get("llm_curator", {})

    batch_size = cfg.get("batch_size", 10)
    content_max_chars = cfg.get("content_max_chars", 2000)
    prompt_style = cfg.get("prompt_style", "aggressive")
    effective_sim = sim_threshold if sim_threshold is not None else cfg.get("sim_threshold", 0.60)
    max_dedup = cfg.get("max_dedup_pairs", 200)
    max_contra = cfg.get("max_contradiction_pairs", 200)

    errors: list[str] = []
    timing: dict[str, int] = {}
    diagnostics: dict[str, Any] = {
        "total_memories_fetched": 0,
        "memories_after_cooldown_filter": 0,
        "dedup_pairs_found": 0,
        "dedup_llm_calls": 0,
        "contradiction_pairs_found": 0,
        "contradiction_llm_calls": 0,
        "importance_candidates": 0,
        "importance_skipped_keep": 0,
        "split_candidates_checked": 0,
    }

    try:
        llm_config = _load_extraction_config(full_config)
        curator_temp = cfg.get("temperature", 0.6)
        llm_config.temperature = curator_temp
    except Exception as exc:
        return {"errors": [f"LLM config load failed: {exc}"], "semantic_duplicates": [],
                "contradictions": [], "importance_reassessments": []}

    try:
        vs = _get_vector_store(full_config)
        vs_available = getattr(vs, "available", False)
    except Exception as exc:
        vs_available = False
        errors.append(f"Vector store unavailable: {exc}")

    memories = _fetch_active_memories(limit)
    diagnostics["total_memories_fetched"] = len(memories)
    if not memories:
        return {"errors": errors, "diagnostics": diagnostics, "semantic_duplicates": [], "contradictions": [],
                "importance_reassessments": []}

    _cleanup_reviewed_ids()

    all_evaluated_ids: set[str] = set()

    # --- Unified vector scan -> dedup + contradiction ---
    semantic_duplicates: list[dict] = []
    contradictions: list[dict] = []

    if vs_available:
        try:
            t0 = _time.monotonic()
            all_pairs = _find_candidate_pairs(vs, memories, effective_sim)
            timing["vector_search_ms"] = int((_time.monotonic() - t0) * 1000)

            dup_pairs = [p for p in all_pairs if p[2] >= effective_sim][:max_dedup]
            contra_pairs = [p for p in all_pairs if p[2] >= effective_sim * 0.8][:max_contra]
            diagnostics["dedup_pairs_found"] = len(dup_pairs)
            diagnostics["contradiction_pairs_found"] = len(contra_pairs)
        except Exception as exc:
            dup_pairs = []
            contra_pairs = []
            errors.append(f"Vector scan failed: {exc}")
            logger.error("vector scan error: %s", exc, exc_info=True)

        if dup_pairs:
            try:
                t0 = _time.monotonic()
                diagnostics["dedup_llm_calls"] = len(dup_pairs) // batch_size + (1 if len(dup_pairs) % batch_size else 0)
                semantic_duplicates, dedup_ids = _llm_judge_duplicates(
                    dup_pairs, llm_config, batch_size=batch_size,
                    content_max_chars=content_max_chars, prompt_style=prompt_style,
                    config=full_config)
                all_evaluated_ids.update(dedup_ids)
                timing["dedup_llm_ms"] = int((_time.monotonic() - t0) * 1000)
            except Exception as exc:
                errors.append(f"Semantic dedup failed: {exc}")
                logger.error("semantic dedup error: %s", exc, exc_info=True)

        if contra_pairs:
            try:
                t0 = _time.monotonic()
                diagnostics["contradiction_llm_calls"] = len(contra_pairs) // batch_size + (1 if len(contra_pairs) % batch_size else 0)
                contradictions, contra_ids = _llm_judge_contradictions(
                    contra_pairs, llm_config, batch_size=batch_size,
                    content_max_chars=content_max_chars, prompt_style=prompt_style,
                    config=full_config)
                all_evaluated_ids.update(contra_ids)
                timing["contradiction_llm_ms"] = int((_time.monotonic() - t0) * 1000)
            except Exception as exc:
                errors.append(f"Contradiction detection failed: {exc}")
                logger.error("contradiction detection error: %s", exc, exc_info=True)
    else:
        errors.append("Vector store not available — skipping semantic dedup and contradiction detection")

    # --- Importance re-evaluation ---
    importance_reassessments: list[dict] = []

    # --- Link discovery (knowledge graph) ---
    link_discoveries: list[dict] = []
    if vs_available:
        max_link = cfg.get("max_link_pairs", 100)
        try:
            t0 = _time.monotonic()
            link_pairs = _find_link_candidates(vs, memories, effective_sim, max_pairs=max_link)
            if link_pairs:
                link_discoveries, link_ids = _llm_discover_links(
                    link_pairs, llm_config, batch_size=batch_size,
                    content_max_chars=content_max_chars, prompt_style=prompt_style,
                    config=full_config)
                all_evaluated_ids.update(link_ids)
                _mark_reviewed(list(link_ids), review_type="llm_link_discovery")
            timing["link_discovery_ms"] = int((_time.monotonic() - t0) * 1000)
        except Exception as exc:
            errors.append(f"Link discovery failed: {exc}")
            logger.error("link discovery error: %s", exc, exc_info=True)

    # --- Long-content split detection ---
    split_candidates: list[dict] = []

    # Full cooldown: mark ALL evaluated memories
    all_evaluated_ids.discard("")
    diagnostics["cooldown_registered"] = len(all_evaluated_ids)
    if all_evaluated_ids:
        _mark_reviewed(list(all_evaluated_ids))

    timing["total_ms"] = int((_time.monotonic() - t_start) * 1000)
    diagnostics["timing"] = timing

    logger.info(
        "[llm-curator] report: memories=%d dedup_pairs=%d contradictions=%d importance=%d links=%d splits=%d errors=%d total_ms=%d",
        diagnostics["total_memories_fetched"],
        diagnostics["dedup_pairs_found"],
        len(contradictions),
        len(importance_reassessments),
        len(link_discoveries),
        len(split_candidates),
        len(errors),
        timing["total_ms"],
    )

    return {
        "semantic_duplicates": semantic_duplicates,
        "contradictions": contradictions,
        "importance_reassessments": importance_reassessments,
        "link_discoveries": link_discoveries,
        "split_candidates": split_candidates,
        "errors": errors,
        "diagnostics": diagnostics,
        "summary": {
            "total_memories": diagnostics["total_memories_fetched"],
            "semantic_duplicates": len(semantic_duplicates),
            "contradictions": len(contradictions),
            "importance_reassessments": len(importance_reassessments),
            "link_discoveries": len(link_discoveries),
            "split_candidates": len(split_candidates),
            "dedup_pairs_found": diagnostics["dedup_pairs_found"],
            "contradiction_pairs_found": diagnostics["contradiction_pairs_found"],
            "importance_candidates": diagnostics["importance_candidates"],
            "importance_skipped_keep": diagnostics["importance_skipped_keep"],
        },
    }


def _batch_report(category: str, findings: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "semantic_duplicates": findings if category == "semantic_duplicates" else [],
        "contradictions": findings if category == "contradictions" else [],
        "importance_reassessments": findings if category == "importance_reassessments" else [],
        "split_candidates": findings if category == "split_candidates" else [],
    }


def _summary_from_counts(counts: dict[str, int], total_memories: int = 0) -> dict[str, int]:
    return {
        "total_memories": total_memories,
        "semantic_duplicates": counts.get("semantic_duplicates", 0),
        "contradictions": counts.get("contradictions", 0),
        "importance_reassessments": counts.get("importance_reassessments", 0),
        "link_discoveries": counts.get("link_discoveries", 0),
        "split_candidates": counts.get("split_candidates", 0),
        "decisions_created": counts.get("decisions_created", 0),
        "batches_completed": counts.get("batches_completed", 0),
        "batches_failed": counts.get("batches_failed", 0),
    }


def run_llm_curator_incremental(
    job_id: str,
    config: dict[str, Any] | None = None,
    limit: int = 200,
    sim_threshold: float | None = None,
    apply: bool = False,
    rebuild_vectors: bool = True,
) -> dict[str, Any]:
    """Run LLM curation and persist decisions after each completed batch."""
    from memorycore.storage.llm_curator_jobs import _diag
    import os as _os
    t_start = _time.monotonic()
    _diag(f"CURATOR_START: job={job_id} pid={_os.getpid()} limit={limit} sim={sim_threshold} apply={apply}")
    from memorycore.models import load_config
    from memorycore.storage.governance import convert_llm_findings_to_decisions
    from memorycore.storage.llm_curator_jobs import (
        finish_llm_curator_batch,
        start_llm_curator_batch,
        update_llm_curator_job,
    )

    full_config = config or load_config()
    cfg = full_config.get("llm_curator", {})
    batch_size = max(1, int(cfg.get("batch_size", 10)))
    content_max_chars = int(cfg.get("content_max_chars", 2000))
    prompt_style = cfg.get("prompt_style", "aggressive")
    effective_sim = sim_threshold if sim_threshold is not None else float(cfg.get("sim_threshold", 0.60))
    max_dedup = int(cfg.get("max_dedup_pairs", 200))
    max_contra = int(cfg.get("max_contradiction_pairs", 200))
    errors: list[str] = []
    counts: dict[str, int] = {}
    all_evaluated_ids: set[str] = set()

    _owner_pid = _os.getpid()

    def progress(stage: str, extra: dict[str, Any] | None = None) -> None:
        payload = {"stage": stage, "elapsed_ms": int((_time.monotonic() - t_start) * 1000), "pid": _owner_pid, **(extra or {})}
        update_llm_curator_job(job_id, progress=payload, summary=_summary_from_counts(counts, counts.get("total_memories", 0)), errors=errors)

    def persist_batch(stage: str, batch_index: int, category: str, candidates: list[Any], run_batch: Any) -> None:
        batch = start_llm_curator_batch(job_id, stage, batch_index, candidate_count=len(candidates))
        progress(stage, {"batch_index": batch_index, "candidate_count": len(candidates)})
        try:
            result = run_batch(candidates)
            if isinstance(result, tuple):
                findings, evaluated_ids = result
                all_evaluated_ids.update(evaluated_ids)
            else:
                findings = result
            report = _batch_report(category, findings)
            governance = convert_llm_findings_to_decisions(
                report,
                auto_apply=apply,
                curator_job_id=job_id,
                curator_batch_id=batch["id"],
            )
            decisions_count = int(governance.get("decisions_created", 0))
            counts[category] = counts.get(category, 0) + len(findings)
            counts["decisions_created"] = counts.get("decisions_created", 0) + decisions_count
            counts["batches_completed"] = counts.get("batches_completed", 0) + 1
            finish_llm_curator_batch(batch["id"], finding_count=len(findings), decision_count=decisions_count)
            progress(stage, {"batch_index": batch_index, "decision_count": decisions_count})
        except Exception as exc:
            message = f"{stage} batch {batch_index} failed: {exc}"
            errors.append(message)
            counts["batches_failed"] = counts.get("batches_failed", 0) + 1
            finish_llm_curator_batch(batch["id"], status="failed", error={"message": str(exc)})
            logger.error("[llm-curator job %s] %s", job_id, message, exc_info=True)
            progress(stage, {"batch_index": batch_index, "error": str(exc)})

    try:
        llm_config = _load_extraction_config(full_config)
        llm_config.temperature = cfg.get("temperature", 0.6)
    except Exception as exc:
        errors.append(f"LLM config load failed: {exc}")
        update_llm_curator_job(job_id, status="failed", errors=errors, finished=True)
        return {"errors": errors, "summary": _summary_from_counts(counts)}

    try:
        vs = _get_vector_store(full_config)
        vs_available = getattr(vs, "available", False)
    except Exception as exc:
        vs_available = False
        errors.append(f"Vector store unavailable: {exc}")

    memories = _fetch_active_memories(limit)
    counts["total_memories"] = len(memories)
    if not memories:
        summary = _summary_from_counts(counts)
        update_llm_curator_job(job_id, status="done", summary=summary, errors=errors, finished=True)
        return {"errors": errors, "summary": summary}

    _cleanup_reviewed_ids()
    progress("vector_scan")
    _diag(f"STAGE: vector_scan started, {len(memories)} memories loaded")

    if vs_available:
        try:
            all_pairs = _find_candidate_pairs(vs, memories, effective_sim)
            dup_pairs = [p for p in all_pairs if p[2] >= effective_sim][:max_dedup]
            contra_pairs = [p for p in all_pairs if p[2] >= effective_sim * 0.8][:max_contra]
            counts["dedup_pairs_found"] = len(dup_pairs)
            counts["contradiction_pairs_found"] = len(contra_pairs)
            progress("vector_scan", {"dedup_pairs_found": len(dup_pairs), "contradiction_pairs_found": len(contra_pairs)})
        except Exception as exc:
            dup_pairs = []
            contra_pairs = []
            errors.append(f"Vector scan failed: {exc}")
            logger.error("vector scan error: %s", exc, exc_info=True)
        _diag(f"STAGE: dedup starting, {len(dup_pairs)} pairs, batch_size={batch_size}")
        for batch_index, start in enumerate(range(0, len(dup_pairs), batch_size)):
            candidates = dup_pairs[start:start + batch_size]
            persist_batch(
                "dedup",
                batch_index,
                "semantic_duplicates",
                candidates,
                lambda batch: _llm_judge_duplicates(batch, llm_config, batch_size=len(batch), content_max_chars=content_max_chars, prompt_style=prompt_style, config=full_config),
            )
        _diag(f"STAGE: contradiction starting, {len(contra_pairs)} pairs")
        for batch_index, start in enumerate(range(0, len(contra_pairs), batch_size)):
            candidates = contra_pairs[start:start + batch_size]
            persist_batch(
                "contradiction",
                batch_index,
                "contradictions",
                candidates,
                lambda batch: _llm_judge_contradictions(batch, llm_config, batch_size=len(batch), content_max_chars=content_max_chars, prompt_style=prompt_style, config=full_config),
            )
    else:
        errors.append("Vector store not available — skipping semantic dedup and contradiction detection")

    if all_evaluated_ids:
        _mark_reviewed(list(all_evaluated_ids))

    if rebuild_vectors:
        try:
            from memorycore.storage import memory_rebuild_vectors
            memory_rebuild_vectors()
        except Exception as exc:
            errors.append(f"Vector rebuild failed: {exc}")

    summary = _summary_from_counts(counts)
    status = "failed" if errors and counts.get("decisions_created", 0) == 0 else "succeeded" if counts.get("decisions_created", 0) else "done"
    _diag(f"CURATOR_END: job={job_id} status={status} elapsed={int(_time.monotonic()-t_start)}s decisions={counts.get('decisions_created',0)} errors={len(errors)}")
    update_llm_curator_job(job_id, status=status, progress={"stage": "finished", "pid": _owner_pid}, summary=summary, errors=errors, finished=True)
    try:
        from memorycore.storage.audit import log_audit_event
        log_audit_event("llm_curator_run", agent="llm_curator", detail={"job_id": job_id, "incremental": True, "summary": summary, "errors": errors})
    except Exception:
        logger.debug("failed to log incremental llm_curator_run audit event", exc_info=True)
    return {"errors": errors, "summary": summary, "status": status}


def run_llm_curator(
    config: dict[str, Any] | None = None,
    limit: int = 200,
    sim_threshold: float | None = None,
    apply: bool = False,
    rebuild_vectors: bool = True,
) -> dict[str, Any]:
    """Run LLM curation, optionally apply findings, and record run metadata."""
    report = llm_curator_report(config=config, limit=limit, sim_threshold=sim_threshold)
    applied: dict[str, Any] | None = None
    governance: dict[str, Any] | None = None
    try:
        from memorycore.storage.governance import convert_llm_findings_to_decisions

        governance = convert_llm_findings_to_decisions(report, auto_apply=apply)
        report = {**report, "governance": governance}
        if apply:
            applied = {"governance_auto_applied": len(governance.get("auto_applied", []))}
            report = {**report, "applied": applied}
    except Exception as exc:
        logger.warning("governance decision conversion failed: %s", exc)
        report = {**report, "governance_error": str(exc)}

    if rebuild_vectors:
        try:
            from memorycore.storage import memory_rebuild_vectors

            report = {**report, "rebuild_vectors": memory_rebuild_vectors()}
        except Exception as exc:
            report = {**report, "rebuild_vectors_error": str(exc)}

    try:
        from memorycore.storage.audit import log_audit_event

        log_audit_event(
            "llm_curator_run",
            agent="llm_curator",
            detail={
                "dry_run": not apply,
                "summary": report.get("summary", {}),
                "errors": report.get("errors", []),
                "applied": applied,
                "governance": governance,
                "rebuild_vectors_error": report.get("rebuild_vectors_error"),
            },
        )
    except Exception:
        logger.debug("failed to log llm_curator_run audit event", exc_info=True)

    return report
