from __future__ import annotations

import logging
from datetime import datetime

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

log = logging.getLogger(__name__)

DECISION_FINISH = "finish"
DECISION_EXTEND = "extend"
DECISION_AUTO_CONTINUE = "auto_continue"


class EtaWarningPopup(QWidget):
    """Pre-task-end warning popup shown 5 minutes before a task's ETA.

    Args:
        task_name (str): Name of the current task
        estimated_minutes (int): Minutes for the extend option
        next_task_name (str | None): Name of next task in pipeline (for auto-continue label)
        on_decision (callable): Callback receiving one of DECISION_* constants
        eta (datetime | None): When the current task is scheduled to end (for countdown)
    """
    def __init__(self, task_name: str, estimated_minutes: int, on_decision,
                 next_task_name: str | None = None, eta: datetime | None = None):
        super().__init__()
        self.on_decision = on_decision
        self.estimated_minutes = estimated_minutes
        self._eta = eta

        self.setWindowTitle("Locked-In — Almost Done")
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setFixedWidth(460)

        self.setStyleSheet("""
            QWidget#popup {
                background: #0c0e14;
                border: 2px solid #d4a039;
                border-radius: 12px;
            }
            QLabel { color: #eae6dc; }
            QLabel#tag {
                background: #1a1500;
                color: #eab94e;
                border: 1px solid rgba(212,160,57,.4);
                border-radius: 4px;
                padding: 3px 10px;
                font-size: 11px;
                font-weight: 700;
            }
            QLabel#task {
                font-size: 22px;
                font-weight: 800;
                color: #eae6dc;
            }
            QLabel#subtitle {
                font-size: 13px;
                color: #d4a039;
            }
            QLabel#timer {
                font-size: 15px;
                font-weight: 700;
                color: #eab94e;
                font-family: 'JetBrains Mono', monospace;
            }
            QLabel#next-task {
                font-size: 12px;
                color: #888;
                font-family: 'JetBrains Mono', monospace;
            }
            QPushButton {
                font-family: 'JetBrains Mono', monospace;
                font-size: 12px;
                font-weight: 700;
                padding: 12px 16px;
                border-radius: 6px;
                border: 1px solid;
            }
            QPushButton#auto-continue {
                background: #2fac6a;
                border-color: #2fac6a;
                color: #080a0c;
            }
            QPushButton#auto-continue:hover { background: #44d88a; }
            QPushButton#finish {
                background: var(--s2, #12151d);
                border-color: #252b3d;
                color: #eae6dc;
            }
            QPushButton#finish:hover { background: #191d28; }
            QPushButton#extend {
                background: rgba(212,160,57,.08);
                border-color: rgba(212,160,57,.3);
                color: #eab94e;
            }
            QPushButton#extend:hover { background: rgba(212,160,57,.16); }
        """)

        container = QWidget()
        container.setObjectName("popup")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(container)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)

        tag = QLabel("5 MIN LEFT")
        tag.setObjectName("tag")
        tag.setAlignment(Qt.AlignmentFlag.AlignLeft)
        tag.setFixedWidth(100)
        layout.addWidget(tag)

        name_label = QLabel(task_name)
        name_label.setObjectName("task")
        name_label.setWordWrap(True)
        layout.addWidget(name_label)

        self.subtitle = QLabel("Task finishing soon — choose what's next")
        self.subtitle.setObjectName("subtitle")
        layout.addWidget(self.subtitle)

        self.timer_label = QLabel("")
        self.timer_label.setObjectName("timer")
        layout.addWidget(self.timer_label)

        if next_task_name:
            next_label = QLabel(f"Next: {next_task_name}")
            next_label.setObjectName("next-task")
            layout.addWidget(next_label)

        layout.addSpacing(8)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        auto_btn = QPushButton("▶ Auto-Continue")
        auto_btn.setObjectName("auto-continue")
        auto_btn.setToolTip("Finish this task and immediately start the next one")
        auto_btn.clicked.connect(lambda: self._decide(DECISION_AUTO_CONTINUE))
        btn_row.addWidget(auto_btn)

        finish_btn = QPushButton("■ Finish")
        finish_btn.setObjectName("finish")
        finish_btn.setToolTip("Finish this task and wait for manual start of next")
        finish_btn.clicked.connect(lambda: self._decide(DECISION_FINISH))
        btn_row.addWidget(finish_btn)

        extend_btn = QPushButton(f"+ {estimated_minutes}m")
        extend_btn.setObjectName("extend")
        extend_btn.setToolTip(f"Extend this task by {estimated_minutes} minutes")
        extend_btn.clicked.connect(lambda: self._decide(DECISION_EXTEND))
        btn_row.addWidget(extend_btn)

        layout.addLayout(btn_row)

        self._tick_timer = QTimer(self)
        self._tick_timer.timeout.connect(self._tick)
        self._tick_timer.start(1000)
        self._tick()

        self._position_top_center()

    def _position_top_center(self):
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            x = geo.x() + (geo.width() - self.width()) // 2
            y = geo.y() + 40
            self.move(x, y)

    def _tick(self):
        if self._eta:
            remaining = (self._eta - datetime.now()).total_seconds()
            if remaining <= 0:
                elapsed = int(-remaining)
                m, s = divmod(elapsed, 60)
                self.timer_label.setText(f"Overtime: {m}m {s:02d}s")
            else:
                m, s = divmod(int(remaining), 60)
                self.timer_label.setText(f"Countdown: {m}m {s:02d}s")
        else:
            self.timer_label.setText("")

    def _decide(self, decision: str):
        self._tick_timer.stop()
        self.close()
        if self.on_decision:
            self.on_decision(decision)


def show_eta_warning(task_name: str, estimated_minutes: int, on_decision,
                     next_task_name: str | None = None, eta: datetime | None = None) -> EtaWarningPopup:
    popup = EtaWarningPopup(task_name, estimated_minutes, on_decision,
                            next_task_name=next_task_name, eta=eta)
    popup.show()
    popup.raise_()
    popup.activateWindow()
    return popup
