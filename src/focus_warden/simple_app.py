from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .simple_store import PlanTask, SimpleTodoStore, TaskDraft
from .simple_ui import launch_planner_window, launch_schedule_dashboard


MORNING_END_HOUR = 12
NIGHT_PROMPT_HOUR = 22


@dataclass
class LaunchDecision:
    should_show: bool
    target_date: date
    reason: str


def decide_launch(now: datetime) -> LaunchDecision:
    today = now.date()

    if now.hour >= NIGHT_PROMPT_HOUR:
        return LaunchDecision(
            should_show=True,
            target_date=today + timedelta(days=1),
            reason="Night setup window",
        )

    if now.hour < MORNING_END_HOUR:
        return LaunchDecision(
            should_show=True,
            target_date=today,
            reason="Morning fallback window",
        )

    return LaunchDecision(
        should_show=False,
        target_date=today,
        reason="Outside prompt window",
    )


class SimpleTodoApp:
    def __init__(self, now: datetime | None = None):
        self.now = now or datetime.now()
        self.store = SimpleTodoStore()

    def _plan_to_drafts(self, target_date: date) -> list[TaskDraft]:
        existing = self.store.get_plan(target_date)
        if not existing:
            return []
        return [
            TaskDraft(
                task_name=task.task_name,
                duration_minutes=task.duration_minutes,
                description=task.description or "",
            )
            for task in existing.tasks
        ]

    def run(self, force: bool = False) -> int:
        decision = decide_launch(self.now)
        today = self.now.date()

        if self.store.has_plan(today):
            self.store.ensure_session(today, self.now)
            return launch_schedule_dashboard(
                target_date=today,
                reason="Today's execution view",
                store=self.store,
            )

        if not force and not decision.should_show:
            return 0

        return launch_planner_window(
            target_date=decision.target_date,
            reason=decision.reason,
            existing_tasks=self._plan_to_drafts(decision.target_date),
            on_save=lambda tasks: self.store.save_plan(decision.target_date, tasks),
            on_save_and_open=lambda tasks: self._open_after_plan(decision.target_date, tasks),
        )

    def _open_after_plan(self, target_date: date, tasks: list[TaskDraft]) -> int:
        self.store.save_plan(target_date, tasks)
        if target_date == self.now.date():
            self.store.ensure_session(target_date, self.now)
            return launch_schedule_dashboard(
                target_date=target_date,
                reason="Today's execution view",
                store=self.store,
            )
        return 0
