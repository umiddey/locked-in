# Remove Daemon Task-Start Mirror

**Status**: COMPLETE
**Created**: 2026-05-11
**Mapped memory**: `docs/memory/20260511_remove_daemon_task_start_mirror.md`

## CONTEXT / THOUGHT PROCESS

The store-owned timing refactor removed the daemon's duplicate schedule/ETA math, but one last daemon-side timing mirror remains: `_task_started_at`.

That attribute is only there to remember when the daemon itself activated a task so it can later compute task duration for the legacy DB row. That is still a hidden local clock, and it is not necessary because:

- when the daemon activates a task, it already writes `actual_start` into the task row immediately;
- when a task is finished, the daemon can read that persisted `actual_start` back from the DB or fall back to the store runtime start timestamp;
- if neither exists, the finish time itself is still valid as a fallback, which keeps the system correct without a daemon memory mirror.

This change makes the daemon thinner and keeps the timing source on persisted records rather than in a mutable attribute.

## PHASES

### Phase 1: Remove the daemon-side start timestamp mirror ✅ DONE
Delete `_task_started_at` from daemon state and replace finish-time duration calculation with persisted `actual_start` lookup or store runtime start lookup.

### Phase 2: Keep task activation and finish behavior intact ✅ DONE
Ensure daemon-started tasks still write `actual_start` immediately, and manual/web-started tasks continue to finish correctly from stored runtime state.

### Phase 3: Verify the cleanup ✅ DONE
Run focused unit tests for idle pause, store-owned stretch ticking, and schedule activation so the thinner daemon still enforces correctly.

## VERIFICATION

- `rtk python -m unittest tests.test_daemon_timing_ownership tests.test_idle_detector`
- Result: passed (`Ran 4 tests ... OK`)

## REFERENCES

- `docs/plans/immediate/20260511_store_owned_timing_and_daemon_enforcement.md`
- `docs/ARCHITECTURE.md`
- `docs/memory/20260510_1545_daemon_decoupling.md`
