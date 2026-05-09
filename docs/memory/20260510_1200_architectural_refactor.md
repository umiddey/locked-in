# 20260510_1200_architectural_refactor
**Task**: Refactor UI to Jinja2 and Decouple Daemon services
**Status**: PENDING
## WHAT
- Migrate HTML f-strings to Jinja2 templates. ❌
- Decouple Daemon into independent background services. ❌
- Implement thread-safe event queue for state changes. ❌
## HOW
- Create `src/locked_in/templates/` and migrate layouts/components.
- Extract `IdleDetector` and `ActivityDetector` into standalone service threads.
- Refactor `Daemon._tick` to be an event consumer rather than a poller.
## WHY
- The current codebase suffers from "God Objects" and brittle UI rendering.
- Separation of concerns will improve maintainability and system stability.
## FILES MODIFIED
- `docs/plans/improvements/20260510_architectural_refactor.md` (Plan)
## NEXT SESSION
- Initialize Phase 1: Add Jinja2 and create base templates.
## REFERENCES
- Critique on codebase quality (May 10, 2026).
