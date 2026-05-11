from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path


DEFAULT_STORE_PATH = Path.home() / ".local" / "share" / "locked-in" / "simple_todos.db"
LEGACY_JSON_PATH = Path.home() / ".local" / "share" / "locked-in" / "simple_todos.json"
DEFAULT_TASK_DURATION_MINUTES = 30
SESSION_RESET_HOUR = 6

SCHEMA = """
CREATE TABLE IF NOT EXISTS plans (
    target_date TEXT PRIMARY KEY,
    saved_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS plan_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_date TEXT NOT NULL,
    position INTEGER NOT NULL,
    task_name TEXT NOT NULL,
    duration_minutes INTEGER NOT NULL DEFAULT 30,
    completed_at TEXT,
    last_outcome TEXT,
    FOREIGN KEY(target_date) REFERENCES plans(target_date) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS daily_sessions (
    target_date TEXT PRIMARY KEY,
    session_started_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS task_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_task_id INTEGER,
    target_date TEXT NOT NULL,
    task_name TEXT NOT NULL,
    scheduled_start TEXT,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    duration_seconds INTEGER,
    outcome TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions_v2 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_date TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    status TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'local',
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tracking_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_date TEXT NOT NULL,
    session_id INTEGER,
    plan_task_id INTEGER,
    event_type TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    source TEXT NOT NULL,
    metadata_json TEXT,
    source_table TEXT,
    source_id TEXT,
    FOREIGN KEY(session_id) REFERENCES sessions_v2(id),
    FOREIGN KEY(plan_task_id) REFERENCES plan_tasks(id)
);

CREATE TABLE IF NOT EXISTS time_blocks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_date TEXT NOT NULL,
    session_id INTEGER,
    plan_task_id INTEGER,
    block_type TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    duration_seconds INTEGER,
    source TEXT NOT NULL,
    project TEXT,
    category TEXT,
    tags_json TEXT,
    quality_score INTEGER,
    energy_score INTEGER,
    interruption_count INTEGER NOT NULL DEFAULT 0,
    metadata_json TEXT,
    source_table TEXT,
    source_id TEXT,
    FOREIGN KEY(session_id) REFERENCES sessions_v2(id),
    FOREIGN KEY(plan_task_id) REFERENCES plan_tasks(id)
);

CREATE TABLE IF NOT EXISTS task_runtime (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_date TEXT NOT NULL,
    session_id INTEGER,
    plan_task_id INTEGER NOT NULL,
    task_run_id INTEGER,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    paused_at TEXT,
    resumed_at TEXT,
    finished_at TEXT,
    estimated_seconds INTEGER NOT NULL,
    accumulated_pause_seconds INTEGER NOT NULL DEFAULT 0,
    active_work_block_id INTEGER,
    active_pause_block_id INTEGER,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(session_id) REFERENCES sessions_v2(id),
    FOREIGN KEY(plan_task_id) REFERENCES plan_tasks(id),
    FOREIGN KEY(task_run_id) REFERENCES task_runs(id),
    FOREIGN KEY(active_work_block_id) REFERENCES time_blocks(id),
    FOREIGN KEY(active_pause_block_id) REFERENCES time_blocks(id)
);

CREATE INDEX IF NOT EXISTS idx_tracking_events_date_time ON tracking_events(target_date, occurred_at);
CREATE INDEX IF NOT EXISTS idx_tracking_events_task ON tracking_events(plan_task_id, occurred_at);
CREATE INDEX IF NOT EXISTS idx_tracking_events_type ON tracking_events(event_type, occurred_at);
CREATE INDEX IF NOT EXISTS idx_time_blocks_date_start ON time_blocks(target_date, started_at);
CREATE INDEX IF NOT EXISTS idx_time_blocks_task ON time_blocks(plan_task_id, started_at);
CREATE INDEX IF NOT EXISTS idx_time_blocks_type ON time_blocks(block_type, started_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_time_blocks_source_identity ON time_blocks(source_table, source_id) WHERE source_table IS NOT NULL AND source_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_tracking_events_source_identity ON tracking_events(source_table, source_id, event_type) WHERE source_table IS NOT NULL AND source_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_task_runtime ON task_runtime(target_date) WHERE status IN ('running', 'paused');
"""


@dataclass
class PlanTask:
    id: int
    target_date: str
    position: int
    task_name: str
    duration_minutes: int
    completed_at: str | None
    last_outcome: str | None
    description: str | None = None


@dataclass
class TodoPlan:
    target_date: str
    tasks: list[PlanTask]
    saved_at: str


@dataclass
class ScheduleEntry:
    task: PlanTask
    scheduled_start: datetime
    scheduled_end: datetime


@dataclass
class TaskRun:
    id: int
    target_date: str
    task_name: str
    started_at: str
    ended_at: str | None
    duration_seconds: int | None
    outcome: str | None
    notes: str | None


@dataclass
class TaskDraft:
    task_name: str
    duration_minutes: int
    description: str = ""


@dataclass
class EditableTaskDraft:
    task_id: int | None
    task_name: str
    duration_minutes: int
    description: str = ""


@dataclass
class SessionV2:
    id: int
    target_date: str
    started_at: str
    ended_at: str | None
    status: str
    source: str
    notes: str | None
    created_at: str
    updated_at: str


@dataclass
class TrackingEvent:
    id: int
    target_date: str
    session_id: int | None
    plan_task_id: int | None
    event_type: str
    occurred_at: str
    source: str
    metadata_json: str | None
    source_table: str | None
    source_id: str | None


@dataclass
class TimeBlock:
    id: int
    target_date: str
    session_id: int | None
    plan_task_id: int | None
    block_type: str
    started_at: str
    ended_at: str | None
    duration_seconds: int | None
    source: str
    project: str | None
    category: str | None
    tags_json: str | None
    quality_score: int | None
    energy_score: int | None
    interruption_count: int
    metadata_json: str | None
    source_table: str | None
    source_id: str | None


@dataclass
class TaskRuntime:
    id: int
    target_date: str
    session_id: int | None
    plan_task_id: int
    task_run_id: int | None
    status: str
    started_at: str
    paused_at: str | None
    resumed_at: str | None
    finished_at: str | None
    estimated_seconds: int
    accumulated_pause_seconds: int
    active_work_block_id: int | None
    active_pause_block_id: int | None
    source: str
    created_at: str
    updated_at: str

    def compute_eta(self, now: datetime | None = None) -> datetime:
        started = datetime.fromisoformat(self.started_at)
        total_pause = self.accumulated_pause_seconds
        if self.status == "paused" and self.paused_at:
            now = now or datetime.now()
            total_pause += int((now - datetime.fromisoformat(self.paused_at)).total_seconds())
        return started + timedelta(seconds=self.estimated_seconds + total_pause)

    def actual_work_seconds(self, now: datetime | None = None) -> int:
        now = now or datetime.now()
        started = datetime.fromisoformat(self.started_at)
        end = datetime.fromisoformat(self.finished_at) if self.finished_at else now
        wall = int((end - started).total_seconds())
        total_pause = self.accumulated_pause_seconds
        if self.status == "paused" and self.paused_at:
            total_pause += int((now - datetime.fromisoformat(self.paused_at)).total_seconds())
        return max(wall - total_pause, 0)


@dataclass
class RuntimeScheduleEntry:
    task_id: int
    task_name: str
    status: str
    estimated_seconds: int
    actual_start: str | None
    actual_end: str | None
    projected_start: str | None
    projected_end: str | None
    actual_work_seconds: int
    pause_seconds: int
    eta: str | None
    drift_seconds: int


