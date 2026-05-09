import time
from focus_warden.idle_detector import IdleDetector

def test_idle_detector_soft_hard_split():
    # We can't easily mock /proc/interrupts without monkeypatching 'open'
    # but we can test the internal logic by manually updating the timestamps
    detector = IdleDetector(idle_seconds=2)
    
    now = time.monotonic()
    detector._last_soft_activity = now - 1.5
    detector._last_hard_activity = now - 5.0
    
    # Soft idle should be false (1.5 < 2.0)
    assert detector.is_idle() is False
    assert detector.seconds_since_any_activity() >= 1.5
    assert detector.seconds_since_hard_activity() >= 5.0

    # Advance "time" for soft activity
    detector._last_soft_activity = now - 3.0
    # Soft idle should be true (3.0 > 2.0)
    assert detector.is_idle() is True
