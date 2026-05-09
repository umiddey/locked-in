# Unified Task Runtime Plan

Created: 2026-05-06 14:50 Europe/Berlin

## Problem

Locked-In currently has multiple competing ideas of "current state":

- The daemon builds an automatic schedule from `daily_sessions.session_started_at`.
- The web frontend starts manual `task_runs`.
- The daemon also creates legacy rows in `warden.db`.
- Metrics use `time_blocks`, but those are written by both daemon and web flows in different ways.
- The frontend shows `Start Task` even when a task is already active.
- The daemon can say a task/break is active while the web UI thinks the next task is pending.

This makes the app feel incoherent. The app must instead have one authoritative runtime model.

## Required Behavior

### Session

Session means "the computer/day is active".

- A session may start automatically when the computer turns on after the daily reset time.
- A session may also start manually from the frontend.
- Starting a session must not imply the first task has started.
- Session start is useful for the day boundary, shutdown logic, and metrics context.

### Task Runtime

Task runtime means "discipline enforcement is active".

- The app starts enforcing only when `Start Task` is clicked.
- If the user clicks `Start Task` at 10:50, the selected/current task starts at 10:50.
- The task ETA is computed from actual task start time plus estimate plus pauses.
- Saved schedule times before task start are only a plan, not runtime truth.
- Once a task starts, the daemon must enforce that task immediately.

Example:

- Task estimate: 60 minutes.
- User clicks `Start Task` at 11:00.
- Initial ETA: 12:00.
- User pauses at 11:15.
- User resumes at 11:30.
- Pause duration: 15 minutes.
- New ETA: 12:15.
- If user pauses again from 11:45 to 12:00, new ETA becomes 12:30.

The important calculation is:

```text
task_eta = task_started_at + estimated_duration + total_paused_seconds_for_that_task
```

### Frontend Controls

The frontend must show controls based on the canonical runtime state.

Rules:

- If no task is running: show `Start Task`.
- If a task is running and not paused: show `Pause` and `Finish Task`.
- If a task is running and paused: show `Resume` and optionally `Finish Task`.
- Do not show `Start Task` while a task is already running.
- Do not show `Pause` when no task is running.
- Do not show daemon-level controls that contradict the task runtime.
- Button labels should use one language consistently: `Start Task`, `Pause`, `Resume`, `Finish Task`.

### Daemon Coupling

The daemon must follow frontend task state.

- Clicking `Start Task` must start the daemon enforcement for that task.
- Clicking `Pause` must pause the daemon and close the current work block.
- Clicking `Resume` must resume the daemon and open a new work block for the same task.
- Clicking `Finish Task` must finish the daemon task and close tracking blocks.
- Mic auto-pause must behave like a normal pause with source `mic`.

The frontend should not create one task runtime while the daemon creates another.

## Current Code Reality

### Relevant Files

```text
src/locked_in/simple_store.py
src/locked_in/web_frontend.py
src/locked_in/daemon.py
src/locked_in/state_machine.py
src/locked_in/db.py
src/locked_in/metrics.py
```

### Current Data Stores

Canonical-ish store:

```text
~/.local/share/locked-in/simple_todos.db
```

Legacy daemon store:

```text
~/.local/share/locked-in/warden.db
```

### Current Tables That Matter

In `simple_todos.db`:

```sql
plans
plan_tasks
daily_sessions
task_runs
sessions_v2
tracking_events
time_blocks
```

In `warden.db`:

```sql
sessions
tasks
interruptions
control_events
```

### What Already Exists

Useful pieces:

- `plan_tasks` has stable local task IDs.
- `task_runs` can record manual task start/finish.
- `time_blocks` can represent actual work/pause/call/break intervals.
- `tracking_events` can store the event stream.
- `sessions_v2` can represent a canonical day/session.
- Daemon control socket already supports `pause`, `resume`, `give_up`, and `status`.
- Mic auto-pause already calls daemon pause/resume behavior.

