# Locked-In — Architecture

## High-Level Overview

Locked-In is a **Linux desktop focus enforcer** with two runtime modes:

1. **Web dashboard** (`locked-in web`) — a standalone HTTP server at `localhost:8765` with a Jinja2-rendered UI for task planning, session control, and metrics. Works on any OS with a browser.
2. **Legacy daemon** (`locked-in run-legacy`) — the full enforcement engine: PyQt6 blocker windows, auto-pause on idle/mic, stretch lockouts, hard shutdown. Built for Hyprland/Wayland.

Both modes share the same data layer (`SimpleTodoStore` → SQLite). The web dashboard can also send commands to a running daemon via a Unix domain socket.

```
┌─────────────────────────────────────────────────────────┐
│                       CLI (main.py)                      │
│  run | web | run-legacy | pause | resume | give-up | …  │
└──────────┬──────────────────────────┬────────────────────┘
           │                          │
           ▼                          ▼
   ┌───────────────┐         ┌──────────────┐
   │  Web Frontend │◄───────►│   Daemon     │
   │  (HTTP :8765) │  IPC    │  (legacy)    │
   └───────┬───────┘  Unix   └──────┬───────┘
           │          socket        │
           ▼                        ▼
   ┌─────────────────────────────────────────┐
   │          SimpleTodoStore (SQLite)        │
   │  plans, plan_tasks, task_runs,          │
   │  sessions_v2, time_blocks,              │
   │  tracking_events                        │
   └─────────────────────────────────────────┘
```

---

## Entry Point — `main.py`

Parses CLI args and dispatches:

| Command | What it does |
|---------|-------------|
| `run` | Launches `SimpleTodoApp` (lightweight planner + scheduler window via PyQt6) |
| `open` | Same as `run` but forces opening even if a plan exists |
| `test-now` | Debug command — opens planner or dashboard directly |
| `web` | Starts the HTTP web frontend |
| `run-legacy` | Starts the full daemon with enforcement |
| `pause/resume/give-up/status` | Sends command to daemon via Unix socket |
| `fetch-tasks` | Prints today's plan to stdout |
| `show-schedule` | Prints projected schedule with ETAs |
| `backfill-metrics` | Retroactively creates time_blocks from old data |
| `repair-backfill` | Fixes backfilled task mappings |
| `auto-open-on/off` | Toggles Hyprland autostart for the dashboard |

---

## Web Frontend — `web_frontend.py` (47KB)

A `ThreadingHTTPServer` with Jinja2 templates. All routes are dispatched in a single `Handler` class.

### Routes

| Path | Method | Purpose |
|------|--------|---------|
| `/` | GET | Dashboard — today's plan, active task, timer |
| `/plan` | GET/POST | Plan page — add/edit/reorder tasks |
| `/start` | POST | Start a task |
| `/pause` | POST | Pause current task |
| `/resume` | POST | Resume current task |
| `/finish` | POST | Finish current task |
| `/extend` | POST | Extend current task time |
| `/settings` | GET/POST | View/edit config.toml settings |
| `/calibrate` | POST | Run idle detector calibration |
| `/metrics` | GET | Daily/weekly metrics dashboard |
| `/api/status` | GET | JSON status of current session |
| `/api/plan` | GET | JSON plan data |
| `/api/metrics` | GET | JSON metrics |

### Templates

Located in `src/locked_in/templates/`, rendered with Jinja2:

- `base.html` — shared layout (nav, styles)
- `index.html` — main dashboard
- `settings.html` — config editor
- `components/calibrate.html` — idle calibration UI fragment

---

## Daemon — `daemon.py` (32KB)

The core enforcement engine. Only runs in `run-legacy` mode.

### Lifecycle

1. **Bootstrap** — loads today's plan from `SimpleTodoStore`, builds a schedule via `scheduler.py`, creates a session in `Database` (legacy DB)
2. **Main loop** — polls an event queue for `TICK`, `USER_ACTIVITY_HARD`, `MIC_ACTIVE`, `MIC_SILENT` events
3. **Tick logic** (every ~1s):
   - Checks idle auto-pause
   - Checks ETA warnings (5 min before task ends)
   - Checks hard shutdown deadline
   - Advances schedule (activates next task/break)
4. **Shutdown** — on `GIVEN_UP`, `FINISHED`, or hard shutdown → closes all time blocks, ends session, stops loop

### State Machine

