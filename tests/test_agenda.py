import time as clock
from datetime import date, datetime, time, timedelta

import pytest

from dayline.agenda import (
    all_day_spans,
    covers,
    day_agenda,
    due_label,
    link_markup,
    status,
    task_groups,
    upcoming_events,
    visible_hours,
    week_segments,
)

WEEK = date(2026, 10, 5)


@pytest.fixture(autouse=True)
def hong_kong(monkeypatch):
    # Fixed UTC+8 without DST, matching the bridge's UTC timestamps for HKU classes.
    monkeypatch.setenv("TZ", "Asia/Hong_Kong")
    clock.tzset()
    yield
    monkeypatch.undo()
    clock.tzset()


def local(day: date, minutes: int) -> str:
    moment = datetime.combine(day, time.min).astimezone() + timedelta(minutes=minutes)
    return moment.isoformat()


def event(title, start, end, **fields):
    return {
        "kind": "event",
        "uid": title,
        "source_id": "calendar",
        "recurrence_id": None,
        "title": title,
        "start": start,
        "end": end,
        **fields,
    }


def task(title, due, **fields):
    return {"kind": "task", "uid": title, "source_id": "todo", "title": title, "due": due, **fields}


def test_week_layout_handles_overlap_chains_overnight_clipping_and_duplicates():
    data = {
        "items": [
            event("long", local(WEEK, 540), local(WEEK, 720)),
            event("inside", local(WEEK, 600), local(WEEK, 660)),
            # Overlaps only "long", but shares its cluster and so its lane count.
            event("chained", local(WEEK, 690), local(WEEK, 750)),
            event("touching", local(WEEK, 750), local(WEEK, 780)),
            event("overnight", local(WEEK, 1380), local(WEEK, 1500)),
            event("outside", local(WEEK, -900), local(WEEK, -840)),
            event("cancelled", local(WEEK, 540), local(WEEK, 600), cancelled=True),
            # The bridge's UTC form of 09:00–09:50 local; repeated reads must not duplicate it.
            event("utc", "2026-10-06T01:00:00.000Z", "2026-10-06T01:50:00.000Z"),
            event("utc", "2026-10-06T01:00:00.000Z", "2026-10-06T01:50:00.000Z"),
        ]
    }
    segments = {}
    for segment in week_segments(data, WEEK):
        segments.setdefault(segment.item["title"], []).append(segment)
    assert {segments[name][0].lanes for name in ("long", "inside", "chained")} == {2}
    assert segments["inside"][0].lane != segments["long"][0].lane
    assert segments["chained"][0].lane != segments["long"][0].lane
    assert (segments["touching"][0].lane, segments["touching"][0].lanes) == (0, 1)
    assert [(s.day, s.start, s.end) for s in segments["overnight"]] == [
        (0, 1380, 1440),
        (1, 0, 60),
    ]
    assert [(s.day, s.start, s.end) for s in segments["utc"]] == [(1, 540, 590)]
    assert "outside" not in segments and "cancelled" not in segments


def test_visible_hours_default_to_working_day_and_widen_to_fit_events():
    def hours(*events):
        return visible_hours(week_segments({"items": list(events)}, WEEK))

    assert hours() == (7, 21)
    assert hours(event("lecture", local(WEEK, 600), local(WEEK, 650))) == (7, 21)
    early = event("early", local(WEEK, 330), local(WEEK, 400))
    late = event("late", local(WEEK, 1290), local(WEEK, 1330))
    assert hours(early, late) == (5, 23)
    # Overnight events reach both ends of the day.
    assert hours(event("overnight", local(WEEK, 1380), local(WEEK, 1500))) == (0, 24)


def test_week_layout_uses_wall_clock_hours_on_daylight_saving_days(monkeypatch):
    monkeypatch.setenv("TZ", "Europe/London")
    clock.tzset()
    autumn, spring = date(2026, 10, 25), date(2026, 3, 29)
    data = {
        "items": [
            # 14:00–15:00 GMT after clocks go back, and 14:00–15:00 BST after they go forward.
            event("autumn", "2026-10-25T14:00:00Z", "2026-10-25T15:00:00Z"),
            event("spring", "2026-03-29T13:00:00Z", "2026-03-29T14:00:00Z"),
        ]
    }
    assert [(s.start, s.end) for s in week_segments(data, autumn, 1)] == [(840, 900)]
    assert [(s.start, s.end) for s in week_segments(data, spring, 1)] == [(840, 900)]