Broken/missing pieces:

- No canonical active task state shared by frontend and daemon.
- `build_schedule()` uses `daily_sessions.session_started_at`, not actual task start time.
- `Start Task` creates web-side tracking but does not reliably start daemon enforcement.
- `Pause` goes directly to daemon and does not update web-side `task_runs` cleanly.
- Frontend buttons do not hide/show based on task runtime state.
- Daemon inserts breaks/tasks from a generated schedule even if the user did not start those tasks.
- Restarting daemon rebuilds schedule from old session time.
- Task ETA does not derive from actual start plus accumulated pause time.

## Design Decision

Use `simple_todos.db` as the canonical runtime store.

The daemon should become an enforcement worker controlled by the canonical runtime, not an independent scheduler that invents its own current item.

Do not continue treating `warden.db` as runtime truth. Keep it only for old history/backfill until it can be removed.

## Target Runtime Model

Add a new canonical concept: `active_task_runtime`.

This can be implemented either as a table or as a query over `task_runs` + `time_blocks`. Use a table because it makes frontend and daemon sync simpler and less error-prone.

### New Table: `task_runtime`

```sql
CREATE TABLE IF NOT EXISTS task_runtime (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_date TEXT NOT NULL,
    session_id INTEGER,
    plan_task_id INTEGER NOT NULL,
    task_run_id INTEGER,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    paused_at TEXT,
    resumed_at TEXT,
    finished_at TEXT,
    estimated_seconds INTEGER NOT NULL,
    accumulated_pause_seconds INTEGER NOT NULL DEFAULT 0,
    active_work_block_id INTEGER,
    active_pause_block_id INTEGER,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(session_id) REFERENCES sessions_v2(id),
    FOREIGN KEY(plan_task_id) REFERENCES plan_tasks(id),
    FOREIGN KEY(task_run_id) REFERENCES task_runs(id),
    FOREIGN KEY(active_work_block_id) REFERENCES time_blocks(id),
    FOREIGN KEY(active_pause_block_id) REFERENCES time_blocks(id)
);
```

Allowed statuses:

```text
running
paused
finished
abandoned
crashed
```

Invariant:

```text
At most one row where status IN ('running', 'paused')
```

SQLite partial unique index:

```sql
CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_task_runtime
ON task_runtime(target_date)
WHERE status IN ('running', 'paused');
```

### Runtime ETA

For a running task:

```text
eta = started_at + estimated_seconds + accumulated_pause_seconds
```

For a paused task:

```text
eta = started_at + estimated_seconds + accumulated_pause_seconds + current_pause_duration
```

Where:

```text
current_pause_duration = now - paused_at
```

The ETA must be computed dynamically so the UI updates while paused.

### Downstream Schedule Projection

The schedule shown in the UI should be a projection, not stored truth.

Projection rules:

- Completed tasks use actual start/end.
- Active task uses runtime ETA.
- Pending tasks start after the active task ETA.
- Pauses shift the active task ETA and therefore all later projected tasks.
- If no active task exists, pending tasks may be projected from now or from the last completed task end, whichever is later.

This fixes the core bug where the UI still shows `08:34 - 09:34` at 14:49.

## Required Store API

Add these methods to `SimpleTodoStore`.

### `get_or_start_session_v2`

Purpose:

- Return the active `sessions_v2` row for the day.
- Create one if missing.
- Do not crash old active sessions unless explicitly requested.

Signature:

```python
def get_or_start_session_v2(
    self,
    target_date: date,
    started_at: datetime | None = None,
    source: str = "web",
) -> SessionV2:
```

### `get_active_task_runtime`

Purpose:

- Return the one active task runtime, if any.

Signature:

```python
def get_active_task_runtime(self, target_date: date) -> TaskRuntime | None:
```

### `start_task_runtime`

Purpose:

