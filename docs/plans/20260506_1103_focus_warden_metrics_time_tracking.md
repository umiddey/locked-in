# Locked-In Metrics-Grade Time Tracking Plan

Created: 2026-05-06 11:03 Europe/Berlin

## Goal

Turn Locked-In from a basic planner/timer into a reliable local time-tracking and productivity metrics system.

The finished system must answer questions like:

- How much focused work did I do today, this week, this month?
- Which tasks/projects/categories consumed the most time?
- How accurate were my estimates?
- How many interruptions happened, why, and how much time did they cost?
- How much time was active work vs pause vs break vs call vs idle?
- What did I actually work on between two timestamps?
- Which tasks repeatedly run over estimate?
- What time of day am I most productive?
- How much planned work did I complete vs abandon?
- How often do I start late, pause, context switch, or leave tasks open?

The key requirement is not just “store more fields”. The app needs a coherent event and time-block model so metrics can be computed consistently.

## Current State

There are currently two independent tracking stores.

### Simple Store

File:

```text
src/locked_in/simple_store.py
```

Database:

```text
~/.local/share/locked-in/simple_todos.db
```

Tables:

```sql
plans(target_date, saved_at)
plan_tasks(id, target_date, position, task_name, duration_minutes, completed_at, last_outcome)
daily_sessions(target_date, session_started_at)
task_runs(id, plan_task_id, target_date, task_name, scheduled_start, started_at, ended_at, duration_seconds, outcome, notes)
```

Strengths:

- Tracks planned tasks.
- Tracks basic task starts/finishes from the simple UI/web dashboard.
- Stores notes/outcome.

Problems:

- Task runs can remain open indefinitely.
- Does not track pauses or interruptions.
- Does not track projects/tags/categories.
- Does not track schedule drift or estimate error in a first-class way.
- Does not track active vs idle time.
- Does not integrate cleanly with daemon task rows.

### Legacy Daemon Store

File:

```text
src/locked_in/db.py
```

Database:

```text
~/.local/share/locked-in/warden.db
```

Tables:

```sql
sessions(id, started_at, ended_at, shutdown_deadline, status)
tasks(id, session_id, notion_task_id, title, normalized_key, scheduled_start, scheduled_duration_minutes, actual_start, actual_end, actual_minutes, status)
interruptions(id, session_id, kind, started_at, ended_at, duration_minutes)
control_events(id, session_id, event_type, payload_json, created_at)
```

Strengths:

- Has actual task starts/ends.
- Has interruptions for pause and call detection.
- Has control events.

Problems:

- Separate from simple dashboard store.
- Multiple stale active sessions can accumulate.
- Does not track project/category/tags.
- Does not store durable event history beyond control events.
- Interruptions are not tied to task/time blocks robustly.
- Breaks and gym blocks are scheduled, but not recorded as actual completed time blocks.

## Design Direction

Use one canonical tracking layer that both the simple UI and daemon write to.

Do not try to compute all metrics from scattered task rows. Add two canonical primitives:

1. `tracking_events`
2. `time_blocks`

`tracking_events` captures the exact event stream.

`time_blocks` captures intervals of time with a semantic type.

Metrics should be computed from `time_blocks` and enriched by tasks/projects/tags.

## New Concepts

### Event

An instantaneous fact:

- session_started
- session_ended
- task_planned
- task_started
- task_finished
- task_abandoned
- task_skipped
- task_extended
- pause_started
- pause_ended
- break_started
- break_ended
- call_started
- call_ended
- idle_started
- idle_ended
- app_focus_changed
- note_added
- estimate_changed
- plan_changed
- shutdown_warning
- shutdown_triggered

### Time Block

A closed or open interval:

- work
- pause
- break
- call
- idle
- planning
- admin
- unknown

Every block has:

- start time
- optional end time
- type
- optional task
- optional project/category/tags
- source
- metadata

### Task Identity

Tasks need a stable internal identity, even if their name changes.

Current `plan_tasks.id` is acceptable as the first internal task id for local tasks.

Future Notion task ids can map into the same model.

### Project/Category/Tags

Add lightweight metadata to tasks:

- `project`
- `category`
- `tags`
- optional `energy_level`
- optional `difficulty`

Keep these optional. Do not block tracking if they are blank.

## Database Plan

Use `simple_todos.db` as the canonical store going forward. Keep `warden.db` readable for migration/history, but new metrics should live in `simple_todos.db`.

