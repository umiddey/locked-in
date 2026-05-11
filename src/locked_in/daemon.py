from __future__ import annotations

import logging
import os
import re
import subprocess
import time
from datetime import date, datetime, timedelta
from queue import Queue, Empty

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
from .eta_warning import show_eta_warning, DECISION_FINISH, DECISION_EXTEND, DECISION_AUTO_CONTINUE
from .notifications import notify
from .scheduler import build_schedule
from .state_machine import StateMachine
from .simple_store import SimpleTodoStore
from .stretch_lockout import StretchLockout
from .ui import BlockerWindow, create_app
from .services import Event, EventType, TickService, IdleService, MicService

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
        
        self.event_queue = Queue()
        
        # Load custom thresholds from config
        soft_thresh = {
            "i8042": config.auto_pause.soft_threshold_i8042,
            "xhci_hcd": config.auto_pause.soft_threshold_xhci_hcd
        }
        hard_thresh = {
            "i8042": config.auto_pause.hard_threshold_i8042,
            "xhci_hcd": config.auto_pause.hard_threshold_xhci_hcd
        }
        
        self._idle_detector = IdleDetector(
            idle_seconds=config.auto_pause.idle_pause_seconds,
            soft_thresholds=soft_thresh,
            hard_thresholds=hard_thresh
        )
        self._mic_detector = MicActivityDetector(
            config.auto_pause.call_apps,
            config.auto_pause.ignored_apps,
        )
        
        self.services = [
            TickService(self.event_queue),
            IdleService(self.event_queue, self._idle_detector),
            MicService(self.event_queue, self._mic_detector, config.auto_pause.poll_seconds)
        ]

        self._auto_paused_by_mic = False
        self._mic_active_since: datetime | None = None
        self._mic_inactive_since: datetime | None = None
        self._auto_paused_by_idle = False
        self._idle_resume_events: list[datetime] = []
        self._last_activity_seconds: float = 0.0
        self._eta_warning_shown_for: int | None = None
        self._eta_warning_popup = None
        self._next_task_notified_for: int | None = None
        self._auto_chain_next: bool = False
        self._running = False
        self._app = None
        self._window: BlockerWindow | None = None
        self.tracking_session_id: int | None = None
        self._daemon_pause_block_id: int | None = None
        self._previous_state_before_pause: str | None = None
        self._stretch_lockout = StretchLockout(
            interval_minutes=config.stretch_lockout.interval_minutes,
            duration_minutes=config.stretch_lockout.duration_minutes,
        ) if config.stretch_lockout.enabled else None

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

        for service in self.services:
            service.start()

        log.info("Daemon started with %d decoupled services", len(self.services))

        try:
            while self._running:
                try:
                    event = self.event_queue.get(timeout=0.05)
                    self._handle_event(event)
                except Empty:
                    pass

                ctrl.poll()
                self._app.processEvents()
        finally:
            for service in self.services:
                service.stop()
            ctrl.close()
            self.db.close()

    def _handle_event(self, event: Event):
        if event.type == EventType.TICK:
            self._tick_logic()
        elif event.type == EventType.USER_ACTIVITY_HARD:
            self._handle_hard_activity(event.timestamp)
        elif event.type == EventType.MIC_ACTIVE:
            self._handle_mic_state(active=True, apps=event.data.get("apps", []), now=event.timestamp)
        elif event.type == EventType.MIC_SILENT:
            self._handle_mic_state(active=False, apps=[], now=event.timestamp)

    def _tick_logic(self):
        if self.sm.state in (State.GIVEN_UP, State.FINISHED):
            self._running = False
            return

        if self._stretch_lockout: self._stretch_lockout.tick()
        now = datetime.now()

        if self.session is None:
            if self._next_bootstrap_retry_at is None or now >= self._next_bootstrap_retry_at:
                self._bootstrap_session()
            if self.session is None:
                return

        self._check_idle_pause(now)
        self._poll_eta_warning(now)
        self._check_hard_shutdown(now)
        self._check_schedule(now)

    def _check_idle_pause(self, now: datetime):
        config = self.config.auto_pause
        if not config.enabled or config.idle_pause_seconds <= 0 or self.sm.state != State.TASK_ACTIVE:
            return

        idle_secs = self._idle_detector.seconds_since_any_activity()
        self._last_activity_seconds = idle_secs

        if idle_secs >= config.idle_pause_seconds and not self._auto_paused_by_idle:
            today = date.today()
            runtime = self.store.get_active_task_runtime(today)
            if runtime and runtime.status == "running":
                try:
                    self.store.pause_task_runtime(today, reason="idle", source="idle")
                    self._auto_paused_by_idle = True
                    self.sm.transition(State.PAUSED)
                    if self._stretch_lockout: self._stretch_lockout.pause()
                    notify("Locked-In", f"Paused — idle for {int(idle_secs)}s")
                except ValueError: pass

    def _get_active_work_block_id(self, today: date) -> int | None:
        """Read active work block ID from store (single source of truth)."""
        rt = self.store.get_active_task_runtime(today)
        return rt.active_work_block_id if rt else None

    def _handle_hard_activity(self, now: datetime):
        if self.sm.state != State.PAUSED or not self._auto_paused_by_idle:
            return
        config = self.config.auto_pause
        if self._idle_detector.seconds_since_hard_activity() < max(config.idle_resume_grace_seconds, 1):
            self._idle_resume_events.append(now)
            cutoff = now - timedelta(seconds=30)
            self._idle_resume_events = [t for t in self._idle_resume_events if t >= cutoff]
            if len(self._idle_resume_events) >= 5:
                today = date.today()
                runtime = self.store.get_active_task_runtime(today)
                if runtime and runtime.status == "paused":
                    try:
                        resumed_rt = self.store.resume_task_runtime(today, source="idle")
                        self._auto_paused_by_idle = False
                        if self.sm.state == State.PAUSED: self.sm.resume()
                        if self._stretch_lockout: self._stretch_lockout.resume()
                        self._idle_resume_events.clear()
                        notify("Locked-In", "Resumed — welcome back!")
                    except ValueError: pass
                else:
                    self._auto_paused_by_idle = False
                    self._idle_resume_events.clear()

    def _handle_mic_state(self, active: bool, apps: list[str], now: datetime):
        config = self.config.auto_pause
        if not config.enabled or self.sm.state in (State.GIVEN_UP, State.FINISHED): return
        if active:
            self._mic_inactive_since = None
            if self._mic_active_since is None: self._mic_active_since = now
            if not self._auto_paused_by_mic and self.sm.state != State.PAUSED and (now - self._mic_active_since).total_seconds() >= config.mic_active_seconds:
                today = date.today(); runtime = self.store.get_active_task_runtime(today)
                if runtime and runtime.status == "running":
                    try:
                        self.store.pause_task_runtime(today, reason="mic", source="mic")
                        self._auto_paused_by_mic = True; self.sm.transition(State.PAUSED); self._stretch_lockout.pause() if self._stretch_lockout else None
                        log.info("Auto-paused for mic: %s", ", ".join(apps))
                        notify("Locked-In", f"Paused for microphone use: {', '.join(apps)}")
                    except ValueError: pass
                else:
                    res = self._pause_session(kind="call_detected", message=f"Paused for mic: {', '.join(apps)}")
                    if "error" not in res: self._auto_paused_by_mic = True
        else:
            self._mic_active_since = None
            if self._auto_paused_by_mic:
                if self._mic_inactive_since is None: self._mic_inactive_since = now
                if (now - self._mic_inactive_since).total_seconds() >= config.resume_after_silence_seconds:
                    today = date.today(); runtime = self.store.get_active_task_runtime(today)
                    if runtime and runtime.status == "paused":
                        try:
                            resumed_rt = self.store.resume_task_runtime(today, source="mic")
                            self._auto_paused_by_mic = False; self._mic_inactive_since = None
                            if self.sm.state == State.PAUSED: self.sm.resume()
                            self._stretch_lockout.resume() if self._stretch_lockout else None; self._recover_active_task(today)
                            log.info("Auto-resumed after mic silence"); notify("Locked-In", "Resumed")
                        except ValueError: pass
                    else:
                        res = self._resume_session()
                        if "error" not in res: self._auto_paused_by_mic = False; self._mic_inactive_since = None; self._recover_active_task(today)

    def _check_hard_shutdown(self, now: datetime):
        if not self.config.schedule.hard_shutdown_enabled: return
        if self._shutdown_warning_until is not None:
            if now >= self._shutdown_warning_until: self._shutdown()
            return
        warning_start = self.session.shutdown_deadline - timedelta(minutes=self.config.schedule.shutdown_warning_minutes)
        if now >= warning_start:
            if now >= self.session.shutdown_deadline: self._shutdown_warning_until = now + timedelta(minutes=self.config.schedule.shutdown_warning_minutes)
            else: self._shutdown_warning_until = self.session.shutdown_deadline
            log.warning("Hard shutdown warning; until=%s", self._shutdown_warning_until.isoformat(timespec="seconds"))
            notify("Locked-In", f"Hard shutdown in {self.config.schedule.shutdown_warning_minutes} min.", "critical")

    def _check_schedule(self, now: datetime):
        if self.current_item is None or self.sm.state in (State.IDLE, State.AWAITING_TASK_START, State.TASK_ACTIVE):
            for item in self.schedule:
                if now >= item.scheduled_start:
                    if item.kind == ScheduleKind.SHUTDOWN_WARNING:
                        notify("Locked-In", f"WARNING: Shutdown in {self.config.schedule.shutdown_warning_minutes} min!", "critical")
                        self.schedule.remove(item); break
                    if item.kind == ScheduleKind.SHUTDOWN: self._shutdown(); return
                    if self.current_item != item: self._activate_item(item)
                    break
        if self.current_item and self._item_finish_due_at and now >= self._item_finish_due_at and self.sm.state == State.TASK_ACTIVE:
            self._on_item_finished()
            return
        if self.session and self.config.schedule.hard_shutdown_enabled and now >= self.session.shutdown_deadline: self._shutdown()

    def _start_session(self, plan):
        now = datetime.now(); today = date.today()
        session_started_at = self.store.ensure_session(today, now)
        self.tracking_session_id = self.store.start_session_v2(today, now, source="daemon")
        self.store.log_event(today, "session_started", session_id=self.tracking_session_id, source="daemon", occurred_at=now)
        shutdown_parts = self.config.schedule.hard_shutdown_time.split(":")
        shutdown_deadline = now.replace(hour=int(shutdown_parts[0]), minute=int(shutdown_parts[1]), second=0, microsecond=0)
        if shutdown_deadline <= now: shutdown_deadline += timedelta(days=1)
        self.session = Session(started_at=session_started_at, shutdown_deadline=shutdown_deadline, status=SessionStatus.ACTIVE)
        self.session.id = self.db.create_session(self.session)
        completed_task_ids = self._completed_task_ids_for_session_start(session_started_at)
        tasks = [NormalizedTask(id=str(t.id), title=t.task_name, normalized_key=_normalize_key(t.task_name), estimate_minutes=t.duration_minutes, due_date=plan.target_date) for t in plan.tasks if str(t.id) not in completed_task_ids]
        self.schedule = build_schedule(tasks, session_started_at, self.config.schedule, grace_seconds=self.config.warden.task_start_grace_seconds)
        for item in self.schedule:
            if item.kind == ScheduleKind.TASK and item.task_ref:
                row_id = self.db.create_task(Task(session_id=self.session.id, notion_task_id=item.task_ref.id, title=item.title, normalized_key=item.task_ref.normalized_key, scheduled_start=item.scheduled_start, scheduled_duration_minutes=item.duration_minutes, status=TaskStatus.PENDING))
                self._task_rows[id(item)] = row_id
        self.sm.transition(State.AWAITING_TASK_START); self._recover_active_task(today)

    def _recover_active_task(self, today) -> None:
        """Recover a running OR paused task after daemon restart."""
        existing_runtime = self.store.get_active_task_runtime(today)
        if not existing_runtime or existing_runtime.status not in ("running", "paused") or self.current_item is not None: return
        target_id = str(existing_runtime.plan_task_id)
        is_paused = existing_runtime.status == "paused"
        started_dt = datetime.fromisoformat(existing_runtime.started_at)

        def _apply_recovery(item):
            self.current_item = item; self._task_started_at = started_dt; self._item_finish_due_at = existing_runtime.compute_eta()
            self.sm.transition(State.AWAITING_TASK_START)
            if is_paused:
                self.sm.transition(State.TASK_ACTIVE); self.sm.transition(State.PAUSED)
                self._auto_paused_by_idle = True
            else:
                self.sm.transition(State.TASK_ACTIVE)
                if self._stretch_lockout: self._stretch_lockout.start()

        for item in self.schedule:
            if item.kind == ScheduleKind.TASK and item.task_ref and item.task_ref.id == target_id:
                _apply_recovery(item); return
        plan = self.store.get_plan(today); plan_task = next((pt for pt in plan.tasks if str(pt.id) == target_id), None) if plan else None
        if plan_task:
            synthetic = ScheduleItem(kind=ScheduleKind.TASK, title=plan_task.task_name, scheduled_start=started_dt, duration_minutes=max(1, int(existing_runtime.estimated_seconds / 60)), task_ref=NormalizedTask(id=str(plan_task.id), title=plan_task.task_name, normalized_key=plan_task.task_name.lower().strip(), estimate_minutes=plan_task.duration_minutes, due_date=today))
            self.schedule.insert(0, synthetic)
            _apply_recovery(synthetic)

    def _bootstrap_session(self) -> bool:
        today = date.today(); plan = self.store.get_plan(today)
        if not plan or not plan.tasks: self._bootstrap_error = None; return False
        try: self._start_session(plan)
        except Exception as e:
            msg = str(e); log.error("Failed to start session: %s", e)
            self._bootstrap_error = msg; self._next_bootstrap_retry_at = datetime.now() + timedelta(minutes=5); notify("Locked-In Error", msg, "critical"); return False
        self._bootstrap_error = None; return True

    def _poll_eta_warning(self, now: datetime):
        today = date.today(); rt = self.store.get_active_task_runtime(today)
        if not rt or rt.status != "running": self._eta_warning_shown_for = None; return
        eta = rt.compute_eta(now); min_left = (eta - now).total_seconds() / 60

        # Notify about next task at 5 min mark
        if min_left <= 5 and self._next_task_notified_for != rt.id:
            plan = self.store.get_plan(today)
            if plan:
                found = False; next_t = None
                for t in plan.tasks:
                    if t.id == rt.plan_task_id: found = True; continue
                    if found and not t.completed_at: next_t = t; break
                if next_t: notify("Locked-In", f"Next up in ~{max(int(min_left), 0)} min: {next_t.task_name}")
            self._next_task_notified_for = rt.id

        # Show popup once at 5 min before ETA
        if self._eta_warning_shown_for == rt.id or now < (eta - timedelta(minutes=5)): return
        row = self.store.conn.execute("SELECT task_name, duration_minutes FROM plan_tasks WHERE id = ?", (rt.plan_task_id,)).fetchone()
        if not row: return
        name = row["task_name"]; ext_min = self.config.warden.default_extend_minutes or row["duration_minutes"]

        # Find next task name for popup label
        plan = self.store.get_plan(today)
        next_task_name = None
        if plan:
            found = False
            for t in plan.tasks:
                if t.id == rt.plan_task_id: found = True; continue
                if found and not t.completed_at: next_task_name = t.task_name; break

        self._eta_warning_shown_for = rt.id

        def on_decision(decision):
            self._eta_warning_popup = None
            try:
                if decision == DECISION_AUTO_CONTINUE:
                    self._auto_chain_next = True
                    notify("Locked-In", f"Auto-continue ON — will start next task after {name}")
                elif decision == DECISION_FINISH:
                    self.store.finish_task_runtime(today); notify("Locked-In", f"Finished: {name}")
                elif decision == DECISION_EXTEND:
                    self.store.extend_task_runtime(today, ext_min * 60)
                    self._eta_warning_shown_for = None; self._next_task_notified_for = None
                    notify("Locked-In", f"Extended +{ext_min}m: {name}")
            except Exception as e: log.warning("ETA action failed: %s", e)

        self._eta_warning_popup = show_eta_warning(name, ext_min, on_decision,
                                                    next_task_name=next_task_name, eta=eta)

    def _activate_item(self, item: ScheduleItem):
        log.info("Activating: %s", item.title); self.current_item = item
        trans = self.sm.transition(State.AWAITING_TASK_START)
        if not trans: return
        if self.config.ui.show_blocker_window:
            if self._window: self._window.close()
            self._window = BlockerWindow(on_confirmed=self._on_confirmed, on_give_up=self._on_give_up); self._window.set_item(item); self._window.show()
        else: self._on_confirmed()

    def _on_confirmed(self):
        if not self.current_item: return
        self.sm.transition(State.TASK_ACTIVE); self._task_started_at = datetime.now(); self._stretch_lockout.start() if self._stretch_lockout else None
        task_row_id = self._task_rows.get(id(self.current_item))
        if task_row_id: self.db.update_task(Task(id=task_row_id, status=TaskStatus.ACTIVE, actual_start=self._task_started_at))
        if self.current_item.task_ref:
            # Check if store already has an active work block (e.g. web-started task)
            today = date.today()
            rt = self.store.get_active_task_runtime(today)
            if not (rt and rt.active_work_block_id):
                self.store.start_time_block(today, "work", session_id=self.tracking_session_id, plan_task_id=int(self.current_item.task_ref.id), source="daemon", started_at=self._task_started_at, metadata={"title": self.current_item.title})
            self.store.log_event(today, "task_started", session_id=self.tracking_session_id, plan_task_id=int(self.current_item.task_ref.id), source="daemon", occurred_at=self._task_started_at, metadata={"title": self.current_item.title})
        self._item_finish_due_at = datetime.now() + timedelta(minutes=self.current_item.duration_minutes)

    def _pause_session(self, kind: str = "pause", message: str = "Paused"):
        if self.sm.state == State.PAUSED: return {"status": "already_paused"}
        self._previous_state_before_pause = self.sm.state.value
        if not self.sm.transition(State.PAUSED): return {"error": "cannot pause"}
        now = datetime.now(); today = date.today(); self._stretch_lockout.pause() if self._stretch_lockout else None
        self._interruption = Interruption(session_id=self.session.id if self.session else None, kind=kind, started_at=now)
        self._interruption.id = self.db.create_interruption(self._interruption)
        # Read active work block from store (single source of truth)
        work_block_id = self._get_active_work_block_id(today)
        if work_block_id: self.store.finish_time_block(work_block_id, ended_at=now, metadata_patch={"ended_by": "pause"})
        pause_block_id = self.store.start_time_block(today, "pause" if kind == "pause" else "call", session_id=self.tracking_session_id, source="daemon", started_at=now, metadata={"kind": kind})
        self._daemon_pause_block_id = pause_block_id
        self.store.log_event(today, "pause_started" if kind == "pause" else "call_started", session_id=self.tracking_session_id, source="daemon", occurred_at=now, metadata={"kind": kind})
        if self._window: self._window.allow_close(); self._window.close(); self._window = None
        notify("Locked-In", message); return {"status": "paused"}

    def _resume_session(self):
        if self.sm.state != State.PAUSED: return {"error": "not paused"}
        pause_sec = self.sm.pause_duration_seconds; prev = self.sm.resume(); now = datetime.now(); today = date.today(); self._stretch_lockout.resume() if self._stretch_lockout else None
        if prev and self._interruption:
            self._interruption.ended_at = now; self._interruption.duration_minutes = pause_sec / 60; self.db.update_interruption(self._interruption)
            self.store.log_event(today, "pause_ended" if self._interruption.kind == "pause" else "call_ended", session_id=self.tracking_session_id, source="daemon", occurred_at=now, metadata={"kind": self._interruption.kind})
            self._interruption = None
            if self._daemon_pause_block_id: self.store.finish_time_block(self._daemon_pause_block_id, ended_at=now); self._daemon_pause_block_id = None
            if self._previous_state_before_pause == "task_active" and self.current_item and self.current_item.task_ref:
                self.store.start_time_block(today, "work", session_id=self.tracking_session_id, plan_task_id=int(self.current_item.task_ref.id), source="daemon", started_at=now, metadata={"title": self.current_item.title})
            shift = timedelta(seconds=pause_sec)
            for item in self.schedule: item.scheduled_start += shift
            if self._item_finish_due_at: self._item_finish_due_at += shift
        notify("Locked-In", "Resumed"); return {"status": "resumed", "previous_state": prev.value if prev else None, "pause_seconds": pause_sec}

    def _on_item_finished(self):
        if not self.current_item: return
        now = datetime.now(); today = date.today(); self._item_finish_due_at = None
        should_chain = self._auto_chain_next
        if self._stretch_lockout: self._stretch_lockout.pause()
        task_row_id = self._task_rows.get(id(self.current_item))
        if task_row_id and self._task_started_at: self.db.update_task(Task(id=task_row_id, actual_end=now, actual_minutes=(now - self._task_started_at).total_seconds() / 60, status=TaskStatus.COMPLETED))
        # Read active work block from store (single source of truth)
        work_block_id = self._get_active_work_block_id(today)
        if work_block_id: self.store.finish_time_block(work_block_id, ended_at=now)
        if self.current_item.task_ref: self.store.log_event(today, "task_finished", session_id=self.tracking_session_id, plan_task_id=int(self.current_item.task_ref.id), source="daemon", occurred_at=now, metadata={"title": self.current_item.title})
        finished_item = self.current_item
        self._task_started_at = None
        if finished_item in self.schedule: self.schedule.remove(finished_item)
        self.current_item = None; self._next_task_notified_for = None; self._auto_chain_next = False
        if self._window: self._window.close(); self._window = None
        if not self.schedule or self.sm.state == State.FINISHED: self._finish_session()
        elif should_chain:
            # Auto-chain: find next task item and activate immediately
            next_item = next((item for item in self.schedule if item.kind == ScheduleKind.TASK), None)
            if next_item:
                log.info("Auto-chaining to next task: %s", next_item.title)
                self.sm.transition(State.AWAITING_TASK_START)
                self._activate_item(next_item)
            else:
                self.sm.transition(State.AWAITING_TASK_START)
        else: self.sm.transition(State.AWAITING_TASK_START)

    def _on_give_up(self):
        now = datetime.now()
        if self._give_up_last and (now - self._give_up_last).total_seconds() < self.config.warden.give_up_cooldown_seconds: notify("Locked-In", f"Wait {self.config.warden.give_up_cooldown_seconds}s", "critical"); return
        self._give_up_attempts += 1; self._give_up_last = now; notify("Locked-In", f"Give up {self._give_up_attempts}/3", "critical")
        if self._give_up_attempts >= 3: self._do_give_up()

    def _do_give_up(self):
        self.sm.transition(State.GIVEN_UP); self._stretch_lockout.stop() if self._stretch_lockout else None; now = datetime.now()
        if self.tracking_session_id: self.store.close_open_blocks(date.today(), ended_at=now, reason="give_up"); self.store.finish_session_v2(self.tracking_session_id, status="abandoned", ended_at=now); self.store.log_event(date.today(), "session_abandoned", session_id=self.tracking_session_id, source="daemon", occurred_at=now)
        if self.session: self.session.status = SessionStatus.GIVEN_UP; self.session.ended_at = now; self.db.update_session(self.session)
        if self._window: self._window.allow_close(); self._window.close(); self._window = None
        notify("Locked-In", "Abandoned.", "critical"); self._running = False

    def _finish_session(self):
        self.sm.transition(State.FINISHED); self._stretch_lockout.stop() if self._stretch_lockout else None; now = datetime.now()
        if self.tracking_session_id: self.store.close_open_blocks(date.today(), ended_at=now, reason="session_finished"); self.store.finish_session_v2(self.tracking_session_id, status="finished", ended_at=now); self.store.log_event(date.today(), "session_finished", session_id=self.tracking_session_id, source="daemon", occurred_at=now)
        if self.session: self.session.status = SessionStatus.FINISHED; self.session.ended_at = now; self.db.update_session(self.session)
        notify("Locked-In", "All clear!"); self._running = False

    def _shutdown(self):
        self.sm.transition(State.FINISHED); self._stretch_lockout.stop() if self._stretch_lockout else None; now = datetime.now()
        if self.tracking_session_id: self.store.close_open_blocks(date.today(), ended_at=now, reason="shutdown"); self.store.finish_session_v2(self.tracking_session_id, status="shutdown", ended_at=now); self.store.log_event(date.today(), "session_shutdown", session_id=self.tracking_session_id, source="daemon", occurred_at=now)
        if self.session: self.session.status = SessionStatus.FINISHED; self.session.ended_at = now; self.db.update_session(self.session)
        notify("Locked-In", "Shutting down.", "critical"); self._running = False; subprocess.run(["systemctl", "poweroff"], check=False)

    def _handle_command(self, cmd: dict) -> dict:
        command = cmd.get("command", "")
        self.db.log_control_event(self.session.id if self.session else None, command, str(cmd))
        if command == "start_task": return self._handle_start_task(cmd)
        if command == "pause_task": return self._handle_pause_task(cmd)
        if command == "resume_task": return self._handle_resume_task(cmd)
        if command == "finish_task": return self._handle_finish_task(cmd)
        if command == "extend_task": return self._handle_extend_task(cmd)
        if command == "set_auto_chain": self._auto_chain_next = bool(cmd.get("enabled", False)); return {"status": "ok", "auto_chain_next": self._auto_chain_next}
        if command == "pause": self._auto_paused_by_mic = False; return self._pause_session()
        if command == "resume": self._auto_paused_by_mic = False; return self._resume_session()
        if command == "give_up": self._do_give_up(); return {"status": "given_up"}
        if command == "status": return self._build_status()
        return {"error": f"unknown: {command}"}

    def _handle_start_task(self, cmd: dict) -> dict:
        try:
            target = date.fromisoformat(cmd.get("target_date", date.today().isoformat()))
            plan_task_id = int(cmd["plan_task_id"])
            self.store.get_or_start_session_v2(target, source="daemon")
            rt = self.store.start_task_runtime(target, plan_task_id, source="daemon")
        except Exception as e: return {"error": str(e)}
        if self.sm.state not in (State.GIVEN_UP, State.FINISHED): self.sm.transition(State.TASK_ACTIVE); self._task_started_at = datetime.now(); self._stretch_lockout.start() if self._stretch_lockout else None
        return {"status": "started", "runtime_id": rt.id, "task_name": self.conn_task_name(plan_task_id)}

    def conn_task_name(self, plan_task_id: int) -> str:
        row = self.store.conn.execute("SELECT task_name FROM plan_tasks WHERE id = ?", (plan_task_id,)).fetchone()
        return row["task_name"] if row else ""

    def _handle_pause_task(self, cmd: dict) -> dict:
        try: rt = self.store.pause_task_runtime(date.today(), reason=cmd.get("reason", "manual"), source="daemon")
        except Exception as e: return {"error": str(e)}
        self._auto_paused_by_mic = False
        if self.sm.state not in (State.GIVEN_UP, State.FINISHED): self._previous_state_before_pause = self.sm.state.value; self.sm.transition(State.PAUSED); self._stretch_lockout.pause() if self._stretch_lockout else None
        return {"status": "paused", "runtime_id": rt.id}

    def _handle_resume_task(self, cmd: dict) -> dict:
        try: rt = self.store.resume_task_runtime(date.today(), source="daemon")
        except Exception as e: return {"error": str(e)}
        self._auto_paused_by_mic = False
        if self.sm.state == State.PAUSED: self.sm.resume(); self._stretch_lockout.resume() if self._stretch_lockout else None
        return {"status": "resumed", "runtime_id": rt.id}

    def _handle_finish_task(self, cmd: dict) -> dict:
        try: rt = self.store.finish_task_runtime(date.today(), outcome=cmd.get("outcome", "finished"), notes=cmd.get("notes", ""))
        except Exception as e: return {"error": str(e)}
        if self.sm.state not in (State.GIVEN_UP, State.FINISHED): self.sm.transition(State.AWAITING_TASK_START); self._stretch_lockout.pause() if self._stretch_lockout else None; self._next_task_notified_for = None
        return {"status": "finished", "runtime_id": rt.id}

    def _handle_extend_task(self, cmd: dict) -> dict:
        try:
            rt = self.store.get_active_task_runtime(date.today())
            if not rt: return {"error": "no active task"}
            rt = self.store.extend_task_runtime(date.today(), cmd.get("extra_seconds", 0))
        except Exception as e: return {"error": str(e)}
        self._eta_warning_shown_for = None; return {"status": "extended", "runtime_id": rt.id, "new_estimated": rt.estimated_seconds}

    def _build_status(self) -> dict:
        now = datetime.now(); today = date.today(); runtime = self.store.get_active_task_runtime(today)
        idx = next((i for i, item in enumerate(self.schedule) if item is self.current_item), None)
        nxt = self.schedule[idx + 1] if idx is not None and idx + 1 < len(self.schedule) else None
        rt_payload = {"id": runtime.id, "status": runtime.status, "eta": runtime.compute_eta(now).isoformat(timespec="seconds")} if runtime else None
        return {"state": self.sm.state.value, "session_status": self.session.status.value if self.session else None, "task_runtime": rt_payload, "current_item": {"title": self.current_item.title, "kind": self.current_item.kind.value} if self.current_item else None, "next_item": {"title": nxt.title, "kind": nxt.kind.value} if nxt else None, "remaining_items": len(self.schedule), "auto_paused_by_mic": self._auto_paused_by_mic, "auto_chain_next": self._auto_chain_next, "bootstrap_error": self._bootstrap_error}
