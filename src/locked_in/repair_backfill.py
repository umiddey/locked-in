from datetime import datetime
from pathlib import Path
import sqlite3

from .simple_store import SimpleTodoStore


LEGACY_DB_PATH = Path.home() / ".local" / "share" / "locked-in" / "warden.db"


def repair_backfill_task_mapping(store: SimpleTodoStore) -> dict:
    """Repair existing backfilled time_blocks by attaching plan_task_id where possible."""

    if not LEGACY_DB_PATH.exists():
        return {"repaired": 0, "reason": "No legacy DB found"}

    legacy_conn = sqlite3.connect(LEGACY_DB_PATH)
    legacy_conn.row_factory = sqlite3.Row

    # Get all backfilled blocks that lack plan_task_id
    rows = store.conn.execute(
        """
        SELECT id, source_table, source_id, target_date, started_at
        FROM time_blocks
        WHERE source_table IN ('warden_tasks', 'task_runs')
          AND plan_task_id IS NULL
          AND block_type = 'work'
        """
    ).fetchall()

    repaired = 0

    for row in rows:
        source_table = row["source_table"]
        source_id = row["source_id"]

        notion_id = None
        if source_table == "warden_tasks":
            # Extract warden task ID from source_id like "warden_task_123"
            warden_task_id = int(source_id.split("_")[-1])
            legacy_row = legacy_conn.execute(
                "SELECT notion_task_id FROM tasks WHERE id = ?",
                (warden_task_id,),
            ).fetchone()
            if legacy_row:
                notion_id = legacy_row["notion_task_id"]
        elif source_table == "task_runs":
            # For task_runs, we need to look at the original task_run row
            # Extract task_run ID from source_id like "task_run_123"
            pass

        if notion_id:
            # Try to find matching plan_task
            plan_task = store.conn.execute(
                "SELECT id FROM plan_tasks WHERE id = ?",
                (notion_id,),
            ).fetchone()

            if plan_task:
                store.conn.execute(
                    "UPDATE time_blocks SET plan_task_id = ? WHERE id = ?",
                    (plan_task["id"], row["id"]),
                )
                repaired += 1

    store.conn.commit()
    legacy_conn.close()

    return {"repaired": repaired, "total_candidates": len(rows)}
