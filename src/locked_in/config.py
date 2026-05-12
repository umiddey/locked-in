from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


CONFIG_SEARCH_PATHS = [
    Path("config.toml"),
    Path("~/.config/locked-in/config.toml"),
]

ENV_SEARCH_PATHS = [
    Path(".env"),
    Path("~/.config/locked-in/.env"),
]

ENV_FIELD_MAP = {
    "schedule": {
        "default_task_minutes": ("SCHEDULE_DEFAULT_TASK_MINUTES",),
        "hard_shutdown_time": ("SCHEDULE_HARD_SHUTDOWN_TIME",),
        "shutdown_warning_minutes": ("SCHEDULE_SHUTDOWN_WARNING_MINUTES",),
        "hard_shutdown_enabled": ("SCHEDULE_HARD_SHUTDOWN_ENABLED",),
    },
    "stretch_lockout": {
        "enabled": ("STRETCH_LOCKOUT_ENABLED",),
        "interval_minutes": ("STRETCH_LOCKOUT_INTERVAL_MINUTES",),
        "duration_minutes": ("STRETCH_LOCKOUT_DURATION_MINUTES",),
    },
    "warden": {
        "task_start_grace_seconds": ("WARDEN_TASK_START_GRACE_SECONDS",),
        "allow_break_skip": ("WARDEN_ALLOW_BREAK_SKIP",),
        "give_up_cooldown_seconds": ("WARDEN_GIVE_UP_COOLDOWN_SECONDS",),
        "give_up_requires_phrase": ("WARDEN_GIVE_UP_REQUIRES_PHRASE",),
        "default_extend_minutes": ("WARDEN_DEFAULT_EXTEND_MINUTES",),
    },
    "control": {
        "socket_path": ("CONTROL_SOCKET_PATH",),
    },
    "ui": {
        "theme": ("UI_THEME",),
        "show_clock": ("UI_SHOW_CLOCK",),
        "show_blocker_window": ("UI_SHOW_BLOCKER_WINDOW",),
    },
    "web": {
        "port": ("WEB_PORT",),
        "open_browser_on_startup": ("WEB_OPEN_BROWSER_ON_STARTUP",),
    },
    "auto_pause": {
        "enabled": ("AUTO_PAUSE_ENABLED",),
        "mic_active_seconds": ("AUTO_PAUSE_MIC_ACTIVE_SECONDS",),
        "resume_after_silence_seconds": ("AUTO_PAUSE_RESUME_AFTER_SILENCE_SECONDS",),
        "poll_seconds": ("AUTO_PAUSE_POLL_SECONDS",),
        "call_apps": ("AUTO_PAUSE_CALL_APPS",),
        "ignored_apps": ("AUTO_PAUSE_IGNORED_APPS",),
        "idle_pause_seconds": ("AUTO_PAUSE_IDLE_SECONDS",),
        "idle_resume_grace_seconds": ("AUTO_PAUSE_IDLE_RESUME_GRACE_SECONDS",),
    },
}


@dataclass
class ScheduleConfig:
    default_task_minutes: int = 30
    hard_shutdown_time: str = "01:00"
    shutdown_warning_minutes: int = 10
    hard_shutdown_enabled: bool = True


@dataclass
class StretchLockoutConfig:
    enabled: bool = False
    interval_minutes: int = 60
    duration_minutes: int = 5


@dataclass
class WardenConfig:
    task_start_grace_seconds: int = 300
    allow_break_skip: bool = False
    give_up_cooldown_seconds: int = 30
    give_up_requires_phrase: str = "I AM GIVING UP TODAY"
    default_extend_minutes: int = 0


@dataclass
class ControlConfig:
    socket_path: str = "~/.local/state/locked-in/control.sock"


@dataclass
class UIConfig:
    theme: str = "black"
    show_clock: bool = True
    show_blocker_window: bool = False


@dataclass
class WebConfig:
    port: int = 8765
    open_browser_on_startup: bool = False


@dataclass
class AutoPauseConfig:
    enabled: bool = True
    mic_active_seconds: int = 15
    resume_after_silence_seconds: int = 180
    poll_seconds: int = 5
    call_apps: list[str] = field(default_factory=list)
    ignored_apps: list[str] = field(default_factory=list)
    idle_pause_seconds: int = 60
    idle_resume_grace_seconds: int = 3
    exclude_irqs: list[str] = field(default_factory=list)
    soft_threshold_i8042: int = 1
    soft_threshold_xhci_hcd: int = 1
    hard_threshold_i8042: int = 3
    hard_threshold_xhci_hcd: int = 10


@dataclass
class BackupConfig:
    enabled: bool = False
    path: str = ""


