# 20260511_fix_auto_chain_stale_deadline

**Task**: Fix auto-chain using stale `_item_finish_due_at` instead of store ETA
**Status**: COMPLETE

## WHAT
- `_check_schedule` used flat wall-clock `_item_finish_due_at` ❌
- Should use store's `compute_eta()` which accounts for pauses ✓
- Idle/mic auto-resume never shifted `_item_finish_due_at` ❌

## HOW
- Replace `_item_finish_due_at` check in `_check_schedule` with `rt.compute_eta(now)`
- Remove redundant `_item_finish_due_at` shift hacks in resume paths

## WHY
User clicked Auto-Continue on popup, but task got force-finished by stale deadline before popup could set `_auto_chain_next = True`. User asked "why doesn't it look at the actual running time?" — exactly right. The store tracks active time correctly via `compute_eta()`, but `_check_schedule` ignored it and used a separate unsynced variable.

## FILES MODIFIED
- `src/locked_in/daemon.py` — auto-chain fix, finish-at-ETA fix, cumulative work seconds method
- `src/locked_in/stretch_lockout.py` — store-based work time, persisted offset

## NEXT SESSION
- Test all three fixes: auto-chain, finish-at-ETA, stretch lockout persistence
