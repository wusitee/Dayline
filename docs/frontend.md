# Native frontend

## Overview

`dayline ui` runs a GTK 4 application with `gtk4-layer-shell`; it has no web
runtime. Code lives in `src/dayline/ui/`. Date, layout, and grouping logic is in
`src/dayline/agenda.py`, which does not import GTK and is tested headlessly.
Task and appointment editing uses Thunderbird providers. See [editing](editing.md)
for permissions, recurrence scope, and synchronization. Optional due-date task
reminders use desktop notifications; see [task reminders](reminders.md).

| Module | Responsibility |
| --- | --- |
| `ui/app.py` | Single instance, command-line actions, worker reads, change monitoring, state. |
| `ui/panel.py` | Regular application window and layer-shell desktop widget. |
| `ui/week.py` | Day headers, all-day events, task deadline rows, and the custom event grid. |
| `ui/agenda.py` | Day-grouped chronological agenda of events and dated tasks. |
| `ui/tasks.py` | Grouped task list and the desktop widget's compact agenda. |
| `ui/sources.py` | Source role, item-type, and editing permission selection. |
| `ui/editor.py` | Editable details card, scheduling controls, notes, and explicit recurrence scope. |
| `ui/datetime_fields.py` | Calendar and half-hour time pickers with interpreted previews. |
| `datetime_input.py` | Flexible local date/time parsing, duration calculation, and text suggestions. |
| `ui/notifications.py` | Asynchronous desktop notifications and task-opening actions. |
| `editing.py` | Local form values and patches preserving unchanged fields. |
| `reminders.py` | Due-date reminder schedule and persistent duplicate protection. |
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
| `dayline ui toggle-widget` | Show or hide the compact widget; starts and shows it if needed. |
| `dayline ui show` / `hide` | Show or hide the panel explicitly. |
| `dayline ui quit` | Stop the instance. |

Every command reaches the same `io.github.wusitee.Dayline` D-Bus application
instance; later invocations forward their action and exit.
[`examples/`](../examples) contains Hyprland (Lua and `hyprland.conf`) autostart and
`Super+A` panel and `Super+T` widget toggle examples, and a Waybar custom module.
`Super+N` remains SwayNC's. Hiding either view keeps the application running and
its data current; their visibility is independent. The Waybar button toggles the
compact widget, like `Super+T`. Use `Super+A` or click the widget's background to
open the full panel.

To install these integrations, replace `DAYLINE` in the example matching your
Hyprland configuration with the absolute path returned by `uv run --frozen
which dayline`. Add its startup handler and binding to your existing Hyprland
configuration. Merge the Waybar module into your existing configuration and add
`custom/dayline` to a modules list. Also merge `examples/waybar.css` into your
Waybar stylesheet and install Symbols Nerd Font. Some patched monospace fonts
draw this icon wider than its character cell, clipping it; the symbol font
preserves its width. Preserve existing bindings and modules.
Run `hyprctl reload`, check `hyprctl configerrors`, and reload Waybar with
`pkill -USR2 -x waybar`. Start `dayline ui` once for the current session;
the startup handler takes effect at the next login. Verify the Waybar button,
`Super+A`, and the existing SwayNC shortcut.

## Views

- **Desktop widget** (`dayline-widget` namespace, top layer, top-right): one
  day's events with times and locations, and the tasks due that day, plus the
  first stale or partial-data warning. Today omits finished events and adds
  overdue tasks. Completed tasks due on the selected day appear in a separate
  Completed section with checkmarks and struck-through titles; they do not count
  as due or overdue. Next 4 days groups unfinished tasks due on each of the four
  days after the selected date. Each date has a heading and every matching task
  remains reachable by scrolling. Task display does not require event coverage
  for that date; unavailable calendar dates are marked explicitly. The arrows or the scroll wheel browse from 7 days before to 13
  days after today; Today returns. It takes no keyboard focus or exclusive space,
  and stays above application windows, like SwayNC, but below fullscreen windows.
  Its layer surface has a fixed 320×640 size so day changes never
  trigger compositor resize animations; only the card inside changes height, and
  input outside the card passes through to the windows below. Clicking an event or
  task opens its details; clicking elsewhere opens the panel.
  Long agendas scroll within the fixed surface. While items overflow, the scroll
  wheel scrolls the card; use the arrows to change days. A fixed footer keeps
  New task and New event visible below the scrollable agenda. Each opens a
  creation dialog without opening the main window; Save creates the item.
