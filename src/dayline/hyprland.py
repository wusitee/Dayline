"""Read-only Hyprland IPC, independent of GTK."""

import json
import os
import socket
from pathlib import Path


def cursor_position() -> tuple[float, float] | None:
    """Return Hyprland's global cursor position in logical pixels, or None elsewhere."""
    signature = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if not signature or not runtime:
        return None
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(0.1)
            client.connect(str(Path(runtime) / "hypr" / signature / ".socket.sock"))
            client.sendall(b"j/cursorpos")
            reply = b""
            while chunk := client.recv(4096):
                reply += chunk
        position = json.loads(reply)
        return float(position["x"]), float(position["y"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
