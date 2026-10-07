# Editing and synchronization

## Using the editor

Open the full panel with `dayline ui toggle` or Super+A. New task and New event
create an item in a selected writable destination. The Add area in the right
column also starts a task or event draft from a title; Enter or Add details
opens its scheduling and notes controls. Nothing is created until Save.
The Add and Tasks buttons switch or hide the column.

Week and compact-widget item clicks first show a details popup with notes and
links. Writable items have an Edit entry that opens a small editor dialog.
The widget's New task and New event footer buttons also open dialogs, without
opening the main panel. Agenda keeps its editable details card beside the
calendar for writable, nonrecurring items. Save applies changes; Cancel restores
the chosen sidebar or closes the dialog. Tasks have a Completed checkbox. Read-only items open a
details popover. Recurring items offer explicit occurrence and series edits
before opening the appropriate editor; recurring task editing and completion
apply to the entire series. Dialogs keep unsaved fields through calendar
refreshes and failed saves. Escape or closing a dialog dismisses it when no
write is pending.

Date fields have native calendar pickers; time fields offer half-hour choices
and accept `9am`, `14:30`, and `0930`. The quick input accepts dates and times
such as `tomorrow at 3pm`, `6 Oct 23:59 HKT`, ISO timestamps, and `in 90m`.
A preview shows the interpreted value before Set start or Set due applies it.
Dates without a year use the item's year; time-only input uses its date.
`today`, `tomorrow`, and weekdays use the local current date. Ambiguous numeric
dates such as `6/10` are rejected. HKT, UTC, and GMT can be specified; otherwise
times use the machine's local zone.

Titles and notes produce up to three distinct date/time suggestions. Applying
a suggestion sets Start for events or Due for tasks; it preserves the text.
URLs are excluded from detection. Suggestions never save automatically.
Notes are editable plain text, with a Preview links button for opening URLs.

Duration accepts `50m`, `1h 30m`, `01:30`, and whole days such as `2d` for all-day
events. It sets End or Due from Start. Changing Start preserves the displayed
duration; changing End or Due recalculates it. An end clock earlier than Start
on the same date rolls into the next day, with the resulting date shown.
All-day events have an explicit toggle. Blank optional dates clear them.
An all-day event's end date is exclusive, so a one-day event ends on the
following date. Task date-only due dates include
that day. Events require matching date-only or timed start/end values and cannot
end before they start. Task due times cannot precede their start.

The form supports title, start, event end or task due, event location, notes, and an
explicit reminder time. A changed reminder replaces DISPLAY alarms; blank
removes them. Leaving it unchanged preserves all existing alarms. A due date
alone does not attach a Thunderbird alarm. Optional [Dayline task reminders](reminders.md)
can notify from due dates without changing the task. Only changed fields are
sent, preserving seconds,
time zones, recurrence rules, and provider-specific properties on untouched
fields. Timed edits retain the existing field's time zone, including a series'
wall time across daylight-saving changes.
Microsoft To Do does not synchronize task locations, so the task form omits
that field while preserving any existing provider location property.

## Permissions and conflicts

Sources must be selected for the relevant item type. Personal sources allow
editing by default; School sources require an explicit Allow edits opt-in.
School sources cannot provide tasks. A subscribed calendar must stay read-only
even if its provider reports it writable; source names do not establish
ownership. Thunderbird's disabled/read-only state and item ACLs are checked
again by the backend. Invitations and events with attendees must be managed in
Thunderbird; invitation management is outside Dayline's editor.

The editor reads a fresh canonical item before opening. Saving compares its
revision with the current provider item and rejects an outdated form rather
than overwriting another edit. Reopen it to load the latest values. A new draft
keeps one UUID across retries, preventing duplicate creation after an uncertain
response. Refresh before retrying an item that was already created.

## Local acceptance and cloud synchronization

A successful save closes the editor and refreshes the agenda without a persistent
success warning. Accepted task completion and reopening update the visible task
immediately from Thunderbird's returned item, before the full agenda refresh.
Failed saves leave the task's displayed completion state unchanged.
It updates Thunderbird's local calendar through its provider API;
TbSync uploads and retries changes according to its configured synchronization
settings. Dayline does not write provider
databases, copy credentials, or claim Microsoft confirmation from a local read.
Thunderbird must remain open for writes and synchronization.

To verify cloud delivery, check the item in Outlook or Microsoft To Do after
TbSync's next successful synchronization. A read-back through Dayline confirms local
fields and routing identity; it does not prove upload completion. Provider
errors appear in the editor and the compact widget. A failure while rereading an
accepted write is reported as such; refresh before attempting another save.

On Thunderbird 156, controlled tasks in two personal To Do lists and a personal
appointment were synchronized and independently fetched from Microsoft through
the installed EAS provider. These checks covered creation, title/notes/date
edits, event location, reminder preservation, task completion, and cleanup.
They establish that workflow on the tested accounts, not confirmation of each
subsequent save.

Dayline's optional due-date task reminders skip tasks with explicit Thunderbird
alarms. Thunderbird's own reminders remain active; Dayline does not change
Thunderbird's reminder preferences.
