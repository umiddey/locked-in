# 20260510_1545_daemon_decoupling
**Task**: Decouple daemon from store block tracking, fix stretch lockout, fix mic false positive
**Status**: COMPLETE

## WHAT
- Daemon and store both track work/pause blocks independently → overlapping timeline blocks ⚠️
- Two competing stretch break systems (StretchLockout + scheduler) → unreliable lockout ⚠️
- Hyprlock uses blind timer instead of detecting unlock → 5min wait after 2s unlock ⚠️
- `call_apps = []` means "any mic = call" → voice-to-text falsely pauses work ⚠️
- Partial fix applied: `_recover_active_task` now syncs `_current_work_block_id` from store ✓

## HOW
- Phase 1 ✓: `_get_active_work_block_id()` helper reads store. `_on_confirmed` checks for existing block before creating. No more dual-tracking.
- Phase 2 ✓: Already done prior session — scheduler has no stretch items
- Phase 3 ✓: `_lock()` stores Popen handle, `tick()` checks `poll()` for hyprlock exit. Timer kept as fallback.
- Phase 4 ✓: `_matching_apps()` now treats `call_apps = []` as "nothing matches". `["*"]` for legacy behavior.
- Phase 5 ✓: `_current_work_block_id` and `_current_pause_block_id` removed. Only `_daemon_pause_block_id` kept (daemon-owned).

## WHY
- User observed overlapping work+pause blocks in timeline — caused by daemon creating duplicate work blocks when recovering web-started tasks
- Stretch lockout set to 1 minute but fires inconsistently — two stretch systems interfere with each other
- After hyprlock unlock, user waits full 5 min timer — pointless
- Voice-to-text triggers mic detection → false call pause

## FILES MODIFIED
- `daemon.py`: removed `_current_work_block_id`/`_current_pause_block_id`, added `_get_active_work_block_id()` helper, `_daemon_pause_block_id` for daemon-owned pause blocks
- `stretch_lockout.py`: added `_lock_proc` field, `tick()` detects hyprlock exit via `poll()`
- `activity_detector.py`: `_matching_apps()` empty call_apps = nothing matches (whitelist)

## NEXT SESSION
- Test all phases end-to-end: start task from web, idle pause, resume, mic detection, stretch lockout with 1min interval
- Commit all changes

## REFERENCES
- Plan: `docs/plans/immediate/daemon_decoupling.md`
- Bug evidence: `time_blocks` table showed blocks 280 (work, web) and 281 (work, daemon) overlapping with block 282 (pause, idle) on 2026-05-10
- Config: `config.toml` at project root
