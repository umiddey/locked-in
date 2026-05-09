from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from focus_warden.simple_store import SimpleTodoStore, TaskDraft
from focus_warden.web_frontend import FocusWardenWebFrontend


class HistoricalPlannerViewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)

        self.today = date.today()
        self.yesterday = self.today - timedelta(days=1)
        self.two_days_ago = self.today - timedelta(days=2)

        self.store = SimpleTodoStore(Path(self.tmpdir.name) / "simple_todos.db")
        self.store.save_plan(self.two_days_ago, [TaskDraft("Older", 15)])
        self.store.save_plan(self.yesterday, [TaskDraft("Latest historical", 25)])

        self.frontend = FocusWardenWebFrontend("/tmp/no.sock", store=self.store)
        self.frontend._metrics_payload = lambda target_date: {
            "focus_seconds": 0, "pause_seconds": 0, "call_seconds": 0,
            "planned_seconds": 0, "by_task": [],
        }
        self.frontend._time_blocks_payload = lambda target_date: {"blocks": []}
        self.frontend._status_payload = lambda target_date: {
            "daemon": {
                "session_id": None,
                "state": "idle",
                "current_item": None,
                "next_item": None,
                "bootstrap_error": None,
                "next_bootstrap_retry_at": None,
            },
            "plan": {
                "plan_exists": True,
                "saved_at": "2026-05-06T09:00:00",
                "session_started_at": "2026-05-06T09:00:00",
                "task_count": 1,
                "completed_count": 0,
                "task_runtime": None,
                "tasks": [
                    {
                        "id": 1,
                        "position": 0,
                        "task_name": "Task",
                        "duration_minutes": 30,
                        "completed_at": None,
                        "last_outcome": None,
                        "description": None,
                    }
                ],
                "schedule": [],
                "current_entry": None,
                "next_entry": None,
                "recent_runs": [],
            },
            "target_date": target_date.isoformat(),
        }

    def test_root_page_ignores_date_query_and_stays_on_today(self) -> None:
        self.assertEqual(self.frontend._page_target_date_from_query({}), self.today)
        self.assertEqual(
            self.frontend._page_target_date_from_query({"date": [self.yesterday.isoformat()]}),
            self.today,
        )

    def test_display_date_uses_dd_mm_yyyy_format(self) -> None:
        self.assertEqual(self.frontend._format_display_date(date(2026, 5, 6)), "06 05 2026")

    def test_historical_view_uses_latest_saved_date_by_default(self) -> None:
        self.assertEqual(
            self.frontend._page_target_date_from_query({"view": ["historical"]}),
            self.yesterday,
        )
        self.assertEqual(
            self.store.get_latest_plan_date(before=self.today),
            self.yesterday,
        )

    def test_deleting_last_row_does_not_restore_raw_import_text(self) -> None:
        result = self.frontend._save_plan_from_form(
            {
                "date": self.yesterday.isoformat(),
                "intent": "save",
                "task_name_0": "",
                "task_minutes_0": "",
                "task_delete_0": "on",
                "tasks": "Latest historical - 25",
            }
        )

        self.assertEqual(result["status"], f"saved {self.yesterday.isoformat()}")

        plan = self.store.get_plan(self.yesterday)
        self.assertIsNotNone(plan)
        self.assertEqual(plan.tasks, [])
        self.assertEqual(self.store.get_latest_plan_date(before=self.today), self.two_days_ago)

    def test_today_render_shows_history_button_and_no_date_picker(self) -> None:
        html = self.frontend._render_page(self.today, "", historical_view=False)
        self.assertIn("History", html)
        self.assertNotIn('input type="date" name="date"', html)

    def test_historical_render_shows_date_picker_and_return_button(self) -> None:
        html = self.frontend._render_page(self.yesterday, "", historical_view=True)
        self.assertIn("Today", html)
        self.assertIn('input type="date" name="date"', html)
        self.assertIn("Historical view", html)


if __name__ == "__main__":
    unittest.main()
