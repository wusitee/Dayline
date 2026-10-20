"""Waybar focus timer, independent of GTK.

While a Waybar module process follows the timer, Dayline publishes its focus state to
the runtime directory whenever the module's extrapolated view would be wrong. The module
process extrapolates the clock between updates, so neither process writes or wakes
Waybar more than needed.
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
# Dayline holds this while it publishes; the kernel releases it when Dayline exits.
PUBLISHER = "focus-publisher.lock"
POLL_SECONDS = 0.5


def runtime_directory() -> Path | None:
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", ""))
    return runtime / "dayline" if runtime.is_absolute() and runtime.is_dir() else None


def held(path: Path, operation: int) -> bool:
    """Whether another open file holds a lock on path that conflicts with operation."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
    except OSError:
        return False
    try:
        fcntl.flock(descriptor, operation | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    finally:
        os.close(descriptor)  # Also releases a lock taken here.
    return False


def attached() -> bool:
    """Whether a Waybar module process is following the focus timer."""
    directory = runtime_directory()
    return directory is not None and held(directory / LOCK, fcntl.LOCK_EX)


def focus_status(tracker: FocusTracker, error: str | None) -> dict:
    current = tracker.current
    return {
        "state": "running" if tracker.running else "paused" if current else "idle",
        "title": current["title"] if current else "",
        "elapsed": tracker.elapsed,
        "today": sum(group["seconds"] for group in tracker.groups(date.today())),
        "error": error,
    }


def stale(published: dict | None, status: dict, now: float) -> bool:
    """Whether the module, extrapolating the published state, no longer shows status.

    This covers changed states, tasks, and errors, a session replaced by another, and
    today's total restarting at midnight.
    """
    if published is None or any(
        published[key] != status[key] for key in ("state", "title", "error")
    ):
        return True
    extra = now - published["monotonic"] if published["state"] == "running" else 0.0
    return any(abs(published[key] + extra - status[key]) >= 1 for key in ("elapsed", "today"))


class Publisher:
    """Dayline's side: focus state written under a lock that lasts as long as Dayline."""

    def __init__(self) -> None:
        self.lock = None

    def publish(self, status: dict) -> dict | None:
        """Record status with the monotonic reading the module extrapolates from."""
        directory = runtime_directory()
        if directory is None:
            return None
        if self.lock is None:
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            # Held until close(), or until this process ends.
            lock = open(directory / PUBLISHER, "a")
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                lock.close()
                raise
            self.lock = lock
        published = {**status, "monotonic": monotonic()}
        write_json(directory / STATUS, published)
        return published

    def close(self) -> None:
        if self.lock is not None:
            self.lock.close()
            self.lock = None


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


class Reader:
    """The published state while Dayline runs; otherwise the saved session, paused."""

    def __init__(self, directory: Path, history: Path):
        self.directory, self.history = directory, history
        self.cache: dict[Path, tuple[tuple | None, dict | None]] = {}

    def read(self, path: Path, parse: Callable[[Path], dict | None], *context) -> dict | None:
        try:
            info = path.stat()
            key = (info.st_mtime_ns, info.st_size, *context)
        except OSError:
            key = None
        if path not in self.cache or self.cache[path][0] != key:
            self.cache[path] = (key, parse(path) if key else None)
        return self.cache[path][1]

    def current(self) -> dict | None:
        status = self.read(self.directory / STATUS, published)
        if status is not None and held(self.directory / PUBLISHER, fcntl.LOCK_SH):
            return status
        # Today's total also depends on the local date.
        return self.read(self.history, saved, date.today())


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
    reader = Reader(directory, history)
    with open(directory / LOCK, "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_SH)
        last = None
        while True:
            line = json.dumps(render(reader.current(), monotonic()), ensure_ascii=False)
            if line != last:
                write(line)
                last = line
            wait(POLL_SECONDS)
