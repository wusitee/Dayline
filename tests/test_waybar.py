import fcntl
import json
import subprocess

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


def test_follow_holds_the_module_lock_and_falls_back_to_saved_sessions(runtime, tmp_path):
    finished = subprocess.Popen(["true"])
    finished.wait()
    history = tmp_path / "state" / "dayline" / "focus.json"
    session = {"key": None, "title": "Saved", "start": 0, "end": 1, "days": {"2026-01-01": 61}}
    write_json(history, {"sessions": [session], "active": 0})
    lines, polls = [], []

    def wait(_seconds):
        assert waybar.attached()
        polls.append(True)
        if len(polls) == 1:
            # Dayline is running: its published state replaces the saved session.
            waybar.publish({**status(), "elapsed": 5.0})
        elif len(polls) == 2:
            # Dayline stopped without publishing: the saved session is shown paused.
            write_json(runtime / waybar.STATUS, {**status(), "pid": finished.pid})
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


def test_attached_detects_a_shared_module_lock(runtime):
    runtime.mkdir()
    assert not waybar.attached()
    with open(runtime / waybar.LOCK, "a") as lock:
        assert not waybar.attached()
        fcntl.flock(lock, fcntl.LOCK_SH)
        assert waybar.attached()
    assert not waybar.attached()
