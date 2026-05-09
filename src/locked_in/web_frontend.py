from __future__ import annotations

import calendar as cal_mod
import html
import json
import re
from datetime import date, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from .control_client import send_command
from .planning import format_task_drafts, parse_task_drafts
from .simple_store import DEFAULT_TASK_DURATION_MINUTES, EditableTaskDraft, SimpleTodoStore, TaskRuntime
from .metrics import summarize_day, summarize_range


class LockedInWebFrontend:
    def __init__(
        self,
        socket_path: str,
        port: int = 8765,
        store: SimpleTodoStore | None = None,
        config_path: "Path | None" = None,
    ):
        self.socket_path = socket_path
        self.port = port
        self.store = store or SimpleTodoStore()
        self.config_path = config_path

    def run(self) -> int:
        frontend = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):  # noqa: A003
                return

            def do_HEAD(self):  # noqa: N802
                self._dispatch(include_body=False)

            def do_GET(self):  # noqa: N802
                self._dispatch(include_body=True)

            def do_POST(self):  # noqa: N802
                parsed = urlparse(self.path)
                form = self._read_form()
                view_mode = form.get("view", "")

                if parsed.path == "/run/pause":
                    result = frontend._pause_current_from_form(form)
                    if form.get("fragment") == "1":
                        target_date = frontend._target_date_from_form(form)
                        fragments = frontend._render_dashboard_fragments(target_date)
                        msg = frontend._message_from_result(result)
                        if "error" in result:
                            fragments["banner"] = f'<div id="banner-section"><div class="ban ban--err">{html.escape(msg)}</div></div>'
                        self._send_json(fragments, include_body=True)
                    else:
                        self._redirect("/", frontend._target_date_from_form(form), frontend._message_from_result(result), view_mode)
                    return

                if parsed.path == "/run/resume":
                    result = frontend._resume_current_from_form(form)
                    if form.get("fragment") == "1":
                        target_date = frontend._target_date_from_form(form)
                        fragments = frontend._render_dashboard_fragments(target_date)
                        msg = frontend._message_from_result(result)
                        if "error" in result:
                            fragments["banner"] = f'<div id="banner-section"><div class="ban ban--err">{html.escape(msg)}</div></div>'
                        self._send_json(fragments, include_body=True)
                    else:
                        self._redirect("/", frontend._target_date_from_form(form), frontend._message_from_result(result), view_mode)
                    return

                if parsed.path == "/run/extend":
                    result = frontend._extend_current_from_form(form)
                    if form.get("fragment") == "1":
                        target_date = frontend._target_date_from_form(form)
                        fragments = frontend._render_dashboard_fragments(target_date)
                        msg = frontend._message_from_result(result)
                        if "error" in result:
                            fragments["banner"] = f'<div id="banner-section"><div class="ban ban--err">{html.escape(msg)}</div></div>'
                        self._send_json(fragments, include_body=True)
                    else:
                        self._redirect("/", frontend._target_date_from_form(form), frontend._message_from_result(result), view_mode)
                    return

                if parsed.path in {"/pause", "/resume", "/give-up"}:
                    result = frontend._command(parsed.path.removeprefix("/"))
                    if form.get("fragment") == "1":
                        target_date = frontend._target_date_from_form(form)
                        fragments = frontend._render_dashboard_fragments(target_date)
                        msg = frontend._message_from_result(result)
                        if "error" in result:
                            fragments["banner"] = f'<div id="banner-section"><div class="ban ban--err">{html.escape(msg)}</div></div>'
                        self._send_json(fragments, include_body=True)
                    else:
                        self._redirect(
                            "/",
                            frontend._target_date_from_form(form),
                            frontend._message_from_result(result),
                            view_mode,
                        )
                    return

                if parsed.path == "/run/start-current":
                    result = frontend._start_current_from_form(form)
                    if form.get("fragment") == "1":
                        target_date = frontend._target_date_from_form(form)
                        fragments = frontend._render_dashboard_fragments(target_date)
                        msg = frontend._message_from_result(result)
                        if "error" in result:
                            fragments["banner"] = f'<div id="banner-section"><div class="ban ban--err">{html.escape(msg)}</div></div>'
                        self._send_json(fragments, include_body=True)
                    else:
                        self._redirect(
                            "/",
                            frontend._target_date_from_form(form),
                            frontend._message_from_result(result),
                            view_mode,
                        )
                    return

                if parsed.path == "/run/finish-current":
                    result = frontend._finish_current_from_form(form)
                    if form.get("fragment") == "1":
                        target_date = frontend._target_date_from_form(form)
                        fragments = frontend._render_dashboard_fragments(target_date)
                        msg = frontend._message_from_result(result)
                        if "error" in result:
                            fragments["banner"] = f'<div id="banner-section"><div class="ban ban--err">{html.escape(msg)}</div></div>'
                        self._send_json(fragments, include_body=True)
                    else:
                        self._redirect(
                            "/",
                            frontend._target_date_from_form(form),
                            frontend._message_from_result(result),
                            view_mode,
                        )
                    return

                if parsed.path == "/day/reset":
                    result = frontend._reset_day_from_form(form)
                    self._redirect(
                        "/",
                        frontend._target_date_from_form(form),
                        frontend._message_from_result(result),
                        view_mode,
                    )
                    return

                if parsed.path == "/plan":
                    result = frontend._save_plan_from_form(form)
                    self._redirect(
                        "/",
                        frontend._target_date_from_form(form),
                        frontend._message_from_result(result),
                        view_mode,
                    )
                    return

                if parsed.path == "/task/delete":
                    result = frontend._delete_task_from_form(form)
                    self._redirect(
                        "/",
                        frontend._target_date_from_form(form),
                        frontend._message_from_result(result),
                        view_mode,
                    )
                    return

                if parsed.path == "/task/edit":
                    result = frontend._edit_task_from_form(form)
                    self._redirect(
                        "/",
                        frontend._target_date_from_form(form),
                        frontend._message_from_result(result),
                        view_mode,
                    )
                    return

                if parsed.path == "/session/start":
                    result = frontend._start_session_from_form(form)
                    self._redirect(
                        "/",
                        frontend._target_date_from_form(form),
                        frontend._message_from_result(result),
                        view_mode,
                    )
                    return

                if parsed.path == "/settings":
                    result = frontend._save_settings_from_form(form)
                    msg = result.get("error") or result.get("status", "")
                    self._send_html(frontend._render_settings_page(msg), include_body=True)
                    return

                if parsed.path == "/task/notes":
                    target_date = frontend._target_date_from_form(form)
                    task_id = int(form.get("task_id", "0") or "0")
                    notes = form.get("notes", "")
                    frontend.store.update_task_run_notes(task_id, notes)
                    if form.get("fragment") == "1":
                        detail = frontend.store.get_task_detail(task_id)
                        self._send_json({"notes": frontend._render_notes_fragment(detail)}, include_body=True)
                    else:
                        self._redirect(f"/task/{task_id}", target_date, "Notes saved")
                    return

                self.send_error(HTTPStatus.NOT_FOUND)

            def _dispatch(self, include_body: bool) -> None:
                parsed = urlparse(self.path)
                query = parse_qs(parsed.query)

                if parsed.path == "/":
                    target_date = frontend._page_target_date_from_query(query)
                    message = query.get("msg", [""])[0]
                    payload = frontend._render_page(
                        target_date,
                        message,
                        historical_view=frontend._is_historical_view(query),
                    )
                    self._send_html(payload, include_body=include_body)
                    return

                if parsed.path == "/api/status":
                    self._send_json(
                        frontend._status_payload(frontend._target_date_from_query(query)),
                        include_body=include_body,
                    )
                    return

                if parsed.path == "/api/overview":
                    self._send_json(
                        frontend._overview_payload(frontend._target_date_from_query(query)),
                        include_body=include_body,
                    )
                    return

                if parsed.path == "/api/plan":
                    self._send_json(
                        frontend._plan_payload(frontend._target_date_from_query(query)),
                        include_body=include_body,
                    )
                    return

                if parsed.path == "/api/runs":
                    self._send_json(
                        frontend._runs_payload(frontend._target_date_from_query(query)),
                        include_body=include_body,
                    )
                    return

                if parsed.path == "/api/metrics":
                    target_date = frontend._target_date_from_query(query)
                    self._send_json(
                        frontend._metrics_payload(target_date),
                        include_body=include_body,
                    )
                    return

                if parsed.path == "/api/metrics/range":
                    start_date = frontend._parse_target_date(query.get("start", [""])[0])
                    end_date = frontend._parse_target_date(query.get("end", [""])[0])
                    self._send_json(
                        frontend._metrics_range_payload(start_date, end_date),
                        include_body=include_body,
                    )
                    return

                if parsed.path == "/api/time-blocks":
                    target_date = frontend._target_date_from_query(query)
                    self._send_json(
                        frontend._time_blocks_payload(target_date),
                        include_body=include_body,
                    )
                    return

                if parsed.path == "/settings":
                    self._send_html(frontend._render_settings_page(), include_body=include_body)
                    return

                if parsed.path == "/api/events":
                    target_date = frontend._target_date_from_query(query)
                    self._send_json(
                        frontend._events_payload(target_date),
                        include_body=include_body,
                    )
                    return

                if parsed.path == "/fragments/dashboard":
                    target_date = frontend._target_date_from_query(query)
                    fragments = frontend._render_dashboard_fragments(target_date)
                    self._send_json(fragments, include_body=include_body)
                    return

                task_match = re.match(r"^/task/(\d+)$", parsed.path)
                if task_match:
                    task_id = int(task_match.group(1))
                    self._send_html(
                        frontend._render_task_detail_page(task_id),
                        include_body=include_body,
                    )
                    return

                api_task_match = re.match(r"^/api/task/(\d+)$", parsed.path)
                if api_task_match:
                    task_id = int(api_task_match.group(1))
                    detail = frontend.store.get_task_detail(task_id)
                    self._send_json(
                        detail or {"error": "Task not found"},
                        include_body=include_body,
                    )
                    return

                if parsed.path == "/history":
                    year = int(query.get("year", [str(date.today().year)])[0])
                    month = int(query.get("month", [str(date.today().month)])[0])
                    self._send_html(frontend._render_history_page(year, month), include_body=include_body)
                    return

                self.send_error(HTTPStatus.NOT_FOUND)

            def _read_form(self) -> dict[str, str]:
                length = int(self.headers.get("Content-Length", "0") or "0")
                raw = self.rfile.read(length).decode("utf-8") if length else ""
                form = parse_qs(raw, keep_blank_values=True)
                return {key: values[0] if values else "" for key, values in form.items()}

            def _send_html(self, body: str, include_body: bool) -> None:
                encoded = body.encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                if include_body:
                    self.wfile.write(encoded)

            def _send_json(self, payload: dict, include_body: bool) -> None:
                encoded = json.dumps(payload, indent=2).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                if include_body:
                    self.wfile.write(encoded)

            def _redirect(self, path: str, target_date: date, message: str, view_mode: str = "") -> None:
                params: dict[str, str] = {}
                if view_mode == "historical":
                    params["view"] = "historical"
                    params["date"] = target_date.isoformat()
                if message:
                    params["msg"] = message
                location = f"{path}?{urlencode(params)}" if params else path
                self.send_response(HTTPStatus.SEE_OTHER)
                self.send_header("Location", location)
                self.send_header("Content-Length", "0")
                self.end_headers()

        server = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        try:
            print(f"Locked-In web dashboard running at http://127.0.0.1:{self.port}")
            server.serve_forever()
            return 0
        except KeyboardInterrupt:
            return 0
        finally:
            server.server_close()

    def _target_date_from_query(self, query: dict[str, list[str]]) -> date:
        value = query.get("date", [""])[0]
        return self._parse_target_date(value)

    def _is_historical_view(self, query: dict[str, list[str]]) -> bool:
        return query.get("view", [""])[0] == "historical"

    def _page_target_date_from_query(self, query: dict[str, list[str]]) -> date:
        if not self._is_historical_view(query):
            return date.today()

        value = query.get("date", [""])[0]
        if value:
            return self._parse_target_date(value)

        historical_date = self.store.get_latest_plan_date(before=date.today())
        return historical_date or date.today()

    def _target_date_from_form(self, form: dict[str, str]) -> date:
        return self._parse_target_date(form.get("date", ""))

    def _parse_target_date(self, value: str) -> date:
        if not value:
            return date.today()
        return date.fromisoformat(value)

    def _format_display_date(self, target_date: date) -> str:
        return target_date.strftime("%d %m %Y")

    def _status_payload(self, target_date: date) -> dict:
        daemon_status = send_command(self.socket_path, {"command": "status"})
        plan_state = self._plan_payload(target_date)
        return {
            "target_date": target_date.isoformat(),
            "daemon": daemon_status,
            "plan": plan_state,
        }

    def _overview_payload(self, target_date: date) -> dict:
        payload = self._status_payload(target_date)
        payload["store_path"] = str(self.store.path)
        return payload

    def _runs_payload(self, target_date: date) -> dict:
        plan = self.store.get_plan(target_date)
        return {
            "target_date": target_date.isoformat(),
            "recent_runs": [
                {
                    "id": run.id,
                    "task_name": run.task_name,
                    "started_at": run.started_at,
                    "ended_at": run.ended_at,
                    "duration_seconds": run.duration_seconds,
                    "outcome": run.outcome,
                    "notes": run.notes,
                }
                for run in self.store.get_recent_runs(50)
                if run.target_date == target_date.isoformat()
            ],
            "task_count": len(plan.tasks) if plan else 0,
        }

    def _plan_payload(self, target_date: date) -> dict:
        plan = self.store.get_plan(target_date)
        session_started_at = self.store.get_session(target_date)
        runtime = self.store.get_active_task_runtime(target_date)
        runtime_entries = self.store.project_runtime_schedule(target_date)
        recent_runs = [
            run
            for run in self.store.get_recent_runs(25)
            if run.target_date == target_date.isoformat()
        ]

        pending_entries = [e for e in runtime_entries if e.status in ("pending", "running", "paused")]
        current_entry_rt = pending_entries[0] if pending_entries else None
        next_entry_rt = pending_entries[1] if len(pending_entries) > 1 else None

        runtime_payload = None
        if runtime:
            now = datetime.now()
            eta = runtime.compute_eta(now)
            runtime_payload = {
                "id": runtime.id,
                "plan_task_id": runtime.plan_task_id,
                "status": runtime.status,
                "started_at": runtime.started_at,
                "paused_at": runtime.paused_at,
                "estimated_seconds": runtime.estimated_seconds,
                "accumulated_pause_seconds": runtime.accumulated_pause_seconds,
                "actual_work_seconds": runtime.actual_work_seconds(now),
                "eta": eta.isoformat(timespec="seconds"),
            }

        return {
            "target_date": target_date.isoformat(),
            "plan_exists": bool(plan and plan.tasks),
            "saved_at": plan.saved_at if plan else None,
            "session_started_at": session_started_at.isoformat(timespec="seconds") if session_started_at else None,
            "task_count": len(plan.tasks) if plan else 0,
            "completed_count": sum(1 for task in plan.tasks if task.completed_at) if plan else 0,
            "task_runtime": runtime_payload,
            "tasks": [
                {
                    "id": task.id,
                    "position": task.position,
                    "task_name": task.task_name,
                    "duration_minutes": task.duration_minutes,
                    "completed_at": task.completed_at,
                    "last_outcome": task.last_outcome,
                    "description": task.description,
                }
                for task in (plan.tasks if plan else [])
            ],
            "schedule": [
                {
                    "task_id": e.task_id,
                    "task_name": e.task_name,
                    "status": e.status,
                    "projected_start": e.projected_start,
                    "projected_end": e.projected_end,
                    "actual_start": e.actual_start,
                    "actual_end": e.actual_end,
                    "eta": e.eta,
                    "duration_minutes": e.estimated_seconds // 60,
                    "actual_work_seconds": e.actual_work_seconds,
                    "pause_seconds": e.pause_seconds,
                    "drift_seconds": e.drift_seconds,
                }
                for e in runtime_entries
            ],
            "current_entry": self._runtime_entry_payload(current_entry_rt) if current_entry_rt else None,
            "next_entry": self._runtime_entry_payload(next_entry_rt) if next_entry_rt else None,
            "recent_runs": [
                {
                    "id": run.id,
                    "task_name": run.task_name,
                    "started_at": run.started_at,
                    "ended_at": run.ended_at,
                    "duration_seconds": run.duration_seconds,
                    "outcome": run.outcome,
                    "notes": run.notes,
                }
                for run in recent_runs
            ],
        }

    def _row_indexes_from_form(self, form: dict[str, str]) -> list[int]:
        indexes: set[int] = set()
        for key in form:
            match = re.match(r"^task_name_(\d+)$", key)
            if match:
                indexes.add(int(match.group(1)))
        return sorted(indexes)

    def _task_rows_from_form(self, form: dict[str, str]) -> list[EditableTaskDraft]:
        indexes = self._row_indexes_from_form(form)
        if not indexes:
            return []

        rows: list[EditableTaskDraft] = []
        for index in indexes:
            if form.get(f"task_delete_{index}") in {"1", "true", "on", "yes"}:
                continue
            task_name = form.get(f"task_name_{index}", "").strip()
            if not task_name:
                continue
            task_id_raw = form.get(f"task_id_{index}", "").strip()
            task_id = int(task_id_raw) if task_id_raw else None
            duration_raw = form.get(f"task_minutes_{index}", "").strip()
            try:
                duration_minutes = max(int(duration_raw), 1) if duration_raw else DEFAULT_TASK_DURATION_MINUTES
            except (ValueError, TypeError):
                duration_minutes = DEFAULT_TASK_DURATION_MINUTES
            description = form.get(f"task_desc_{index}", "").strip()
            rows.append(
                EditableTaskDraft(
                    task_id=task_id,
                    task_name=task_name,
                    duration_minutes=duration_minutes,
                    description=description,
                )
            )
        return rows

    def _has_deleted_task_rows(self, form: dict[str, str]) -> bool:
        for index in self._row_indexes_from_form(form):
            if form.get(f"task_delete_{index}") in {"1", "true", "on", "yes"}:
                return True
        return False

    def _task_editor_rows(self, tasks: list[dict]) -> tuple[str, str]:
        rows: list[str] = []
        for index, task in enumerate(tasks):
            status = "done" if task["completed_at"] else "pending"
            badge = "DONE" if task["completed_at"] else "PENDING"
            rows.append(
                self._render_task_row(
                    index=index,
                    task_id=task["id"],
                    task_name=task["task_name"],
                    duration_minutes=task["duration_minutes"],
                    status=status,
                    badge=badge,
                    completed_at=task["completed_at"],
                    last_outcome=task["last_outcome"],
                    description=task.get("description") or "",
                )
            )
        template = self._render_task_row(
            index="__INDEX__",
            task_id="",
            task_name="",
            duration_minutes=DEFAULT_TASK_DURATION_MINUTES,
            status="pending",
            badge="",
            completed_at=None,
            last_outcome=None,
            description="",
            template=True,
        )
        return "".join(rows), template

    def _render_task_row(
        self,
        *,
        index,
        task_id,
        task_name,
        duration_minutes,
        status,
        badge,
        completed_at,
        last_outcome,
        description: str = "",
        template: bool = False,
    ) -> str:
        row_class = f"task-row {html.escape(status)}"
        name_value = html.escape(str(task_name))
        minutes_value = html.escape(str(duration_minutes))
        desc_value = html.escape(str(description))
        task_id_field = (
            f'<input type="hidden" name="task_id_{index}" value="{html.escape(str(task_id))}" />'
            if task_id not in {"", None}
            else f'<input type="hidden" name="task_id_{index}" value="" />'
        )
        badge_html = f'<span class="pill {html.escape(status)}">{html.escape(badge)}</span>' if badge else ""
        completed_html = (
            f'<div class="task-hint">Completed {html.escape(str(completed_at))}</div>'
            if completed_at
            else '<div class="task-hint">Not completed yet</div>'
        )
        outcome_html = (
            f'<div class="task-hint">Last outcome: {html.escape(str(last_outcome))}</div>'
            if last_outcome
            else ""
        )
        delete_label = "Remove row"
        if template:
            delete_label = "Remove row"
        return f"""
        <div class="{row_class}">
          <div class="task-index">{"__DISPLAY__" if template else html.escape(str(index + 1))}</div>
          <div class="task-fields">
            {task_id_field}
            <input type="text" name="task_name_{index}" value="{name_value}" placeholder="Task name" />
            <input type="number" name="task_minutes_{index}" min="1" value="{minutes_value}" />
            <input type="text" name="task_desc_{index}" value="{desc_value}" placeholder="Description (optional)" class="task-desc" />
          </div>
          <div class="task-meta">
            {badge_html}
            {completed_html}
            {outcome_html}
          </div>
          <label class="task-delete">
            <input type="checkbox" name="task_delete_{index}" />
            {delete_label}
          </label>
        </div>
        """

    def _save_plan_from_form(self, form: dict[str, str]) -> dict:
        target_date = self._target_date_from_form(form)
        intent = form.get("intent", "save")
        drafts = self._task_rows_from_form(form)
        if not drafts and not self._has_deleted_task_rows(form):
            raw_tasks = parse_task_drafts(form.get("tasks", ""))
            drafts = [
                EditableTaskDraft(
                    task_id=None,
                    task_name=task.task_name,
                    duration_minutes=task.duration_minutes,
                    description=task.description,
                )
                for task in raw_tasks
                ]
        if not drafts and not self._has_deleted_task_rows(form):
            return {"error": "Add at least one task."}

        self.store.save_plan_rows(target_date, drafts)
        if intent in {"save_start", "save-and-start", "save_start_day"}:
            plan = self.store.get_plan(target_date)
            first_pending = next((t for t in plan.tasks if not t.completed_at), None) if plan else None
            if not first_pending:
                return {"status": f"saved {target_date.isoformat()} (no pending tasks to start)"}
            self.store.ensure_session(target_date)
            result = send_command(self.socket_path, {
                "command": "start_task",
                "target_date": target_date.isoformat(),
                "plan_task_id": first_pending.id,
            })
            if "error" in result:
                try:
                    self.store.start_task_runtime(target_date, first_pending.id, source="web")
                except ValueError:
                    return {"error": "Failed to start task."}
            return {"status": f"saved and started {target_date.isoformat()}"}
        return {"status": f"saved {target_date.isoformat()}"}

    def _start_current_from_form(self, form: dict[str, str]) -> dict:
        target_date = self._target_date_from_form(form)

        runtime = self.store.get_active_task_runtime(target_date)
        if runtime:
            return {"error": "A task is already running."}

        plan = self.store.get_plan(target_date)
        if not plan or not plan.tasks:
            return {"error": "Save a plan first."}

        current_task = next((t for t in plan.tasks if not t.completed_at), None)
        if not current_task:
            return {"error": "No pending task to start."}

        self.store.ensure_session(target_date)
        result = send_command(self.socket_path, {
            "command": "start_task",
            "target_date": target_date.isoformat(),
            "plan_task_id": current_task.id,
        })
        if "error" in result:
            try:
                rt = self.store.start_task_runtime(target_date, current_task.id, source="web")
                return {"status": f"started {current_task.task_name}"}
            except ValueError as e:
                return {"error": str(e)}
        return {"status": f"started {current_task.task_name}"}

    def _finish_current_from_form(self, form: dict[str, str]) -> dict:
        target_date = self._target_date_from_form(form)
        runtime = self.store.get_active_task_runtime(target_date)
        if not runtime:
            return {"error": "No active task run."}

        notes = form.get("notes", "")
        result = send_command(self.socket_path, {
            "command": "finish_task",
            "outcome": "finished",
            "notes": notes,
        })
        if "error" in result:
            try:
                rt = self.store.finish_task_runtime(target_date, outcome="finished", notes=notes)
                task_row = self.store.conn.execute(
                    "SELECT task_name FROM plan_tasks WHERE id = ?", (rt.plan_task_id,),
                ).fetchone()
                return {"status": f"finished {task_row['task_name'] if task_row else 'task'}"}
            except ValueError as e:
                return {"error": str(e)}
        task_row = self.store.conn.execute(
            "SELECT task_name FROM plan_tasks WHERE id = ?", (runtime.plan_task_id,),
        ).fetchone()
        return {"status": f"finished {task_row['task_name'] if task_row else 'task'}"}

    def _pause_current_from_form(self, form: dict[str, str]) -> dict:
        target_date = self._target_date_from_form(form)
        runtime = self.store.get_active_task_runtime(target_date)
        if not runtime or runtime.status != "running":
            return {"error": "No running task to pause."}

        result = send_command(self.socket_path, {"command": "pause_task", "reason": "manual"})
        if "error" in result:
            try:
                self.store.pause_task_runtime(target_date, reason="manual", source="web")
                return {"status": "paused"}
            except ValueError as e:
                return {"error": str(e)}
        return {"status": "paused"}

    def _resume_current_from_form(self, form: dict[str, str]) -> dict:
        target_date = self._target_date_from_form(form)
        runtime = self.store.get_active_task_runtime(target_date)
        if not runtime or runtime.status != "paused":
            return {"error": "No paused task to resume."}

        result = send_command(self.socket_path, {"command": "resume_task"})
        if "error" in result:
            try:
                self.store.resume_task_runtime(target_date, source="web")
                return {"status": "resumed"}
            except ValueError as e:
                return {"error": str(e)}
        return {"status": "resumed"}

    def _extend_current_from_form(self, form: dict[str, str]) -> dict:
        target_date = self._target_date_from_form(form)
        runtime = self.store.get_active_task_runtime(target_date)
        if not runtime:
            return {"error": "No active task to extend."}

        notes = form.get("notes", "").strip()
        extra_seconds = runtime.estimated_seconds
        result = send_command(self.socket_path, {"command": "extend_task", "extra_seconds": extra_seconds})
        if "error" in result:
            try:
                self.store.extend_task_runtime(target_date, extra_seconds, source="web", notes=notes)
                return {"status": f"extended +{extra_seconds // 60}m"}
            except ValueError as e:
                return {"error": str(e)}
        if notes:
            self.store.log_event(
                target_date, "task_extend_note",
                session_id=runtime.session_id,
                plan_task_id=runtime.plan_task_id,
                source="web",
                metadata={"notes": notes, "extra_seconds": extra_seconds},
            )
        return {"status": f"extended +{extra_seconds // 60}m"}

    def _reset_day_from_form(self, form: dict[str, str]) -> dict:
        target_date = self._target_date_from_form(form)
        self.store.reset_day(target_date)
        return {"status": f"reset {target_date.isoformat()}"}

    def _delete_task_from_form(self, form: dict[str, str]) -> dict:
        target_date = self._target_date_from_form(form)
        try:
            task_id = int(form["task_id"])
        except (KeyError, ValueError):
            return {"error": "Invalid task ID."}
        if self.store.delete_task(target_date, task_id):
            return {"status": "Task deleted"}
        return {"error": "Task not found."}

    def _edit_task_from_form(self, form: dict[str, str]) -> dict:
        target_date = self._target_date_from_form(form)
        try:
            task_id = int(form["task_id"])
        except (KeyError, ValueError):
            return {"error": "Invalid task ID."}
        task_name = form.get("task_name", "").strip() or None
        duration_raw = form.get("duration_minutes", "").strip()
        duration_minutes = int(duration_raw) if duration_raw else None
        desc_raw = form.get("description", "").strip()
        if self.store.update_task(target_date, task_id, task_name=task_name, duration_minutes=duration_minutes, description=desc_raw):
            return {"status": "Task updated"}
        return {"error": "Task not found."}

    def _metrics_payload(self, target_date: date) -> dict:
        return summarize_day(self.store, target_date)

    def _metrics_range_payload(self, start_date: date, end_date: date) -> dict:
        return summarize_range(self.store, start_date, end_date)

    def _time_blocks_payload(self, target_date: date) -> dict:
        blocks = self.store.get_time_blocks(target_date)
        return {
            "target_date": target_date.isoformat(),
            "blocks": [
                {
                    "id": b.id,
                    "type": b.block_type,
                    "start": b.started_at,
                    "end": b.ended_at,
                    "duration": b.duration_seconds,
                    "task_id": b.plan_task_id,
                    "project": b.project,
                    "category": b.category,
                    "tags": json.loads(b.tags_json) if b.tags_json else [],
                    "interruptions": b.interruption_count,
                }
                for b in blocks
            ],
        }

    def _events_payload(self, target_date: date) -> dict:
        events = self.store.conn.execute(
            "SELECT * FROM tracking_events WHERE target_date = ? ORDER BY occurred_at ASC",
            (target_date.isoformat(),),
        ).fetchall()

        return {
            "target_date": target_date.isoformat(),
            "events": [
                {
                    "id": e["id"],
                    "type": e["event_type"],
                    "occurred_at": e["occurred_at"],
                    "task_id": e["plan_task_id"],
                    "session_id": e["session_id"],
                    "source": e["source"],
                    "metadata": json.loads(e["metadata_json"]) if e["metadata_json"] else None,
                }
                for e in events
            ],
        }

    def _entry_payload(self, entry) -> dict:
        return {
            "task_name": entry.task.task_name,
            "scheduled_start": entry.scheduled_start.isoformat(timespec="seconds"),
            "scheduled_end": entry.scheduled_end.isoformat(timespec="seconds"),
            "duration_minutes": entry.task.duration_minutes,
            "completed_at": entry.task.completed_at,
            "last_outcome": entry.task.last_outcome,
        }

    def _runtime_entry_payload(self, entry) -> dict:
        return {
            "task_id": entry.task_id,
            "task_name": entry.task_name,
            "status": entry.status,
            "projected_start": entry.projected_start,
            "projected_end": entry.projected_end,
            "actual_start": entry.actual_start,
            "eta": entry.eta,
            "duration_minutes": entry.estimated_seconds // 60,
        }

    def _message_from_result(self, result: dict) -> str:
        if "error" in result:
            return result["error"]
        return result.get("status", "ok")

    def _command(self, command: str) -> dict:
        return send_command(self.socket_path, {"command": command.replace("-", "_")})

    def _start_session_from_form(self, form: dict[str, str]) -> dict:
        target_date = self._target_date_from_form(form)
        self.store.ensure_session(target_date)
        return {"status": f"session started {target_date.isoformat()}"}

    def _read_config_values(self) -> dict[str, str]:
        if not self.config_path or not Path(self.config_path).exists():
            return {}
        text = Path(self.config_path).read_text(encoding="utf-8")
        import sys
        if sys.version_info >= (3, 11):
            import tomllib
        else:
            import tomli as tomllib
        return tomllib.loads(text)

    def _update_config_value(self, section: str, key: str, value: str) -> None:
        if not self.config_path:
            return
        path = Path(self.config_path)
        lines = path.read_text(encoding="utf-8").splitlines()
        in_section = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                in_section = stripped == f"[{section}]"
                continue
            if in_section and "=" in stripped:
                line_key = stripped.split("=", 1)[0].strip()
                if line_key == key:
                    lines[i] = f"{key} = {value}"
                    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
                    return
        for i, line in enumerate(lines):
            if line.strip() == f"[{section}]":
                lines.insert(i + 1, f"{key} = {value}")
                path.write_text("\n".join(lines) + "\n", encoding="utf-8")
                return

    def _save_settings_from_form(self, form: dict[str, str]) -> dict:
        if not self.config_path:
            return {"error": "No config file found."}
        try:
            fields = {
                ("schedule", "stretch_interval_minutes"): ("int", 1, 480),
                ("schedule", "stretch_duration_minutes"): ("int", 1, 60),
                ("schedule", "hard_shutdown_time"): ("time", None, None),
                ("schedule", "shutdown_warning_minutes"): ("int", 0, 120),
                ("schedule", "hard_shutdown_enabled"): ("bool", None, None),
                ("warden", "task_start_grace_seconds"): ("int", 0, 3600),
                ("warden", "default_extend_minutes"): ("int", 0, 120),
                ("warden", "give_up_cooldown_seconds"): ("int", 0, 3600),
                ("auto_pause", "idle_pause_seconds"): ("int", 0, 3600),
                ("auto_pause", "idle_resume_grace_seconds"): ("int", 1, 30),
            }
            for (section, key), (typ, lo, hi) in fields.items():
                form_key = f"{section}__{key}"
                raw = form.get(form_key, "").strip()
                if not raw and typ != "bool":
                    continue
                if typ == "int":
                    val = int(raw)
                    if lo is not None and val < lo:
                        return {"error": f"{key} must be at least {lo}."}
                    if hi is not None and val > hi:
                        return {"error": f"{key} must be at most {hi}."}
                    self._update_config_value(section, key, str(val))
                elif typ == "bool":
                    val = form_key in form and raw in {"on", "true", "1", "yes"}
                    self._update_config_value(section, key, "true" if val else "false")
                elif typ == "time":
                    if not re.match(r"^\d{1,2}:\d{2}$", raw):
                        return {"error": f"Invalid time format for {key}: use HH:MM."}
                    self._update_config_value(section, key, f'"{raw}"')
            self._toggle_hypr_auto_open("open_dashboard_on_login" in form and form.get("open_dashboard_on_login", "").strip() in {"on", "true", "1", "yes"})
            import subprocess
            try:
                subprocess.run(
                    ["systemctl", "--user", "restart", "locked-in.service"],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                return {"status": "Settings saved and daemon restarted."}
            except (subprocess.CalledProcessError, FileNotFoundError) as exc:
                return {"status": "Settings saved. Could not auto-restart daemon: " + str(exc)}
        except (ValueError, OSError) as exc:
            return {"error": str(exc)}

    _HYPR_AUTOSTART = Path("~/.config/hypr/autostart.conf").expanduser()
    _HYPR_MARKER = "exec-once = sleep 5 && xdg-open http://localhost:8765"
    _HYPR_COMMENTED = "# " + _HYPR_MARKER

    def _is_hypr_auto_open_enabled(self) -> bool:
        if not self._HYPR_AUTOSTART.exists():
            return False
        text = self._HYPR_AUTOSTART.read_text()
        return self._HYPR_MARKER in text and self._HYPR_COMMENTED not in text

    def _toggle_hypr_auto_open(self, enable: bool) -> None:
        if not self._HYPR_AUTOSTART.exists():
            return
        text = self._HYPR_AUTOSTART.read_text()
        if enable and self._HYPR_COMMENTED in text:
            text = text.replace(self._HYPR_COMMENTED, self._HYPR_MARKER)
            self._HYPR_AUTOSTART.write_text(text)
        elif enable and self._HYPR_MARKER not in text:
            text = text.rstrip() + "\n\n# Open Locked-In dashboard after login\n" + self._HYPR_MARKER + "\n"
            self._HYPR_AUTOSTART.write_text(text)
        elif not enable and self._HYPR_MARKER in text and self._HYPR_COMMENTED not in text:
            text = text.replace(self._HYPR_MARKER, self._HYPR_COMMENTED)
            self._HYPR_AUTOSTART.write_text(text)

    def _render_history_page(self, year: int, month: int) -> str:
        today = date.today()
        first_of_month = date(year, month, 1)
        last_of_month = date(year, month, cal_mod.monthrange(year, month)[1])

        prev_month = month - 1 if month > 1 else 12
        prev_year = year if month > 1 else year - 1
        next_month = month + 1 if month < 12 else 1
        next_year = year if month < 12 else year + 1

        plan_dates = set(self.store.get_plan_dates_range(first_of_month, last_of_month))
        summaries = {}
        for d in plan_dates:
            summaries[d] = self.store.get_day_summary(date.fromisoformat(d))

        # Year Grid (Current - 2 to Current + 1)
        year_html = ""
        for y in range(today.year - 2, today.year + 2):
            active = " nav-tile--active" if y == year else ""
            year_html += f'<a href="/history?year={y}&month={month}" class="nav-tile{active}">{y}</a>'

        # Month Grid (6x2)
        month_html = ""
        for m in range(1, 13):
            active = " nav-tile--active" if m == month else ""
            m_name = date(2000, m, 1).strftime("%b")
            month_html += f'<a href="/history?year={year}&month={m}" class="nav-tile{active}">{m_name}</a>'

        today_str = today.isoformat()
        next_year_limit = today.replace(year=today.year + 1)
        
        weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        first_wd = first_of_month.weekday()
        cal_days: list[tuple[int | None, str | None, str | None, dict | None]] = []
        for _ in range(first_wd):
            cal_days.append((None, None, None, None))
        for day in range(1, last_of_month.day + 1):
            d = date(year, month, day)
            d_str = d.isoformat()
            in_plan = d_str in plan_dates
            summary = summaries.get(d_str)
            cal_days.append((day, d_str, "today" if d_str == today_str else None, summary if in_plan else None))

        weekday_headers = "".join(f'<div class="cal__wd">{html.escape(w)}</div>' for w in weekdays)
        grid_cells_html = ""
        for day_num, d_str, today_cls, summary in cal_days:
            if day_num is None:
                grid_cells_html += '<div class="cal__cell cal__cell--empty"></div>'
            else:
                d_obj = date.fromisoformat(d_str)
                can_link = d_obj <= next_year_limit
                
                cls = ""
                if today_cls: cls = "cal__cell--today"
                elif d_str in plan_dates: cls = "cal__cell--plan"
                
                label = ""
                dot = ""
                if d_str in plan_dates and summary:
                    tc = summary["task_count"]
                    cc = summary["completed_count"]
                    label = f"{tc}T {cc}D"
                    dot = '<span class="cal__dot"></span>'
                
                if can_link:
                    link = f'/?view=historical&date={d_str}'
                    grid_cells_html += f'<a href="{html.escape(link)}" class="cal__cell {cls}">{dot}<span class="cal__num">{day_num}</span><span class="cal__label">{html.escape(label)}</span></a>'
                else:
                    grid_cells_html += f'<div class="cal__cell {cls}">{dot}<span class="cal__num">{day_num}</span><span class="cal__label">{html.escape(label)}</span></div>'

        return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>History — Locked-In</title>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700;800&family=Outfit:wg@400;500;600;700;800;900&display=swap" rel="stylesheet"/>
<style>
:root {{
    color-scheme:dark;
    --bg:#06070a;--s1:#0c0e14;--s2:#12151d;--s3:#191d28;
    --b1:#1a1f2e;--b2:#252b3d;
    --tx:#ccc8be;--txh:#eae6dc;--dim:#585e72;
    --grn:#2fac6a;--grnh:#44d88a;--grnbg:rgba(47,172,106,.08);--grnb:rgba(47,172,106,.22);
    --amb:#d4a039;--ambh:#eab94e;--ambbg:rgba(212,160,57,.07);--ambb:rgba(212,160,57,.18);
    --mono:'JetBrains Mono',monospace;--sans:'Outfit',system-ui,sans-serif;
    --r:6px;--rl:10px;
}}
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:var(--sans);background:var(--bg);color:var(--tx);line-height:1.5;-webkit-font-smoothing:antialiased}}
.shell{{max-width:720px;margin:0 auto;padding:20px 16px 80px}}
.nav{{display:flex;align-items:center;justify-content:space-between;padding:12px 0 16px;border-bottom:1px solid var(--b1);margin-bottom:20px}}
.nav__brand{{font-family:var(--mono);font-size:13px;font-weight:700;color:var(--amb);letter-spacing:.08em;text-transform:uppercase;text-decoration:none}}
.nav__btn{{appearance:none;background:var(--s2);border:1px solid var(--b1);color:var(--dim);font-family:var(--mono);font-size:11px;font-weight:500;padding:5px 12px;border-radius:var(--r);cursor:pointer;transition:.15s;text-decoration:none}}
.nav__btn:hover{{background:var(--s3);color:var(--tx);border-color:var(--b2)}}
.nav__btn--accent{{color:var(--amb);border-color:var(--ambb)}}
.cal-nav{{display:grid;grid-template-columns:1fr 2.5fr;gap:12px;margin-bottom:20px}}
.cal-nav__section{{background:var(--s1);border:1px solid var(--b1);border-radius:var(--rl);padding:12px}}
.cal-nav__head{{font-family:var(--mono);font-size:9px;font-weight:700;color:var(--dim);text-transform:uppercase;margin-bottom:8px;letter-spacing:.05em}}
.year-grid{{display:grid;grid-template-columns:1fr 1fr;gap:6px}}
.month-grid-wrap{{overflow-x:auto;scrollbar-width:none}}
.month-grid-wrap::-webkit-scrollbar{{display:none}}
.month-grid{{display:grid;grid-template-columns:repeat(6, 1fr);grid-template-rows:1fr 1fr;gap:6px;min-width:420px}}
.nav-tile{{display:block;text-decoration:none;background:var(--s2);border:1px solid var(--b1);border-radius:var(--r);padding:6px;text-align:center;font-family:var(--mono);font-size:12px;font-weight:600;color:var(--tx);transition:.1s;position:relative}}
.nav-tile:hover{{background:var(--s3);border-color:var(--b2);color:var(--txh)}}
.nav-tile--active{{background:var(--ambbg);border-color:var(--ambb);color:var(--ambh)}}
.cal-grid{{display:grid;grid-template-columns:repeat(7,1fr);gap:4px}}
.cal__wd{{font-family:var(--mono);font-size:10px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--dim);text-align:center;padding:6px 0}}
.cal__cell{{background:var(--s1);border:1px solid var(--b1);border-radius:var(--r);padding:8px 6px;min-height:64px;display:flex;flex-direction:column;align-items:center;gap:2px;transition:.15s;position:relative}}
.cal__cell--empty{{background:transparent;border:none;min-height:0}}
.cal__cell--plan{{cursor:pointer}}
.cal__cell--plan:hover{{background:var(--s2);border-color:var(--b2)}}
.cal__cell--today{{border-color:var(--ambb)}}
.cal__cell--today .cal__num{{color:var(--ambh);font-weight:800}}
.cal__num{{font-family:var(--mono);font-size:13px;font-weight:600;color:var(--tx)}}
.cal__dot{{width:6px;height:6px;border-radius:50%;background:var(--grn);display:inline-block;margin-bottom:1px}}
.cal__label{{font-family:var(--mono);font-size:9px;color:var(--dim);text-align:center;line-height:1.2}}
a.cal__cell, a.nav-tile{{text-decoration:none;color:inherit}}
a.cal__cell::after, a.nav-tile::after{{content:'';position:absolute;top:0;left:0;right:0;bottom:0;z-index:1}}
.legend{{display:flex;gap:16px;margin-top:16px;justify-content:center}}
.legend__item{{display:flex;align-items:center;gap:5px;font-family:var(--mono);font-size:10px;color:var(--dim)}}
.legend__dot{{width:8px;height:8px;border-radius:50%}}
.legend__dot--plan{{background:var(--grn)}}
.legend__dot--today{{border:2px solid var(--amb)}}
@media(max-width:640px){{
    .shell{{padding:12px 10px 60px}}
    .cal-nav{{grid-template-columns:1fr}}
    .cal__cell{{min-height:48px;padding:6px 4px}}
    .cal__label{{display:none}}
}}
</style>
</head>
<body>
<div class="shell">
<nav class="nav">
    <a href="/" class="nav__brand">Locked-In</a>
    <a href="/" class="nav__btn">&#8592; Dashboard</a>