Reason:

- Simple UI/web frontend already use `simple_todos.db`.
- Plans/tasks already live there.
- It is easier to attach metrics to planned tasks.

## Schema Additions

Add migrations in `SimpleTodoStore._ensure_columns()` or a real migration function.

Recommended: add a `schema_meta` table with integer versioning before adding many changes.

### schema_meta

```sql
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
```

Store:

```text
schema_version = 2
```

### sessions_v2

Daily sessions should become first-class and multi-session capable.

```sql
CREATE TABLE IF NOT EXISTS sessions_v2 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_date TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    status TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'local',
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

Valid statuses:

```text
active
finished
abandoned
shutdown
crashed
```

Keep existing `daily_sessions` for compatibility at first, but new code should create/read `sessions_v2`.

### tracking_events

```sql
CREATE TABLE IF NOT EXISTS tracking_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_date TEXT NOT NULL,
    session_id INTEGER,
    plan_task_id INTEGER,
    event_type TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    source TEXT NOT NULL,
    metadata_json TEXT,
    FOREIGN KEY(session_id) REFERENCES sessions_v2(id),
    FOREIGN KEY(plan_task_id) REFERENCES plan_tasks(id)
);
```

Indexes:

```sql
CREATE INDEX IF NOT EXISTS idx_tracking_events_date_time
ON tracking_events(target_date, occurred_at);

CREATE INDEX IF NOT EXISTS idx_tracking_events_task
ON tracking_events(plan_task_id, occurred_at);

CREATE INDEX IF NOT EXISTS idx_tracking_events_type
ON tracking_events(event_type, occurred_at);
```

### time_blocks

```sql
CREATE TABLE IF NOT EXISTS time_blocks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_date TEXT NOT NULL,
    session_id INTEGER,
    plan_task_id INTEGER,
    block_type TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    duration_seconds INTEGER,
    source TEXT NOT NULL,
    project TEXT,
    category TEXT,
    tags_json TEXT,
    quality_score INTEGER,
    energy_score INTEGER,
    interruption_count INTEGER NOT NULL DEFAULT 0,
    metadata_json TEXT,
    FOREIGN KEY(session_id) REFERENCES sessions_v2(id),
    FOREIGN KEY(plan_task_id) REFERENCES plan_tasks(id)
);
```

Valid block types:

```text
work
pause
break
call
idle
planning
admin
unknown
```

Indexes:

```sql
CREATE INDEX IF NOT EXISTS idx_time_blocks_date_start
ON time_blocks(target_date, started_at);

CREATE INDEX IF NOT EXISTS idx_time_blocks_task
ON time_blocks(plan_task_id, started_at);

CREATE INDEX IF NOT EXISTS idx_time_blocks_type
ON time_blocks(block_type, started_at);
```

### Extend plan_tasks

Add columns:

```sql
ALTER TABLE plan_tasks ADD COLUMN project TEXT;
ALTER TABLE plan_tasks ADD COLUMN category TEXT;
ALTER TABLE plan_tasks ADD COLUMN tags_json TEXT;
ALTER TABLE plan_tasks ADD COLUMN estimate_source TEXT;
ALTER TABLE plan_tasks ADD COLUMN priority INTEGER;
ALTER TABLE plan_tasks ADD COLUMN difficulty INTEGER;
ALTER TABLE plan_tasks ADD COLUMN energy_required INTEGER;
ALTER TABLE plan_tasks ADD COLUMN created_at TEXT;
ALTER TABLE plan_tasks ADD COLUMN updated_at TEXT;
```

Do this through `_ensure_column`, not direct unconditional `ALTER TABLE`.

### Extend task_runs

Keep `task_runs` for backward compatibility but enrich it.

Add:

```sql
ALTER TABLE task_runs ADD COLUMN time_block_id INTEGER;
ALTER TABLE task_runs ADD COLUMN project TEXT;
ALTER TABLE task_runs ADD COLUMN category TEXT;
ALTER TABLE task_runs ADD COLUMN tags_json TEXT;
ALTER TABLE task_runs ADD COLUMN quality_score INTEGER;
ALTER TABLE task_runs ADD COLUMN energy_score INTEGER;
ALTER TABLE task_runs ADD COLUMN interruption_count INTEGER NOT NULL DEFAULT 0;
```

Eventually `task_runs` can become a view over `time_blocks`, but do not do that in the first implementation.

## Store API Additions

File:

```text
src/locked_in/simple_store.py
```

Add dataclasses:

```python
@dataclass
class TrackingEvent:
    id: int
    target_date: str
    session_id: int | None
    plan_task_id: int | None
    event_type: str
    occurred_at: str
    source: str
    metadata_json: str | None

