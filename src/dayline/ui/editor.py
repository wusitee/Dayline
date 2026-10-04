"""A native form for tasks and appointments, with explicit recurrence scope."""

from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import uuid4

from gi.repository import Gtk

from dayline.editing import editor_changes, editor_values
from dayline.errors import DaylineError
from dayline.ui.widgets import box, clear, label, text_button


class EditorPage(Gtk.Box):
    def __init__(self, save: Callable, close: Callable):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.save_item = save
        header = box(False, 8)
        self.title = label("", "title")
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
        self.form = box(True, 8)
        self.append(Gtk.ScrolledWindow(child=self.form, vexpand=True))
        self.entries: dict[str, Gtk.Entry] = {}
        self.item: dict | None = None
        self.previous: dict[str, str] = {}
        self.busy = False

    def show_error(self, message: str | None) -> None:
        self.error.set_text(message or "")
        self.error.set_visible(bool(message))

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        for widget in (self.form, self.cancel, self.save_button):
            widget.set_sensitive(not busy)

    def loading(self) -> None:
        self.set_busy(True)
        self.show_error(None)
        self.title.set_text("Reading item…")
        clear(self.form)

    def load(self, kind: str, sources: list[dict], item: dict | None, scope: str) -> None:
        self.set_busy(False)
        self.show_error(None)
        clear(self.form)
        self.entries = {}
        self.scope = scope
        self.creating = item is None
        self.item = dict(item) if item is not None else {"kind": kind, "uid": str(uuid4())}
        self.sources = sources
        noun = "event" if kind == "event" else "task"
        suffix = (
            " · Entire series"
            if scope == "series"
            else " · This occurrence"
            if scope == "occurrence"
            else ""
        )
        self.title.set_text(("New " if self.creating else "Edit ") + noun + suffix)
        self.source = Gtk.DropDown.new_from_strings([s["name"] for s in sources])
        self.source.update_property([Gtk.AccessibleProperty.LABEL], ["Destination source"])
        self.source.set_sensitive(self.creating)
        if item:
            self.source.set_selected(
                next(i for i, s in enumerate(sources) if s["id"] == item["source_id"])
            )
        self.form.append(label("Calendar" if kind == "event" else "Task list", "heading"))
        self.form.append(self.source)
        if self.creating and kind == "event":
            start = datetime.now().astimezone().replace(
                minute=0, second=0, microsecond=0
            ) + timedelta(hours=1)
            self.item.update(start=start.isoformat(), end=(start + timedelta(hours=1)).isoformat())
        values = editor_values(self.item)
        self.previous = {} if self.creating else values
        names = {
            "title": "Title",
            "start": "Start",
            "end": "End (all-day end is exclusive)",
            "due": "Due",
            "location": "Location",
            "description": "Notes",
            "reminder": "Reminder time",
        }
        for key, value in values.items():
            self.form.append(label(names[key], "heading"))
            if key == "description":
                self.notes = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
                self.notes.set_size_request(-1, 100)
                self.notes.get_buffer().set_text(value)
                self.form.append(self.notes)
                continue
            entry = Gtk.Entry(text=value, hexpand=True)
            entry.update_property([Gtk.AccessibleProperty.LABEL], [names[key]])
            if key in ("start", "end", "due", "reminder"):
                entry.set_placeholder_text("YYYY-MM-DD or YYYY-MM-DD HH:MM (local time)")
            self.entries[key] = entry
            self.form.append(entry)
        self.form.append(
            label(
                "Blank optional dates mean no date. A changed reminder replaces DISPLAY reminders; "
                "leave it unchanged to preserve existing alarms. Saves are accepted locally by "
                "Thunderbird; TbSync synchronizes them later.",
                "small",
                "muted",
                wrap=True,
            )
        )
        self.save_button.set_sensitive(bool(sources))
        if not sources:
            self.show_error("No selected writable source. Enable an owned source in Sources.")

    def save(self) -> None:
        if self.busy or not self.sources:
            return
        buffer = self.notes.get_buffer()
        entered = {key: entry.get_text() for key, entry in self.entries.items()}
        entered["description"] = buffer.get_text(
            buffer.get_start_iter(), buffer.get_end_iter(), False
        )
        try:
            changes = editor_changes(self.previous, entered)
        except DaylineError as exc:
            self.show_error(str(exc))
            return
        if not changes:
            self.show_error("No changes to save.")
            return
        self.item["source_id"] = self.sources[self.source.get_selected()]["id"]
        self.save_item("create" if self.creating else "update", self.item, changes, self.scope)
