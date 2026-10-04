# Task reminders

Dayline can send local desktop reminders for unfinished tasks that have a due
date and no explicit Thunderbird alarm. Enable **Task reminders** using the alarm
button beside Refresh in the full window. It is disabled by default; the setting
is saved as `task_reminders` in Dayline's `config.json`.

- Date-only tasks remind at **09:00 on the due day**, in the machine's local time
  zone. Microsoft To Do timestamps at local midnight count as date-only dates.
- Tasks with a due time remind **30 minutes before the deadline**.
- Tasks with explicit reminder alarms remain Thunderbird's responsibility.
  Dayline skips these tasks to avoid sending another alert for the same reminder.
- Completed, cancelled, and undated tasks do not produce automatic reminders.

A due date and an explicit alarm are different fields. Thunderbird supports
task alarms, but setting a due date alone does not attach an alarm. Dayline's
optional due-date reminders fill that gap without editing the task or uploading
an alarm to Microsoft. Thunderbird's reminder preferences are unchanged.

## Delivery and catch-up

Keep `dayline ui` running, typically through the supplied Hyprland autostart
example. The widget and full window can both be hidden. Dayline checks after
snapshot refreshes and once per minute, so a reminder may arrive up to one minute
after its scheduled time. The freedesktop notification service handles delivery;
on Hyprland with SwayNC, alerts appear in SwayNC and respect its Do Not Disturb
setting. **Open task** opens the full window and the current task's details.

After startup or resume, a missed reminder is delivered while its task's due day
has not ended. This includes reminders shortly before midnight for tasks due
early the next day. Historical deadlines are not replayed. Notification
identities include source, task, recurrence identity, and scheduled time. They
are recorded after the notification service accepts the alert, in the private
`$XDG_CACHE_HOME/dayline/task-reminders.json` journal. Restarts and title edits do
not repeat an alert; changing a due date schedules a new reminder. Notification
service failures are reported in the UI and retried on the next check.

Reminders use the currently displayed snapshot, including a matching saved
snapshot when Thunderbird is closed. A stale snapshot may not contain a recent
completion or due-date change; keep Thunderbird running for live updates.
Deleting the reminder journal removes duplicate protection for still-relevant
reminders.

If an alert is missing, check that Dayline is running, the alarm button is
enabled, the task has a due date and remains unfinished, and SwayNC is available.
For a task with an explicit alarm, check Thunderbird's reminder settings and the
calendar's Show reminders option. Inspect the task's returned `alarms` through
the bridge when diagnosing whether Thunderbird has an alarm to schedule.
