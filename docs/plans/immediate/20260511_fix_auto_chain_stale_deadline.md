# Fix: Auto-chain uses stale deadline, ignores pause-adjusted ETA

**Task**: Fix `_check_schedule` to use store's `compute_eta()` instead of stale `_item_finish_due_at`
**Status**: COMPLETE

## Problem
- `_check_schedule` (daemon.py:297) checks `_item_finish_due_at` to decide if a task is done
- `_item_finish_due_at` is set once at activation (line 428) as flat `now + duration_minutes`
- Idle auto-resume (line 228-231) and mic auto-resume (line 266) do NOT shift `_item_finish_due_at`
- Only manual `_resume_session` (line 458) shifts it — but even that is a band-aid
- Meanwhile, the popup correctly uses `compute_eta()` which accounts for all pauses
- Result: task gets force-finished by stale deadline BEFORE popup can trigger auto-chain

## Root Cause
Two different clocks. The finish check should look at the same thing the popup looks at — the store's computed ETA, which is the single source of truth for "when does this task actually end."

## Fix — Phase 1: Make `_check_schedule` use store ETA
- In `_check_schedule`, replace `_item_finish_due_at` check with `rt.compute_eta(now)` from the store
- The store already tracks `estimated_seconds + accumulated_pause_seconds` — that IS "active time"
- When `now >= eta` → task is done, fire `_on_item_finished()`
- This makes the finish check identical to what the popup uses

## Fix — Phase 2: Kept `_item_finish_due_at` as secondary tracking (no harm)
- Still set/cleared in recovery/activation/finish for potential future use
- `_resume_session` `+= shift` kept — harmless
- The schedule check is the critical path and now uses store ETA

## Files Modified
- `src/locked_in/daemon.py` — `_check_schedule`, potentially remove `_item_finish_due_at` tracking in `_resume_session`, `_on_confirmed`, `_activate_item`

## Verification
- Start a 2-min task, idle-auto-pause it for 30s, resume, verify it doesn't finish early
- Start a task, click auto-continue on popup, verify next task starts automatically
