import json
import time
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

from dayline.errors import DaylineError
from dayline.focus import FocusTracker, task_key

DAY = date(2026, 10, 6)
TASK = {"source_id": "tasks", "uid": "essay", "title": "Essay draft"}


@pytest.fixture
def clock(monkeypatch):
    clock = SimpleNamespace(wall=datetime(2026, 10, 6, 9).timestamp(), mono=100.0)
    monkeypatch.setattr("dayline.focus.wall_time", lambda: clock.wall)
    monkeypatch.setattr("dayline.focus.monotonic", lambda: clock.mono)

    def advance(seconds, *, asleep=0):
        clock.wall += seconds + asleep
        clock.mono += seconds

    clock.advance = advance
    return clock


def test_sessions_exclude_pauses_and_suspend_and_keep_task_identity(tmp_path, clock):
    tracker = FocusTracker(tmp_path / "focus.json")
    tracker.load()
    tracker.start(TASK)
    clock.advance(120)
    tracker.pause()
    clock.advance(600)
    tracker.start()
    clock.advance(60, asleep=3600)
    tracker.finish()
    tracker.start({**TASK, "source_id": "other"})
    clock.advance(30)
    tracker.finish()
    tracker.start()
    clock.advance(15)
    tracker.finish()
    groups = tracker.groups(DAY)
    assert [group["seconds"] for group in groups] == [180, 30, 15]
    assert groups[0]["key"] != groups[1]["key"]
    assert groups[2]["title"] == "Unassigned"
    assert tracker.current is None and not tracker.running
    assert tracker.path.stat().st_mode & 0o777 == 0o600


def test_checkpoint_restores_unfinished_session_paused_without_counting_downtime(tmp_path, clock):
    path = tmp_path / "focus.json"
    tracker = FocusTracker(path)
    tracker.load()
    tracker.start(TASK)
    clock.advance(65)
    tracker.tick()
    clock.advance(1800)
    restored = FocusTracker(path)
    restored.load()
    assert not restored.running and restored.elapsed == 65
    restored.start()
    clock.advance(35)
    restored.finish()
    assert restored.groups(DAY)[0]["seconds"] == 100
    again = FocusTracker(path)
    again.load()
    assert again.current is None
    assert again.groups(DAY) == restored.groups(DAY)


@pytest.mark.parametrize("paused", [False, True])
def test_correcting_task_preserves_current_time_and_finished_sessions(tmp_path, clock, paused):
    tracker = FocusTracker(tmp_path / "focus.json")
    tracker.load()
    tracker.start(TASK)
    clock.advance(30)
    tracker.finish()
    tracker.start(TASK)
    started = tracker.current["start"]
    clock.advance(60)
    if paused:
        tracker.pause()
    clock.advance(15)
    correct = {**TASK, "source_id": "another-list", "title": "Correct task"}
    tracker.reassign(correct)
    elapsed = 60 if paused else 75
    assert tracker.running is not paused
    assert tracker.elapsed == elapsed
    assert tracker.current["start"] == started
    assert tracker.current["key"] == task_key(correct)
    assert tracker.current["title"] == "Correct task"
    assert [(group["key"], group["seconds"]) for group in tracker.groups(DAY)] == [
        (task_key(TASK), 30),
        (task_key(correct), elapsed),
    ]
    restored = FocusTracker(tracker.path)
    restored.load()
    assert restored.current == tracker.current
    clock.advance(15)
    tracker.reassign(None)
    assert tracker.current["key"] is None and tracker.current["title"] == "Unassigned"
    assert tracker.elapsed == elapsed + (0 if paused else 15)
    assert len(tracker.sessions) == 2


