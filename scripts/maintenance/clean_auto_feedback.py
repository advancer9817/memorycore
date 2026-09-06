import sqlite3
import os

DB_PATH = "/home/advancer/project/memorycore/memory.sqlite3"

def main():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 1. 找出受影响的记忆 ID
    print("Finding affected memories...")
    affected_ids = [
        r[0] for r in cursor.execute(
            "SELECT DISTINCT memory_id FROM feedback_events WHERE note IN ('auto:injected', 'auto:seed')"
        ).fetchall()
    ]
    print(f"Total affected memories: {len(affected_ids)}")

    # 2. 删除 auto:injected 和 auto:seed 的 feedback 事件
    del_count = cursor.execute(
        "DELETE FROM feedback_events WHERE note IN ('auto:injected', 'auto:seed')"
    ).rowcount
    print(f"Deleted feedback events: {del_count}")

    # 3. 清理对应的 audit_events
    del_audit = cursor.execute(
        "DELETE FROM audit_events WHERE event_type='memory_feedback' AND (detail_json LIKE '%auto:injected%' OR detail_json LIKE '%auto:seed%')"
    ).rowcount
    print(f"Deleted audit events: {del_audit}")

    # 4. 重新计算并精确重放受影响记忆的三项指标
    print("Recalculating feedback scores and effectiveness for affected memories...")
    updated_count = 0
    for mid in affected_ids:
        rows = cursor.execute(
            "SELECT score FROM feedback_events WHERE memory_id=? ORDER BY created_at", (mid,)
        ).fetchall()

        if rows:
            avg_score = sum(r[0] for r in rows) / len(rows)
            inj_count = sum(1 for r in rows if r[0] > 0)
            eff_score = 0.5
            for r in rows:
                if r[0] > 0:
                    eff_score = min(1.0, eff_score + 0.05 * r[0])
                elif r[0] < 0:
                    eff_score = max(0.0, eff_score + 0.05 * r[0])
        else:
            avg_score = 0.0
            inj_count = 0
            eff_score = 0.5

        cursor.execute(
            """
            UPDATE memories
            SET feedback_score = ?,
                injected_count = ?,
                effectiveness_score = ?
            WHERE id = ?
            """,
            (float(avg_score), inj_count, round(eff_score, 4), mid),
        )
        updated_count += 1

    conn.commit()
    conn.close()
    print(f"Successfully recalculated and updated {updated_count} memories.")

if __name__ == "__main__":
    main()
