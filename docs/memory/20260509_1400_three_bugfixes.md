# 20260509_1400_three_bugfixes
**Task**: Fix 3 bugs: add task description, fix notifications, fix stretch lockout
**Status**: COMPLETE
## WHAT
- Task description column ✓
- Notification fixes ✓
- Stretch lockout fix ✓
## HOW
- Added `description TEXT` column to plan_tasks, wired through TaskDraft/EditableTaskDraft/PlanTask, web task editor row, planner
- Removed "Session started" notification from daemon bootstrap; added `_next_task_notified_for` tracker to fire "Next up in ~5 min: TASKNAME" once per runtime based on actual ETA
- Changed `StretchLockout.start()` to NOT reset accumulated work; changed daemon to call `pause()` (not `stop()`) between tasks so cumulative work persists across task boundaries
## WHY
User reported: no description field, wrong notifications ("Session started" on save, next task too early/wrong), stretch lockout fires randomly instead of at cumulative 60min work
## FILES MODIFIED
- simple_store.py: description column + dataclass fields + save/load/update
- web_frontend.py: description in task editor rows, plan payload, CSS
- planning.py: format_task_drafts handles description
- simple_app.py: _plan_to_drafts passes description
- daemon.py: removed "Session started" notification, added next-task warning, changed stop() to pause() between tasks
- stretch_lockout.py: start() no longer resets accumulation, added docstring
- tests/test_web_frontend.py: updated mock payload + assertions to match current UI
## NEXT SESSION
- Test end-to-end with actual daemon running
## REFERENCES
- Plan: docs/plans/immediate/20260509_1400_three_bugfixes.md
