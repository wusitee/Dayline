"""Local focus sessions, independent of GTK and Thunderbird."""

import json
import math
from datetime import date, datetime, time, timedelta
from pathlib import Path
from time import monotonic
from time import time as wall_time

from dayline.config import write_json
from dayline.errors import DaylineError

# Pomodoro intervals: focus, short and long breaks, and pomodoros per long break.
POMODORO_SECONDS = 25 * 60
SHORT_BREAK_SECONDS = 5 * 60
LONG_BREAK_SECONDS = 15 * 60
LONG_BREAK_EVERY = 4


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


def today() -> date:
    return datetime.fromtimestamp(wall_time()).date()


def timer_display(tracker: "FocusTracker") -> tuple[str, str]:
    """The timer's state and clock: elapsed time, or a Pomodoro countdown."""
    if tracker.on_break:
        long = tracker.break_seconds == LONG_BREAK_SECONDS
        return ("Long break" if long else "Short break"), clock_time(math.ceil(tracker.remaining))
    current = tracker.current
    state = "Focusing now" if tracker.running else "Paused" if current else "New session"
    if not tracker.pomodoro:
        return state, clock_time(tracker.elapsed)
    number = tracker.pomodoros(today()) % LONG_BREAK_EVERY + 1
    return (
        f"{state} · Pomodoro {number}/{LONG_BREAK_EVERY}",
        clock_time(math.ceil(tracker.remaining)),
    )


class FocusTracker:
    """Checkpoint active time; an unfinished session is restored paused.

    In Pomodoro mode each focus interval is one session. It finishes on its own
    after POMODORO_SECONDS of recorded time and starts a break, which counts down
    in wall-clock time and ends early when the next session starts.
    """

    def __init__(self, path: Path):
        self.path = path
        self.sessions: list[dict] = []
        self.active: int | None = None
        self.running = False
        self.pomodoro = False
        # The current break's wall-clock end and length.
        self.break_end: float | None = None
        self.break_seconds = 0.0
        self.loaded = False
        self.dirty = False
        self.last_tick = self.last_save = monotonic()

    @property
    def current(self) -> dict | None:
        return self.sessions[self.active] if self.active is not None else None

    @property
    def elapsed(self) -> float:
        return sum(self.current["days"].values()) if self.current else 0

    @property
    def on_break(self) -> bool:
        return self.break_end is not None and self.current is None

    @property
    def remaining(self) -> float:
        """Seconds left in the current break or Pomodoro focus interval."""
        if self.on_break:
            return max(0.0, self.break_end - wall_time())
        return max(0.0, POMODORO_SECONDS - self.elapsed)

    def pomodoros(self, day: date) -> int:
        """Pomodoros completed on day, by the date each one finished."""
        return sum(
            1
            for session in self.sessions
            if session.get("pomodoro") and datetime.fromtimestamp(session["end"]).date() == day
        )

    def load(self) -> None:
        try:
            data = json.loads(self.path.read_text())
            sessions, active = data["sessions"], data["active"]
            pomodoro, pause = data.get("pomodoro", False), data.get("break")
            if (
                not isinstance(sessions, list)
                or (
                    active is not None
                    and (type(active) is not int or not 0 <= active < len(sessions))
                )
                or type(pomodoro) is not bool
                or (pause is not None and not isinstance(pause, dict))
            ):
                raise ValueError
            if pause is not None:
                for value in (pause["end"], pause["seconds"]):
                    if type(value) not in (int, float) or not math.isfinite(value):
                        raise ValueError
            for session in sessions:
                if (
                    not isinstance(session, dict)
                    or not isinstance(session["title"], str)
                    or (session["key"] is not None and not isinstance(session["key"], str))
                    or not isinstance(session["days"], dict)
                    or type(session.get("pomodoro", False)) is not bool
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
            self.pomodoro = pomodoro
            if pause is not None:
                self.break_end, self.break_seconds = pause["end"], pause["seconds"]
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
        self.break_end = None
        self.last_tick = monotonic()
        self.dirty = True
        self.save()

    def tick(self) -> str | None:
        """Advance and checkpoint; return "break" or "break-over" when a phase ends."""
        self.advance()
        if self.pomodoro and self.running and self.elapsed >= POMODORO_SECONDS:
            self.current["pomodoro"] = True
            long = self.pomodoros(today()) % LONG_BREAK_EVERY == 0
            self.break_seconds = LONG_BREAK_SECONDS if long else SHORT_BREAK_SECONDS
            self.break_end = wall_time() + self.break_seconds
            self.finish()
            return "break"
        if self.break_end is not None and wall_time() >= self.break_end:
            self.break_end = None
            self.dirty = True
            self.save()
            return "break-over"
        if self.dirty and monotonic() - self.last_save >= 60:
            self.save()
        return None

    def set_pomodoro(self, enabled: bool) -> None:
        self.pomodoro = enabled
        self.break_end = None
        self.dirty = True
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

    def reassign(self, item: dict | None, *, sessions: list[dict] | None = None) -> None:
        """Correct selected sessions, defaulting to the active session."""
        self.advance()
        if sessions is None:
            sessions = [self.current] if self.current else []
        if not sessions:
            return
        for session in sessions:
            session["key"] = task_key(item) if item else None
            session["title"] = (item["title"] or "(Untitled)") if item else "Unassigned"
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
            pause = None
            if self.break_end is not None:
                pause = {"end": self.break_end, "seconds": self.break_seconds}
            write_json(
                self.path,
                {
                    "sessions": self.sessions,
                    "active": self.active,
                    "pomodoro": self.pomodoro,
                    "break": pause,
                },
            )
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
