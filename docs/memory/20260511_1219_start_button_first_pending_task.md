# Naming convention: YYYYMMDD_HHMM_task_name
**Task**: Fix the dashboard Start button so it appears on the first pending task when nothing is running or paused.
**Status**: COMPLETE
## WHAT
- Change ✓
## HOW
- Update the full-page dashboard render context so `next_task` points at the first pending entry instead of the second one.
- Add a regression test that renders two pending tasks and asserts the Start button appears once, on the first row.
## WHY
- The template already renders the Start button conditionally, but the main page was passing `plan["next_entry"]`, which skips the first pending task and leaves the Start action unreachable in the all-pending state.
## FILES MODIFIED
- `src/locked_in/web_frontend.py`: route `next_task` to the first pending entry in `_render_page()`.
- `tests/test_web_frontend.py`: add a regression test for the first pending row Start button.
## NEXT SESSION
- None.
## REFERENCES
- User report about the missing Start button on the first pending task.
- Verification: `rtk .venv/bin/python -m unittest tests.test_web_frontend.HistoricalPlannerViewTests.test_first_pending_task_gets_start_button_on_full_page -q` -> passed.
