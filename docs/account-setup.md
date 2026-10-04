# Thunderbird bridge setup

## Prerequisites

Use a native Linux Thunderbird installation with TbSync and its required
provider already synchronizing both accounts. Confirm the personal Outlook
calendars, Microsoft To Do lists, HKU calendars, and subscribed timetable are
visible in Thunderbird. Dayline does not configure these accounts or copy their
credentials. Evolution and DavMail are not part of this connection route.

The experiment was developed against Thunderbird 156. The manifest permits
Thunderbird 140–156; live calendar/task reads, cloud-created tasks synchronized
by TbSync, explicit task alarms, offline reads, cached reads with Thunderbird
closed, and automatic reconnection after restart have been verified on 156.
Native provider writes and recurrence behavior are tested on 156 with Bridge
0.2.0 in an isolated storage calendar. Microsoft write acceptance remains
pending; older-version compatibility is unverified.
Flatpak/Snap native-host integration is outside the current setup instructions.

## Install

From the repository:

```sh
uv venv --python /usr/bin/python3 --system-site-packages
uv sync --frozen
uv run --frozen dayline install-bridge
```

This writes three user-local artifacts:

- `$XDG_DATA_HOME/dayline/dayline-bridge.xpi` (default
  `~/.local/share/dayline/dayline-bridge.xpi`): the add-on.
- `$XDG_DATA_HOME/dayline/native-host`: a launcher using the current Python
  environment.
- `~/.mozilla/native-messaging-hosts/io.github.wusitee.dayline.json`: the native
  host registration, restricted to `dayline@wusitee.github.io`.

Thunderbird's Linux native messaging lookup uses Mozilla's native-host directory,
not a directory inside a Thunderbird profile. Do not relocate the repository or
delete its virtual environment without reinstalling the host launcher.

In Thunderbird, open **Add-ons and Themes**, use the gear menu, select
**Install Add-on From File**, and choose the generated XPI. Accept the add-on's
permission prompt, then keep Thunderbird open. This changes no existing TbSync
account or calendar configuration.

[Thunderbird Experiment APIs](https://developer.thunderbird.net/add-ons/mailextensions/experiments)
require the broad “Have full, unrestricted access to Thunderbird, and your
computer” permission. Dayline's implementation accesses calendar APIs and native
messaging; it does not access mail, credentials, calendar subscription URLs, or
Microsoft tokens. That limited implementation does not narrow Thunderbird's
permission prompt.

After changing the add-on code, rebuild with `install-bridge` and reinstall the
XPI. Reloading the Python environment alone does not update the installed add-on.

## Choose sources

```sh
uv run --frozen dayline sources
```

Discovery lists metadata only: ID, name, provider type, color, enabled state,
read-only state, and event/task capabilities. It reads no calendar items.
Match IDs to Thunderbird's source names, then select each required calendar or
list:

```sh
uv run --frozen dayline select --source-id PERSONAL_CALENDAR_ID --role personal --events
uv run --frozen dayline select --source-id PERSONAL_TASK_LIST_ID --role personal --tasks
uv run --frozen dayline select --source-id HKU_CALENDAR_ID --role school --events
uv run --frozen dayline select --source-id HKU_TIMETABLE_ID --role school --events
```

The agenda panel's Sources page offers the same choices. Otherwise, replace the
placeholders with returned IDs. Repeat for every personal To Do
list and calendar. A source that contains both types can use `--events --tasks`.
Selecting an ID again replaces that ID's options; other IDs remain selected.
Dayline rejects `--role school --tasks` in both the CLI and the add-on.
Roles are user-assigned labels, not authenticated account ownership: choose
Personal only for sources belonging to the personal account.

Inspect or remove selections:

```sh
uv run --frozen dayline selection
uv run --frozen dayline unselect --source-id SOURCE_ID
```

Selections live in `$XDG_CONFIG_HOME/dayline/config.json` (default
`~/.config/dayline/config.json`, mode `0600`), outside the repository.

## Read and verify

```sh
uv run --frozen dayline read --start 2026-10-05 --days 7
uv run --frozen dayline cached
```

Use the desired week start instead of the example date. Reads expand calendar
recurrences within a bounded range of 1–35 days. The snapshot also includes
7 days before to 13 days after today for the compact widget, as a second range
when the requested days do not cover them. All selected personal tasks are included, even without due dates;
recurring tasks are returned as parent tasks rather than expanded indefinitely.

The successful snapshot lives in `$XDG_CACHE_HOME/dayline/snapshot.json`
(default `~/.cache/dayline/snapshot.json`, mode `0600`). A provider error produces
an explicit entry in `errors` and preserves the previous successful cache.
`cached` refuses data that does not match the current source selection.
A cached view is not proof of current Microsoft availability.

`generated_at` is the time Dayline read Thunderbird's local state, **not** the
last successful Microsoft sync. `offline` is Thunderbird's global offline flag.
Run TbSync synchronization in Thunderbird and compare items there before
claiming cloud freshness. The UI can create and edit items through Thunderbird;
TbSync owns their cloud synchronization. School sources default to read-only
in Dayline. For an owned, writable school calendar, select Allow edits in Sources
or use `select --role school --events --allow-edits`; keep subscribed timetables
read-only even if their EAS provider reports `read_only: false`. Use `--read-only`
to prevent writes to a selected personal source. See [editing](editing.md).

For acceptance, check that the snapshot includes a real class occurrence,
all-day events with exclusive end dates, and a task from every selected personal
list. Check source read-only flags and whether `alarms` contains actual reminder
times. Avoid posting complete JSON output publicly: it contains private titles,
notes, locations, and account-identifying source names.

## Troubleshooting and removal

If the bridge is unavailable, check that Thunderbird is open, Dayline Bridge is
enabled, and `install-bridge` ran from the environment you still use. The add-on
retries the native connection every ten seconds. Only one Thunderbird profile
can own the bridge at a time. Close other profiles if necessary.

A missing timetable or task list must be resolved in Thunderbird/TbSync first;
Dayline only reads sources that its calendar manager exposes. An empty result
with an `errors` entry is a failed read, not an empty calendar. Read-only sources
are valid for viewing. Disabled sources must be enabled before selection.

To remove the bridge, uninstall Dayline Bridge through Thunderbird, then delete
the generated native-host launcher, XPI, and native-host registration. Remove
Dayline's config and cache directories if you also want to erase saved schedules.
Do not remove Thunderbird/TbSync account data.
