from __future__ import annotations

import logging
import os
import re
import subprocess
import time
from datetime import date, datetime, timedelta

from .activity_detector import MicActivityDetector
from .config import Config
from .control_server import ControlServer
from .db import Database
from .idle_detector import IdleDetector
from .models import (
    Interruption,
    ScheduleItem,
    ScheduleKind,
    Session,
    SessionStatus,
    State,
    Task,
    TaskStatus,
    NormalizedTask,
)
from .eta_warning import show_eta_warning, DECISION_FINISH, DECISION_EXTEND
from .notifications import notify
from .scheduler import build_schedule
from .state_machine import StateMachine
from .simple_store import SimpleTodoStore
from .stretch_lockout import StretchLockout
from .ui import BlockerWindow, create_app

log = logging.getLogger(__name__)


def _normalize_key(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")


class Daemon:
    def __init__(self, config: Config):
        self.config = config
        self.db = Database()
        self.store = SimpleTodoStore()
        self.sm = StateMachine()
        self.schedule: list[ScheduleItem] = []
        self.current_item: ScheduleItem | None = None
        self._task_rows: dict[str, int] = {}  # schedule item id -> db task id
        self._task_started_at: datetime | None = None
        self.session: Session | None = None
        self._interruption: Interruption | None = None
        self._give_up_attempts: int = 0
        self._give_up_last: datetime | None = None
        self._bootstrap_error: str | None = None
        self._next_bootstrap_retry_at: datetime | None = None
        self._shutdown_warning_until: datetime | None = None
        self._item_finish_due_at: datetime | None = None
        self._mic_detector = MicActivityDetector(
            config.auto_pause.call_apps,
            config.auto_pause.ignored_apps,
        )
        self._next_mic_poll_at: datetime | None = None
        self._mic_active_since: datetime | None = None
        self._mic_inactive_since: datetime | None = None
        self._auto_paused_by_mic = False
        self._idle_detector = IdleDetector(idle_seconds=config.auto_pause.idle_pause_seconds)
        self._auto_paused_by_idle = False
        self._idle_resume_events: list[datetime] = []
        self._last_activity_seconds: float = 0.0
        self._eta_warning_shown_for: int | None = None
        self._eta_warning_popup = None
        self._next_task_notified_for: int | None = None
        self._running = False
        self._app = None
        self._window: BlockerWindow | None = None
        self.tracking_session_id: int | None = None
        self._current_work_block_id: int | None = None
        self._current_pause_block_id: int | None = None
        self._previous_state_before_pause: str | None = None
        self._stretch_lockout = StretchLockout(
            interval_minutes=config.schedule.stretch_interval_minutes,
            duration_minutes=config.schedule.stretch_duration_minutes,
        )

    def _completed_task_ids_for_session_start(self, started_at: datetime) -> set[str]:
        """Recover completed plan task IDs when the daemon restarts mid-session."""
        rows = self.db.conn.execute(
            """
            SELECT t.notion_task_id
            FROM tasks t
            JOIN sessions s ON s.id = t.session_id
            WHERE s.started_at = ?
              AND s.status = ?
              AND t.status = ?
              AND t.notion_task_id IS NOT NULL
            """,
            (started_at.isoformat(), SessionStatus.ACTIVE.value, TaskStatus.COMPLETED.value),
        ).fetchall()
        return {str(row["notion_task_id"]) for row in rows}

    def run(self):
        self._running = True
        if not self.config.ui.show_blocker_window and not os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("DISPLAY"):
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        self._app = create_app()
        ctrl = ControlServer(self.config.control.socket_path, self._handle_command)

        try:
            self._bootstrap_session()
        except Exception:
            ctrl.close()
            raise

        self._idle_detector.start()

        tick_timer = self._setup_tick_timer(ctrl)

        try:
            while self._running:
                self._app.processEvents()
                time.sleep(0.05)
        finally:
            self._idle_detector.stop()
            ctrl.close()
            self.db.close()

    def _setup_tick_timer(self, ctrl):
        from PyQt6.QtCore import QTimer
        timer = QTimer()
        timer.timeout.connect(lambda: self._tick(ctrl))
        timer.start(1000)
        return timer

    def _start_session(self, plan):
        now = datetime.now()
        today = date.today()
        session_started_at = self.store.ensure_session(today, now)
        self.tracking_session_id = self.store.start_session_v2(today, now, source="daemon")
        self.store.log_event(today, "session_started", session_id=self.tracking_session_id, source="daemon", occurred_at=now)

        shutdown_parts = self.config.schedule.hard_shutdown_time.split(":")
        shutdown_deadline = now.replace(
            hour=int(shutdown_parts[0]),
            minute=int(shutdown_parts[1]),
            second=0,
            microsecond=0,
        )
        if shutdown_deadline <= now:
            shutdown_deadline += timedelta(days=1)

        self.session = Session(
            started_at=session_started_at,
            shutdown_deadline=shutdown_deadline,
            status=SessionStatus.ACTIVE,
        )
        self.session.id = self.db.create_session(self.session)
        completed_task_ids = self._completed_task_ids_for_session_start(session_started_at)

        tasks = [
            NormalizedTask(
                id=str(task.id),
                title=task.task_name,
                normalized_key=_normalize_key(task.task_name),
                estimate_minutes=task.duration_minutes,
                due_date=plan.target_date,
            )
            for task in plan.tasks
            if str(task.id) not in completed_task_ids
        ]
        self.schedule = build_schedule(
            tasks, session_started_at, self.config.schedule,
            grace_seconds=self.config.warden.task_start_grace_seconds,
        )
        for item in self.schedule:
            if item.kind == ScheduleKind.TASK and item.task_ref:
                row_id = self.db.create_task(Task(
                    session_id=self.session.id,
                    notion_task_id=item.task_ref.id,
                    title=item.title,
                    normalized_key=item.task_ref.normalized_key,
                    scheduled_start=item.scheduled_start,
                    scheduled_duration_minutes=item.duration_minutes,
                    status=TaskStatus.PENDING,
                ))
                self._task_rows[id(item)] = row_id

        self.sm.transition(State.AWAITING_TASK_START)

        # Recover if a task_runtime was already running from a previous daemon instance.
        # Paused runtimes are left as-is — user or another trigger will resume them.
        self._recover_active_task(today)

    def _recover_active_task(self, today) -> None:
        """Sync state machine with DB if a task_runtime is running but daemon has no current_item."""
        existing_runtime = self.store.get_active_task_runtime(today)
        if not existing_runtime or existing_runtime.status != "running":
            return
        if self.current_item is not None:
            return  # already tracking something
        target_id = str(existing_runtime.plan_task_id)
        log.info("Recovering running runtime id=%d plan_task_id=%s, schedule has %d items",
                 existing_runtime.id, target_id, len(self.schedule))

        # Try to find in schedule first
        for item in self.schedule:
            item_id = item.task_ref.id if item.task_ref else None
            if item.kind == ScheduleKind.TASK and item.task_ref and item.task_ref.id == target_id:
                log.info("Recovered task from schedule: %s (runtime id=%d)", item.title, existing_runtime.id)
                self.current_item = item
                self._task_started_at = existing_runtime.started_at
                self._item_finish_due_at = existing_runtime.compute_eta()
                self.sm.transition(State.AWAITING_TASK_START)
                self.sm.transition(State.TASK_ACTIVE)
                return

        # Task not in schedule (e.g. daemon restarted past its scheduled slot).
        # Create a synthetic schedule item so the daemon can track it.
        plan = self.store.get_plan(today)
        plan_task = None
        if plan:
            for pt in plan.tasks:
                if str(pt.id) == target_id:
                    plan_task = pt
                    break

        if plan_task:
            synthetic = ScheduleItem(
                kind=ScheduleKind.TASK,
                title=plan_task.task_name,
                scheduled_start=existing_runtime.started_at,
                duration_minutes=max(1, int(existing_runtime.estimated_seconds / 60)),
                task_ref=NormalizedTask(
                    id=str(plan_task.id),
                    title=plan_task.task_name,
                    normalized_key=plan_task.task_name.lower().strip(),
                    estimate_minutes=plan_task.duration_minutes,
                    due_date=today,
                ),
            )
            log.info("Recovered task via synthetic item: %s (runtime id=%d)", synthetic.title, existing_runtime.id)
            self.current_item = synthetic
            self._task_started_at = existing_runtime.started_at
            self._item_finish_due_at = existing_runtime.compute_eta()
            self.sm.transition(State.AWAITING_TASK_START)
            self.sm.transition(State.TASK_ACTIVE)
        else:
            log.warning("Cannot recover runtime id=%d: plan_task_id=%s not found in plan", existing_runtime.id, target_id)

    def _bootstrap_session(self) -> bool:
        today = date.today()
        plan = self.store.get_plan(today)
        if not plan or not plan.tasks:
            self._bootstrap_error = None
            self._next_bootstrap_retry_at = None
            return False

        try:
            self._start_session(plan)
        except Exception as e:
            message = str(e)
            log.error("Failed to start session: %s", e)
            self._bootstrap_error = message
            self._next_bootstrap_retry_at = datetime.now() + timedelta(minutes=5)
            notify("Focus Warden Error", message, "critical")
            return False

        self._bootstrap_error = None
        self._next_bootstrap_retry_at = None
        log.info("Session bootstrapped successfully")
        return True

    def _tick(self, ctrl: ControlServer):
        ctrl.poll()

        if self.sm.state == State.GIVEN_UP:
            self._running = False
            return

        if self.sm.state == State.FINISHED:
            self._running = False
            return

        self._stretch_lockout.tick()

        now = datetime.now()

        if self.session is None:
            if self._next_bootstrap_retry_at is None or now >= self._next_bootstrap_retry_at:
                self._bootstrap_session()
            if self.session is None:
                return

        self._poll_auto_pause(now)
        self._poll_idle_pause(now)
        self._poll_eta_warning(now)

        if self.sm.state == State.PAUSED:
            return

        if self.config.schedule.hard_shutdown_enabled:
            if self._shutdown_warning_until is not None:
                if now >= self._shutdown_warning_until:
                    self._shutdown()
                return

            warning_start = self.session.shutdown_deadline - timedelta(
                minutes=self.config.schedule.shutdown_warning_minutes
            )
            if now >= warning_start:
                if now >= self.session.shutdown_deadline:
                    self._shutdown_warning_until = now + timedelta(
                        minutes=self.config.schedule.shutdown_warning_minutes
                    )
                else:
                    self._shutdown_warning_until = self.session.shutdown_deadline
                log.warning(
                    "Hard shutdown warning started; until=%s",
                    self._shutdown_warning_until.isoformat(timespec="seconds"),
                )
                notify(
                    "Focus Warden",
                    f"Hard shutdown in {self.config.schedule.shutdown_warning_minutes} minutes.",
                    "critical",
                )
                return

        # Find current or next item
        if self.current_item is None or self.sm.state in (State.IDLE, State.AWAITING_TASK_START, State.TASK_ACTIVE, State.BREAK_ACTIVE):
            for item in self.schedule:
                if now >= item.scheduled_start:
                    if item.kind == ScheduleKind.SHUTDOWN_WARNING:
                        notify("Focus Warden", f"WARNING: Shutdown in {self.config.schedule.shutdown_warning_minutes} minutes!", "critical")
                        self.schedule.remove(item)
                        break
                    if item.kind == ScheduleKind.SHUTDOWN:
                        self._shutdown()
                        return
                    if self.current_item != item:
                        self._activate_item(item)
                    break

        if (
            self.current_item
            and self._item_finish_due_at
            and now >= self._item_finish_due_at
            and self.sm.state in (State.TASK_ACTIVE, State.BREAK_ACTIVE)
        ):
            self._on_item_finished()
            return

        # Check shutdown
        if self.session and self.config.schedule.hard_shutdown_enabled:
            if now >= self.session.shutdown_deadline:
                self._shutdown()
                return

    def _poll_auto_pause(self, now: datetime):
        config = self.config.auto_pause
        if not config.enabled:
            return
        if self.sm.state in (State.GIVEN_UP, State.FINISHED):
            return
        if self._next_mic_poll_at and now < self._next_mic_poll_at:
            return

        self._next_mic_poll_at = now + timedelta(seconds=max(config.poll_seconds, 1))
        snapshot = self._mic_detector.snapshot()

        if snapshot.active:
            self._mic_inactive_since = None
            if self._mic_active_since is None:
                self._mic_active_since = now

            active_for = (now - self._mic_active_since).total_seconds()
            if (
                not self._auto_paused_by_mic
                and self.sm.state != State.PAUSED
                and active_for >= config.mic_active_seconds
            ):
                today = date.today()
                runtime = self.store.get_active_task_runtime(today)
                if runtime and runtime.status == "running":
                    try:
                        self.store.pause_task_runtime(today, reason="mic", source="mic")
                        self._auto_paused_by_mic = True
                        self.sm.transition(State.PAUSED)
                        self._stretch_lockout.pause()
                        log.info("Auto-paused for microphone use: %s", ", ".join(snapshot.apps))
                        notify("Focus Warden", f"Paused for microphone use: {', '.join(snapshot.apps)}")
                    except ValueError:
                        pass
                else:
                    result = self._pause_session(
                        kind="call_detected",
                        message=f"Paused for microphone use: {', '.join(snapshot.apps)}",
                    )
                    if "error" not in result:
                        self._auto_paused_by_mic = True
                        log.info("Auto-paused for microphone use: %s", ", ".join(snapshot.apps))
            return

        self._mic_active_since = None
        if self._auto_paused_by_mic:
            if self._mic_inactive_since is None:
                self._mic_inactive_since = now
            inactive_for = (now - self._mic_inactive_since).total_seconds()
            if inactive_for >= config.resume_after_silence_seconds:
                today = date.today()
                runtime = self.store.get_active_task_runtime(today)
                if runtime and runtime.status == "paused":
                    try:
                        self.store.resume_task_runtime(today, source="mic")
                        self._auto_paused_by_mic = False
                        self._mic_inactive_since = None
                        if self.sm.state == State.PAUSED:
                            self.sm.resume()
                        self._stretch_lockout.resume()
                        self._recover_active_task(today)
                        log.info("Auto-resumed after microphone silence")
                        notify("Focus Warden", "Resumed")
                    except ValueError:
                        pass
                else:
                    result = self._resume_session()
                    if "error" not in result:
                        self._auto_paused_by_mic = False
                        self._mic_inactive_since = None
                        self._recover_active_task(today)
                        log.info("Auto-resumed after microphone silence")

    def _poll_idle_pause(self, now: datetime):
        """Auto-pause when user goes idle (no kb/mouse), auto-resume on 5+ events in 30s."""
        config = self.config.auto_pause
        if not config.enabled or config.idle_pause_seconds <= 0:
            return
        if self.sm.state in (State.GIVEN_UP, State.FINISHED, State.IDLE, State.PAUSED):
            if self.sm.state == State.PAUSED and self._auto_paused_by_idle:
                # Require multiple real (HARD) input events before auto-resuming.
                # A single phantom blip should NOT resume.
                idle_secs = self._idle_detector.seconds_since_hard_activity()
                grace = max(config.idle_resume_grace_seconds, 1)
                if idle_secs < grace:
                    self._idle_resume_events.append(now)
                    # Keep only events from last 30 seconds
                    cutoff = now - timedelta(seconds=30)
                    self._idle_resume_events = [t for t in self._idle_resume_events if t >= cutoff]
                    if len(self._idle_resume_events) >= 5:
                        today = date.today()
                        runtime = self.store.get_active_task_runtime(today)
                        if runtime and runtime.status == "paused":
                            try:
                                self.store.resume_task_runtime(today, source="idle")
                                self._auto_paused_by_idle = False
                                if self.sm.state == State.PAUSED:
                                    self.sm.resume()
                                self._stretch_lockout.resume()
                                log.info("Auto-resumed from idle (%d events in 30s)", len(self._idle_resume_events))
                                self._idle_resume_events.clear()
                                notify("Focus Warden", "Resumed — welcome back!")
                            except ValueError:
                                pass
                        else:
                            self._auto_paused_by_idle = False
                            self._idle_resume_events.clear()
                else:
                    self._idle_resume_events.clear()
            return

        # Only auto-pause when a task is actively being worked on
        if self.sm.state != State.TASK_ACTIVE:
            return

        # Use ANY activity (SOFT) to keep the session alive
        idle_secs = self._idle_detector.seconds_since_any_activity()
        self._last_activity_seconds = idle_secs

        if idle_secs >= config.idle_pause_seconds and not self._auto_paused_by_idle:
            today = date.today()
            runtime = self.store.get_active_task_runtime(today)
            if runtime and runtime.status == "running":
                try:
                    self.store.pause_task_runtime(today, reason="idle", source="idle")
                    self._auto_paused_by_idle = True
                    self._idle_resume_events.clear()
                    self.sm.transition(State.PAUSED)
                    self._stretch_lockout.pause()
                    log.info("Auto-paused for idle (%.0fs)", idle_secs)
                    notify("Focus Warden", f"Paused — idle for {int(idle_secs)}s")
                except ValueError:
                    pass

    def _poll_eta_warning(self, now: datetime):
        today = date.today()
        rt = self.store.get_active_task_runtime(today)
        if not rt or rt.status != "running":
            self._eta_warning_shown_for = None
            return

        eta = rt.compute_eta(now)
        minutes_left = (eta - now).total_seconds() / 60

        # Fire "next task" notification once per runtime, only when <=5 min left
        if minutes_left <= 5 and self._next_task_notified_for != rt.id:
            plan = self.store.get_plan(today)
            if plan:
                # Find the first non-completed task AFTER the current one in plan order
                found_current = False
                next_task = None
                for t in plan.tasks:
                    if t.id == rt.plan_task_id:
                        found_current = True
                        continue
                    if found_current and not t.completed_at:
                        next_task = t
                        break
                if next_task:
                    notify(
                        "Focus Warden",
                        f"Next up in ~{max(int(minutes_left), 0)} min: {next_task.task_name}",
                    )
            self._next_task_notified_for = rt.id

        if self._eta_warning_shown_for == rt.id:
            return

        warning_at = eta - timedelta(minutes=5)
        if now < warning_at:
            return

        task_row = self.store.conn.execute(
            "SELECT task_name, duration_minutes FROM plan_tasks WHERE id = ?",
            (rt.plan_task_id,),
        ).fetchone()
        if not task_row:
            return

        task_name = task_row["task_name"]
        est_minutes = task_row["duration_minutes"]
        
        # Use configured default_extend_minutes if set, else fall back to original est
        extend_minutes = self.config.warden.default_extend_minutes or est_minutes
        
        self._eta_warning_shown_for = rt.id

        def on_decision(decision):
            self._eta_warning_popup = None
            try:
                if decision == DECISION_FINISH:
                    self.store.finish_task_runtime(today)
                    notify("Focus Warden", f"Finished: {task_name}")
                elif decision == DECISION_EXTEND:
                    self.store.extend_task_runtime(today, extend_minutes * 60)
                    self._eta_warning_shown_for = None
                    self._next_task_notified_for = None
                    notify("Focus Warden", f"Extended +{extend_minutes}m: {task_name}")
            except ValueError as e:
                log.warning("ETA warning action failed: %s", e)

        log.info("ETA warning for %s (eta=%s, extend=%dm)", task_name, eta.isoformat(timespec="seconds"), extend_minutes)
        self._eta_warning_popup = show_eta_warning(task_name, extend_minutes, on_decision)

    def _activate_item(self, item: ScheduleItem):
        log.info("Activating: %s (%s)", item.title, item.kind.value)
        self.current_item = item

        transitioned = True
        if item.kind == ScheduleKind.STRETCH:
            transitioned = self.sm.transition(State.AWAITING_BREAK_START)
        elif item.kind == ScheduleKind.TASK:
            transitioned = self.sm.transition(State.AWAITING_TASK_START)

        if not transitioned:
            return

        if self.config.ui.show_blocker_window:
            self._show_blocker(item)
            return

        self._on_confirmed()

    def _show_blocker(self, item: ScheduleItem):
        if self._window:
            self._window.close()
            self._window = None

        self._window = BlockerWindow(
            on_confirmed=self._on_confirmed,
            on_give_up=self._on_give_up,
        )
        self._window.set_item(item)
        self._window.show()

    def _on_confirmed(self):
        if not self.current_item:
            return
        kind = self.current_item.kind
        if kind == ScheduleKind.TASK:
            self.sm.transition(State.TASK_ACTIVE)
            self._task_started_at = datetime.now()
            self._stretch_lockout.start()
            task_row_id = self._task_rows.get(id(self.current_item))
            if task_row_id:
                task = Task(id=task_row_id, status=TaskStatus.ACTIVE, actual_start=self._task_started_at)
                self.db.update_task(task)

            if self.current_item.task_ref:
                self._current_work_block_id = self.store.start_time_block(
                    date.today(),
                    "work",
                    session_id=self.tracking_session_id,
                    plan_task_id=int(self.current_item.task_ref.id),
                    source="daemon",
                    started_at=self._task_started_at,
                    metadata={"title": self.current_item.title},
                )
                self.store.log_event(
                    date.today(),
                    "task_started",
                    session_id=self.tracking_session_id,
                    plan_task_id=int(self.current_item.task_ref.id),
                    source="daemon",
                    occurred_at=self._task_started_at,
                    metadata={"title": self.current_item.title},
                )

        elif kind == ScheduleKind.STRETCH:
            self.sm.transition(State.BREAK_ACTIVE)
            self.store.start_time_block(
                date.today(),
                "break",
                session_id=self.tracking_session_id,
                source="daemon",
                started_at=datetime.now(),
                metadata={"break_kind": "stretch"},
            )
            self.store.log_event(
                date.today(),
                "stretch_started",
                session_id=self.tracking_session_id,
                source="daemon",
            )

        self._item_finish_due_at = datetime.now() + timedelta(minutes=self.current_item.duration_minutes)

    def _pause_session(self, kind: str = "pause", message: str = "Paused"):
        if self.sm.state == State.PAUSED:
            return {"status": "already_paused"}

        self._previous_state_before_pause = self.sm.state.value
        if not self.sm.transition(State.PAUSED):
            return {"error": "cannot pause from current state"}

        now = datetime.now()

        self._stretch_lockout.pause()

        self._interruption = Interruption(
            session_id=self.session.id if self.session else None,
            kind=kind,
            started_at=now,
        )
        self._interruption.id = self.db.create_interruption(self._interruption)

        if self._current_work_block_id:
            self.store.finish_time_block(
                self._current_work_block_id,
                ended_at=now,
                metadata_patch={"ended_by": "pause"},
            )
            self._current_work_block_id = None

        block_type = "pause" if kind == "pause" else "call"
        event_type = "pause_started" if kind == "pause" else "call_started"

        self._current_pause_block_id = self.store.start_time_block(
            date.today(),
            block_type,
            session_id=self.tracking_session_id,
            source="daemon",
            started_at=now,
            metadata={"kind": kind},
        )
        self.store.log_event(
            date.today(),
            event_type,
            session_id=self.tracking_session_id,
            source="daemon",
            occurred_at=now,
            metadata={"kind": kind},
        )

        if self._window:
            self._window.allow_close()
            self._window.close()
            self._window = None

        notify("Focus Warden", message)
        return {"status": "paused"}

    def _resume_session(self):
        if self.sm.state != State.PAUSED:
            return {"error": "not paused"}
        pause_seconds = self.sm.pause_duration_seconds
        prev = self.sm.resume()
        now = datetime.now()

        self._stretch_lockout.resume()

        if prev and self._interruption:
            self._interruption.ended_at = now
            self._interruption.duration_minutes = pause_seconds / 60
            self.db.update_interruption(self._interruption)

            kind = self._interruption.kind
            event_type = "pause_ended" if kind == "pause" else "call_ended"
            self.store.log_event(
                date.today(),
                event_type,
                session_id=self.tracking_session_id,
                source="daemon",
                occurred_at=now,
                metadata={"kind": kind},
            )

            self._interruption = None

            if self._current_pause_block_id:
                self.store.finish_time_block(
                    self._current_pause_block_id,
                    ended_at=now,
                )
                self._current_pause_block_id = None

            if self._previous_state_before_pause == "task_active" and self.current_item and self.current_item.task_ref:
                self._current_work_block_id = self.store.start_time_block(
                    date.today(),
                    "work",
                    session_id=self.tracking_session_id,
                    plan_task_id=int(self.current_item.task_ref.id),
                    source="daemon",
                    started_at=now,
                    metadata={"title": self.current_item.title, "resumed_from": kind},
                )

            shift = timedelta(seconds=pause_seconds)
            for item in self.schedule:
                item.scheduled_start += shift
            if self._item_finish_due_at:
                self._item_finish_due_at += shift

        notify("Focus Warden", "Resumed")
        return {"status": "resumed", "previous_state": prev.value if prev else None, "pause_seconds": pause_seconds}

    def _on_item_finished(self):
        if not self.current_item:
            return
        log.info("Finished: %s", self.current_item.title)
        now = datetime.now()
        today = date.today()
        self._item_finish_due_at = None

        if self.current_item.kind == ScheduleKind.TASK:
            self._stretch_lockout.pause()
            task_row_id = self._task_rows.get(id(self.current_item))
            if task_row_id and self._task_started_at:
                actual_minutes = (now - self._task_started_at).total_seconds() / 60
                task = Task(
                    id=task_row_id,
                    actual_end=now,
                    actual_minutes=actual_minutes,
                    status=TaskStatus.COMPLETED,
                )
                self.db.update_task(task)

            if self._current_work_block_id:
                self.store.finish_time_block(self._current_work_block_id, ended_at=now)
                self._current_work_block_id = None

            if self.current_item.task_ref:
                self.store.log_event(
                    today,
                    "task_finished",
                    session_id=self.tracking_session_id,
                    plan_task_id=int(self.current_item.task_ref.id),
                    source="daemon",
                    occurred_at=now,
                    metadata={"title": self.current_item.title},
                )

            self._task_started_at = None

        elif self.current_item.kind == ScheduleKind.STRETCH:
            open_blocks = self.store.get_open_time_block(session_id=self.tracking_session_id, block_type="break")
            if open_blocks:
                self.store.finish_time_block(open_blocks.id, ended_at=now)

            self.store.log_event(
                today,
                "stretch_ended",
                session_id=self.tracking_session_id,
                source="daemon",
                occurred_at=now,
            )

        self.schedule.remove(self.current_item)
        self.current_item = None
        self._next_task_notified_for = None

        if self._window:
            self._window.close()
            self._window = None

        if not self.schedule or self.sm.state == State.FINISHED:
            self._finish_session()
        else:
            self.sm.transition(State.AWAITING_TASK_START)

    def _on_give_up(self):
        now = datetime.now()
        if self._give_up_last and (now - self._give_up_last).total_seconds() < self.config.warden.give_up_cooldown_seconds:
            notify("Focus Warden", f"Wait {self.config.warden.give_up_cooldown_seconds}s between attempts", "critical")
            return

        self._give_up_attempts += 1
        self._give_up_last = now
        notify("Focus Warden", f"Give up attempt {self._give_up_attempts}. Keep trying to give up.", "critical")

        if self._give_up_attempts >= 3:
            self._do_give_up()

    def _do_give_up(self):
        log.info("Session given up")
        self.sm.transition(State.GIVEN_UP)
        self._stretch_lockout.stop()
        self._shutdown_warning_until = None
        self._item_finish_due_at = None
        self._auto_paused_by_mic = False
        now = datetime.now()

        if self.tracking_session_id:
            self.store.close_open_blocks(date.today(), ended_at=now, reason="give_up")
            self.store.finish_session_v2(self.tracking_session_id, status="abandoned", ended_at=now)
            self.store.log_event(date.today(), "session_abandoned", session_id=self.tracking_session_id, source="daemon", occurred_at=now)

        if self.session:
            self.session.status = SessionStatus.GIVEN_UP
            self.session.ended_at = now
            self.db.update_session(self.session)
        if self._window:
            self._window.allow_close()
            self._window.close()
            self._window = None
        notify("Focus Warden", "Session abandoned. See you tomorrow.", "critical")
        self._running = False

    def _finish_session(self):
        log.info("Session finished")
        self.sm.transition(State.FINISHED)
        self._stretch_lockout.stop()
        self._shutdown_warning_until = None
        self._item_finish_due_at = None
        self._auto_paused_by_mic = False
        now = datetime.now()

        if self.tracking_session_id:
            self.store.close_open_blocks(date.today(), ended_at=now, reason="session_finished")
            self.store.finish_session_v2(self.tracking_session_id, status="finished", ended_at=now)
            self.store.log_event(date.today(), "session_finished", session_id=self.tracking_session_id, source="daemon", occurred_at=now)

        if self.session:
            self.session.status = SessionStatus.FINISHED
            self.session.ended_at = now
            self.db.update_session(self.session)
        notify("Focus Warden", "All tasks complete!")
        self._running = False

    def _shutdown(self):
        log.info("Hard shutdown triggered")
        self.sm.transition(State.FINISHED)
        self._stretch_lockout.stop()
        self._shutdown_warning_until = None
        self._item_finish_due_at = None
        self._auto_paused_by_mic = False
        now = datetime.now()

        if self.tracking_session_id:
            self.store.close_open_blocks(date.today(), ended_at=now, reason="shutdown")
            self.store.finish_session_v2(self.tracking_session_id, status="shutdown", ended_at=now)
            self.store.log_event(date.today(), "session_shutdown", session_id=self.tracking_session_id, source="daemon", occurred_at=now)

        if self.session:
            self.session.status = SessionStatus.FINISHED
            self.session.ended_at = now
            self.db.update_session(self.session)
        notify("Focus Warden", "Hard shutdown — powering off", "critical")
        self._running = False
        subprocess.run(["systemctl", "poweroff"], check=False)

    def _handle_command(self, cmd: dict) -> dict:
        command = cmd.get("command", "")
        self.db.log_control_event(
            self.session.id if self.session else None,
            command,
            str(cmd),
        )

        if command == "start_task":
            return self._handle_start_task(cmd)

        if command == "pause_task":
            return self._handle_pause_task(cmd)

        if command == "resume_task":
            return self._handle_resume_task(cmd)

        if command == "finish_task":
            return self._handle_finish_task(cmd)

        if command == "extend_task":
            return self._handle_extend_task(cmd)

        if command == "pause":
            self._auto_paused_by_mic = False
            return self._pause_session()

        elif command == "resume":
            self._auto_paused_by_mic = False
            return self._resume_session()

        elif command == "give_up":
            self._do_give_up()
            return {"status": "given_up"}

        elif command == "status":
            return self._build_status()

        return {"error": f"unknown command: {command}"}

    def _handle_start_task(self, cmd: dict) -> dict:
        try:
            target_str = cmd.get("target_date", date.today().isoformat())
            target_date = date.fromisoformat(target_str)
            plan_task_id = int(cmd["plan_task_id"])
        except (KeyError, ValueError) as e:
            return {"error": f"Invalid start_task params: {e}"}

        try:
            self.store.get_or_start_session_v2(target_date, source="daemon")
            rt = self.store.start_task_runtime(target_date, plan_task_id, source="daemon")
        except ValueError as e:
            return {"error": str(e)}

        if self.sm.state not in (State.GIVEN_UP, State.FINISHED):
            self.sm.transition(State.TASK_ACTIVE)
            self._task_started_at = datetime.now()
            self._stretch_lockout.start()

        return {"status": "task_started", "runtime_id": rt.id, "task_name": self.conn_task_name(plan_task_id)}

    def conn_task_name(self, plan_task_id: int) -> str:
        row = self.store.conn.execute("SELECT task_name FROM plan_tasks WHERE id = ?", (plan_task_id,)).fetchone()
        return row["task_name"] if row else ""

    def _handle_pause_task(self, cmd: dict) -> dict:
        reason = cmd.get("reason", "manual")
        target_date = date.today()
        try:
            rt = self.store.pause_task_runtime(target_date, reason=reason, source="daemon")
        except ValueError as e:
            return {"error": str(e)}

        self._auto_paused_by_mic = False
        if self.sm.state not in (State.GIVEN_UP, State.FINISHED):
            self._previous_state_before_pause = self.sm.state.value
            self.sm.transition(State.PAUSED)
            self._stretch_lockout.pause()

        return {"status": "paused", "runtime_id": rt.id}

    def _handle_resume_task(self, cmd: dict) -> dict:
        target_date = date.today()
        try:
            rt = self.store.resume_task_runtime(target_date, source="daemon")
        except ValueError as e:
            return {"error": str(e)}

        self._auto_paused_by_mic = False
        if self.sm.state == State.PAUSED:
            self.sm.resume()
            self._stretch_lockout.resume()

        return {"status": "resumed", "runtime_id": rt.id}

    def _handle_finish_task(self, cmd: dict) -> dict:
        outcome = cmd.get("outcome", "finished")
        notes = cmd.get("notes", "")
        target_date = date.today()
        try:
            rt = self.store.finish_task_runtime(target_date, outcome=outcome, notes=notes)
        except ValueError as e:
            return {"error": str(e)}

        if self.sm.state not in (State.GIVEN_UP, State.FINISHED):
            self.sm.transition(State.AWAITING_TASK_START)
            self._stretch_lockout.pause()
            self._next_task_notified_for = None

        return {"status": "task_finished", "runtime_id": rt.id}

    def _handle_extend_task(self, cmd: dict) -> dict:
        extra_seconds = cmd.get("extra_seconds", 0)
        if not extra_seconds:
            return {"error": "extra_seconds required"}
        target_date = date.today()
        try:
            rt = self.store.extend_task_runtime(target_date, extra_seconds)
        except ValueError as e:
            return {"error": str(e)}
        self._eta_warning_shown_for = None
        return {"status": "extended", "runtime_id": rt.id, "new_estimated": rt.estimated_seconds}

    def _build_status(self) -> dict:
        now = datetime.now()
        today = date.today()
        runtime = self.store.get_active_task_runtime(today)

        current_index = None
        if self.current_item is not None:
            for idx, item in enumerate(self.schedule):
                if item is self.current_item:
                    current_index = idx
                    break

        next_item = None
        if current_index is not None and current_index + 1 < len(self.schedule):
            next_item = self.schedule[current_index + 1]

        runtime_payload = None
        if runtime:
            eta = runtime.compute_eta(now)
            runtime_payload = {
                "id": runtime.id,
                "plan_task_id": runtime.plan_task_id,
                "status": runtime.status,
                "started_at": runtime.started_at,
                "paused_at": runtime.paused_at,
                "estimated_seconds": runtime.estimated_seconds,
                "accumulated_pause_seconds": runtime.accumulated_pause_seconds,
                "actual_work_seconds": runtime.actual_work_seconds(now),
                "eta": eta.isoformat(timespec="seconds"),
            }

        return {
            "state": self.sm.state.value,
            "session_status": self.session.status.value if self.session else None,
            "task_runtime": runtime_payload,
            "current_item": {
                "title": self.current_item.title,
                "kind": self.current_item.kind.value,
                "scheduled_start": self.current_item.scheduled_start.isoformat(timespec="seconds"),
                "duration_minutes": self.current_item.duration_minutes,
            }
            if self.current_item
            else None,
            "next_item": {
                "title": next_item.title,
                "kind": next_item.kind.value,
                "scheduled_start": next_item.scheduled_start.isoformat(timespec="seconds"),
                "duration_minutes": next_item.duration_minutes,
            }
            if next_item
            else None,
            "remaining_items": len(self.schedule),
            "session_id": self.session.id if self.session else None,
            "auto_paused_by_mic": self._auto_paused_by_mic,
            "mic_active_since": self._mic_active_since.isoformat(timespec="seconds")
            if self._mic_active_since
            else None,
            "mic_inactive_since": self._mic_inactive_since.isoformat(timespec="seconds")
            if self._mic_inactive_since
            else None,
            "bootstrap_error": self._bootstrap_error,
            "next_bootstrap_retry_at": self._next_bootstrap_retry_at.isoformat(timespec="seconds")
            if self._next_bootstrap_retry_at
            else None,
            "shutdown_warning_until": self._shutdown_warning_until.isoformat(timespec="seconds")
            if self._shutdown_warning_until
            else None,
            "shutdown_warning_seconds_remaining": max(
                int((self._shutdown_warning_until - now).total_seconds()),
                0,
            )
            if self._shutdown_warning_until
            else None,
        }
