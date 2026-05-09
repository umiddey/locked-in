# Focus Warden

A Linux desktop focus enforcer. Plan your tasks, start a session, and let the warden keep you honest — enforced breaks, hard shutdowns, and a web dashboard to track it all.

Built for Hyprland/Wayland but the web dashboard works anywhere.

## What it does

- **Task planning** — add tasks with time estimates via the web UI
- **Session enforcement** — the daemon tracks your active task and enforces focus
- **Mandatory breaks** — configurable work intervals (default: 60 min work, 5 min break)
- **Hard shutdown** — forces you to stop at a set time (default: 01:00)
- **Auto-pause on calls** — detects microphone activity and pauses the timer
- **Web dashboard** — plan, start, pause, finish tasks from `localhost:8765`
- **Metrics** — tracks focus time, pause time, and per-task accuracy vs estimates

## Requirements

- Python 3.11+
- Linux (systemd user services for auto-start)
- PyQt6 (for the native blocker window)
- A Wayland compositor (Hyprland recommended) for the auto-open-on-login feature

## Install

```bash
git clone https://github.com/user/focus-warden.git
cd focus-warden
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Configure

```bash
cp config.example.toml config.toml
# Edit config.toml to your preferences
```

All settings are also configurable from the web dashboard at `/settings`.

Key settings in `config.toml`:

| Section | Key | Default | Description |
|---------|-----|---------|-------------|
| `schedule` | `stretch_interval_minutes` | 60 | Minutes of work before a break |
| `schedule` | `stretch_duration_minutes` | 5 | Break duration in minutes |
| `schedule` | `hard_shutdown_time` | "01:00" | Force-stop time (24h) |
| `schedule` | `hard_shutdown_enabled` | true | Toggle hard shutdown |
| `warden` | `task_start_grace_seconds` | 300 | Grace period before enforcement |
| `web` | `port` | 8765 | Web dashboard port |
| `web` | `open_browser_on_startup` | false | Auto-open browser with web server |

## Run

**Web dashboard only:**

```bash
focus-warden web
```

Open `http://localhost:8765` in your browser.

**Full daemon (break enforcement + blocker window):**

```bash
focus-warden run-legacy
```

## Auto-start on login

Install the systemd user services:

```bash
mkdir -p ~/.config/systemd/user
cp systemd/focus-warden.service ~/.config/systemd/user/
cp systemd/focus-warden-web.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now focus-warden.service
systemctl --user enable --now focus-warden-web.service
```

**Note:** Edit the `ExecStart` path in the service files if your install location differs from `~/.local/bin/`.

### Auto-open dashboard on login (Hyprland)

```bash
focus-warden auto-open-on   # adds exec-once to Hyprland autostart
focus-warden auto-open-off  # removes it
```

## CLI commands

| Command | Description |
|---------|-------------|
| `focus-warden run` | Start the simple app |
| `focus-warden web` | Start the web dashboard |
| `focus-warden run-legacy` | Start the full daemon |
| `focus-warden pause` | Pause current task |
| `focus-warden resume` | Resume current task |
| `focus-warden give-up` | Give up for the day |
| `focus-warden status` | Show daemon status |
| `focus-warden fetch-tasks` | List today's tasks |
| `focus-warden show-schedule` | Print today's schedule |
| `focus-warden auto-open-on` | Enable browser auto-open on login |
| `focus-warden auto-open-off` | Disable browser auto-open on login |

## License

MIT
