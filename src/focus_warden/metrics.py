from datetime import date, datetime, timedelta
from collections import Counter

from focus_warden.simple_store import (
    SimpleTodoStore,
    TimeBlock,
    PlanTask,
)


def seconds_between(start_iso: str, end_iso: str | None, now: datetime | None = None) -> int:
    if not end_iso:
        if now:
            end_iso = now.isoformat(timespec="seconds")
        else:
            return 0
    return max(int((datetime.fromisoformat(end_iso) - datetime.fromisoformat(start_iso)).total_seconds()), 0)


def summarize_day(store: SimpleTodoStore, target_date: date) -> dict:
    blocks = store.get_time_blocks(target_date)
    plan = store.get_plan(target_date)
    now = datetime.now()

    def block_duration(b: TimeBlock) -> int:
        if b.duration_seconds:
            return b.duration_seconds
        if b.ended_at:
            return seconds_between(b.started_at, b.ended_at)
        return seconds_between(b.started_at, None, now=now)

    focus_seconds = sum(block_duration(b) for b in blocks if b.block_type == "work")
    pause_seconds = sum(block_duration(b) for b in blocks if b.block_type == "pause")
    call_seconds = sum(block_duration(b) for b in blocks if b.block_type == "call")
    break_seconds = sum(block_duration(b) for b in blocks if b.block_type == "break")
    idle_seconds = sum(block_duration(b) for b in blocks if b.block_type == "idle")

    planned_seconds = sum(t.duration_minutes * 60 for t in plan.tasks) if plan else 0

    completed_tasks = len([t for t in plan.tasks if t.completed_at]) if plan else 0
    total_tasks = len(plan.tasks) if plan else 0
    completion_rate = completed_tasks / total_tasks if total_tasks > 0 else 0.0

    estimate_delta_seconds = focus_seconds - planned_seconds

    work_blocks_with_duration = [b for b in blocks if b.block_type == "work" and (b.duration_seconds or not b.ended_at)]
    if work_blocks_with_duration:
        durations = [block_duration(b) for b in work_blocks_with_duration]
        longest_focus = max(durations)
        avg_focus = sum(durations) // len(durations)
        first_start = min(b.started_at for b in work_blocks_with_duration)
        last_end = max((b.ended_at for b in work_blocks_with_duration if b.ended_at), default=None)
    else:
        longest_focus = 0
        avg_focus = 0
        first_start = None
        last_end = None

    interruption_count = sum(1 for b in blocks if b.block_type in ("pause", "call", "idle"))

    by_project = _summarize_by_field(blocks, "project", block_duration)
    by_category = _summarize_by_field(blocks, "category", block_duration)
    by_task = _summarize_task_blocks(blocks, plan.tasks if plan else [], block_duration)

    timeline = [
        {
            "start": b.started_at,
            "end": b.ended_at,
            "type": b.block_type,
            "task_id": b.plan_task_id,
            "duration": b.duration_seconds,
        }
        for b in blocks
        if b.ended_at
    ]

    return {
        "target_date": target_date.isoformat(),
        "focus_seconds": focus_seconds,
        "pause_seconds": pause_seconds,
        "call_seconds": call_seconds,
        "break_seconds": break_seconds,
        "idle_seconds": idle_seconds,
        "planned_seconds": planned_seconds,
        "estimate_delta_seconds": estimate_delta_seconds,
        "completion_rate": completion_rate,
        "completed_tasks": completed_tasks,
        "total_tasks": total_tasks,
        "interruption_count": interruption_count,
        "longest_focus_block_seconds": longest_focus,
        "average_focus_block_seconds": avg_focus,
        "first_work_started_at": first_start,
        "last_work_ended_at": last_end,
        "by_project": by_project,
        "by_category": by_category,
        "by_task": by_task,
        "timeline": timeline,
    }


def summarize_range(store: SimpleTodoStore, start_date: date, end_date: date) -> dict:
    blocks = store.get_time_blocks_range(start_date, end_date)
    now = datetime.now()

    def block_duration(b: TimeBlock) -> int:
        if b.duration_seconds:
            return b.duration_seconds
        if b.ended_at:
            return seconds_between(b.started_at, b.ended_at)
        return seconds_between(b.started_at, None, now=now)

    daily = {}
    for d in (start_date + timedelta(days=i) for i in range((end_date - start_date).days + 1)):
        daily[d.isoformat()] = summarize_day(store, d)

    focus_by_day = [(d, daily[d]["focus_seconds"]) for d in daily]
    focus_by_project = Counter()
    estimate_delta_by_day = [(d, daily[d]["estimate_delta_seconds"]) for d in daily]

    for block in blocks:
        if block.project and block.block_type == "work":
            focus_by_project[block.project] += block_duration(block)

    return {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "daily": daily,
        "focus_by_day": focus_by_day,
        "focus_by_project": dict(focus_by_project),
        "estimate_delta_by_day": estimate_delta_by_day,
    }


def _summarize_by_field(blocks: list[TimeBlock], field: str, block_duration_func) -> list[dict]:
    work_blocks = [b for b in blocks if b.block_type == "work"]
    grouped = Counter()

    for block in work_blocks:
        key = getattr(block, field) or "unknown"
        grouped[key] += block_duration_func(block)

    return [{"key": k, "seconds": v} for k, v in grouped.most_common()]


def _summarize_task_blocks(blocks: list[TimeBlock], tasks: list[PlanTask], block_duration_func) -> list[dict]:
    task_map = {t.id: t for t in tasks}

    by_task: dict[int, dict] = {}
    task_time_ranges: dict[int, dict] = {}

    for block in blocks:
        if block.block_type != "work" or not block.plan_task_id:
            continue

        tid = block.plan_task_id
        if tid not in by_task:
            task = task_map.get(tid)
            by_task[tid] = {
                "task_id": tid,
                "task_name": task.task_name if task else "Unknown",
                "project": block.project,
                "category": block.category,
                "estimated_seconds": task.duration_minutes * 60 if task else 0,
                "actual_seconds": 0,
                "blocks": 0,
                "interruptions": 0,
                "completed": bool(task and task.completed_at),
            }
            task_time_ranges[tid] = {"first_start": None, "last_end": None}

        by_task[tid]["actual_seconds"] += block_duration_func(block)
        by_task[tid]["blocks"] += 1

        block_start = datetime.fromisoformat(block.started_at)
        block_end = datetime.fromisoformat(block.ended_at) if block.ended_at else datetime.now()

        if task_time_ranges[tid]["first_start"] is None or block_start < task_time_ranges[tid]["first_start"]:
            task_time_ranges[tid]["first_start"] = block_start
        if task_time_ranges[tid]["last_end"] is None or block_end > task_time_ranges[tid]["last_end"]:
            task_time_ranges[tid]["last_end"] = block_end

    for block in blocks:
        if block.block_type not in ("pause", "call", "idle"):
            continue

        block_start = datetime.fromisoformat(block.started_at)
        block_end = datetime.fromisoformat(block.ended_at) if block.ended_at else datetime.now()

        for tid, time_range in task_time_ranges.items():
            if time_range["first_start"] and time_range["last_end"]:
                if block_start >= time_range["first_start"] and block_end <= time_range["last_end"]:
                    by_task[tid]["interruptions"] += 1

    return list(by_task.values())