class SimpleTodoStore:
    def __init__(self, path: Path | None = None):
        self.path = path or DEFAULT_STORE_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self._lock = threading.RLock()
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._ensure_columns()
        self._migrate_legacy_json()

    def _ensure_columns(self) -> None:
        self._ensure_column("plan_tasks", "duration_minutes", "INTEGER NOT NULL DEFAULT 30")
        self._ensure_column("plan_tasks", "completed_at", "TEXT")
        self._ensure_column("plan_tasks", "last_outcome", "TEXT")
        self._ensure_column("plan_tasks", "project", "TEXT")
        self._ensure_column("plan_tasks", "category", "TEXT")
        self._ensure_column("plan_tasks", "tags_json", "TEXT")
        self._ensure_column("plan_tasks", "estimate_source", "TEXT")
        self._ensure_column("plan_tasks", "priority", "INTEGER")
        self._ensure_column("plan_tasks", "difficulty", "INTEGER")
        self._ensure_column("plan_tasks", "energy_required", "INTEGER")
        self._ensure_column("plan_tasks", "description", "TEXT")
        self._ensure_column("plan_tasks", "created_at", "TEXT")
        self._ensure_column("plan_tasks", "updated_at", "TEXT")
        self._ensure_column("task_runs", "plan_task_id", "INTEGER")
        self._ensure_column("task_runs", "scheduled_start", "TEXT")
        self._ensure_column("task_runs", "time_block_id", "INTEGER")
        self._ensure_column("task_runs", "project", "TEXT")
        self._ensure_column("task_runs", "category", "TEXT")
        self._ensure_column("task_runs", "tags_json", "TEXT")
        self._ensure_column("task_runs", "quality_score", "INTEGER")
        self._ensure_column("task_runs", "energy_score", "INTEGER")
        self._ensure_column("task_runs", "interruption_count", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_schema_version()
        self.conn.commit()

    def _ensure_column(self, table: str, column: str, ddl: str) -> None:
        columns = {
            row["name"]
            for row in self.conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    def _ensure_schema_version(self) -> None:
        row = self.conn.execute("SELECT value FROM schema_meta WHERE key = 'schema_version'").fetchone()
        if not row:
            self.conn.execute("INSERT INTO schema_meta (key, value) VALUES ('schema_version', '3')")
        else:
            version = int(row["value"])
            if version < 3:
                self.conn.execute("UPDATE schema_meta SET value = '3' WHERE key = 'schema_version'")

    def _migrate_legacy_json(self) -> None:
        plans_exist = self.conn.execute("SELECT COUNT(*) FROM plans").fetchone()[0]
        if plans_exist or not LEGACY_JSON_PATH.exists():
            return
        try:
            raw = json.loads(LEGACY_JSON_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return

        for target_date, payload in raw.get("plans", {}).items():
            saved_at = payload.get("saved_at") or datetime.now().isoformat(timespec="seconds")
            self.conn.execute(
                "INSERT OR REPLACE INTO plans (target_date, saved_at) VALUES (?, ?)",
                (target_date, saved_at),
            )
            for position, task_name in enumerate(payload.get("tasks", [])):
                cleaned = task_name.strip()
                if not cleaned:
                    continue
                self.conn.execute(
                    """
                    INSERT INTO plan_tasks
                    (target_date, position, task_name, duration_minutes)
                    VALUES (?, ?, ?, ?)
                    """,
                    (target_date, position, cleaned, DEFAULT_TASK_DURATION_MINUTES),
                )
        self.conn.commit()

    def get_plan(self, target_date: date) -> TodoPlan | None:
        with self._lock:
            target = target_date.isoformat()
            row = self.conn.execute(
                "SELECT target_date, saved_at FROM plans WHERE target_date = ?",
                (target,),
            ).fetchone()
            if not row:
                return None
            task_rows = self.conn.execute(
                """
                SELECT id, target_date, position, task_name, duration_minutes, completed_at, last_outcome, description
                FROM plan_tasks
                WHERE target_date = ?
                ORDER BY position ASC, id ASC
                """,
                (target,),
            ).fetchall()
            tasks = [
                PlanTask(
                    id=task_row["id"],
                    target_date=task_row["target_date"],
                    position=task_row["position"],
                    task_name=task_row["task_name"],
                    duration_minutes=task_row["duration_minutes"] or DEFAULT_TASK_DURATION_MINUTES,
                    completed_at=task_row["completed_at"],
                    last_outcome=task_row["last_outcome"],
                    description=task_row["description"],
                )
                for task_row in task_rows
            ]
            return TodoPlan(target_date=row["target_date"], tasks=tasks, saved_at=row["saved_at"])

    def has_plan(self, target_date: date) -> bool:
        with self._lock:
            plan = self.get_plan(target_date)
            return bool(plan and plan.tasks)

    def get_latest_plan_date(self, before: date | None = None) -> date | None:
        with self._lock:
            if before is None:
                row = self.conn.execute(
                    """
                    SELECT p.target_date
                    FROM plans p
                    WHERE EXISTS (
                        SELECT 1 FROM plan_tasks t WHERE t.target_date = p.target_date
                    )
                    ORDER BY p.target_date DESC
                    LIMIT 1
                    """,
                ).fetchone()
            else:
                row = self.conn.execute(
                    """
                    SELECT p.target_date
                    FROM plans p
                    WHERE p.target_date < ?
                      AND EXISTS (
                          SELECT 1 FROM plan_tasks t WHERE t.target_date = p.target_date
                      )
                    ORDER BY p.target_date DESC
                    LIMIT 1
                    """,
                    (before.isoformat(),),
                ).fetchone()

            if not row:
                return None
            return date.fromisoformat(row["target_date"])

    def save_plan(self, target_date: date, tasks: list[TaskDraft]) -> TodoPlan:
        with self._lock:
            editable = [
                EditableTaskDraft(
                    task_id=None,
                    task_name=task.task_name,
                    duration_minutes=task.duration_minutes,
                    description=task.description,
                )
                for task in tasks
            ]
            return self.save_plan_rows(target_date, editable)

    def save_plan_rows(
        self,
        target_date: date,
        tasks: list[EditableTaskDraft],
    ) -> TodoPlan:
        with self._lock:
            target = target_date.isoformat()
            cleaned = [
                EditableTaskDraft(
                    task_id=task.task_id,
                    task_name=task.task_name.strip(),
                    duration_minutes=max(int(task.duration_minutes), 1),
                    description=task.description.strip(),
                )
                for task in tasks
                if task.task_name.strip()
            ]
            saved_at = datetime.now().isoformat(timespec="seconds")
            self.conn.execute(
                "INSERT OR REPLACE INTO plans (target_date, saved_at) VALUES (?, ?)",
                (target, saved_at),
            )

            existing_ids = {
                row["id"]
                for row in self.conn.execute(
                    "SELECT id FROM plan_tasks WHERE target_date = ?",
                    (target,),
                ).fetchall()
            }

            kept_ids: set[int] = set()
            for position, task in enumerate(cleaned):
                if task.task_id is not None and task.task_id in existing_ids:
                    self.conn.execute(
                        """
                        UPDATE plan_tasks
                        SET position = ?, task_name = ?, duration_minutes = ?, description = ?
                        WHERE id = ? AND target_date = ?
                        """,
                        (position, task.task_name, task.duration_minutes, task.description or None, task.task_id, target),
                    )
                    kept_ids.add(task.task_id)
                    continue

                cur = self.conn.execute(
                    """
                    INSERT INTO plan_tasks
                    (target_date, position, task_name, duration_minutes, description, completed_at, last_outcome)
                    VALUES (?, ?, ?, ?, ?, NULL, NULL)
                    """,
                    (target, position, task.task_name, task.duration_minutes, task.description or None),
                )
                kept_ids.add(int(cur.lastrowid))

            if existing_ids:
                if kept_ids:
                    placeholders = ",".join("?" for _ in kept_ids)
                    self.conn.execute(
                        f"DELETE FROM plan_tasks WHERE target_date = ? AND id NOT IN ({placeholders})",
                        (target, *sorted(kept_ids)),
                    )
                else:
                    self.conn.execute("DELETE FROM plan_tasks WHERE target_date = ?", (target,))

            self.conn.commit()
            return self.get_plan(target_date)  # type: ignore[return-value]

    def delete_task(self, target_date: date, task_id: int) -> bool:
        with self._lock:
            cur = self.conn.execute(
                "DELETE FROM plan_tasks WHERE id = ? AND target_date = ?",
                (task_id, target_date.isoformat()),
            )
            self.conn.commit()
            return cur.rowcount > 0

    def update_task(self, target_date: date, task_id: int, task_name: str | None = None, duration_minutes: int | None = None, description: str | None = None, position: int | None = None) -> bool:
        with self._lock:
            parts: list[str] = []
            vals: list = []
            if task_name is not None:
                parts.append("task_name = ?")
                vals.append(task_name.strip())
            if duration_minutes is not None:
                parts.append("duration_minutes = ?")
                vals.append(max(int(duration_minutes), 1))
            if description is not None:
                parts.append("description = ?")
                vals.append(description.strip() or None)
            if position is not None:
                parts.append("position = ?")
                vals.append(int(position))
            if not parts:
                return False
            vals.extend([task_id, target_date.isoformat()])
            cur = self.conn.execute(
                f"UPDATE plan_tasks SET {', '.join(parts)} WHERE id = ? AND target_date = ?",
                vals,
            )
            self.conn.commit()
            return cur.rowcount > 0

    def move_task(self, target_date: date, task_id: int, direction: int) -> bool:
        """Move a task up (-1) or down (+1) in position. Swaps with neighbor."""
        with self._lock:
            target = target_date.isoformat()
            rows = self.conn.execute(
                "SELECT id, position FROM plan_tasks WHERE target_date = ? ORDER BY position ASC, id ASC",
                (target,),
            ).fetchall()
            if not rows:
                return False
            idx = next((i for i, r in enumerate(rows) if r["id"] == task_id), None)
            if idx is None:
                return False
            new_idx = idx + direction
            if new_idx < 0 or new_idx >= len(rows):
                return False
            swap_id = rows[new_idx]["id"]
            cur_pos = rows[idx]["position"]
            swap_pos = rows[new_idx]["position"]
            self.conn.execute("UPDATE plan_tasks SET position = ? WHERE id = ?", (swap_pos, task_id))
            self.conn.execute("UPDATE plan_tasks SET position = ? WHERE id = ?", (cur_pos, swap_id))
            self.conn.commit()
            return True

    def ensure_session(self, target_date: date, started_at: datetime | None = None) -> datetime:
        with self._lock:
            target = target_date.isoformat()
            requested_start = started_at or datetime.now()
            existing = self.conn.execute(
                "SELECT session_started_at FROM daily_sessions WHERE target_date = ?",
                (target,),
            ).fetchone()
            if existing:
                session_started_at = datetime.fromisoformat(existing["session_started_at"])
                if self._should_reset_session_start(target_date, session_started_at, requested_start):
                    reset_start = requested_start.isoformat(timespec="seconds")
                    self.conn.execute(
                        "UPDATE daily_sessions SET session_started_at = ? WHERE target_date = ?",
                        (reset_start, target),
                    )
                    self.conn.commit()
                    return datetime.fromisoformat(reset_start)
                return session_started_at

            session_started_at = requested_start.isoformat(timespec="seconds")
            self.conn.execute(
                "INSERT INTO daily_sessions (target_date, session_started_at) VALUES (?, ?)",
                (target, session_started_at),
            )
            self.conn.commit()
            return datetime.fromisoformat(session_started_at)

    def _should_reset_session_start(
        self,
        target_date: date,
        existing_start: datetime,
        requested_start: datetime,
    ) -> bool:
        return (
            requested_start.date() == target_date
            and existing_start.date() == target_date
            and existing_start.hour < SESSION_RESET_HOUR
            and requested_start.hour >= SESSION_RESET_HOUR
        )

    def get_session(self, target_date: date) -> datetime | None:
        with self._lock:
            target = target_date.isoformat()
            row = self.conn.execute(
                "SELECT session_started_at FROM daily_sessions WHERE target_date = ?",
                (target,),
            ).fetchone()
            if not row:
                return None
            return datetime.fromisoformat(row["session_started_at"])

    def build_schedule(self, target_date: date) -> tuple[TodoPlan | None, datetime | None, list[ScheduleEntry]]:
        with self._lock:
            plan = self.get_plan(target_date)
            session_started_at = self.get_session(target_date)
            if not plan or not session_started_at:
                return plan, session_started_at, []

            entries: list[ScheduleEntry] = []
            cursor = session_started_at
            for task in plan.tasks:
                start = cursor
                end = start + timedelta(minutes=task.duration_minutes)
                entries.append(
                    ScheduleEntry(task=task, scheduled_start=start, scheduled_end=end)
                )
                cursor = end
            return plan, session_started_at, entries

    def start_task_run(
        self,
        target_date: date,
        plan_task_id: int,
        task_name: str,
        scheduled_start: datetime,
    ) -> int:
        with self._lock:
            started_at = datetime.now()
            started_at_iso = started_at.isoformat(timespec="seconds")

            cur = self.conn.execute(
                """
                INSERT INTO task_runs (plan_task_id, target_date, task_name, scheduled_start, started_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    plan_task_id,
                    target_date.isoformat(),
                    task_name,
                    scheduled_start.isoformat(timespec="seconds"),
                    started_at_iso,
                ),
            )

            block_id = self.start_time_block(
                target_date,
                "work",
                plan_task_id=plan_task_id,
                source="web",
                started_at=started_at,
                metadata={"title": task_name},
            )

            self.log_event(
                target_date,
                "task_started",
                plan_task_id=plan_task_id,
                source="web",
                occurred_at=started_at,
                metadata={"title": task_name},
            )

            self.conn.commit()
            return int(cur.lastrowid)

    def finish_task_run(self, run_id: int, outcome: str, notes: str = "") -> TaskRun:
        with self._lock:
            ended_at = datetime.now()
            ended_at_iso = ended_at.isoformat(timespec="seconds")
            row = self.conn.execute(
                """
                SELECT id, plan_task_id, target_date, task_name, started_at
                FROM task_runs
                WHERE id = ?
                """,
                (run_id,),
            ).fetchone()
            if not row:
                raise ValueError(f"Unknown task run id: {run_id}")

            started_at_dt = datetime.fromisoformat(row["started_at"])
            duration_seconds = max(int((ended_at - started_at_dt).total_seconds()), 0)

            self.conn.execute(
                """
                UPDATE task_runs
                SET ended_at = ?, duration_seconds = ?, outcome = ?, notes = ?
                WHERE id = ?
                """,
                (ended_at_iso, duration_seconds, outcome, notes.strip() or None, run_id),
            )

            open_block = self.get_open_time_block(block_type="work")
            if open_block and open_block.plan_task_id == row["plan_task_id"]:
                self.finish_time_block(open_block.id, ended_at=ended_at)

            self.log_event(
                date.fromisoformat(row["target_date"]),
                "task_finished",
                plan_task_id=row["plan_task_id"],
                source="web",
                occurred_at=ended_at,
                metadata={"title": row["task_name"], "outcome": outcome},
            )

            if row["plan_task_id"] is not None:
                completed_at = ended_at_iso if outcome == "finished" else None
                self.conn.execute(
                    """
                    UPDATE plan_tasks
                    SET completed_at = COALESCE(?, completed_at),
                        last_outcome = ?
                    WHERE id = ?
                    """,
                    (completed_at, outcome, row["plan_task_id"]),
                )

            self.conn.commit()
            return TaskRun(
                id=row["id"],
                target_date=row["target_date"],
                task_name=row["task_name"],
                started_at=row["started_at"],
                ended_at=ended_at_iso,
                duration_seconds=duration_seconds,
                outcome=outcome,
                notes=notes.strip() or None,
            )

    def get_recent_runs(self, limit: int = 20) -> list[TaskRun]:
        with self._lock:
            rows = self.conn.execute(
                """
                SELECT id, target_date, task_name, started_at, ended_at, duration_seconds, outcome, notes
                FROM task_runs
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [
                TaskRun(
                    id=row["id"],
                    target_date=row["target_date"],
                    task_name=row["task_name"],
                    started_at=row["started_at"],
                    ended_at=row["ended_at"],
                    duration_seconds=row["duration_seconds"],
                    outcome=row["outcome"],
                    notes=row["notes"],
                )
                for row in rows
            ]

    def get_open_run(self, target_date: date) -> TaskRun | None:
        with self._lock:
            row = self.conn.execute(
                """
                SELECT id, target_date, task_name, started_at, ended_at, duration_seconds, outcome, notes
                FROM task_runs
                WHERE target_date = ? AND ended_at IS NULL
                ORDER BY id DESC
                LIMIT 1
                """,
                (target_date.isoformat(),),
            ).fetchone()
            if not row:
                return None
            return TaskRun(
                id=row["id"],
                target_date=row["target_date"],
                task_name=row["task_name"],
                started_at=row["started_at"],
                ended_at=row["ended_at"],
                duration_seconds=row["duration_seconds"],
                outcome=row["outcome"],
                notes=row["notes"],
            )

    def _row_to_task_runtime(self, row) -> TaskRuntime:
        return TaskRuntime(
            id=row["id"],
            target_date=row["target_date"],
            session_id=row["session_id"],
            plan_task_id=row["plan_task_id"],
            task_run_id=row["task_run_id"],
            status=row["status"],
            started_at=row["started_at"],
            paused_at=row["paused_at"],
            resumed_at=row["resumed_at"],
            finished_at=row["finished_at"],
            estimated_seconds=row["estimated_seconds"],
            accumulated_pause_seconds=row["accumulated_pause_seconds"],
            active_work_block_id=row["active_work_block_id"],
            active_pause_block_id=row["active_pause_block_id"],
            source=row["source"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def get_or_start_session_v2(
        self,
        target_date: date,
        started_at: datetime | None = None,
        source: str = "web",
    ) -> SessionV2:
        with self._lock:
            existing = self.get_active_session_v2(target_date)
            if existing:
                return existing
            now = started_at or datetime.now()
            sid = self.start_session_v2(target_date, now, source=source)
            return self.get_active_session_v2(target_date)  # type: ignore[return-value]

    def get_active_task_runtime(self, target_date: date) -> TaskRuntime | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM task_runtime WHERE target_date = ? AND status IN ('running', 'paused') LIMIT 1",
                (target_date.isoformat(),),
            ).fetchone()
            if not row:
                return None
            return self._row_to_task_runtime(row)

    def get_task_runtime(self, runtime_id: int) -> TaskRuntime | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM task_runtime WHERE id = ?", (runtime_id,),
            ).fetchone()
            if not row:
                return None
            return self._row_to_task_runtime(row)

    def start_task_runtime(
        self,
        target_date: date,
        plan_task_id: int,
        source: str = "web",
        started_at: datetime | None = None,
    ) -> TaskRuntime:
        with self._lock:
            target = target_date.isoformat()
            now = started_at or datetime.now()
            now_iso = now.isoformat(timespec="seconds")

            active = self.conn.execute(
                "SELECT id FROM task_runtime WHERE target_date = ? AND status IN ('running', 'paused')",
                (target,),
            ).fetchone()
            if active:
                raise ValueError("Another task is already running or paused.")

            task_row = self.conn.execute(
                "SELECT * FROM plan_tasks WHERE id = ? AND target_date = ?",
                (plan_task_id, target),
            ).fetchone()
            if not task_row:
                raise ValueError(f"Task {plan_task_id} not found for {target}.")
            if task_row["completed_at"]:
                raise ValueError(f"Task {plan_task_id} is already completed.")

            estimated_seconds = task_row["duration_minutes"] * 60

            session = self.get_active_session_v2(target_date)
            session_id = session.id if session else None

            run_cur = self.conn.execute(
                """
                INSERT INTO task_runs (plan_task_id, target_date, task_name, scheduled_start, started_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (plan_task_id, target, task_row["task_name"], now_iso, now_iso),
            )
            task_run_id = int(run_cur.lastrowid)

            work_block_id = self.start_time_block(
                target_date, "work",
                session_id=session_id,
                plan_task_id=plan_task_id,
                source=source,
                started_at=now,
                metadata={"title": task_row["task_name"]},
            )

            self.log_event(
                target_date, "task_started",
                session_id=session_id,
                plan_task_id=plan_task_id,
                source=source,
                occurred_at=now,
                metadata={"title": task_row["task_name"]},
            )

            cur = self.conn.execute(
                """
                INSERT INTO task_runtime
                (target_date, session_id, plan_task_id, task_run_id, status,
                 started_at, estimated_seconds, accumulated_pause_seconds,
                 active_work_block_id, source, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'running', ?, ?, 0, ?, ?, ?, ?)
                """,
                (target, session_id, plan_task_id, task_run_id,
                 now_iso, estimated_seconds, work_block_id, source, now_iso, now_iso),
            )
            runtime_id = int(cur.lastrowid)
            self.conn.commit()
            return self.get_task_runtime(runtime_id)  # type: ignore[return-value]

    def pause_task_runtime(
        self,
        target_date: date,
        reason: str = "manual",
        source: str = "web",
        paused_at: datetime | None = None,
    ) -> TaskRuntime:
        with self._lock:
            target = target_date.isoformat()
            now = paused_at or datetime.now()
            now_iso = now.isoformat(timespec="seconds")

            rt = self.get_active_task_runtime(target_date)
            if not rt:
                raise ValueError("No active task runtime.")
            if rt.status == "paused":
                raise ValueError("Task is already paused.")

            if rt.active_work_block_id:
                self.finish_time_block(rt.active_work_block_id, ended_at=now, metadata_patch={"ended_by": "pause"})

            block_type = "call" if reason in ("mic", "call_detected") else "pause"
            pause_block_id = self.start_time_block(
                target_date, block_type,
                session_id=rt.session_id,
                plan_task_id=rt.plan_task_id,
                source=source,
                started_at=now,
                metadata={"reason": reason},
            )

            event_type = "call_started" if block_type == "call" else "pause_started"
            self.log_event(
                target_date, event_type,
                session_id=rt.session_id,
                plan_task_id=rt.plan_task_id,
                source=source,
                occurred_at=now,
                metadata={"reason": reason},
            )

            self.conn.execute(
                """
                UPDATE task_runtime
                SET status = 'paused', paused_at = ?, active_work_block_id = NULL,
                    active_pause_block_id = ?, updated_at = ?
                WHERE id = ?
                """,
                (now_iso, pause_block_id, now_iso, rt.id),
            )
            self.conn.commit()
            return self.get_task_runtime(rt.id)  # type: ignore[return-value]

    def resume_task_runtime(
        self,
        target_date: date,
        source: str = "web",
        resumed_at: datetime | None = None,
    ) -> TaskRuntime:
        with self._lock:
            target = target_date.isoformat()
            now = resumed_at or datetime.now()
            now_iso = now.isoformat(timespec="seconds")

            rt = self.get_active_task_runtime(target_date)
            if not rt or rt.status != "paused":
                raise ValueError("No paused task runtime.")

            pause_duration = 0
            if rt.paused_at:
                pause_duration = int((now - datetime.fromisoformat(rt.paused_at)).total_seconds())

            if rt.active_pause_block_id:
                self.finish_time_block(rt.active_pause_block_id, ended_at=now)

            event_type = "pause_ended"
            self.log_event(
                target_date, event_type,
                session_id=rt.session_id,
                plan_task_id=rt.plan_task_id,
                source=source,
                occurred_at=now,
                metadata={"pause_seconds": pause_duration},
            )

            task_row = self.conn.execute(
                "SELECT task_name FROM plan_tasks WHERE id = ?", (rt.plan_task_id,),
            ).fetchone()
            task_name = task_row["task_name"] if task_row else ""

            work_block_id = self.start_time_block(
                target_date, "work",
                session_id=rt.session_id,
                plan_task_id=rt.plan_task_id,
                source=source,
                started_at=now,
                metadata={"title": task_name, "resumed": True},
            )

            new_accumulated = rt.accumulated_pause_seconds + pause_duration
            self.conn.execute(
                """
                UPDATE task_runtime
                SET status = 'running', paused_at = NULL, resumed_at = ?,
                    accumulated_pause_seconds = ?, active_work_block_id = ?,
                    active_pause_block_id = NULL, updated_at = ?
                WHERE id = ?
                """,
                (now_iso, new_accumulated, work_block_id, now_iso, rt.id),
            )
            self.conn.commit()
            return self.get_task_runtime(rt.id)  # type: ignore[return-value]

    def finish_task_runtime(
        self,
        target_date: date,
        outcome: str = "finished",
        notes: str = "",
        finished_at: datetime | None = None,
    ) -> TaskRuntime:
        with self._lock:
            target = target_date.isoformat()
            now = finished_at or datetime.now()
            now_iso = now.isoformat(timespec="seconds")

            rt = self.get_active_task_runtime(target_date)
            if not rt:
                raise ValueError("No active task runtime.")

            if rt.status == "paused" and rt.paused_at:
                pause_duration = int((now - datetime.fromisoformat(rt.paused_at)).total_seconds())
                new_accumulated = rt.accumulated_pause_seconds + pause_duration
                if rt.active_pause_block_id:
                    self.finish_time_block(rt.active_pause_block_id, ended_at=now)
            else:
                new_accumulated = rt.accumulated_pause_seconds

            if rt.active_work_block_id:
                self.finish_time_block(rt.active_work_block_id, ended_at=now)

            task_row = self.conn.execute(
                "SELECT task_name FROM plan_tasks WHERE id = ?", (rt.plan_task_id,),
            ).fetchone()

            self.log_event(
                target_date, "task_finished",
                session_id=rt.session_id,
                plan_task_id=rt.plan_task_id,
                source=rt.source,
                occurred_at=now,
                metadata={"outcome": outcome, "title": task_row["task_name"] if task_row else ""},
            )

            if rt.task_run_id:
                started_dt = datetime.fromisoformat(rt.started_at)
                duration_seconds = max(int((now - started_dt).total_seconds()), 0)
                self.conn.execute(
                    "UPDATE task_runs SET ended_at = ?, duration_seconds = ?, outcome = ?, notes = ? WHERE id = ?",
                    (now_iso, duration_seconds, outcome, notes.strip() or None, rt.task_run_id),
                )

            if outcome == "finished":
                self.conn.execute(
                    "UPDATE plan_tasks SET completed_at = ?, last_outcome = ? WHERE id = ?",
                    (now_iso, outcome, rt.plan_task_id),
                )
            else:
                self.conn.execute(
                    "UPDATE plan_tasks SET last_outcome = ? WHERE id = ?",
                    (outcome, rt.plan_task_id),
                )

            final_status = "finished" if outcome == "finished" else "abandoned"
            self.conn.execute(
                """
                UPDATE task_runtime
                SET status = ?, finished_at = ?, accumulated_pause_seconds = ?,
                    active_work_block_id = NULL, active_pause_block_id = NULL,
                    paused_at = NULL, updated_at = ?
                WHERE id = ?
                """,
                (final_status, now_iso, new_accumulated, now_iso, rt.id),
            )
            self.conn.commit()
            return self.get_task_runtime(rt.id)  # type: ignore[return-value]

    def extend_task_runtime(
        self,
        target_date: date,
        extra_seconds: int,
        source: str = "web",
        notes: str = "",
    ) -> TaskRuntime:
        with self._lock:
            now = datetime.now()
            now_iso = now.isoformat(timespec="seconds")

            rt = self.get_active_task_runtime(target_date)
            if not rt:
                raise ValueError("No active task runtime.")

            new_estimated = rt.estimated_seconds + extra_seconds
            self.conn.execute(
                "UPDATE task_runtime SET estimated_seconds = ?, updated_at = ? WHERE id = ?",
                (new_estimated, now_iso, rt.id),
            )

            self.conn.execute(
                "UPDATE plan_tasks SET duration_minutes = ? WHERE id = ?",
                (new_estimated // 60, rt.plan_task_id),
            )

            metadata = {"extra_seconds": extra_seconds, "new_estimated": new_estimated}
            if notes.strip():
                metadata["notes"] = notes.strip()

            self.log_event(
                target_date, "task_extended",
                session_id=rt.session_id,
                plan_task_id=rt.plan_task_id,
                source=source,
                occurred_at=now,
                metadata=metadata,
            )

            self.conn.commit()
            return self.get_task_runtime(rt.id)  # type: ignore[return-value]

    def project_runtime_schedule(
        self,
        target_date: date,
        now: datetime | None = None,
    ) -> list[RuntimeScheduleEntry]:
        with self._lock:
            now = now or datetime.now()
            plan = self.get_plan(target_date)
            if not plan:
                return []

            runtimes = self.conn.execute(
                "SELECT * FROM task_runtime WHERE target_date = ? ORDER BY id ASC",
                (target_date.isoformat(),),
            ).fetchall()
            runtime_map: dict[int, TaskRuntime] = {}
            for row in runtimes:
                rt = self._row_to_task_runtime(row)
                runtime_map[rt.plan_task_id] = rt

            blocks = self.get_time_blocks(target_date)

            entries: list[RuntimeScheduleEntry] = []
            cursor = now

            for task in plan.tasks:
                rt = runtime_map.get(task.id)
                estimated_seconds = task.duration_minutes * 60

                if rt and rt.status in ("finished", "abandoned"):
                    actual_start = rt.started_at
                    actual_end = rt.finished_at
                    work_secs = rt.actual_work_seconds(now)
                    pause_secs = rt.accumulated_pause_seconds
                    wall = int((datetime.fromisoformat(rt.finished_at) - datetime.fromisoformat(rt.started_at)).total_seconds()) if rt.finished_at else 0
                    drift = wall - estimated_seconds
                    end_dt = datetime.fromisoformat(rt.finished_at) if rt.finished_at else now
                    if end_dt > cursor:
                        cursor = end_dt
                    entries.append(RuntimeScheduleEntry(
                        task_id=task.id,
                        task_name=task.task_name,
                        status=rt.status,
                        estimated_seconds=estimated_seconds,
                        actual_start=actual_start,
                        actual_end=actual_end,
                        projected_start=actual_start,
                        projected_end=actual_end,
                        actual_work_seconds=work_secs,
                        pause_seconds=pause_secs,
                        eta=None,
                        drift_seconds=drift,
                    ))

                elif rt and rt.status in ("running", "paused"):
                    eta = rt.compute_eta(now)
                    work_secs = rt.actual_work_seconds(now)
                    total_pause = rt.accumulated_pause_seconds
                    if rt.status == "paused" and rt.paused_at:
                        total_pause += int((now - datetime.fromisoformat(rt.paused_at)).total_seconds())
                    wall_so_far = int((now - datetime.fromisoformat(rt.started_at)).total_seconds())
                    drift = wall_so_far - estimated_seconds
                    cursor = eta
                    entries.append(RuntimeScheduleEntry(
                        task_id=task.id,
                        task_name=task.task_name,
                        status=rt.status,
                        estimated_seconds=estimated_seconds,
                        actual_start=rt.started_at,
                        actual_end=None,
                        projected_start=rt.started_at,
                        projected_end=eta.isoformat(timespec="seconds"),
                        actual_work_seconds=work_secs,
                        pause_seconds=total_pause,
                        eta=eta.isoformat(timespec="seconds"),
                        drift_seconds=drift,
                    ))

                elif task.completed_at:
                    entries.append(RuntimeScheduleEntry(
                        task_id=task.id,
                        task_name=task.task_name,
                        status="finished",
                        estimated_seconds=estimated_seconds,
                        actual_start=None,
                        actual_end=task.completed_at,
                        projected_start=None,
                        projected_end=None,
                        actual_work_seconds=0,
                        pause_seconds=0,
                        eta=None,
                        drift_seconds=0,
                    ))

                else:
                    proj_start = cursor
                    proj_end = proj_start + timedelta(seconds=estimated_seconds)
                    cursor = proj_end
                    entries.append(RuntimeScheduleEntry(
                        task_id=task.id,
                        task_name=task.task_name,
                        status="pending",
                        estimated_seconds=estimated_seconds,
                        actual_start=None,
                        actual_end=None,
                        projected_start=proj_start.isoformat(timespec="seconds"),
                        projected_end=proj_end.isoformat(timespec="seconds"),
                        actual_work_seconds=0,
                        pause_seconds=0,
                        eta=None,
                        drift_seconds=0,
                    ))

            return entries

    def reset_day(self, target_date: date) -> None:
        with self._lock:
            target = target_date.isoformat()
            self.conn.execute("DELETE FROM task_runtime WHERE target_date = ?", (target,))
            self.conn.execute("DELETE FROM task_runs WHERE target_date = ?", (target,))
            self.conn.execute("DELETE FROM plan_tasks WHERE target_date = ?", (target,))
            self.conn.execute("DELETE FROM daily_sessions WHERE target_date = ?", (target,))
            self.conn.execute("DELETE FROM plans WHERE target_date = ?", (target,))
            self.conn.execute("DELETE FROM time_blocks WHERE target_date = ?", (target,))
            self.conn.execute("DELETE FROM tracking_events WHERE target_date = ?", (target,))
            self.conn.execute("DELETE FROM sessions_v2 WHERE target_date = ?", (target,))
            self.conn.commit()

    def start_session_v2(self, target_date: date, started_at: datetime | None = None, source: str = "local") -> int:
        with self._lock:
            target = target_date.isoformat()
            now = started_at or datetime.now()
            now_iso = now.isoformat(timespec="seconds")

            existing = self.conn.execute(
                "SELECT id, status FROM sessions_v2 WHERE target_date = ? AND status = 'active'",
                (target,),
            ).fetchone()

            if existing:
                self.conn.execute(
                    "UPDATE sessions_v2 SET status = 'crashed', ended_at = ?, updated_at = ? WHERE id = ?",
                    (now_iso, now_iso, existing["id"]),
                )

            cur = self.conn.execute(
                """
                INSERT INTO sessions_v2 (target_date, started_at, status, source, created_at, updated_at)
                VALUES (?, ?, 'active', ?, ?, ?)
                """,
                (target, now_iso, source, now_iso, now_iso),
            )
            self.conn.commit()
            return int(cur.lastrowid)

    def finish_session_v2(self, session_id: int, status: str = "finished", ended_at: datetime | None = None) -> None:
        with self._lock:
            now = ended_at or datetime.now()
            now_iso = now.isoformat(timespec="seconds")
            self.conn.execute(
                "UPDATE sessions_v2 SET status = ?, ended_at = ?, updated_at = ? WHERE id = ?",
                (status, now_iso, now_iso, session_id),
            )
            self.conn.commit()

    def get_active_session_v2(self, target_date: date) -> SessionV2 | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM sessions_v2 WHERE target_date = ? AND status = 'active'",
                (target_date.isoformat(),),
            ).fetchone()
            if not row:
                return None
            return SessionV2(
                id=row["id"],
                target_date=row["target_date"],
                started_at=row["started_at"],
                ended_at=row["ended_at"],
                status=row["status"],
                source=row["source"],
                notes=row["notes"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )

    def log_event(
        self,
        target_date: date,
        event_type: str,
        *,
        session_id: int | None = None,
        plan_task_id: int | None = None,
        source: str = "local",
        metadata: dict | None = None,
        occurred_at: datetime | None = None,
        source_table: str | None = None,
        source_id: str | None = None,
    ) -> int:
        with self._lock:
            now = occurred_at or datetime.now()
            cur = self.conn.execute(
                """
                INSERT INTO tracking_events
                (target_date, session_id, plan_task_id, event_type, occurred_at, source, metadata_json, source_table, source_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    target_date.isoformat(),
                    session_id,
                    plan_task_id,
                    event_type,
                    now.isoformat(timespec="seconds"),
                    source,
                    json.dumps(metadata) if metadata else None,
                    source_table,
                    source_id,
                ),
            )
            self.conn.commit()
            return int(cur.lastrowid)

    def start_time_block(
        self,
        target_date: date,
        block_type: str,
        *,
        session_id: int | None = None,
        plan_task_id: int | None = None,
        source: str = "local",
        project: str | None = None,
        category: str | None = None,
        tags: list[str] | None = None,
        started_at: datetime | None = None,
        metadata: dict | None = None,
        source_table: str | None = None,
        source_id: str | None = None,
    ) -> int:
        with self._lock:
            now = started_at or datetime.now()

            if block_type == "work":
                self._close_open_blocks_for_session(session_id, block_type, now)

            cur = self.conn.execute(
                """
                INSERT INTO time_blocks
                (target_date, session_id, plan_task_id, block_type, started_at, source, project, category, tags_json, metadata_json, source_table, source_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    target_date.isoformat(),
                    session_id,
                    plan_task_id,
                    block_type,
                    now.isoformat(timespec="seconds"),
                    source,
                    project,
                    category,
                    json.dumps(tags) if tags else None,
                    json.dumps(metadata) if metadata else None,
                    source_table,
                    source_id,
                ),
            )
            self.conn.commit()
            return int(cur.lastrowid)

    def finish_time_block(
        self,
        block_id: int,
        ended_at: datetime | None = None,
        metadata_patch: dict | None = None,
    ) -> TimeBlock:
        with self._lock:
            now = ended_at or datetime.now()
            now_iso = now.isoformat(timespec="seconds")

            row = self.conn.execute(
                "SELECT * FROM time_blocks WHERE id = ?", (block_id,)
            ).fetchone()

            if not row:
                raise ValueError(f"Unknown time block id: {block_id}")

            started = datetime.fromisoformat(row["started_at"])
            duration = max(int((now - started).total_seconds()), 0)

            metadata = {}
            if row["metadata_json"]:
                try:
                    metadata = json.loads(row["metadata_json"])
                except json.JSONDecodeError:
                    pass
            if metadata_patch:
                metadata.update(metadata_patch)

            self.conn.execute(
                """
                UPDATE time_blocks
                SET ended_at = ?, duration_seconds = ?, metadata_json = ?
                WHERE id = ?
                """,
                (now_iso, duration, json.dumps(metadata) if metadata else None, block_id),
            )
            self.conn.commit()

            return TimeBlock(
                id=row["id"],
                target_date=row["target_date"],
                session_id=row["session_id"],
                plan_task_id=row["plan_task_id"],
                block_type=row["block_type"],
                started_at=row["started_at"],
                ended_at=now_iso,
                duration_seconds=duration,
                source=row["source"],
                project=row["project"],
                category=row["category"],
                tags_json=row["tags_json"],
                quality_score=row["quality_score"],
                energy_score=row["energy_score"],
                interruption_count=row["interruption_count"],
                metadata_json=json.dumps(metadata) if metadata else None,
                source_table=row["source_table"],
                source_id=row["source_id"],
            )

    def get_open_time_block(self, session_id: int | None = None, block_type: str | None = None) -> TimeBlock | None:
        with self._lock:
            sql = "SELECT * FROM time_blocks WHERE ended_at IS NULL"
            params = []
            if session_id is not None:
                sql += " AND session_id = ?"
                params.append(session_id)
            if block_type is not None:
                sql += " AND block_type = ?"
                params.append(block_type)

            row = self.conn.execute(sql + " ORDER BY id DESC LIMIT 1", params).fetchone()
            if not row:
                return None

            return TimeBlock(
                id=row["id"],
                target_date=row["target_date"],
                session_id=row["session_id"],
                plan_task_id=row["plan_task_id"],
                block_type=row["block_type"],
                started_at=row["started_at"],
                ended_at=row["ended_at"],
                duration_seconds=row["duration_seconds"],
                source=row["source"],
                project=row["project"],
                category=row["category"],
                tags_json=row["tags_json"],
                quality_score=row["quality_score"],
                energy_score=row["energy_score"],
                interruption_count=row["interruption_count"],
                metadata_json=row["metadata_json"],
                source_table=row["source_table"],
                source_id=row["source_id"],
            )

    def close_open_blocks(self, target_date: date, ended_at: datetime | None = None, reason: str = "cleanup") -> list[TimeBlock]:
        with self._lock:
            now = ended_at or datetime.now()
            rows = self.conn.execute(
                "SELECT * FROM time_blocks WHERE target_date = ? AND ended_at IS NULL",
                (target_date.isoformat(),),
            ).fetchall()

            closed = []
            for row in rows:
                block_id = row["id"]
                metadata = {"closed_by": reason}
                if row["metadata_json"]:
                    try:
                        existing = json.loads(row["metadata_json"])
                        existing.update(metadata)
                        metadata = existing
                    except json.JSONDecodeError:
                        pass

                started = datetime.fromisoformat(row["started_at"])
                duration = max(int((now - started).total_seconds()), 0)

                self.conn.execute(
                    """
                    UPDATE time_blocks
                    SET ended_at = ?, duration_seconds = ?, metadata_json = ?
                    WHERE id = ?
                    """,
                    (now.isoformat(timespec="seconds"), duration, json.dumps(metadata), block_id),
                )

                closed.append(
                    TimeBlock(
                        id=row["id"],
                        target_date=row["target_date"],
                        session_id=row["session_id"],
                        plan_task_id=row["plan_task_id"],
                        block_type=row["block_type"],
                        started_at=row["started_at"],
                        ended_at=now.isoformat(timespec="seconds"),
                        duration_seconds=duration,
                        source=row["source"],
                        project=row["project"],
                        category=row["category"],
                        tags_json=row["tags_json"],
                        quality_score=row["quality_score"],
                        energy_score=row["energy_score"],
                        interruption_count=row["interruption_count"],
                        metadata_json=json.dumps(metadata),
                        source_table=row["source_table"],
                        source_id=row["source_id"],
                    )
                )

            self.conn.commit()
            return closed

    def get_time_blocks(self, target_date: date) -> list[TimeBlock]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM time_blocks WHERE target_date = ? ORDER BY started_at ASC",
                (target_date.isoformat(),),
            ).fetchall()

            return [
                TimeBlock(
                    id=row["id"],
                    target_date=row["target_date"],
                    session_id=row["session_id"],
                    plan_task_id=row["plan_task_id"],
                    block_type=row["block_type"],
                    started_at=row["started_at"],
                    ended_at=row["ended_at"],
                    duration_seconds=row["duration_seconds"],
                    source=row["source"],
                    project=row["project"],
                    category=row["category"],
                    tags_json=row["tags_json"],
                    quality_score=row["quality_score"],
                    energy_score=row["energy_score"],
                    interruption_count=row["interruption_count"],
                    metadata_json=row["metadata_json"],
                    source_table=row["source_table"],
                    source_id=row["source_id"],
                )
                for row in rows
            ]

    def get_time_blocks_range(self, start_date: date, end_date: date) -> list[TimeBlock]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM time_blocks WHERE target_date >= ? AND target_date <= ? ORDER BY started_at ASC",
                (start_date.isoformat(), end_date.isoformat()),
            ).fetchall()

            return [
                TimeBlock(
                    id=row["id"],
                    target_date=row["target_date"],
                    session_id=row["session_id"],
                    plan_task_id=row["plan_task_id"],
                    block_type=row["block_type"],
                    started_at=row["started_at"],
                    ended_at=row["ended_at"],
                    duration_seconds=row["duration_seconds"],
                    source=row["source"],
                    project=row["project"],
                    category=row["category"],
                    tags_json=row["tags_json"],
                    quality_score=row["quality_score"],
                    energy_score=row["energy_score"],
                    interruption_count=row["interruption_count"],
                    metadata_json=row["metadata_json"],
                    source_table=row["source_table"],
                    source_id=row["source_id"],
                )
                for row in rows
            ]

    def get_task_detail(self, plan_task_id: int) -> dict | None:
        """Full detail for a single task: metadata, timeline of work/pause blocks, events, runtime summary.

        Args:
            plan_task_id (int): the plan_tasks.id to look up

        Returns:
            dict | None: task detail payload or None if not found
        """
        with self._lock:
            task_row = self.conn.execute(
                "SELECT * FROM plan_tasks WHERE id = ?", (plan_task_id,),
            ).fetchone()
            if not task_row:
                return None

            target = task_row["target_date"]

            blocks = self.conn.execute(
                "SELECT * FROM time_blocks WHERE plan_task_id = ? ORDER BY started_at ASC",
                (plan_task_id,),
            ).fetchall()

            unlinked_pauses = []
            if blocks:
                first_start = blocks[0]["started_at"]
                last_end = None
                for b in reversed(blocks):
                    if b["ended_at"]:
                        last_end = b["ended_at"]
                        break
                if not last_end:
                    last_end = datetime.now().isoformat(timespec="seconds")

                unlinked_pauses = self.conn.execute(
                    """SELECT * FROM time_blocks
                    WHERE target_date = ? AND plan_task_id IS NULL
                      AND block_type IN ('pause', 'call', 'idle')
                      AND started_at >= ? AND started_at <= ?
                    ORDER BY started_at ASC""",
                    (target, first_start, last_end),
                ).fetchall()

            all_blocks = list(blocks) + list(unlinked_pauses)
            all_blocks.sort(key=lambda r: r["started_at"])

            now = datetime.now()
            timeline = []
            total_work = 0
            total_pause = 0
            for b in all_blocks:
                started = datetime.fromisoformat(b["started_at"])
                if b["ended_at"]:
                    ended = datetime.fromisoformat(b["ended_at"])
                    dur = int((ended - started).total_seconds())
                else:
                    dur = int((now - started).total_seconds())

                if b["block_type"] == "work":
                    total_work += dur
                else:
                    total_pause += dur

                timeline.append({
                    "id": b["id"],
                    "type": b["block_type"],
                    "started_at": b["started_at"],
                    "ended_at": b["ended_at"],
                    "duration_seconds": dur,
                    "source": b["source"],
                    "linked": b["plan_task_id"] == plan_task_id,
                })

            events = self.conn.execute(
                "SELECT * FROM tracking_events WHERE plan_task_id = ? ORDER BY occurred_at ASC",
                (plan_task_id,),
            ).fetchall()

            runtimes = self.conn.execute(
                "SELECT * FROM task_runtime WHERE plan_task_id = ? ORDER BY id ASC",
                (plan_task_id,),
            ).fetchall()

            runs = self.conn.execute(
                "SELECT * FROM task_runs WHERE plan_task_id = ? ORDER BY id ASC",
                (plan_task_id,),
            ).fetchall()

            return {
                "task_id": plan_task_id,
                "target_date": target,
                "task_name": task_row["task_name"],
                "duration_minutes": task_row["duration_minutes"],
                "completed_at": task_row["completed_at"],
                "last_outcome": task_row["last_outcome"],
                "position": task_row["position"],
                "total_work_seconds": total_work,
                "total_pause_seconds": total_pause,
                "total_wall_seconds": total_work + total_pause,
                "block_count": len([b for b in timeline if b["type"] == "work"]),
                "pause_count": len([b for b in timeline if b["type"] != "work"]),
                "timeline": timeline,
                "events": [
                    {
                        "id": e["id"],
                        "type": e["event_type"],
                        "occurred_at": e["occurred_at"],
                        "source": e["source"],
                        "metadata": json.loads(e["metadata_json"]) if e["metadata_json"] else None,
                    }
                    for e in events
                ],
                "runtimes": [
                    {
                        "id": r["id"],
                        "status": r["status"],
                        "started_at": r["started_at"],
                        "finished_at": r["finished_at"],
                        "estimated_seconds": r["estimated_seconds"],
                        "accumulated_pause_seconds": r["accumulated_pause_seconds"],
                    }
                    for r in runtimes
                ],
                "runs": [
                    {
                        "id": r["id"],
                        "started_at": r["started_at"],
                        "ended_at": r["ended_at"],
                        "duration_seconds": r["duration_seconds"],
                        "outcome": r["outcome"],
                        "notes": r["notes"],
                    }
                    for r in runs
                ],
            }

    def update_task_run_notes(self, plan_task_id: int, notes: str) -> bool:
        """Append notes to the most recent task_run for a plan_task.

        Args:
            plan_task_id (int): the plan_tasks.id
            notes (str): new notes text to append

        Returns:
            bool: True if a run was updated
        """
        if not notes.strip():
            return False
            
        with self._lock:
            row = self.conn.execute(
                "SELECT id, notes FROM task_runs WHERE plan_task_id = ? ORDER BY id DESC LIMIT 1",
                (plan_task_id,),
            ).fetchone()
            if not row:
                return False
            
            existing = row["notes"] or ""
            timestamp = datetime.now().strftime("%H:%M:%S")
            entry = f"[{timestamp}] {notes.strip()}"
            
            new_notes = existing + ("\n\n" if existing else "") + entry
            
            self.conn.execute(
                "UPDATE task_runs SET notes = ? WHERE id = ?",
                (new_notes, row["id"]),
            )
            self.conn.commit()
            return True

    def get_plan_dates_range(self, start_date: date, end_date: date) -> list[str]:
        """Return all target_date strings that have plan tasks in the given range.

        Args:
            start_date (date): inclusive start
            end_date (date): inclusive end

        Returns:
            list[str]: sorted list of date strings
        """
        with self._lock:
            rows = self.conn.execute(
                """SELECT DISTINCT target_date FROM plan_tasks
                WHERE target_date >= ? AND target_date <= ?
                ORDER BY target_date""",
                (start_date.isoformat(), end_date.isoformat()),
            ).fetchall()
            return [r["target_date"] for r in rows]

    def get_day_summary(self, target_date: date) -> dict:
        """Lightweight summary for a date: task count, completed count, total focus seconds.

        Args:
            target_date (date): the date to summarize

        Returns:
            dict: {task_count, completed_count, focus_seconds}
        """
        with self._lock:
            target = target_date.isoformat()
            task_row = self.conn.execute(
                "SELECT COUNT(*) as total, SUM(CASE WHEN completed_at IS NOT NULL THEN 1 ELSE 0 END) as done FROM plan_tasks WHERE target_date = ?",
                (target,),
            ).fetchone()
            focus_row = self.conn.execute(
                "SELECT COALESCE(SUM(duration_seconds), 0) as total FROM time_blocks WHERE target_date = ? AND block_type = 'work' AND ended_at IS NOT NULL",
                (target,),
            ).fetchone()
            return {
                "task_count": task_row["total"] or 0,
                "completed_count": task_row["done"] or 0,
                "focus_seconds": focus_row["total"] or 0,
            }

    def _close_open_blocks_for_session(self, session_id: int | None, block_type: str, now: datetime) -> None:
        if session_id is None:
            return
        rows = self.conn.execute(
            "SELECT id FROM time_blocks WHERE session_id = ? AND block_type = ? AND ended_at IS NULL",
            (session_id, block_type),
        ).fetchall()

        for row in rows:
            self.conn.execute(
                """
                UPDATE time_blocks
                SET ended_at = ?, duration_seconds = ?, metadata_json = ?
                WHERE id = ?
                """,
                (
                    now.isoformat(timespec="seconds"),
                    int((now - datetime.fromisoformat(
                        self.conn.execute("SELECT started_at FROM time_blocks WHERE id = ?", (row["id"],)).fetchone()["started_at"]
                    )).total_seconds()),
                    json.dumps({"closed_by": "new_block_started"}),
                    row["id"],
                ),
            )

    def backup_to(self, dest_path: str) -> str:
        """Back up the SQLite database to dest_path using SQLite online backup API."""
        dest = Path(dest_path).expanduser()
        dest.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = dest / f"locked-in_{timestamp}.db"
        import sqlite3 as _sqlite3
        dst_conn = _sqlite3.connect(str(backup_file))
        try:
            self.conn.backup(dst_conn)
        finally:
            dst_conn.close()
        return str(backup_file)
