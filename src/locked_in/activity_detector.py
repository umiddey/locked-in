from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class MicActivitySnapshot:
    active: bool
    apps: list[str]
    error: str | None = None


class MicActivityDetector:
    def __init__(
        self,
        call_apps: list[str] | None = None,
        ignored_apps: list[str] | None = None,
    ):
        self.call_apps = [app.lower() for app in (call_apps or []) if app.strip()]
        self.ignored_apps = [app.lower() for app in (ignored_apps or []) if app.strip()]
        self._last_error: str | None = None

    def snapshot(self) -> MicActivitySnapshot:
        try:
            result = subprocess.run(
                ["pactl", "list", "source-outputs"],
                check=False,
                capture_output=True,
                text=True,
                timeout=2,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            return self._error_snapshot(str(e))

        if result.returncode != 0:
            return self._error_snapshot((result.stderr or result.stdout).strip())

        self._last_error = None
        apps = self._parse_apps(result.stdout)
        matched_apps = self._matching_apps(apps)
        return MicActivitySnapshot(active=bool(matched_apps), apps=matched_apps)

    def _error_snapshot(self, error: str) -> MicActivitySnapshot:
        if error != self._last_error:
            log.warning("Mic activity detection unavailable: %s", error)
            self._last_error = error
        return MicActivitySnapshot(active=False, apps=[], error=error)

    def _matching_apps(self, apps: list[str]) -> list[str]:
        """Return apps matching call_apps whitelist. Empty list = nothing matches (safe default).

        Use call_apps = ["*"] to match any app (legacy "any mic = call" behavior).
        """
        matched = []
        wildcard = "*" in self.call_apps
        for app in apps:
            normalized = app.lower()
            if any(ignored in normalized for ignored in self.ignored_apps):
                continue
            # Empty call_apps = no auto-pause (whitelist semantics)
            if not self.call_apps:
                continue
            if wildcard or any(allowed in normalized for allowed in self.call_apps):
                matched.append(app)
        return matched

    def _parse_apps(self, output: str) -> list[str]:
        apps: list[str] = []
        current: dict[str, str] = {}

        for line in output.splitlines():
            if line.startswith("Source Output #"):
                self._append_app(apps, current)
                current = {}
                continue

            match = re.match(r'\s*(application\.name|application\.process\.binary|media\.name) = "?(.*?)"?$', line)
            if match:
                current[match.group(1)] = match.group(2)

        self._append_app(apps, current)
        return apps

    def _append_app(self, apps: list[str], props: dict[str, str]) -> None:
        app = (
            props.get("application.name")
            or props.get("application.process.binary")
            or props.get("media.name")
            or ""
        ).strip()
        if app and app not in apps:
            apps.append(app)
