# 20260508_2130_task_detail_timeline
**Task**: Task detail timeline page — click a task to see work/pause breakdown
**Status**: COMPLETE

## WHAT
- Added `get_task_detail()` to SimpleTodoStore ✓
- Added `/task/<id>` HTML page + `/api/task/<id>` JSON endpoint ✓
- Made schedule + per-task metrics names clickable to detail page ✓
- Added `.sc__link` CSS + `_render_404()` helper ✓

## HOW
1. Added store method that queries `time_blocks` + `tracking_events` for a given `plan_task_id`, plus unlinked pause blocks within the task's time window
2. Added regex route matching in `_dispatch()` for `/task/\d+` and `/api/task/\d+`
3. Built full detail page with timeline visualization (work=green bars, pause=amber, call=purple, idle=gray) matching existing dark theme
4. Wrapped task names in schedule rows + metrics rows with `<a>` links

## WHY
User wanted drill-down into individual tasks to see exactly when they worked vs took breaks. Data was already being tracked in `time_blocks` table — only the UI/route layer was missing. No schema changes needed.

## FILES MODIFIED
- `src/locked_in/simple_store.py`: +`get_task_detail()` (~100 LOC)
- `src/locked_in/web_frontend.py`: +routes, +`_render_task_detail_page()`, +`_render_404()`, clickable names (~200 LOC)

## NEXT SESSION
- Could add a visual timeline bar chart (horizontal stacked bars for work/pause proportions)
- Could add task comparison view across multiple days for recurring tasks

## REFERENCES
- Plan: `docs/plans/20260508_2130_task_detail_timeline.md`
