from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(prog="focus-warden")
    parser.add_argument("command", nargs="?", default="run", help="run | open | test-now | run-legacy | web | pause | resume | give-up | status | fetch-tasks | show-schedule | backfill-metrics | repair-backfill | auto-open-on | auto-open-off")
    parser.add_argument("--config", "-c", help="Path to config.toml")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--port", type=int, default=8765, help="Local web dashboard port")
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    if args.command == "run":
        from .simple_app import SimpleTodoApp
        sys.exit(SimpleTodoApp().run(force=False))

    if args.command == "open":
        from .simple_app import SimpleTodoApp
        sys.exit(SimpleTodoApp().run(force=True))

    if args.command == "test-now":
        from .simple_store import SimpleTodoStore
        from .simple_ui import launch_planner_window, launch_schedule_dashboard

        store = SimpleTodoStore()
        today = __import__("datetime").date.today()
        if store.has_plan(today):
            store.ensure_session(today)
            sys.exit(
                launch_schedule_dashboard(
                    target_date=today,
                    reason="Real behavior test",
                    store=store,
                )
            )
        sys.exit(
            launch_planner_window(
                target_date=today,
                reason="Real behavior test",
                existing_tasks=[],
                on_save=lambda tasks: store.save_plan(today, tasks),
                on_save_and_open=lambda tasks: (
                    store.save_plan(today, tasks),
                    store.ensure_session(today),
                    launch_schedule_dashboard(
                        target_date=today,
                        reason="Real behavior test",
                        store=store,
                    ),
                )[-1],
            )
        )

    if args.command in ("pause", "resume", "give-up", "give_up", "status"):
        from .config import load_config
        from .control_client import send_command
        import os
        try:
            config = load_config(args.config)
            socket_path = config.control.socket_path
        except FileNotFoundError:
            socket_path = os.path.expanduser("~/.local/state/focus-warden/control.sock")
        result = send_command(socket_path, {"command": args.command.replace("-", "_")})
        print(json.dumps(result, indent=2))
        sys.exit(0 if "error" not in result else 1)

    if args.command == "fetch-tasks":
        from datetime import date
        from .simple_store import SimpleTodoStore

        store = SimpleTodoStore()
        plan = store.get_plan(date.today())
        if not plan or not plan.tasks:
            print(f"No saved local plan for {date.today().isoformat()}")
            sys.exit(1)

        for task in plan.tasks:
            status = "done" if task.completed_at else "pending"
            print(f"  {task.task_name} ({task.duration_minutes}min) {status}")
        print(f"\n{len(plan.tasks)} tasks")
        sys.exit(0)

    if args.command == "show-schedule":
        from datetime import date, datetime
        from .simple_store import SimpleTodoStore

        store = SimpleTodoStore()
        today = date.today()
        plan = store.get_plan(today)
        if not plan or not plan.tasks:
            print(f"No saved local plan for {today.isoformat()}")
            sys.exit(1)

        entries = store.project_runtime_schedule(today)
        if not entries:
            print("No schedule entries.")
            sys.exit(0)

        runtime = store.get_active_task_runtime(today)
        if runtime:
            eta = runtime.compute_eta()
            print(f"  Active: {runtime.status} | ETA: {eta.strftime('%H:%M')} | Pause: {runtime.accumulated_pause_seconds // 60}m")
            print()

        for entry in entries:
            start = entry.actual_start or entry.projected_start or ""
            end = entry.actual_end or entry.eta or entry.projected_end or ""
            s_start = start[11:16] if len(start) >= 16 else (start or "??:??")
            s_end = end[11:16] if len(end) >= 16 else (end or "??:??")
            status_tag = entry.status.upper()[:4]
            pause_note = f" +{entry.pause_seconds // 60}m pause" if entry.pause_seconds else ""
            print(f"  {s_start} - {s_end} | [{status_tag}] {entry.task_name} ({entry.estimated_seconds // 60}m){pause_note}")
        sys.exit(0)

    if args.command == "backfill-metrics":
        from .simple_store import SimpleTodoStore
        from .backfill_metrics import backfill_all

        store = SimpleTodoStore()
        print("Backfilling metrics from old data...")
        stats = backfill_all(store)
        print(f"\nBackfill complete:")
        print(f"  Time blocks created: {stats['time_blocks']}")
        print(f"  Events logged: {stats['events']}")
        print(f"  Sources:")
        for source, count in stats["sources"].items():
            print(f"    {source}: {count}")
        sys.exit(0)

    if args.command == "repair-backfill":
        from .simple_store import SimpleTodoStore
        from .repair_backfill import repair_backfill_task_mapping

        store = SimpleTodoStore()
        print("Repairing backfilled task mappings...")
        result = repair_backfill_task_mapping(store)
        print(f"\nRepair complete:")
        print(f"  Repaired: {result['repaired']}")
        print(f"  Total candidates: {result['total_candidates']}")
        if result.get("reason"):
            print(f"  Reason: {result['reason']}")
        sys.exit(0)

    if args.command in ("auto-open-on", "auto-open-off"):
        AUTOSTART = Path("~/.config/hypr/autostart.conf").expanduser()
        MARKER = "exec-once = sleep 5 && xdg-open http://localhost:8765"
        COMMENTED = "# " + MARKER
        enable = args.command == "auto-open-on"
        if not AUTOSTART.exists():
            print(f"ERROR: {AUTOSTART} not found")
            sys.exit(1)
        text = AUTOSTART.read_text()
        if enable:
            if MARKER in text and COMMENTED not in text:
                print("Already enabled.")
            elif COMMENTED in text:
                text = text.replace(COMMENTED, MARKER)
                AUTOSTART.write_text(text)
                print("Auto-open browser on login: ENABLED")
            else:
                text = text.rstrip() + "\n\n# Open Focus Warden dashboard after login\n" + MARKER + "\n"
                AUTOSTART.write_text(text)
                print("Auto-open browser on login: ENABLED")
        else:
            if COMMENTED in text:
                print("Already disabled.")
            elif MARKER in text:
                text = text.replace(MARKER, COMMENTED)
                AUTOSTART.write_text(text)
                print("Auto-open browser on login: DISABLED")
            else:
                print("No auto-open line found — nothing to disable.")
        sys.exit(0)

    from .config import load_config
    config = load_config(args.config)

    if args.command == "run-legacy":
        from .daemon import Daemon
        daemon = Daemon(config)
        daemon.run()
        sys.exit(0)

    if args.command == "web":
        from .config import find_config_path
        from .web_frontend import FocusWardenWebFrontend
        port = args.port or config.web.port
        config_path = find_config_path(args.config)
        frontend = FocusWardenWebFrontend(config.control.socket_path, port=port, config_path=config_path)
        sys.exit(frontend.run())

    print(f"Unknown command: {args.command}")
    sys.exit(1)


if __name__ == "__main__":
    main()
