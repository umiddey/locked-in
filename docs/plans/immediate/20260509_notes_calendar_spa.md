# Locked-In: Retroactive Notes + Calendar History + SPA Fragment Rendering
**Implementation Status: Phases 2+3 DONE, 4+5 DONE**

## Context
Three pain points with the current web dashboard:
1. **No retroactive notes** — notes can only be added when finishing a running task (the finish form has a notes textarea). Once a task is done, there's no way to go back and add notes.
2. **Historical view is useless** — the "History" button shows only one day behind (uses `get_latest_plan_date(before=today)`). User wants a calendar grid to click any past date.
3. **Full page reloads on every action** — every button press causes a full page reload. User wants app-like feel with no reloads.

## Approach: htmx-style fragment rendering
Instead of a full SPA rewrite or adding a JS framework, we use **server-side HTML fragments**:
- Task actions (start/pause/resume/finish/extend/notes) return just the changed HTML fragment (~50 lines) instead of the full page (~1800 lines)
- Server already renders HTML — no duplication
- Browser swaps fragments via small JS (~30 lines fetch + innerHTML)
- Navigation between pages (dashboard, history, task detail, settings) stays as full page loads — fine for a local dashboard

**Why this over full SPA**: Zero duplicated rendering logic. The server already builds all the HTML. Fragment responses are ~97% smaller than full page (0.5-2KB vs 8-12KB). CPU savings on both server (less string concat) and browser (no full re-layout).

## Architecture

### New response pattern for task actions
Current flow: `POST /run/pause` → execute → `303 redirect to /` → full HTML render
New flow: `POST /run/pause` → execute → `200 OK` with HTML fragment of hero+actions+schedule

The JS intercepts form submissions, sends via `fetch()`, and swaps the returned HTML into the right container div.

---

## Phase 1: Store methods for retroactive notes + date queries
**File: `src/locked_in/simple_store.py`**

### 1a. `update_task_run_notes(plan_task_id: int, notes: str) -> bool`
```python
def update_task_run_notes(self, plan_task_id: int, notes: str) -> bool:
    """Update notes on the most recent task_run for a plan_task.

    Args:
        plan_task_id (int): the plan_tasks.id
        notes (str): new notes text

    Returns:
        bool: True if a run was updated
    """
    with self._lock:
        row = self.conn.execute(
            "SELECT id FROM task_runs WHERE plan_task_id = ? ORDER BY id DESC LIMIT 1",
            (plan_task_id,),
        ).fetchone()
        if not row:
            return False
        self.conn.execute(
            "UPDATE task_runs SET notes = ? WHERE id = ?",
            (notes.strip() or None, row["id"]),
        )
        self.conn.commit()
        return True
```

### 1b. `get_plan_dates_range(start_date: date, end_date: date) -> list[str]`
```python
def get_plan_dates_range(self, start_date: date, end_date: date) -> list[str]:
    """Return all target_date strings that have plans in the given range.

    Args:
        start_date (date): inclusive start
        end_date (date): inclusive end

    Returns:
        list[str]: sorted list of date strings
    """
    with self._lock:
        rows = self.conn.execute(
            """SELECT DISTINCT p.target_date FROM plans p
            WHERE p.target_date >= ? AND p.target_date <= ?
            AND EXISTS (SELECT 1 FROM plan_tasks t WHERE t.target_date = p.target_date)
            ORDER BY p.target_date""",
            (start_date.isoformat(), end_date.isoformat()),
        ).fetchall()
        return [r["target_date"] for r in rows]
```