def test_all_day_end_is_exclusive_and_spans_stack_in_rows():
    data = {
        "items": [
            event("holiday", "2026-10-04", "2026-10-07"),
            event("single", "2026-10-06", "2026-10-07"),
            event("next week", "2026-10-12", "2026-10-13"),
            event("timed", local(WEEK, 540), local(WEEK, 600)),
        ]
    }
    spans = {span.item["title"]: span for span in all_day_spans(data, WEEK)}
    assert (spans["holiday"].first, spans["holiday"].last) == (0, 1)
    assert (spans["single"].first, spans["single"].last, spans["single"].row) == (1, 1, 1)
    assert set(spans) == {"holiday", "single"}


def test_tasks_group_by_local_due_date_and_keep_undated_items():
    now = datetime.combine(WEEK, time(9)).astimezone()
    data = {
        "items": [
            # Microsoft To Do date-only dues arrive as local midnight in UTC.
            task("due today", "2026-10-04T16:00:00.000Z"),
            task("due yesterday", "2026-10-03T16:00:00.000Z"),
            task("timed, passed", local(WEEK, 480)),
            task("timed, later", local(WEEK, 1080)),
            task("date only", "2026-10-07"),
            task("undated", None),
            task("done", None, completed=True),
        ]
    }
    groups = {
        name: [item["title"] for item in items] for name, items in task_groups(data, now).items()
    }
    assert groups == {
        "overdue": ["due yesterday", "timed, passed"],
        "today": ["due today", "timed, later"],
        "upcoming": ["date only"],
        "undated": ["undated"],
    }
    assert due_label(task("t", "2026-10-04T16:00:00.000Z"), WEEK) == "Due today"
    assert due_label(task("t", local(WEEK, 1080)), WEEK) == "Due today 18:00"


def test_upcoming_events_include_current_and_exclude_finished_events():
    now = datetime.combine(WEEK, time(10, 30)).astimezone()
    data = {
        "items": [
            event("finished", local(WEEK, 540), local(WEEK, 600)),
            event("current", local(WEEK, 600), local(WEEK, 660)),
            event("all day", "2026-10-05", "2026-10-06"),
            event("beyond horizon", local(WEEK + timedelta(days=8), 600), None),
        ]
    }
    assert [item["title"] for item in upcoming_events(data, now)] == ["all day", "current"]


def test_week_coverage_and_status_distinguish_saved_partial_and_offline_data():
    data = {
        "generated_at": "2026-10-05T01:00:00.000Z",
        "offline": True,
        "ranges": [
            {"start": "2026-10-05T00:00:00+08:00", "end": "2026-10-12T00:00:00+08:00"},
            {"start": "2026-10-12T00:00:00+08:00", "end": "2026-10-19T00:00:00+08:00"},
        ],
        "sources": [{"id": "timetable", "name": "Timetable"}],
        "errors": [{"source_id": "timetable", "message": "Provider failed."}],
    }
    assert covers(data, WEEK, WEEK + timedelta(days=14))
    assert not covers(data, WEEK - timedelta(days=7), WEEK)
    assert status(data, saved=False, error=None, today=WEEK) == [
        "Timetable could not be read; its items are missing. Provider failed.",
        "Thunderbird is offline; items reflect its local copy.",
    ]
    stale = status({**data, "errors": [], "offline": False}, saved=True, error="Down.", today=WEEK)
    assert stale == ["Down. Showing data read at 09:00."]


def test_day_agenda_lists_remaining_today_and_whole_other_days():
    now = datetime.combine(WEEK, time(10, 30)).astimezone()
    tomorrow = WEEK + timedelta(days=1)
    data = {
        "items": [
            event("finished", local(WEEK, 540), local(WEEK, 600)),
            event("current", local(WEEK, 600), local(WEEK, 660)),
            event("tomorrow", local(tomorrow, 540), local(tomorrow, 600)),
            task("late", "2026-10-02"),
            task("due today", "2026-10-04T16:00:00.000Z"),
            task("due tomorrow", "2026-10-06"),
            task("undated", None),
        ]
    }
    events, due = day_agenda(data, WEEK, now)
    assert [item["title"] for item in events] == ["current"]
    assert [item["title"] for item in due] == ["late", "due today"]
    events, due = day_agenda(data, tomorrow, now)
    assert [item["title"] for item in events] == ["tomorrow"]
    assert [item["title"] for item in due] == ["due tomorrow"]


def test_link_markup_escapes_text_and_links_only_http_urls():
    text = "Notes <b>&</b> see https://example.com/a?x=1&y=2. Not javascript:alert(1)"
    assert link_markup(text) == (
        "Notes &lt;b&gt;&amp;&lt;/b&gt; see "
        '<a href="https://example.com/a?x=1&amp;y=2">https://example.com/a?x=1&amp;y=2</a>.'
        " Not javascript:alert(1)"
    )