```
IDLE → AWAITING_TASK_START → TASK_ACTIVE
  │         │                    │
  │         ├──── PAUSED ◄──────┤
  │         │                    │
  │         ├──── GIVEN_UP       ├──── GIVEN_UP
  │         │                    │
  └──── FINISHED                └──── FINISHED
```

**PAUSED** is special — it remembers the previous state and resumes back to it.

### Schedule Building — `scheduler.py`

Pure function `build_schedule()`:
1. Starts from session start time + grace period
2. Places tasks sequentially with estimated durations
3. Truncates tasks that would cross the hard shutdown deadline
4. Appends shutdown warning + shutdown marker at the deadline
5. Sorts all items by scheduled start time

Stretch lockouts are NOT inserted into the schedule — they're handled independently by `StretchLockout` (see below).

### Give-Up Mechanism

3 attempts required within a cooldown window (`give_up_cooldown_seconds`, default 30s). On the 3rd attempt, the session is abandoned.

### Hard Shutdown

When `hard_shutdown_enabled=true` and the clock hits `hard_shutdown_time` (default 01:00):
1. A warning notification fires `shutdown_warning_minutes` (default 10) before
2. At deadline, the daemon calls `systemctl poweroff`

---

## Services — `services.py`

Three decoupled services run as daemon threads, pushing events to a shared `Queue`:

| Service | Poll Rate | Event | Purpose |
|---------|-----------|-------|---------|
| `TickService` | 1s | `TICK` | Drives the main tick loop |
| `IdleService` | 0.5s | `USER_ACTIVITY_SOFT`, `USER_ACTIVITY_HARD` | Forwards idle detector state changes |
| `MicService` | configurable (default 5s) | `MIC_ACTIVE`, `MIC_SILENT` | Forwards mic activity snapshots |

---

## Idle Detection — `idle_detector.py`

Since Wayland/Hyprland exclusively grabs `/dev/input/event*`, idle detection works by polling **`/proc/interrupts`** for IRQ counter changes.

### Strategy

- Monitors IRQs for `i8042` (keyboard) and `xhci_hcd` (USB)
- Excludes IRQ 12 (touchpad — has phantom noise on Synaptics)
- Two sensitivity levels:
  - **Soft** — any input above threshold → resets "last activity" timer
  - **Hard** — intentional input (higher threshold) → triggers resume from idle-pause
- Thresholds are configurable via `config.toml` and the calibration UI

### Calibration (`/calibrate` endpoint)

1. Records IRQ deltas during an "idle" phase → establishes noise floor
2. Records IRQ deltas during an "active" phase → establishes signal level
3. Computes optimal thresholds between noise and signal

---

## Mic Activity Detection — `activity_detector.py`

Detects microphone usage via `pactl list source-outputs` (PipeWire/PulseAudio).

- Parses `application.name`, `application.process.binary`, and `media.name` from PulseAudio source outputs
- Filters against `call_apps` whitelist (if set) or detects any mic use
- Excludes `ignored_apps` (e.g., background noise detection tools)
- Returns a `MicActivitySnapshot` with `active: bool` and matched app names

### Auto-Pause Behavior

- Mic active for `mic_active_seconds` (default 15s) → auto-pause
- Mic silent for `resume_after_silence_seconds` (default 180s) → auto-resume

---

## Stretch Lockout — `stretch_lockout.py`

**Opt-in** (`[stretch_lockout] enabled = true` in config). Tracks cumulative work time across task boundaries. When the counter hits `interval_minutes` (default 60):

1. Locks the screen via `hyprlock`
2. Waits `duration_minutes` (default 5)
3. Unlocks via `loginctl unlock-session`
4. Resets the counter

The counter pauses when the session is paused and only resets after a full break completes or the session ends.

---

## ETA Warning — `eta_warning.py`