</nav>

<div class="cal-nav">
    <div class="cal-nav__section">
        <div class="cal-nav__head">Year</div>
        <div class="year-grid">{year_html}</div>
    </div>
    <div class="cal-nav__section">
        <div class="cal-nav__head">Month</div>
        <div class="month-grid-wrap">
            <div class="month-grid">{month_html}</div>
        </div>
    </div>
</div>

<div class="cal-grid">
    {weekday_headers}
    {grid_cells_html}
</div>

<div class="legend">
    <div class="legend__item"><span class="legend__dot legend__dot--plan"></span>Has plan</div>
    <div class="legend__item"><span class="legend__dot legend__dot--today"></span>Today</div>
</div>
</div>
</body>
</html>"""

    def _render_settings_page(self, message: str = "") -> str:
        data = self._read_config_values()
        sched = data.get("schedule", {})
        warden = data.get("warden", {})
        ap = data.get("auto_pause", {})
        auto_open = self._is_hypr_auto_open_enabled()

        def v(section_dict, key, default=""):
            return html.escape(str(section_dict.get(key, default)))

        def checked(section_dict, key, default=False):
            return "checked" if section_dict.get(key, default) else ""

        banner = ""
        if message:
            is_err = "error" in message.lower() or "must" in message.lower() or "invalid" in message.lower()
            bcls = "ban ban--err" if is_err else "ban"
            banner = f'<div class="{bcls}">{html.escape(message)}</div>'

        return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Settings — Locked-In</title>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700;800&family=Outfit:wght@400;500;600;700;800;900&display=swap" rel="stylesheet"/>
<style>
:root {{
    color-scheme:dark;
    --bg:#06070a;--s1:#0c0e14;--s2:#12151d;--s3:#191d28;
    --b1:#1a1f2e;--b2:#252b3d;
    --tx:#ccc8be;--txh:#eae6dc;--dim:#585e72;
    --grn:#2fac6a;--grnh:#44d88a;--grnbg:rgba(47,172,106,.08);--grnb:rgba(47,172,106,.22);
    --amb:#d4a039;--ambh:#eab94e;--ambbg:rgba(212,160,57,.07);--ambb:rgba(212,160,57,.18);
    --red:#c04040;--redh:#e55;--redbg:rgba(192,64,64,.08);--redb:rgba(192,64,64,.22);
    --mono:'JetBrains Mono',monospace;--sans:'Outfit',system-ui,sans-serif;
    --r:6px;--rl:10px;
}}
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:var(--sans);background:var(--bg);color:var(--tx);line-height:1.5;-webkit-font-smoothing:antialiased}}
.shell{{max-width:640px;margin:0 auto;padding:20px 16px 80px}}
.nav{{display:flex;align-items:center;justify-content:space-between;padding:12px 0 16px;border-bottom:1px solid var(--b1);margin-bottom:20px}}
.nav__brand{{font-family:var(--mono);font-size:13px;font-weight:700;color:var(--amb);letter-spacing:.08em;text-transform:uppercase}}
.nav__r{{display:flex;align-items:center;gap:10px}}
.nav__btn{{appearance:none;background:var(--s2);border:1px solid var(--b1);color:var(--dim);font-family:var(--mono);font-size:11px;font-weight:500;padding:5px 12px;border-radius:var(--r);cursor:pointer;transition:.15s;text-decoration:none}}
.nav__btn:hover{{background:var(--s3);color:var(--tx);border-color:var(--b2)}}
.ban{{font-family:var(--mono);font-size:12px;padding:8px 14px;border-radius:var(--r);margin-bottom:12px;border:1px solid var(--ambb);background:var(--ambbg);color:var(--ambh)}}
.ban--err{{border-color:var(--redb);background:var(--redbg);color:var(--redh)}}
h1{{font-family:var(--sans);font-size:22px;font-weight:700;color:var(--txh);margin-bottom:20px}}
.section{{background:var(--s1);border:1px solid var(--b1);border-radius:var(--rl);padding:20px 24px;margin-bottom:16px}}
.section__title{{font-family:var(--mono);font-size:11px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--amb);margin-bottom:14px}}
.field{{display:grid;grid-template-columns:1fr 1fr;gap:8px;align-items:center;padding:8px 0;border-bottom:1px solid var(--b1)}}
.field:last-child{{border-bottom:none}}
.field__label{{font-family:var(--sans);font-size:13px;color:var(--tx)}}
.field__hint{{font-family:var(--mono);font-size:10px;color:var(--dim);grid-column:1/-1;padding-top:2px}}
.field input[type="number"],.field input[type="text"]{{background:var(--s2);border:1px solid var(--b1);color:var(--tx);padding:6px 10px;border-radius:var(--r);font-family:var(--mono);font-size:13px;width:100%;text-align:right}}
.field input:focus{{outline:none;border-color:var(--ambb)}}
.field input[type="checkbox"]{{width:18px;height:18px;accent-color:var(--amb);justify-self:end}}
.btn{{appearance:none;font-family:var(--mono);font-size:11px;font-weight:700;padding:10px 20px;border-radius:var(--r);border:1px solid var(--b1);background:var(--s2);color:var(--tx);cursor:pointer;transition:.15s}}
.btn--primary{{background:var(--amb);border-color:var(--amb);color:#0a0a0a}}
.btn--primary:hover{{background:var(--ambh)}}
.actions{{display:flex;gap:10px;margin-top:20px}}
</style>
</head>
<body>
<div class="shell">
<nav class="nav">
    <a href="/" class="nav__brand" style="text-decoration:none">Locked-In</a>
    <div class="nav__r">
        <a href="/" class="nav__btn">&#8592; Dashboard</a>
    </div>
</nav>

{banner}

<h1>Settings</h1>

<form method="post" action="/settings">
<div class="section">
    <div class="section__title">Break Schedule</div>
    <div class="field">
        <label class="field__label">Work interval</label>
        <input type="number" name="schedule__stretch_interval_minutes" value="{v(sched, 'stretch_interval_minutes', 60)}" min="1" max="480" />
        <div class="field__hint">Minutes of continuous work before a break is enforced</div>
    </div>
    <div class="field">
        <label class="field__label">Break duration</label>
        <input type="number" name="schedule__stretch_duration_minutes" value="{v(sched, 'stretch_duration_minutes', 5)}" min="1" max="60" />
        <div class="field__hint">Minutes you must take a break for</div>
    </div>
</div>

<div class="section">
    <div class="section__title">Shutdown</div>
    <div class="field">
        <label class="field__label">Hard shutdown time</label>
        <input type="text" name="schedule__hard_shutdown_time" value="{v(sched, 'hard_shutdown_time', '01:00')}" placeholder="HH:MM" />
        <div class="field__hint">Time of day to force shutdown (24h format)</div>
    </div>
    <div class="field">
        <label class="field__label">Shutdown warning</label>
        <input type="number" name="schedule__shutdown_warning_minutes" value="{v(sched, 'shutdown_warning_minutes', 10)}" min="0" max="120" />
        <div class="field__hint">Minutes of warning before hard shutdown</div>
    </div>
    <div class="field">
        <label class="field__label">Enabled</label>
        <input type="checkbox" name="schedule__hard_shutdown_enabled" value="on" {checked(sched, 'hard_shutdown_enabled', True)} />
    </div>
</div>

<div class="section">
    <div class="section__title">Task Rules</div>
    <div class="field">
        <label class="field__label">Start grace period</label>
        <input type="number" name="warden__task_start_grace_seconds" value="{v(warden, 'task_start_grace_seconds', 300)}" min="0" max="3600" />
        <div class="field__hint">Seconds after task starts before enforcement kicks in</div>
    </div>
    <div class="field">
        <label class="field__label">Default extend duration</label>
        <input type="number" name="warden__default_extend_minutes" value="{v(warden, 'default_extend_minutes', 0)}" min="0" max="120" />
        <div class="field__hint">Minutes to add when clicking 'Extend' in popup (0 = use task's original estimate)</div>
    </div>
    <div class="field">
        <label class="field__label">Give-up cooldown</label>
        <input type="number" name="warden__give_up_cooldown_seconds" value="{v(warden, 'give_up_cooldown_seconds', 30)}" min="0" max="3600" />
        <div class="field__hint">Seconds between give-up attempts</div>
    </div>
</div>

<div class="section">
    <div class="section__title">Idle Auto-Pause</div>
    <div class="field">
        <label class="field__label">Idle timeout</label>
        <input type="number" name="auto_pause__idle_pause_seconds" value="{v(ap, 'idle_pause_seconds', 60)}" min="0" max="3600" />
        <div class="field__hint">Seconds of no keyboard/mouse activity before auto-pausing (0 = disabled)</div>
    </div>
    <div class="field">
        <label class="field__label">Resume grace</label>
        <input type="number" name="auto_pause__idle_resume_grace_seconds" value="{v(ap, 'idle_resume_grace_seconds', 3)}" min="1" max="30" />
        <div class="field__hint">Seconds of activity before auto-resuming from idle pause</div>
    </div>
</div>

<div class="section">
    <div class="section__title">Startup</div>
    <div class="field">
        <label class="field__label">Open dashboard on login</label>
        <input type="checkbox" name="open_dashboard_on_login" value="on" {"checked" if auto_open else ""} />
        <div class="field__hint">Open the web dashboard in your browser when you log in (Hyprland)</div>
    </div>
</div>

<div class="actions">
    <button class="btn btn--primary" type="submit">Save Settings</button>
    <a href="/" class="btn">Cancel</a>
</div>
</form>

</div>
</body>
</html>"""

    def _render_task_detail_page(self, task_id: int) -> str:
        """Render full task detail page with interactive timeline."""
        detail = self.store.get_task_detail(task_id)
        if not detail:
            return self._render_404("Task not found")

        task_name = html.escape(detail["task_name"])
        target_date = detail["target_date"]
        est_m = detail["duration_minutes"]
        work_m = detail["total_work_seconds"] // 60
        work_s = detail["total_work_seconds"] % 60
        pause_m = detail["total_pause_seconds"] // 60
        pause_s = detail["total_pause_seconds"] % 60
        wall_m = detail["total_wall_seconds"] // 60
        delta = work_m - est_m
        delta_cls = "over" if delta > 0 else ("under" if delta < 0 else "on")
        completed_html = f'Completed {html.escape(detail["completed_at"][:16])}' if detail["completed_at"] else "Not completed"
        current_notes = ""
        if detail.get("runs"):
            current_notes = detail["runs"][-1].get("notes") or ""

        notes_entries_html = ""
        if current_notes:
            entries = current_notes.split("\n\n")
            for entry in entries:
                if not entry.strip(): continue
                # Match [HH:MM:SS] Prefix
                match = re.match(r"^\[(\d{{2}}:\d{{2}}:\d{{2}})\] (.*)", entry, re.DOTALL)
                if match:
                    ts, text = match.groups()
                    notes_entries_html += f'<div class="note-entry"><span>{html.escape(ts)}</span>{html.escape(text)}</div>'
                else:
                    notes_entries_html += f'<div class="note-entry">{html.escape(entry)}</div>'

        notes_panel_html = f"""<div id="notes-section" class="panel">
    <div class="panel__head">
        <span class="panel__title">Notes</span>
        <span class="panel__badge" id="notes-saved-badge" style="display:none">saved</span>
    </div>
    <div style="padding:14px 16px">
        <div class="notes-list">
            {notes_entries_html}
        </div>
        <form method="post" action="/task/notes" data-fragment>
            <input type="hidden" name="task_id" value="{task_id}" />
            <input type="hidden" name="date" value="{html.escape(target_date)}" />
            <textarea name="notes" class="act-notes" placeholder="Add a new note..." rows="3"></textarea>
            <div style="margin-top:8px">
                <button class="btn btn--primary" type="submit">Add Note</button>
            </div>
        </form>
    </div>
</div>"""

        total_dur = sum(b["duration_seconds"] for b in detail["timeline"]) or 1
        timeline_html = ""
        if detail["timeline"]:
            first_start = detail["timeline"][0]["started_at"][11:16]
            last_block = detail["timeline"][-1]
            last_end = last_block["ended_at"][11:16] if last_block["ended_at"] else "now"

            chunks = ""
            for block in detail["timeline"]:
                btype = block["type"]
                dur = block["duration_seconds"]
                pct = max(dur / total_dur * 100, 0.5)
                t0 = block["started_at"][11:19] if len(block["started_at"]) >= 19 else block["started_at"][11:16]
                t1 = (block["ended_at"][11:19] if block["ended_at"] and len(block["ended_at"]) >= 19 else "ongoing") if block["ended_at"] else "now"
                label = {"work": "Work", "pause": "Pause", "call": "Call", "idle": "Idle"}.get(btype, btype.title())
                cls = f"tc--{btype}" if btype in ("work", "pause", "call", "idle") else "tc--other"
                chunks += f'<div class="tc {cls}" style="width:{pct:.2f}%" data-label="{label}" data-start="{t0}" data-end="{t1}" data-dur="{dur // 60}m {dur % 60}s"></div>'

            timeline_html = f"""<div class="tl-bar-wrap">
                <div class="tl-times"><span>{html.escape(first_start)}</span><span>{html.escape(last_end)}</span></div>
                <div class="tl-bar">{chunks}</div>
                <div class="tl-legend">
                    <span class="tl-leg"><span class="tl-dot tc--work"></span>Work</span>
                    <span class="tl-leg"><span class="tl-dot tc--pause"></span>Pause</span>
                    <span class="tl-leg"><span class="tl-dot tc--call"></span>Call</span>
                    <span class="tl-leg"><span class="tl-dot tc--idle"></span>Idle</span>
                </div>
            </div>"""
        else:
            timeline_html = '<div class="empty">No timeline data — task was never started.</div>'

        back_link = f'/?view=historical&amp;date={html.escape(target_date)}' if target_date != date.today().isoformat() else "/"

        return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{task_name} — Locked-In</title>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700;800&family=Outfit:wght@400;500;600;700;800;900&display=swap" rel="stylesheet"/>
