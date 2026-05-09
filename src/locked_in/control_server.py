from __future__ import annotations

import json
import logging
import os
import socket
from pathlib import Path

log = logging.getLogger(__name__)


class ControlServer:
    def __init__(self, socket_path: str, handler):
        self.socket_path = socket_path
        self.handler = handler  # Callable(dict) -> dict
        Path(self.socket_path).parent.mkdir(parents=True, exist_ok=True)
        if os.path.exists(self.socket_path):
            os.unlink(self.socket_path)

        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.bind(self.socket_path)
        self.sock.listen(5)
        self.sock.settimeout(0.1)
        log.info("Control server listening on %s", self.socket_path)

    def poll(self):
        try:
            conn, _ = self.sock.accept()
        except socket.timeout:
            return
        except OSError:
            return

        try:
            data = conn.recv(4096)
            if not data:
                return
            cmd = json.loads(data.decode("utf-8"))
            response = self.handler(cmd)
            conn.sendall(json.dumps(response).encode("utf-8"))
        except Exception as e:
            log.error("Control server error: %s", e)
            try:
                conn.sendall(json.dumps({"error": str(e)}).encode("utf-8"))
            except Exception:
                pass
        finally:
            conn.close()

    def close(self):
        self.sock.close()
        if os.path.exists(self.socket_path):
            os.unlink(self.socket_path)
