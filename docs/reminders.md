# Reminders

Dayline can send local desktop reminders for unfinished tasks that have a due
date and no explicit Thunderbird alarm. Open the alarm menu beside Refresh in
the full window and enable **Task due-date reminders**. It is disabled by default;
the setting is saved as `task_reminders` in Dayline's `config.json`.

- Date-only tasks remind at **09:00 on the due day**, in the machine's local time
  zone. Microsoft To Do timestamps at local midnight count as date-only dates.
- Tasks with a due time remind **30 minutes before the deadline**.
- This option skips tasks with explicit alarms. Use the separate explicit-alarm
  option below if Dayline should deliver those alarms.
- Completed, cancelled, and undated tasks do not produce automatic reminders.

A due date and an explicit alarm are different fields. Thunderbird supports
task alarms, but setting a due date alone does not attach an alarm. Dayline's
optional due-date reminders fill that gap without editing the task or uploading
an alarm to Microsoft. Thunderbird's reminder preferences are unchanged.

## Explicit alarms

Enable **Explicit calendar and task alarms** in the same menu to deliver the
returned Thunderbird DISPLAY alarms as desktop notifications. This option is
disabled by default and saved separately as `explicit_alarms`. The menu explains
that Thunderbird may also alert for the same alarm. Enabling Dayline does not
disable Thunderbird reminders or change a calendar's Show reminders preference.

The scheduler uses each returned absolute alarm time, including multiple alarms
and distinct recurring event occurrences. It does not infer an alarm from an
event's start or a task's due date. After startup or resume, explicit alarms
catch up for 24 hours after their scheduled time; older alarms are not replayed.
Completed tasks and cancelled items are excluded. Removing an item or its alarm
from a refreshed snapshot removes its pending schedule; changing an alarm time
creates a new notification identity. Renaming an item does not repeat an alert.
Recurring tasks use the current parent task/alarm returned by Thunderbird;
Dayline does not independently expand task recurrence.

## Delivery and catch-up

Keep `dayline ui` running, typically through the supplied Hyprland autostart
example. The widget and full window can both be hidden. Dayline checks after
snapshot refreshes and once per minute, so a reminder may arrive up to one minute
after its scheduled time. The freedesktop notification service handles delivery;
on Hyprland with SwayNC, alerts appear in SwayNC and respect its Do Not Disturb
setting. **Open task** or **Open event** opens the full window and the current
item. An event outside the displayed snapshot is fetched by identity through
the bridge; a missing item or unavailable bridge is reported.

After startup or resume, a missed reminder is delivered while its task's due day
has not ended. This includes reminders shortly before midnight for tasks due
early the next day. Historical deadlines are not replayed. Notification
identities include source, task, recurrence identity, and scheduled time. They
are recorded after the notification service accepts the alert, in the private
`$XDG_CACHE_HOME/dayline/task-reminders.json` journal. Restarts and title edits do
not repeat an alert; changing a due date schedules a new reminder. Notification
service failures are reported in the UI and retried on the next check.
Both reminder options share this journal, preserving existing due-date history.
After a clock gap longer than two minutes, Dayline refreshes Thunderbird before
checking reminders. Midnight also refreshes the range before delivery.

Reminders use the currently displayed snapshot, including a matching saved
snapshot when Thunderbird is closed. A stale snapshot may not contain a recent
completion or due-date change; keep Thunderbird running for live updates.
Calendar alarms are limited to the snapshot's bounded event ranges (the displayed
week plus the widget's range around today). An alarm far ahead of its event may
not be present until that event's range is read. Deleting the reminder journal
removes duplicate protection for still-relevant reminders.

If an alert is missing, check that Dayline is running, the relevant reminder
option is enabled, the item remains active, and SwayNC is available. Due-date reminders
need a dated task without an explicit alarm. For explicit alarms, enable the
separate option and inspect the item's returned `alarms` through the bridge.