<style>
:root {{
    color-scheme:dark;
    --bg:#06070a;--s1:#0c0e14;--s2:#12151d;--s3:#191d28;
    --b1:#1a1f2e;--b2:#252b3d;
    --tx:#ccc8be;--txh:#eae6dc;--dim:#585e72;
    --grn:#2fac6a;--grnh:#44d88a;--grnbg:rgba(47,172,106,.08);--grnb:rgba(47,172,106,.22);
    --amb:#d4a039;--ambh:#eab94e;--ambbg:rgba(212,160,57,.07);--ambb:rgba(212,160,57,.18);
    --red:#c04040;--redh:#e55;--redbg:rgba(192,64,64,.08);--redb:rgba(192,64,64,.22);
    --blu:#4488bb;--blubg:rgba(68,136,187,.08);--blub:rgba(68,136,187,.22);
    --purp:#8866cc;--purpbg:rgba(136,102,204,.08);--purpb:rgba(136,102,204,.22);
    --mono:'JetBrains Mono',monospace;--sans:'Outfit',system-ui,sans-serif;
    --r:6px;--rl:10px;
}}
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:var(--sans);background:var(--bg);color:var(--tx);line-height:1.5;-webkit-font-smoothing:antialiased}}
.shell{{max-width:860px;margin:0 auto;padding:20px 16px 80px}}

