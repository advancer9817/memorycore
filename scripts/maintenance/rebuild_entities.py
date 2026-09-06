import sqlite3
from memorycore.models import row_to_dict
from memorycore.storage.entities import sync_memory_entities

DB_PATH = "/home/advancer/project/memorycore/memory.sqlite3"

def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    print("Fetching active memories...")
    rows = cursor.execute("SELECT * FROM memories WHERE status='active'").fetchall()
    print(f"Total active memories to rebuild: {len(rows)}")

    rebuilt_count = 0
    for r in rows:
        rec = row_to_dict(r)
        sync_memory_entities(rec, conn=conn)
        rebuilt_count += 1
        if rebuilt_count % 300 == 0:
            conn.commit()
            print(f"Rebuilt {rebuilt_count}/{len(rows)}...")

    conn.commit()

    total_entities = cursor.execute("SELECT count(*) FROM memory_entities").fetchone()[0]
    polluted = cursor.execute(
        "SELECT count(*) FROM memory_entities WHERE entity IN ('extracted', 'rollup', 'atomic_fact') OR entity LIKE 'agent:%'"
    ).fetchone()[0]
    print(f"Done! Remaining total entities: {total_entities}, polluted count: {polluted}")
    conn.close()

if __name__ == "__main__":
    main()
