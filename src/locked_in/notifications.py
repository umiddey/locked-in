from __future__ import annotations

import logging
import subprocess

log = logging.getLogger(__name__)


def notify(title: str, body: str, urgency: str = "normal"):
    try:
        subprocess.run(
            ["notify-send", "-u", urgency, title, body],
            check=False,
            capture_output=True,
        )
    except FileNotFoundError:
        log.warning("notify-send not found, skipping notification: %s", title)
