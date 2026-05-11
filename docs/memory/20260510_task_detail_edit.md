# 20260510_1700_task_detail_edit
**Task**: Allow editing pending tasks directly from their detail page.
**Status**: COMPLETE
## WHAT
- Added "Edit" functionality to the task detail page ✓
- Supported redirecting back to the detail page after editing ✓
- Restricted editing to unstarted/pending tasks ✓
## HOW
- Updated `/task/edit` route in `web_frontend.py` to support an optional `redirect_to` parameter.
- Enhanced `_render_task_detail_page` to compute a `can_edit` flag based on task status (no runs, no timeline, not completed).
- Modified `task_detail.html` to:
    - Include a new `edit-form` and `hero__header` CSS.
    - Show an "Edit" button if `can_edit` is True.
    - Display a toggleable form for editing the task name and duration.
    - Submit the form with `redirect_to` pointing back to the task's detail view.
- Added `toggleEdit` JavaScript function to handle the UI interaction.
## WHY
- Users need a way to quickly correct or adjust tasks while viewing their details, especially when they realize a task is misconfigured before starting it.
## FILES MODIFIED
- `src/locked_in/web_frontend.py`
- `src/locked_in/templates/task_detail.html`
## NEXT SESSION
- Test the edit flow with various task states.
## REFERENCES
- `docs/plans/immediate/edit_pending_task_detail.md`
