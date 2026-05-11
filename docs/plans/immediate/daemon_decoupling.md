# Plan: Daemon-Store Decoupling & Bug Fixes

**Status**: COMPLETE
**Created**: 2026-05-10
**Mapped memory**: `docs/memory/20260510_1545_daemon_decoupling.md`

## CONTEXT / THOUGHT PROCESS

User reported three interrelated problems, all rooted in the daemon and store tracking state independently:

1. **Overlapping work+pause blocks**: When a task is started from web UI and daemon recovers it, daemon creates a SECOND work block. Idle-pause only closes the store's block, leaving daemon's orphan running. This was partially fixed in conversation (daemon now syncs `_current_work_block_id` from store during recovery/pause/resume), but the deeper architectural issue remains — the daemon and store both manage work blocks independently.

2. **Stretch lockout not firing reliably**: Two competing stretch systems exist:
   - `StretchLockout` class: accumulates work seconds via `tick()`, locks screen via `hyprlock`
   - `scheduler.py` `build_schedule()`: inserts `ScheduleKind.STRETCH` items into the schedule at `stretch_interval_minutes`
   These two systems have no awareness of each other. The schedule's stretch break can transition the state machine mid-lockout, calling `pause()` on the lockout and breaking its counter. Also, idle/mic auto-pauses fragment the accumulation counter.

3. **Hyprlock blind timer**: `StretchLockout._lock()` fires `hyprlock` via `Popen` fire-and-forget, then waits a fixed `duration_minutes` timer. User unlocks in seconds by typing password, but the lockout doesn't know — it keeps the "locked" state for the full duration, blocking work resumption.

4. **Mic false positive on voice-to-text**: When user holds spacebar to dictate to Claude Code, the browser grabs the mic. Since `call_apps = []` (any mic = call), the app pauses. The `ignored_apps` list doesn't include the browser. Need to add browser/dictation apps to ignore list, OR flip the detection model so `call_apps` must be explicitly listed (whitelist vs blacklist).

## PHASES

### Phase 1: Make store the single source of truth for block tracking ✅ DONE
**What**: Daemon reads `active_work_block_id` from store via `_get_active_work_block_id()` helper. `_current_work_block_id` removed entirely.
**Verified paths**:
- `_on_confirmed`: checks store for existing active block before creating (no duplicate)
- `_pause_session`: reads from `_get_active_work_block_id()` (store), not cached
- `_resume_session`: creates new work block via store, no cached ID
- `_on_item_finished`: reads from store
- `_recover_active_task`: no cached block ID
- Only `_daemon_pause_block_id` remains cached — acceptable since daemon owns that block (created by `_pause_session`, not a dual-tracking situation)

### Phase 2: Unify the two stretch break systems ✅ DONE (prior session)
**What**: Removed schedule-based stretch breaks from `scheduler.py`. Only `StretchLockout` handles screen locking now.
**Verified**: `scheduler.py` has no stretch item insertion — comment confirms "Stretch lockouts are handled independently by StretchLockout, not inserted into the schedule."

### Phase 3: Fix hyprlock blind timer — detect unlock ✅ DONE
**What**: `_lock()` stores `Popen` handle. `tick()` checks `poll()` — hyprlock exit = user unlocked = break over. Timer kept as fallback.

### Phase 4: Fix mic false positive for voice-to-text / dictation ✅ DONE
**What**: `call_apps = []` now means "no mic pause" (whitelist semantics). `call_apps = ["*"]` for legacy "any mic = call." Docstring documents the change.

### Phase 5: Daemon block-tracking audit + cleanup ✅ DONE
**What**: `_current_work_block_id` and `_current_pause_block_id` removed. `_get_active_work_block_id()` helper reads from store on every call. Only `_daemon_pause_block_id` kept (daemon-owned, no dual-tracking risk).

## RISKS
- Phase 4 is a breaking change for users who rely on `call_apps = []` meaning "any mic pauses." Need to handle migration or at least log a warning.
- Phase 2 removes schedule stretch items — any UI that displays upcoming stretch breaks in the schedule view will lose those entries. May need a different way to show "lockout coming in X minutes" in the dashboard.
- Phase 3 depends on hyprlock exiting cleanly on unlock. Need to verify this behavior.

## TESTING
- Phase 1-2: Start task from web, let daemon recover, go idle, come back — verify NO overlapping blocks in `time_blocks` table.
- Phase 3: Set `interval_minutes = 1`, work for 1 min, verify hyprlock fires, unlock immediately, verify work resumes within seconds (not 5 min).
- Phase 4: Hold spacebar for voice-to-text in browser, verify task does NOT pause. Start a real call app (e.g., Zoom/Discord), verify task DOES pause.
- Phase 5: Run full session with multiple tasks, pauses, resumes — verify timeline has zero overlaps.
