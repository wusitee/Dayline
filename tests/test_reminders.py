import time as clock
from datetime import date, datetime, time, timedelta

import pytest

from dayline.errors import DaylineError
from dayline.reminders import TaskReminders, task_reminders

DAY = date(2026, 10, 5)


def local(day=DAY, hour=9, minute=0):
    return datetime.combine(day, time(hour, minute)).astimezone()


def task(uid, due, **fields):
    return {
        "kind": "task",
        "source_id": "source",
        "uid": uid,
        "title": uid,
        "due": due,
        **fields,
    }


def test_reminders_use_due_dates_without_duplicating_explicit_alarms():
    data = {
        "items": [
            task("date only", DAY.isoformat()),
            task("timed", local(hour=10).isoformat()),
            task("explicit", DAY.isoformat(), alarms=[local().isoformat()]),
            task("completed", DAY.isoformat(), completed=True),
            task("cancelled", DAY.isoformat(), cancelled=True),
            task("undated", None),
            task("old", (DAY - timedelta(days=1)).isoformat()),
            task("future", (DAY + timedelta(days=1)).isoformat()),
            task("date only", DAY.isoformat()),
        ]
    }
    assert task_reminders(data, local(hour=8, minute=59)) == []
    assert [(r.item["uid"], r.when) for r in task_reminders(data, local())] == [
        ("date only", local()),
    ]
    assert [(r.item["uid"], r.when) for r in task_reminders(data, local(minute=30))] == [
        ("date only", local()),
        ("timed", local(minute=30)),
    ]


def test_history_survives_restart_and_midnight_and_tracks_changed_deadlines(tmp_path):
    path = tmp_path / "reminders.json"
    tomorrow = DAY + timedelta(days=1)
    item = task("task", local(tomorrow, 0, 15).isoformat())
    data = {"items": [item]}
    scheduler = TaskReminders(path)
    reminders = scheduler.ready(data, local(hour=23, minute=45))
    assert len(reminders) == 1
    scheduler.mark_sent(reminders[0])
    restarted = TaskReminders(path)
    assert restarted.ready(data, local(tomorrow, 0, 5)) == []
    item["title"] = "Renamed"
    assert restarted.ready(data, local(tomorrow, 0, 5)) == []
    item["due"] = local(tomorrow, 0, 30).isoformat()
    assert len(restarted.ready(data, local(tomorrow, 0, 5))) == 1
    item["completed"] = True
    assert restarted.ready(data, local(tomorrow, 0, 5)) == []
    assert restarted.ready({"items": []}, local(tomorrow, 0, 5)) == []
    # Missed reminders still catch up on their due day, but never on later days.
    assert (
        len(
            TaskReminders(tmp_path / "fresh.json").ready(
                {"items": [task("missed", tomorrow.isoformat())]}, local(tomorrow, 14)
            )
        )
        == 1
    )
    assert task_reminders(data, local(tomorrow + timedelta(days=1))) == []


def test_date_only_reminders_keep_nine_oclock_across_daylight_saving(monkeypatch):
    monkeypatch.setenv("TZ", "Europe/London")
    clock.tzset()
    try:
        day = date(2026, 3, 29)
        data = {"items": [task("task", day.isoformat())]}
        assert task_reminders(data, local(day, 8, 59)) == []
        assert task_reminders(data, local(day))[0].when == local(day)
    finally:
        monkeypatch.undo()
        clock.tzset()


def test_corrupt_history_is_reported_instead_of_silently_replaying_alerts(tmp_path):
    path = tmp_path / "reminders.json"
    path.write_text("invalid json")
    scheduler = TaskReminders(path)
    with pytest.raises(DaylineError, match="Cannot read task-reminder history"):
        scheduler.ready({"items": [task("task", DAY.isoformat())]}, local())