.nav{{display:flex;align-items:center;justify-content:space-between;padding:12px 0 16px;border-bottom:1px solid var(--b1);margin-bottom:20px}}
.nav__brand{{font-family:var(--mono);font-size:13px;font-weight:700;color:var(--amb);letter-spacing:.08em;text-transform:uppercase;text-decoration:none}}
.nav__btn{{appearance:none;background:var(--s2);border:1px solid var(--b1);color:var(--dim);font-family:var(--mono);font-size:11px;font-weight:500;padding:5px 12px;border-radius:var(--r);cursor:pointer;transition:.15s;text-decoration:none}}
.nav__btn:hover{{background:var(--s3);color:var(--tx);border-color:var(--b2)}}

.hero{{background:var(--s1);border:1px solid var(--b1);border-radius:var(--rl);padding:28px 32px;margin-bottom:16px}}
.hero__date{{font-family:var(--mono);font-size:12px;color:var(--dim);margin-bottom:6px}}
.hero__name{{font-size:28px;font-weight:800;letter-spacing:-.02em;color:var(--txh);line-height:1.15;margin-bottom:8px}}
.hero__status{{font-family:var(--mono);font-size:12px;color:var(--dim);margin-bottom:16px}}
.tag{{font-family:var(--mono);font-size:10px;font-weight:700;letter-spacing:.1em;padding:3px 8px;border-radius:4px}}
.tag--running{{background:var(--grnbg);color:var(--grnh);border:1px solid var(--grnb)}}
.tag--dim{{background:var(--s2);color:var(--dim);border:none;font-size:9px}}

