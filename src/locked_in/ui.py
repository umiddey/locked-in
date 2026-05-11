from __future__ import annotations

import logging
import sys
from datetime import datetime

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from .models import ScheduleItem, State

log = logging.getLogger(__name__)


class BlockerWindow(QWidget):
    """Fullscreen blocker window. NOT a secure lock."""

    def __init__(self, on_confirmed=None, on_give_up=None):
        super().__init__()
        self.on_confirmed = on_confirmed
        self.on_give_up = on_give_up
        self._confirmed = False
        self._closing_allowed = False
        self._ready_to_confirm = False
        self._setup_ui()
        # Add 1.5s delay before allowing confirmation to prevent accidental triggers (e.g. VTT key release)
        QTimer.singleShot(1500, self._allow_confirmation)

    def _allow_confirmation(self):
        self._ready_to_confirm = True
        self._update_confirm_button_state()

    def _update_confirm_button_state(self):
        if not hasattr(self, "_item") or not self._item:
            return
        typed = self.input.text().strip().lower()
        expected = self._item.title.strip().lower()
        self.confirm_btn.setEnabled(self._ready_to_confirm and typed == expected)

    def _setup_ui(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setStyleSheet("background-color: #0a0a0a; color: #ffffff;")
        self.showFullScreen()

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.clock_label = QLabel()
        self.clock_label.setFont(QFont("Monospace", 24))
        self.clock_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.clock_label)

        self.title_label = QLabel()
        self.title_label.setFont(QFont("Sans", 32, QFont.Weight.Bold))
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setWordWrap(True)
        layout.addWidget(self.title_label)

        self.duration_label = QLabel()
        self.duration_label.setFont(QFont("Monospace", 18))
        self.duration_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.duration_label)

        self.input = QLineEdit()
        self.input.setFont(QFont("Sans", 16))
        self.input.setPlaceholderText("Type the task name to start...")
        self.input.setStyleSheet(
            "background-color: #1a1a1a; color: #ffffff; border: 2px solid #333; padding: 10px; border-radius: 5px;"
        )
        self.input.textChanged.connect(self._on_text)
        layout.addWidget(self.input)

        self.confirm_btn = QPushButton("Start")
        self.confirm_btn.setFont(QFont("Sans", 18))
        self.confirm_btn.setStyleSheet(
            "background-color: #2d5016; color: white; padding: 15px; border-radius: 5px;"
        )
        self.confirm_btn.clicked.connect(self._confirm)
        self.confirm_btn.setEnabled(False)
        layout.addWidget(self.confirm_btn)

        self.give_up_btn = QPushButton("Give Up")
        self.give_up_btn.setFont(QFont("Sans", 10))
        self.give_up_btn.setStyleSheet(
            "background-color: #4a1010; color: #888; padding: 5px; border-radius: 3px;"
        )
        self.give_up_btn.clicked.connect(self._give_up)
        layout.addWidget(self.give_up_btn)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)
        self._tick()

    def set_item(self, item: ScheduleItem):
        self._item = item
        self.title_label.setText(item.title)
        self.duration_label.setText(f"{item.duration_minutes} min")
        self.input.setPlaceholderText(f"Type: {item.title}")
        self.input.show()
        self.confirm_btn.show()

    def _on_text(self, text: str):
        self._update_confirm_button_state()

    def _confirm(self):
        if self._confirmed:
            return
        self._confirmed = True
        if self.on_confirmed:
            self.on_confirmed()

    def _give_up(self):
        if self.on_give_up:
            self.on_give_up()

    def allow_close(self):
        self._closing_allowed = True

    def _tick(self):
        self.clock_label.setText(datetime.now().strftime("%H:%M:%S"))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            return  # Block escape
        super().keyPressEvent(event)

    def closeEvent(self, event):
        if not self._confirmed and not self._closing_allowed:
            event.ignore()
            self.raise_()
            self.activateWindow()
        else:
            super().closeEvent(event)


def create_app() -> QApplication:
    if QApplication.instance() is None:
        return QApplication(sys.argv)
    return QApplication.instance()
