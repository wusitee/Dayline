# Agent access through MCP

`dayline mcp` exposes local stdio tools for Codex, Claude Code, and other MCP
clients. It uses the same private Thunderbird bridge as the native UI. The agent
can discover sources, read events and tasks, create items, edit them, and complete
or reopen tasks. The GTK UI does not need to be running. Thunderbird and the
Dayline Bridge add-on must be running for live reads and writes.

## Install and connect

MCP support is optional. Install it in the environment that runs Dayline:

```sh
uv sync --frozen --extra mcp
DAYLINE_ROOT="$PWD"
DAYLINE_UV="$(command -v uv)"
```

For a standalone wheel, install its extra instead:

```sh
uv pip install --python ~/.local/share/dayline/venv/bin/python '/path/to/dayline.whl[mcp]'
DAYLINE_BIN="$HOME/.local/share/dayline/venv/bin/dayline"
```

Replace the wheel placeholder with the actual versioned filename. Use an
absolute executable path so the client can launch Dayline from any directory.
Installing the extra does not change source selections or require an add-on
upgrade. Choose sources and editing permissions in Dayline's Sources page or
with the [existing CLI](account-setup.md) before accessing items.

Run registration from your Linux desktop session. Pass `XDG_RUNTIME_DIR`
explicitly because MCP clients may filter their subprocess environment:

```sh
codex mcp add dayline --env "XDG_RUNTIME_DIR=$XDG_RUNTIME_DIR" -- \
  "$DAYLINE_UV" --directory "$DAYLINE_ROOT" run --frozen --extra mcp dayline mcp
claude mcp add --transport stdio --scope user dayline \
  --env "XDG_RUNTIME_DIR=$XDG_RUNTIME_DIR" -- \
  "$DAYLINE_UV" --directory "$DAYLINE_ROOT" run --frozen --extra mcp dayline mcp
```

These checkout commands explicitly retain the optional extra when uv synchronizes
the environment. For a standalone wheel, replace the launch command after `--`
with `"$DAYLINE_BIN" mcp`.

If you use custom `XDG_CONFIG_HOME` or `XDG_CACHE_HOME`, pass their absolute
values as additional `--env NAME=VALUE` arguments so the agent uses the same
selection and cache as the UI. The client must run on the same machine and as
the same user as Thunderbird. The server uses stdin/stdout for MCP and stderr
for diagnostics; it does not listen on a network port.

Start a new client session, then check `/mcp` and ask it to list Dayline sources
or show today's events and unfinished tasks. See the official
[Codex MCP guide](https://developers.openai.com/codex/mcp/) and
[Claude Code MCP guide](https://code.claude.com/docs/en/mcp) for client configuration.
Each client starts its own small server process. Other stdio clients can launch
the same executable with the single argument `mcp`.

## Tools and data

| Tool | Behavior |
| --- | --- |
| `list_sources` | Thunderbird source metadata, current Dayline `selection`, and effective source `writable` flags. Does not read items. |
| `list_items` | Live events from a local date range and all selected personal tasks, including completed and undated tasks. Optional `kind`, `source_id`, and plain-text `query` filters. |
| `read_cached_snapshot` | The native UI/CLI's last saved snapshot, only when it matches current selections. Always reports `freshness: "cached"`. |
| `get_item` | A fresh canonical item and its revision, using an explicit scope. |
| `create_item` | A nonrecurring event or task, using a caller-chosen UUID to prevent duplicate creation across retries. |
| `update_item` | Changed fields only, with a required revision and scope. Includes task completion and reopening. |

`list_items` defaults to today and seven days; `days` must be 1–35. Its date
range limits events only. Task reads include all tasks from the selected lists.
`query` matches title, description, or location without interpreting search
syntax. Live MCP reads do not replace the UI's offline snapshot.

Read results preserve the [snapshot/item contract](frontend.md#snapshot-contract).
Always inspect `errors`: provider failures yield partial data, not a successful
empty calendar. `offline` is Thunderbird's global state. `freshness: "live"`
means a new local provider read, not Microsoft cloud confirmation. Cached
results retain their original `generated_at` and event `ranges`; they must be
presented as saved data. Live reads never silently fall back to the cache.

An item reference contains only `source_id`, `kind` (`event` or `task`), `uid`,
and optional `recurrence_id`. Use `get_item` before updating and pass its
returned `revision` separately. Scope is required: `item` for nonrecurring
items, `occurrence` with a recurrence ID for a single recurring event, or
`series` for the parent. Recurring task edits and completion use `series`.

For example, to complete a nonrecurring task after reading its canonical item:

```json
{
  "item": {"source_id": "SOURCE_ID", "kind": "task", "uid": "TASK_UID"},
  "scope": "item",
  "revision": "REVISION_FROM_GET_ITEM",
  "fields": {"completed": true}
}
```

## Writes and permissions

Every call reloads Dayline's saved source selections. The server provides no
tools to select additional sources or grant editing permissions. Personal
sources permit writes by default; school calendars require the user's explicit
opt-in and cannot supply tasks. Keep subscriptions read-only. The native broker
reloads write permissions independently, and Thunderbird checks source state,
item ACLs, attendees, and revision conflicts. See [editing](editing.md).

Creation requires `source_id`, `kind`, a new `uid` UUID, and `fields` with a
nonempty `title`. Events also require `start` and `end`; task dates are optional.
Retain the same UUID across retries. If creation times out or reports that the
UUID already exists, read that UID before deciding what to do next.

Supported fields are `title`, `description`, `start`, and `reminder`, plus
`end`/`location` for events or `due`/`completed` for tasks. Dates are
`YYYY-MM-DD` or ISO timestamps with an explicit timezone. All-day event ends
are exclusive; date-only task deadlines include that day. Reminders require a
timed value. Omitted fields are preserved. `null` clears optional dates and
reminders; empty text clears notes/location. An edited reminder replaces DISPLAY
alarms; untouched alarms and provider properties are preserved. Set
`completed: false` to reopen a task.

Updates require the revision from `get_item`. A conflict is a tool error;
the server never automatically rereads and retries the write. Review the latest
item before retrying. Successful writes return `state: "local"` and
`cloud_confirmed: false`. TbSync owns upload and retries; local acceptance does
not prove cloud delivery. Existing bridge change signals refresh a running UI.
Deletion, creating recurrence rules, and invitation management remain in Thunderbird.

## Troubleshooting

If the client cannot start the server, verify its absolute executable path and
install the `mcp` extra in that environment. Launching `dayline mcp` directly
waits for protocol input; it is not an interactive terminal command.

A bridge-unavailable tool error means Thunderbird is closed, its add-on is
disabled, or the client lacks the correct `XDG_RUNTIME_DIR`. Use the
[bridge diagnostics](account-setup.md#troubleshooting-and-removal). Explicit
cached reads still work when a selection-matching snapshot exists. After changing
an executable path or the client environment, update registration and restart
the client session.