def test_midnight_splits_sessions_and_pause_across_days_adds_no_time(tmp_path, clock):
    clock.wall = datetime(2026, 10, 6, 23, 59, 30).timestamp()
    tracker = FocusTracker(tmp_path / "focus.json")
    tracker.load()
    tracker.start(TASK)
    clock.advance(90)
    tracker.pause()
    assert tracker.groups(DAY)[0]["seconds"] == 30
    assert tracker.groups(DAY + timedelta(days=1))[0]["seconds"] == 60
    clock.advance(24 * 3600)
    tracker.start()
    clock.advance(10)
    tracker.finish()
    assert tracker.elapsed == 0
    assert tracker.groups(DAY + timedelta(days=2))[0]["seconds"] == 10
    assert len(tracker.sessions) == 1


def test_reassigning_history_changes_only_selected_sessions_and_preserves_timing(tmp_path, clock):
    tracker = FocusTracker(tmp_path / "focus.json")
    tracker.load()
    tracker.start(TASK)
    clock.advance(5)
    tracker.finish()
    clock.advance(86400)
    for seconds in (10, 20):
        tracker.start(TASK)
        clock.advance(seconds)
        tracker.finish()
    other = {**TASK, "uid": "other", "title": "Other task"}
    tracker.start(other)
    clock.advance(15)
    targets = tracker.sessions[1:3]
    timing = [(session["start"], session["end"], dict(session["days"])) for session in targets]
    correct = {**TASK, "uid": "correct", "title": "Correct task"}
    tracker.reassign(correct, sessions=targets)
    assert tracker.sessions[0]["key"] == task_key(TASK)
    assert [session["key"] for session in targets] == [task_key(correct)] * 2
    assert [(session["start"], session["end"], session["days"]) for session in targets] == timing
    assert tracker.running and tracker.current["key"] == task_key(other)
    assert tracker.elapsed == 15
    tracker.reassign(None, sessions=[targets[0]])
    assert targets[0]["key"] is None and targets[0]["title"] == "Unassigned"
    assert targets[1]["key"] == task_key(correct)
    restored = FocusTracker(tracker.path)
    restored.load()
    assert restored.sessions == tracker.sessions
    assert len(restored.sessions) == 4


def test_local_midnight_handles_daylight_saving(tmp_path, clock, monkeypatch):
    monkeypatch.setenv("TZ", "Europe/London")
    time.tzset()
    try:
        day = date(2026, 3, 28)
        clock.wall = datetime(2026, 3, 28, 23, 59, 30).timestamp()
        tracker = FocusTracker(tmp_path / "focus.json")
        tracker.load()
        tracker.start()
        clock.advance(2 * 3600 + 30)
        tracker.finish()
        assert tracker.groups(day)[0]["seconds"] == 30
        assert tracker.groups(day + timedelta(days=1))[0]["seconds"] == 7200
        assert datetime.fromtimestamp(clock.wall).hour == 3
    finally:
        monkeypatch.undo()
        time.tzset()


@pytest.mark.parametrize(
    "contents",
    ["invalid JSON", "[]", '{"sessions":[],"active":0}', '{"sessions":[{}],"active":null}'],
)
def test_corrupt_history_is_reported_without_overwriting_it(tmp_path, contents):
    path = tmp_path / "focus.json"
    path.write_text(contents)
    tracker = FocusTracker(path)
    with pytest.raises(DaylineError, match="Cannot read focus history"):
        tracker.load()
    tracker.save()
    assert path.read_text() == contents


def test_failed_save_keeps_elapsed_time_and_retries_checkpoint(tmp_path, clock, monkeypatch):
    tracker = FocusTracker(tmp_path / "focus.json")
    tracker.load()
    tracker.start(TASK)
    clock.advance(65)
    with monkeypatch.context() as patch:
        patch.setattr("dayline.focus.write_json", lambda *_: (_ for _ in ()).throw(OSError()))
        with pytest.raises(DaylineError, match="Cannot save focus history"):
            tracker.pause()
    assert not tracker.running and tracker.elapsed == 65
    clock.advance(60)
    tracker.tick()
    assert json.loads(tracker.path.read_text())["sessions"][0]["days"][DAY.isoformat()] == 65
