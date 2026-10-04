# Implementation plan

This is the user-requested versioned plan for Dayline. Update acceptance results
in the pull request delivering each milestone. Code availability alone does not
complete an account-dependent milestone.

## Architecture and scope

Thunderbird and TbSync already hold the personal Outlook calendars/To Do lists
and HKU calendars, including the subscribed class timetable. Reuse that working
sync path. A small Thunderbird Experiment add-on exposes calendar-manager reads
through a Python native-messaging broker and private Unix socket. Dayline stores
an offline snapshot and explicit source selections, never Microsoft credentials.
Do not write directly to Thunderbird's database.

The native frontend is assigned to Opus. It owns a compact desktop widget above
application windows and a separate toggleable calendar/task window, with
Waybar access. Preserve `Meta+N` for SwayNC. Reminders become ordinary desktop
notifications collected by SwayNC. Avoid a resident web runtime.

| Source | Required behavior |
| --- | --- |
| Personal Outlook | Selected calendars and every selected Microsoft To Do list; task creation/editing/completion and writable-event creation/editing. |
| HKU Microsoft 365 | Selected calendars and subscribed timetable; editing only on writable calendars. No school task access. |

Initial editing covers tasks and appointments; invitation management is outside
this version. TbSync owns the synchronization queue. Distinguish local acceptance
from Microsoft confirmation instead of promising immediate cloud writes.

## Milestones

- [x] **0. Repository foundation** — README, roadmap, GitHub flow, PR template,
  canonical repository policy, and ignored scratch directory. Initial commit
  is signed and pushed.

- [x] **1. Thunderbird bridge and live reads**
  - Branch: `feat/thunderbird-bridge`.
  - [x] Python package/CLI, native messaging framing, private socket broker,
    installable XPI, source discovery/selection, bounded recurrence reads, all
    selected personal task lists, explicit errors, focused tests, and CI.
  - [x] Private atomic offline snapshot, selection-matching cache reads, and
    preservation of the last successful cache after provider errors.
  - [x] Document setup and the frontend contract; remove the superseded
    Evolution dependency from the implementation.
  - [x] Load the bridge in Thunderbird 156, enumerate real sources, select all
    exposed personal calendars/lists and HKU event sources, and successfully read
    real class-timetable events, recurring events, and personal tasks. No school
    task source is selected; successful snapshots are stored privately.
  - [x] Read two cloud-created Microsoft To Do tasks after TbSync synchronization:
    one with an explicit reminder and one without dates. Preserve both and
    observe the calendar-change signal after synchronization.
  - [x] Verify recurring/all-day events, event and task alarm preservation,
    source flags, and successful reads in Thunderbird's offline mode.
  - [x] Verify cached reads through Python and the CLI with Thunderbird fully
    closed, actionable live-request errors while unavailable, and automatic
    reconnection with a refreshed snapshot after reopening.
  - [x] Verify Bridge 0.1.1 preserves actionable validation messages across
    Thunderbird's Experiment boundary, including rejection of school tasks.
  - **Done when:** these live checks pass and any missing provider capability is
    recorded. The bridge is loaded and live read access is verified on
    Thunderbird 156. The subscribed HKU timetable is exposed as writable by the
    EAS provider; this is not proof of cloud write permission and requires a
    safeguard before editing. Fourteen Python tests and five JavaScript contract
    tests pass, including a subprocess broker round trip.

- [x] **2. Native frontend — Opus**
  - Branch: `feat/agenda-ui`; implementation in [frontend](frontend.md).
  - [x] GTK 4/layer-shell desktop widget, regular app window, seven-day time grid with
    overlap lanes and midnight clipping, all-day spans, grouped personal tasks
    including undated tasks, Sources page enforcing Personal-only tasks, and
    read-only item details. Layout/grouping/freshness tests.
  - [x] Worker-thread reads, debounced change-signal refresh, date rollover,
    marked saved/partial/offline/out-of-range states, single-instance commands,
    Escape, and Hyprland/Waybar examples using `Super+A`.
  - [x] On Hyprland 0.56 at scale 2 with real Thunderbird data: both views show
    the timetable, all-day holiday, and tasks; `dayline ui toggle` works from a
    second process; a burst of change signals caused one read; Escape closes the
    panel. With the widget visible, the instance used 68 MiB PSS and about 0.03%
    of one core over 60 idle seconds.
  - [x] The widget stays above application windows on the top layer with a fixed
    surface size; it browses days around today and opens item details. Details
    popovers switch in one click and open links in the default browser. Week
    changes keep the main thread responsive during a slow read.
  - [x] Install the Waybar module and Hyprland startup/binding without configuration
    errors. Wayland input verified `Super+A`, Escape, the Waybar button, and
    `Super+N` opening SwayNC. The GTK views correctly mark an empty selection, an unavailable
    bridge with saved data, and a partial live read with a removed source.
  - **Done when:** real schedules appear in both views on Hyprland; overlap,
    overnight/all-day events, long titles, undated tasks, empty selections,
    stale/partial results, and HiDPI sizing are readable. Both launch paths work
    without changing the SwayNC shortcut.

