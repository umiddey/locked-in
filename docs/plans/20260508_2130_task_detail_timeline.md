# Task Detail Timeline Page

**Created:** 2026-05-08
**Status:** COMPLETE
**Size:** NON-TINY (new route, new store method, new HTML page, CSS, main page modifications)

---

## Context / Thought Process

User wanted to click on a task in the schedule and see a full timeline breakdown:
- How much time was spent working vs paused
- Each individual work segment and pause gap with timestamps
- Historical data queryable months/years later

After reading the codebase, discovered the data layer was ALREADY complete:
- `time_blocks` table stores every work/pause/call/idle block with start/end timestamps, linked via `plan_task_id`
- `tracking_events` logs every state transition
- `task_runtime` tracks accumulated pause time

So the only gap was a **UI to drill into it** — no schema changes needed.

---

## Phase 1 — Store Method ✅

Added `SimpleTodoStore.get_task_detail(plan_task_id)` that:
- Fetches the task from `plan_tasks`
- Queries all `time_blocks` linked to that task
- Also finds unlinked pause/call/idle blocks that fall within the task's time window
- Sorts everything chronologically
- Computes total work/pause/wall seconds
- Returns events and runtimes for the events log

**File:** `src/locked_in/simple_store.py` (added ~100 lines)

## Phase 2 — API + HTML Route ✅

Added to `web_frontend.py`:
- GET `/task/<id>` → full HTML detail page
- GET `/api/task/<id>` → JSON payload
- Route matching via `re.match(r"^/task/(\d+)$", ...)`

**File:** `src/locked_in/web_frontend.py`

## Phase 3 — Task Detail Page ✅

`_render_task_detail_page()` renders:
- Hero section: task name, date, status, estimate
- Metrics bar: work time, pause time, wall time, delta vs estimate
- Timeline panel: every work/pause block with timestamps, duration bars, type coloring
- Events panel: chronological event log with metadata

Design matches existing dashboard dark theme (same CSS variables, JetBrains Mono, Outfit fonts).

## Phase 4 — Clickable Links on Dashboard ✅

Made task names clickable in two places:
- Schedule rows: `sc__name` now wraps in `<a href="/task/{id}">` link
- Per-task metrics section: same treatment

Added `.sc__link` CSS: dashed underline, amber hover.

---

## Verification

```bash
# API returns full JSON
curl -s http://localhost:8765/api/task/20 | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['task_name'], len(d['timeline']), 'blocks')"
# AI Accountant work 68 blocks

# HTML page renders
curl -s http://localhost:8765/task/20 | grep -c 'tl--'
# 77 (timeline CSS classes)

# Main page has clickable links
curl -s http://localhost:8765/ | grep -c '/task/'
# 6
```

## Files Modified

- `src/locked_in/simple_store.py`: +`get_task_detail()` method
- `src/locked_in/web_frontend.py`: +task detail route, +detail page renderer, +404 helper, clickable schedule names, clickable metrics names