- **Panel**: a regular, resizable GTK application window titled Dayline, with
  minimize, maximize, and close controls. The compositor manages its placement
  and focus. Closing it hides the window and keeps the desktop widget running.
  Week navigation and Today come before the week title, so they do not move.
  The view selector switches between **Week** and **Agenda**, keeping the
  selected calendar anchor. Week is a seven-day Monday-first event grid with
  up to three rows of all-day event spans. A separate task strip above the
  hourly grid shows unfinished tasks on their due dates, including timed
  deadlines with their local clock time. It shows four tasks per day; +N more
  opens every task for that date. Both sections have per-day overflow lists.
  Empty task columns remain aligned with the event grid. Task dates are
  available independently of loaded event ranges. Agenda groups events and
  all unfinished dated tasks by day, including deadlines outside the selected
  week and overdue tasks. Undated tasks have a No due date section. Events
  are shown from the calendar anchor onward within the loaded ranges; dates
  outside those ranges are explicitly marked Tasks only. All-day items come
  first, followed by timed items in chronological order. Overnight events
  appear on each day they overlap, with
  their displayed times clipped to that day. Empty days are marked explicitly.
  Refresh and Sources work in both views. The alarm button enables or disables
  automatic task reminders. The right column defaults to an Add task/event
  area: select Task or Event, enter a title, then use Add details or Enter to
  open a draft in the side editor. Save creates the item. Tasks switches the
  column to the grouped list of overdue, today, upcoming, and undated tasks.
  Add switches back to creation; clicking either active button hides the
  column. Opening the side editor reveals it until Save or Cancel, then
  restores the chosen column state. New task and New event also open drafts.
  Escape closes Sources or an idle editor, then the panel. The selected view is
  kept when returning from Sources or the editor and when reopening the window.
- **Item details**: desktop-widget and Week items first open the original
  details popover. Writable items offer Edit, which opens a fixed-size dialog
  with a scrollable form. It does not open the main window when used from the
  widget. Writable nonrecurring items opened from Agenda retain their editable
  side card beside the calendar. Date and time pickers, flexible input, duration,
  notes, and date suggestions are described in [editing](editing.md). Details
  popovers have a fixed width and scroll long content, with time,
  source, role, location, notes, explicit reminder times, and whether an event is
  one occurrence of a recurring series. `http` and `https` URLs in locations and
  notes are links opened in the default browser through `Gtk.UriLauncher`.
  Writable items offer Edit and unfinished tasks offer Complete task. Recurring
  events offer separate occurrence and series edits; task completion applies to
  the series. Explicit edits from these choices follow the same dialog or
  side-card placement. An editor dialog retains unsaved fields across snapshot
  refreshes and failed saves; Cancel, Escape, or closing it dismisses it when no
  write is pending. One details popover is open at a time: clicking another item replaces it in one
  click, clicking elsewhere closes it, and Escape closes it before the panel.
- **Sources**: lists Thunderbird metadata through the bridge. Each source is Off,
  Personal, or School; Tasks is available only for Personal sources that support
  tasks. Allow edits defaults to enabled for Personal and disabled for School;
  keep subscriptions disabled even if the provider reports them as writable.
  Saving applies only the rows you changed, merged into the selection on
  disk, so unchanged selections are kept as saved. That includes sources now
  disabled or missing in Thunderbird. Disabled sources can be turned Off but not
  newly selected. Missing sources are removed with `dayline unselect`.

