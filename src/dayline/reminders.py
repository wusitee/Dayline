"""Local due-date reminders for tasks that have no Thunderbird alarm."""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from pathlib import Path

from dayline.agenda import day_start, due, tasks
from dayline.config import write_json
from dayline.errors import DaylineError


@dataclass(frozen=True)
class TaskReminder:
    key: str
    item: dict
    when: datetime


def task_reminders(data: dict, now: datetime) -> list[TaskReminder]:
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
        result.append(TaskReminder(key, item, when))
    return sorted(result, key=lambda reminder: (reminder.when, reminder.item["title"].casefold()))


class TaskReminders:
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
            raise DaylineError(
                "Cannot read task-reminder history; check task-reminders.json."
            ) from exc
        self.loaded = True

    def ready(self, data: dict, now: datetime) -> list[TaskReminder]:
        if not self.loaded:
            self.load()
        self.fired = {
            key: moment for key, moment in self.fired.items() if moment >= now - timedelta(days=2)
        }
        return [
            reminder for reminder in task_reminders(data, now) if reminder.key not in self.fired
        ]

    def mark_sent(self, reminder: TaskReminder) -> None:
        self.fired[reminder.key] = reminder.when
        write_json(
            self.path, {"fired": {key: moment.isoformat() for key, moment in self.fired.items()}}
        )
