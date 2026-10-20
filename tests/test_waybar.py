import fcntl
import json
from datetime import date

import pytest

from dayline import waybar
from dayline.config import write_json


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    return tmp_path / "dayline"


def status(**values):
    return {
        "state": "running",
        "title": "Essay & <notes>",
        "elapsed": 65.0,
        "today": 600.0,
        "error": None,
        "monotonic": 100.0,
        **values,
    }


def test_render_extrapolates_running_time_and_escapes_markup():
    running = waybar.render(status(elapsed=50.0), 130.0)
    assert running["text"] == "1m"
    assert running["alt"] == "running" and running["class"] == ["running"]
    assert running["tooltip"].startswith("Essay &amp; &lt;notes&gt;\nFocusing · 1m this session")
    assert "Focus today: 10m" in running["tooltip"] and "right-click to pause" in running["tooltip"]
    paused = waybar.render(status(state="paused", elapsed=50.0, error="Cannot save"), 500.0)
    assert paused["text"] == "0m" and paused["class"] == ["paused", "error"]
    assert "Cannot save" in paused["tooltip"] and "right-click to resume" in paused["tooltip"]
    for idle in (None, status(state="idle"), {"state": "running"}):
        assert waybar.render(idle, 130.0)["text"] == ""


def test_stale_detects_what_extrapolation_cannot_show():
    published = status(elapsed=600.0, today=900.0)
    current = {**published, "elapsed": 630.0, "today": 930.0}
    assert not waybar.stale(published, current, 130.0)
    assert waybar.stale(None, current, 130.0)
    assert waybar.stale(published, {**current, "title": "Review"}, 130.0)
    # Another session for a task with the same title restarts the clock.
    assert waybar.stale(published, {**current, "elapsed": 0.0}, 130.0)
    # Today's total restarts at midnight.
    assert waybar.stale(published, {**current, "today": 10.0}, 130.0)
    paused = {**published, "state": "paused"}
    assert not waybar.stale(paused, {**paused, "monotonic": 0.0}, 130.0)


def test_follow_shows_published_state_only_while_dayline_runs(runtime, tmp_path):
    history = tmp_path / "state" / "dayline" / "focus.json"
    session = {"key": None, "title": "Saved", "start": 0, "end": 1, "days": {"2026-01-01": 61}}
    write_json(history, {"sessions": [session], "active": 0})
    publisher = waybar.Publisher()
    lines, polls = [], []

    def wait(_seconds):
        assert waybar.attached()
        polls.append(True)
        if len(polls) == 1:
            publisher.publish({**status(), "elapsed": 5.0})
        elif len(polls) == 2:
            # Dayline stopped: its last running state stays on disk but is not shown.
            publisher.close()
        else:
            raise StopIteration

    assert not waybar.attached()
    with pytest.raises(StopIteration):
        waybar.follow(lines.append, wait)
    assert not waybar.attached()
    shown = [json.loads(line) for line in lines]
    assert [(line["alt"], line["text"], line["tooltip"].split("\n")[0]) for line in shown] == [
        ("paused", "1m", "Saved"),
        ("running", "0m", "Essay &amp; &lt;notes&gt;"),
        ("paused", "1m", "Saved"),
    ]


def test_saved_totals_follow_the_local_date(runtime, tmp_path, monkeypatch):
    history = tmp_path / "state" / "dayline" / "focus.json"
    session = {"key": None, "title": "Saved", "start": 0, "end": 1, "days": {"2026-01-01": 61}}
    write_json(history, {"sessions": [session], "active": 0})

    class Clock(date):
        current = date(2026, 1, 1)

        @classmethod
        def today(cls):
            return cls.current

    monkeypatch.setattr("dayline.waybar.date", Clock)
    reader = waybar.Reader(runtime, history)
    assert reader.current()["today"] == 61
    Clock.current = date(2026, 1, 2)
    assert reader.current()["today"] == 0


def test_attached_detects_a_shared_module_lock(runtime):
    runtime.mkdir()
    assert not waybar.attached()
    with open(runtime / waybar.LOCK, "a") as lock:
        assert not waybar.attached()
        fcntl.flock(lock, fcntl.LOCK_SH)
        assert waybar.attached()
    assert not waybar.attached()
