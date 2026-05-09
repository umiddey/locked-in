from __future__ import annotations

import logging
import subprocess
from datetime import datetime, timedelta

log = logging.getLogger(__name__)


class StretchLockout:
    """Tracks cumulative work time across tasks. Locks screen when threshold is hit.

    The accumulated work time persists across task boundaries (task A finishes,
    task B starts — the counter keeps going). Only resets after a lockout completes
    or the session ends.
    """

    def __init__(self, interval_minutes: int = 60, duration_minutes: int = 5):
        self.interval_seconds = interval_minutes * 60
        self.duration_seconds = duration_minutes * 60
        self._work_accumulated = 0.0
        self._active = False
        self._locked = False
        self._paused = False
        self._lock_until: datetime | None = None

    def start(self):
        """Mark that work is happening. Does NOT reset accumulation."""
        self._paused = False
        if self._active:
            return
        self._active = True
        log.info("Stretch lockout tracking resumed: accumulated %.0fs / %ds", self._work_accumulated, self.interval_seconds)

    def stop(self):
        """Full session stop — resets everything."""
        if self._locked:
            self._unlock()
        self._active = False
        self._paused = False
        self._work_accumulated = 0.0
        self._lock_until = None

    def pause(self):
        self._paused = True
        log.info("Stretch lockout paused")

    def resume(self):
        self._paused = False
        log.info("Stretch lockout resumed")

    @property
    def is_locked(self) -> bool:
        return self._locked

    def tick(self):
        if not self._active:
            return
        if self._paused:
            return

        if self._locked:
            now = datetime.now()
            if self._lock_until and now >= self._lock_until:
                self._unlock()
                self._locked = False
                self._lock_until = None
                self._work_accumulated = 0.0
                log.info("Stretch break over. Resuming work.")
            return

        self._work_accumulated += 1.0

        if self._work_accumulated >= self.interval_seconds:
            log.info("Work threshold hit: %.0fs >= %ds, locking", self._work_accumulated, self.interval_seconds)
            self._lock()
            self._locked = True
            self._lock_until = datetime.now() + timedelta(seconds=self.duration_seconds)
            log.info("Stretch break! Screen locked for %dm (until %s)", self.duration_seconds // 60, self._lock_until.strftime("%H:%M:%S"))

    def _lock(self):
        try:
            subprocess.Popen(
                ["hyprlock"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            log.warning("hyprlock not found, cannot lock screen")

    def _unlock(self):
        try:
            subprocess.run(
                ["loginctl", "unlock-session"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            log.warning("loginctl not found, cannot unlock screen")
