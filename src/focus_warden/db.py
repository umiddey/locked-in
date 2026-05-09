from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path

from .models import Interruption, Session, SessionStatus, Task, TaskStatus

DEFAULT_DB_PATH = "~/.local/share/focus-warden/warden.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    shutdown_deadline TEXT NOT NULL,
    status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    notion_task_id TEXT,
    title TEXT NOT NULL,
    normalized_key TEXT NOT NULL,
    scheduled_start TEXT NOT NULL,
    scheduled_duration_minutes INTEGER NOT NULL,
    actual_start TEXT,
    actual_end TEXT,
    actual_minutes REAL,
    status TEXT NOT NULL,
    FOREIGN KEY(session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS interruptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    duration_minutes REAL,
    FOREIGN KEY(session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS control_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER,
    event_type TEXT NOT NULL,
    payload_json TEXT,
    created_at TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: str | None = None):
        self.path = os.path.expanduser(path or DEFAULT_DB_PATH)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self):
        self.conn.close()

    # --- Sessions ---

    def create_session(self, session: Session) -> int:
        cur = self.conn.execute(
            "INSERT INTO sessions (started_at, shutdown_deadline, status) VALUES (?, ?, ?)",
            (
                session.started_at.isoformat(),
                (session.shutdown_deadline or datetime.now()).isoformat(),
                session.status.value,
            ),
        )
        self.conn.commit()
        return cur.lastrowid

    def update_session(self, session: Session):
        self.conn.execute(
            "UPDATE sessions SET ended_at=?, status=? WHERE id=?",
            (session.ended_at.isoformat() if session.ended_at else None, session.status.value, session.id),
        )
        self.conn.commit()

    def get_active_session(self) -> Session | None:
        row = self.conn.execute(
            "SELECT * FROM sessions WHERE status IN ('active', 'paused') ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        return Session(
            id=row["id"],
            started_at=datetime.fromisoformat(row["started_at"]),
            ended_at=datetime.fromisoformat(row["ended_at"]) if row["ended_at"] else None,
            shutdown_deadline=datetime.fromisoformat(row["shutdown_deadline"]) if row["shutdown_deadline"] else None,
            status=SessionStatus(row["status"]),
        )

    # --- Tasks ---

    def create_task(self, task: Task) -> int:
        cur = self.conn.execute(
            """INSERT INTO tasks
            (session_id, notion_task_id, title, normalized_key, scheduled_start,
             scheduled_duration_minutes, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                task.session_id,
                task.notion_task_id,
                task.title,
                task.normalized_key,
                task.scheduled_start.isoformat() if task.scheduled_start else None,
                task.scheduled_duration_minutes,
                task.status.value,
            ),
        )
        self.conn.commit()
        return cur.lastrowid

    def update_task(self, task: Task):
        self.conn.execute(
            """UPDATE tasks
            SET actual_start=COALESCE(?, actual_start),
                actual_end=COALESCE(?, actual_end),
                actual_minutes=COALESCE(?, actual_minutes),
                status=?
            WHERE id=?""",
            (
                task.actual_start.isoformat() if task.actual_start else None,
                task.actual_end.isoformat() if task.actual_end else None,
                task.actual_minutes,
                task.status.value,
                task.id,
            ),
        )
        self.conn.commit()

    # --- Interruptions ---

    def create_interruption(self, interruption: Interruption) -> int:
        cur = self.conn.execute(
            "INSERT INTO interruptions (session_id, kind, started_at) VALUES (?, ?, ?)",
            (
                interruption.session_id,
                interruption.kind,
                interruption.started_at.isoformat() if interruption.started_at else None,
            ),
        )
        self.conn.commit()
        return cur.lastrowid

    def update_interruption(self, interruption: Interruption):
        self.conn.execute(
            "UPDATE interruptions SET ended_at=?, duration_minutes=? WHERE id=?",
            (
                interruption.ended_at.isoformat() if interruption.ended_at else None,
                interruption.duration_minutes,
                interruption.id,
            ),
        )
        self.conn.commit()

    # --- Control events ---

    def log_control_event(self, session_id: int | None, event_type: str, payload: str | None = None):
        self.conn.execute(
            "INSERT INTO control_events (session_id, event_type, payload_json, created_at) VALUES (?, ?, ?, ?)",
            (session_id, event_type, payload, datetime.now().isoformat()),
        )
        self.conn.commit()
