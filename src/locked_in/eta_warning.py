from __future__ import annotations

import logging
from datetime import date, datetime

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont
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


class EtaWarningPopup(QWidget):
    def __init__(self, task_name: str, estimated_minutes: int, on_decision):
        super().__init__()
        self.on_decision = on_decision
        self.estimated_minutes = estimated_minutes

        self.setWindowTitle("Locked-In — Time's Up")
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setFixedWidth(420)

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
            QPushButton {
                font-family: 'JetBrains Mono', monospace;
                font-size: 13px;
                font-weight: 700;
                padding: 12px 20px;
                border-radius: 6px;
                border: 1px solid;
            }
            QPushButton#finish {
                background: #2fac6a;
                border-color: #2fac6a;
                color: #080a0c;
            }
            QPushButton#finish:hover { background: #44d88a; }
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

        tag = QLabel("TIME'S UP")
        tag.setObjectName("tag")
        tag.setAlignment(Qt.AlignmentFlag.AlignLeft)
        tag.setFixedWidth(90)
        layout.addWidget(tag)

        name_label = QLabel(task_name)
        name_label.setObjectName("task")
        name_label.setWordWrap(True)
        layout.addWidget(name_label)

        self.subtitle = QLabel("Scheduled time has elapsed")
        self.subtitle.setObjectName("subtitle")
        layout.addWidget(self.subtitle)

        self.timer_label = QLabel("")
        self.timer_label.setObjectName("timer")
        layout.addWidget(self.timer_label)

        layout.addSpacing(8)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        finish_btn = QPushButton("✓ Finish Task")
        finish_btn.setObjectName("finish")
        finish_btn.clicked.connect(lambda: self._decide(DECISION_FINISH))
        btn_row.addWidget(finish_btn)

        extend_btn = QPushButton(f"+ {estimated_minutes}m More")
        extend_btn.setObjectName("extend")
        extend_btn.clicked.connect(lambda: self._decide(DECISION_EXTEND))
        btn_row.addWidget(extend_btn)

        layout.addLayout(btn_row)

        self._tick_timer = QTimer(self)
        self._tick_timer.timeout.connect(self._tick)
        self._tick_timer.start(1000)
        self._started = datetime.now()
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
        elapsed = int((datetime.now() - self._started).total_seconds())
        m, s = divmod(elapsed, 60)
        self.timer_label.setText(f"Overtime: {m}m {s:02d}s")

    def _decide(self, decision: str):
        self._tick_timer.stop()
        self.close()
        if self.on_decision:
            self.on_decision(decision)


def show_eta_warning(task_name: str, estimated_minutes: int, on_decision) -> EtaWarningPopup:
    popup = EtaWarningPopup(task_name, estimated_minutes, on_decision)
    popup.show()
    popup.raise_()
    popup.activateWindow()
    return popup
