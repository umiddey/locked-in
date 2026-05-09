# Plan: Three Focus Warden Fixes
**Date**: 2026-05-09
**Status**: IN PROGRESS

## Context (conversation thought-process)

User reported 3 bugs:
1. **Task description field missing** — tasks need an optional description column in plan_tasks table + UI
2. **Wrong notifications** — When saving tasks (not starting), daemon sends "Session started" notification. Also, next-task notification fires too early and sometimes shows wrong task (skip-ahead).
3. **Stretch lockout is random** — The lockout should trigger when cumulative actual WORK time hits 60 min across tasks+pauses, not randomly. Currently `tick()` adds 1s per second regardless of pause state but the accumulation doesn't properly reset between tasks or track cumulative work across tasks.

## Phase 1: Task Description Column

**Files**: `simple_store.py`, `web_frontend.py`, `planning.py`, `simple_ui.py`

- Add `description TEXT` column to `plan_tasks` table via `_ensure_column`
- Add `description` field to `TaskDraft`, `EditableTaskDraft`, `PlanTask` dataclasses
- Update `save_plan_rows`, `get_plan`, `update_task` to handle description
- Add description textarea in task editor row in web frontend
- Update planner UI hint text

**Justification**: Straightforward column addition. All existing description values default to NULL, no migration needed.

## Phase 2: Fix Notifications

**Files**: `daemon.py`

Root cause analysis:
- **"Session started" on save**: In `_bootstrap_session()` line 208, `notify("Focus Warden", "Session started")` fires unconditionally when the daemon boots and finds a plan. The web frontend's "Save + Start" sends `start_task` command which goes through `_handle_start_task` — but the daemon also calls `_bootstrap_session()` on startup which fires that notification. The fix: don't send "Session started" on bootstrap. Only send task-specific notifications.
- **Next task notification too early/wrong**: In `_activate_item()` line 458, `notify("Focus Warden", f"Next: {item.title}")` fires when ANY schedule item activates. But the schedule is built from daemon's scheduler (old system), while the web uses task_runtime (new system). The daemon's schedule iteration in `_tick()` at line 267-279 walks `self.schedule` items by `scheduled_start` time — but those times don't shift with pauses/extensions. The 5-minute-before-next notification doesn't exist — it's just the `_activate_item` notification which fires whenever `now >= item.scheduled_start`. We need a proper "next task in 5 min" notification that fires based on the CURRENT task's ETA, not the schedule.

Fix approach:
- Remove the generic "Session started" from bootstrap
- Add a proper `_poll_next_task_warning()` that checks current runtime ETA and fires notification 5 min before current task ends, showing the ACTUAL next pending task

## Phase 3: Fix Stretch Lockout

**Files**: `stretch_lockout.py`, `daemon.py`

Root cause:
- `StretchLockout.tick()` adds 1.0 per second unconditionally (when not paused/locked). But `_work_accumulated` resets to 0 on `stop()` and on unlock. The problem: `stop()` is called when a task FINISHES (`_on_item_finished` line 658), and `start()` resets accumulated to 0. So cross-task accumulation is broken.
- User wants: cumulative ACTUAL WORK time across all tasks. Pauses should NOT count. When cumulative work hits 60 min → lockout.

Fix approach:
- Remove the `stop()` call on task finish. Instead, keep the stretch lockout running across tasks. Only reset accumulated on lockout completion.
- Make `tick()` only accumulate when not paused (already handled by `_paused` flag). But we need the daemon to NOT call `stop()` between tasks — only `stop()` when session ends (give_up/finish/shutdown).
- The `start()` method should NOT reset `_work_accumulated` if already active. Only reset on explicit `reset()` after a lockout completes.

## Phase Status
- [x] Phase 1: Task description
- [x] Phase 2: Fix notifications
- [x] Phase 3: Fix stretch lockout

## Verification
```
python -m pytest tests/ -v  # 6 passed
```

All imports clean, all tests pass.
