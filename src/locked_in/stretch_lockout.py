from __future__ import annotations

import json
import logging
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path

log = logging.getLogger(__name__)

_STATE_DIR = Path.home() / ".local" / "state" / "locked-in"


class StretchLockout:
    """Tracks cumulative work time across tasks. Locks screen when threshold is hit.

    Work time is provided externally (from the store's time_blocks) so it
    survives daemon restarts. The counter keeps going across task boundaries.
    Only resets after a lockout completes or the session ends.
    """

    def __init__(self, interval_minutes: int = 60, duration_minutes: int = 5):
        self.interval_seconds = interval_minutes * 60
        self.duration_seconds = duration_minutes * 60
        self._active = False
        self._locked = False
        self._paused = False
        self._offset: float = 0.0
        self._bootstrapped: bool = False
        self._lock_until: datetime | None = None
        self._lock_proc: subprocess.Popen | None = None
        self._restore_offset()

    def start(self):
        """Mark that work is happening. Does NOT reset accumulation."""
        self._paused = False
        if self._active:
            return
        self._active = True
        log.info("Stretch lockout tracking started")

    def stop(self):
        """Full session stop — resets everything."""
        if self._locked:
            self._unlock()
        self._active = False
        self._paused = False
        self._offset = 0.0
        self._save_offset()
        self._lock_until = None
        self._lock_proc = None

    def pause(self):
        self._paused = True
        log.info("Stretch lockout paused")

    def resume(self):
        self._paused = False
        log.info("Stretch lockout resumed")

    @property
    def is_locked(self) -> bool:
        return self._locked

    def tick(self, cumulative_work_seconds: float = 0.0):
        """Check if stretch break is due based on cumulative work time.

        Args:
            cumulative_work_seconds: Total work seconds today from store.
        """
        if not self._active:
            return
        if self._paused:
            return

        # Bootstrap offset on first tick: set to current cumulative work
        # so we only count NEW work from this point forward
        if not self._bootstrapped:
            self._offset = max(self._offset, cumulative_work_seconds)
            self._bootstrapped = True
            log.info("Stretch lockout bootstrapped: offset %.0fs, cumulative %.0fs", self._offset, cumulative_work_seconds)

        if self._locked:
            # Primary: detect hyprlock exit (user typed password)
            if self._lock_proc and self._lock_proc.poll() is not None:
                log.info("Hyprlock exited (user unlocked), stretch break over")
                self._offset = cumulative_work_seconds
                self._locked = False
                self._lock_until = None
                self._lock_proc = None
                self._save_offset()
                return
            # Fallback: timer-based in case process tracking fails
            now = datetime.now()
            if self._lock_until and now >= self._lock_until:
                self._unlock()
                self._offset = cumulative_work_seconds
                self._locked = False
                self._lock_until = None
                self._lock_proc = None
                self._save_offset()
                log.info("Stretch break over (timer expired). Resuming work.")
            return

        effective = cumulative_work_seconds - self._offset
        if effective >= self.interval_seconds:
            log.info("Work threshold hit: %.0fs (offset %.0fs) >= %ds, locking", effective, self._offset, self.interval_seconds)
            self._lock()
            self._locked = True
            self._lock_until = datetime.now() + timedelta(seconds=self.duration_seconds)
            log.info("Stretch break! Screen locked for %dm (until %s)", self.duration_seconds // 60, self._lock_until.strftime("%H:%M:%S"))

    def _lock(self):
        try:
            self._lock_proc = subprocess.Popen(
                ["hyprlock"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            log.warning("hyprlock not found, cannot lock screen")
            self._lock_proc = None

    def _unlock(self):
        try:
            subprocess.run(
                ["loginctl", "unlock-session"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            log.warning("loginctl not found, cannot unlock session")

    def _save_offset(self):
        try:
            _STATE_DIR.mkdir(parents=True, exist_ok=True)
            (_STATE_DIR / "stretch_offset.json").write_text(
                json.dumps({"date": date.today().isoformat(), "offset": self._offset})
            )
        except OSError:
            log.warning("Failed to persist stretch offset")

    def _restore_offset(self):
        try:
            f = _STATE_DIR / "stretch_offset.json"
            if f.exists():
                data = json.loads(f.read_text())
                if data.get("date") == date.today().isoformat():
                    self._offset = data.get("offset", 0.0)
                    log.info("Restored stretch offset: %.0fs", self._offset)
                    return
            self._offset = 0.0
        except (OSError, json.JSONDecodeError):
            self._offset = 0.0
