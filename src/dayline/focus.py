"""Local focus sessions, independent of GTK and Thunderbird."""

import json
import math
from datetime import date, datetime, time, timedelta
from pathlib import Path
from time import monotonic
from time import time as wall_time

from dayline.config import write_json
from dayline.errors import DaylineError


def task_key(item: dict) -> str:
    return json.dumps([item["source_id"], item["uid"], item.get("recurrence_id")])


def duration(seconds: float) -> str:
    minutes = int(seconds) // 60
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02}m" if hours else f"{minutes}m"


def clock_time(seconds: float) -> str:
    minutes, seconds = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02}:{seconds:02}" if hours else f"{minutes:02}:{seconds:02}"


class FocusTracker:
    """Checkpoint active time; an unfinished session is restored paused."""

    def __init__(self, path: Path):
        self.path = path
        self.sessions: list[dict] = []
        self.active: int | None = None
        self.running = False
        self.loaded = False
        self.dirty = False
        self.last_tick = self.last_save = monotonic()

    @property
    def current(self) -> dict | None:
        return self.sessions[self.active] if self.active is not None else None

    @property
    def elapsed(self) -> float:
        return sum(self.current["days"].values()) if self.current else 0

    def load(self) -> None:
        try:
            data = json.loads(self.path.read_text())
            sessions, active = data["sessions"], data["active"]
            if not isinstance(sessions, list) or (
                active is not None and (type(active) is not int or not 0 <= active < len(sessions))
            ):
                raise ValueError
            for session in sessions:
                if (
                    not isinstance(session, dict)
                    or not isinstance(session["title"], str)
                    or (session["key"] is not None and not isinstance(session["key"], str))
                    or not isinstance(session["days"], dict)
                ):
                    raise ValueError
                for moment in (session["start"], session["end"]):
                    if type(moment) not in (int, float) or not math.isfinite(moment):
                        raise ValueError
                    datetime.fromtimestamp(moment)
                for day, seconds in session["days"].items():
                    if (
                        date.fromisoformat(day).isoformat() != day
                        or type(seconds) not in (int, float)
                        or not math.isfinite(seconds)
                        or seconds < 0
                    ):
                        raise ValueError
            self.sessions, self.active = sessions, active
        except FileNotFoundError:
            pass
        except (OSError, ValueError, KeyError, TypeError, OverflowError) as exc:
            raise DaylineError(
                "Cannot read focus history; check focus.json in the state directory."
            ) from exc
        self.loaded = True

    def start(self, item: dict | None = None) -> None:
        if self.current is None:
            now = wall_time()
            self.sessions.append(
                {
                    "key": task_key(item) if item else None,
                    "title": (item["title"] or "(Untitled)") if item else "Unassigned",
                    "start": now,
                    "end": now,
                    "days": {},
                }
            )
            self.active = len(self.sessions) - 1
        self.running = True
        self.last_tick = monotonic()
        self.dirty = True
        self.save()

    def tick(self) -> None:
        self.advance()
        if self.dirty and monotonic() - self.last_save >= 60:
            self.save()

    def advance(self) -> None:
        now = monotonic()
        if self.running:
            seconds = max(0, now - self.last_tick)
            end = wall_time()
            # Linux's monotonic clock excludes suspend and ignores clock adjustments.
            # Attribute the measured active interval to the current local dates.
            cursor = end - seconds
            while cursor < end:
                day = datetime.fromtimestamp(cursor).date()
                midnight = datetime.combine(day + timedelta(days=1), time.min).timestamp()
                boundary = min(end, midnight)
                key = day.isoformat()
                days = self.current["days"]
                days[key] = days.get(key, 0) + boundary - cursor
                cursor = boundary
            self.current["end"] = end
            self.dirty = True
        self.last_tick = now

    def pause(self) -> None:
        self.advance()
        self.running = False
        self.dirty = True
        self.save()

    def finish(self) -> None:
        self.advance()
        self.running = False
        if self.current and not self.elapsed:
            self.sessions.pop(self.active)
        self.active = None
        self.dirty = True
        self.save()

    def save(self) -> None:
        if not self.loaded:
            return
        try:
            write_json(self.path, {"sessions": self.sessions, "active": self.active})
        except OSError as exc:
            raise DaylineError(
                "Cannot save focus history; check state directory permissions."
            ) from exc
        self.last_save = monotonic()
        self.dirty = False

    def groups(self, day: date) -> list[dict]:
        groups = {}
        for session in self.sessions:
            seconds = session["days"].get(day.isoformat(), 0)
            if seconds:
                group = groups.setdefault(
                    session["key"], {"key": session["key"], "title": session["title"], "seconds": 0}
                )
                group["title"] = session["title"]
                group["seconds"] += seconds
        return list(groups.values())
