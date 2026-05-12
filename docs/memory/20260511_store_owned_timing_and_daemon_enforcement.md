# Naming convention: 20260511_XXXX_store_owned_timing_and_daemon_enforcement
**Task**: Move timing ownership into the store and keep the daemon as a control/enforcement loop
**Status**: COMPLETE
## WHAT
- Removed daemon-owned ETA shifting and schedule-time mutation.
- Added store-driven cumulative work queries for stretch lockout.
- Kept idle pause/resume and task enforcement tied to persisted runtime state and store projections.
## HOW
- Added `SimpleTodoStore.get_cumulative_work_seconds()`.
- Reworked daemon schedule advancement to use `project_runtime_schedule()` instead of shifting local ETA state.
- Kept stretch lockout fed from store cumulative work and removed daemon-side work counters.
- Added focused unit tests for idle pause, store-driven stretch ticking, and projection-based activation.
## WHY
- The user wanted the store/web side to own timing while the daemon only enforces computer actions.
- Duplicating timing in the daemon and store creates stale ETA and pause bugs.
- The daemon should be the executor, not a second scheduler.
## FILES MODIFIED
- `src/locked_in/simple_store.py`: added cumulative work helper.
- `src/locked_in/daemon.py`: removed local ETA shifting, used store projection, tightened manual finish handling.
- `tests/test_daemon_timing_ownership.py`: added unit coverage for store-owned timing behavior.
- `docs/plans/immediate/20260511_store_owned_timing_and_daemon_enforcement.md`: plan and phased scope.
- `docs/memory/20260511_store_owned_timing_and_daemon_enforcement.md`: execution log for the refactor.
## NEXT SESSION
- If the web frontend tests are still relevant, update their stale assertions to match the current UI wording.
- Consider removing the remaining `_task_started_at` mirror if you want the daemon even thinner.
## REFERENCES
- `docs/ARCHITECTURE.md`
- `docs/plans/immediate/20260511_stretch_lockout_persist_and_finish_at_eta.md`
- `docs/plans/immediate/20260511_fix_auto_chain_stale_deadline.md`
