import time
from datetime import date, datetime, timedelta

import pytest

from dayline.search import search, search_reads, search_window


@pytest.fixture
def now(monkeypatch):
    with monkeypatch.context() as patch:
        patch.setenv("TZ", "Asia/Hong_Kong")
        time.tzset()
        yield datetime(2026, 10, 17, 12).astimezone()
    time.tzset()


def item(kind, uid, title, **values):
    return {"kind": kind, "source_id": "s", "uid": uid, "title": title, **values}


def test_reads_cover_the_window_nearest_first_within_bridge_limits():
    today = date(2026, 10, 17)
    reads = search_reads(today)
    ranges = [bounds for read in reads for bounds in read]
    assert all(len(read) == 2 for read in reads)
    assert all(0 < (end - start).days <= 35 for start, end in ranges)
    assert reads[0] == [(today, today + timedelta(35)), (today - timedelta(35), today)]
    covered = sorted(ranges)
    assert all(a[1] == b[0] for a, b in zip(covered, covered[1:], strict=False))
    first, last = search_window(today)
    assert (covered[0][0], covered[-1][1]) == (first, last + timedelta(days=1))


def test_matches_words_across_fields_and_collapses_recurring_series(now):
    weekly = [
        item(
            "event",
            "lab",
            "Chemistry lab",
            start=f"2026-10-{day:02d}T02:00:00Z",
            end=f"2026-10-{day:02d}T04:00:00Z",
            recurring=True,
            recurrence_id=f"2026-10-{day:02d}T02:00:00Z",
        )
        for day in (10, 17, 24)
    ]
    past_series = [
        {
            **occurrence,
            "uid": "old",
            "start": occurrence["start"].replace("-10-", "-09-"),
            "end": occurrence["end"].replace("-10-", "-09-"),
        }
        for occurrence in weekly[:2]
    ]
    single = item("event", "trip", "Field trip", start="2026-11-02", end="2026-11-03")
    items = [
        *weekly,
        weekly[0],  # Snapshot and search index overlap.
        *past_series,
        single,
        item("event", "gone", "Chemistry lab", start="2026-10-20", cancelled=True),
        item("task", "report", "Write report", description="chemistry LAB results"),
        item("task", "elsewhere", "Unrelated", location="Lab", source_id="chem"),
        item("task", "other", "Lab safety quiz"),
    ]
    results = search(items, {"chem": "Chemistry"}, "lab CHEM", now)
    # Today's occurrence ended at noon, so the next one represents the series.
    assert [(event["uid"], count) for event, count in results["upcoming"]] == [("lab", 3)]
    assert results["upcoming"][0][0]["start"] == "2026-10-24T02:00:00Z"
    assert [(event["uid"], count) for event, count in results["past"]] == [("old", 2)]
    assert results["past"][0][0]["start"] == "2026-09-17T02:00:00Z"
    assert {task["uid"] for task in results["tasks"]} == {"report", "elsewhere"}
    assert search(items, {}, "  ", now) == {"tasks": [], "upcoming": [], "past": []}
    assert [event["uid"] for event, _ in search(items, {}, "trip", now)["upcoming"]] == ["trip"]


def test_running_events_are_upcoming_and_tasks_order_by_state_and_date(now):
    items = [
        item("event", "now", "Review", start="2026-10-17T03:00:00Z", end="2026-10-17T05:00:00Z"),
        item("task", "done-old", "Review A", completed=True, completed_at="2026-10-01"),
        item("task", "done-new", "Review B", completed=True, completed_at="2026-10-16"),
        item("task", "undated", "Review C"),
        item("task", "later", "Review D", due="2026-10-30"),
        item("task", "soon", "Review E", due="2026-10-18"),
    ]
    results = search(items, {}, "review", now)
    assert [event["uid"] for event, _ in results["upcoming"]] == ["now"]
    assert [task["uid"] for task in results["tasks"]] == [
        "soon",
        "later",
        "undated",
        "done-new",
        "done-old",
    ]
