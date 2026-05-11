# 20260510_1600_unified_dashboard_refactor
**Task**: Refactor web dashboard into a unified view.
**Status**: PENDING
## WHAT
- Unified Schedule (Live Plan) with integrated task controls.
- Sidecar Detail View for task information.
- Relocated "Reset Day" to settings "Danger Zone".
- Pro Mode (Bulk Editor) moved to a modal/toggle.
## HOW
- Modify `web_frontend.py` to add fragment routes and update rendering logic.
- Overhaul `index.html` and `schedule.html` for the new layout.
- Update `settings.html` for the Danger Zone.
- Add JS/CSS for sidecar and active row integration.
## WHY
- The dashboard was fragmented across multiple components (hero, actions, schedule, planner).
- Merging these into a single "Live Plan" view improves workflow efficiency and clarity.
- A sidecar avoids full-page navigations for task details, keeping the user in their context.
## FILES MODIFIED
- `src/locked_in/web_frontend.py`
- `src/locked_in/templates/index.html`
- `src/locked_in/templates/components/schedule.html`
- `src/locked_in/templates/settings.html`
- `src/locked_in/templates/task_detail.html`
- `src/locked_in/templates/base.html`
## NEXT SESSION
- Implement Phase 1: Backend Updates.
## REFERENCES
- [[20260510_unified_dashboard_refactor]]
