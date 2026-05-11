from __future__ import annotations

import calendar as cal_mod
import html
import json
import logging
import re
import statistics
from datetime import date, datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .control_client import send_command
from .planning import format_task_drafts, parse_task_drafts
from .simple_store import DEFAULT_TASK_DURATION_MINUTES, EditableTaskDraft, SimpleTodoStore, TaskRuntime
from .metrics import summarize_day, summarize_range

log = logging.getLogger(__name__)


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
        
        # Initialize Jinja2
        template_dir = Path(__file__).parent / "templates"
        self.jinja_env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            autoescape=select_autoescape(['html', 'xml'])
        )

        from .idle_detector import IdleDetector
        self._idle_detector = IdleDetector()

    def _render(self, template_name: str, **kwargs) -> str:
        template = self.jinja_env.get_template(template_name)
        return template.render(**kwargs)

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
                parsed = urlparse(self.path); form = self._read_form()
                view_mode = form.get("view", "")

                if parsed.path == "/backup":
                    result = frontend._run_backup()
                    self._send_json(result, include_body=True)
                    return

                if parsed.path == "/calibrate":
                    stage = form.get("stage", "idle"); duration = int(form.get("duration", "30"))
                    deltas = frontend._idle_detector.capture_deltas(duration)
                    if stage == "idle":
                        noise = {name: max(vals) if vals else 0 for name, vals in deltas.items()}
                        self._send_json({"status": "idle_recorded", "noise": noise}, include_body=True)
                    else:
                        sig = {name: int(statistics.median(vals)) if vals else 0 for name, vals in deltas.items()}
                        self._send_json({"status": "active_recorded", "signal": sig}, include_body=True)
                    return

                if parsed.path == "/calibrate/apply":
                    soft = json.loads(form.get("soft", "{}")); hard = json.loads(form.get("hard", "{}"))
                    for name, val in soft.items(): frontend._update_config_value("auto_pause", f"soft_threshold_{name}", str(val))
                    for name, val in hard.items(): frontend._update_config_value("auto_pause", f"hard_threshold_{name}", str(val))
                    import subprocess
                    try:
                        subprocess.run(["systemctl", "--user", "restart", "locked-in.service"], check=True)
                        self._send_json({"status": "success"}, include_body=True)
                    except: self._send_json({"status": "error"}, include_body=True)
                    return

                if parsed.path == "/run/pause":
                    result = frontend._pause_current_from_form(form)
                    if form.get("fragment") == "1":
                        self._send_json(frontend._render_dashboard_fragments(frontend._target_date_from_form(form)), include_body=True)
                    else: self._redirect("/", frontend._target_date_from_form(form), frontend._message_from_result(result), view_mode)
                    return

                if parsed.path == "/run/resume":
                    result = frontend._resume_current_from_form(form)
                    if form.get("fragment") == "1":
                        self._send_json(frontend._render_dashboard_fragments(frontend._target_date_from_form(form)), include_body=True)
                    else: self._redirect("/", frontend._target_date_from_form(form), frontend._message_from_result(result), view_mode)
                    return

                if parsed.path == "/run/extend":
                    result = frontend._extend_current_from_form(form)
                    if form.get("fragment") == "1":
                        self._send_json(frontend._render_dashboard_fragments(frontend._target_date_from_form(form)), include_body=True)
                    else: self._redirect("/", frontend._target_date_from_form(form), frontend._message_from_result(result), view_mode)
                    return

                if parsed.path in {"/pause", "/resume", "/give-up"}:
                    result = frontend._command(parsed.path.removeprefix("/"))
                    if form.get("fragment") == "1":
                        self._send_json(frontend._render_dashboard_fragments(frontend._target_date_from_form(form)), include_body=True)
                    else: self._redirect("/", frontend._target_date_from_form(form), frontend._message_from_result(result), view_mode)
                    return

                if parsed.path == "/run/start-current":
                    result = frontend._start_current_from_form(form)
                    if form.get("fragment") == "1":
                        self._send_json(frontend._render_dashboard_fragments(frontend._target_date_from_form(form)), include_body=True)
                    else: self._redirect("/", frontend._target_date_from_form(form), frontend._message_from_result(result), view_mode)
                    return

                if parsed.path == "/run/finish-current":
                    result = frontend._finish_current_from_form(form)
                    if form.get("fragment") == "1":
                        self._send_json(frontend._render_dashboard_fragments(frontend._target_date_from_form(form)), include_body=True)
                    else: self._redirect("/", frontend._target_date_from_form(form), frontend._message_from_result(result), view_mode)
                    return

                if parsed.path == "/day/reset":
                    result = frontend._reset_day_from_form(form)
                    self._redirect("/", frontend._target_date_from_form(form), frontend._message_from_result(result), view_mode)
                    return

                if parsed.path == "/plan":
                    result = frontend._save_plan_from_form(form)
                    self._redirect("/", frontend._target_date_from_form(form), frontend._message_from_result(result), view_mode)
                    return

                if parsed.path == "/task/delete":
                    result = frontend._delete_task_from_form(form)
                    self._redirect("/", frontend._target_date_from_form(form), frontend._message_from_result(result), view_mode)
                    return

                if parsed.path == "/task/edit":
                    result = frontend._edit_task_from_form(form)
                    if form.get("fragment") == "1":
                        self._send_json(frontend._render_dashboard_fragments(frontend._target_date_from_form(form)), include_body=True)
                    else:
                        target_path = form.get("redirect_to") or "/"
                        self._redirect(target_path, frontend._target_date_from_form(form), frontend._message_from_result(result), view_mode)
                    return

                if parsed.path == "/task/move":
                    result = frontend._move_task_from_form(form)
                    if form.get("fragment") == "1":
                        self._send_json(frontend._render_dashboard_fragments(frontend._target_date_from_form(form)), include_body=True)
                    else:
                        self._redirect("/", frontend._target_date_from_form(form), frontend._message_from_result(result), view_mode)
                    return

                if parsed.path == "/session/start":
                    result = frontend._start_session_from_form(form)
                    self._redirect("/", frontend._target_date_from_form(form), frontend._message_from_result(result), view_mode)
                    return

                if parsed.path == "/settings":
                    result = frontend._save_settings_from_form(form)
                    self._send_html(frontend._render_settings_page(result.get("error") or result.get("status", "")), include_body=True)
                    return

                if parsed.path == "/task/notes":
                    target_date = frontend._target_date_from_form(form); task_id = int(form.get("task_id", "0") or "0")
                    frontend.store.update_task_run_notes(task_id, form.get("notes", ""))
                    if form.get("fragment") == "1":
                        detail = frontend.store.get_task_detail(task_id)
                        self._send_json({"notes": frontend._render_notes_fragment(detail)}, include_body=True)
                    else: self._redirect(f"/task/{task_id}", target_date, "Notes saved")
                    return

                self.send_error(HTTPStatus.NOT_FOUND)

            def _dispatch(self, include_body: bool) -> None:
                parsed = urlparse(self.path); query = parse_qs(parsed.query)
                if parsed.path == "/":
                    t = frontend._page_target_date_from_query(query)
                    self._send_html(frontend._render_page(t, query.get("msg", [""])[0], frontend._is_historical_view(query)), include_body)
                    return
                if parsed.path == "/fragments/dashboard":
                    self._send_json(frontend._render_dashboard_fragments(frontend._target_date_from_query(query)), include_body)
                    return
                task_detail_fragment_match = re.match(r"^/fragments/task-detail/(\d+)$", parsed.path)
                if task_detail_fragment_match:
                    self._send_html(frontend._render_task_detail_fragment(int(task_detail_fragment_match.group(1))), include_body)
                    return
                if parsed.path == "/settings":
                    self._send_html(frontend._render_settings_page(), include_body); return
                task_match = re.match(r"^/task/(\d+)$", parsed.path)
                if task_match:
                    self._send_html(frontend._render_task_detail_page(int(task_match.group(1))), include_body); return
                if parsed.path == "/history":
                    y = int(query.get("year", [str(date.today().year)])[0]); m = int(query.get("month", [str(date.today().month)])[0])
                    self._send_html(frontend._render_history_page(y, m), include_body); return
                self.send_error(HTTPStatus.NOT_FOUND)

            def _read_form(self) -> dict[str, str]:
                length = int(self.headers.get("Content-Length", "0") or "0")
                raw = self.rfile.read(length).decode("utf-8") if length else ""
                form = parse_qs(raw, keep_blank_values=True)
                return {key: values[0] if values else "" for key, values in form.items()}

            def _send_html(self, body: str, include_body: bool) -> None:
                encoded = body.encode("utf-8"); self.send_response(HTTPStatus.OK); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(encoded))); self.end_headers()
                if include_body: self.wfile.write(encoded)

            def _send_json(self, payload: dict, include_body: bool) -> None:
                encoded = json.dumps(payload, indent=2).encode("utf-8"); self.send_response(HTTPStatus.OK); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(encoded))); self.end_headers()
                if include_body: self.wfile.write(encoded)

            def _redirect(self, path: str, target_date: date, message: str, view_mode: str = "") -> None:
                params = {}
                if view_mode == "historical": params["view"] = "historical"; params["date"] = target_date.isoformat()
                if message: params["msg"] = message
                location = f"{path}?{urlencode(params)}" if params else path
                self.send_response(HTTPStatus.SEE_OTHER); self.send_header("Location", location); self.send_header("Content-Length", "0"); self.end_headers()

        server = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        try:
            print(f"Locked-In web dashboard running at http://127.0.0.1:{self.port}")
            server.serve_forever(); return 0
        except KeyboardInterrupt: return 0
        finally: server.server_close()

    def _target_date_from_query(self, query: dict[str, list[str]]) -> date:
        return self._parse_target_date(query.get("date", [""])[0])

    def _is_historical_view(self, query: dict[str, list[str]]) -> bool:
        return query.get("view", [""])[0] == "historical"

    def _page_target_date_from_query(self, query: dict[str, list[str]]) -> date:
        if not self._is_historical_view(query): return date.today()
        val = query.get("date", [""])[0]
        if val: return self._parse_target_date(val)
        return self.store.get_latest_plan_date(before=date.today()) or date.today()

    def _target_date_from_form(self, form: dict[str, str]) -> date:
        return self._parse_target_date(form.get("date", ""))

    def _parse_target_date(self, value: str) -> date:
        if not value: return date.today()
        return date.fromisoformat(value)

    def _metrics_payload(self, target_date: date) -> dict:
        return summarize_day(self.store, target_date)

    def _status_payload(self, target_date: date) -> dict:
        daemon_status = send_command(self.socket_path, {"command": "status"})
        plan_state = self._plan_payload(target_date)
        return {"target_date": target_date.isoformat(), "daemon": daemon_status, "plan": plan_state}

    def _plan_payload(self, target_date: date) -> dict:
        plan = self.store.get_plan(target_date); runtime = self.store.get_active_task_runtime(target_date)
        runtime_entries = self.store.project_runtime_schedule(target_date)
        pending_entries = [e for e in runtime_entries if e.status in ("pending", "running", "paused")]
        runtime_payload = None
        if runtime:
            now = datetime.now(); eta = runtime.compute_eta(now)
            runtime_payload = {"id": runtime.id, "plan_task_id": runtime.plan_task_id, "status": runtime.status, "started_at": runtime.started_at, "paused_at": runtime.paused_at, "estimated_seconds": runtime.estimated_seconds, "accumulated_pause_seconds": runtime.accumulated_pause_seconds, "actual_work_seconds": runtime.actual_work_seconds(now), "eta": eta.isoformat(timespec="seconds")}
        return {
            "target_date": target_date.isoformat(), "plan_exists": bool(plan and plan.tasks), "task_count": len(plan.tasks) if plan else 0, "completed_count": sum(1 for task in plan.tasks if task.completed_at) if plan else 0,
            "task_runtime": runtime_payload,
            "tasks": [{"id": t.id, "task_name": t.task_name, "duration_minutes": t.duration_minutes, "completed_at": t.completed_at, "last_outcome": t.last_outcome, "description": t.description} for t in (plan.tasks if plan else [])],
            "schedule": [{"task_id": e.task_id, "task_name": e.task_name, "status": e.status, "projected_start": e.projected_start, "projected_end": e.projected_end, "actual_start": e.actual_start, "actual_end": e.actual_end, "eta": e.eta, "duration_minutes": e.estimated_seconds // 60, "actual_work_seconds": e.actual_work_seconds, "pause_seconds": e.pause_seconds} for e in runtime_entries],
            "current_entry": self._runtime_entry_payload(pending_entries[0]) if pending_entries else None,
            "next_entry": self._runtime_entry_payload(pending_entries[1]) if len(pending_entries) > 1 else None,
        }

    def _runtime_entry_payload(self, entry) -> dict:
        return {"task_id": entry.task_id, "task_name": entry.task_name, "status": entry.status, "projected_start": entry.projected_start, "projected_end": entry.projected_end, "actual_start": entry.actual_start, "eta": entry.eta, "duration_minutes": entry.estimated_seconds // 60}

    def _read_config_values(self) -> dict[str, str]:
        if not self.config_path or not Path(self.config_path).exists(): return {}
        import sys
        if sys.version_info >= (3, 11): import tomllib
        else: import tomli as tomllib
        return tomllib.loads(Path(self.config_path).read_text(encoding="utf-8"))

    def _update_config_value(self, section: str, key: str, value: str) -> None:
        if not self.config_path: return
        path = Path(self.config_path); lines = path.read_text(encoding="utf-8").splitlines()
        in_section = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]"): in_section = stripped == f"[{section}]"; continue
            if in_section and "=" in stripped:
                if stripped.split("=", 1)[0].strip() == key:
                    lines[i] = f"{key} = {value}"; path.write_text("\n".join(lines) + "\n", encoding="utf-8"); return
        for i, line in enumerate(lines):
            if line.strip() == f"[{section}]": lines.insert(i + 1, f"{key} = {value}"); path.write_text("\n".join(lines) + "\n", encoding="utf-8"); return
        lines.append(f"\n[{section}]"); lines.append(f"{key} = {value}"); path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _save_settings_from_form(self, form: dict[str, str]) -> dict:
        if not self.config_path: return {"error": "No config file found."}
        try:
            fields = {
                ("stretch_lockout", "enabled"): ("bool", None, None),
                ("stretch_lockout", "interval_minutes"): ("int", 1, 480),
                ("stretch_lockout", "duration_minutes"): ("int", 1, 60),
                ("schedule", "hard_shutdown_time"): ("time", None, None), ("schedule", "shutdown_warning_minutes"): ("int", 0, 120),
                ("schedule", "hard_shutdown_enabled"): ("bool", None, None), ("warden", "task_start_grace_seconds"): ("int", 0, 3600),
                ("warden", "default_extend_minutes"): ("int", 0, 120), ("warden", "give_up_cooldown_seconds"): ("int", 0, 3600),
                ("auto_pause", "idle_pause_seconds"): ("int", 0, 3600), ("auto_pause", "idle_resume_grace_seconds"): ("int", 1, 30),
                ("backup", "enabled"): ("bool", None, None), ("backup", "path"): ("path", None, None),
            }
            for (section, key), (typ, lo, hi) in fields.items():
                form_key = f"{section}__{key}"; raw = form.get(form_key, "").strip()
                if not raw and typ != "bool": continue
                if typ == "int":
                    val = int(raw); 
                    if (lo is not None and val < lo) or (hi is not None and val > hi): return {"error": f"{key} out of range."}
                    self._update_config_value(section, key, str(val))
                elif typ == "bool":
                    val = form_key in form and raw in {"on", "true", "1", "yes"}
                    self._update_config_value(section, key, "true" if val else "false")
                elif typ == "time":
                    if not re.match(r"^\d{1,2}:\d{2}$", raw): return {"error": f"Invalid time format for {key}."}
                    self._update_config_value(section, key, f'"{raw}"')
                elif typ == "path":
                    self._update_config_value(section, key, f'"{raw}"')
            self._toggle_hypr_auto_open("open_dashboard_on_login" in form and form.get("open_dashboard_on_login", "").strip() in {"on", "true", "1", "yes"})
            import subprocess
            try: subprocess.run(["systemctl", "--user", "restart", "locked-in.service"], check=True); return {"status": "Settings saved and daemon restarted."}
            except Exception as e: return {"status": "Settings saved. Manual restart required: " + str(e)}
        except Exception as e: return {"error": str(e)}

    def _is_hypr_auto_open_enabled(self) -> bool:
        p = Path("~/.config/hypr/autostart.conf").expanduser()
        if not p.exists(): return False
        t = p.read_text(); m = "exec-once = sleep 5 && xdg-open http://localhost:8765"; c = "# " + m
        return m in t and c not in t

    def _toggle_hypr_auto_open(self, enable: bool) -> None:
        p = Path("~/.config/hypr/autostart.conf").expanduser()
        if not p.exists(): return
        t = p.read_text(); m = "exec-once = sleep 5 && xdg-open http://localhost:8765"; c = "# " + m
        if enable:
            if c in t: t = t.replace(c, m)
            elif m not in t: t = t.rstrip() + "\n\n# Open Locked-In dashboard\n" + m + "\n"
        else:
            if m in t and c not in t: t = t.replace(m, c)
        p.write_text(t)

    def _render_history_page(self, year: int, month: int) -> str:
        today = date.today(); first_of_month = date(year, month, 1); last_of_month = date(year, month, cal_mod.monthrange(year, month)[1])
        plan_dates = set(self.store.get_plan_dates_range(first_of_month, last_of_month))
        summaries = {d: self.store.get_day_summary(date.fromisoformat(d)) for d in plan_dates}
        next_year_limit = today.replace(year=today.year + 1)
        cal_days = []
        for _ in range(first_of_month.weekday()): cal_days.append({"num": None})
        for d_num in range(1, last_of_month.day + 1):
            d = date(year, month, d_num); d_str = d.isoformat(); summary = summaries.get(d_str)
            cal_days.append({"num": d_num, "date": d_str, "is_today": d_str == today.isoformat(), "has_plan": d_str in plan_dates, "can_link": d <= next_year_limit, "label": f"{summary['task_count']}T {summary['completed_count']}D" if summary else ""})
        
        ctx = self._get_nav_context(today, "history")
        ctx.update({
            "current_year": year,
            "current_month": month,
            "years": list(range(today.year - 2, today.year + 2)),
            "months": [{"value": m, "name": date(2000, m, 1).strftime("%b")} for m in range(1, 13)],
            "weekdays": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
            "cal_days": cal_days
        })
        return self._render("history.html", **ctx)

    def _render_dashboard_fragments(self, target_date: date, message: str = "", historical_view: bool = False) -> dict[str, str]:
        payload = self._status_payload(target_date); metrics = self._metrics_payload(target_date)
        return {
            "banner": self._render_banner_fragment(message, payload["daemon"], historical_view, target_date), 
            "schedule": self._render_schedule_fragment(target_date, payload, historical_view, metrics), 
            "metrics": self._render_metrics_fragment(target_date, payload), 
            "task-metrics": self._render_task_metrics_fragment(target_date, metrics)
        }

    def _render_banner_fragment(self, message: str, daemon: dict, historical_view: bool, target_date: date) -> str:
        return self._render("components/banner.html", message=message, is_error=any(w in message.lower() for w in ("error", "fail")) if message else False, bootstrap_error=daemon.get("bootstrap_error"), historical_view=historical_view, planning_label="Planning view" if target_date > date.today() else "Historical view", target_date_display=target_date.strftime("%d %b %Y"))

    def _render_schedule_fragment(self, target_date: date, payload: dict, historical_view: bool, metrics: dict | None = None) -> str:
        if metrics is None:
            metrics = self._metrics_payload(target_date)
        
        return self._render("components/schedule.html", 
            schedule=self._schedule_list(target_date, payload), 
            target_date_iso=target_date.isoformat(),
            historical_view=historical_view,
            hero_cls=self._hero_cls(payload), 
            hero_label=self._hero_label(payload), 
            hero_meta=self._hero_meta(payload), 
            hero_name=self._hero_name(payload), 
            hero_detail=self._hero_detail(payload), 
            runtime_status=self._runtime_status(payload), 
            pct=self._hero_pct(payload), 
            completed_str=f"{payload['plan']['completed_count']}/{payload['plan']['task_count']}", 
            next_task=payload["plan"]["current_entry"],
            actions=self._actions_list(target_date, historical_view, payload),
            plan_exists=payload["plan"]["plan_exists"],
            tasks_text=format_task_drafts([
                type("DraftView", (), {"task_name": t["task_name"], "duration_minutes": t["duration_minutes"], "description": t.get("description") or ""})()
                for t in payload["plan"]["tasks"]
            ]),
            editor_rows_html=self._task_editor_rows(payload["plan"]["tasks"])[0],
            editor_template_html=self._task_editor_rows(payload["plan"]["tasks"])[1]
        )

    def _render_metrics_fragment(self, target_date: date, payload: dict) -> str:
        metrics = payload.get("metrics", {})
        return self._render("components/metrics.html", focus_m=metrics.get('focus_seconds', 0) // 60, completed_count=payload['plan']['completed_count'], task_count=payload['plan']['task_count'], pause_m=(metrics.get('pause_seconds', 0) + metrics.get('call_seconds', 0)) // 60, planned_m=metrics.get('planned_seconds', 0) // 60)

    def _render_task_metrics_fragment(self, target_date: date, metrics: dict) -> str:
        return self._render("components/task_metrics.html", task_metrics=self._task_metrics_list(metrics))

    def _render_settings_page(self, message: str = "") -> str:
        data = self._read_config_values()
        # Ensure all sections exist as dicts
        for s in ["schedule", "stretch_lockout", "warden", "auto_pause", "backup"]:
            if s not in data or not isinstance(data[s], dict): data[s] = {}
        
        # Set specific defaults for template fields
        data["stretch_lockout"].setdefault("enabled", False)
        data["stretch_lockout"].setdefault("interval_minutes", 60)
        data["stretch_lockout"].setdefault("duration_minutes", 5)
        
        data["schedule"].setdefault("hard_shutdown_time", "01:00")
        data["schedule"].setdefault("shutdown_warning_minutes", 10)
        data["schedule"].setdefault("hard_shutdown_enabled", True)
        
        data["warden"].setdefault("task_start_grace_seconds", 300)
        data["warden"].setdefault("default_extend_minutes", 0)
        data["warden"].setdefault("give_up_cooldown_seconds", 30)
        
        data["auto_pause"].setdefault("idle_pause_seconds", 60)
        data["auto_pause"].setdefault("idle_resume_grace_seconds", 3)

        data["backup"].setdefault("enabled", False)
        data["backup"].setdefault("path", "")
        
        is_error = any(w in message.lower() for w in ("error", "must", "invalid")) if message else False
        ctx = self._get_nav_context(date.today(), "settings")
        ctx.update({
            "message": message,
            "is_error": is_error,
            "config": data,
            "auto_open_enabled": self._is_hypr_auto_open_enabled()
        })
        return self._render("settings.html", **ctx)

    def _get_nav_context(self, target_date: date, page_id: str, historical_view: bool = False, daemon_status: dict | None = None) -> dict:
        if daemon_status is None:
            daemon_status = send_command(self.socket_path, {"command": "status"})
        return {
            "page_id": page_id,
            "daemon_online": "error" not in daemon_status,
            "target_date_iso": target_date.isoformat(),
            "historical_view": historical_view,
        }

    def _render_page(self, target_date: date, message: str, historical_view: bool = False) -> str:
        payload = self._status_payload(target_date)
        metrics = self._metrics_payload(target_date)
        payload["metrics"] = metrics
        plan = payload["plan"]
        
        rows_html, template_html = self._task_editor_rows(plan["tasks"])
        if not rows_html: rows_html = self._render_task_row(index=0, task_id="", task_name="", duration_minutes=DEFAULT_TASK_DURATION_MINUTES, status="pending", badge="", completed_at=None, last_outcome=None)
        
        ctx = self._get_nav_context(target_date, "dashboard", historical_view, daemon_status=payload["daemon"])
        ctx.update({
            "target_date_display": target_date.strftime("%d %b %Y"),
            "message": message,
            "is_error": any(w in message.lower() for w in ("error", "fail")) if message else False,
            "bootstrap_error": payload["daemon"].get("bootstrap_error"),
            "planning_label": "Planning view" if target_date > date.today() else "Historical view",
            "hero_cls": self._hero_cls(payload),
            "hero_label": self._hero_label(payload),
            "hero_meta": self._hero_meta(payload),
            "hero_name": self._hero_name(payload),
            "hero_detail": self._hero_detail(payload),
            "runtime_status": self._runtime_status(payload),
            "pct": self._hero_pct(payload),
            "completed_str": f"{plan['completed_count']}/{plan['task_count']}",
            "next_task": plan["current_entry"],
            "actions": self._actions_list(target_date, historical_view, payload),
            "schedule": self._schedule_list(target_date, payload),
            "focus_m": metrics.get('focus_seconds', 0) // 60,
            "completed_count": plan['completed_count'],
            "task_count": plan['task_count'],
            "pause_m": (metrics.get('pause_seconds', 0) + metrics.get('call_seconds', 0)) // 60,
            "planned_m": metrics.get('planned_seconds', 0) // 60,
            "task_metrics": self._task_metrics_list(metrics),
            "plan_exists": plan["plan_exists"],
            "editor_rows_html": rows_html,
            "editor_template_html": template_html,
            "tasks_text": format_task_drafts([
                type("DraftView", (), {"task_name": t["task_name"], "duration_minutes": t["duration_minutes"], "description": t.get("description") or ""})()
                for t in plan["tasks"]
            ])
        })
        return self._render("index.html", **ctx)

    def _render_task_detail_page(self, task_id: int) -> str:
        return self._render_task_detail(task_id, is_fragment=False)

    def _render_task_detail_fragment(self, task_id: int) -> str:
        return self._render_task_detail(task_id, is_fragment=True)

    def _render_task_detail(self, task_id: int, is_fragment: bool = False) -> str:
        detail = self.store.get_task_detail(task_id)
        if not detail: return self._render_404("Task not found")
        notes = detail["runs"][-1].get("notes") or "" if detail.get("runs") else ""
        notes_entries = []
        if notes:
            for entry in notes.split("\n\n"):
                if not entry.strip(): continue
                match = re.match(r"^\[(\d{2}:\d{2}:\d{2})\] (.*)", entry, re.DOTALL)
                if match: notes_entries.append({"timestamp": match.group(1), "text": match.group(2)})
                else: notes_entries.append({"timestamp": None, "text": entry})
        total_dur = sum(b["duration_seconds"] for b in detail["timeline"]) or 1
        timeline = []
        for block in detail["timeline"]:
            dur = block["duration_seconds"]; t0 = block["started_at"][11:19] if len(block["started_at"]) >= 19 else block["started_at"][11:16]; t1 = (block["ended_at"][11:19] if block["ended_at"] and len(block["ended_at"]) >= 19 else "ongoing") if block["ended_at"] else "now"
            timeline.append({"type": block["type"], "pct": max(dur / total_dur * 100, 0.5), "label": block["type"].title(), "start": t0, "end": t1, "dur_disp": f"{dur // 60}m {dur % 60}s"})
        work_m = detail["total_work_seconds"] // 60; delta = work_m - detail["duration_minutes"]
        
        target_date = date.fromisoformat(detail["target_date"])
        is_historical = target_date != date.today()
        ctx = self._get_nav_context(target_date, "task_detail", historical_view=is_historical)
        ctx.update({
            "is_fragment": is_fragment,
            "task_id": task_id, "task_name": detail["task_name"], "target_date": detail["target_date"], 
            "position": detail["position"], "est_m": detail["duration_minutes"], "work_m": work_m, "work_s": detail["total_work_seconds"] % 60, 
            "pause_m": detail["total_pause_seconds"] // 60, "pause_s": detail["total_pause_seconds"] % 60, "wall_m": detail["total_wall_seconds"] // 60, 
            "delta": delta, "delta_cls": "over" if delta > 0 else ("under" if delta < 0 else "on"), 
            "completed_status": f'Completed {detail["completed_at"][:16]}' if detail["completed_at"] else "Not completed", 
            "block_count": detail["block_count"], "first_start": detail["timeline"][0]["started_at"][11:16] if detail["timeline"] else "--:--", 
            "last_end": (detail["timeline"][-1]["ended_at"][11:16] if detail["timeline"][-1]["ended_at"] else "now") if detail["timeline"] else "--:--", 
            "timeline": timeline, "notes_entries": notes_entries, 
            "back_url": f'/?view=historical&date={detail["target_date"]}' if is_historical else "/",
            "can_edit": not detail["completed_at"] and not detail["runs"] and not detail["timeline"]
        })
        return self._render("task_detail.html", **ctx)

    def _render_notes_fragment(self, detail: dict) -> str:
        notes = detail["runs"][-1].get("notes") or "" if detail.get("runs") else ""
        notes_entries = []
        if notes:
            for entry in notes.split("\n\n"):
                if not entry.strip(): continue
                match = re.match(r"^\[(\d{2}:\d{2}:\d{2})\] (.*)", entry, re.DOTALL)
                if match: notes_entries.append({"timestamp": match.group(1), "text": match.group(2)})
                else: notes_entries.append({"timestamp": None, "text": entry})
        return self._render("components/notes.html", task_id=detail["task_id"], target_date_iso=detail["target_date"], notes_entries=notes_entries)

    def _render_404(self, message: str = "Not found") -> str:
        return f"""<!doctype html><html><head><title>404</title><style>body{{font-family:system-ui;background:#06070a;color:#ccc;display:flex;align-items:center;justify-content:center;height:100vh}} .c{{text-align:center}}a{{color:#d4a039}}</style></head><body><div class="c"><h1>404</h1><p>{html.escape(message)}</p><a href="/">Back to dashboard</a></div></body></html>"""

    def _hero_cls(self, payload: dict) -> str:
        rt = payload["plan"].get("task_runtime"); status = rt["status"] if rt else None
        if status == "running": return "hero--running"
        if status == "paused": return "hero--paused"
        return "hero--pending" if payload["plan"]["current_entry"] else "hero--idle"

    def _hero_label(self, payload: dict) -> str:
        rt = payload["plan"].get("task_runtime")
        status = rt["status"] if rt else None
        if status == "running": return "RUNNING"
        if status == "paused": return "PAUSED"
        # If schedule loop decided to show hero, but runtime is missing, it's likely a race or sync issue
        # but we should still label it correctly based on the active state if possible.
        curr = payload["plan"].get("current_entry")
        if curr and curr.get("status") == "running": return "RUNNING"
        if curr and curr.get("status") == "paused": return "PAUSED"
        return "NEXT UP" if curr else "IDLE"

    def _hero_meta(self, payload: dict) -> str:
        rt = payload["plan"].get("task_runtime")
        if rt:
            meta = f'Started {rt["started_at"][11:16]}'
            if rt.get("eta"): meta += f' &mdash; ETA {rt["eta"][11:16]}'
            return meta
        entry = payload["plan"]["current_entry"]
        if entry:
            ps, pe = entry.get("projected_start") or "", entry.get("projected_end") or ""
            if ps and pe: return f'{ps[11:16]} &mdash; {pe[11:16]}'
        return ""

    def _hero_name(self, payload: dict) -> str:
        rt = payload["plan"].get("task_runtime")
        if rt:
            row = self.store.conn.execute("SELECT task_name FROM plan_tasks WHERE id = ?", (rt["plan_task_id"],)).fetchone()
            return row["task_name"] if row else "Active task"
        entry = payload["plan"]["current_entry"]
        return entry["task_name"] if entry else "No active task"

    def _hero_detail(self, payload: dict) -> str:
        rt = payload["plan"].get("task_runtime")
        if not rt: return ""
        work_m = rt["actual_work_seconds"] // 60
        if rt["status"] == "running": return f'<span class="hero__timer" id="work-timer" data-started="{rt["started_at"]}" data-pause-acc="{rt["accumulated_pause_seconds"]}">{work_m}m</span> of {rt["estimated_seconds"] // 60}m'
        if rt["status"] == "paused": return f'<span class="hero__pause-icon">&#9646;&#9646;</span> Paused &mdash; {work_m}m worked, {rt["accumulated_pause_seconds"] // 60}m paused'
        return ""

    def _runtime_status(self, payload: dict) -> str | None:
        rt = payload["plan"].get("task_runtime")
        return rt["status"] if rt else None

    def _hero_pct(self, payload: dict) -> int:
        plan = payload["plan"]; total = plan["task_count"] or 1
        return min(int(plan["completed_count"] / total * 100), 100)

    def _actions_list(self, target_date: date, historical_view: bool, payload: dict) -> list[dict]:
        rt = payload["plan"].get("task_runtime"); status = rt["status"] if rt else None
        actions = []
        if payload["plan"]["plan_exists"]:
            if status == "running": actions.append({"url": "/run/pause", "btn_class": "act--pause", "label": "&#9646;&#9646; Pause", "fragment": True})
            if status == "paused": actions.append({"url": "/run/resume", "btn_class": "act--resume", "label": "&#9654; Resume", "fragment": True})
            if rt:
                default_ext = self._read_config_values().get("warden", {}).get("default_extend_minutes", 0)
                extra = (default_ext * 60) if default_ext > 0 else rt["estimated_seconds"]
                actions.append({"url": "/run/extend", "btn_class": "act--extend", "label": f"+{extra // 60}m More", "fragment": True, "notes": True, "notes_placeholder": "Why extending?", "form_class": "act-form"})
                actions.append({"url": "/run/finish-current", "btn_class": "act--finish", "label": "&#9632; Finish Task", "fragment": True, "notes": True, "notes_placeholder": "Notes?", "form_class": "act-form"})
        return actions

    def _schedule_list(self, target_date: date, payload: dict) -> list[dict]:
        data = []
        for entry in payload["plan"]["schedule"]:
            st = entry["status"]; start = entry.get("actual_start") or entry.get("projected_start") or ""; end = entry.get("actual_end") or entry.get("eta") or entry.get("projected_end") or ""
            pause_s = entry.get("pause_seconds", 0); work_s = entry.get("actual_work_seconds", 0)
            data.append({"t0": start[11:16] if len(start) >= 16 else "-", "t1": end[11:16] if len(end) >= 16 else "-", "task_name": entry["task_name"], "task_id": entry.get("task_id"), "pause_tag": f"+{pause_s // 60}m pause" if pause_s > 60 else "", "work_tag": f"{work_s // 60}m" if st in ("finished", "abandoned", "running", "paused") and work_s > 0 else "", "cls": "sc--done" if st in ("finished", "abandoned") else ("sc--active" if st in ("running", "paused") else "sc--pending"), "status": st, "duration_minutes": entry["duration_minutes"]})
        return data

    def _task_metrics_list(self, metrics: dict) -> list[dict]:
        data = []
        for t in metrics.get('by_task', []):
            actual_m, est_m = t['actual_seconds'] // 60, t['estimated_seconds'] // 60; delta = actual_m - est_m
            data.append({"task_name": t["task_name"], "task_id": t.get("task_id"), "actual_m": actual_m, "est_m": est_m, "delta": delta, "dcls": "over" if delta > 0 else ("under" if delta < 0 else "on")})
        return data

    def _row_indexes_from_form(self, form: dict[str, str]) -> list[int]:
        indexes = set(); 
        for key in form:
            match = re.match(r"^task_name_(\d+)$", key)
            if match: indexes.add(int(match.group(1)))
        return sorted(indexes)

    def _task_rows_from_form(self, form: dict[str, str]) -> list[EditableTaskDraft]:
        indexes = self._row_indexes_from_form(form)
        if not indexes: return []
        rows = []
        for index in indexes:
            if form.get(f"task_delete_{index}") in {"1", "true", "on", "yes"}: continue
            name = form.get(f"task_name_{index}", "").strip()
            if not name: continue
            tid = form.get(f"task_id_{index}", "").strip(); tid = int(tid) if tid else None
            dur = form.get(f"task_minutes_{index}", "").strip(); dur = max(int(dur), 1) if dur else DEFAULT_TASK_DURATION_MINUTES
            rows.append(EditableTaskDraft(task_id=tid, task_name=name, duration_minutes=dur, description=form.get(f"task_desc_{index}", "").strip()))
        return rows

    def _has_deleted_task_rows(self, form: dict[str, str]) -> bool:
        for index in self._row_indexes_from_form(form):
            if form.get(f"task_delete_{index}") in {"1", "true", "on", "yes"}: return True
        return False

    def _task_editor_rows(self, tasks: list[dict]) -> tuple[str, str]:
        rows = []
        for index, task in enumerate(tasks):
            rows.append(self._render_task_row(index=index, task_id=task["id"], task_name=task["task_name"], duration_minutes=task["duration_minutes"], status="done" if task["completed_at"] else "pending", badge="DONE" if task["completed_at"] else "PENDING", completed_at=task["completed_at"], last_outcome=task["last_outcome"], description=task.get("description") or ""))
        return "".join(rows), self._render_task_row(index="__INDEX__", task_id="", task_name="", duration_minutes=DEFAULT_TASK_DURATION_MINUTES, status="pending", badge="", completed_at=None, last_outcome=None, description="", template=True)

    def _render_task_row(self, *, index, task_id, task_name, duration_minutes, status, badge, completed_at, last_outcome, description: str = "", template: bool = False) -> str:
        row_class = f"task-row {html.escape(status)}"; name_val = html.escape(str(task_name)); min_val = html.escape(str(duration_minutes)); desc_val = html.escape(str(description))
        tid_field = f'<input type="hidden" name="task_id_{index}" value="{html.escape(str(task_id))}" />' if task_id else f'<input type="hidden" name="task_id_{index}" value="" />'
        badge_html = f'<span class="pill {html.escape(status)}">{html.escape(badge)}</span>' if badge else ""
        hint_html = f'<div class="task-hint">Completed {html.escape(str(completed_at))}</div>' if completed_at else '<div class="task-hint">Not completed</div>'
        outcome_html = f'<div class="task-hint">Last: {html.escape(str(last_outcome))}</div>' if last_outcome else ""
        return f'<div class="{row_class}"><div class="task-index">{"__DISPLAY__" if template else html.escape(str(index+1))}</div><div class="task-fields">{tid_field}<input type="text" name="task_name_{index}" value="{name_val}" placeholder="Task name" /><input type="number" name="task_minutes_{index}" min="1" value="{min_val}" /><input type="text" name="task_desc_{index}" value="{desc_val}" placeholder="Description" class="task-desc" /></div><div class="task-meta">{badge_html}{hint_html}{outcome_html}</div><label class="task-delete"><input type="checkbox" name="task_delete_{index}" /> Remove row</label></div>'

    def _message_from_result(self, result: dict) -> str:
        if "error" in result: return result["error"]
        return result.get("status", "ok")

    def _start_current_from_form(self, form: dict[str, str]) -> dict:
        log.info("Starting current task from web form")
        try:
            target_date = self._target_date_from_form(form)
            # Find the first pending task
            entries = self.store.project_runtime_schedule(target_date)
            pending = [e for e in entries if e.status == "pending"]
            if not pending: return {"error": "No pending tasks."}
            
            res = send_command(self.socket_path, {"command": "start_task", "task_id": pending[0].task_id})
            if "error" in res:
                self.store.start_task_runtime(target_date, pending[0].task_id, source="web")
                return {"status": "started"}
            return {"status": "started"}
        except Exception as e:
            log.exception("Failed to start current task")
            return {"error": str(e)}

    def _extend_current_from_form(self, form: dict[str, str]) -> dict:
        log.info("Extending current task from web form")
        try:
            target_date = self._target_date_from_form(form)
            rt = self.store.get_active_task_runtime(target_date)
            if not rt: return {"error": "No active task."}
            
            config = self._read_config_values()
            ext_min = config.get("warden", {}).get("default_extend_minutes", 0)
            extra_sec = (ext_min * 60) if ext_min > 0 else rt.estimated_seconds
            
            res = send_command(self.socket_path, {"command": "extend_task", "extra_seconds": extra_sec, "notes": form.get("notes", "")})
            if "error" in res:
                # Fallback to direct DB update if daemon is offline
                self.store.extend_task_runtime(target_date, extra_sec)
                return {"status": "extended"}
            return {"status": "extended"}
        except Exception as e:
            log.exception("Failed to extend task")
            return {"error": str(e)}

    def _save_plan_from_form(self, form: dict[str, str]) -> dict:
        log.info("Saving plan from web form")
        try:
            target_date = self._target_date_from_form(form)
            tasks = self._task_rows_from_form(form)
            self.store.save_plan_rows(target_date, tasks)
            return {"status": "Plan saved"}
        except Exception as e:
            log.exception("Failed to save plan")
            return {"error": str(e)}

    def _start_session_from_form(self, form: dict[str, str]) -> dict:
        log.info("Starting new session from web form")
        try:
            self.store.ensure_session(self._target_date_from_form(form))
            return {"status": "session started"}
        except Exception as e:
            log.exception("Failed to start session")
            return {"error": str(e)}

    def _delete_task_from_form(self, form: dict[str, str]) -> dict:
        log.info("Deleting task from web form")
        try:
            target_date = self._target_date_from_form(form)
            task_id = int(form.get("task_id", "0"))
            if self.store.delete_task(target_date, task_id):
                return {"status": "Deleted"}
            return {"error": "Task not found"}
        except Exception as e:
            log.exception("Failed to delete task")
            return {"error": str(e)}

    def _edit_task_from_form(self, form: dict[str, str]) -> dict:
        log.info("Editing task from web form")
        try:
            target_date = self._target_date_from_form(form)
            task_id = int(form.get("task_id", "0"))
            name = form.get("task_name", "").strip() or None
            dur = form.get("duration_minutes", "")
            dur_val = int(dur) if dur else None
            desc = form.get("description", "").strip()
            
            if self.store.update_task(target_date, task_id, task_name=name, duration_minutes=dur_val, description=desc):
                return {"status": "Updated"}
            return {"error": "Task not found"}
        except Exception as e:
            log.exception("Failed to edit task")
            return {"error": str(e)}

    def _run_backup(self) -> dict:
        """Run an immediate backup of the database."""
        try:
            config = self._read_config_values()
            backup_cfg = config.get("backup", {})
            path = backup_cfg.get("path", "").strip()
            if not path: return {"error": "No backup path configured. Set it in Settings first."}
            result = self.store.backup_to(path)
            return {"status": f"Backed up to {result}"}
        except Exception as e:
            log.exception("Backup failed")
            return {"error": str(e)}

    def _command(self, command: str) -> dict:
        log.info("Forwarding command to daemon: %s", command)
        return send_command(self.socket_path, {"command": command.replace("-", "_")})

    def _start_session_from_form(self, form: dict[str, str]) -> dict:
        self.store.ensure_session(self._target_date_from_form(form)); return {"status": "session started"}

    def _pause_current_from_form(self, form: dict[str, str]) -> dict:
        rt = self.store.get_active_task_runtime(self._target_date_from_form(form))
        if not rt or rt.status != "running": return {"error": "No running task."}
        res = send_command(self.socket_path, {"command": "pause_task", "reason": "manual"})
        if "error" in res:
            try:
                self.store.pause_task_runtime(self._target_date_from_form(form), reason="manual", source="web")
                return {"status": "paused"}
            except Exception as e: return {"error": str(e)}
        return {"status": "paused"}

    def _resume_current_from_form(self, form: dict[str, str]) -> dict:
        rt = self.store.get_active_task_runtime(self._target_date_from_form(form))
        if not rt or rt.status != "paused": return {"error": "No paused task."}
        res = send_command(self.socket_path, {"command": "resume_task"})
        if "error" in res:
            try:
                self.store.resume_task_runtime(self._target_date_from_form(form), source="web")
                return {"status": "resumed"}
            except Exception as e: return {"error": str(e)}
        return {"status": "resumed"}

    def _finish_current_from_form(self, form: dict[str, str]) -> dict:
        t = self._target_date_from_form(form); rt = self.store.get_active_task_runtime(t)
        if not rt: return {"error": "No active run."}
        res = send_command(self.socket_path, {"command": "finish_task", "outcome": "finished", "notes": form.get("notes", "")})
        if "error" in res:
            try:
                self.store.finish_task_runtime(t, outcome="finished", notes=form.get("notes", ""))
                return {"status": "finished"}
            except Exception as e: return {"error": str(e)}
        return {"status": "finished"}

    def _reset_day_from_form(self, form: dict[str, str]) -> dict:
        self.store.reset_day(self._target_date_from_form(form)); return {"status": "reset"}

    def _delete_task_from_form(self, form: dict[str, str]) -> dict:
        try:
            tid = int(form["task_id"])
            if self.store.delete_task(self._target_date_from_form(form), tid): return {"status": "Deleted"}
            return {"error": "Not found"}
        except: return {"error": "Invalid ID"}

    def _edit_task_from_form(self, form: dict[str, str]) -> dict:
        try:
            tid = int(form["task_id"]); n = form.get("task_name", "").strip() or None; d = int(form.get("duration_minutes", "")) if form.get("duration_minutes") else None
            if self.store.update_task(self._target_date_from_form(form), tid, task_name=n, duration_minutes=d, description=form.get("description", "").strip()): return {"status": "Updated"}
            return {"error": "Not found"}
        except: return {"error": "Invalid params"}

    def _move_task_from_form(self, form: dict[str, str]) -> dict:
        try:
            tid = int(form["task_id"]); direction = int(form.get("direction", "0"))
            if direction not in (-1, 1): return {"error": "Invalid direction"}
            if self.store.move_task(self._target_date_from_form(form), tid, direction): return {"status": "Moved"}
            return {"error": "Cannot move"}
        except: return {"error": "Invalid params"}