The time grid includes all 24 hours. Opening Week starts at 07:00; scroll
up to see earlier hours or down to see later hours. Overlapping timed events,
including chains of overlaps, share a cluster and
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
- **Week outside the snapshot**: the event grid states that the week is unavailable;
  known tasks remain visible above it.

Task due dates at local midnight are treated as date-only, matching Microsoft To
Do. A task due today is not overdue until the next day. Due-date grouping is not
Microsoft To Do My Day.

The EAS provider can report subscribed timetables as writable. School sources
remain read-only in Dayline unless editing is explicitly enabled in Sources.
Provider metadata alone does not establish cloud write permission.

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

The schema below describes the current `0.2.0` interface. Future extensions
must preserve these fields or explicitly version the contract.

| Field | Meaning |
| --- | --- |
| `generated_at` | UTC ISO timestamp when Thunderbird's local snapshot was read. Not a Microsoft sync timestamp. |
| `offline` | Thunderbird's global offline flag. Does not prove individual account availability. |
| `ranges` | One or two `{start, end}` ISO timestamp ranges, each bounded. Events include occurrences from their union. |
| `selection` | The exact local source mapping used for this read. Added by the Python client. |
| `sources` | Selected existing sources with `id`, `name`, `type`, `color`, `read_only`, `disabled`, `events`, `tasks`, `role`, and effective Dayline `writable`. Capability flags differ from the user's selection flags. |
| `items` | Normalized event occurrences and parent tasks described below. |
| `errors` | `{source_id, message}` entries for removed, disabled, unsupported, or failed sources. A partial result must not be presented as a successful empty calendar. |

Each item contains:

| Field | Meaning |
| --- | --- |
| `uid`, `source_id`, `recurrence_id` | Stable routing identity. Recurrence ID is null for non-occurrences. Do not key items by title or UID alone. |
| `revision` | SHA-256 of the provider's canonical iCalendar representation; required for optimistic update checks. |
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

## Write and reminder contracts

`read_item(config, item, scope)` returns the current canonical item for an edit.
`write_item(config, command, item, fields, scope)` accepts `create` or `update`
and returns `{state: "local", cloud_confirmed: false, item: ...}`. They are
blocking bridge calls and use the same worker requirement as reads. The native
host reloads the source selection from disk for every write; a client-supplied
selection cannot grant additional permissions.

Creates require a stable UUID and `scope="item"`. Updates require the current
revision and explicitly choose `item`, `series`, or `occurrence`; occurrence
writes also require the recurrence ID. Supported event patches contain title,
start, end, location, description, and reminder; task patches contain title,
start, due, description, reminder, and completed. A null optional date clears it. Reminder
means an absolute DISPLAY alarm, not a due date. Only changed fields are sent;
unchanged alarms, recurrence rules, and provider-specific properties are kept.

Writes use Thunderbird calendar/provider APIs. Do not modify Thunderbird SQLite
files or edit snapshot JSON to simulate synchronization. Local acceptance is not
Microsoft confirmation; verify changes after TbSync's next successful sync.
See [editing](editing.md) for the user flow and write restrictions.

Returned `alarms` are explicit Thunderbird DISPLAY alarms. Optional Dayline
task reminders use due dates only when the task has no explicit alarm; they do
not change the snapshot or Thunderbird preferences. The scheduler persists
notification identities across restarts, suppresses cancelled/completed tasks,
and catches up still-relevant reminders after resume. Standard desktop
notifications allow SwayNC to handle history and Do Not Disturb. Explicit task
alarms and event reminders remain Thunderbird's responsibility.

## Acceptance

Final milestone acceptance requires the real-account checks on Hyprland listed in
the [roadmap](roadmap.md). Synthetic previews belong in `.scratch/`. Measure
Dayline's incremental resource use separately from Thunderbird's background cost.
