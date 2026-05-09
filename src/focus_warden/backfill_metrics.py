from datetime import date, datetime
from pathlib import Path
import sqlite3
import json

from .simple_store import SimpleTodoStore


LEGACY_DB_PATH = Path.home() / ".local" / "share" / "focus-warden" / "warden.db"


def backfill_all(store: SimpleTodoStore) -> dict:
    stats = {
        "time_blocks": 0,
        "events": 0,
        "sources": {"task_runs": 0, "warden_tasks": 0, "warden_interruptions": 0},
    }

    stats["sources"]["task_runs"] = backfill_task_runs(store)
    stats["sources"]["warden_tasks"] = backfill_warden_tasks(store)
    stats["sources"]["warden_interruptions"] = backfill_warden_interruptions(store)

    stats["time_blocks"] = sum(stats["sources"].values())
    stats["events"] = stats["time_blocks"]

    return stats


def backfill_task_runs(store: SimpleTodoStore) -> int:
    rows = store.conn.execute(
        """
        SELECT id, plan_task_id, target_date, task_name, started_at, ended_at, duration_seconds
        FROM task_runs
        WHERE started_at IS NOT NULL AND ended_at IS NOT NULL
        ORDER BY started_at ASC
        """
    ).fetchall()

    count = 0
    for row in rows:
        source_id = f"task_run_{row['id']}"
        existing = store.conn.execute(
            "SELECT id FROM time_blocks WHERE source_table = 'task_runs' AND source_id = ?",
            (source_id,),
        ).fetchone()

        if existing:
            continue

        target_date = date.fromisoformat(row["target_date"])
        started = datetime.fromisoformat(row["started_at"])
        ended = datetime.fromisoformat(row["ended_at"])

        store.conn.execute(
            """
            INSERT INTO time_blocks
            (target_date, plan_task_id, block_type, started_at, ended_at, duration_seconds, source, source_table, source_id, metadata_json)
            VALUES (?, ?, 'work', ?, ?, ?, 'backfill', 'task_runs', ?, ?)
            """,
            (
                target_date.isoformat(),
                row["plan_task_id"],
                started.isoformat(timespec="seconds"),
                ended.isoformat(timespec="seconds"),
                row["duration_seconds"],
                source_id,
                json.dumps({"title": row["task_name"]}),
            ),
        )

        store.conn.execute(
            """
            INSERT INTO tracking_events
            (target_date, plan_task_id, event_type, occurred_at, source, source_table, source_id)
            VALUES (?, ?, 'task_started', ?, 'backfill', 'task_runs', ?)
            """,
            (target_date.isoformat(), row["plan_task_id"], started.isoformat(timespec="seconds"), source_id),
        )

        store.conn.execute(
            """
            INSERT INTO tracking_events
            (target_date, plan_task_id, event_type, occurred_at, source, source_table, source_id)
            VALUES (?, ?, 'task_finished', ?, 'backfill', 'task_runs', ?)
            """,
            (target_date.isoformat(), row["plan_task_id"], ended.isoformat(timespec="seconds"), f"{source_id}_end"),
        )

        count += 1

    store.conn.commit()
    return count


def backfill_warden_tasks(store: SimpleTodoStore) -> int:
    if not LEGACY_DB_PATH.exists():
        return 0

    legacy_conn = sqlite3.connect(LEGACY_DB_PATH)
    legacy_conn.row_factory = sqlite3.Row

    rows = legacy_conn.execute(
        """
        SELECT t.id, t.session_id, t.actual_start, t.actual_end, t.actual_minutes, t.title, t.notion_task_id
        FROM tasks t
        INNER JOIN sessions s ON t.session_id = s.id
        WHERE t.actual_start IS NOT NULL AND t.actual_end IS NOT NULL
        ORDER BY t.actual_start ASC
        """
    ).fetchall()

    count = 0
    for row in rows:
        source_id = f"warden_task_{row['id']}"
        existing = store.conn.execute(
            "SELECT id FROM time_blocks WHERE source_table = 'warden_tasks' AND source_id = ?",
            (source_id,),
        ).fetchone()

        if existing:
            continue

        started = datetime.fromisoformat(row["actual_start"])
        ended = datetime.fromisoformat(row["actual_end"])
        target_date = started.date()

        plan_task_id = None
        if row["notion_task_id"]:
            plan_task = store.conn.execute(
                "SELECT id FROM plan_tasks WHERE id = ?",
                (row["notion_task_id"],),
            ).fetchone()
            if plan_task:
                plan_task_id = plan_task["id"]

        store.conn.execute(
            """
            INSERT INTO time_blocks
            (target_date, plan_task_id, block_type, started_at, ended_at, duration_seconds, source, source_table, source_id, metadata_json)
            VALUES (?, ?, 'work', ?, ?, ?, 'backfill', 'warden_tasks', ?, ?)
            """,
            (
                target_date.isoformat(),
                plan_task_id,
                started.isoformat(timespec="seconds"),
                ended.isoformat(timespec="seconds"),
                int((ended - started).total_seconds()),
                source_id,
                json.dumps({"title": row["title"], "notion_id": row["notion_task_id"]}),
            ),
        )

        count += 1

    store.conn.commit()
    legacy_conn.close()
    return count


def backfill_warden_interruptions(store: SimpleTodoStore) -> int:
    if not LEGACY_DB_PATH.exists():
        return 0

    legacy_conn = sqlite3.connect(LEGACY_DB_PATH)
    legacy_conn.row_factory = sqlite3.Row

    rows = legacy_conn.execute(
        """
        SELECT id, session_id, kind, started_at, ended_at, duration_minutes
        FROM interruptions
        WHERE started_at IS NOT NULL AND ended_at IS NOT NULL
        ORDER BY started_at ASC
        """
    ).fetchall()

    count = 0
    for row in rows:
        kind = row["kind"]
        if kind not in ("pause", "call_detected"):
            continue

        source_id = f"warden_interruption_{row['id']}"
        block_type = "pause" if kind == "pause" else "call"

        existing = store.conn.execute(
            "SELECT id FROM time_blocks WHERE source_table = 'warden_interruptions' AND source_id = ?",
            (source_id,),
        ).fetchone()

        if existing:
            continue

        started = datetime.fromisoformat(row["started_at"])
        ended = datetime.fromisoformat(row["ended_at"])
        target_date = started.date()

        store.conn.execute(
            """
            INSERT INTO time_blocks
            (target_date, block_type, started_at, ended_at, duration_seconds, source, source_table, source_id, metadata_json)
            VALUES (?, ?, ?, ?, ?, 'backfill', 'warden_interruptions', ?, ?)
            """,
            (
                target_date.isoformat(),
                block_type,
                started.isoformat(timespec="seconds"),
                ended.isoformat(timespec="seconds"),
                int((ended - started).total_seconds()),
                source_id,
                json.dumps({"kind": kind}),
            ),
        )

        count += 1

    store.conn.commit()
    legacy_conn.close()
    return count
