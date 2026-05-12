# Naming convention: 20260511_XXXX_remove_daemon_task_start_mirror
**Task**: Remove the last daemon-side task-start timestamp mirror
**Status**: COMPLETE
## WHAT
- Deleted `_task_started_at` from daemon state.
- Compute completion duration from persisted `actual_start` or store runtime state.
- Kept task activation/finish behavior intact without daemon-held start time.
## HOW
- Read `actual_start` from the legacy task row when finishing daemon-started tasks.
- Fall back to store runtime `started_at` for store-started tasks.
- Use finish time as the final fallback so the daemon never needs its own start-time cache.
## WHY
- The daemon should enforce actions, not carry a second hidden clock.
- Persisted rows already capture the needed start timestamp.
- Removing the mirror reduces drift and keeps timing ownership in storage.
## FILES MODIFIED
- `src/locked_in/daemon.py`: removed `_task_started_at`, finished task runtimes from store state, and used persisted timings on finish.
- `tests/test_daemon_timing_ownership.py`: added regression coverage for finishing without a daemon-held start mirror.
- `docs/plans/immediate/20260511_remove_daemon_task_start_mirror.md`: plan for the cleanup.
## NEXT SESSION
- None required for this cleanup unless a new drift path appears.
## REFERENCES
- `docs/plans/immediate/20260511_store_owned_timing_and_daemon_enforcement.md`
- `docs/ARCHITECTURE.md`
