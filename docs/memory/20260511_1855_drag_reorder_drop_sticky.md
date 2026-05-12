# Naming convention: YYYYMMDD_HHMM_task_name
**Task**: Fix dashboard drag-and-drop reorder snapback on pending tasks
**Status**: COMPLETE
## WHAT
- Change ✓
- The pending-task drag handler now remembers the last valid hover target and insertion side, so releasing the mouse does not lose the reorder target.
- The drag flow now falls back to repeated `/task/move` requests if `/task/reorder` is unavailable, which avoids the 404/JSON parse failure seen in the browser.
## HOW
- Added `lastDropTarget` and `lastDropAbove` state inside the dashboard drag script.
- Captured the active hover row during `dragover` and reused it during `drop` when the browser's drop event target is unreliable.
- Added a fragment application helper and a move-by-steps fallback so reorder still works against older running servers.
- Cleared the stored drag state on `drop` and `dragend` to keep the UI state clean.
## WHY
- The user could see the yellow insertion line over the correct row, but the actual reorder still snapped back.
- The root cause was twofold: `drop` re-derived the target from the release event, which can be null or inconsistent even after a valid `dragover`, and the live server was returning 404 for `/task/reorder`.
- Reusing the last confirmed hover target makes the reorder stick to the position the user actually indicated, and falling back to `/task/move` keeps the feature working even when the newer reorder route is absent.
## FILES MODIFIED
- `src/locked_in/templates/index.html`: fixed the drag/drop reorder handler for pending dashboard tasks and added a compatibility fallback.
## NEXT SESSION
- If users still report odd drag behavior, add a browser-level smoke test for the schedule fragment reorder flow.
## REFERENCES
- Plan context: none; this was a tiny frontend fix.
- Verification: `rtk /usr/bin/bash -lc 'git diff --check'`
- Verification: `rtk /usr/bin/bash -lc 'tmp=$(mktemp --suffix=.js); sed -n "189,286p" src/locked_in/templates/index.html > "$tmp"; node --check "$tmp"; status=$?; rm -f "$tmp"; exit $status'`
