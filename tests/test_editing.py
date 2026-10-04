from datetime import datetime

import pytest

from dayline.editing import editor_changes, editor_values, parse_entry_date
from dayline.errors import DaylineError


def test_patch_preserves_unedited_dates_seconds_and_multiple_alarms():
    item = {
        "kind": "event",
        "title": "Meeting",
        "start": "2026-10-05T03:00:45Z",
        "end": "2026-10-05T04:00:45Z",
        "description": "  Keep whitespace\nAnd notes  ",
        "alarms": ["2026-10-05T02:30:45Z", "2026-10-05T02:45:00Z"],
    }
    initial = editor_values(item)
    assert editor_changes(initial, initial) == {}
    assert editor_changes(initial, {**initial, "title": "Renamed"}) == {"title": "Renamed"}
    assert editor_changes(initial, {**initial, "reminder": ""}) == {"reminder": None}


def test_date_only_task_dates_and_clearing_are_explicit():
    initial = editor_values({"kind": "task", "title": "Task", "due": "2026-10-05"})
    assert initial["due"] == "2026-10-05"
    assert editor_changes(initial, {**initial, "due": ""}) == {"due": None}
    assert parse_entry_date("2026-10-06") == "2026-10-06"
    assert datetime.fromisoformat(parse_entry_date("2026-10-06 09:30")).tzinfo is not None
    with pytest.raises(DaylineError):
        parse_entry_date("2026-02-30")
    with pytest.raises(DaylineError, match="title"):
        editor_changes(initial, {**initial, "title": "  "})
