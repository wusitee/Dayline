# Editing and synchronization

## Using the editor

Open the full panel with `dayline ui toggle` or Super+A. New task and New event
create an item in a selected writable destination. Item details offer Edit, and
unfinished tasks offer Complete task. Recurring events offer This occurrence
and Entire series separately; recurring task editing and completion apply to
the entire series.

Dates use `YYYY-MM-DD`; times use `YYYY-MM-DD HH:MM` in the machine's local time
zone. Blank optional dates clear them. An all-day event's end date is exclusive,
so a one-day event ends on the following date. Task date-only due dates include
that day. Events require matching date-only or timed start/end values and cannot
end before they start. Task due times cannot precede their start.

The form supports title, start, event end or task due, location, notes, and an
explicit reminder time. A changed reminder replaces DISPLAY alarms; blank
removes them. Leaving it unchanged preserves all existing alarms. A due date
alone is not a reminder. Only changed fields are sent, preserving seconds,
time zones, recurrence rules, and provider-specific properties on untouched
fields. Timed edits retain the existing field's time zone, including a series'
wall time across daylight-saving changes.

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

A successful save displays “Saved in Thunderbird. Cloud synchronization is not
confirmed.” It updates Thunderbird's local calendar through its provider API;
TbSync owns uploading and retrying changes. Dayline does not write provider
databases, copy credentials, or claim Microsoft confirmation from a local read.
Thunderbird must remain open for writes and synchronization.

After saving, run the affected account's TbSync synchronization and verify the
item in Outlook or Microsoft To Do. A read-back through Dayline confirms local
fields and routing identity; it does not prove upload completion. Provider
errors appear in the editor and the compact widget. A failure while rereading an
accepted write is reported as such; refresh before attempting another save.

Dayline's optional reminder scheduler is not yet implemented. Thunderbird's
own reminders remain active; Dayline does not change Thunderbird's reminder
preferences.
