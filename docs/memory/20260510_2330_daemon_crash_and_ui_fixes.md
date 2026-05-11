# 20260510_2330_daemon_crash_and_ui_fixes
**Task**: Fix daemon crashes during task recovery and correct dashboard UI labeling.
**Status**: COMPLETE
## WHAT
- Fixed `ValueError: list.remove(x): x not in list` in daemon ✓
- Fixed `TypeError: '>=' not supported between instances of 'datetime' and 'str'` in daemon ✓
- Fixed "NEXT UP" label appearing for "RUNNING" tasks on dashboard ✓
- Fixed "Extend" button not adding time to active tasks ✓
## HOW
- **Daemon Fixes (`daemon.py`):**
    - Updated `_recover_active_task` to insert "synthetic" recovered tasks into `self.schedule`.
    - Converted `started_at` string from DB to `datetime` object during recovery.
    - Added safety check `if item in self.schedule` before calling `remove()` in `_on_item_finished`.
- **Dashboard Fixes (`web_frontend.py`):**
    - Corrected data path for `task_runtime` in hero helpers (`_hero_label`, `_hero_cls`, etc.).
    - Updated `_extend_current_from_form` to properly calculate and send `extra_seconds` to the daemon.
## WHY
- The daemon was failing to maintain a consistent internal state after restarts mid-task. The UI was misreporting task status because it was looking for the runtime state in an outdated data location.
## FILES MODIFIED
- `src/locked_in/daemon.py`
- `src/locked_in/web_frontend.py`
## NEXT SESSION
- Monitor daemon stability across session restarts.
## REFERENCES
- `docs/memory/20260510_unified_dashboard.md`
