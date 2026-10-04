# Native frontend

## Overview

`dayline ui` runs a GTK 4 application with `gtk4-layer-shell`; it has no web
runtime. Code lives in `src/dayline/ui/`. Date, layout, and grouping logic is in
`src/dayline/agenda.py`, which does not import GTK and is tested headlessly.
Editing and reminders are not implemented; item details are read-only.

| Module | Responsibility |
| --- | --- |
| `ui/app.py` | Single instance, command-line actions, worker reads, change monitoring, state. |
| `ui/panel.py` | Layer-shell windows: overlay panel and desktop widget. |
| `ui/week.py` | Day headers, all-day rows, and the custom time-grid widget. |
| `ui/tasks.py` | Grouped task list and the desktop widget's compact agenda. |
| `ui/sources.py` | Source role and item-type selection. |
| `ui/widgets.py` | Shared helpers, source color classes, and the item-details popover. |
| `ui/style.css` | Dark SwayNC-like styling. |

## Requirements and running

Use the system Python with PyGObject, GTK 4, and `gtk4-layer-shell` (Arch:
`python-gobject`, `gtk4`, `gtk4-layer-shell`). The virtual environment must see
system packages:

```sh
uv venv --python /usr/bin/python3 --system-site-packages
uv sync --frozen
uv run --frozen dayline ui
```

The bridge and its CLI still work without GTK; only `dayline ui` imports it.
The compositor must support `wlr-layer-shell`. Hyprland 0.56 is tested.

| Command | Effect |
| --- | --- |
| `dayline ui` | Start the instance and show the desktop widget. |
| `dayline ui toggle` | Show or hide the panel; starts the instance if needed. |
| `dayline ui show` / `hide` | Show or hide the panel explicitly. |
| `dayline ui quit` | Stop the instance. |

Every command reaches the same `io.github.wusitee.Dayline` D-Bus application
instance; later invocations forward their action and exit.
[`examples/`](../examples) contains Hyprland (Lua and `hyprland.conf`) autostart and
`Super+A` toggle examples, and a Waybar custom module. `Super+N` remains SwayNC's.

To install these integrations, replace `DAYLINE` in the example matching your
Hyprland configuration with the absolute path returned by `uv run --frozen
which dayline`. Add its startup handler and binding to your existing Hyprland
configuration. Merge the Waybar module into your existing configuration and add
`custom/dayline` to a modules list. Preserve existing bindings and modules.
Run `hyprctl reload`, check `hyprctl configerrors`, and reload Waybar with
`pkill -USR2 -x waybar`. Start `dayline ui` once for the current session;
the startup handler takes effect at the next login. Verify the Waybar button,
`Super+A`, and the existing SwayNC shortcut.

## Views

- **Desktop widget** (`dayline-widget` namespace, top layer, top-right): one
  day's events with times and locations, and the tasks due that day, plus the
  first stale or partial-data warning. Today omits finished events and adds
  overdue tasks. The arrows or the scroll wheel browse from 7 days before to 13
  days after today; Today returns. It takes no keyboard focus or exclusive space,
  and stays above application windows, like SwayNC, but below fullscreen windows
  and the panel. Its layer surface has a fixed 320×640 size so day changes never
  trigger compositor resize animations; only the card inside changes height, and
  input outside the card passes through to the windows below. Clicking an event or
  task opens its details; clicking elsewhere opens the panel.
  Long agendas scroll within the fixed surface. While items overflow, the scroll
  wheel scrolls the card; use the arrows to change days.
- **Panel** (`dayline-panel` namespace, overlay layer): week navigation and Today
  (placed before the week title, so they do not move), refresh, Sources, a
  seven-day Monday-first time grid, up to three rows of
  all-day spans per week plus a per-day overflow list, and grouped personal tasks:
  overdue, due today, upcoming, and no due date. While open it takes keyboard
  focus exclusively, like SwayNC's control center. Escape closes Sources, then
  the panel.
- **Item details**: a fixed-width popover, as tall as its content, with time,
  source, role, location, notes, explicit reminder times, and whether an event is
  one occurrence of a recurring series. `http` and `https` URLs in locations and
  notes are links opened in the default browser through `Gtk.UriLauncher`, which
  also closes the panel.
  One details popover is open at a time: clicking another item replaces it in one
  click, clicking elsewhere closes it, and Escape closes it before the panel.
- **Sources**: lists Thunderbird metadata through the bridge. Each source is Off,
  Personal, or School; Tasks is available only for Personal sources that support
  tasks. Saving applies only the rows you changed, merged into the selection on
  disk, so unchanged selections are kept as saved. That includes sources now
  disabled or missing in Thunderbird. Disabled sources can be turned Off but not
  newly selected. Missing sources are removed with `dayline unselect`.

The time grid shows 07:00–21:00, widened to whole hours covering the week's
earliest start and latest end. Rows stretch to fill the panel and scroll only
when the range does not fit. Overlapping timed events, including chains of overlaps, share a cluster and
split its width into lanes. Events are clipped at local midnight and placed by
local wall-clock time, so they match the hour labels on daylight-saving days. Blocks shorter
than 30 minutes are laid out as 30 minutes so titles remain readable. Source
colors come from Thunderbird; non-hex colors fall back to a neutral color.

## Data flow and freshness

Before each read and when Sources opens or saves, the instance reloads
`config.json`, so CLI `select`/`unselect` changes take effect at the next
refresh. An invalid file is reported and the last valid selection is kept.
Startup shows the matching saved snapshot, then reads the current week through a
single worker thread. GTK's main thread never blocks on the bridge. Results from
before a selection change are discarded. The cache directory is monitored for
the change signal only. Bursts are debounced for 1.5 seconds into one read,
so snapshot writes never trigger refresh loops. A one-minute tick updates current
events, overdue tasks, and the now line, and refreshes after a local date change,
including after resume.

