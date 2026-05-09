# 20260509_1600_decouple_idle_sensitivity
**Task**: Decouple idle detection sensitivity for pausing vs resuming
**Status**: COMPLETE
## WHAT
- Refactored `IdleDetector` to track "soft" and "hard" activity separately. ✓
- Updated `Daemon` to use soft activity for pause timeouts and hard activity for resume logic. ✓
- Increased `idle_pause_seconds` to 120 in `config.toml`. ✓
- Added `tests/test_idle_detector.py`. ✓
## HOW
- `IdleDetector` now uses a threshold of 1 (any delta > 0) for soft activity to ensure even light typing or mouse movement resets the pause timer.
- `IdleDetector` maintains original thresholds (3 for keyboard, 10 for USB) for "hard" activity to ensure auto-resumes remain intentional and noise-resistant.
- `Daemon._poll_idle_pause` was updated to call the appropriate methods for each state.
## WHY
- The user reported that idle detection was "too strict" and triggering while they were still active (light work/typing).
- By decoupling the paths, we can be extremely sensitive to "staying awake" (preventing pause) while remaining strict about "waking up" (resuming task), which requires a higher level of confidence in user intent.
## FILES MODIFIED
- `src/locked_in/idle_detector.py`
- `src/locked_in/daemon.py`
- `config.toml`
- `tests/test_idle_detector.py` (New)
## NEXT SESSION
- Monitor if the soft threshold of 1 is too sensitive for users on very noisy hardware (may need to bump to 2 if they never go idle).
## REFERENCES
- User feedback in chat session regarding strict idle triggers.
