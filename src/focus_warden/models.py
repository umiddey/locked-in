from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime


class SessionStatus(str, enum.Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    GIVEN_UP = "given_up"
    FINISHED = "finished"


class TaskStatus(str, enum.Enum):
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    SKIPPED = "skipped"


class ScheduleKind(str, enum.Enum):
    TASK = "task"
    STRETCH = "stretch"
    SHUTDOWN_WARNING = "shutdown_warning"
    SHUTDOWN = "shutdown"


class State(str, enum.Enum):
    IDLE = "idle"
    AWAITING_TASK_START = "awaiting_task_start"
    TASK_ACTIVE = "task_active"
    AWAITING_BREAK_START = "awaiting_break_start"
    BREAK_ACTIVE = "break_active"
    PAUSED = "paused"
    GIVEN_UP = "given_up"
    FINISHED = "finished"


@dataclass
class NormalizedTask:
    id: str
    title: str
    normalized_key: str
    estimate_minutes: int = 30
    due_date: str | None = None


@dataclass
class ScheduleItem:
    kind: ScheduleKind
    title: str
    scheduled_start: datetime
    duration_minutes: int
    task_ref: NormalizedTask | None = None


@dataclass
class Session:
    id: int | None = None
    started_at: datetime = field(default_factory=datetime.now)
    ended_at: datetime | None = None
    shutdown_deadline: datetime | None = None
    status: SessionStatus = SessionStatus.ACTIVE


@dataclass
class Task:
    id: int | None = None
    session_id: int | None = None
    notion_task_id: str | None = None
    title: str = ""
    normalized_key: str = ""
    scheduled_start: datetime | None = None
    scheduled_duration_minutes: int = 0
    actual_start: datetime | None = None
    actual_end: datetime | None = None
    actual_minutes: float | None = None
    status: TaskStatus = TaskStatus.PENDING


@dataclass
class Interruption:
    id: int | None = None
    session_id: int | None = None
    kind: str = ""
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration_minutes: float | None = None
