from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger(__name__)


class IdleDetector:
    """Detects user idle state by monitoring /proc/interrupts for input device changes.

    Under Wayland+Hyprland, /dev/input/event* is exclusively grabbed by the
    compositor. Instead, we poll /proc/interrupts for IRQ counters.

    Strategy:
      - Track per-IRQ deltas between polls.
      - Use per-IRQ-type thresholds to filter phantom noise:
          * i8042 IRQ 1 (keyboard): low phantom (~1-2/sec), sensitive threshold
          * i8042 IRQ 12 (touchpad/mouse): high phantom (~400+/sec on some
            Synaptics touchpads), high threshold — or skip entirely
          * xhci_hcd (USB): low phantom, medium threshold
      - Only count deltas exceeding the per-type threshold as real input.

    Args:
        idle_seconds: Seconds of inactivity before considered idle.
    """

    _POLL_INTERVAL = 1.0

    # Class-level defaults for "Hard" activity (intentional input for resuming)
    _HARD_THRESHOLDS: dict[str, int] = {
        "i8042": 3,       # keyboard only (IRQ 1)
        "xhci_hcd": 10,   # USB host controller
    }

    # Class-level defaults for "Soft" activity (any input to keep the session alive)
    _SOFT_THRESHOLDS: dict[str, int] = {
        "i8042": 1,
        "xhci_hcd": 1,
    }

    # IRQ numbers to EXCLUDE even if they match a monitored name.
    _EXCLUDE_IRQ_NUMS: set[str] = set()

    _INPUT_IRQ_NAMES = {"i8042", "xhci_hcd"}

    def __init__(self, idle_seconds: int = 60, soft_thresholds: dict[str, int] | None = None, hard_thresholds: dict[str, int] | None = None, exclude_irqs: list[str] | None = None):
        self.idle_seconds = idle_seconds
        
        # Instance-level thresholds (allows override via calibration or config)
        self.soft_thresholds = soft_thresholds or self._SOFT_THRESHOLDS.copy()
        self.hard_thresholds = hard_thresholds or self._HARD_THRESHOLDS.copy()
        self.exclude_irqs = set(exclude_irqs) if exclude_irqs is not None else self._EXCLUDE_IRQ_NUMS.copy()
        
        self._last_soft_activity: float = time.monotonic()
        self._last_hard_activity: float = time.monotonic()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._started = False

    def start(self) -> None:
        """Start the background interrupt monitoring thread."""
        if self._started:
            return
        self._started = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the background thread."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)

    def seconds_since_any_activity(self) -> float:
        """Return seconds since any (soft) activity was detected."""
        return time.monotonic() - self._last_soft_activity

    def seconds_since_hard_activity(self) -> float:
        """Return seconds since hard (intentional) activity was detected."""
        return time.monotonic() - self._last_hard_activity

    def is_idle(self) -> bool:
        """Check if user has been soft-idle longer than threshold."""
        return self.seconds_since_any_activity() >= self.idle_seconds

    def capture_deltas(self, duration_seconds: int) -> dict[str, list[int]]:
        """Record interrupt deltas for a period of time.
        
        Returns a dict mapping IRQ key (e.g. '49_xhci_hcd') to a list of recorded deltas per poll.
        """
        start_time = time.monotonic()
        
        # Read initial state to find all available IRQs
        prev = self._read_input_irqs(include_excluded=True)
        results: dict[str, list[int]] = {key: [] for key in prev}
        
        while time.monotonic() - start_time < duration_seconds:
            time.sleep(1.0)
            current = self._read_input_irqs(include_excluded=True)
            
            for key in results:
                delta = current.get(key, 0) - prev.get(key, 0)
                if delta < 0:
                    results[key].append(0)
                else:
                    results[key].append(delta)
                
            prev = current
            
        return results

    def _read_input_irqs(self, include_excluded: bool = False) -> dict[str, int]:
        """Read total interrupt counts for input-related IRQs from /proc/interrupts."""
        result: dict[str, int] = {}
        try:
            with open("/proc/interrupts") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) < 2:
                        continue
                    desc = parts[-1]
                    if desc in self._INPUT_IRQ_NAMES:
                        irq_num = parts[0].rstrip(":")
                        if not include_excluded and irq_num in self.exclude_irqs:
                            continue
                        total = 0
                        for val in parts[1:]:
                            try:
                                total += int(val)
                            except ValueError:
                                pass
                        key = f"{irq_num}_{desc}"
                        result[key] = total
        except OSError:
            pass
        return result

    def _monitor_loop(self) -> None:
        """Background loop: poll /proc/interrupts for input IRQ changes."""
        prev = self._read_input_irqs()
        if not prev:
            log.warning("Cannot read /proc/interrupts — idle detection disabled")
            return

        log.info("Monitoring IRQs: %s", list(prev.keys()))

        while not self._stop_event.is_set():
            self._stop_event.wait(self._POLL_INTERVAL)
            current = self._read_input_irqs()
            if not current:
                continue
            
            soft_found = False
            hard_found = False
            
            for key in current:
                delta = current.get(key, 0) - prev.get(key, 0)
                if delta <= 0:
                    continue
                    
                irq_name = key.split("_", 1)[1] if "_" in key else ""
                
                soft_thresh = self.soft_thresholds.get(irq_name, 1)
                hard_thresh = self.hard_thresholds.get(irq_name, 3)
                
                if delta >= soft_thresh:
                    soft_found = True
                if delta >= hard_thresh:
                    hard_found = True
                    
            now = time.monotonic()
            if soft_found:
                self._last_soft_activity = now
            if hard_found:
                self._last_hard_activity = now
                
            prev = current
