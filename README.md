# Dayline

Your schedule and tasks, at a glance.

Dayline is being built as a lightweight native agenda for Hyprland: a compact
desktop widget, a separate calendar and task window, Waybar access, and
reminder notifications in SwayNC.

## Status

The Thunderbird bridge and diagnostic CLI are implemented, with live event and
personal-task reads verified in Thunderbird 156, including cloud-created tasks,
explicit reminders, undated tasks, reads in Thunderbird's offline mode,
cached reads with Thunderbird closed, and automatic reconnection after restart.
A native GTK frontend provides a desktop widget and a regular, resizable window
with week and agenda views, separate task rows above the event grid, an optional
Add/Tasks sidebar, and popup editing and creation from the widget. It supports task
creation, editing, completion, and appointment editing. Saves are accepted locally
by Thunderbird; Microsoft confirmation requires TbSync synchronization. Optional
task reminders notify through SwayNC
at 09:00 for date-only deadlines or 30 minutes before timed deadlines. A separate
opt-in delivers explicit calendar/task alarms; Thunderbird may also alert. School
calendar editing requires an explicit opt-in; subscriptions should remain read-only.

Dayline reuses calendars and tasks already synchronized by **Thunderbird and
TbSync**. Keep Thunderbird running for live reads and synchronization. Dayline
also saves a private snapshot for viewing while Thunderbird is closed. No
Evolution, DavMail, or separate Microsoft application registration is required
for this route.

## Getting started

With Thunderbird/TbSync already showing your calendars and To Do lists:

```sh
uv venv --python /usr/bin/python3 --system-site-packages
uv sync --frozen
uv run --frozen dayline install-bridge
```

The agenda UI also needs the system's PyGObject, GTK 4, and `gtk4-layer-shell`.

Install the generated `dayline-bridge.xpi` through Thunderbird's Add-ons Manager,
then run:

```sh
uv run --frozen dayline sources
```

Choose sources explicitly before reading items. Personal sources can supply
calendars and tasks; school sources supply calendars only. See
[bridge setup](docs/account-setup.md) for installation, source selection, and
reading a snapshot. The bridge is an experimental Thunderbird add-on and
requires its unrestricted-access permission prompt.

Start the agenda and toggle its panel:

```sh
uv run --frozen dayline ui
uv run --frozen dayline ui toggle
uv run --frozen dayline ui toggle-widget
```

Sources can also be chosen in the panel. See [examples](examples) for Hyprland
autostart, `Super+A` for the full panel, `Super+T` for the compact widget, and a
Waybar button.

## Intended experience

- A compact agenda above application windows, like SwayNC's notifications.
- A separate app window with week and agenda views and a personal task list,
  toggled from Waybar or a dedicated shortcut.
- Personal Outlook calendars and Microsoft To Do lists, alongside HKU calendars
  and the subscribed class timetable already visible in Thunderbird.
- Task creation, editing, and completion; event editing on writable calendars.
- Reminder notifications collected by SwayNC.

The UI should use native Wayland components without a resident web runtime.
Thunderbird remains a running dependency for live updates; lightweight Dayline
code does not remove Thunderbird's resource cost. Resource use is unmeasured.

## Documentation

- [Bridge setup and diagnostics](docs/account-setup.md)
- [Native frontend and data contract](docs/frontend.md)
- [Editing and synchronization](docs/editing.md)
- [Task reminders](docs/reminders.md)
- [Implementation plan and acceptance checks](docs/roadmap.md)
- [Git workflow and development](docs/development.md)

Repository-wide agent instructions are in [AGENTS.md](AGENTS.md).
