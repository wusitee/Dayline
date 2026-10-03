# Native frontend handoff

## Scope and ownership

The frontend will be implemented separately with Opus. There is no maintained
frontend code yet. The implemented Python bridge and CLI provide the read path;
editing and reminders remain backend milestones requiring live validation.

Build a native Wayland interface with low idle CPU use. GTK4/PyGObject and
`gtk4-layer-shell` are available choices. Avoid Electron or another resident web
runtime. Reuse the existing Waybar and SwayNC installations.

## Required views

- **Desktop widget:** a small agenda on the background layer, behind application
  windows, showing today's/current/next events with time and location, a brief
  task list, and overdue/today counts. It must not steal keyboard focus.
- **Separate agenda panel:** toggleable, similar in presentation to SwayNC:
  readable dark surfaces, rounded cards, restrained transparency, a seven-day
  time grid, all-day events, and a personal task list. Give overlapping events
  separate lanes. Support week navigation, Today, source selection, item details,
  and eventually editing. Include undated tasks.
- **Integration:** one application instance; a Waybar button and dedicated
  shortcut toggle the same panel. Escape closes it. Preserve `Meta+N` for SwayNC;
  choose a different agenda shortcut. Notifications go to the actual SwayNC
  message center, not a second notification list inside Dayline.

Source colors identify calendars. Source selection must explicitly distinguish
Personal and School. Only Personal may enable tasks. Disable editing for
read-only sources, and identify recurrence occurrences separately from series.
The EAS provider currently reports the subscribed HKU timetable as writable.
Treat subscription sources as read-only until a backend safeguard is available;
a false `read_only` flag alone is not proof of cloud write permission.
Do not label a due-date filter as Microsoft To Do My Day synchronization.

## Implemented Python interface

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

Set a new mapping and call `Config.save()`. Match actual source capabilities and
prevent school task selection before saving. The CLI validates selections against
Thunderbird metadata. Do not infer account ownership from a calendar's display
name alone: let the user assign roles.

A connected add-on sends calendar-change signals through the broker, which
atomically replaces `$XDG_CACHE_HOME/dayline/bridge-change.json`. Monitor the
cache directory and debounce changes to that filename before fetching a new
snapshot. Monitoring `snapshot.json` and refreshing on each write would loop.
The change signal contains a timestamp only; it is not an item snapshot.
Refresh the compact widget's date range after local midnight. No extra Microsoft
client or credential access is needed.

## Snapshot contract

The schema below describes the current `0.1.0` read interface. Future extensions
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

A frontend preview can use synthetic data outside Git. Final acceptance requires
real source reads and checks on Hyprland: the widget stays behind applications,
the panel toggles from both entry points, overlapping and overnight events remain
readable, date-only/undated items survive, stale data is clearly marked, and the
notification-center shortcut remains unchanged. Measure Dayline's incremental
resource use and disclose Thunderbird's background dependency separately.
