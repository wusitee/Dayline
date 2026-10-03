# Implementation plan

This is the versioned plan for Dayline. Only repository setup is complete; all
application milestones below are pending. Complete them in order and update this
checklist in the pull request that delivers each milestone.

## Product scope

Build one native application for a Hyprland/Wayland desktop, using
Python/PyGObject, GTK4, gtk4-layer-shell, Microsoft Graph, MSAL, and SQLite.
The application owns synchronization, cached data, both agenda views, and
reminders. Waybar launches or toggles the existing process rather than running
a separate Microsoft synchronization client.

| Source | Required behavior |
| --- | --- |
| Personal Outlook | Calendars and all Microsoft To Do lists/tasks; task and writable-event creation/editing; task completion. |
| School/work Microsoft 365 | Calendar events, including accessible subscribed timetable calendars; editing only where permitted. No To Do access required. |

The compact widget sits behind application windows. A separate toggleable panel
uses dark translucent surfaces and rounded cards, with a readable seven-day
calendar and task list. A wider view may open from the panel if needed for the
timetable. Keep `Meta+N` available for SwayNC; select a non-conflicting agenda
shortcut during desktop integration. Reminders arrive as normal notifications
in SwayNC and respect its Do Not Disturb setting.

Initial editing covers tasks and appointments. Invitation/attendee management
and an offline edit queue are outside the first version. Show tasks with only
due dates in a task/all-day area without inventing timed events. A Today view
must not claim exact Microsoft To Do My Day synchronization without API support.

## Milestones

- [x] **0. Repository foundation** — README, versioned roadmap, GitHub flow,
  pull-request template, repository policy, and scratch ignore rules.
  Validation: local documentation links, staged content, and whitespace checks.

- [ ] **1. Account access and Python project skeleton**
  - Branch: `feat/account-access`.
  - Add package metadata, a `src/dayline/` package, and a diagnostic CLI with
    account sign-in and source-listing commands. Document exact setup commands.
  - Use an application-owned Entra registration supporting organizational and
    personal accounts, browser sign-in with PKCE, MSAL silent refresh, and
    Secret Service-backed token persistence.
  - Separate account identities and tokens. Request calendar permissions for
    both accounts and task permissions only for the personal account.
  - **Done when:** both account sign-ins and token persistence work; the personal
    calendars and To Do lists can be read; school calendars and at least one
    real timetable occurrence can be read; available edit permissions are
    recorded. Test account isolation and explicit consent/authentication errors.
  - Add focused tests and CI for the code introduced, using synthetic data.
  - **Gate:** determine who can register the app and whether the school tenant
    grants access. If access is denied, record the actual failure and resolution
    needed. Test a direct timetable feed only if Graph access to the subscription
    fails and the feed is accessible. Do not claim live synchronization is
    validated until these account checks pass.

- [ ] **2. Local cache and synchronization**
  - Branch: `feat/sync-cache`; depends on milestone 1.
  - Add account-aware calendar/task models and SQLite storage in XDG user data
    directories. Normalize timed values and preserve all-day date boundaries.
  - Enumerate calendars and task lists, follow pagination, and retrieve bounded
    calendar views with expanded recurring events. Synchronize tasks using
    supported delta queries. Begin with a five-minute background refresh and
    manual refresh, honoring throttling and network failures.
  - Keep the most recent successful data and show its sync time while offline.
  - **Done when:** cache reload after restart works; recurring exceptions,
    cancellations, all-day boundaries, multiple lists/calendars, deletions,
    pagination, and account isolation are verified. Compare retrieved real
    calendar/task data with Outlook and To Do without committing personal data.

- [ ] **3. Native widget, agenda panel, and week calendar**
  - Branch: `feat/agenda-ui`; depends on milestone 2.
  - Add the desktop layer-shell widget, on-demand panel, seven-day time grid,
    all-day/task area, source colors, source visibility, and task list.
  - Show the current/next event with time and location, relevant upcoming tasks,
    and overdue/today counts in the compact widget.
  - Expose an application command for panel toggle, with Waybar and Hyprland
    configuration examples. Use one application instance; avoid focus stealing
    from the desktop widget. Close the panel with its shortcut or Escape.
  - **Done when:** both entry points work on Hyprland; the widget stays behind
    application windows; HiDPI sizing, overlapping events, long titles, empty
    calendars, undated tasks, and stale-cache state remain readable. Preserve
    the existing notification-center shortcut.

- [ ] **4. Task and writable-calendar editing**
  - Branch: `feat/editing`; depends on milestone 3.
  - Add task creation/editing/completion and appointment creation/editing,
    including supported due dates, notes, reminders, times, and locations.
  - Route writes by account and calendar/list identifiers. Disable editing for
    read-only sources. Distinguish a recurring-event occurrence from its series.
  - Refresh the affected item after successful writes; show failures and avoid
    displaying failed changes as synchronized. Keep first-version writes online.
  - **Done when:** controlled test-item changes round-trip through the correct
    account and match Outlook/To Do; account routing, read-only handling,
    recurrence targeting, and write failures have meaningful regression tests.
    Use clearly identified test items, with authorization, for live write checks.

- [ ] **5. SwayNC reminders**
  - Branch: `feat/reminders`; depends on milestone 4.
  - Schedule event and task alerts from their Microsoft reminder fields using
    cached data, independently of network refresh. Send standard desktop
    notifications that appear in SwayNC; clicking a reminder opens its item.
  - Persist fired-reminder identities, recompute after edits and resume, and
    suppress completed tasks and cancelled events. A due date alone is not an
    explicit alert time.
  - **Done when:** reminders appear in SwayNC at the expected local time;
    changed alerts, cancellation/completion, restart deduplication,
    suspend/resume, and Do Not Disturb behavior are verified.

- [ ] **6. Packaging, documentation, and resource verification**
  - Branch: `feat/packaging`; depends on milestone 5.
  - Provide repeatable Arch/Linux setup instructions, launch/autostart support,
    and example desktop integration files without machine-specific paths.
  - Document account setup, permission limitations, read-only timetables,
    reminder behavior, offline viewing, and troubleshooting actual failures.
  - Measure the complete process while idle and refreshing, with detail views
    closed and open. Starting targets: at most 100 MiB proportional set size with
    the compact widget visible and less than 0.5% of one CPU core averaged while
    idle. These are evaluation targets, not measured claims.
  - **Done when:** a clean setup works, the end-to-end account/UI/edit/reminder
    checks pass, resource results and any unmet targets are recorded, and no
    maintained code or workflow depends on scratch files.

## Execution and Git updates

Take the first unchecked milestone, follow its dependency gate, and commit
complete, validated changes on its branch. Update this document with acceptance
results and any remaining limitation in the same pull request. Push completed
work, squash-merge the reviewed pull request, then continue from updated `main`.
Do not skip account-access evidence or mark a milestone complete because its
code exists. Keep temporary logs and experiments out of Git.

## API references

- [Calendar views and recurring occurrences](https://learn.microsoft.com/en-us/graph/api/calendar-list-calendarview?view=graph-rest-1.0)
- [Microsoft To Do API](https://learn.microsoft.com/en-us/graph/api/resources/todo-overview?view=graph-rest-1.0)
- [MSAL Python sign-in and token acquisition](https://learn.microsoft.com/en-us/entra/msal/python/getting-started/acquiring-tokens)
- [Organizational consent](https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/user-admin-consent-overview)