- [x] **3. Task and calendar writes**
  - Branch: `feat/editing`; depends on verified live reads.
  - [x] Add task creation/editing/completion and writable-event creation/editing via
    Thunderbird's provider API, including supported dates, notes, event locations,
    and reminder settings. Preserve fields not edited by Dayline.
  - [x] Enforce selected source/type/role, read-only state, and item identity in the
    backend. Explicitly distinguish recurrence occurrence from series edits.
  - [x] Expose provider failures, conflicts, and local acceptance truthfully.
    Native Thunderbird 156 storage-provider probes verify fields, alarms,
    completion, recurrence response identity, floating dates, and DST wall time.
  - [x] Create and edit controlled tasks in both selected personal To Do lists
    and a personal appointment, synchronize through TbSync, and independently
    fetch Microsoft's server copies through the installed EAS provider. Verify
    titles, dates, notes, event location, reminders, and task completion. Remove
    the test items and confirm server removal. Invalid dates, stale revisions,
    and school writes without opt-in are rejected without changing the item.
  - **Done when:** controlled, clearly identified test items round-trip through
    the correct account and are confirmed by Microsoft server reads; permission rejection,
    recurrence targeting, completion, and failed writes are tested. Do not mark
    local cache changes as Microsoft confirmation.

- [ ] **4. SwayNC reminders**
  - Branch: `feat/reminders`; depends on verified alarm reads and editing.
  - [x] Optional local due-date reminders for tasks without explicit alarms:
    09:00 for date-only tasks and 30 minutes before timed deadlines, persistent
    duplicate protection, missed-reminder catch-up, and an action opening the task.
    Explicit alarms stay with Thunderbird; see [task reminders](reminders.md).
  - [ ] Schedule from explicit returned alarms, persist fired identities, handle
    edited/deleted/cancelled/completed items, restart, midnight, and resume.
  - Send standard desktop notifications with an action opening the item.
    Keep Dayline reminders disabled by default and leave Thunderbird's reminder
    preferences unchanged. Explicit opt-in explains the duplicate-alert risk.
  - **Done when:** reminders arrive in SwayNC at the expected local time;
    deduplication, changed alarms, cancellation/completion, restart/resume, and
    SwayNC Do Not Disturb behavior are verified. A due date is not an explicit
    alarm; optional local task reminders can use it separately.

- [ ] **5. Packaging and resource verification**
  - Branch: `feat/packaging`; depends on the complete vertical workflow.
  - Supply repeatable setup, user-local integration examples, and current
    documentation for sync dependencies, cache freshness, source permissions,
    editing, reminders, and troubleshooting observed failures.
  - Measure Dayline/broker incremental proportional memory and idle CPU, plus
    Thunderbird's required background cost separately. Starting Dayline target:
    at most 100 MiB proportional set size with the widget visible and under
    0.5% of one CPU core averaged idle. These are unmeasured evaluation targets.
  - **Done when:** a clean setup and full account/UI/edit/reminder workflow pass,
    resource results and unmet targets are recorded, and no maintained artifact
    depends on scratch files.

## Execution and Git updates

Use GitHub flow with cohesive, validated feature commits and pull requests. Push
reviewable implementation slices even when external live checks remain pending,
but leave the PR in draft and the milestone unchecked. After validation/review,
squash-merge and continue from updated `main`. Keep temporary probes, frontend
drafts, private account output, and work logs in ignored `.scratch/` or XDG data
locations. The committed roadmap is the explicit user-authorized exception for
versioned planning.

## References

- [Thunderbird calendar architecture](https://source-docs.thunderbird.net/en/latest/calendar/calendars.html)
- [Thunderbird Experiment APIs and permissions](https://developer.thunderbird.net/add-ons/mailextensions/experiments)
- [Native messaging manifests](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/Native_manifests)
