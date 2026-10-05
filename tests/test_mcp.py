import os
import sys
from pathlib import Path

import pytest
from mcp import Client, StdioServerParameters

from dayline import bridge
from dayline.config import Config, cache_directory, write_json
from dayline.errors import DaylineError
from dayline.mcp_server import server

TASK = {"source_id": "personal", "kind": "task", "uid": "task-uid"}
EVENT = {
    "source_id": "school",
    "kind": "event",
    "uid": "event-uid",
    "recurrence_id": "2026-10-05T03:00:00Z",
}
CREATION_ID = "2a1b3baa-0555-4c68-824c-caaeb069036e"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def private_config(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    config = Config(
        {
            "personal": {"role": "personal", "events": False, "tasks": True},
            "school": {"role": "school", "events": True, "tasks": False},
        }
    )
    config.save()
    return config


@pytest.mark.anyio
async def test_live_reads_narrow_selected_types_and_preserve_partial_results(
    monkeypatch, private_config
):
    calls = []

    def request(command, **arguments):
        calls.append((command, arguments))
        if command == "sources":
            return {
                "sources": [
                    {"id": uid, "read_only": False, "disabled": False}
                    for uid in ("personal", "school", "unselected")
                ]
            }
        return {
            "generated_at": "2026-10-05T01:00:00Z",
            "offline": True,
            "ranges": arguments["ranges"],
            "items": [{**TASK, "title": "课程", "due": None}, {**TASK, "title": "Other"}],
            "errors": [{"source_id": "personal", "message": "Partial provider failure"}],
        }

    monkeypatch.setattr(bridge, "request", request)
    async with Client(server, raise_exceptions=True) as client:
        sources = (await client.call_tool("list_sources")).structured_content
        assert sources["selection"] == private_config.sources
        assert [s["writable"] for s in sources["sources"]] == [True, False, False]
        result = await client.call_tool(
            "list_items",
            {
                "start": "2026-10-05",
                "days": 2,
                "kind": "task",
                "query": "课程",
            },
        )
        data = result.structured_content
        assert not result.is_error
        assert data["freshness"] == "live" and data["offline"]
        assert len(data["items"]) == 1 and data["items"][0]["due"] is None
        assert data["errors"][0]["message"] == "Partial provider failure"
        assert calls[-1][1]["selection"] == {"personal": private_config.sources["personal"]}
        assert len(data["ranges"]) == 1
        assert data["ranges"][0]["start"].startswith("2026-10-05T00:00:00")
        assert data["ranges"][0]["end"].startswith("2026-10-07T00:00:00")
        for arguments in ({"days": 36}, {"days": "7"}, {"source_id": "unselected"}):
            assert (await client.call_tool("list_items", arguments)).is_error
        assert len(calls) == 2


@pytest.mark.anyio
async def test_writes_keep_identity_scope_revision_and_explicit_patch_fields(
    monkeypatch, private_config
):
    calls = []

    def request(command, **arguments):
        calls.append((command, arguments))
        if command == "item":
            return {"item": {**TASK, "revision": "fresh", "title": "Task"}}
        if arguments.get("revision") == "stale":
            raise DaylineError("This item changed since it was opened; reopen it before saving.")
        return {"state": "local", "cloud_confirmed": False, "item": {**TASK, **arguments["fields"]}}

    monkeypatch.setattr(bridge, "request", request)
    async with Client(server, raise_exceptions=True) as client:
        created = await client.call_tool(
            "create_item",
            {
                "source_id": "personal",
                "kind": "task",
                "uid": CREATION_ID,
                "fields": {"title": "Task", "due": "2026-10-05"},
            },
        )
        assert created.structured_content["cloud_confirmed"] is False
        assert calls[-1][1]["uid"] == CREATION_ID
        assert calls[-1][1]["scope"] == "item"
        fresh = await client.call_tool("get_item", {"item": TASK, "scope": "series"})
        result = await client.call_tool(
            "update_item",
            {
                "item": TASK,
                "scope": "series",
                "revision": fresh.structured_content["item"]["revision"],
                "fields": {"completed": True, "due": None, "description": ""},
            },
        )
        assert not result.is_error and result.structured_content["state"] == "local"
        assert calls[-1][1]["fields"] == {"completed": True, "due": None, "description": ""}
        assert calls[-1][1]["revision"] == "fresh"
        assert calls[-1][1]["selection"] == private_config.sources
        await client.call_tool("get_item", {"item": EVENT, "scope": "occurrence"})
        assert calls[-1][1]["recurrence_id"] == EVENT["recurrence_id"]
        conflict = await client.call_tool(
            "update_item",
            {
                "item": TASK,
                "scope": "series",
                "revision": "stale",
                "fields": {"completed": False},
            },
        )
        assert conflict.is_error and "changed since" in conflict.content[0].text
        assert len(calls) == 5  # A conflict never triggers an automatic reread/retry.


@pytest.mark.anyio
async def test_permissions_reload_and_invalid_writes_never_reach_bridge(
    monkeypatch, private_config
):
    calls = []
    monkeypatch.setattr(bridge, "request", lambda *a, **kw: calls.append((a, kw)))
    arguments = {"item": TASK, "scope": "item", "revision": "fresh", "fields": {"completed": True}}
    async with Client(server, raise_exceptions=True) as client:
        for invalid in (
            {**arguments, "fields": {"completed": "true"}},
            {**arguments, "fields": {"unsupported": "value"}},
            {key: value for key, value in arguments.items() if key != "revision"},
        ):
            assert (await client.call_tool("update_item", invalid)).is_error
        denied = await client.call_tool("update_item", {**arguments, "item": EVENT})
        assert denied.is_error and "read-only" in denied.content[0].text
        private_config.sources["personal"]["writable"] = False
        private_config.save()
        denied = await client.call_tool("update_item", arguments)
        assert denied.is_error and "read-only" in denied.content[0].text
        private_config.sources.pop("personal")
        private_config.save()
        assert (await client.call_tool("get_item", {"item": TASK, "scope": "item"})).is_error
        assert (
            await client.call_tool(
                "create_item",
                {
                    "source_id": "personal",
                    "kind": "task",
                    "uid": CREATION_ID,
                    "fields": {"title": "Task"},
                },
            )
        ).is_error
    assert calls == []


@pytest.mark.anyio
async def test_stdio_cli_legacy_client_cache_and_unavailable_bridge(private_config, tmp_path):
    snapshot = {
        "selection": private_config.sources,
        "items": [{**TASK, "title": "Saved task"}],
        "generated_at": "2026-10-01T00:00:00Z",
        "ranges": [],
    }
    write_json(cache_directory() / "snapshot.json", snapshot)
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "dayline", "mcp"],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(Path("src").resolve())},
    )
    async with Client(parameters, mode="legacy", read_timeout_seconds=10) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
        assert set(tools) == {
            "list_sources",
            "list_items",
            "get_item",
            "create_item",
            "update_item",
            "read_cached_snapshot",
        }
        assert tools["get_item"].annotations.read_only_hint
        assert tools["update_item"].annotations.read_only_hint is False
        assert "revision" in tools["update_item"].input_schema["required"]
        cached = await client.call_tool("read_cached_snapshot")
        assert cached.structured_content == {**snapshot, "freshness": "cached"}
        unavailable = await client.call_tool("list_items")
        assert (
            unavailable.is_error and "Thunderbird bridge unavailable" in unavailable.content[0].text
        )
        private_config.sources.pop("personal")
        private_config.save()
        removed = await client.call_tool("read_cached_snapshot")
        assert removed.is_error and "No snapshot matches" in removed.content[0].text
