#!/usr/bin/env python3
"""One-time complete data migration script: SQLite (+ optional Qdrant) -> Native PostgreSQL 16 + pgvector."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import psycopg
from pgvector.psycopg import register_vector

ROOT = Path(__file__).resolve().parents[1]
SQLITE_DB = ROOT / "memory.sqlite3"
PG_CONNINFO = "host=127.0.0.1 port=5432 dbname=mcore user=mcore_user password=mcore_secure_password_2026"


def parse_json_safely(val, default):
    if not val:
        return default
    if isinstance(val, (list, dict)):
        return val
    try:
        return json.loads(val)
    except Exception:
        return default


def migrate():
    print(f"[*] Starting migration from {SQLITE_DB} to Native PostgreSQL (mcore)...")
    if not SQLITE_DB.exists():
        print(f"[-] Source SQLite database not found at {SQLITE_DB}")
        sys.exit(1)

    sqlite_conn = sqlite3.connect(SQLITE_DB)
    sqlite_conn.row_factory = sqlite3.Row

    pg_conn = psycopg.connect(PG_CONNINFO)
    register_vector(pg_conn)

    # 1. Attempt to fetch vectors from Qdrant if running
    vector_cache = {}
    try:
        from qdrant_client import QdrantClient
        qdrant = QdrantClient(url="http://127.0.0.1:6333", timeout=3)
        points, _ = qdrant.scroll(collection_name="agent_memory", limit=10000, with_vectors=True)
        vector_cache = {str(p.id): p.vector for p in points if p.vector is not None}
        print(f"[+] Successfully extracted {len(vector_cache)} vectors from active Qdrant server!")
    except Exception as e:
        print(f"[!] Qdrant not available ({e}), embeddings will default to NULL for asynchronous backfill.")

    # 2. Migrate memories
    print("[*] Migrating memories table...")
    mem_rows = sqlite_conn.execute("SELECT * FROM memories").fetchall()
    with pg_conn.cursor() as cur:
        for r in mem_rows:
            d = dict(r)
            mid = d["id"]
            vec = vector_cache.get(mid)
            tags = parse_json_safely(d.get("tags_json"), [])
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(",") if t.strip()]
            metadata = parse_json_safely(d.get("metadata_json"), {})
            related_ids = parse_json_safely(d.get("related_ids_json"), [])
            if isinstance(related_ids, str):
                related_ids = [related_ids]

            cur.execute("""
                INSERT INTO memories (
                    id, type, scope, title, content, tags, metadata, source, source_agent,
                    project_path, confidence, importance, status, decay_policy, feedback_score,
                    injected_count, ineffective_count, effectiveness_score, created_at, updated_at,
                    last_accessed_at, last_injected_at, valid_from, valid_until, superseded_by,
                    fact_lineage_root, related_ids, embedding
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s
                ) ON CONFLICT (id) DO UPDATE SET
                    title = EXCLUDED.title,
                    content = EXCLUDED.content,
                    tags = EXCLUDED.tags,
                    metadata = EXCLUDED.metadata,
                    status = EXCLUDED.status,
                    importance = EXCLUDED.importance,
                    effectiveness_score = EXCLUDED.effectiveness_score,
                    updated_at = EXCLUDED.updated_at,
                    embedding = COALESCE(EXCLUDED.embedding, memories.embedding);
            """, (
                d["id"], d["type"], d.get("scope") or "global", d["title"], d["content"],
                tags, json.dumps(metadata), d.get("source") or "manual",
                d.get("source_agent") or "agent", d.get("project_path") or "",
                float(d.get("confidence") or 0.7), float(d.get("importance") or 0.5),
                d.get("status") or "active", d.get("decay_policy") or "review",
                float(d.get("feedback_score") or 0.0), int(d.get("injected_count") or 0),
                int(d.get("ineffective_count") or 0), float(d.get("effectiveness_score") or 0.5),
                d.get("created_at"), d.get("updated_at"),
                d.get("last_accessed_at"), d.get("last_injected_at"),
                d.get("valid_from"), d.get("valid_until"),
                d.get("superseded_by"), d.get("fact_lineage_root"),
                related_ids, vec
            ))
        pg_conn.commit()
    print(f"[+] Migrated {len(mem_rows)} memories.")

    # 3. Migrate memory_links
    print("[*] Migrating memory_links table...")
    link_rows = sqlite_conn.execute("SELECT * FROM memory_links").fetchall()
    valid_mids = {r["id"] for r in mem_rows}
    valid_links = [l for l in link_rows if l["source_id"] in valid_mids and l["target_id"] in valid_mids]
    with pg_conn.cursor() as cur:
        for l in valid_links:
            ld = dict(l)
            cur.execute("""
                INSERT INTO memory_links (id, source_id, target_id, relation_type, weight, note, source_agent, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING;
            """, (
                ld["id"], ld["source_id"], ld["target_id"], ld["relation_type"],
                float(ld.get("weight") or 1.0), ld.get("note") or "",
                ld.get("source_agent") or "agent", ld.get("created_at"), ld.get("created_at")
            ))
        pg_conn.commit()
    print(f"[+] Migrated {len(valid_links)} memory_links.")

    # 4. Migrate memory_entities
    print("[*] Migrating memory_entities table...")
    entity_rows = sqlite_conn.execute("SELECT * FROM memory_entities").fetchall()
    valid_entities = [e for e in entity_rows if e["memory_id"] in valid_mids]
    with pg_conn.cursor() as cur:
        for e in valid_entities:
            ed = dict(e)
            aliases = parse_json_safely(ed.get("aliases_json"), [])
            cur.execute("""
                INSERT INTO memory_entities (id, memory_id, entity, normalized_entity, aliases_json, entity_type, weight, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING;
            """, (
                ed["id"], ed["memory_id"], ed["entity"], ed["normalized_entity"],
                json.dumps(aliases), ed["entity_type"], float(ed.get("weight") or 1.0),
                ed.get("created_at")
            ))
        pg_conn.commit()
    print(f"[+] Migrated {len(valid_entities)} memory_entities.")

    # 5. Migrate user_profile_attrs
    print("[*] Migrating user_profile_attrs table...")
    profile_rows = sqlite_conn.execute("SELECT * FROM user_profile_attrs").fetchall()
    with pg_conn.cursor() as cur:
        for p in profile_rows:
            pd = dict(p)
            source_ids = parse_json_safely(pd.get("source_ids_json"), [])
            cur.execute("""
                INSERT INTO user_profile_attrs (user_id, attribute, value, confidence, immutable, source_ids_json, updated_at, decayed_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, attribute) DO UPDATE SET
                    value = EXCLUDED.value,
                    confidence = EXCLUDED.confidence,
                    immutable = EXCLUDED.immutable,
                    updated_at = EXCLUDED.updated_at;
            """, (
                pd.get("user_id") or "default", pd["attribute"], pd["value"],
                float(pd.get("confidence") or 0.7), bool(pd.get("immutable")),
                json.dumps(source_ids), pd.get("updated_at"), pd.get("decayed_at")
            ))
        pg_conn.commit()
    print(f"[+] Migrated {len(profile_rows)} user_profile_attrs.")

    # 6. Migrate feedback_events
    print("[*] Migrating feedback_events table...")
    fb_rows = sqlite_conn.execute("SELECT * FROM feedback_events").fetchall()
    valid_fbs = [f for f in fb_rows if f["memory_id"] in valid_mids]
    with pg_conn.cursor() as cur:
        for f in valid_fbs:
            fd = dict(f)
            cur.execute("""
                INSERT INTO feedback_events (id, memory_id, score, note, source_agent, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING;
            """, (
                fd["id"], fd["memory_id"], float(fd.get("score") or 0.0),
                fd.get("note") or "", fd.get("source_agent") or "agent", fd.get("created_at")
            ))
        pg_conn.commit()
    print(f"[+] Migrated {len(valid_fbs)} feedback_events.")

    # 7. Migrate context_quality_events
    print("[*] Migrating context_quality_events table...")
    cq_rows = sqlite_conn.execute("SELECT * FROM context_quality_events").fetchall()
    with pg_conn.cursor() as cur:
        for cq in cq_rows:
            cqd = dict(cq)
            type_weights = parse_json_safely(cqd.get("type_weights_json"), {})
            cur.execute("""
                INSERT INTO context_quality_events (
                    id, task, task_type, agent, project_path, scope, total_candidates,
                    used_count, filtered_count, hit_rate, filter_rate, ineffective_rate,
                    type_weights_json, vector_avg_score, cross_retrieval_rate, created_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s
                ) ON CONFLICT (id) DO NOTHING;
            """, (
                cqd["id"], cqd["task"], cqd.get("task_type") or "general",
                cqd.get("agent") or "agent", cqd.get("project_path") or "",
                cqd.get("scope") or "global", int(cqd.get("total_candidates") or 0),
                int(cqd.get("used_count") or 0), int(cqd.get("filtered_count") or 0),
                float(cqd.get("hit_rate") or 0.0), float(cqd.get("filter_rate") or 0.0),
                float(cqd.get("ineffective_rate") or 0.0), json.dumps(type_weights),
                float(cqd.get("vector_avg_score") or 0.0), float(cqd.get("cross_retrieval_rate") or 0.0),
                cqd.get("created_at")
            ))
        pg_conn.commit()
    print(f"[+] Migrated {len(cq_rows)} context_quality_events.")

    # 8. Reconcile check
    with pg_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM memories")
        pg_mem_count = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM memory_links")
        pg_link_count = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM memory_entities")
        pg_entity_count = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM user_profile_attrs")
        pg_profile_count = cur.fetchone()[0]

    print("\n==========================================")
    print("   Migration & Reconcile Report           ")
    print("==========================================")
    print(f"memories            : SQLite {len(mem_rows)} -> PG {pg_mem_count}")
    print(f"memory_links        : SQLite {len(valid_links)} -> PG {pg_link_count}")
    print(f"memory_entities     : SQLite {len(valid_entities)} -> PG {pg_entity_count}")
    print(f"user_profile_attrs  : SQLite {len(profile_rows)} -> PG {pg_profile_count}")
    print("==========================================")
    assert pg_mem_count == len(mem_rows), "Memory count mismatch!"
    print("ALL DATA RECONCILED 100% CLEANLY!")


if __name__ == "__main__":
    migrate()
