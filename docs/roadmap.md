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

The native frontend is assigned to Opus. It owns a compact desktop widget behind
application windows and a separate toggleable week-calendar/task panel, with
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

- [ ] **1. Thunderbird bridge and live reads**
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
  - [ ] Compare cloud freshness with Outlook/To Do after a successful TbSync sync.
  - [ ] Verify read-only timetable flags, alarm preservation, change signals,
    restart/reconnection, Thunderbird-offline behavior, and cached reads with
    Thunderbird closed.
  - **Done when:** these live checks pass and any missing provider capability is
    recorded. The bridge is loaded and live read
    access is verified. Thunderbird 156 calendar API signatures were inspected.
    Event DISPLAY alarms are present in some returned records; task reminders
    need a known-reminder test. The subscribed HKU timetable is incorrectly
    exposed as writable by the EAS provider, requiring a write safeguard. Fourteen Python tests and five
    JavaScript contract tests pass, including a subprocess broker round trip.

- [ ] **2. Native frontend — Opus**
  - Branch: `feat/agenda-ui`; contract in [frontend handoff](frontend.md).
  - Build the background widget, separate panel, seven-day time grid, all-day
    area, source selection, task list, and item details. Use backend snapshots
    without adding an authentication client.
  - Run native requests off the GTK main thread; monitor/debounce bridge changes
    and retain clearly marked cache views when the backend is unavailable.
  - Provide one-instance toggle, Waybar integration, and non-conflicting Hyprland
    shortcut/autostart examples. Escape closes the panel.
  - **Done when:** real schedules appear in both views on Hyprland; overlap,
    overnight/all-day events, long titles, undated tasks, empty selections,
    stale/partial results, and HiDPI sizing are readable. Both launch paths work
    without changing the SwayNC shortcut. Synthetic preview work may proceed
    while milestone 1 live checks are pending; final acceptance may not.

- [ ] **3. Task and calendar writes**
  - Branch: `feat/editing`; depends on verified live reads.
  - Add task creation/editing/completion and writable-event creation/editing via
    Thunderbird's provider API, including supported dates, notes, locations,
    and reminder settings. Preserve fields not edited by Dayline.
  - Enforce selected source/type/role, read-only state, and item identity in the
    backend. Explicitly distinguish recurrence occurrence from series edits.
  - Expose failures and queued/local acceptance truthfully. Re-read affected
    items and verify their next TbSync synchronization.
  - **Done when:** controlled, clearly identified test items round-trip through
    the correct account and appear in Outlook/To Do; permission rejection,
    recurrence targeting, completion, and failed writes are tested. Do not mark
    local cache changes as Microsoft confirmation.

- [ ] **4. SwayNC reminders**
  - Branch: `feat/reminders`; depends on verified alarm reads and editing.
  - Schedule from explicit returned alarms, persist fired identities, handle
    edited/deleted/cancelled/completed items, restart, midnight, and resume.
  - Send standard desktop notifications with an action opening the item.
    Coordinate Thunderbird's own reminders to avoid duplicate alerts without
    silently changing the user's notification preferences.
  - **Done when:** reminders arrive in SwayNC at the expected local time;
    deduplication, changed alarms, cancellation/completion, restart/resume, and
    SwayNC Do Not Disturb behavior are verified. A due date alone is not an alarm.

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
