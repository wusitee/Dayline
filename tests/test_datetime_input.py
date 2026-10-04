"""Friendly scheduling input must be explicit, deterministic, and preserve precision."""

import time as clock
from datetime import UTC, date, datetime, time, timedelta

import pytest

from dayline.datetime_input import (
    detect_schedules,
    duration_end,
    parse_duration,
    parse_schedule,
    parse_time,
)
from dayline.errors import DaylineError


@pytest.fixture(autouse=True)
def local_zone(monkeypatch):
    monkeypatch.setenv("TZ", "Asia/Hong_Kong")
    clock.tzset()
    yield
    monkeypatch.undo()
    clock.tzset()


NOW = datetime(2026, 10, 4, 2, tzinfo=UTC)


def test_flexible_times_dates_and_relative_input_use_local_reference():
    for text, expected in (
        ("9am", time(9)),
        ("0930", time(9, 30)),
        ("2:30pm", time(14, 30)),
        ("noon", time(12)),
        ("12am", time(0)),
        ("23:59:45", time(23, 59, 45)),
    ):
        assert parse_time(text) == expected
    for text in ("tomorrow at 3pm", "5 Oct 15:00 HKT", "Oct5 3pm", "2026-10-05 at 3pm"):
        assert parse_schedule(text, now=NOW) == "2026-10-05T15:00:00+08:00"
    assert parse_schedule("next Sunday", now=NOW) == "2026-10-11"
    assert parse_schedule("Tue 6 Oct", now=NOW) == "2026-10-06"
    assert parse_schedule("9am", now=NOW, reference=date(2027, 1, 2)) == "2027-01-02T09:00:00+08:00"
    assert parse_schedule("in 90m", now=NOW) == "2026-10-04T11:30:00+08:00"
    assert parse_schedule("6 Oct 23:59 UTC", now=NOW) == "2026-10-07T07:59:00+08:00"
    assert parse_schedule("2026-10-05T03:00:45Z", now=NOW) == "2026-10-05T11:00:45+08:00"
    assert parse_schedule(" ", now=NOW) is None


@pytest.mark.parametrize(
    "text", ["25:00", "13pm", "9:75", "2026-02-30", "6/10", "Mon 6 Oct", "in 0m"]
)
def test_ambiguous_or_invalid_schedule_input_is_rejected(text):
    with pytest.raises(DaylineError):
        parse_schedule(text, now=NOW)


def test_duration_moves_end_across_midnight_and_uses_elapsed_time_across_dst(monkeypatch):
    assert parse_duration("1h 30m") == parse_duration("01:30") == timedelta(minutes=90)
    assert duration_end("2026-10-06T23:59:45+08:00", "1h") == "2026-10-07T00:59:45+08:00"
    assert duration_end("2026-10-06", "2d") == "2026-10-08"
    for text in ("0m", "-1h", "1:90", "1 hour later", "999999999999999999d"):
        with pytest.raises(DaylineError):
            parse_duration(text)
    with pytest.raises(DaylineError, match="whole days"):
        duration_end("2026-10-06", "30m")
    monkeypatch.setenv("TZ", "America/New_York")
    clock.tzset()
    assert duration_end("2026-11-01T01:30:45-04:00", "1h") == "2026-11-01T01:30:45-05:00"


def test_notes_suggest_distinct_dates_ignore_links_and_keep_text():
    notes = (
        "Due: 6 Oct 23:59 HKT (roadmap target)\n"
        "Hard deadline Sat 10 Oct 23:59\n"
        "Again 6 Oct 23:59 HKT\n"
        "https://example.test/2026-10-09/15:30\n"
        "Invalid: 30 Feb 14:00"
    )
    assert detect_schedules(notes, now=NOW) == [
        ("6 Oct 23:59 HKT", "2026-10-06T23:59:00+08:00"),
        ("Sat 10 Oct 23:59", "2026-10-10T23:59:00+08:00"),
    ]