### 1c. `get_day_summary(target_date: date) -> dict`
For the calendar, we need task counts per date without loading full plans:
```python
def get_day_summary(self, target_date: date) -> dict:
    """Lightweight summary for a date: task count, completed count, total focus seconds.

    Args:
        target_date (date): the date to summarize

    Returns:
        dict: {task_count, completed_count, focus_seconds}
    """
    with self._lock:
        target = target_date.isoformat()
        task_row = self.conn.execute(
            "SELECT COUNT(*) as total, SUM(CASE WHEN completed_at IS NOT NULL THEN 1 ELSE 0 END) as done FROM plan_tasks WHERE target_date = ?",
            (target,),
        ).fetchone()
        focus_row = self.conn.execute(
            "SELECT COALESCE(SUM(duration_seconds), 0) as total FROM time_blocks WHERE target_date = ? AND block_type = 'work' AND ended_at IS NOT NULL",
            (target,),
        ).fetchone()
        return {
            "task_count": task_row["total"] or 0,
            "completed_count": task_row["done"] or 0,
            "focus_seconds": focus_row["total"] or 0,
        }
```

---

## Phase 2: Fragment rendering helpers
**File: `src/locked_in/web_frontend.py`**

### 2a. Add wrapper div IDs to existing render output
The main `_render_page` output needs IDs on key sections so JS can target them for swapping:

- `<div id="hero-section">` — wraps the hero block
- `<div id="actions-section">` — wraps the actions buttons
- `<div id="schedule-section">` — wraps the schedule panel
- `<div id="metrics-section">` — wraps the metrics bar
- `<div id="task-metrics-section">` — wraps per-task metrics
- `<div id="banner-section">` — wraps the banner messages

These are pure HTML additions, no logic changes. Just wrapping existing output with ID'd divs.

### 2b. Fragment render methods
Extract small renderers that return just the HTML fragment:

```python
def _render_hero_fragment(self, target_date: date) -> str:
    """Render just the hero section as an HTML fragment."""
    # Same logic as the hero section in _render_page, but returns only that div

def _render_schedule_fragment(self, target_date: date) -> str:
    """Render just the schedule panel as an HTML fragment."""

def _render_actions_fragment(self, target_date: date) -> str:
    """Render just the action buttons as an HTML fragment."""

def _render_metrics_fragment(self, target_date: date) -> str:
    """Render just the metrics bar + per-task metrics as an HTML fragment."""

def _render_dashboard_fragments(self, target_date: date) -> dict[str, str]:
    """Return all fragments as a dict for the fragment response."""
    return {
        "hero": self._render_hero_fragment(target_date),
        "actions": self._render_actions_fragment(target_date),
        "schedule": self._render_schedule_fragment(target_date),
        "metrics": self._render_metrics_fragment(target_date),
    }
```

**Key insight**: Most of the fragment renderers can reuse the same logic that `_render_page` currently uses inline. We extract it, then `_render_page` calls the same fragment renderers to compose the full page. This avoids duplication.

### 2c. Fragment response endpoint
New GET endpoint `/fragments/dashboard?date=YYYY-MM-DD` that returns a JSON body of fragment HTML:
```json
{
  "hero": "<div id='hero-section'>...</div>",
  "actions": "<div id='actions-section'>...</div>",
  "schedule": "<div id='schedule-section'>...</div>",
  "metrics": "<div id='metrics-section'>...</div>"
}
```

### 2d. Modify POST handlers to return fragments instead of redirects
For task actions, change the response pattern:

Current:
```python
# In do_POST for /run/pause
result = frontend._pause_current_from_form(form)
self._redirect("/", ...)
```

New:
```python
# In do_POST for /run/pause
result = frontend._pause_current_from_form(form)
# Check Accept header or form field for fragment mode
if form.get("fragment") == "1":
    target_date = frontend._target_date_from_form(form)
    fragments = frontend._render_dashboard_fragments(target_date)
    if result.get("error"):
        fragments["banner"] = f'<div id="banner-section"><div class="ban ban--err">{html.escape(result["error"])}</div></div>'
    self._send_json(fragments, include_body=True)
else:
    self._redirect("/", ...)  # fallback for no-JS
```

This applies to all POST routes: `/run/pause`, `/run/resume`, `/run/extend`, `/run/finish-current`, `/run/start-current`.

---

## Phase 3: Client-side JS for fragment swapping
**File: `src/locked_in/web_frontend.py`** (inline in the `<script>` tag at bottom of `_render_page`)

