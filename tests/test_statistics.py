import copy
import time
from datetime import datetime

import pytest

from dayline.statistics import summarize


@pytest.fixture
def now(monkeypatch):
    with monkeypatch.context() as patch:
        patch.setenv("TZ", "Asia/Hong_Kong")
        time.tzset()
        yield datetime(2026, 10, 8, 12).astimezone()
    time.tzset()


def task(uid, **values):
    return {"kind": "task", "source_id": "list", "uid": uid, "title": uid, **values}


def test_task_counts_use_local_completion_dates_and_current_deadlines(now):
    early = task("early", completed=True, completed_at="2026-10-07T16:00:00Z", due="2026-10-20")
    items = [
        early,
        dict(early),
        task("late", due="2026-10-07"),
        task("timed", due="2026-10-08T01:00:00Z"),
        task("today", due="2026-10-08"),
        task("undated"),
        task("late", source_id="other"),
        task("last day", completed=True, completed_at="2026-10-01T16:00:00Z"),
        task("too old", completed=True, completed_at="2026-10-01T15:59:59Z"),
        task("future", completed=True, completed_at="2026-10-09"),
        task("unknown", completed=True),
        task("cancelled", cancelled=True, completed=True),
        {"kind": "event", "source_id": "list", "uid": "event", "title": "Event"},
    ]
    data = {"items": items, "sources": [{"id": "list", "name": "Tasks"}]}
    result = summarize(data, [], now, 7)
    assert result["tasks"] == {"open": 5, "overdue": 2, "due_today": 2, "completed": 2}
    assert result["unknown_completions"] == 1
    assert [day["completed"] for day in result["daily"]] == [1, 0, 0, 0, 0, 0, 1]
    assert result["by_list"] == [
        {"title": "Tasks", "open": 4, "completed": 2},
        {"title": "To Do list", "open": 1, "completed": 0},
    ]
    reopened = {**early, "completed": False, "completed_at": None}
    assert summarize({"items": [reopened]}, [], now, 1)["tasks"]["completed"] == 0


@pytest.mark.parametrize(
    "days,total,count,active_days", [(1, 30, 1, 1), (7, 120, 3, 3), (30, 420, 3, 4)]
)
def test_focus_ranges_clip_midnight_sessions_and_preserve_identity(
    now, days, total, count, active_days
):
    sessions = [
        {"key": "removed task", "title": "Old task", "days": {"2026-10-01": 300, "2026-10-02": 60}},
        {"key": None, "title": "Unassigned", "days": {"2026-10-07": 30}},
        {"key": "other list", "title": "Old task", "days": {"2026-10-08": 30}},
    ]
    before = copy.deepcopy(sessions)
    result = summarize(None, sessions, now, days)
    assert result["focus"] == {
        "seconds": total,
        "sessions": count,
        "average": total / count,
        "days": active_days,
    }
    assert len(result["daily"]) == days
    assert sum(group["seconds"] for group in result["by_task"]) == total
    assert len(result["by_task"]) == count
    assert sessions == before


def test_empty_statistics_include_zero_days_without_division_by_zero(now):
    result = summarize({"items": []}, [], now, 7)
    assert result["focus"] == {"seconds": 0, "sessions": 0, "average": 0, "days": 0}
    assert result["by_task"] == result["by_list"] == []
    assert len(result["daily"]) == 7
    assert all(day["seconds"] == day["completed"] == 0 for day in result["daily"])