A PyQt6 popup shown 5 minutes before a task's ETA. Offers two choices:
- **Finish Task** — marks the task complete
- **Extend +Xm** — adds more time (default = task's original estimate or `default_extend_minutes`)

Shows an overtime counter while the popup is displayed.

---

## Data Layer

### `SimpleTodoStore` (`simple_store.py`, 70KB)

The primary data store. SQLite at `~/.local/share/locked-in/simple_todos.db`.

#### Tables

| Table | Purpose |
|-------|---------|
| `plans` | One row per date — tracks that a plan exists |
| `plan_tasks` | Tasks within a plan: name, duration, position, completion status |
| `daily_sessions` | Session start time per date |
| `task_runs` | Individual task execution records: start, end, duration, outcome, notes |
| `sessions_v2` | Enhanced session tracking with status, source, timestamps |
| `tracking_events` | Event log: task_started, task_finished, pause_started, etc. |
| `time_blocks` | Time intervals: work, pause, call, break, idle blocks with metadata |
| `schema_meta` | Schema version tracking |

#### Key Operations

- `save_plan()` / `get_plan()` — CRUD for daily plans
- `start_task_runtime()` / `pause_task_runtime()` / `resume_task_runtime()` / `finish_task_runtime()` — task lifecycle
- `extend_task_runtime()` — add time to a running task
- `start_time_block()` / `finish_time_block()` — track work/pause/break intervals
- `log_event()` — append to tracking_events
- `project_runtime_schedule()` — compute projected schedule with ETAs

### `Database` (`db.py`, legacy)

A second SQLite store at `~/.local/share/locked-in/warden.db`, used by the legacy daemon for sessions, tasks (with Notion IDs), and interruptions. Coexists with `SimpleTodoStore` — the daemon writes to both.

#### Tables

| Table | Purpose |
|-------|---------|
| `sessions` | Daemon sessions with shutdown deadlines |
| `tasks` | Scheduled tasks with Notion integration |
| `interruptions` | Pause/call interruption records |
| `control_events` | Audit log of all control commands |

---

## Control Protocol — `control_server.py` / `control_client.py`

Unix domain socket IPC at `~/.local/state/locked-in/control.sock`.

**Client** sends JSON: `{"command": "pause"}`
**Server** responds JSON: `{"status": "paused"}`

Supported commands: `pause`, `resume`, `give_up`, `status`, `start_task`, `pause_task`, `resume_task`, `finish_task`, `extend_task`

---

## Metrics — `metrics.py`

Computes summaries from time blocks:

### `summarize_day()`
- Focus time, pause time, call time, break time, idle time
- Task completion rate
- Estimate vs actual delta
- Longest and average focus blocks
- Interruption count
- Breakdowns by project, category, and individual task
- Timeline of all blocks

### `summarize_range()`
- Aggregates `summarize_day()` across a date range
- Focus by day, focus by project, estimate deltas

### Backfill — `backfill_metrics.py`

Retroactively creates `time_blocks` from old `task_runs` and `tracking_events` data for days before the time_blocks system existed.

---

## Planning — `planning.py`

Parses free-text task lists:

```
Task name - 30        # name + duration in minutes
Task name | 45        # alternative separator
Task name             # defaults to 30 minutes
```

---

## Notion Integration — `notion_client.py`

Fetches tasks from a Notion database and normalizes them into `NormalizedTask` objects.

- Configured via `config.toml` `[notion]` section (token, database ID, property names)
- Supports filtering by status, select, and multi-select properties
- Maps Notion page properties to task fields (title, date, estimate)

---

## Notifications — `notifications.py`

Thin wrapper around `notify-send` (libnotify). Used for all user-facing alerts: pause/resume, shutdown warnings, ETA warnings.

---

## Configuration — `config.py`

Layered config from multiple sources (priority: env vars > .env > config.toml > defaults):

| Section | Key fields | Purpose |
|---------|-----------|---------|
| `schedule` | shutdown time, task defaults | Deadline and scheduling |
| `stretch_lockout` | enabled, interval, duration | Opt-in screen lock for breaks |
| `warden` | grace period, give-up cooldown, extend minutes | Enforcement behavior |
| `control` | socket path | IPC socket location |
| `ui` | theme, blocker window toggle | UI preferences |
| `web` | port, auto-open | Web server settings |
| `auto_pause` | idle/mic thresholds, call apps | Auto-pause sensitivity |

Config is also editable from the web dashboard at `/settings`.

---

## Models — `models.py`

Core data structures used across the system:

- `Session` / `SessionStatus` — daemon session lifecycle
- `Task` / `TaskStatus` — scheduled task with actuals
- `NormalizedTask` — plan-agnostic task representation
- `ScheduleItem` / `ScheduleKind` — scheduled time slots (task, stretch, shutdown)
- `Interruption` — pause/call records
- `State` — state machine states

---

## File Locations

| Path | Purpose |
|------|---------|
| `~/.local/share/locked-in/simple_todos.db` | Primary data store |
| `~/.local/share/locked-in/warden.db` | Legacy daemon store |
| `~/.local/state/locked-in/control.sock` | IPC socket |
| `~/.config/locked-in/config.toml` | Configuration |
| `~/.config/hypr/autostart.conf` | Hyprland auto-open toggle |
