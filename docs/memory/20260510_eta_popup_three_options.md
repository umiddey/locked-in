# 20260510_1600_eta_popup_three_options

**Task**: Replace 2-option ETA popup with 3-option pre-task-end popup (auto-continue, manual, extend)
**Status**: COMPLETE

## WHAT
- Changed eta_warning.py popup to fire 5 min before task end with 3 options ✓
- Added auto-chain flag to daemon for automatic next-task start ✓
- Added set_auto_chain command to control protocol ✓

## HOW
- Phase 1: Rewrote EtaWarningPopup — 3 buttons (Auto-Continue, Finish, Extend), countdown timer instead of overtime, "5 MIN LEFT" tag, shows next task name
- Phase 2: Added `_auto_chain_next` bool to Daemon.__init__. On DECISION_AUTO_CONTINUE sets flag. In `_on_item_finished` checks flag — if True, finds next TASK item in schedule and calls `_activate_item` directly (bypasses AWAITING_TASK_START wait). Resets flag after use.
- Added `set_auto_chain` command to control protocol + `auto_chain_next` in status response

## WHY
User gets popup AFTER task is over. Wants it BEFORE (5 min warning) with ability to chain into next task automatically. The "auto-continue" is the killer feature — no manual start needed between tasks. Current popup only had finish/extend.

## FILES MODIFIED
- src/locked_in/eta_warning.py: 3-option popup, countdown, auto-continue button, next task label, eta param
- src/locked_in/daemon.py: auto_chain_next flag, popup timing passes eta+next_task, _on_item_finished chains, set_auto_chain command, status includes auto_chain_next

## NEXT SESSION
- Test e2e with daemon running a plan
- Consider web-only mode JS popup (low priority)

## REFERENCES
- docs/plans/immediate/eta_popup_three_options.md
