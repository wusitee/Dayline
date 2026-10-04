"""An editable details card with explicit scheduling and recurrence scope."""

from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from uuid import uuid4

from gi.repository import GLib, Gtk

from dayline.agenda import link_markup, local_datetime
from dayline.datetime_input import detect_schedules, duration_end, parse_schedule
from dayline.editing import editor_changes, editor_values, entry_date
from dayline.errors import DaylineError
from dayline.ui.datetime_fields import DateTimeField
from dayline.ui.widgets import box, clear, label, text_button


class EditorPage(Gtk.Box):
    def __init__(self, save: Callable, close: Callable, open_link: Callable | None = None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add_css_class("editor-card")
        self.save_item = save
        self.open_link = open_link or (lambda _uri: None)
        self.detection_timer = None
        header = box(False, 8)
        self.title = label("", "heading")
        self.title.set_hexpand(True)
        header.append(self.title)
        self.cancel = text_button("Cancel", close)
        header.append(self.cancel)
        self.save_button = text_button("Save", self.save, "suggested-action")
        header.append(self.save_button)
        self.append(header)
        self.error = label("", "warning", wrap=True)
        self.error.set_visible(False)
        self.append(self.error)
        self.form = box(True, 10)
        self.append(
            Gtk.ScrolledWindow(
                child=self.form, vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER
            )
        )
        self.entries: dict = {}
        self.item: dict | None = None
        self.previous: dict = {}
        self.busy = False
        self.adjusting = False
        self.duration_value = ""

    def show_error(self, message: str | None) -> None:
        self.error.set_text(message or "")
        self.error.set_visible(bool(message))

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        for widget in (self.form, self.cancel, self.save_button):
            widget.set_sensitive(not busy)

    def stop_detection(self) -> None:
        if self.detection_timer is not None:
            GLib.source_remove(self.detection_timer)
            self.detection_timer = None

    def loading(self) -> None:
        self.stop_detection()
        self.sources = []
        self.set_busy(True)
        self.show_error(None)
        self.title.set_text("Reading item…")
        clear(self.form)

    def reference(self) -> date:
        key = "start" if self.item["kind"] == "event" else "due"
        field = self.entries.get(key)
        try:
            if field:
                return date.fromisoformat(field.day.get_text())
        except ValueError:
            pass
        try:
            value = self.item.get(key)
            return local_datetime(value).date() if value else date.today()
        except DaylineError:
            return date.today()

    def load(self, kind: str, sources: list[dict], item: dict | None, scope: str) -> None:
        self.stop_detection()
        self.set_busy(False)
        self.show_error(None)
        clear(self.form)
        self.entries = {}
        self.scope = scope
        self.creating = item is None
        self.item = dict(item) if item is not None else {"kind": kind, "uid": str(uuid4())}
        self.sources = sources
        self.end_key = "end" if kind == "event" else "due"
        noun = "event" if kind == "event" else "task"
        suffix = (
            " · Series" if scope == "series" else " · Occurrence" if scope == "occurrence" else ""
        )
        self.title.set_text(("New " if self.creating else "Edit ") + noun + suffix)
        self.source = Gtk.DropDown.new_from_strings([s["name"] for s in sources])
        self.source.update_property([Gtk.AccessibleProperty.LABEL], ["Destination source"])
        self.source.set_sensitive(self.creating)
        if item:
            self.source.set_selected(
                next(i for i, s in enumerate(sources) if s["id"] == item["source_id"])
            )
        self.form.append(self.source)
        if self.creating and kind == "event":
            start = datetime.now().astimezone().replace(
                minute=0, second=0, microsecond=0
            ) + timedelta(hours=1)
            self.item.update(start=start.isoformat(), end=(start + timedelta(hours=1)).isoformat())
        values = editor_values(self.item)
        self.previous = {} if self.creating else values
        title = Gtk.Entry(text=values["title"], placeholder_text="Title", hexpand=True)
        title.add_css_class("item-title")
        title.update_property([Gtk.AccessibleProperty.LABEL], ["Title"])
        self.entries["title"] = title
        self.form.append(title)
        if kind == "task":
            self.completed = Gtk.CheckButton(
                label="Completed", active=bool(self.item.get("completed"))
            )
            self.form.append(self.completed)
            if not self.creating:
                self.previous["completed"] = self.completed.get_active()

        self.quick = Gtk.Entry(placeholder_text="Try tomorrow at 3pm or in 90m", hexpand=True)
        self.quick.update_property([Gtk.AccessibleProperty.LABEL], ["Flexible date and time"])
        self.form.append(self.quick)
        quick_row = box(False, 8)
        self.quick_preview = label("", "small", "muted", wrap=True)
        self.quick_preview.set_hexpand(True)
        quick_row.append(self.quick_preview)
        self.quick_apply = text_button(
            "Set start" if kind == "event" else "Set due", self.apply_quick
        )
        self.quick_apply.set_sensitive(False)
        quick_row.append(self.quick_apply)
        self.form.append(quick_row)
        self.quick.connect("changed", self.review_quick)
        self.quick.connect("activate", lambda *_: self.apply_quick())
        self.suggestions = box(True, 4)
        self.form.append(self.suggestions)
        keys = ("start", "end") if kind == "event" else ("due", "start")
        for key in keys:
            self.form.append(label({"start": "Start", "end": "End", "due": "Due"}[key], "heading"))
            field = DateTimeField(
                self.item.get(key),
                self.schedule_changed,
                self.reference,
                nullable=kind == "task",
                midnight_is_date=kind == "task" and key == "due",
            )
            self.entries[key] = field
            self.form.append(field)
        duration_row = box(False, 8)
        if kind == "event":
            self.all_day = Gtk.CheckButton(
                label="All day", active=len(self.item.get("start") or "") == 10
            )
            self.all_day.connect("toggled", self.toggle_all_day)
            duration_row.append(self.all_day)
        duration_row.append(label("Duration", "heading"))
        self.duration = Gtk.Entry(placeholder_text="1h 30m", hexpand=True)
        self.duration.set_width_chars(8)
        self.duration.update_property([Gtk.AccessibleProperty.LABEL], ["Duration"])
        duration_row.append(self.duration)
        self.form.append(duration_row)
        self.duration.connect("changed", self.duration_changed)
        self.sync_duration()
        self.schedule_hint = label(
            "All-day End is the first day after the event."
            if kind == "event"
            else "Duration uses Start → Due. Blank Start is allowed.",
            "small",
            "muted",
            wrap=True,
        )
        self.form.append(self.schedule_hint)
        if kind == "event":
            self.form.append(label("Location", "heading"))
            self.entries["location"] = Gtk.Entry(
                text=values["location"], placeholder_text="Location"
            )
            self.form.append(self.entries["location"])
        notes_heading = box(False, 8)
        notes_title = label("Notes", "heading")
        notes_title.set_hexpand(True)
        notes_heading.append(notes_title)
        self.notes_toggle = text_button("Preview links", self.toggle_notes, "flat", "small")
        notes_heading.append(self.notes_toggle)
        self.form.append(notes_heading)
        self.notes = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.notes.set_size_request(-1, 180)
        self.notes.add_css_class("notes-editor")
        self.notes.get_buffer().set_text(values["description"])
        self.notes_stack = Gtk.Stack(hhomogeneous=False, vhomogeneous=False)
        self.notes_stack.add_named(self.notes, "edit")
        self.notes_preview = label("", wrap=True)
        self.notes_preview.set_selectable(True)
        self.notes_preview.connect("activate-link", lambda _label, uri: self.activate_link(uri))
        self.notes_stack.add_named(self.notes_preview, "preview")
        self.form.append(self.notes_stack)
        self.form.append(label("Reminder", "heading"))
        self.entries["reminder"] = DateTimeField(
            next(iter(self.item.get("alarms", [])), None), lambda _field: None, self.reference
        )
        self.form.append(self.entries["reminder"])
        self.form.append(
            label(
                "Tasks without explicit alarms use Dayline’s due-date reminders when enabled. "
                "Changing this time replaces "
                "Thunderbird DISPLAY alarms; clearing it removes them. Save writes to Thunderbird.",
                "small",
                "muted",
                wrap=True,
            )
        )
        title.connect("changed", self.queue_detection)
        self.notes.get_buffer().connect("changed", self.queue_detection)
        self.detect_dates()
        self.save_button.set_sensitive(bool(sources))
        if not sources:
            self.show_error("No selected writable source. Enable an owned source in Sources.")

    def notes_text(self) -> str:
        buffer = self.notes.get_buffer()
        return buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)

    def activate_link(self, uri: str) -> bool:
        self.open_link(uri)
        return True

    def toggle_notes(self) -> None:
        preview = self.notes_stack.get_visible_child_name() == "edit"
        self.notes_preview.set_markup(link_markup(self.notes_text()))
        self.notes_stack.set_visible_child_name("preview" if preview else "edit")
        self.notes_toggle.set_label("Edit notes" if preview else "Preview links")

    def review_quick(self, *_args) -> None:
        try:
            self.quick_value = parse_schedule(self.quick.get_text(), reference=self.reference())
            text = entry_date(self.quick_value) + (
                " · Local time" if self.quick_value and len(self.quick_value) > 10 else ""
            )
        except DaylineError as exc:
            self.quick_value, text = None, str(exc)
        self.quick_preview.set_text(text)
        self.quick_apply.set_sensitive(bool(self.quick_value))

    def apply_quick(self) -> None:
        if getattr(self, "quick_value", None):
            self.entries["start" if self.item["kind"] == "event" else "due"].set_value(
                self.quick_value
            )

    def queue_detection(self, *_args) -> None:
        self.stop_detection()
        self.detection_timer = GLib.timeout_add(300, self.detect_dates)

    def detect_dates(self) -> bool:
        self.detection_timer = None
        clear(self.suggestions)
        found = detect_schedules(
            self.entries["title"].get_text() + "\n" + self.notes_text(),
            now=datetime.now().astimezone(),
            reference=self.reference(),
        )
        key = "start" if self.item["kind"] == "event" else "due"
        for text, value in found:
            button = text_button(
                "",
                lambda value=value: self.entries[key].set_value(value),
                "flat",
                "small",
            )
            button.set_child(label(f"Use {text} → {entry_date(value)}", wrap=True))
            button.set_tooltip_text(f"Set {key}; title and notes stay unchanged")
            self.suggestions.append(button)
        self.suggestions.set_visible(bool(found))
        return GLib.SOURCE_REMOVE

    def sync_duration(self) -> None:
        start = end = None
        try:
            start, end = self.entries["start"].value(), self.entries[self.end_key].value()
            seconds = (
                (
                    local_datetime(end).astimezone(UTC) - local_datetime(start).astimezone(UTC)
                ).total_seconds()
                if start and end
                else 0
            )
            if seconds > 0:
                self.duration_value = (
                    f"{(date.fromisoformat(end) - date.fromisoformat(start)).days}d"
                    if len(start) == len(end) == 10
                    else f"{seconds / 60:g}m"
                )
            else:
                self.duration_value = ""
        except DaylineError:
            self.duration_value = ""
        self.adjusting = True
        self.duration.set_text(self.duration_value)
        if self.item["kind"] == "event":
            self.all_day.set_active(bool(start and len(start) == 10))
        self.adjusting = False

    def schedule_changed(self, field: DateTimeField) -> None:
        if self.adjusting or "start" not in self.entries or self.end_key not in self.entries:
            return
        start_field, end_field = self.entries["start"], self.entries[self.end_key]
        try:
            start, end = start_field.value(), end_field.value()
            self.adjusting = True
            if field is start_field and start and self.duration_value:
                duration = self.duration_value
                if self.item["kind"] == "event" and end and (len(start) == 10) != (len(end) == 10):
                    duration = "1d" if len(start) == 10 else "1h"
                end_field.set_value(duration_end(start, duration))
            elif field is end_field and start and end and len(start) > 10 and len(end) > 10:
                # Earlier clock entries denote overnight ends; date edits stay explicit.
                first, last = local_datetime(start), local_datetime(end)
                if field.last_changed == "time" and first.date() == last.date() and last < first:
                    end_field.set_value((last + timedelta(days=1)).isoformat())
        except DaylineError:
            pass  # The field's own preview explains invalid partial input.
        finally:
            self.adjusting = False
        self.sync_duration()

    def duration_changed(self, *_args) -> None:
        if self.adjusting:
            return
        if not self.duration.get_text().strip():
            self.duration_value = ""
            self.show_error(None)
            return
        try:
            start = self.entries["start"].value()
            if not start:
                raise DaylineError("Choose Start before setting a duration.")
            end = duration_end(start, self.duration.get_text())
            self.adjusting = True
            self.entries[self.end_key].set_value(end)
            self.duration_value = self.duration.get_text()
            self.show_error(None)
        except DaylineError as exc:
            self.show_error(str(exc))
        finally:
            self.adjusting = False

    def toggle_all_day(self, *_args) -> None:
        if self.adjusting:
            return
        try:
            start = self.entries["start"].value()
            end = self.entries["end"].value()
            if not start or not end:
                return
            first, last = local_datetime(start), local_datetime(end)
            if self.all_day.get_active():
                start = first.date().isoformat()
                exclusive = last.date() + timedelta(days=bool(last.time() != time.min))
                end = max(first.date() + timedelta(days=1), exclusive).isoformat()
            else:
                start = datetime.combine(first.date(), time(9)).astimezone().isoformat()
                end = (local_datetime(start) + timedelta(hours=1)).isoformat()
            self.adjusting = True
            self.entries["start"].set_value(start)
            self.entries["end"].set_value(end)
        except DaylineError as exc:
            self.show_error(str(exc))
        finally:
            self.adjusting = False
        self.sync_duration()

    def save(self) -> None:
        if self.busy or not self.sources:
            return
        try:
            entered = {key: entry.get_text() for key, entry in self.entries.items()}
            entered["description"] = self.notes_text()
            if self.item["kind"] == "task":
                entered["completed"] = self.completed.get_active()
            start, end = self.entries["start"].value(), self.entries[self.end_key].value()
            if self.item["kind"] == "event" and (
                not start or not end or (len(start) == 10) != (len(end) == 10)
            ):
                raise DaylineError("Events need matching all-day or timed Start and End values.")
            if start and end and local_datetime(end) < local_datetime(start):
                raise DaylineError("End or Due cannot precede Start.")
            reminder = self.entries["reminder"].value()
            if reminder and len(reminder) == 10:
                raise DaylineError("A reminder needs both a date and a time.")
            if self.duration.get_text().strip() and self.duration.get_text() != self.duration_value:
                if not start:
                    raise DaylineError("Choose Start before setting a duration.")
                duration_end(start, self.duration.get_text())
            changes = editor_changes(self.previous, entered)
        except DaylineError as exc:
            self.show_error(str(exc))
            return
        if not changes:
            self.show_error("No changes to save.")
            return
        self.item["source_id"] = self.sources[self.source.get_selected()]["id"]
        self.save_item("create" if self.creating else "update", self.item, changes, self.scope)