The panel distinguishes these states with a banner:

- **Live read**: “Updated HH:MM”.
- **Saved snapshot**: shown at startup, or when the bridge is unavailable, with the
  read time and the bridge error.
- **Partial read**: each failed source is named, and its items are reported as
  missing. When a previous complete snapshot exists, the banner offers it.
- **Thunderbird offline**: items reflect Thunderbird's local copy.
- **Week outside the snapshot**: the grid states that the week is unavailable
  instead of showing an empty week.

Task due dates at local midnight are treated as date-only, matching Microsoft To
Do. A task due today is not overdue until the next day. Due-date grouping is not
Microsoft To Do My Day.

The subscribed HKU timetable is reported as writable by the EAS provider. No
editing is exposed, so this does not yet affect the UI; editing must treat
subscriptions as read-only until a backend safeguard exists.

## Bridge interface

```python
from datetime import date
from dayline.bridge import cached_snapshot, request, snapshot
from dayline.config import Config

config = Config.load()
sources = request("sources")["sources"]  # Metadata only; requires Thunderbird.
data = cached_snapshot(config)  # Dict or None; no network/native request.
data = snapshot(config, date(2026, 10, 5), days=7)
```

`request`/`snapshot` are blocking calls with a 25-second socket timeout. Use a
worker, never GTK's main thread. Source selection is `Config.sources`, a mapping
from Thunderbird calendar ID to:

```json
{"role": "personal", "events": true, "tasks": false}
```

Set a new mapping and call `Config.save()`. `config.check_selection(options,
source)` enforces role, item-type, and capability rules for both the CLI and the
Sources page. Do not infer account ownership from a calendar's display name
alone: let the user assign roles.

A connected add-on sends calendar-change signals through the broker, which
atomically replaces `$XDG_CACHE_HOME/dayline/bridge-change.json`
(`bridge.CHANGE_SIGNAL`). The signal contains a timestamp only; it is not an item
snapshot. Refreshing on `snapshot.json` writes instead would loop.

## Snapshot contract

The schema below describes the current `0.1.1` read interface. Future extensions
must preserve these fields or explicitly version the contract.

| Field | Meaning |
| --- | --- |
| `generated_at` | UTC ISO timestamp when Thunderbird's local snapshot was read. Not a Microsoft sync timestamp. |
| `offline` | Thunderbird's global offline flag. Does not prove individual account availability. |
| `ranges` | One or two `{start, end}` ISO timestamp ranges, each bounded. Events include occurrences from their union. |
| `selection` | The exact local source mapping used for this read. Added by the Python client. |
| `sources` | Selected existing sources with `id`, `name`, `type`, `color`, `read_only`, `disabled`, `events`, `tasks`, and `role`. Capability flags differ from the user's selection flags. |
| `items` | Normalized event occurrences and parent tasks described below. |
| `errors` | `{source_id, message}` entries for removed, disabled, unsupported, or failed sources. A partial result must not be presented as a successful empty calendar. |

Each item contains:

| Field | Meaning |
| --- | --- |
| `uid`, `source_id`, `recurrence_id` | Stable routing identity. Recurrence ID is null for non-occurrences. Do not key items by title or UID alone. |
| `kind` | `event` or `task`. |
| `title`, `location`, `description` | Plain text. Escape before displaying in markup. |
| `start`, `end`, `due` | Null, `YYYY-MM-DD` for date-only values, or UTC ISO timestamps for timed values. Events use start/end; tasks use start/due. |
| `completed`, `cancelled` | Suppress completed tasks and cancelled events from the normal upcoming view and reminder scheduling. |
| `recurring` | Recurrence metadata exists. Task series are not expanded into infinite instances. |
| `alarms` | Explicit DISPLAY alarm times calculated by Thunderbird, in ISO form; an empty array means no supported alert was returned. |

All-day `end` is exclusive. Preserve date-only values as local dates rather than
converting them to UTC midnight. Convert timed timestamps to the display's local
time zone, clip multi-day events to each visible day, and deduplicate by source,
UID, recurrence ID, and start time. The bridge already deduplicates overlapping
requested ranges.

Source errors do not replace the last successful saved snapshot. On an error,
show a clear failed/partial state and offer the last matching cache as such.
After source selection changes, `cached_snapshot` returns None until a matching
read succeeds. Viewing requires no live connection once a matching cache exists;
refresh and future edits require Thunderbird.

## Pending write and reminder contracts

No write command is implemented yet. Do not modify Thunderbird SQLite files or
edit snapshot JSON to simulate synchronization. Backend writes must go through
Thunderbird calendar/provider APIs, preserve unrelated item fields, respect
read-only permissions, and target the correct recurrence occurrence or series.
TbSync's local acceptance is not cloud confirmation; verify changes after its
next successful sync.

Reminders will use the returned explicit alarm times. Do not invent alerts from
due dates alone. Persist deduplication across restarts, suppress cancelled or
completed items, handle resume and changed alarms, and coordinate Thunderbird's
own alerts to prevent duplicates. Use standard desktop notifications so SwayNC
handles history and Do Not Disturb.

## Acceptance

Final milestone acceptance requires the real-account checks on Hyprland listed in
the [roadmap](roadmap.md). Synthetic previews belong in `.scratch/`. Measure
Dayline's incremental resource use separately from Thunderbird's background cost.
