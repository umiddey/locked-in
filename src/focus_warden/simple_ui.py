from __future__ import annotations

from datetime import date, datetime

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from .simple_store import DEFAULT_TASK_DURATION_MINUTES, ScheduleEntry, TaskDraft
from .notifications import notify
from .planning import format_task_drafts, parse_task_drafts
from .ui import create_app


class TodoPlannerWindow(QWidget):
    def __init__(
        self,
        target_date: date,
        reason: str,
        existing_tasks: list[TaskDraft] | None = None,
        on_save=None,
        on_save_and_open=None,
    ):
        super().__init__()
        self.target_date = target_date
        self.reason = reason
        self.on_save = on_save
        self.on_save_and_open = on_save_and_open
        self._setup_ui(existing_tasks or [])

    def _setup_ui(self, existing_tasks: list[TaskDraft]) -> None:
        self.setWindowTitle("Focus Warden Planner")
        self.setMinimumSize(760, 560)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setStyleSheet(
            """
            QWidget { background: #111111; color: #f5f1e8; }
            QLabel#eyebrow { color: #f0b429; font-size: 13px; font-weight: 700; }
            QLabel#headline { font-size: 30px; font-weight: 800; }
            QLabel#subhead { color: #b7b2a8; font-size: 14px; }
            QPlainTextEdit {
                background: #1c1c1c;
                border: 1px solid #383838;
                border-radius: 10px;
                padding: 14px;
                color: #f5f1e8;
            }
            QPushButton {
                background: #f0b429;
                color: #111111;
                border: none;
                border-radius: 8px;
                padding: 12px 16px;
                font-weight: 700;
            }
            QPushButton:hover { background: #ffc857; }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(16)

        eyebrow = QLabel(self.reason)
        eyebrow.setObjectName("eyebrow")
        layout.addWidget(eyebrow)

        headline = QLabel(
            f"Plan your tasks for {self.target_date.strftime('%A, %B %d')}"
        )
        headline.setObjectName("headline")
        headline.setWordWrap(True)
        layout.addWidget(headline)

        subhead = QLabel(
            "One task per line. Use `task - minutes`. Example: `Write article - 25`."
        )
        subhead.setObjectName("subhead")
        layout.addWidget(subhead)

        self.editor = QPlainTextEdit()
        self.editor.setFont(QFont("Monospace", 12))
        self.editor.setPlaceholderText(
            "Write article - 25\nRead 10 mins - 10\nExercise - 40"
        )
        self.editor.setPlainText(format_task_drafts(existing_tasks))
        layout.addWidget(self.editor, 1)

        button_row = QHBoxLayout()
        button_row.setSpacing(12)

        save_button = QPushButton("Save Plan")
        save_button.clicked.connect(self._save)
        button_row.addWidget(save_button)

        save_open_button = QPushButton("Save and Open Today")
        save_open_button.clicked.connect(self._save_and_open)
        button_row.addWidget(save_open_button)

        layout.addLayout(button_row)

    def _collect(self) -> list[TaskDraft]:
        return parse_task_drafts(self.editor.toPlainText())

    def _save(self) -> None:
        try:
            drafts = self._collect()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid plan", str(exc))
            return
        if not drafts:
            QMessageBox.warning(self, "No tasks", "Add at least one task.")
            return
        if self.on_save:
            self.on_save(drafts)
        self.close()

    def _save_and_open(self) -> None:
        try:
            drafts = self._collect()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid plan", str(exc))
            return
        if not drafts:
            QMessageBox.warning(self, "No tasks", "Add at least one task.")
            return
        if self.on_save:
            self.on_save(drafts)
        if self.on_save_and_open:
            self.on_save_and_open(drafts)
        self.close()


TASK_ALERT_5_MINUTES = 5 * 60
TASK_ALERT_1_MINUTE = 60
TASK_POPUP_SECONDS = 30
TASK_EXTEND_SECONDS = 5 * 60


class TaskDeadlinePopup(QWidget):
    def __init__(self, controller: "TaskTimerWindow", parent=None):
        super().__init__(parent)
        self.controller = controller
        self._closing_allowed = False
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setWindowTitle("Focus Warden")
        self.setFixedSize(380, 230)
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setStyleSheet(
            """
            QWidget { background: #111111; color: #f5f1e8; }
            QLabel#eyebrow { color: #f0b429; font-size: 13px; font-weight: 700; }
            QLabel#headline { font-size: 22px; font-weight: 800; }
            QLabel#timer { font-size: 54px; font-weight: 900; color: #ffc857; }
            QLabel#subhead { color: #b7b2a8; font-size: 14px; }
            QPushButton {
                background: #f0b429;
                color: #111111;
                border: none;
                border-radius: 8px;
                padding: 10px 12px;
                font-weight: 700;
            }
            QPushButton:hover { background: #ffc857; }
            QPushButton#danger { background: #a63d40; color: #f5f1e8; }
            QPushButton#danger:hover { background: #c24f52; }
            QPushButton#extend { background: #355c7d; color: #f5f1e8; }
            QPushButton#extend:hover { background: #4478a5; }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        eyebrow = QLabel("Task ending soon")
        eyebrow.setObjectName("eyebrow")
        layout.addWidget(eyebrow)

        self.title_label = QLabel(self.controller.entry.task.task_name)
        self.title_label.setObjectName("headline")
        self.title_label.setWordWrap(True)
        layout.addWidget(self.title_label)

        self.timer_label = QLabel()
        self.timer_label.setObjectName("timer")
        self.timer_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.timer_label)

        self.status_label = QLabel(
            f"Scheduled {self.controller.entry.scheduled_start.strftime('%H:%M')} - {self.controller.entry.scheduled_end.strftime('%H:%M')}"
        )
        self.status_label.setObjectName("subhead")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)

        button_row = QHBoxLayout()
        button_row.setSpacing(10)

        finish_button = QPushButton("Finished")
        finish_button.clicked.connect(self.controller.finish_task)
        button_row.addWidget(finish_button)

        extend_button = QPushButton(
            f"Extend {self.controller.original_extension_minutes} Min"
        )
        extend_button.setObjectName("extend")
        extend_button.clicked.connect(self.controller.extend_original_task)
        button_row.addWidget(extend_button)

        quick_extend_button = QPushButton("Extend 5 Min")
        quick_extend_button.setObjectName("extend")
        quick_extend_button.clicked.connect(self.controller.extend_task)
        button_row.addWidget(quick_extend_button)

        layout.addLayout(button_row)
        self.refresh(self.controller.remaining_seconds)

    def refresh(self, remaining_seconds: int) -> None:
        minutes, seconds = divmod(max(remaining_seconds, 0), 60)
        self.timer_label.setText(f"{minutes:02d}:{seconds:02d}")
        if remaining_seconds <= 0:
            self.status_label.setText("Time is up. Choose an action now.")
        elif remaining_seconds <= 10:
            self.status_label.setText("Final countdown. Choose an action now.")
        else:
            self.status_label.setText("Choose finish or extend.")

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._move_to_corner()

    def closeEvent(self, event) -> None:
        if self._closing_allowed:
            super().closeEvent(event)
            return
        event.ignore()
        self.raise_()
        self.activateWindow()

    def allow_close(self) -> None:
        self._closing_allowed = True

    def _move_to_corner(self) -> None:
        screen = self.screen() or QApplication.primaryScreen()
        if not screen:
            return
        geo = screen.availableGeometry()
        margin = 24
        x = max(geo.x() + margin, geo.x() + geo.width() - self.width() - margin)
        y = geo.y() + margin
        self.move(x, y)


class TaskTimerWindow(QWidget):
    def __init__(
        self,
        entry: ScheduleEntry,
        reason: str,
        on_started=None,
        on_finished=None,
        parent=None,
    ):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        self.entry = entry
        self.reason = reason
        self.on_started = on_started
        self.on_finished = on_finished
        self.original_extension_minutes = max(entry.task.duration_minutes, 1)
        self.original_extension_seconds = self.original_extension_minutes * 60
        self.remaining_seconds = self.original_extension_seconds
        self.run_id = None
        self._popup: TaskDeadlinePopup | None = None
        self._notified_thresholds: set[int] = set()
        self._task_complete = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        QTimer.singleShot(0, self._start)
        self._timer.start(1000)

    def _start(self) -> None:
        if self.on_started:
            self.run_id = self.on_started(
                self.entry.task.task_name,
                self.entry.task.id,
                self.entry.scheduled_start,
            )
        notify("Focus Warden", f"Task started: {self.entry.task.task_name}")
        if self.remaining_seconds <= TASK_POPUP_SECONDS:
            self._show_popup()

    def _tick(self) -> None:
        if self._task_complete:
            return

        previous = self.remaining_seconds
        self.remaining_seconds = max(self.remaining_seconds - 1, 0)
        self._maybe_send_notifications(previous, self.remaining_seconds)

        if self._popup:
            self._popup.refresh(self.remaining_seconds)

        if self.remaining_seconds <= TASK_POPUP_SECONDS and self._popup is None:
            self._show_popup()

    def _maybe_send_notifications(self, previous: int, current: int) -> None:
        thresholds = (
            (TASK_ALERT_5_MINUTES, "5 minutes left", "Task has 5 minutes remaining."),
            (TASK_ALERT_1_MINUTE, "1 minute left", "Task has 1 minute remaining.", "critical"),
        )
        for item in thresholds:
            threshold, title, body, *urgency = item
            if threshold in self._notified_thresholds:
                continue
            if previous > threshold >= current:
                notify("Focus Warden", title, body, urgency[0] if urgency else "normal")
                self._notified_thresholds.add(threshold)

    def _show_popup(self) -> None:
        if self._popup is None:
            self._popup = TaskDeadlinePopup(self)
        self._popup.refresh(self.remaining_seconds)
        self._popup.show()
        self._popup.raise_()
        self._popup.activateWindow()
        if self.remaining_seconds <= TASK_POPUP_SECONDS:
            notify(
                "Focus Warden",
                f"{max(self.remaining_seconds, 0)} seconds left",
                "critical",
            )

    def _close_popup(self) -> None:
        if self._popup:
            self._popup.allow_close()
            self._popup.close()
            self._popup = None

    def finish_task(self) -> None:
        if self._task_complete:
            return
        self._task_complete = True
        self._timer.stop()
        self._close_popup()
        if self.on_finished and self.run_id is not None:
            self.on_finished(self.run_id, "")
        notify("Focus Warden", "Task marked finished.")

    def extend_task(self) -> None:
        if self._task_complete:
            return
        self._extend_remaining(TASK_EXTEND_SECONDS, "Task extended by 5 minutes.")

    def extend_original_task(self) -> None:
        if self._task_complete:
            return
        # Keep the same run open so the final finish time reflects real elapsed time.
        self._extend_remaining(
            self.original_extension_seconds,
            f"Task extended by {self.original_extension_minutes} minutes.",
        )

    def _extend_remaining(self, extra_seconds: int, message: str) -> None:
        self.remaining_seconds += extra_seconds
        self._notified_thresholds.clear()
        self._close_popup()
        notify("Focus Warden", message)


class ScheduleDashboardWindow(QWidget):
    def __init__(
        self,
        target_date: date,
        reason: str,
        on_start_current=None,
    ):
        super().__init__()
        self.target_date = target_date
        self.reason = reason
        self.on_start_current = on_start_current
        self.current_entry: ScheduleEntry | None = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setWindowTitle("Focus Warden Schedule")
        self.setMinimumSize(760, 560)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setStyleSheet(
            """
            QWidget { background: #111111; color: #f5f1e8; }
            QLabel#eyebrow { color: #f0b429; font-size: 13px; font-weight: 700; }
            QLabel#headline { font-size: 30px; font-weight: 800; }
            QLabel#subhead { color: #b7b2a8; font-size: 14px; }
            QPlainTextEdit {
                background: #1c1c1c;
                border: 1px solid #383838;
                border-radius: 10px;
                padding: 14px;
                color: #f5f1e8;
            }
            QPushButton {
                background: #f0b429;
                color: #111111;
                border: none;
                border-radius: 8px;
                padding: 12px 16px;
                font-weight: 700;
            }
            QPushButton:hover { background: #ffc857; }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(16)

        eyebrow = QLabel(self.reason)
        eyebrow.setObjectName("eyebrow")
        layout.addWidget(eyebrow)

        headline = QLabel(
            f"Today's schedule for {self.target_date.strftime('%A, %B %d')}"
        )
        headline.setObjectName("headline")
        layout.addWidget(headline)

        self.session_label = QLabel()
        self.session_label.setObjectName("subhead")
        layout.addWidget(self.session_label)

        self.current_label = QLabel()
        self.current_label.setObjectName("subhead")
        layout.addWidget(self.current_label)

        self.next_label = QLabel()
        self.next_label.setObjectName("subhead")
        layout.addWidget(self.next_label)

        self.schedule_view = QPlainTextEdit()
        self.schedule_view.setReadOnly(True)
        layout.addWidget(self.schedule_view, 1)

        button_row = QHBoxLayout()
        button_row.setSpacing(12)

        self.start_button = QPushButton("Start Current Task")
        self.start_button.clicked.connect(self._start_current)
        button_row.addWidget(self.start_button)

        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close)
        button_row.addWidget(close_button)

        layout.addLayout(button_row)

    def set_data(
        self,
        session_started_at: datetime,
        entries: list[ScheduleEntry],
    ) -> None:
        self.session_label.setText(
            f"Day anchored to PC-on time: {session_started_at.strftime('%H:%M')}"
        )

        pending_entries = [entry for entry in entries if not entry.task.completed_at]
        self.current_entry = pending_entries[0] if pending_entries else None
        next_entry = pending_entries[1] if len(pending_entries) > 1 else None

        if self.current_entry:
            self.current_label.setText(
                f"Current: {self.current_entry.task.task_name} "
                f"({self.current_entry.scheduled_start.strftime('%H:%M')} - {self.current_entry.scheduled_end.strftime('%H:%M')})"
            )
        else:
            self.current_label.setText("Current: all tasks finished")

        if next_entry:
            self.next_label.setText(
                f"Next: {next_entry.task.task_name} at {next_entry.scheduled_start.strftime('%H:%M')}"
            )
        else:
            self.next_label.setText("Next: nothing queued")

        lines: list[str] = []
        now = datetime.now()
        for entry in entries:
            if entry.task.completed_at:
                status = "DONE"
            elif now < entry.scheduled_start:
                status = "UPCOMING"
            else:
                status = "PENDING"
            lines.append(
                f"[{status}] {entry.scheduled_start.strftime('%H:%M')} - "
                f"{entry.scheduled_end.strftime('%H:%M')} | "
                f"{entry.task.task_name} | {entry.task.duration_minutes}m"
            )
        self.schedule_view.setPlainText("\n".join(lines))
        self.start_button.setEnabled(self.current_entry is not None)

    def _start_current(self) -> None:
        if self.current_entry and self.on_start_current:
            self.on_start_current(self.current_entry)


def launch_planner_window(
    target_date: date,
    reason: str,
    existing_tasks: list[TaskDraft],
    on_save,
    on_save_and_open,
) -> int:
    app = create_app()
    planner = TodoPlannerWindow(
        target_date=target_date,
        reason=reason,
        existing_tasks=existing_tasks,
        on_save=on_save,
        on_save_and_open=on_save_and_open,
    )
    planner.show()
    return app.exec()


def launch_task_test_window(
    entry: ScheduleEntry,
    reason: str,
    on_started,
    on_finished,
) -> int:
    app = create_app()
    app.setQuitOnLastWindowClosed(False)

    def _finished(run_id: int, notes: str) -> None:
        if on_finished:
            on_finished(run_id, notes)
        app.quit()

    timer = TaskTimerWindow(
        entry=entry,
        reason=reason,
        on_started=on_started,
        on_finished=_finished,
    )
    return app.exec()


def launch_schedule_dashboard(target_date: date, reason: str, store) -> int:
    app = create_app()
    windows: list[QWidget] = []

    def load_schedule() -> tuple[datetime, list[ScheduleEntry]]:
        session_started_at = store.ensure_session(target_date)
        _, _, entries = store.build_schedule(target_date)
        return session_started_at, entries

    dashboard = ScheduleDashboardWindow(
        target_date=target_date,
        reason=reason,
    )
    windows.append(dashboard)

    def refresh_dashboard() -> None:
        session_started_at, entries = load_schedule()
        dashboard.set_data(session_started_at, entries)
        app.setQuitOnLastWindowClosed(True)
        dashboard.show()
        dashboard.raise_()
        dashboard.activateWindow()

    def start_current(entry: ScheduleEntry) -> None:
        app.setQuitOnLastWindowClosed(False)
        dashboard.hide()

        def on_started(task_name: str, plan_task_id: int, scheduled_start: datetime) -> int:
            return store.start_task_run(target_date, plan_task_id, task_name, scheduled_start)

        def on_finished(run_id: int, notes: str) -> None:
            store.finish_task_run(run_id, "finished", notes)
            refresh_dashboard()
            app.setQuitOnLastWindowClosed(True)

        timer = TaskTimerWindow(
            entry=entry,
            reason="Active task",
            on_started=on_started,
            on_finished=on_finished,
            parent=dashboard,
        )
        windows.append(timer)

    dashboard.on_start_current = start_current
    refresh_dashboard()
    return app.exec()