@dataclass
class TimeBlock:
    id: int
    target_date: str
    session_id: int | None
    plan_task_id: int | None
    block_type: str
    started_at: str
    ended_at: str | None
    duration_seconds: int | None
    source: str
    project: str | None
    category: str | None
    tags_json: str | None
    quality_score: int | None
    energy_score: int | None
    interruption_count: int
    metadata_json: str | None
```

Add methods:

```python
def start_session_v2(target_date: date, started_at: datetime | None = None, source: str = "local") -> int
def finish_session_v2(session_id: int, status: str = "finished", ended_at: datetime | None = None) -> None
def get_active_session_v2(target_date: date) -> SessionV2 | None
def log_event(target_date: date, event_type: str, *, session_id=None, plan_task_id=None, source="local", metadata=None, occurred_at=None) -> int
def start_time_block(target_date: date, block_type: str, *, session_id=None, plan_task_id=None, source="local", metadata=None, started_at=None) -> int
def finish_time_block(block_id: int, ended_at: datetime | None = None, metadata_patch: dict | None = None) -> TimeBlock
def get_open_time_block(session_id: int | None = None, block_type: str | None = None) -> TimeBlock | None
def close_open_blocks(target_date: date, ended_at: datetime | None = None, reason: str = "cleanup") -> list[TimeBlock]
def get_time_blocks(target_date: date) -> list[TimeBlock]
def get_time_blocks_range(start_date: date, end_date: date) -> list[TimeBlock]
```

Rules:

- Starting a work block should close any open work block for the same session first.
- Starting a pause/call/idle block should not destroy the work block unless the design decides work is exclusive. Preferred: pause/call should pause work by ending the current work block, then resume creates a new work block.
- Avoid overlapping blocks of the same exclusive type.
- Always write a matching event when starting/ending blocks.

## Runtime Behavior Changes

### Starting the Daemon

File:

```text
src/locked_in/daemon.py
```

When daemon creates a session:

1. Create or reuse `sessions_v2`.
2. Log `session_started`.
3. Do not create duplicate active sessions for the same target date without closing the old one.

Pseudo:

```python
self.tracking_session_id = self.store.start_session_v2(today, session_started_at, source="daemon")
self.store.log_event(today, "session_started", session_id=self.tracking_session_id, source="daemon")
```

### Starting a Task

When `_on_confirmed()` transitions to `TASK_ACTIVE`:

1. Update old daemon task row as today.
2. Start a canonical `time_blocks` row of type `work`.
3. Log `task_started`.
4. Attach `plan_task_id` where possible.

Important: currently daemon uses `ScheduleItem.task_ref.id` derived from local `plan_tasks.id`. Preserve that mapping.

Pseudo:

```python
self._current_work_block_id = self.store.start_time_block(
    today,
    "work",
    session_id=self.tracking_session_id,
    plan_task_id=int(self.current_item.task_ref.id),
    source="daemon",
    metadata={"title": self.current_item.title},
)
```

### Finishing a Task

When `_on_item_finished()` completes a task:

1. Finish the current `work` block.
2. Log `task_finished`.
3. Update `plan_tasks.completed_at`.
4. Update old daemon task row.

Pseudo:

```python
self.store.finish_time_block(self._current_work_block_id)
self.store.log_event(today, "task_finished", ...)
```

### Pause

When `_pause_session()` is called:

1. Finish the current work block with metadata `{"ended_by": "pause"}`.
2. Start a pause/call block depending on `kind`.
3. Log `pause_started` or `call_started`.

Mapping:

```text
kind="pause" -> block_type="pause", event_type="pause_started"
kind="call_detected" -> block_type="call", event_type="call_started"
```

### Resume

When `_resume_session()` is called:

1. Finish current pause/call block.
2. Log `pause_ended` or `call_ended`.
3. If the previous state was task active, start a new `work` block for the same current task.

This is crucial. Work blocks should represent actual focused intervals. A 90-minute task interrupted by a 20-minute call should become:

```text
work 10:00-10:30
call 10:30-10:50
work 10:50-11:20
```

Not:

```text
work 10:00-11:20
```

### Breaks

When stretch/gym starts:

1. Start `time_blocks.block_type = "break"`.
2. Metadata should include break kind:

```json
{"break_kind": "stretch"}
```

or:

```json
{"break_kind": "gym"}
```

When break ends, finish the block.

### Shutdown / Give Up / Crash Cleanup

On `_finish_session()`, `_do_give_up()`, `_shutdown()`:

1. Close all open blocks for the session.
2. Mark `sessions_v2.status`.
3. Log final event.

At daemon startup:

1. Find stale active sessions from previous boots.
2. Mark them `crashed` or `abandoned`.
3. Close open blocks at last known event timestamp or current startup time with metadata:

```json
{"closed_by": "startup_cleanup"}
```

## Web Dashboard Changes

File:

```text
src/locked_in/web_frontend.py
```

Add API endpoints:

```text
GET /api/metrics?date=YYYY-MM-DD
GET /api/metrics/range?start=YYYY-MM-DD&end=YYYY-MM-DD
GET /api/time-blocks?date=YYYY-MM-DD
GET /api/events?date=YYYY-MM-DD
```

Add page sections:

### Today Metrics Card

Show:

- Focused work time
- Pause time
- Call time
- Break time
- Idle/unknown time
- Planned minutes
- Actual work minutes
- Estimate delta
- Completed task count
- Open task count
- Interruption count
- Longest focus block
- Average focus block
- First work start
- Last work end

### Task Metrics Table

Columns:

- Task
- Project
- Category
- Estimate
- Actual
- Delta
- Blocks
- Interruptions
- Status
- Notes

### Timeline

Render time blocks as a vertical timeline:

```text
08:39-09:12 work: Work with Spatio
09:12-09:18 call
09:18-09:44 work: Work with Spatio
09:44-09:49 break: stretch
```

### Weekly Metrics

Add a weekly summary:

- Total focus time by day
- Total focus time by project
- Estimate accuracy by day
- Interruptions by kind
- Average first start time
- Completion rate

## Metrics Computation

Add a new file:

```text
src/locked_in/metrics.py
```

Functions:

```python
def seconds_between(start_iso: str, end_iso: str | None, now: datetime | None = None) -> int
def summarize_day(store: SimpleTodoStore, target_date: date) -> dict
def summarize_range(store: SimpleTodoStore, start_date: date, end_date: date) -> dict
def summarize_task_blocks(blocks: list[TimeBlock], tasks: list[PlanTask]) -> list[dict]
```

Day metrics output shape:

```python
{
    "target_date": "2026-05-06",
    "focus_seconds": 12345,
    "pause_seconds": 500,
    "call_seconds": 1200,
    "break_seconds": 600,
    "idle_seconds": 0,
    "planned_seconds": 14400,
    "estimate_delta_seconds": -2055,
    "completion_rate": 0.66,
    "completed_tasks": 2,
    "total_tasks": 3,
    "interruption_count": 4,
    "longest_focus_block_seconds": 3600,
    "average_focus_block_seconds": 1800,
    "first_work_started_at": "...",
    "last_work_ended_at": "...",
    "by_project": [...],
    "by_category": [...],
    "by_task": [...],
    "timeline": [...]
}
```

Estimate delta:

```text
actual_focus_seconds_for_task - planned_duration_minutes * 60
```

Completion rate:

```text
completed_tasks / total_tasks
```

Interruption count:

```text
count of pause/call/idle blocks that happened during a task
```

## Idle Detection

This can be v2 after event/time-block foundation.

Possible implementation:

- Hyprland idle inhibitor or `hypridle` integration.
- Poll keyboard/mouse idle time if available.
- Use screen lock/suspend events from systemd journal later.

Initial schema should support idle blocks, but first implementation does not need automatic idle detection.

## App/Window/Site Tracking

This should be optional and separate because it can become noisy.

Possible future table:

```sql
CREATE TABLE IF NOT EXISTS app_focus_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_date TEXT NOT NULL,
    sampled_at TEXT NOT NULL,
    app_id TEXT,
    title TEXT,
    workspace TEXT,
    plan_task_id INTEGER,
    metadata_json TEXT
);
```

Do not implement in phase 1 unless explicitly requested.

## Migration Strategy

### Phase 1: Add Schema

1. Add schema versioning.
2. Add `sessions_v2`.
3. Add `tracking_events`.
4. Add `time_blocks`.
5. Add new columns to `plan_tasks` and `task_runs`.
6. Ensure app boots cleanly with existing DB.

### Phase 2: Write New Data Going Forward

1. Update simple UI/web task start to create `work` time block.
2. Update simple UI/web task finish to close that block.
3. Update daemon task start/end to write blocks.
4. Update pause/resume/call detection to write pause/call blocks.
5. Update break start/end to write break blocks.

### Phase 3: Backfill Old Data

Backfill from `task_runs`:

```text
task_runs with started_at and ended_at -> time_blocks(work)
task_runs start -> tracking_events(task_started)
task_runs finish -> tracking_events(task_finished)
```

Backfill from `warden.db.tasks`:

```text
completed tasks with actual_start and actual_end -> time_blocks(work)
```

Backfill from `warden.db.interruptions`:

```text
kind=pause -> time_blocks(pause)
kind=call_detected -> time_blocks(call)
```

Important:

- Mark backfilled blocks with `source = "backfill"`.
- Add metadata:

```json
{"backfilled_from": "warden.tasks", "source_id": 12}
```

### Phase 4: Metrics API

1. Implement `metrics.py`.
2. Add `/api/metrics`.
3. Add `/api/metrics/range`.
4. Add tests with temporary SQLite DB.

### Phase 5: Dashboard

1. Add today metrics card.
2. Add timeline.
3. Add task metrics table.
4. Add weekly summary.

## Testing Requirements

Add tests if test framework is introduced. If no framework, add temporary script-based checks.

Minimum scenarios:

### Schema Migration

- Existing old DB opens without errors.
- New tables exist.
- Existing plans/tasks remain readable.

### Basic Work Block

Steps:

1. Create plan with one task.
2. Start session.
3. Start task.
4. Finish task.

Expected:

- One `work` block.
- `duration_seconds > 0`.
- `task_started` and `task_finished` events exist.
- Metrics focus time equals block duration.

### Pause During Work

Steps:

1. Start task at 10:00.
2. Pause at 10:10.
3. Resume at 10:20.
4. Finish at 10:30.

Expected:

```text
work 10:00-10:10
pause 10:10-10:20
work 10:20-10:30
```

Metrics:

```text
focus = 20 min
pause = 10 min
```

### Call During Work

Same as pause, but block type should be `call`.

### Break

Stretch/gym should create `break` time block.

### Open Block Cleanup

If daemon restarts with open work block:

- close or mark previous session cleanly.
- do not leave duplicate active sessions.

### Estimate Accuracy

Task estimated 30 min, actual work blocks total 45 min:

```text
estimate_delta_seconds = 900
```

### Dictation Ignore

If mic app is `PipeWire ALSA [python3.14]`, auto-pause should not create call block.

If mic app is `Zoom`, auto-pause should create call block.

## Implementation Order

Use this exact order to minimize breakage:

1. Add schema and dataclasses in `simple_store.py`.
2. Add low-level store methods for events and time blocks.
3. Add `metrics.py` with pure functions.
4. Add script checks using temporary DB.
5. Wire simple web task start/finish to time blocks.
6. Wire daemon task start/finish to time blocks.
7. Wire pause/resume/call to time blocks.
8. Add API endpoints.
9. Add dashboard cards/timeline.
10. Add backfill command.
11. Run compile checks and manual daemon test.

## Backfill Command

Add CLI command:

```text
locked-in backfill-metrics
```

Behavior:

- Backfill from `simple_todos.db.task_runs`.
- Backfill from `warden.db.tasks`.
- Backfill from `warden.db.interruptions`.
- Idempotent: do not duplicate blocks/events if run multiple times.

To support idempotency, add metadata or a unique source key.

Option A: add columns:

```sql
source_table TEXT
source_id TEXT
```

to `time_blocks` and `tracking_events`.

Recommended: add these columns now:

```sql
ALTER TABLE time_blocks ADD COLUMN source_table TEXT;
ALTER TABLE time_blocks ADD COLUMN source_id TEXT;
ALTER TABLE tracking_events ADD COLUMN source_table TEXT;
ALTER TABLE tracking_events ADD COLUMN source_id TEXT;
```

Then create indexes:

```sql
CREATE UNIQUE INDEX IF NOT EXISTS idx_time_blocks_source_identity
ON time_blocks(source_table, source_id)
WHERE source_table IS NOT NULL AND source_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_tracking_events_source_identity
ON tracking_events(source_table, source_id, event_type)
WHERE source_table IS NOT NULL AND source_id IS NOT NULL;
```

## Data Quality Rules

- No open block should remain open after session finish.
- Only one active `work` block per session.
- A `work` block should have a task id unless it is explicitly `unknown`.
- All block durations must be recomputed from timestamps when closing.
- Never trust user-edited duration alone if timestamps exist.
- Avoid deleting historical tracking data on plan edit. Mark tasks changed instead.

## Dashboard Metrics Definitions

### Focus Time

Sum of `duration_seconds` for blocks where:

```text
block_type = "work"
```

### Pause Time

Sum where:

```text
block_type = "pause"
```

### Call Time

Sum where:

```text
block_type = "call"
```

### Break Time

Sum where:

```text
block_type = "break"
```

### Planned Time

Sum of `plan_tasks.duration_minutes * 60`.

### Actual Time Per Task

Sum work blocks grouped by `plan_task_id`.

### Estimate Delta Per Task

```text
actual_task_seconds - estimated_task_seconds
```

### Start Delay

```text
first_work_block.started_at - schedule_entry.scheduled_start
```

Only calculate if both exist.

### Interruption Count Per Task

Count pause/call/idle blocks that occur between task work block ranges.

Simple first version:

- Count pause/call blocks whose `started_at` is between first task work start and last task work end.

Better later:

- Track active task id on pause/call blocks.

## Important Edge Cases

### Task Active Across Midnight

Use `target_date` from the session/plan, not necessarily `started_at.date()`.

### Session Reset After 6AM

Current behavior resets stale pre-6AM session starts when opened after 6AM.

Keep this behavior. New `sessions_v2` should use the reset session time.

### Manual Pause Before Call

If user manually paused, mic auto-pause should not resume the session.

Current daemon has `_auto_paused_by_mic` guard. Preserve that logic.

### Dictation Hotkey

`Super+Alt+V` starts:

```text
~/.local/bin/voice-toggle.sh
```

which runs:

```text
voice_continuous.py
```

Current config ignores:

```toml
ignored_apps = ["PipeWire ALSA [python", "python3.14", "voice_continuous.py"]
```

This must remain ignored for call detection metrics.

### Duplicate Sessions

Current `warden.db` can contain multiple active sessions. New `sessions_v2` must prevent this.

Rule:

- On startup, if another active session for the same target date exists, mark it `crashed` before creating a new active session.

## Files To Modify

Primary:

```text
src/locked_in/simple_store.py
src/locked_in/daemon.py
src/locked_in/web_frontend.py
src/locked_in/main.py
```

New:

```text
src/locked_in/metrics.py
src/locked_in/backfill_metrics.py
```

Optional:

```text
src/locked_in/models.py
docs/locked-in-explainer.html
```

## Acceptance Criteria

The implementation is acceptable when:

1. Starting and finishing a task creates a closed `work` block.
2. Pausing during a task splits work into two blocks and creates a pause block.
3. Mic call auto-pause creates a `call` block for real call apps.
4. Dictation mic use does not create a call block.
5. `/api/metrics?date=YYYY-MM-DD` returns correct totals.
6. Dashboard shows focus/pause/call/break/planned/actual/estimate-delta metrics.
7. Open blocks are closed on session end/give-up/shutdown.
8. Restart does not create duplicate active sessions without closing old ones.
9. Backfill can be run twice without duplicating data.
10. Existing plan editing and task execution still work.

## Non-Goals For First Pass

Do not implement these in phase 1:

- App/window tracking.
- Browser URL tracking.
- Automatic idle detection.
- Cloud sync.
- Notion metrics sync.
- Charts requiring frontend libraries.
- Full export UI.

Schema should make these possible later, but first pass should focus on trustworthy work/pause/call/break time.

## Manual Verification Commands

Compile:

```bash
rtk .venv/bin/python -m compileall -q src/locked_in
```

Inspect DB:

```bash
rtk sqlite3 ~/.local/share/locked-in/simple_todos.db '.schema'
```

Check status:

```bash
rtk .venv/bin/locked-in status
```

Restart daemon:

```bash
rtk systemctl --user restart locked-in.service
```

Restart web:

```bash
rtk systemctl --user restart locked-in-web.service
```

Open metrics JSON:

```bash
rtk curl -sS 'http://127.0.0.1:8765/api/metrics'
```

Open dashboard:

```text
http://127.0.0.1:8765/
```