~40 lines of vanilla JS:

```javascript
// Intercept all forms with [data-fragment] attribute
document.addEventListener('submit', async (e) => {
    const form = e.target;
    if (!form.dataset.fragment) return;
    e.preventDefault();

    const body = new FormData(form);
    body.set('fragment', '1');

    const resp = await fetch(form.action, { method: 'POST', body });
    const fragments = await resp.json();

    for (const [id, html] of Object.entries(fragments)) {
        const el = document.getElementById(id + '-section');
        if (el) el.outerHTML = html;
    }
});
```

All action forms get `data-fragment` attribute added in the HTML rendering. This is the ONLY JS change — no framework, no build step.

---

## Phase 4: Retroactive notes on task detail page
**File: `src/locked_in/web_frontend.py`**

### 4a. POST `/task/notes` handler in `do_POST`
```python
if parsed.path == "/task/notes":
    target_date = self._target_date_from_form(form)
    task_id = int(form.get("task_id", "0"))
    notes = form.get("notes", "")
    if form.get("fragment") == "1":
        frontend.store.update_task_run_notes(task_id, notes)
        # Return just the notes fragment
        detail = frontend.store.get_task_detail(task_id)
        self._send_html(frontend._render_notes_fragment(detail), include_body=True)
    else:
        frontend.store.update_task_run_notes(task_id, notes)
        self._redirect(f"/task/{task_id}", target_date, "Notes saved")
    return
```

### 4b. Notes panel in `_render_task_detail_page`
After the timeline panel, add a notes section:

```python
# Get current notes from most recent run
current_notes = ""
if detail["runs"]:
    current_notes = detail["runs"][-1].get("notes") or ""

notes_html = f"""
<div class="panel" id="notes-section">
    <div class="panel__head">
        <span class="panel__title">Notes</span>
    </div>
    <div style="padding:14px 16px">
        <form method="post" action="/task/notes" data-fragment>
            <input type="hidden" name="task_id" value="{task_id}" />
            <input type="hidden" name="date" value="{target_date}" />
            <textarea name="notes" class="act-notes" placeholder="Add notes about this task..." rows="4">{html.escape(current_notes)}</textarea>
            <div style="margin-top:8px">
                <button class="btn btn--primary" type="submit">Save Notes</button>
            </div>
        </form>
    </div>
</div>
"""
```

### 4c. Notes fragment renderer
```python
def _render_notes_fragment(self, detail: dict) -> str:
    """Render just the notes panel fragment for swap."""
    current_notes = ""
    if detail.get("runs"):
        current_notes = detail["runs"][-1].get("notes") or ""
    task_id = detail["task_id"]
    return f"""<div id="notes-section" class="panel">
        <div class="panel__head"><span class="panel__title">Notes</span><span class="panel__badge">saved</span></div>
        <div style="padding:14px 16px">
            <form method="post" action="/task/notes" data-fragment>
                <input type="hidden" name="task_id" value="{task_id}" />
                <input type="hidden" name="date" value="{detail['target_date']}" />
                <textarea name="notes" class="act-notes" rows="4">{html.escape(current_notes)}</textarea>
                <div style="margin-top:8px"><button class="btn btn--primary" type="submit">Save Notes</button></div>
            </form>
        </div>
    </div>"""
```

---

## Phase 5: Calendar historical view
**File: `src/locked_in/web_frontend.py`**

### 5a. GET `/history` route in `_dispatch`
```python
if parsed.path == "/history":
    year = int(query.get("year", [str(date.today().year)])[0])
    month = int(query.get("month", [str(date.today().month)])[0])
    self._send_html(frontend._render_history_page(year, month), include_body=include_body)
    return
```

### 5b. `_render_history_page(self, year: int, month: int) -> str`
Calendar page:

