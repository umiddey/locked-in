from __future__ import annotations

from .simple_store import DEFAULT_TASK_DURATION_MINUTES, TaskDraft


def parse_task_drafts(text: str) -> list[TaskDraft]:
    drafts: list[TaskDraft] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if " - " in line:
            task_name, duration_raw = [part.strip() for part in line.rsplit(" - ", 1)]
            if not task_name:
                raise ValueError("Task name cannot be empty before '-'.")
            try:
                duration = int(duration_raw)
            except ValueError as exc:
                raise ValueError(f"Invalid duration in line: {line}") from exc
        elif "|" in line:
            task_name, duration_raw = [part.strip() for part in line.rsplit("|", 1)]
            if not task_name:
                raise ValueError("Task name cannot be empty before '|'.")
            try:
                duration = int(duration_raw)
            except ValueError as exc:
                raise ValueError(f"Invalid duration in line: {line}") from exc
        else:
            task_name = line
            duration = DEFAULT_TASK_DURATION_MINUTES
        drafts.append(
            TaskDraft(task_name=task_name, duration_minutes=max(duration, 1))
        )
    return drafts


def format_task_drafts(tasks: list[TaskDraft]) -> str:
    return "\n".join(
        f"{task.task_name} - {task.duration_minutes}" + (f"  # {task.description}" if task.description else "")
        for task in tasks
    )
