# Unified Dashboard Strategy

## Background & Motivation
The previous Locked-In dashboard suffered from a disjointed user experience:
1.  **Split Context:** Planning (Bulk Editor) was at the bottom, while Execution (Active Task) was at the top, and the Schedule was in the middle.
2.  **Navigation Friction:** Viewing task details required full-page navigation, breaking the "Focus State."
3.  **Safety:** "Reset Day" was too accessible in the dashboard footer.

## Scope & Impact
- Comprehensive refactor of the dashboard layout and component architecture.
- Impact on all main dashboard routes and fragment updates.

## Proposed Solution
1.  **The Live Plan:** A unified schedule where active tasks expand to show controls.
2.  **Sidecar Detail View:** AJAX-powered panel for inspecting tasks without leaving the dashboard.
3.  **Bulk Editor Modal:** "Pro Mode" for quick text-based planning.
4.  **Settings Danger Zone:** Relocating destructive actions.

## Implementation Plan

### Phase 1: Architecture & Backend [COMPLETE]
- Add fragment routes for task details. [DONE]
- Consolidate dashboard rendering context. [DONE]

### Phase 2: Template Refactor [COMPLETE]
- Overhaul `index.html` layout. [DONE]
- Redesign `schedule.html` for dynamic states. [DONE]
- Integrate Hero/Actions into schedule rows. [DONE]

### Phase 3: Sidecar & Modal JS [COMPLETE]
- Implement AJAX detail loading. [DONE]
- Implement Modal toggle. [DONE]

### Phase 4: Cleanup & Safety [COMPLETE]
- Move "Reset Day" to settings. [DONE]
- Delete redundant component files. [DONE]

## Verification
- Dashboard loads with unified schedule.
- Active task shows timer and buttons correctly.
- Clicking task name opens sidecar panel.
- Pro Mode opens bulk editor modal.
- Settings page contains Reset Day functionality.