- Start the selected pending task now.
- Create `task_runs`.
- Create `time_blocks(work)`.
- Create `tracking_events(task_started)`.
- Store runtime row.

Signature:

```python
def start_task_runtime(
    self,
    target_date: date,
    plan_task_id: int,
    source: str = "web",
    started_at: datetime | None = None,
) -> TaskRuntime:
```

Validation:

- Error if another runtime is running or paused.
- Error if task is already completed.
- Error if task does not belong to target date.

### `pause_task_runtime`

Purpose:

- Pause the active runtime.
- Close active work block.
- Start pause/call block.
- Log event.
- Update runtime status to `paused`.

Signature:

```python
def pause_task_runtime(
    self,
    target_date: date,
    reason: str = "manual",
    source: str = "web",
    paused_at: datetime | None = None,
) -> TaskRuntime:
```

Validation:

- Error if no active runtime.
- Error if already paused.

### `resume_task_runtime`

Purpose:

- Resume a paused runtime.
- Close active pause block.
- Add pause duration to `accumulated_pause_seconds`.
- Start new work block for same task.
- Log event.
- Update runtime status to `running`.

Signature:

```python
def resume_task_runtime(
    self,
    target_date: date,
    source: str = "web",
    resumed_at: datetime | None = None,
) -> TaskRuntime:
```

Validation:

- Error if no paused runtime.

### `finish_task_runtime`

Purpose:

- Finish active runtime.
- Close open work or pause block.
- Update `task_runs`.
- Mark `plan_tasks.completed_at`.
- Log event.
- Set runtime status to `finished`.

Signature:

```python
def finish_task_runtime(
    self,
    target_date: date,
    outcome: str = "finished",
    notes: str = "",
    finished_at: datetime | None = None,
) -> TaskRuntime:
```

Validation:

- Error if no active runtime.

### `project_runtime_schedule`

Purpose:

- Return the display schedule using actual runtime state.

Signature:

```python
def project_runtime_schedule(
    self,
    target_date: date,
    now: datetime | None = None,
) -> list[RuntimeScheduleEntry]:
```

Each entry should include:

```text
task_id
task_name
status
estimated_seconds
actual_start
actual_end
projected_start
projected_end
actual_work_seconds
pause_seconds
eta
drift_seconds
```

## Daemon Changes

The daemon should stop acting as the owner of task scheduling.

### New Daemon Commands

Add commands to the control server:

```json
{"command": "start_task", "target_date": "2026-05-06", "plan_task_id": 13}
{"command": "pause_task", "reason": "manual"}
{"command": "resume_task"}
{"command": "finish_task", "outcome": "finished", "notes": ""}
```

### Daemon Responsibilities

The daemon should:

- Start enforcement when `start_task` is received.
- Pause enforcement when `pause_task` is received.
- Resume enforcement when `resume_task` is received.
- Finish enforcement when `finish_task` is received.
- Report status from canonical runtime.
- Mic auto-pause should call `pause_task_runtime(reason='mic')`.
- Mic auto-resume should call `resume_task_runtime(source='mic')`.
- Shutdown warning can remain daemon-owned.

### Daemon Should Not

The daemon should not:

- Auto-start the first task from session start.
- Build an independent task schedule from `daily_sessions`.
- Create independent legacy task rows as runtime truth.
- Advance to the next task without user `Start Task`.
- Insert stretch/gym breaks as current runtime items unless those are modeled as explicit break blocks in the canonical store.

### Legacy Mode

Short-term:

- Keep `run-legacy` command but route its task state through canonical runtime.
- Alternatively add `run-daemon` and migrate the systemd unit.

Recommended:

- Keep the systemd service name.
- Replace internals of `Daemon` so it watches/serves canonical runtime.
- Do not introduce another command unless necessary.

## Frontend Changes

### Status Source

Frontend `_plan_payload()` must stop using `build_schedule()` as runtime truth.

Replace:

```python
_, _, entries = self.store.build_schedule(target_date)
open_run = self.store.get_open_run(target_date)
```

