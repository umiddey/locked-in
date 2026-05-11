# ETA Popup Three Options

**Status**: COMPLETE
**Created**: 2026-05-10
**Size**: NON-TINY (daemon + popup + web frontend + new auto-chain flag)

## WHAT

Currently, the ETA warning popup (PyQt6, `eta_warning.py`) fires when a task's scheduled time has elapsed. It shows **two options**: Finish and Extend.

The user wants a **pre-task-end** popup that fires **5 minutes before** the current task's ETA, with **three options**:

1. **Auto-continue** → When the current task finishes (5 min later), immediately start the next task in the pipeline
2. **Manual** → Don't auto-continue; user starts next task from the web frontend at their own pace
3. **Extend** → Extend the current task by `default_extend_minutes` (from config, e.g. 15)

This replaces the current "time's up" popup behavior — the popup now fires *before* time is up, giving the user advance warning.

## CURRENT BEHAVIOR (for context)

- `_poll_eta_warning()` in daemon.py fires when `min_left <= 5` AND shows a notification about the next task
- The PyQt6 popup (`eta_warning.py`) fires when scheduled time has elapsed (not 5 min before)
- Popup offers: Finish Task | Extend +Xm
- There's also a `_next_task_notified_for` that fires a notification about the upcoming task

## THOUGHT PROCESS

The key insight is: the current `_poll_eta_warning` fires at 5 min remaining but only sends a *notification* about next task. The actual PyQt6 popup fires at ETA (= time elapsed). We need to:

1. Move the popup to fire at **5 min before ETA** instead of at ETA
2. Change the popup to offer 3 choices instead of 2
3. Add an `auto_chain_next` flag to the daemon so that when a task finishes normally (via `_on_item_finished`), if the flag is set, it auto-starts the next task instead of going to `AWAITING_TASK_START`
4. The "Manual" option = do nothing special (current default behavior = go to AWAITING_TASK_START)
5. The "Extend" option = extend + reset the warning flag so popup doesn't re-fire

For web-only mode (no daemon), this will be handled via a browser-based popup/alert in the web frontend's JS polling. But the user said they're using the daemon + PyQt6 popup, so that's the primary target.

## PHASES

### Phase 1: Update PyQt6 Popup (eta_warning.py)
**Status**: COMPLETE

- Add a new decision constant `DECISION_AUTO_CONTINUE`
- Change popup to fire as "5 min warning" instead of "time's up"
- Update styling: tag from "TIME'S UP" → "5 MIN LEFT"
- Add third button: "Auto-continue to next"
- Remove the overtime timer (popup fires before overtime)
- Instead show a countdown to ETA

### Phase 2: Daemon handling for auto-chain (daemon.py)
**Status**: COMPLETE

- Add `self._auto_chain_next: bool = False` flag
- Move popup to fire at `eta - 5min` (it already fires there for notification, just also show popup)
- On `DECISION_AUTO_CONTINUE`: set `_auto_chain_next = True`, finish the task at ETA
- On `DECISION_FINISH`: finish immediately (same as before)
- On `DECISION_EXTEND`: extend, reset warning flags (same as before)
- In `_on_item_finished()`: if `_auto_chain_next` is True AND there's a next item, call `_activate_item()` on it directly (bypass AWAITING_TASK_START)
- In `_on_item_finished()`: reset `_auto_chain_next = False`

### Phase 3: Web frontend fallback (web_frontend.py)
**Status**: COMPLETE

- The web frontend already has polling via `/api/status`. The `_poll_eta_warning` in the daemon handles the popup.
- For web-only mode: add a JS-based alert that fires 5 min before ETA, offering the same 3 options via fetch POST to existing endpoints (/run/extend, /run/finish-current, + new auto-chain flag endpoint)
- This is LOW priority since user uses daemon mode primarily
- Added `set_auto_chain` command to control protocol for web-triggered auto-chain

## VERIFICATION
- Start a task with 10 min duration
- After 5 min, popup should appear with 3 options
- Test each option works correctly
- Test that auto-continue chains into next task immediately
