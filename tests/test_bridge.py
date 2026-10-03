import io
import json
import os
import stat
import struct
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest

from dayline import bridge
from dayline.config import Config, cache_directory, write_json
from dayline.errors import DaylineError


class Fragmented(io.BytesIO):
    def read(self, size=-1):
        return super().read(min(size, 2))

    def write(self, data):
        return super().write(data[:2])


def test_native_message_framing_handles_fragmented_utf8_and_rejects_truncation():
    stream = Fragmented()
    bridge.write_message(stream, {"title": "课程"})
    assert bridge.read_message(Fragmented(stream.getvalue())) == {"title": "课程"}
    with pytest.raises(EOFError):
        bridge.read_message(Fragmented(stream.getvalue()[:-1]))
    with pytest.raises(DaylineError, match="limit"):
        bridge.read_message(io.BytesIO(struct.pack("=I", bridge.MAX_MESSAGE + 1)))


def test_cache_is_private_and_never_reuses_removed_source_data(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    original = Config({"list": {"role": "personal", "events": False, "tasks": True}})
    path = cache_directory() / "snapshot.json"
    write_json(path, {"selection": original.sources, "items": [{"title": "private"}]})
    assert bridge.cached_snapshot(original)["items"][0]["title"] == "private"
    assert bridge.cached_snapshot(Config()) is None
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_snapshot_keeps_browsed_week_and_today_ranges_bounded(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    calls = []

    def request(command, **arguments):
        calls.append((command, arguments))
        return {"items": [], "ranges": arguments["ranges"]}

    monkeypatch.setattr(bridge, "request", request)
    config = Config({"school": {"role": "school", "events": True, "tasks": False}})
    bridge.snapshot(config, date(2040, 1, 2))
    ranges = calls[0][1]["ranges"]
    assert len(ranges) == 2
    assert ranges[0]["start"].startswith("2040-01-02")
    assert ranges[1]["start"].startswith(date.today().isoformat())
    assert calls[0][1]["selection"] == config.sources
    with pytest.raises(DaylineError):
        bridge.snapshot(config, date.today(), 36)


def test_native_broker_round_trip_and_change_signal(monkeypatch, tmp_path):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    process = subprocess.Popen(
        [sys.executable, "-m", "dayline.native_host"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={**os.environ, "PYTHONPATH": str(__import__("pathlib").Path("src").resolve())},
    )
    try:
        for _ in range(100):
            if bridge.socket_path().exists():
                break
            if process.poll() is not None:
                pytest.fail(process.stderr.read().decode())
            time.sleep(0.01)
        assert stat.S_IMODE(bridge.socket_path().stat().st_mode) == 0o600
        with ThreadPoolExecutor(max_workers=1) as executor:
            result = executor.submit(bridge.request, "sources")
            command = bridge.read_message(process.stdout)
            assert command["command"] == "sources"
            # Two messages in one pipe burst catches buffered-stdin/selector deadlocks.
            burst = io.BytesIO()
            bridge.write_message(burst, {"event": "changed"})
            bridge.write_message(burst, {"id": command["id"], "result": {"sources": []}})
            process.stdin.write(burst.getvalue())
            process.stdin.flush()
            assert result.result(timeout=5) == {"sources": []}
        assert json.loads((cache_directory() / "bridge-change.json").read_text()) > 0
        process.stdin.close()
        assert process.wait(timeout=3) == 0
        assert not bridge.socket_path().exists()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def test_failed_provider_read_preserves_last_successful_snapshot(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    config = Config({"source": {"role": "personal", "events": True, "tasks": False}})
    write_json(
        cache_directory() / "snapshot.json", {"selection": config.sources, "items": ["last-good"]}
    )
    monkeypatch.setattr(
        bridge,
        "request",
        lambda *args, **kwargs: {
            "items": [],
            "errors": [{"source_id": "source", "message": "read failed"}],
        },
    )
    assert bridge.snapshot(config, date.today())["errors"]
    assert bridge.cached_snapshot(config)["items"] == ["last-good"]
