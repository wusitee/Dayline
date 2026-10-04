"""Explicit calendar/task alarms and optional local task due-date reminders."""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from pathlib import Path

from dayline.agenda import day_start, due, local_datetime, tasks, visible_items
from dayline.config import write_json
from dayline.errors import DaylineError


@dataclass(frozen=True)
class Reminder:
    key: str
    item: dict
    when: datetime


def task_reminders(data: dict, now: datetime) -> list[Reminder]:
    """Catch up today's reminders, without replaying historical deadlines.

    Date-only tasks remind at 09:00; timed tasks remind 30 minutes before due.
    Explicit alarms remain Thunderbird's responsibility, avoiding duplicate alerts.
    """
    result = []
    for item in tasks(data):
        value = due(item)
        if value is None or item.get("alarms"):
            continue
        day, moment = value
        when = (
            (moment - timedelta(minutes=30)).astimezone()
            if moment
            else datetime.combine(day, time(9)).astimezone()
        )
        if not when <= now < day_start(day + timedelta(days=1)):
            continue
        identity = (
            item["source_id"],
            item["uid"],
            item.get("recurrence_id"),
            when.astimezone(UTC).isoformat(),
        )
        key = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
        result.append(Reminder(key, item, when))
    return sorted(result, key=lambda reminder: (reminder.when, reminder.item["title"].casefold()))


def explicit_reminders(data: dict, now: datetime) -> list[Reminder]:
    """Deliver returned DISPLAY alarms, catching up at most 24 hours after each."""
    result = {}
    for item in visible_items(data):
        for alarm in item.get("alarms", []):
            when = local_datetime(alarm)
            if not when <= now < when + timedelta(days=1):
                continue
            identity = (
                "alarm",
                item["kind"],
                item["source_id"],
                item["uid"],
                item.get("recurrence_id"),
                when.astimezone(UTC).isoformat(),
            )
            key = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
            result[key] = Reminder(key, item, when)
    return sorted(result.values(), key=lambda reminder: (reminder.when, reminder.key))


class Reminders:
    """Remember submitted notifications across restarts using a private journal."""

    def __init__(self, path: Path):
        self.path = path
        self.loaded = False
        self.fired: dict[str, datetime] = {}

    def load(self) -> None:
        try:
            data = json.loads(self.path.read_text())
            fired = data["fired"]
            if not isinstance(fired, dict):
                raise ValueError
            self.fired = {key: datetime.fromisoformat(value) for key, value in fired.items()}
            if any(moment.tzinfo is None for moment in self.fired.values()):
                raise ValueError
        except FileNotFoundError:
            pass
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise DaylineError("Cannot read reminder history; check task-reminders.json.") from exc
        self.loaded = True

    def ready(
        self, data: dict, now: datetime, *, task_due: bool = True, explicit: bool = False
    ) -> list[Reminder]:
        if not self.loaded:
            self.load()
        self.fired = {
            key: moment for key, moment in self.fired.items() if moment >= now - timedelta(days=2)
        }
        candidates = task_reminders(data, now) if task_due else []
        if explicit:
            candidates.extend(explicit_reminders(data, now))
        return [reminder for reminder in candidates if reminder.key not in self.fired]

    def mark_sent(self, reminder: Reminder) -> None:
        self.fired[reminder.key] = reminder.when
        write_json(
            self.path, {"fired": {key: moment.isoformat() for key, moment in self.fired.items()}}
        )