With:

```python
runtime = self.store.get_active_task_runtime(target_date)
entries = self.store.project_runtime_schedule(target_date)
```

### Start Task

Current:

- Starts a `task_run`.
- Does not reliably tell daemon to enforce.
- Leaves `Start Task` visible after start.

Target:

- Calls daemon `start_task`.
- Daemon/store starts canonical runtime.
- Frontend redirects.
- On reload, `Start Task` is hidden because runtime exists.

Implementation:

```python
result = send_command(socket_path, {
    "command": "start_task",
    "target_date": target_date.isoformat(),
    "plan_task_id": current_task_id,
})
```

Fallback:

- If daemon is offline, either error clearly or start local runtime without enforcement.
- Recommended default: error clearly, because the user expects enforcement.

### Pause

Current:

- Calls daemon `pause`, independent from web runtime.

Target:

- Show only if runtime status is `running`.
- Calls daemon `pause_task`.
- Daemon/store updates canonical runtime and time blocks.

### Resume

Target:

- Show only if runtime status is `paused`.
- Calls daemon `resume_task`.
- Resume updates accumulated pause seconds and ETA.

### Finish Task

Target:

- Show if runtime status is `running` or `paused`.
- Calls daemon `finish_task`.
- Closes runtime and marks task completed.

### Button Rendering Rules

In `_render_page()`:

```python
runtime_status = runtime["status"] if runtime else None

show_start_task = runtime is None and plan["current_entry"] is not None
show_pause = runtime_status == "running"
show_resume = runtime_status == "paused"
show_finish = runtime_status in {"running", "paused"}
```

Render exactly those controls.

Do not render `Start Task` when `runtime_status in {"running", "paused"}`.

## Metrics Changes

Metrics should use `time_blocks` only for actual time.

Important fields:

- `work` blocks are actual focus time.
- `pause` blocks are user pauses.
- `call` blocks are mic/call pauses.
- `break` blocks are intentional breaks.

Per-task metrics should compute:

```text
estimated_seconds = plan_tasks.duration_minutes * 60
actual_work_seconds = sum(work blocks for task)
pause_seconds = sum(pause/call blocks during task runtime)
wall_clock_seconds = finished_at - started_at
drift_seconds = wall_clock_seconds - estimated_seconds
focus_delta_seconds = actual_work_seconds - estimated_seconds
```

This distinguishes:

- The task took four hours on the clock.
- Only one hour was focused work.
- Three hours were pause/call/idle.

That distinction is the whole point of the tracker.

## Migration / Cleanup

### Existing Active Rows

Before switching models:

- Close stale `sessions_v2` rows older than current active daemon session.
- Close stale open `time_blocks` with metadata `closed_by = migration`.
- Mark stale `task_runs` as `outcome = crashed` if they are open but no runtime exists.

Do not delete history.

### Backfill

Existing `task_runs` and `warden.db` history can remain backfilled into `time_blocks`.

Do not rely on backfilled rows for current active runtime.

## Implementation Steps

### Step 1: Add Runtime Schema

Files:

```text
src/locked_in/simple_store.py
```

Tasks:

- Add `task_runtime` table.
- Add `TaskRuntime` dataclass.
- Add schema version migration.
- Add active runtime unique index.

Verification:

- Creating store on existing DB does not fail.
- Creating store on empty temp DB creates all tables.

### Step 2: Add Store Runtime API

Files:

```text
src/locked_in/simple_store.py
```

Tasks:

- Implement `get_or_start_session_v2`.
- Implement `get_active_task_runtime`.
- Implement `start_task_runtime`.
- Implement `pause_task_runtime`.
- Implement `resume_task_runtime`.
- Implement `finish_task_runtime`.
- Implement ETA calculation helper.
- Implement `project_runtime_schedule`.

Tests:

