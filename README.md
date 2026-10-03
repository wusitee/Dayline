# Dayline

Your schedule and tasks, at a glance.

Dayline is being built as a lightweight native agenda for Hyprland: a compact
desktop widget, a separate week-calendar and task panel, Waybar access, and
reminder notifications in SwayNC.

## Status

The Thunderbird bridge and diagnostic CLI are implemented, with live event and
personal-task reads verified in the current setup. The native frontend, editing,
and notification scheduler are not implemented yet. Cloud freshness, subscribed
calendar write permissions, task alarms, and restart/offline behavior still need
acceptance checks.

Dayline reuses calendars and tasks already synchronized by **Thunderbird and
TbSync**. Keep Thunderbird running for live reads and synchronization. Dayline
also saves a private snapshot for viewing while Thunderbird is closed. No
Evolution, DavMail, or separate Microsoft application registration is required
for this route.

## Getting started

With Thunderbird/TbSync already showing your calendars and To Do lists:

```sh
uv venv --python /usr/bin/python3
uv sync --frozen
uv run --frozen dayline install-bridge
```

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

## Intended experience

- A compact agenda behind application windows.
- A separate panel with a readable week calendar and personal task list,
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
- [Frontend handoff and data contract](docs/frontend.md)
- [Implementation plan and acceptance checks](docs/roadmap.md)
- [Git workflow and development](docs/development.md)

Repository-wide agent instructions are in [AGENTS.md](AGENTS.md).
