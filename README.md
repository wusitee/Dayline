# Dayline

Your schedule and tasks, at a glance.

Dayline is a lightweight native agenda for Hyprland. It is being built to combine
Outlook and Microsoft 365 calendars with Microsoft To Do, a desktop widget,
a toggleable agenda panel, Waybar integration, and reminders in SwayNC.

## Status

The repository contains the project scope, implementation plan, and development
workflow. The application is not implemented yet, so there is no install or run
command. The first milestone is Microsoft account authentication and data access.

## Planned experience

- A compact agenda on the desktop, behind application windows.
- A separate panel with a week calendar and task list, opened from Waybar or a
  dedicated shortcut and closed when no longer needed.
- Personal Outlook calendars and Microsoft To Do tasks, alongside a school or
  work Microsoft 365 calendar, including accessible subscribed timetables.
- Task creation, editing, and completion, plus event creation and editing on
  writable calendars.
- Ordinary desktop reminder notifications collected by SwayNC.
- Cached schedules for offline viewing and low background resource use.

The planned stack is Python, GTK4/PyGObject, gtk4-layer-shell, Microsoft Graph,
MSAL, and SQLite. Microsoft account access must be verified before the full
interface is built. Organizational consent restrictions and read-only calendar
subscriptions can limit access or editing.

## Documentation

- [Implementation plan and acceptance checks](docs/roadmap.md)
- [Git workflow and development](docs/development.md)

Repository-wide agent instructions are in [AGENTS.md](AGENTS.md).