- Start task at fixed time creates runtime, run, work block, event.
- Pause closes work block and opens pause block.
- Resume closes pause block, adds pause seconds, opens new work block.
- Finish closes work block, marks task completed, closes runtime.
- Cannot start second task while one is running.
- ETA shifts by pause duration.

### Step 3: Route Daemon Through Runtime API

Files:

```text
src/locked_in/daemon.py
src/locked_in/control_server.py
src/locked_in/control_client.py
```

Tasks:

- Add command handling for `start_task`, `pause_task`, `resume_task`, `finish_task`.
- Make daemon status return canonical runtime fields.
- Stop auto-activating tasks from generated schedule.
- Keep hard shutdown logic.
- Keep mic auto-pause, but route it through runtime pause/resume.

Tests:

- `locked-in status` shows no active task after session start.
- Web/CLI `start_task` makes daemon status `task_active`.
- Web/CLI `pause_task` makes daemon status `paused`.
- Web/CLI `resume_task` makes daemon status `task_active`.
- Web/CLI `finish_task` clears active task.

### Step 4: Fix Frontend Control State

Files:

```text
src/locked_in/web_frontend.py
```

Tasks:

- Replace open-run logic with active runtime logic.
- Replace static schedule with projected runtime schedule.
- Hide/show controls based on runtime state.
- Make `Start Task` call daemon `start_task`.
- Make `Pause` call daemon `pause_task`.
- Make `Resume` call daemon `resume_task`.
- Make `Finish Task` call daemon `finish_task`.
- Display active task ETA and pause-adjusted projected end.

Tests:

- No runtime: only `Start Task` visible.
- Running runtime: `Pause` and `Finish Task` visible, `Start Task` hidden.
- Paused runtime: `Resume` and `Finish Task` visible, `Start Task` hidden.
- After finish: `Start Task` visible for next pending task.

### Step 5: Fix Schedule Display

Files:

```text
src/locked_in/simple_store.py
src/locked_in/web_frontend.py
src/locked_in/main.py
```

Tasks:

- Keep old `build_schedule()` only for planning preview if needed.
- Add CLI command or update `show-schedule` to use projected runtime schedule.
- Show:
  - planned estimate
  - actual start
  - projected end
  - actual focused time
  - pause time
  - drift

Acceptance:

- At 14:49 the UI must not show an active/pending task as `08:34 - 09:34`.
- If a task starts at 14:49 with 60-minute estimate, its projected end starts at 15:49.
- If paused 15 minutes, projected end becomes 16:04.

### Step 6: Clean Up Legacy Confusion

Files:

```text
src/locked_in/daemon.py
src/locked_in/db.py
src/locked_in/backfill_metrics.py
```

Tasks:

- Stop writing new runtime truth to `warden.db`, or clearly mark it as legacy-only.
- Prevent multiple stale active legacy sessions from affecting runtime.
- Keep backfill readable.
- Optionally add a maintenance command to close stale legacy sessions.

## Acceptance Criteria

The implementation is correct when all of these are true:

- Starting a session does not start a task.
- Starting a task starts both canonical runtime tracking and daemon enforcement.
- If the task starts at 10:50, the task projected end is based on 10:50, not the day/session start.
- Pausing a task hides `Pause` and shows `Resume`.
- Resuming a task adds pause duration to ETA.
- `Start Task` is hidden while a task is running or paused.
- Finishing a task clears the active runtime and shows `Start Task` for the next pending task.
- Schedule display never shows stale morning times as current runtime truth.
- Metrics distinguish focus time, pause/call time, wall-clock task duration, and estimate drift.
- Mic auto-pause uses the same pause/resume path as manual pause.

## Recommended Implementation Order

Do not start with CSS or visual cleanup.

Order:

1. Store runtime API.
2. Runtime ETA/projection tests.
3. Daemon command routing.
4. Frontend button state.
5. Schedule display.
6. Legacy cleanup.

This order prevents another UI layer from being built on top of a broken state model.
