# Task Editing in Detail View

## Background & Motivation
Currently, users can only edit pending tasks (name and duration) from the main dashboard's schedule list. The user wants the ability to edit a task's details directly from its dedicated detail page (`/task/<id>`), provided the task has not yet been started.

## Scope & Impact
- Updates `web_frontend.py` to identify if a task is eligible for editing (i.e., pending/unstarted).
- Modifies `web_frontend.py`'s routing to allow redirecting back to the detail page after a successful edit.
- Modifies `task_detail.html` to include an edit interface (button and form) for eligible tasks.

## Proposed Solution
1. **Determine Edit Eligibility:** In `web_frontend.py`'s `_render_task_detail_page`, calculate a `can_edit` boolean flag. A task is considered pending if it has no `runs`, no `timeline` entries, and `completed_at` is null.
2. **Support Custom Redirects:** Update the `/task/edit` route handler to accept a `redirect_to` form parameter. This will allow the form submitted from the detail page to route the user back to the same detail page instead of the dashboard.
3. **Detail Page UI:** In `task_detail.html`, if `can_edit` is true, display an "Edit" button in the hero section. Clicking this will toggle visibility of a simple edit form containing inputs for `task_name` and `duration_minutes`.

## Implementation Plan

### Phase 1: Backend Updates [COMPLETE]
- In `LockedInWebFrontend.run.Handler.do_POST`, update the `/task/edit` route to use `form.get("redirect_to") or "/"` for its redirect path. [DONE]
- In `_render_task_detail_page`, compute `can_edit = not detail["completed_at"] and not detail["runs"] and not detail["timeline"]` and pass it to the Jinja template context. [DONE]

### Phase 2: Template Updates [COMPLETE]
- In `task_detail.html`, add CSS for the inline edit form. [DONE]
- Add an "Edit" button next to the task name or in the hero status bar, visible only if `can_edit` is true. [DONE]
- Add a hidden form that toggles visibility when the "Edit" button is clicked. The form will submit to `/task/edit` with `redirect_to=/task/{{ task_id }}`. [DONE]

## Verification
- Navigate to a pending task's detail page and confirm the "Edit" button is visible.
- Edit the task's name and duration, submit, and ensure it redirects back to the detail page with the updated values.
- Navigate to a started or completed task's detail page and verify the "Edit" button is absent.