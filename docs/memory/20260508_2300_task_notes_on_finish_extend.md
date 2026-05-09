# 20260508_2300_task_notes_on_finish_extend
**Task**: Add notes textarea to finish/extend task actions
**Status**: COMPLETE
## WHAT
- Added textarea for notes on both "Finish Task" and "Extend" action forms ✓
- Wired extend notes into `extend_task_runtime` and tracking events metadata ✓
- Added CSS styling for `.act-notes` textarea ✓
## HOW
- Modified `_render_page` HTML in `web_frontend.py` — replaced bare button forms with form+textarea combos
- Updated `extend_task_runtime()` in `simple_store.py` to accept `notes` param, stores in event metadata
- `_extend_current_from_form` now reads notes from form, passes to store + logs `task_extend_note` event
- Finish path was already wired (reads `form.get("notes")` → `finish_task_runtime` → `task_runs.notes`)
## WHY
- User wants to write context notes when completing or extending tasks for later analysis
- Finish already had backend support, just needed UI textarea
- Extend had no notes support at all — added to event metadata since extends don't create task_runs
## FILES MODIFIED
- `src/locked_in/web_frontend.py`: textarea in finish+extend forms, CSS for `.act-notes`/`.act-form`, extend handler reads notes
- `src/locked_in/simple_store.py`: `extend_task_runtime` accepts `notes` kwarg, stores in event metadata
## NEXT SESSION
- Pre-existing test failure in `test_historical_render_shows_date_picker_and_return_button` (KeyError: 'plan_exists') — unrelated
## REFERENCES
- `task_runs.notes` column (already existed)
- `tracking_events.metadata_json` stores extend notes
- Verification: import check passed, test failure is pre-existing
