import json
import socket
import struct
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import BinaryIO

from dayline.config import Config, cache_directory, write_json, xdg_directory
from dayline.errors import DaylineError

HOST_NAME = "io.github.wusitee.dayline"
EXTENSION_ID = "dayline@wusitee.github.io"
MAX_MESSAGE = 16 * 1024 * 1024
# Rewritten in the cache directory when Thunderbird reports a calendar change.
CHANGE_SIGNAL = "bridge-change.json"
# Days around today, as [first, last) offsets, that the compact widget can browse.
WIDGET_DAYS = (-7, 14)


def socket_path() -> Path:
    # Linux desktop sessions supply XDG_RUNTIME_DIR, private to this user.
    import os

    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", ""))
    if not runtime.is_absolute() or not runtime.is_dir():
        raise DaylineError("XDG_RUNTIME_DIR is missing; run Dayline inside your desktop session.")
    return runtime / "dayline" / "bridge.sock"


def read_exact(stream: BinaryIO, length: int) -> bytes:
    data = bytearray()
    while len(data) < length:
        chunk = stream.read(length - len(data))
        if not chunk:
            raise EOFError("Bridge connection closed.")
        data.extend(chunk)
    return bytes(data)


def read_message(stream: BinaryIO) -> dict:
    length = struct.unpack("=I", read_exact(stream, 4))[0]
    if length > MAX_MESSAGE:
        raise DaylineError("Bridge message exceeds the 16 MiB limit; narrow the date range.")
    message = json.loads(read_exact(stream, length))
    if not isinstance(message, dict):
        raise DaylineError("Invalid bridge message.")
    return message


def write_message(stream: BinaryIO, message: dict) -> None:
    data = json.dumps(message, ensure_ascii=False).encode()
    if len(data) > MAX_MESSAGE:
        raise DaylineError("Bridge message exceeds the 16 MiB limit; narrow the date range.")
    frame = memoryview(struct.pack("=I", len(data)) + data)
    while frame:
        written = stream.write(frame)
        if not written:
            raise EOFError("Bridge connection closed.")
        frame = frame[written:]
    stream.flush()


def request(command: str, **arguments) -> dict:
    try:
        with socket.socket(socket.AF_UNIX) as connection:
            connection.settimeout(25)
            connection.connect(str(socket_path()))
            with connection.makefile("rwb", buffering=0) as stream:
                write_message(stream, {"command": command, **arguments})
                response = read_message(stream)
    except (OSError, EOFError) as exc:
        raise DaylineError(
            "Thunderbird bridge unavailable. Keep Thunderbird open with Dayline Bridge enabled."
        ) from exc
    if "error" in response:
        raise DaylineError(response["error"])
    return response["result"]


def snapshot(config: Config, start: date, days: int = 7) -> dict:
    if not 1 <= days <= 35:
        raise DaylineError("Choose a date range between 1 and 35 days.")
    # Include the compact widget's days around today, even when browsing another week.
    # Navigation may be far from today: two bounded ranges rather than unbounded expansion.
    today = date.today()
    week = (start, start + timedelta(days=days))
    widget = tuple(today + timedelta(days=offset) for offset in WIDGET_DAYS)
    ranges = [week]
    if widget[0] < week[0] or widget[1] > week[1]:
        ranges.append(widget)
    encoded = [
        {
            "start": datetime.combine(a, time.min).astimezone().isoformat(),
            "end": datetime.combine(b, time.min).astimezone().isoformat(),
        }
        for a, b in ranges
    ]
    selection = {uid: dict(options) for uid, options in config.sources.items()}
    data = request("snapshot", selection=selection, ranges=encoded)
    data["selection"] = selection
    # A provider failure must not overwrite the last successful offline snapshot.
    if not data.get("errors"):
        write_json(cache_directory() / "snapshot.json", data)
    return data


def cached_snapshot(config: Config) -> dict | None:
    try:
        data = json.loads((cache_directory() / "snapshot.json").read_text())
    except (FileNotFoundError, ValueError, OSError):
        return None
    # Never display data from a removed source or a previous account selection.
    return data if isinstance(data, dict) and data.get("selection") == config.sources else None


def item_identity(item: dict) -> dict:
    return {key: item.get(key) for key in ("source_id", "kind", "uid", "recurrence_id", "revision")}


def read_item(config: Config, item: dict, scope: str) -> dict:
    return request("item", selection=config.sources, **item_identity(item), scope=scope)["item"]


def write_item(config: Config, command: str, item: dict, fields: dict, scope: str) -> dict:
    return request(
        command, selection=config.sources, **item_identity(item), fields=fields, scope=scope
    )


def install_bridge() -> dict:
    import shlex
    import sys
    import zipfile
    from importlib.resources import files

    directory = xdg_directory("XDG_DATA_HOME", ".local/share") / "dayline"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    launcher = directory / "native-host"
    launcher.write_text(
        f'#!/bin/sh\nexec {shlex.quote(sys.executable)} -m dayline.native_host "$@"\n'
    )
    launcher.chmod(0o700)
    manifest = Path.home() / ".mozilla/native-messaging-hosts" / f"{HOST_NAME}.json"
    write_json(
        manifest,
        {
            "name": HOST_NAME,
            "description": "Dayline Thunderbird calendar bridge",
            "path": str(launcher),
            "type": "stdio",
            "allowed_extensions": [EXTENSION_ID],
        },
    )
    addon = directory / "dayline-bridge.xpi"
    with zipfile.ZipFile(addon, "w", zipfile.ZIP_DEFLATED) as archive:
        for resource in sorted(files("dayline").joinpath("thunderbird").iterdir(), key=str):
            if resource.name.endswith((".js", ".json")):
                archive.writestr(resource.name, resource.read_bytes())
    addon.chmod(0o600)
    return {"addon": str(addon), "native_manifest": str(manifest)}
