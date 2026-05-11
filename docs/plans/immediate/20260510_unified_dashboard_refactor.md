# Plan: Unified Dashboard Refactor

Refactor the Locked-In web dashboard into a "Unified Dashboard" with a single "Live Plan" view, integrating active task controls into the schedule list and adding a sidecar for task details.

## Phase 1: Backend Updates (`web_frontend.py`)
- **Task 1.1:** Add `/fragments/task-detail/<id>` route to `Handler`.
- **Task 1.2:** Implement `_render_task_detail_fragment(task_id)` to return a fragment-friendly version of task details.
- **Task 1.3:** Update `_render_page` to provide context for the unified schedule and bulk editor.
- **Task 1.4:** Update `_render_dashboard_fragments` to support the new unified components.

## Phase 2: Layout & Global Styles (`base.html` & `index.html`)
- **Task 2.1:** Overhaul `index.html` layout to support the "main schedule" and "sidecar panel".
- **Task 2.2:** Add CSS for `.side-panel`, `.modal` (Pro Mode), and `.sc--active-hero` (integrated active task).
- **Task 2.3:** Implement JS for `openTaskDetail(id)`, `closeTaskDetail()`, and `toggleProMode()`.
- **Task 2.4:** Remove "Reset Day" from `index.html` footer.

## Phase 3: Unified Schedule Component (`components/schedule.html`)
- **Task 3.1:** Redesign `sc` rows.
- **Task 3.2:** Integrate `hero.html` and `actions.html` logic into the `sc--active` row when a task is running or paused.
- **Task 3.3:** Add "Add Task" button at the bottom of the schedule list.
- **Task 3.4:** Ensure task names trigger `openTaskDetail(id)` via JS instead of navigation.

## Phase 4: Settings & Danger Zone (`settings.html`)
- **Task 4.1:** Add a "Danger Zone" section at the bottom of the settings page.
- **Task 4.2:** Move the "Reset Day" button and logic here.

## Phase 5: Cleanup & Validation
- **Task 5.1:** Remove redundant component includes from `index.html`.
- **Task 5.2:** Ensure fragment updates still work correctly for the unified view.
- **Task 5.3:** Verify all links and forms.

## VERIFICATION STRATEGY
- **Manual Verification:**
    - Open the dashboard, verify the schedule view.
    - Start a task, verify it expands and shows controls.
    - Click a task name, verify sidecar opens with details.
    - Toggle Pro Mode, verify bulk editor appears.
    - Go to settings, verify "Reset Day" is in the Danger Zone.
- **Automated Testing:**
    - Update `tests/test_web_frontend.py` if necessary to reflect the new route and fragment structure.