.mbar{{display:flex;gap:1px;background:var(--b1);border-radius:var(--rl);overflow:hidden;margin-bottom:16px}}
.mbar__cell{{flex:1;background:var(--s1);padding:14px 16px;text-align:center}}
.mbar__val{{font-family:var(--mono);font-size:22px;font-weight:800;color:var(--txh);line-height:1;margin-bottom:3px}}
.mbar__lbl{{font-family:var(--mono);font-size:9px;font-weight:600;letter-spacing:.1em;text-transform:uppercase;color:var(--dim)}}
.mbar__sub{{font-family:var(--mono);font-size:10px;color:var(--dim);margin-top:2px}}

.tm__d{{font-family:var(--mono);font-weight:700;padding:1px 6px;border-radius:3px;white-space:nowrap;font-size:12px}}
.tm__d--over{{background:var(--redbg);color:var(--redh)}}
.tm__d--under{{background:var(--grnbg);color:var(--grnh)}}
.tm__d--on{{background:var(--s3);color:var(--dim)}}

.panel{{background:var(--s1);border:1px solid var(--b1);border-radius:var(--rl);overflow:hidden;margin-bottom:16px}}
.panel__head{{display:flex;align-items:center;justify-content:space-between;padding:12px 16px;border-bottom:1px solid var(--b1)}}
.panel__title{{font-family:var(--mono);font-size:10px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--dim)}}
.panel__badge{{font-family:var(--mono);font-size:10px;color:var(--dim);background:var(--s2);padding:2px 7px;border-radius:4px}}

