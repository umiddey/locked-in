# Persistent Web Navigation

## Background & Motivation
Currently, only the main dashboard (`/`) has a complete navigation bar (Clock, Status Dot, Refresh, History, Settings). Other pages like History (`/history`) and Settings (`/settings`) override this with a minimal "Dashboard" return button. The goal is to make all main navigation options, particularly "Settings", accessible from every page.

## Scope & Impact
- Updates Jinja2 templates (`base.html` and child pages) to share a unified top navigation bar.
- Updates the HTTP handler (`web_frontend.py`) to provide necessary context variables (`daemon_online`, `target_date_iso`, `page_id`) to all template renders.

## Proposed Solution
1. **Unify Navigation Template**: Move the complex `nav_right` logic from `index.html` into `base.html` as the default block content. Use a `page_id` variable to conditionally hide links (e.g., hide the "Settings" link when already on the settings page).
2. **Context Data injection**: Create a helper in `web_frontend.py` to efficiently fetch the daemon status and bundle it with standard context variables. Pass these to every `_render` call.

## Implementation Plan

### Phase 1: Context Injection in Backend [COMPLETE]
- Modify `LockedInWebFrontend` to pass `daemon_online`, `target_date_iso`, `historical_view`, and a `page_id` (e.g., 'dashboard', 'history', 'settings', 'task_detail') to all template rendering methods. [DONE]

### Phase 2: Template Refactoring [COMPLETE]
- Update `base.html`'s `nav_right` block to include the full navigation structure, using `page_id` to adjust active states or hide redundant links. [DONE]
- Remove `{% block nav_right %}` from `index.html`, `history.html`, and `settings.html`. [DONE]
- For `task_detail.html`, integrate its specific "Back" button into the unified nav or keep it alongside the standard links. [DONE]

## Verification
- Verify the web server starts correctly.
- Verify `/`, `/history`, `/settings`, and a `/task/<id>` page all render without Jinja2 errors and display the full navigation bar.