@dataclass
class Config:
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
    stretch_lockout: StretchLockoutConfig = field(default_factory=StretchLockoutConfig)
    warden: WardenConfig = field(default_factory=WardenConfig)
    control: ControlConfig = field(default_factory=ControlConfig)
    ui: UIConfig = field(default_factory=UIConfig)
    web: WebConfig = field(default_factory=WebConfig)
    auto_pause: AutoPauseConfig = field(default_factory=AutoPauseConfig)
    backup: BackupConfig = field(default_factory=BackupConfig)


def _expand_path(p: str) -> str:
    return os.path.expanduser(p)


def _dict_to_dataclass(dc_type, d: dict):
    field_names = {f.name for f in dc_type.__dataclass_fields__.values()}
    filtered = {k: v for k, v in d.items() if k in field_names}
    return dc_type(**filtered)


def _parse_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        value = raw_value.strip()
        if (
            len(value) >= 2
            and ((value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")))
        ):
            value = value[1:-1]
        values[key] = value
    return values


def _collect_env_values() -> dict[str, str]:
    values: dict[str, str] = {}
    for search in ENV_SEARCH_PATHS:
        p = Path(_expand_path(str(search)))
        values.update(_parse_env_file(p))
    values.update(os.environ)
    return values


def _coerce_env_value(current, raw: str):
    if isinstance(current, bool):
        return raw.strip().lower() in {"1", "true", "yes", "on", "y"}
    if isinstance(current, int) and not isinstance(current, bool):
        return int(raw)
    if isinstance(current, float):
        return float(raw)
    if isinstance(current, list):
        return [part.strip() for part in raw.split(",") if part.strip()]
    return raw


def _apply_env_overrides(cfg: Config, env_values: dict[str, str]) -> None:
    for section_name, field_map in ENV_FIELD_MAP.items():
        section = getattr(cfg, section_name)
        for field_name, env_names in field_map.items():
            for env_name in env_names:
                if env_name in env_values:
                    current = getattr(section, field_name)
                    setattr(section, field_name, _coerce_env_value(current, env_values[env_name]))
                    break


def _has_relevant_env(env_values: dict[str, str]) -> bool:
    known_keys = {
        env_name
        for field_map in ENV_FIELD_MAP.values()
        for env_names in field_map.values()
        for env_name in env_names
    }
    return any(key in env_values for key in known_keys)


def find_config_path(path: str | None = None) -> Path | None:
    if path:
        p = Path(_expand_path(path))
        return p if p.exists() else None
    for search in CONFIG_SEARCH_PATHS:
        p = Path(_expand_path(str(search)))
        if p.exists():
            return p
    return None


def load_config(path: str | None = None) -> Config:
    env_values = _collect_env_values()
    data: dict = {}

    if path:
        p = Path(_expand_path(path))
        if not p.exists():
            raise FileNotFoundError(f"Config not found: {p}")
        raw = p.read_bytes()
        data = tomllib.loads(raw.decode("utf-8"))
    else:
        found = False
        for search in CONFIG_SEARCH_PATHS:
            p = Path(_expand_path(str(search)))
            if p.exists():
                raw = p.read_bytes()
                data = tomllib.loads(raw.decode("utf-8"))
                found = True
                break
        if not found and not _has_relevant_env(env_values):
            raise FileNotFoundError(
                "No config.toml or .env found. Create one from config.example.toml and .env.example"
            )

    cfg = Config()
    if "schedule" in data:
        cfg.schedule = _dict_to_dataclass(ScheduleConfig, data["schedule"])
    if "stretch_lockout" in data:
        cfg.stretch_lockout = _dict_to_dataclass(StretchLockoutConfig, data["stretch_lockout"])
    if "warden" in data:
        cfg.warden = _dict_to_dataclass(WardenConfig, data["warden"])
    if "control" in data:
        cfg.control = _dict_to_dataclass(ControlConfig, data["control"])
    if "ui" in data:
        cfg.ui = _dict_to_dataclass(UIConfig, data["ui"])
    if "web" in data:
        cfg.web = _dict_to_dataclass(WebConfig, data["web"])
    if "auto_pause" in data:
        cfg.auto_pause = _dict_to_dataclass(AutoPauseConfig, data["auto_pause"])
    if "backup" in data:
        cfg.backup = _dict_to_dataclass(BackupConfig, data["backup"])

    _apply_env_overrides(cfg, env_values)
    cfg.control.socket_path = _expand_path(cfg.control.socket_path)
    if cfg.backup.path:
        cfg.backup.path = _expand_path(cfg.backup.path)
    return cfg