.tl-bar-wrap{{padding:16px}}
.tl-times{{display:flex;justify-content:space-between;font-family:var(--mono);font-size:11px;color:var(--dim);margin-bottom:6px}}
.tl-bar{{display:flex;height:28px;border-radius:6px;overflow:hidden;gap:1px;background:var(--b1)}}
.tc{{transition:opacity .15s;cursor:pointer}}
.tc:hover{{opacity:.8;outline:1px solid #fff}}
.tc--work{{background:linear-gradient(180deg,var(--grnh),var(--grn))}}
.tc--pause{{background:linear-gradient(180deg,var(--ambh),var(--amb))}}
.tc--call{{background:linear-gradient(180deg,#aa88ee,var(--purp))}}
.tc--idle{{background:linear-gradient(180deg,#777,var(--dim))}}
.tc--other{{background:var(--dim)}}
.tl-legend{{display:flex;gap:14px;margin-top:10px;justify-content:center}}
.tl-leg{{display:flex;align-items:center;gap:5px;font-family:var(--mono);font-size:10px;color:var(--dim);font-weight:600;letter-spacing:.05em;text-transform:uppercase}}
.tl-dot{{display:inline-block;width:10px;height:10px;border-radius:3px}}

.detail-panel{{background:var(--s2);border-top:1px solid var(--b1);padding:12px 16px;display:none}}
.detail-grid{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px}}
.detail-item{{display:flex;flex-direction:column;gap:2px}}
.detail-lbl{{font-family:var(--mono);font-size:9px;color:var(--dim);text-transform:uppercase}}
.detail-val{{font-family:var(--mono);font-size:13px;font-weight:700;color:var(--txh)}}

.notes-list{{display:flex;flex-direction:column;gap:8px;margin-bottom:12px}}
.note-entry{{background:var(--s2);border-left:3px solid var(--amb);padding:10px 12px;border-radius:0 var(--r) var(--r) 0;font-family:var(--mono);font-size:12px;line-height:1.4;white-space:pre-wrap;color:var(--tx)}}
.note-entry span{{color:var(--dim);font-weight:700;display:block;margin-bottom:4px;font-size:10px}}

.empty{{padding:24px 16px;text-align:center;font-size:13px;color:var(--dim)}}

@media(max-width:640px){{
    .shell{{padding:12px 10px 60px}}
    .hero{{padding:20px 18px}}
    .hero__name{{font-size:22px}}
    .tl-bar{{height:22px}}
    .tl-bar-wrap{{padding:12px 10px}}
    .mbar{{flex-wrap:wrap}}
    .mbar__cell{{min-width:calc(50% - 1px)}}
}}
</style>
</head>
<body>
<div class="shell">
<nav class="nav">
    <a href="/" class="nav__brand">Locked-In</a>
    <a href="{back_link}" class="nav__btn">&#8592; Back</a>
</nav>

<div class="hero">
    <div class="hero__date">{html.escape(target_date)}</div>
    <div class="hero__name">{task_name}</div>
    <div class="hero__status">{html.escape(completed_html)} &middot; #{detail["position"] + 1} in plan &middot; Est. {est_m}m</div>
</div>

<div class="mbar">
    <div class="mbar__cell">
        <div class="mbar__val">{work_m}m</div>
        <div class="mbar__lbl">Work</div>
        <div class="mbar__sub">{work_s}s extra</div>
    </div>
    <div class="mbar__cell">
        <div class="mbar__val">{pause_m}m</div>
        <div class="mbar__lbl">Paused</div>
        <div class="mbar__sub">{pause_s}s extra</div>
    </div>
    <div class="mbar__cell">
        <div class="mbar__val">{wall_m}m</div>
        <div class="mbar__lbl">Wall</div>
    </div>
    <div class="mbar__cell">
        <div class="mbar__val"><span class="tm__d tm__d--{delta_cls}">{delta:+d}m</span></div>
        <div class="mbar__lbl">vs Est</div>
    </div>
</div>

<div class="panel">
    <div class="panel__head">
        <span class="panel__title">Timeline</span>
        <span class="panel__badge">{detail["block_count"]} segments</span>
    </div>
    {timeline_html}
    <div id="segment-detail" class="detail-panel">
        <div class="detail-grid">
            <div class="detail-item"><span class="detail-lbl">Type</span><span class="detail-val" id="det-type">-</span></div>
            <div class="detail-item"><span class="detail-lbl">Interval</span><span class="detail-val" id="det-interval">-</span></div>
            <div class="detail-item"><span class="detail-lbl">Duration</span><span class="detail-val" id="det-dur">-</span></div>
        </div>
    </div>
</div>

<div id="notes-section-container">
    {notes_panel_html}
</div>

</div>
<script>
document.querySelectorAll('.tc').forEach(el => {{
    el.addEventListener('click', () => {{
        const panel = document.getElementById('segment-detail');
        panel.style.display = 'block';
        document.getElementById('det-type').textContent = el.dataset.label;
        document.getElementById('det-interval').textContent = el.dataset.start + ' - ' + el.dataset.end;
        document.getElementById('det-dur').textContent = el.dataset.dur;
    }});
}});

// Fragment intercept
document.addEventListener('submit', async (e) => {{
    const form = e.target;
    if (!form.dataset.fragment) return;
    e.preventDefault();
    const body = new FormData(form);
    body.set('fragment', '1');
    try {{
        const resp = await fetch(form.action, {{ method: 'POST', body }});
        if (resp.ok) {{
            const data = await resp.json();
            if (data.notes) {{
                const container = document.getElementById('notes-section-container');
                if (container) container.innerHTML = data.notes;
                const badge = document.getElementById('notes-saved-badge');
                if (badge) {{
                    badge.style.display = 'inline';
                    setTimeout(() => badge.style.display = 'none', 2000);
                }}
                // Clear textarea
                const txt = container.querySelector('textarea');
                if (txt) txt.value = '';
            }}
        }}
    }} catch (err) {{ console.error(err); }}
}});
</script>
</body>
</html>"""

    def _render_notes_fragment(self, detail: dict) -> str:
        current_notes = ""
        if detail.get("runs"):
            current_notes = detail["runs"][-1].get("notes") or ""

        notes_entries_html = ""
        if current_notes:
            entries = current_notes.split("\n\n")
            for entry in entries:
                if not entry.strip(): continue
                match = re.match(r"^\[(\d{{2}}:\d{{2}}:\d{{2}})\] (.*)", entry, re.DOTALL)
                if match:
                    ts, text = match.groups()
                    notes_entries_html += f'<div class="note-entry"><span>{html.escape(ts)}</span>{html.escape(text)}</div>'
                else:
                    notes_entries_html += f'<div class="note-entry">{html.escape(entry)}</div>'

        task_id = detail["task_id"]
        target_date = detail["target_date"]
        return f"""<div id="notes-section" class="panel">
    <div class="panel__head">
        <span class="panel__title">Notes</span>
        <span class="panel__badge" id="notes-saved-badge">saved</span>
    </div>
    <div style="padding:14px 16px">
        <div class="notes-list">
            {notes_entries_html}
        </div>
        <form method="post" action="/task/notes" data-fragment>
            <input type="hidden" name="task_id" value="{task_id}" />
            <input type="hidden" name="date" value="{html.escape(target_date)}" />
            <textarea name="notes" class="act-notes" placeholder="Add a new note..." rows="3"></textarea>
            <div style="margin-top:8px">
                <button class="btn btn--primary" type="submit">Add Note</button>
            </div>
        </form>
    </div>
</div>"""

    def _render_404(self, message: str = "Not found") -> str:
        """Simple 404 page."""
        return f"""<!doctype html><html><head><title>404</title>
<style>body{{font-family:system-ui;background:#06070a;color:#ccc;display:flex;align-items:center;justify-content:center;height:100vh}}
.c{{text-align:center}}a{{color:#d4a039}}</style></head>
<body><div class="c"><h1>404</h1><p>{html.escape(message)}</p><a href="/">Back to dashboard</a></div></body></html>"""

    def _render_banner_fragment(self, message: str, daemon: dict, historical_view: bool, target_date: date) -> str:
        parts = []
        if message:
            is_err = any(w in message.lower() for w in ("error", "fail", "no ", "already"))
            bcls = "ban ban--err" if is_err else "ban"
            parts.append(f'<div class="{bcls}">{html.escape(message)}</div>')
        if daemon.get("bootstrap_error"):
            parts.append(f'<div class="ban ban--err">Daemon bootstrap failed: {html.escape(daemon["bootstrap_error"])}</div>')
        if historical_view:
            label = "Planning view" if target_date > date.today() else "Historical view"
            parts.append(f'<div class="ban ban--info">{label}: {html.escape(target_date.strftime("%d %b %Y"))}</div>')
        if not parts:
            return ""
        return "".join(parts)

    def _render_hero_fragment(self, target_date: date, payload: dict, metrics: dict) -> str:
        task_runtime = payload.get("task_runtime")
        plan = payload["plan"]
        plan_tasks = plan["tasks"]

        runtime_status = task_runtime["status"] if task_runtime else None
        has_active = runtime_status in ("running", "paused")
        has_pending = plan["current_entry"] is not None
        has_plan = bool(plan["plan_exists"])

        if has_active:
            rt_task = self.store.conn.execute(
                "SELECT task_name FROM plan_tasks WHERE id = ?", (task_runtime["plan_task_id"],)
            ).fetchone()
            hero_name = html.escape(rt_task["task_name"]) if rt_task else "Active task"
        elif has_pending:
            hero_name = html.escape(plan["current_entry"]["task_name"])
        else:
            hero_name = "No active task"

        if runtime_status == "running":
            hero_cls, hero_label = "hero--running", "RUNNING"
        elif runtime_status == "paused":
            hero_cls, hero_label = "hero--paused", "PAUSED"
        elif has_pending:
            hero_cls, hero_label = "hero--pending", "NEXT UP"
        else:
            hero_cls, hero_label = "hero--idle", "IDLE"

        hero_meta = ""
        if has_active:
            hero_meta = f'Started {html.escape(task_runtime["started_at"][11:16])}'
            if task_runtime.get("eta"):
                hero_meta += f' &mdash; ETA {html.escape(task_runtime["eta"][11:16])}'
        elif has_pending:
            ps = plan["current_entry"].get("projected_start") or ""
            pe = plan["current_entry"].get("projected_end") or ""
            if ps and pe:
                hero_meta = f'{html.escape(ps[11:16])} &mdash; {html.escape(pe[11:16])}'

        hero_detail = ""
        if runtime_status == "running" and task_runtime:
            work_m = task_runtime["actual_work_seconds"] // 60
            est_m = task_runtime["estimated_seconds"] // 60
            hero_detail = f'<div class="hero__detail"><span class="hero__timer" id="work-timer" data-started="{html.escape(task_runtime["started_at"])}" data-pause-acc="{task_runtime["accumulated_pause_seconds"]}">{work_m}m</span> of {est_m}m</div>'
        elif runtime_status == "paused" and task_runtime:
            work_m = task_runtime["actual_work_seconds"] // 60
            pause_acc = task_runtime["accumulated_pause_seconds"] // 60
            hero_detail = f'<div class="hero__detail hero__detail--paused"><span class="hero__pause-icon">&#9646;&#9646;</span> Paused &mdash; {work_m}m worked, {pause_acc}m paused</div>'

        done = plan["completed_count"]
        total = plan["task_count"] or 1
        pct = min(int(done / total * 100), 100)
        completed_str = f"{done}/{plan['task_count']}"

        next_html = ""
        if plan["next_entry"]:
            nt = plan["next_entry"].get("projected_start") or ""
            nt_disp = nt[11:16] if len(nt) >= 16 else ""
            next_html = f"""<div class="hero__next">
                <span class="tag tag--dim">NEXT</span>
                <span class="hero__next-name">{html.escape(plan["next_entry"]["task_name"])}</span>
                <span class="hero__next-time">{html.escape(nt_disp)}</span>
            </div>"""

        return f"""<div class="hero {html.escape(hero_cls)}">
    <div class="hero__top">
        <span class="tag tag--{hero_cls.split('--')[1]}">{html.escape(hero_label)}</span>
        <span class="hero__meta">{hero_meta}</span>
    </div>
    <div class="hero__name">{hero_name}</div>
    {hero_detail}
    <div class="hero__bar">
        <div class="hero__prog"><div class="hero__prog-fill" style="width:{pct}%"></div></div>
        <span class="hero__prog-label">{html.escape(completed_str)}</span>
    </div>
    {next_html}
</div>"""

    def _render_actions_fragment(self, target_date: date, historical_view: bool, payload: dict) -> str:
        task_runtime = payload["plan"].get("task_runtime")
        runtime_status = task_runtime["status"] if task_runtime else None
        has_active = runtime_status in ("running", "paused")
        has_pending = payload["plan"]["current_entry"] is not None
        has_plan = bool(payload["plan"]["plan_exists"])

        form_date_value = html.escape(target_date.isoformat())
        dh = f'<input type="hidden" name="date" value="{form_date_value}" />'
        vh = '<input type="hidden" name="view" value="historical" />' if historical_view else ""

        actions = []
        if not has_plan:
            pass
        elif not has_active and has_pending:
            actions.append(f'<form method="post" action="/run/start-current" data-fragment>{dh}{vh}<button class="act act--start" type="submit">&#9654; Start Task</button></form>')
        if runtime_status == "running":
            actions.append(f'<form method="post" action="/run/pause" data-fragment>{dh}{vh}<button class="act act--pause" type="submit">&#9646;&#9646; Pause</button></form>')
        if runtime_status == "paused":
            actions.append(f'<form method="post" action="/run/resume" data-fragment>{dh}{vh}<button class="act act--resume" type="submit">&#9654; Resume</button></form>')
        if has_active:
            est_m = task_runtime["estimated_seconds"] // 60 if task_runtime else 0
            actions.append(f'<form method="post" action="/run/extend" class="act-form" data-fragment>{dh}{vh}<textarea name="notes" class="act-notes" placeholder="Why extending? (optional)" rows="2"></textarea><button class="act act--extend" type="submit">+{est_m}m More</button></form>')
            actions.append(f'<form method="post" action="/run/finish-current" class="act-form" data-fragment>{dh}{vh}<textarea name="notes" class="act-notes" placeholder="Notes on completion (optional)" rows="2"></textarea><button class="act act--finish" type="submit">&#9632; Finish Task</button></form>')
        actions_html = "\n".join(actions)
        if not actions_html:
            return ""
        return f'<div class="actions">{actions_html}</div>'

    def _render_schedule_fragment(self, target_date: date, payload: dict, historical_view: bool) -> str:
        plan = payload["plan"]
        form_date_value = html.escape(target_date.isoformat())
        dh = f'<input type="hidden" name="date" value="{form_date_value}" />'
        vh = '<input type="hidden" name="view" value="historical" />' if historical_view else ""

        sched_html = ""
        for entry in plan["schedule"]:
            st = entry["status"]
            start_raw = entry.get("actual_start") or entry.get("projected_start") or ""
            end_raw = entry.get("actual_end") or entry.get("eta") or entry.get("projected_end") or ""
            t0 = start_raw[11:16] if len(start_raw) >= 16 else "-"
            t1 = end_raw[11:16] if len(end_raw) >= 16 else "-"
            pause_s = entry.get("pause_seconds", 0)
            pause_tag = f' <span class="tag tag--amber">+{pause_s // 60}m pause</span>' if pause_s > 60 else ""
            work_s = entry.get("actual_work_seconds", 0)
            work_tag = f'<span class="sc__work">{work_s // 60}m</span>' if st in ("finished", "abandoned", "running", "paused") and work_s > 0 else ""

            if st in ("finished", "abandoned"):
                cls = "sc--done"
            elif st in ("running", "paused"):
                cls = "sc--active"
            else:
                cls = "sc--pending"

            task_id = entry.get("task_id")
            actions_cell = ""
            if task_id and st == "pending":
                actions_cell = f'<div class="sc__act"><form method="post" action="/task/delete" onsubmit="return confirm(\'Delete this task?\')">{dh}<input type="hidden" name="task_id" value="{task_id}"/><button class="sc__del" type="submit" title="Delete">&times;</button></form></div>'

            name_html = f'<a href="/task/{task_id}" class="sc__link">{html.escape(entry["task_name"])}</a>' if task_id else html.escape(entry["task_name"])

            sched_html += f"""<div class="sc {cls}">
                <div class="sc__time">{html.escape(t0)}<span class="sc__sep">&mdash;</span>{html.escape(t1)}</div>
                <div class="sc__body">
                    <div class="sc__name">{name_html}{pause_tag}</div>
                    {work_tag}
                </div>
                <div class="sc__est">{entry["duration_minutes"]}m</div>
                {actions_cell}
            </div>"""
        if not sched_html:
            sched_html = '<div class="empty">No schedule. Save a plan first.</div>'

        return f"""<div class="panel">
    <div class="panel__head">
        <span class="panel__title">Schedule</span>
        <span class="panel__badge">{len(plan["schedule"])}</span>
    </div>
    {sched_html}
</div>"""

    def _render_metrics_fragment(self, target_date: date, payload: dict) -> str:
        metrics = payload.get("metrics", {})
        focus_m = metrics.get('focus_seconds', 0) // 60
        pause_m = (metrics.get('pause_seconds', 0) + metrics.get('call_seconds', 0)) // 60
        completed_str = f"{payload['plan']['completed_count']}/{payload['plan']['task_count']}"
        planned_m = metrics.get('planned_seconds', 0) // 60

        return f"""<div class="mbar">
    <div class="mbar__cell"><div class="mbar__val">{focus_m}</div><div class="mbar__lbl">Focus</div></div>
    <div class="mbar__cell"><div class="mbar__val">{html.escape(completed_str)}</div><div class="mbar__lbl">Done</div></div>
    <div class="mbar__cell"><div class="mbar__val">{pause_m}</div><div class="mbar__lbl">Paused</div></div>
    <div class="mbar__cell"><div class="mbar__val">{planned_m}</div><div class="mbar__lbl">Planned</div></div>
</div>"""

    def _render_task_metrics_fragment(self, target_date: date, metrics: dict) -> str:
        tm_html = ""
        for t in metrics.get('by_task', []):
            actual_m = t['actual_seconds'] // 60
            est_m = t['estimated_seconds'] // 60
            delta = actual_m - est_m
            dcls = "over" if delta > 0 else ("under" if delta < 0 else "on")
            tid = t.get("task_id")
            tname = f'<a href="/task/{tid}" class="sc__link">{html.escape(t["task_name"])}</a>' if tid else html.escape(t["task_name"])
            tm_html += f'<div class="tm"><span class="tm__name">{tname}</span><span class="tm__val">{actual_m}m / {est_m}m</span><span class="tm__d tm__d--{dcls}">{delta:+d}m</span></div>'
        if not tm_html:
            return ""
        return f"<div class='panel'><div class='panel__head'><span class='panel__title'>Per-Task</span></div>{tm_html}</div>"

    def _render_dashboard_fragments(self, target_date: date, message: str = "", historical_view: bool = False) -> dict[str, str]:
        payload = self._status_payload(target_date)
        daemon = payload["daemon"]
        payload["metrics"] = self._metrics_payload(target_date)

        banner = self._render_banner_fragment(message, daemon, historical_view, target_date)
        return {
            "banner": f'<div id="banner-section">{banner}</div>' if banner else '<div id="banner-section"></div>',
            "hero": f'<div id="hero-section">{self._render_hero_fragment(target_date, payload, payload["metrics"])}</div>',
            "actions": f'<div id="actions-section">{self._render_actions_fragment(target_date, historical_view, payload)}</div>',
            "schedule": f'<div id="schedule-section">{self._render_schedule_fragment(target_date, payload, historical_view)}</div>',
            "metrics": f'<div id="metrics-section">{self._render_metrics_fragment(target_date, payload)}</div>',
            "task-metrics": f'<div id="task-metrics-section">{self._render_task_metrics_fragment(target_date, payload["metrics"])}</div>',
        }

    def _render_page(self, target_date: date, message: str, historical_view: bool = False) -> str:
        payload = self._status_payload(target_date)
        daemon = payload["daemon"]
        metrics = self._metrics_payload(target_date)
        time_blocks = self._time_blocks_payload(target_date)
        payload["metrics"] = metrics
        plan = payload["plan"]
        plan_tasks = plan["tasks"]

        editor_rows_html, editor_template_html = self._task_editor_rows(plan_tasks)
        if not editor_rows_html:
            editor_rows_html = self._render_task_row(
                index=0, task_id="", task_name="",
                duration_minutes=DEFAULT_TASK_DURATION_MINUTES,
                status="pending", badge="", completed_at=None, last_outcome=None,
                description="",
            )
        tasks_text = format_task_drafts([
            type("DraftView", (), {"task_name": t["task_name"], "duration_minutes": t["duration_minutes"], "description": t.get("description") or ""})()
            for t in plan_tasks
        ])

        historical_view = bool(historical_view)
        form_date_value = html.escape(target_date.isoformat())
        dh = f'<input type="hidden" name="date" value="{form_date_value}" />'
        vh = '<input type="hidden" name="view" value="historical" />' if historical_view else ""

        daemon_online = "error" not in daemon and not daemon.get("bootstrap_error")
        daemon_dot = "dot--on" if daemon_online else "dot--off"

        banner_html = self._render_banner_fragment(message, daemon, historical_view, target_date)
        hero_html = self._render_hero_fragment(target_date, payload, metrics)
        actions_html = self._render_actions_fragment(target_date, historical_view, payload)
        sched_html = self._render_schedule_fragment(target_date, payload, historical_view)
        metrics_html = self._render_metrics_fragment(target_date, payload)
        task_metrics_html = self._render_task_metrics_fragment(target_date, metrics)

        planner_open = "" if plan["plan_exists"] else " open"
        planner_date_html = (
            f'<span class="plan__date-val">{html.escape(target_date.strftime("%d %b %Y"))}</span>{dh}'
            if not historical_view
            else f'<input type="date" name="date" value="{form_date_value}" class="plan__date-input" />{vh}'
        )

        nav_toggle = (
            '<a href="/history" class="nav__btn">History</a>'
            if not historical_view
            else '<a href="/" class="nav__btn nav__btn--accent">Today</a>'
        )

        return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Locked-In</title>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700;800&family=Outfit:wg@400;500;600;700;800;900&display=swap" rel="stylesheet"/>
<style>
:root {{
    color-scheme:dark;
    --bg:#06070a;--s1:#0c0e14;--s2:#12151d;--s3:#191d28;
    --b1:#1a1f2e;--b2:#252b3d;
    --tx:#ccc8be;--txh:#eae6dc;--dim:#585e72;
    --grn:#2fac6a;--grnh:#44d88a;--grnbg:rgba(47,172,106,.08);--grnb:rgba(47,172,106,.22);
    --amb:#d4a039;--ambh:#eab94e;--ambbg:rgba(212,160,57,.07);--ambb:rgba(212,160,57,.18);
    --red:#c04040;--redh:#e55;--redbg:rgba(192,64,64,.08);--redb:rgba(192,64,64,.22);
    --blu:#4488bb;--blubg:rgba(68,136,187,.08);--blub:rgba(68,136,187,.22);
    --mono:'JetBrains Mono',monospace;--sans:'Outfit',system-ui,sans-serif;
    --r:6px;--rl:10px;
}}
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:var(--sans);background:var(--bg);color:var(--tx);line-height:1.5;-webkit-font-smoothing:antialiased}}
.shell{{max-width:860px;margin:0 auto;padding:20px 16px 80px}}
form{{margin:0;display:inline}}

/* NAV */
.nav{{display:flex;align-items:center;justify-content:space-between;padding:12px 0 16px;border-bottom:1px solid var(--b1);margin-bottom:20px}}
.nav__brand{{font-family:var(--mono);font-size:13px;font-weight:700;color:var(--amb);letter-spacing:.08em;text-transform:uppercase}}
.nav__r{{display:flex;align-items:center;gap:10px}}
.nav__btn{{appearance:none;background:var(--s2);border:1px solid var(--b1);color:var(--dim);font-family:var(--mono);font-size:11px;font-weight:500;padding:5px 12px;border-radius:var(--r);cursor:pointer;transition:.15s;text-decoration:none}}
.nav__btn:hover{{background:var(--s3);color:var(--tx);border-color:var(--b2)}}
.nav__btn--accent{{color:var(--amb);border-color:var(--ambb)}}
.dot{{width:7px;height:7px;border-radius:50%;display:inline-block}}
.dot--on{{background:var(--grnh);box-shadow:0 0 6px var(--grn)}}
.dot--off{{background:var(--red);box-shadow:0 0 6px rgba(192,64,64,.4)}}
.clock{{font-family:var(--mono);font-size:12px;color:var(--dim);letter-spacing:.04em}}

/* BANNER */
.ban{{font-family:var(--mono);font-size:12px;padding:8px 14px;border-radius:var(--r);margin-bottom:12px;border:1px solid var(--ambb);background:var(--ambbg);color:var(--ambh)}}
.ban--err{{border-color:var(--redb);background:var(--redbg);color:var(--redh)}}
.ban--info{{border-color:var(--blub);background:var(--blubg);color:var(--blu)}}

/* HERO */
.hero{{background:var(--s1);border:1px solid var(--b1);border-radius:var(--rl);padding:28px 32px;margin-bottom:16px;position:relative;overflow:hidden}}
.hero::before{{content:'';position:absolute;top:0;left:0;right:0;height:2px}}
.hero--running::before{{background:linear-gradient(90deg,var(--grn),var(--grnh),transparent 60%)}}
.hero--paused::before{{background:linear-gradient(90deg,var(--amb),var(--ambh),transparent 60%)}}
.hero--pending::before{{background:linear-gradient(90deg,var(--b2),transparent 40%)}}
.hero--idle::before{{background:none}}
.hero--paused{{border-color:var(--ambb)}}
.hero__top{{display:flex;align-items:center;gap:12px;margin-bottom:8px}}
.tag{{font-family:var(--mono);font-size:10px;font-weight:700;letter-spacing:.1em;padding:3px 8px;border-radius:4px}}
.tag--running{{background:var(--grnbg);color:var(--grnh);border:1px solid var(--grnb)}}
.tag--paused{{background:var(--ambbg);color:var(--ambh);border:1px solid var(--ambb);animation:pulse 2s ease-in-out infinite}}
.tag--pending{{background:var(--s2);color:var(--dim);border:1px solid var(--b1)}}
.tag--idle{{background:var(--s2);color:var(--dim);border:1px solid var(--b1)}}
.tag--dim{{background:var(--s2);color:var(--dim);border:none;font-size:9px}}
.tag--amber{{background:var(--ambbg);color:var(--ambh);border:none;font-size:10px}}
.hero__meta{{font-family:var(--mono);font-size:12px;color:var(--dim)}}
.hero__name{{font-size:32px;font-weight:800;letter-spacing:-.02em;color:var(--txh);line-height:1.15;margin-bottom:12px}}
.hero--idle .hero__name{{color:var(--dim);font-size:24px;font-weight:600}}
.hero__detail{{font-family:var(--mono);font-size:13px;color:var(--dim);margin-bottom:14px}}
.hero__detail--paused{{color:var(--ambh)}}
.hero__timer{{color:var(--grnh);font-weight:700;font-size:15px}}
.hero__pause-icon{{font-size:11px;margin-right:4px}}
.hero__bar{{display:flex;align-items:center;gap:16px}}
.hero__prog{{flex:1;height:4px;background:var(--s3);border-radius:2px;overflow:hidden}}
.hero__prog-fill{{height:100%;border-radius:2px;background:linear-gradient(90deg,var(--grn),var(--grnh));transition:width .4s}}
.hero__prog-label{{font-family:var(--mono);font-size:12px;font-weight:700;color:var(--tx);white-space:nowrap}}
.hero__next{{display:flex;align-items:center;gap:8px;margin-top:14px;padding-top:12px;border-top:1px solid var(--b1)}}
.hero__next-name{{font-weight:600;font-size:14px;color:var(--tx)}}
.hero__next-time{{font-family:var(--mono);font-size:12px;color:var(--dim);margin-left:auto}}
@keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:.5}}}}

/* ACTIONS */
.actions{{display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap}}
.act{{appearance:none;font-family:var(--mono);font-size:12px;font-weight:700;letter-spacing:.03em;padding:10px 20px;border-radius:var(--r);cursor:pointer;transition:.15s;border:1px solid}}
.act--start{{background:var(--grn);border-color:var(--grn);color:#080a0c}}
.act--start:hover{{background:var(--grnh)}}
.act--pause{{background:var(--ambbg);border-color:var(--ambb);color:var(--ambh)}}
.act--pause:hover{{background:rgba(212,160,57,.14)}}
.act--resume{{background:var(--grn);border-color:var(--grn);color:#080a0c}}
.act--resume:hover{{background:var(--grnh)}}
.act--extend{{background:var(--ambbg);border-color:var(--ambb);color:var(--ambh)}}
.act--extend:hover{{background:rgba(212,160,57,.14)}}
.act--finish{{background:var(--s2);border-color:var(--b2);color:var(--tx)}}
.act--finish:hover{{background:var(--s3);border-color:var(--dim)}}
.act-form{{display:flex;flex-direction:column;gap:6px}}
.act-notes{{font-family:var(--mono);font-size:11px;padding:6px 10px;border-radius:var(--r);border:1px solid var(--b2);background:var(--s2);color:var(--tx);resize:vertical;min-height:36px;width:100%}}
.act-notes:focus{{outline:none;border-color:var(--ambb)}}
.act-notes::placeholder{{color:var(--dim);opacity:.6}}

/* SCHEDULE */
.panel{{background:var(--s1);border:1px solid var(--b1);border-radius:var(--rl);overflow:hidden;margin-bottom:16px}}
.panel__head{{display:flex;align-items:center;justify-content:space-between;padding:12px 16px;border-bottom:1px solid var(--b1)}}
.panel__title{{font-family:var(--mono);font-size:10px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--dim)}}
.panel__badge{{font-family:var(--mono);font-size:10px;color:var(--dim);background:var(--s2);padding:2px 7px;border-radius:4px}}
.sc{{display:grid;grid-template-columns:90px 1fr auto auto;gap:10px;align-items:center;padding:10px 16px;border-bottom:1px solid var(--b1);transition:.1s;position:relative}}
.sc:last-child{{border-bottom:none}}
.sc--done{{opacity:.4}}
.sc--active{{background:var(--grnbg);border-left:3px solid var(--grn)}}
.sc--pending{{}}
.sc__time{{font-family:var(--mono);font-size:12px;color:var(--dim);white-space:nowrap}}
.sc__sep{{margin:0 3px;opacity:.4}}
.sc__body{{min-width:0}}
.sc__name{{font-weight:600;font-size:13px;color:var(--tx);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.sc--done .sc__name{{text-decoration:line-through;color:var(--dim)}}
.sc__link{{color:inherit;text-decoration:none;transition:.15s;display:block;width:100%}}
.sc__link::after{{content:'';position:absolute;top:0;left:0;right:0;bottom:0;z-index:1}}
.sc__link:hover{{color:var(--ambh)}}
.sc__work{{font-family:var(--mono);font-size:11px;color:var(--grnh);font-weight:600}}
.sc__est{{font-family:var(--mono);font-size:11px;color:var(--dim);text-align:right}}
.sc__act{{display:flex;align-items:center;gap:2px;position:relative;z-index:2}}
.sc__del{{appearance:none;border:none;background:none;color:var(--dim);font-size:16px;cursor:pointer;padding:2px 6px;border-radius:3px;transition:.15s;line-height:1}}
.sc__del:hover{{color:var(--redh);background:var(--redbg)}}
.empty{{padding:24px 16px;text-align:center;font-size:13px;color:var(--dim)}}

/* METRICS BAR */
.mbar{{display:flex;gap:1px;background:var(--b1);border-radius:var(--rl);overflow:hidden;margin-bottom:16px}}
.mbar__cell{{flex:1;background:var(--s1);padding:14px 16px;text-align:center}}
.mbar__val{{font-family:var(--mono);font-size:22px;font-weight:800;color:var(--txh);line-height:1;margin-bottom:3px}}
.mbar__lbl{{font-family:var(--mono);font-size:9px;font-weight:600;letter-spacing:.1em;text-transform:uppercase;color:var(--dim)}}

/* TASK METRICS */
.tm{{display:flex;align-items:center;gap:10px;padding:8px 16px;border-bottom:1px solid var(--b1);font-size:12px;position:relative}}
.tm:last-child{{border-bottom:none}}
.tm__name{{flex:1;font-weight:600;color:var(--tx);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.tm__val{{font-family:var(--mono);color:var(--dim);white-space:nowrap}}
.tm__d{{font-family:var(--mono);font-weight:700;padding:1px 6px;border-radius:3px;white-space:nowrap}}
.tm__d--over{{background:var(--redbg);color:var(--redh)}}
.tm__d--under{{background:var(--grnbg);color:var(--grnh)}}
.tm__d--on{{background:var(--s3);color:var(--dim)}}

/* PLANNER */
details.planner>summary{{font-family:var(--mono);font-size:11px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--dim);cursor:pointer;padding:12px 16px;list-style:none;display:flex;align-items:center;justify-content:space-between}}
details.planner>summary::after{{content:'\\25B6';font-size:9px;transition:transform .2s}}
details.planner[open]>summary::after{{transform:rotate(90deg)}}
details.planner>summary::-webkit-details-marker{{display:none}}
.plan__date-val{{font-family:var(--mono);font-size:14px;font-weight:700;color:var(--txh)}}
.plan__date-input{{font-family:var(--mono);font-size:13px;background:var(--s2);border:1px solid var(--b1);color:var(--tx);padding:6px 10px;border-radius:var(--r)}}
.task-editor{{display:grid;gap:5px}}
.task-row{{display:grid;grid-template-columns:28px 1fr 70px auto auto;gap:6px;align-items:center;padding:6px 10px;background:var(--s2);border:1px solid var(--b1);border-radius:var(--r)}}
.task-row:focus-within{{border-color:var(--ambb)}}
.task-row.done{{border-color:var(--grnb);opacity:.5}}
.task-index{{font-family:var(--mono);font-size:11px;font-weight:700;color:var(--dim);text-align:center}}
.task-fields{{display:grid;grid-template-columns:1fr 65px;gap:6px}}
.task-fields input[type="text"],.task-fields input[type="number"]{{background:var(--s1);border:1px solid var(--b1);color:var(--tx);padding:6px 8px;border-radius:var(--r);font-family:var(--sans);font-size:12px;width:100%}}
.task-fields input:focus{{outline:none;border-color:var(--ambb)}}
.task-desc{{grid-column:1/-1;background:var(--s1)!important;border:1px solid var(--b1);color:var(--dim);padding:4px 8px!important;border-radius:var(--r);font-size:11px!important}}
.task-meta{{display:flex;align-items:center;gap:4px}}
.pill{{font-family:var(--mono);font-size:9px;font-weight:700;letter-spacing:.06em;padding:2px 6px;border-radius:3px}}
.pill.done{{background:var(--grnbg);color:var(--grnh)}}
.pill.pending{{background:var(--ambbg);color:var(--ambh)}}
.task-hint{{display:none}}
.task-delete{{display:flex;align-items:center;gap:3px;font-family:var(--mono);font-size:10px;color:var(--dim);cursor:pointer;white-space:nowrap}}
.task-delete input[type="checkbox"]{{accent-color:var(--red)}}
textarea{{width:100%;min-height:120px;background:var(--s2);border:1px solid var(--b1);color:var(--tx);padding:10px;border-radius:var(--r);font-family:var(--mono);font-size:12px;line-height:1.6;resize:vertical;margin-top:6px}}
textarea:focus{{outline:none;border-color:var(--ambb)}}
details.raw-import{{margin-top:8px}}
details.raw-import summary{{font-family:var(--mono);font-size:11px;color:var(--amb);cursor:pointer;padding:4px 0}}
.btn{{appearance:none;font-family:var(--mono);font-size:11px;font-weight:700;padding:8px 14px;border-radius:var(--r);border:1px solid var(--b1);background:var(--s2);color:var(--tx);cursor:pointer;transition:.15s}}
.btn:hover{{background:var(--s3);border-color:var(--b2)}}
.btn--primary{{background:var(--amb);border-color:var(--amb);color:#0a0a0a}}
.btn--primary:hover{{background:var(--ambh)}}
.btn--green{{border-color:var(--grnb);color:var(--grnh)}}
.btn--green:hover{{background:var(--grnbg)}}
.btn--ghost{{border-color:transparent;background:transparent;color:var(--dim)}}
.btn--ghost:hover{{color:var(--tx);background:var(--s2)}}
.btn--red{{border-color:var(--redb);color:var(--redh)}}
.btn--red:hover{{background:var(--redbg)}}

/* FOOTER */
.foot{{display:flex;align-items:center;justify-content:space-between;padding:12px 0;margin-top:8px;border-top:1px solid var(--b1)}}
.foot__l,.foot__r{{display:flex;gap:8px;align-items:center}}

/* RESPONSIVE */
@media(max-width:640px){{
    .shell{{padding:12px 10px 60px}}
    .hero{{padding:20px 18px}}
    .hero__name{{font-size:24px}}
    .sc{{grid-template-columns:70px 1fr auto}}
    .mbar{{flex-wrap:wrap}}
    .mbar__cell{{min-width:calc(50% - 1px)}}
    .task-row{{grid-template-columns:1fr;gap:4px}}
    .task-index{{display:none}}
    .actions{{flex-direction:column}}
    .act{{width:100%;text-align:center}}
}}
</style>
</head>
<body>
<div class="shell">
<nav class="nav">
    <div class="nav__brand">Locked-In</div>
    <div class="nav__r">
        <span class="clock" id="clock"></span>
        <span class="dot {html.escape(daemon_dot)}"></span>
        <form method="get" action="/">{dh}{vh}<button class="nav__btn" type="submit">&#8635;</button></form>
        {nav_toggle}
        <a href="/settings" class="nav__btn">&#9881; Settings</a>
    </div>
</nav>

{f'<div id="banner-section">{banner_html}</div>' if banner_html else '<div id="banner-section"></div>'}

<div id="hero-section">{hero_html}</div>

{f'<div id="actions-section">{actions_html}</div>' if actions_html else ''}

<div id="schedule-section">{sched_html}</div>

<div id="metrics-section">{metrics_html}</div>

{f'<div id="task-metrics-section">{task_metrics_html}</div>' if task_metrics_html else ''}

<details class="planner panel"{planner_open}>
    <summary>Planner &mdash; {html.escape(target_date.strftime("%d %b %Y"))}</summary>
    <div style="padding:14px 16px">
        <form method="post" action="/plan">
            <div style="margin-bottom:10px">{planner_date_html}</div>
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
                <span class="panel__title" style="margin:0">Tasks</span>
                <button class="btn btn--ghost" type="button" id="add-task-row">+ Add</button>
            </div>
            <div id="task-editor" class="task-editor">{editor_rows_html}</div>
            <template id="task-row-template">{editor_template_html}</template>
            <details class="raw-import">
                <summary>Raw text import</summary>
                <textarea name="tasks" spellcheck="false" placeholder="Task name - 30">{html.escape(tasks_text)}</textarea>
            </details>
            <div style="display:flex;gap:6px;margin-top:12px">
                <button class="btn btn--primary" type="submit" name="intent" value="save">Save</button>
                <button class="btn btn--green" type="submit" name="intent" value="save_start">Save + Start</button>
            </div>
        </form>
    </div>
</details>

<div class="foot">
    <div class="foot__l">
        <form method="post" action="/day/reset" onsubmit="return confirm('Reset entire day?')">{dh}{vh}<button class="btn btn--red" type="submit">Reset Day</button></form>
    </div>
    <div class="foot__r">
        <span style="font-family:var(--mono);font-size:10px;color:var(--dim)">{html.escape(target_date.isoformat())}</span>
    </div>
</div>

</div>
<script>
(()=>{{
    const c=document.getElementById("clock");
    if(c){{const t=()=>{{c.textContent=new Date().toLocaleTimeString("en-GB",{{hour:"2-digit",minute:"2-digit",second:"2-digit"}})}};t();setInterval(t,1000)}}

    const e=document.getElementById("task-editor"),tpl=document.getElementById("task-row-template"),ab=document.getElementById("add-task-row");
    if(e&&tpl&&ab)ab.addEventListener("click",()=>{{const i=e.querySelectorAll(".task-row").length,w=document.createElement("div");w.innerHTML=tpl.innerHTML.replaceAll("__INDEX__",String(i)).replaceAll("__DISPLAY__",String(i+1)).trim();const r=w.firstElementChild;if(!r)return;e.appendChild(r);const n=r.querySelector(`input[name="task_name_${{i}}"]`);if(n)n.focus()}});

    const wt=document.getElementById("work-timer");
    if(wt){{const s=new Date(wt.dataset.started).getTime(),pa=parseInt(wt.dataset.pauseAcc||"0")*1000;
    setInterval(()=>{{const d=Date.now()-s-pa;const m=Math.max(0,Math.floor(d/60000));wt.textContent=m+"m"}},5000)}}

    // Fragment interchange: intercept forms with data-fragment
    document.addEventListener('submit', async (e) => {{
        const form = e.target;
        if (!form.dataset.fragment) return;
        e.preventDefault();
        const body = new FormData(form);
        body.set('fragment', '1');
        try {{
            const resp = await fetch(form.action, {{ method: 'POST', body }});
            const fragments = await resp.json();
            for (const [id, html] of Object.entries(fragments)) {{
                const el = document.getElementById(id + '-section');
                if (el) el.outerHTML = html;
            }}
        }} catch (err) {{
            console.error('Fragment update failed:', err);
        }}
    }});
}})();
</script>
</body>
</html>"""
