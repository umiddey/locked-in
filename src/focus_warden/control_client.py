from __future__ import annotations

import json
import logging
import socket
import sys

log = logging.getLogger(__name__)


def send_command(socket_path: str, command: dict) -> dict:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.connect(socket_path)
        sock.sendall(json.dumps(command).encode("utf-8"))
        data = sock.recv(4096)
        return json.loads(data.decode("utf-8"))
    except FileNotFoundError:
        log.warning("Control socket missing at %s", socket_path)
        return {
            "error": (
                f"Control socket missing at {socket_path}. "
                "Start the daemon service to use pause/resume/give-up."
            )
        }
    except ConnectionRefusedError:
        return {"error": "Daemon not running"}
    except Exception as e:
        log.exception("Control command failed for %s", socket_path)
        return {"error": str(e)}
    finally:
        sock.close()


def main():
    if len(sys.argv) < 2:
        print("Usage: focus-warden <command> [args]")
        print("Commands: pause, resume, give-up, status")
        sys.exit(1)

    socket_path = "~/.local/state/focus-warden/control.sock"
    import os
    socket_path = os.path.expanduser(socket_path)

    cmd = sys.argv[1].replace("-", "_")
    result = send_command(socket_path, {"command": cmd})
    if "error" in result:
        print(f"Error: {result['error']}", file=sys.stderr)
        sys.exit(1)
    else:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
