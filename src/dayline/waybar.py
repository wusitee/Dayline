"""Waybar focus timer, independent of GTK.

While a Waybar module process follows the timer, Dayline publishes its focus state to
the runtime directory on changes and every minute. The module process extrapolates the
clock between updates, so neither process writes or wakes Waybar more than needed.
"""

import fcntl
import json
import os
from collections.abc import Callable
from datetime import date
from html import escape
from pathlib import Path
from time import monotonic, sleep

from dayline.config import write_json, xdg_directory
from dayline.errors import DaylineError
from dayline.focus import FocusTracker, duration

STATUS = "focus-status.json"
# Module processes hold a shared lock; Dayline then hides its floating indicator.
LOCK = "waybar-focus.lock"
POLL_SECONDS = 0.5


def runtime_directory() -> Path | None:
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", ""))
    return runtime / "dayline" if runtime.is_absolute() and runtime.is_dir() else None


def attached() -> bool:
    """Whether a Waybar module process is following the focus timer."""
    directory = runtime_directory()
    if directory is None:
        return False
    try:
        descriptor = os.open(directory / LOCK, os.O_RDONLY | os.O_CLOEXEC)
    except OSError:
        return False
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    finally:
        os.close(descriptor)  # Also releases a lock taken here.
    return False


def focus_status(tracker: FocusTracker, error: str | None) -> dict:
    current = tracker.current
    return {
        "state": "running" if tracker.running else "paused" if current else "idle",
        "title": current["title"] if current else "",
        "elapsed": tracker.elapsed,
        "today": sum(group["seconds"] for group in tracker.groups(date.today())),
        "error": error,
    }


def publish(status: dict) -> None:
    """Record the focus state with the monotonic reading the module extrapolates from."""
    directory = runtime_directory()
    if directory is not None:
        write_json(directory / STATUS, {**status, "monotonic": monotonic(), "pid": os.getpid()})


def render(status: dict | None, now: float) -> dict:
    """Waybar's JSON for a focus state; empty text hides the module."""
    try:
        if status is None or status["state"] not in ("running", "paused"):
            return {"text": "", "alt": "idle", "class": "idle", "tooltip": ""}
        running = status["state"] == "running"
        extra = max(0.0, now - status["monotonic"]) if running else 0.0
        # Minutes keep the bar calm; the task stays in the tooltip.
        session, error = duration(status["elapsed"] + extra), status["error"]
        lines = [
            status["title"],
            f"{'Focusing' if running else 'Paused'} · {session} this session",
            f"Focus today: {duration(status['today'] + extra)}",
            *([error] if error else []),
            f"Click for focus controls; right-click to {'pause' if running else 'resume'}.",
        ]
        state = "running" if running else "paused"
        return {
            "text": session,
            "alt": state,
            "class": [state, "error"] if error else [state],
            "tooltip": escape("\n".join(lines)),
        }
    except (KeyError, TypeError, ValueError):
        return {"text": "", "alt": "idle", "class": "idle", "tooltip": ""}


def alive(pid: object) -> bool:
    if type(pid) is not int or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class Reader:
    """The published state while Dayline runs; otherwise the saved session, paused."""

    def __init__(self, status: Path, history: Path):
        self.status, self.history = status, history
        self.cache: dict[Path, tuple[tuple[int, int] | None, dict | None]] = {}

    def read(self, path: Path, parse: Callable[[Path], dict | None]) -> dict | None:
        try:
            info = path.stat()
            key = (info.st_mtime_ns, info.st_size)
        except OSError:
            key = None
        if path not in self.cache or self.cache[path][0] != key:
            self.cache[path] = (key, parse(path) if key else None)
        return self.cache[path][1]

    def current(self) -> dict | None:
        status = self.read(self.status, published)
        if status is not None and alive(status.get("pid")):
            return status
        return self.read(self.history, saved)


def published(path: Path) -> dict | None:
    try:
        status = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return status if isinstance(status, dict) else None


def saved(path: Path) -> dict | None:
    # Dayline restores an unfinished session paused, so it is shown paused.
    tracker = FocusTracker(path)
    try:
        tracker.load()
    except DaylineError:
        return None
    return {**focus_status(tracker, None), "monotonic": 0.0}


def follow(write: Callable[[str], None], wait: Callable[[float], None] = sleep) -> None:
    """Write one Waybar JSON line whenever the displayed focus timer changes."""
    directory = runtime_directory()
    if directory is None:
        raise DaylineError("XDG_RUNTIME_DIR is missing; run Waybar inside your desktop session.")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    history = xdg_directory("XDG_STATE_HOME", ".local/state") / "dayline" / "focus.json"
    reader = Reader(directory / STATUS, history)
    with open(directory / LOCK, "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_SH)
        last = None
        while True:
            line = json.dumps(render(reader.current(), monotonic()), ensure_ascii=False)
            if line != last:
                write(line)
                last = line
            wait(POLL_SECONDS)
