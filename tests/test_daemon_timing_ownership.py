from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from locked_in.config import Config
from locked_in.daemon import Daemon
from locked_in.models import NormalizedTask, ScheduleItem, ScheduleKind, Session, SessionStatus, State
from locked_in.simple_store import SimpleTodoStore, TaskDraft


class _DummyDB:
    def __init__(self) -> None:
        self.conn = SimpleNamespace()

    def close(self) -> None:
        return None

    def log_control_event(self, *args, **kwargs) -> None:
        return None

    def create_session(self, *args, **kwargs) -> int:
        return 1

    def update_session(self, *args, **kwargs) -> None:
        return None

    def create_task(self, *args, **kwargs) -> int:
        return 1

    def update_task(self, *args, **kwargs) -> None:
        return None

    def create_interruption(self, *args, **kwargs) -> int:
        return 1

    def update_interruption(self, *args, **kwargs) -> None:
        return None


class _FakeStretchLockout:
    def __init__(self) -> None:
        self.calls: list[float] = []

    def tick(self, cumulative_work_seconds: float) -> None:
        self.calls.append(cumulative_work_seconds)

    def pause(self) -> None:
        return None

    def resume(self) -> None:
        return None

    def stop(self) -> None:
        return None


class DaemonTimingOwnershipTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)

        self.today = date.today()
        self.store = SimpleTodoStore(Path(self.tmpdir.name) / "simple_todos.db")
        self.addCleanup(self.store.conn.close)
        self.store.save_plan(self.today, [TaskDraft("Deep Work", 60)])
        self.plan_task = self.store.get_plan(self.today).tasks[0]

    def _make_daemon(self, config: Config | None = None) -> Daemon:
        cfg = config or Config()
        with patch("locked_in.daemon.Database", return_value=_DummyDB()), patch(
            "locked_in.daemon.SimpleTodoStore", return_value=self.store
        ):
            daemon = Daemon(cfg)
        daemon.store = self.store
        return daemon

    def test_idle_pause_closes_store_runtime(self) -> None:
        config = Config()
        config.auto_pause.idle_pause_seconds = 1
        daemon = self._make_daemon(config)

        now = datetime.now().replace(microsecond=0)
        self.store.ensure_session(self.today, now)
        self.store.start_task_runtime(self.today, self.plan_task.id, source="test", started_at=now - timedelta(minutes=5))

        daemon.session = Session(started_at=now - timedelta(minutes=5), shutdown_deadline=now + timedelta(hours=1), status=SessionStatus.ACTIVE)
        daemon.sm.state = State.TASK_ACTIVE
        daemon._idle_detector.seconds_since_any_activity = lambda: 2.0

        daemon._check_idle_pause(now)

        runtime = self.store.get_active_task_runtime(self.today)
        self.assertIsNotNone(runtime)
        self.assertEqual(runtime.status, "paused")
        self.assertEqual(daemon.sm.state, State.PAUSED)

    def test_tick_loop_asks_store_for_cumulative_work(self) -> None:
        daemon = self._make_daemon()
        fake_lockout = _FakeStretchLockout()
        daemon._stretch_lockout = fake_lockout
        daemon.session = Session(started_at=datetime.now(), shutdown_deadline=datetime.now() + timedelta(hours=1), status=SessionStatus.ACTIVE)
        daemon.sm.state = State.AWAITING_TASK_START

        cumulative = MagicMock(return_value=123.0)
        daemon.store.get_cumulative_work_seconds = cumulative

        daemon._tick_logic()

        cumulative.assert_called_once()
        self.assertEqual(fake_lockout.calls, [123.0])

    def test_schedule_activation_comes_from_store_projection(self) -> None:
        daemon = self._make_daemon()
        now = datetime.now().replace(microsecond=0)
        daemon.session = Session(started_at=now - timedelta(minutes=1), shutdown_deadline=now + timedelta(hours=1), status=SessionStatus.ACTIVE)
        daemon.sm.state = State.AWAITING_TASK_START

        schedule_item = ScheduleItem(
            kind=ScheduleKind.TASK,
            title=self.plan_task.task_name,
            scheduled_start=now,
            duration_minutes=self.plan_task.duration_minutes,
            task_ref=NormalizedTask(
                id=str(self.plan_task.id),
                title=self.plan_task.task_name,
                normalized_key=self.plan_task.task_name.lower(),
                estimate_minutes=self.plan_task.duration_minutes,
                due_date=self.today,
            ),
        )
        daemon.schedule = [schedule_item]

        projection_entry = SimpleNamespace(
            task_id=self.plan_task.id,
            task_name=self.plan_task.task_name,
            status="pending",
            projected_start=now.isoformat(timespec="seconds"),
            projected_end=(now + timedelta(minutes=60)).isoformat(timespec="seconds"),
        )
        projection = MagicMock(return_value=[projection_entry])
        daemon.store.project_runtime_schedule = projection

        activate = MagicMock()
        daemon._activate_item = activate

        daemon._check_schedule(now)

        projection.assert_called_once()
        activate.assert_called_once_with(schedule_item)

    def test_task_finish_uses_persisted_start_without_daemon_mirror(self) -> None:
        daemon = self._make_daemon()
        now = datetime.now().replace(microsecond=0)

        self.store.save_plan(self.today, [TaskDraft("Deep Work", 60), TaskDraft("Second task", 15)])
        plan_tasks = self.store.get_plan(self.today).tasks
        first_plan_task = plan_tasks[0]
        second_plan_task = plan_tasks[1]

        self.store.ensure_session(self.today, now)
        self.store.start_task_runtime(self.today, first_plan_task.id, source="web", started_at=now - timedelta(minutes=12))

        schedule_item = ScheduleItem(
            kind=ScheduleKind.TASK,
            title=first_plan_task.task_name,
            scheduled_start=now - timedelta(minutes=12),
            duration_minutes=first_plan_task.duration_minutes,
            task_ref=NormalizedTask(
                id=str(first_plan_task.id),
                title=first_plan_task.task_name,
                normalized_key=first_plan_task.task_name.lower(),
                estimate_minutes=first_plan_task.duration_minutes,
                due_date=self.today,
            ),
        )
        daemon.current_item = schedule_item
        daemon.schedule = [
            schedule_item,
            ScheduleItem(
                kind=ScheduleKind.TASK,
                title=second_plan_task.task_name,
                scheduled_start=now,
                duration_minutes=second_plan_task.duration_minutes,
                task_ref=NormalizedTask(
                    id=str(second_plan_task.id),
                    title=second_plan_task.task_name,
                    normalized_key=second_plan_task.task_name.lower(),
                    estimate_minutes=second_plan_task.duration_minutes,
                    due_date=self.today,
                ),
            ),
        ]
        daemon.sm.state = State.TASK_ACTIVE

        daemon._on_item_finished()

        self.assertIsNone(self.store.get_active_task_runtime(self.today))
        self.assertIsNone(daemon.current_item)
        self.assertEqual(daemon.sm.state, State.AWAITING_TASK_START)
        self.assertFalse(hasattr(daemon, "_task_started_at"))


if __name__ == "__main__":
    unittest.main()
