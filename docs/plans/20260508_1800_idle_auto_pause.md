# Idle Auto-Pause Feature

**Status**: COMPLETE
**Created**: 2026-05-08

## Context
User wants: when no keyboard/mouse activity for 1 minute → auto-pause task. When user returns → auto-resume.

## Approach
Use `/dev/input/eventX` file modification times to detect idle. Zero new dependencies. Poll every tick (1s) via daemon `_tick`.

## Phases

### Phase 1: Idle Detector Module ✓
- New `idle_detector.py`: scans `/dev/input/` devices, tracks last activity timestamp
- Pure stat-based, no evdev dependency needed

### Phase 2: Config Integration ✓
- Add to `AutoPauseConfig`: `idle_pause_seconds` (default 60), `idle_resume_grace_seconds` (default 3)
- Add env vars mapping

### Phase 3: Daemon Integration ✓
- Wire into `_poll_auto_pause` or new `_poll_idle_pause` method
- Pause when idle > threshold, resume on activity return
- Only pause during TASK_ACTIVE state (not during breaks, idle, etc.)

### Phase 4: Config File ✓
- Update config.toml with new settings

### Phase 5: Testing
- Verify idle detection works
- Verify pause/resume cycle
