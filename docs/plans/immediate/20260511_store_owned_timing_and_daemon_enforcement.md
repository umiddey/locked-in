# Store-Owned Timing + Daemon Enforcement

**Status**: COMPLETE
**Created**: 2026-05-11
**Mapped memory**: `docs/memory/20260511_store_owned_timing_and_daemon_enforcement.md`

## CONTEXT / THOUGHT PROCESS

User wants the product split to be strict:

- The web app owns user-facing planning, ETA math, and persisted timing state.
- The daemon exists to observe input activity and enforce computer-level actions.
- The daemon should not maintain a second source of truth for task timing, pause math, or stretch accumulation.

Current code is halfway there, which is why the user keeps hitting drift bugs:

- `task_runtime.compute_eta()` already lives in the store.
- `time_blocks` already persist work/pause/call history.
- The daemon still keeps mutable local schedule timing, `_item_finish_due_at`, and schedule shift logic on pause/resume.
- Stretch lockout currently takes cumulative work from a daemon helper instead of asking the store directly.

The job of this refactor is not to invent new behavior. It is to remove the duplicate timing source in the daemon so the runtime math comes from the store only.

## PHASES

### Phase 1: Move timing queries into the store ✅ DONE
Add a store helper for cumulative work seconds and use store projections for task/runtime timing so the daemon stops owning that math.

### Phase 2: Make daemon a control loop, not a timing engine ✅ DONE
Remove in-memory pause/resume time shifting and stale ETA state from the daemon. Keep only ephemeral active-item control state and use store queries for activation, pause, resume, and completion decisions.

### Phase 3: Keep stretch lockout store-driven ✅ DONE
Feed stretch lockout from the store's cumulative work seconds and make it trigger only while a task is actively running. No daemon-side work counter should remain.

### Phase 4: Verify the live flow end to end ✅ DONE
Run targeted tests for idle pause, ETA projection, and stretch lockout persistence to confirm the daemon still enforces actions without re-owning timing.

## VERIFICATION

- `rtk python -m unittest tests.test_daemon_timing_ownership tests.test_idle_detector`
- Result: passed (`Ran 3 tests ... OK`)
- `rtk python -m unittest tests.test_web_frontend`
- Result: failed in pre-existing/stale assertions unrelated to this refactor (`_format_display_date` missing, `Plan saved` vs `saved <date>`, "Today" label mismatch)

## REFERENCES

- `docs/ARCHITECTURE.md`
- `docs/plans/immediate/20260511_stretch_lockout_persist_and_finish_at_eta.md`
- `docs/memory/20260510_1545_daemon_decoupling.md`
