# Naming convention: 20260511_1920_web_idle_watcher_thread
**Task**: Add idle auto-pause background thread to web frontend
**Status**: COMPLETE
## WHAT
- Added `_start_idle_watcher()` + `_idle_watcher_loop()` to `LockedInWebFrontend` ✓
- Added `import threading, time` ✓
- Watcher starts `IdleDetector` (was instantiated but never started) ✓
## HOW
- `_start_idle_watcher()` called inside `run()` before `serve_forever()`
- Daemon thread polls every 1s, reads `auto_pause` config from toml each cycle
- If `idle_secs >= idle_pause_seconds` and task is running → `store.pause_task_runtime()`
- If paused by us and `hard_secs <= idle_resume_grace_seconds` → `store.resume_task_runtime()`
- `_idle_watcher_paused_by_us` flag gates double-pause and resume
- `enabled` defaults to `True` (no config = on) to match daemon behavior
## WHY
- Idle auto-pause only existed in daemon.py (`_check_idle_pause`); web-only users got nothing
- `IdleDetector` was already instantiated in web frontend for calibration but never `.start()`ed
- Store-owned timing refactor made it safe: watcher just calls store methods, no local state drift
## FILES MODIFIED
- `src/locked_in/web_frontend.py`: added threading/time imports, `_start_idle_watcher`, `_idle_watcher_loop`
## NEXT SESSION
- Consider also auto-restarting IdleDetector if config thresholds change at runtime
## REFERENCES
- Root cause diagnosed: `IdleDetector` not started in web mode, no tick loop calling `_check_idle_pause`
- Verification: `source .venv/bin/activate && python -c "from src.locked_in.web_frontend import LockedInWebFrontend; print('OK')`