1. Compute first day of month, last day, weekday of first day
2. Query `store.get_plan_dates_range(first_of_month, last_of_month)` → set of dates with plans
3. Query `store.get_day_summary(date)` for each plan date to get task counts
4. Render 7-column grid:
   - Header row: Mon Tue Wed Thu Fri Sat Sun
   - Week rows: each cell has date number
   - Cells with plans: green dot + task count badge (e.g., "3 tasks, 2 done")
   - Today: highlighted border
   - Empty cells for days outside month
5. Each plan-date cell is a link: `<a href="/?view=historical&date=YYYY-MM-DD">`
6. Month navigation: `← May 2026 →` links to `/history?year=X&month=Y`

### 5c. Style
Same dark theme CSS variables. Calendar cells: dark background, green dot for plan dates, amber highlight for today, hover state shows task summary. Consistent with existing panel/card styling.

### 5d. Update nav button
Change the "History" button in `_render_page`:
```python
# Old
'<form method="get" action="/"><input type="hidden" name="view" value="historical" /><button class="nav__btn" type="submit">History</button></form>'
# New
'<a href="/history" class="nav__btn">History</a>'
```

---

## Phase 6: Refactor `_render_page` to use fragments
**File: `src/locked_in/web_frontend.py`**

This is the key deduplication step. Currently `_render_page` is ~500 lines of inline HTML building. Refactor so:

1. `_render_page` calls `_render_hero_fragment`, `_render_actions_fragment`, `_render_schedule_fragment`, `_render_metrics_fragment` and wraps them in the full page shell (nav, CSS, scripts)
2. Fragment endpoints call the same functions but return just the fragment
3. Zero duplication — both full page and fragment paths use the same renderers

This is a pure refactor — no behavior change for full page loads.

---

## Files Modified
1. **`src/locked_in/simple_store.py`** — add `update_task_run_notes`, `get_plan_dates_range`, `get_day_summary`
2. **`src/locked_in/web_frontend.py`** — fragment rendering, `/task/notes` POST, `/history` GET, JS interceptor, calendar page, refactor `_render_page`
3. **`tests/test_web_frontend.py`** — add tests for notes update, calendar page, fragment responses

## Implementation Order
1. Phase 1 (store methods) — no dependencies, pure data layer
2. Phase 2b (fragment renderers) + Phase 6 (refactor _render_page) — extract first, then both full-page and fragment paths work
3. Phase 3 (client JS) — minimal, ~40 lines
4. Phase 2d (modify POST handlers) — now fragments work end-to-end
5. Phase 4 (retroactive notes) — uses the fragment pattern
6. Phase 5 (calendar history) — standalone page, uses store methods from Phase 1

## Verification
1. `python -m pytest tests/test_web_frontend.py -v` — all existing tests pass + new tests
2. `locked-in web` — start server
3. **Fragment SPA**: On today's dashboard, click Pause → hero updates without page reload. Click Resume → updates again. Click Finish with notes → task completes, schedule updates, metrics update, all without reload.
4. **Retroactive notes**: Navigate to `/task/11` (a completed past task). See notes panel. Type notes, click Save → notes saved without reload. Refresh page → notes persist.
5. **Calendar**: Navigate to `/history`. See May 2026 calendar. Green dots on dates 4-9. Click on 2026-05-06 → loads historical dashboard for that date with 3 tasks. Navigate to April 2026 → no green dots (no plans). Navigate back to May.
6. **DB check**: `sqlite3 ~/.local/share/locked-in/simple_todos.db "SELECT id, notes FROM task_runs WHERE notes IS NOT NULL LIMIT 5;"`

## Thought Process
User started by asking to understand the codebase, then identified three pain points: no retroactive notes, useless historical view (one day), and wanted app-like feel. We discussed SPA approaches — full SPA rewrite was overkill for a local single-user dashboard. htmx-style fragment rendering is the sweet spot: server already renders HTML, so we just return fragments instead of full pages. The existing `/api/*` JSON endpoints confirmed the architecture was ready for this. The calendar was straightforward — just needed a new store query method and a page renderer. The refactoring of `_render_page` into composable fragments is the key architectural change that makes everything else work without duplication.
