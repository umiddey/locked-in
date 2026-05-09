# 20260508_1800_idle_auto_pause
**Task**: Add idle auto-pause (no kb/mouse for 60s → pause, activity → resume)
**Status**: COMPLETE
## WHAT
- New `idle_detector.py` module ✓
- Config integration (idle_pause_seconds, idle_resume_grace_seconds) ✓
- Daemon integration (poll + pause/resume) ✓
- Web frontend settings page ✓
- Config files updated ✓
## HOW
- IdleDetector uses background daemon thread reading /dev/input/eventX via select() (non-blocking poll, 1s timeout)
- Updates shared monotonic timestamp on any input event
- Main tick loop checks seconds_since_last_activity() each tick
- Pauses ONLY during TASK_ACTIVE when idle > threshold (AWAITING_TASK_START removed — no task = no pause)
- Auto-resumes on activity return within grace period
- Removed session-level pause/resume fallback — only task-level pause/resume now
- Settings exposed in /settings page under "Idle Auto-Pause" section
## WHY
- User walks away from desk → task timer shouldn't count AFK time
- Auto-resume on return = zero-friction, no manual unpausing
- /dev/input approach: zero external deps, works on Wayland/Hyprland
- Background thread: avoids blocking the Qt event loop
## FILES MODIFIED
- src/focus_warden/idle_detector.py: new module (background thread input monitor)
- src/focus_warden/config.py: added idle_pause_seconds, idle_resume_grace_seconds to AutoPauseConfig
- src/focus_warden/daemon.py: wired IdleDetector into __init__, run, _tick loop, added _poll_idle_pause method
- src/focus_warden/web_frontend.py: added auto_pause fields to settings form + save handler
- config.toml: added idle_pause_seconds=60, idle_resume_grace_seconds=3
- config.example.toml: same
## NEXT SESSION
- Test full daemon cycle (start → idle → auto-pause → return → auto-resume)
- Consider adding idle_seconds to /api/status response for frontend display
## REFERENCES
- docs/plans/20260508_1800_idle_auto_pause.md
