# Fix: Stretch lockout persistence + Finish button behavior

**Task**: Two fixes — (1) stretch lockout uses store work time, (2) Finish button lets task end at ETA
**Status**: COMPLETE

## Problem 1: Stretch lockout loses accumulated time on daemon restart
- `StretchLockout` uses in-memory `_work_accumulated` counter, ticking +1s per tick
- Daemon crash/restart resets it to 0
- Store already has work time blocks — should compute from there

## Fix 1: Replace in-memory counter with store-based computation
- On `tick()`, compute cumulative work seconds from store's `get_time_blocks(today)` where `block_type="work"`
- Compare against `interval_seconds` threshold
- No more in-memory accumulation — survives daemon restarts
- Keep pause/resume/start/stop logic for knowing when to count or not

## Problem 2: Finish button on popup ends task immediately
- Clicking "Finish" calls `store.finish_task_runtime(today)` — ends NOW, not at ETA
- User wants: "let the task run until its scheduled end time, then finish normally"
- This is actually the DEFAULT behavior (doing nothing = task ends at ETA naturally)

## Fix 2: "Finish" button = dismiss popup, let natural deadline handle it
- Change `DECISION_FINISH` handler to just close the popup without calling `finish_task_runtime`
- The task will naturally end when `_check_schedule` detects ETA reached
- `_on_item_finished` already handles store cleanup properly

## Phase 1: Stretch lockout — store-based work time
- Modify `StretchLockout.tick()` to accept store reference and compute work time
- Or better: daemon passes computed work seconds to tick
- Remove `_work_accumulated` in-memory counter

## Phase 2: Finish button — let task end at ETA
- Change `on_decision` handler for `DECISION_FINISH` to not call `finish_task_runtime`
- Just close popup, natural flow handles the rest

## Files Modified
- `src/locked_in/stretch_lockout.py` — store-based work accumulation
- `src/locked_in/daemon.py` — pass work seconds to tick, fix finish handler

## Verification
- Kill daemon mid-task, restart, verify stretch lockout accumulates from where it left off
- Click Finish on popup, verify task continues until ETA then ends naturally
