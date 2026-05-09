from __future__ import annotations

from datetime import datetime, timedelta

from .config import ScheduleConfig
from .models import NormalizedTask, ScheduleItem, ScheduleKind


def build_schedule(
    tasks: list[NormalizedTask],
    session_start: datetime,
    config: ScheduleConfig,
    grace_seconds: int = 300,
) -> list[ScheduleItem]:
    """Build a deterministic schedule from tasks and config.

    Pure function — no datetime.now() calls.
    """
    items: list[ScheduleItem] = []
    now = session_start

    shutdown_parts = config.hard_shutdown_time.split(":")
    shutdown_hour, shutdown_minute = int(shutdown_parts[0]), int(shutdown_parts[1])
    shutdown_deadline = session_start.replace(hour=shutdown_hour, minute=shutdown_minute, second=0, microsecond=0)
    if shutdown_deadline <= session_start:
        shutdown_deadline += timedelta(days=1)

    # Grace period before first task
    cursor = now + timedelta(seconds=grace_seconds)
    accumulated_work = 0

    for task in tasks:
        # Insert stretch break if accumulated work exceeds threshold
        while accumulated_work >= config.stretch_interval_minutes:
            accumulated_work -= config.stretch_interval_minutes
            if cursor + timedelta(minutes=config.stretch_duration_minutes) < shutdown_deadline:
                items.append(ScheduleItem(
                    kind=ScheduleKind.STRETCH,
                    title="Stretch Break",
                    scheduled_start=cursor,
                    duration_minutes=config.stretch_duration_minutes,
                ))
                cursor += timedelta(minutes=config.stretch_duration_minutes)

        duration = task.estimate_minutes or config.default_task_minutes

        # Check if task would cross shutdown
        if cursor + timedelta(minutes=duration) >= shutdown_deadline:
            remaining = (shutdown_deadline - cursor).total_seconds() / 60
            if remaining > 5:
                items.append(ScheduleItem(
                    kind=ScheduleKind.TASK,
                    title=task.title,
                    scheduled_start=cursor,
                    duration_minutes=int(remaining),
                    task_ref=task,
                ))
                cursor = shutdown_deadline
                accumulated_work += remaining
            break

        items.append(ScheduleItem(
            kind=ScheduleKind.TASK,
            title=task.title,
            scheduled_start=cursor,
            duration_minutes=duration,
            task_ref=task,
        ))
        cursor += timedelta(minutes=duration)
        accumulated_work += duration

    # Shutdown warning
    if config.hard_shutdown_enabled:
        warning_time = shutdown_deadline - timedelta(minutes=config.shutdown_warning_minutes)
        if warning_time > cursor:
            items.append(ScheduleItem(
                kind=ScheduleKind.SHUTDOWN_WARNING,
                title="Shutdown Warning",
                scheduled_start=warning_time,
                duration_minutes=config.shutdown_warning_minutes,
            ))
        items.append(ScheduleItem(
            kind=ScheduleKind.SHUTDOWN,
            title="Hard Shutdown",
            scheduled_start=shutdown_deadline,
            duration_minutes=1,
        ))

    items.sort(key=lambda i: i.scheduled_start)
    return items
