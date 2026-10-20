"""A full-width page searching tasks and events, with a details pane for the selection."""

from datetime import date, datetime

from gi.repository import Gdk, Gtk, Pango

from dayline.agenda import due, due_label, event_bounds, is_overdue, time_range
from dayline.search import query_words, search, search_window
from dayline.ui.widgets import (
    SourceStyles,
    box,
    clear,
    completion_action,
    dot,
    icon_button,
    label,
    text_button,
)

# Rows per section; more matches ask for a narrower query.
LIMIT = 50
SECTIONS = (
    ("tasks", "Tasks", "task"),
    ("upcoming", "Upcoming events", "event"),
    ("completed", "Completed tasks", "task"),
    ("past", "Past events", "event"),
)
TITLES = {key: title for key, title, _ in SECTIONS}
KINDS = (("All", None), ("Events", "event"), ("Tasks", "task"))


def identity(item: dict) -> tuple:
    return tuple(item.get(key) for key in ("source_id", "kind", "uid", "recurrence_id"))


def calendar_day(item: dict) -> date | None:
    """The calendar day of an event's start or a task's deadline."""
    if item["kind"] == "event":
        return event_bounds(item)[0].date()
    value = due(item)
    return value[0] if value else None


def keep_scroll(adjustment: Gtk.Adjustment, value: float) -> None:
    """Restore a scroll position once rebuilt content has been measured."""

    def changed(adjustment):
        if adjustment.get_page_size() > 0:
            adjustment.disconnect(handler)
            adjustment.set_value(value)

    handler = adjustment.connect("changed", changed)


class SearchPage(Gtk.Box):
    """Results beside the selected result's details and actions.

    actions provides item_details(item, anchor), can_edit(item),
    complete(item, scope, completed), and show_in_calendar(day).
    """

    def __init__(self, styles: SourceStyles, back, actions: dict):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.styles = styles
        self.actions = actions
        self.signature = None
        self.data: dict | None = None
        self.events: list[dict] = []
        self.event_sources: list[dict] = []
        self.reading = False
        self.warnings: list[str] = []
        # Each row's section and item, and section totals before the row limit.
        self.entries: list[tuple[str, dict]] = []
        self.totals: dict[str, int] = {}
        self.selected: dict | None = None
        self.details: Gtk.ScrolledWindow | None = None
        self.rebuilding = False
        header = box(False, 10)
        header.append(icon_button("go-previous-symbolic", "Back to calendar", back))
        self.entry = Gtk.SearchEntry(placeholder_text="Search events and tasks", hexpand=True)
        self.entry.update_property([Gtk.AccessibleProperty.LABEL], ["Search events and tasks"])
        self.entry.connect("search-changed", lambda *_: self.update())
        # The entry consumes Escape; leave the page like Escape elsewhere on it.
        self.entry.connect("stop-search", lambda *_: back())
        self.entry.connect("activate", lambda *_: self.focus_results())
        keys = Gtk.EventControllerKey()
        # Capture Down before the text field handles it.
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self.entry_key_pressed)
        self.entry.add_controller(keys)
        self.entry.set_key_capture_widget(self)
        header.append(self.entry)
        kinds = box(False, 0, "linked")
        kinds.update_property([Gtk.AccessibleProperty.LABEL], ["Search item type"])
        self.kinds: list[tuple[Gtk.ToggleButton, str | None]] = []
        for text, kind in KINDS:
            button = Gtk.ToggleButton(label=text, active=kind is None)
            if self.kinds:
                button.set_group(self.kinds[0][0])
            button.connect("toggled", self.kind_toggled)
            kinds.append(button)
            self.kinds.append((button, kind))
        header.append(kinds)
        self.append(header)
        self.status = label("", "small", "muted", wrap=True)
        self.append(self.status)
        self.notice = label("", "small", "warning", wrap=True)
        self.append(self.notice)
        self.results = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.results.add_css_class("search-results")
        self.results.update_property([Gtk.AccessibleProperty.LABEL], ["Search results"])
        self.results.set_header_func(self.section_header)
        self.results.connect("row-selected", self.row_selected)
        self.results.connect("keynav-failed", self.keynav_failed)
        self.empty = label("", "muted", wrap=True)
        self.empty.set_valign(Gtk.Align.START)
        self.empty.set_margin_top(8)
        self.results.set_placeholder(self.empty)
        results = Gtk.ScrolledWindow(
            child=self.results, hscrollbar_policy=Gtk.PolicyType.NEVER, hexpand=True
        )
        results.set_size_request(320, -1)
        results.set_margin_end(8)
        # The pane keeps actions visible beside full-width rows, where popovers would clip.
        self.pane = box(True, 8, "card")
        self.pane.set_size_request(380, -1)
        self.pane.set_margin_start(8)
        self.hint = label("Select a result to see its details and actions.", "muted", wrap=True)
        self.pane.append(self.hint)
        self.append(
            Gtk.Paned(
                orientation=Gtk.Orientation.HORIZONTAL,
                start_child=results,
                end_child=self.pane,
                resize_start_child=True,
                resize_end_child=False,
                shrink_start_child=False,
                shrink_end_child=False,
                wide_handle=True,
                vexpand=True,
            )
        )
        self.connect("map", lambda *_: self.update())

    def set_data(self, data: dict | None) -> None:
        self.data = data
        self.update()

    def set_events(
        self, events: list[dict], sources: list[dict], reading: bool, warnings: list[str]
    ) -> None:
        self.events, self.event_sources = events, sources
        self.reading, self.warnings = reading, warnings
        self.update()

    def kind(self) -> str | None:
        return next((kind for button, kind in self.kinds if button.get_active()), None)

    def kind_toggled(self, button: Gtk.ToggleButton) -> None:
        if button.get_active():
            self.update()

    def update(self) -> None:
        if not self.get_mapped():
            return
        today = date.today()
        first, last = search_window(today)
        status = (
            "Matches titles, locations, notes, and source names · All tasks · "
            f"Events {first:%-d %b %Y} – {last:%-d %b %Y}"
        )
        if self.reading:
            status += " · Reading events from Thunderbird…"
        self.status.set_text(status)
        self.notice.set_text("\n".join(self.warnings))
        self.notice.set_visible(bool(self.warnings))
        data = self.data or {}
        names = {
            source["id"]: source["name"] for source in self.event_sources + data.get("sources", [])
        }
        now = datetime.now().astimezone()
        # Snapshot items first: they are at least as fresh as the search index.
        results = search(data.get("items", []) + self.events, names, self.entry.get_text(), now)
        kind = self.kind()
        shown = [key for key, _, section in SECTIONS if kind in (None, section)]
        rows = [
            (key, match if key in ("upcoming", "past") else (match, 1))
            for key in shown
            for match in results[key][:LIMIT]
        ]
        words = query_words(self.entry.get_text())
        # Unchanged results keep the list, its scroll position, and the details pane.
        # Rows and details also depend on source names, roles, and edit permissions.
        signature = (
            today,
            names,
            data.get("sources", []),
            rows,
            [len(results[key]) for key in shown],
            [(is_overdue(item, now), self.actions["can_edit"](item)) for _, (item, _) in rows],
            words,
        )
        if signature == self.signature:
            return
        self.signature = signature
        focused = self.results.get_focus_child() is not None
        self.rebuilding = True
        # ListBox.remove_all() would also remove the placeholder.
        while (row := self.results.get_row_at_index(0)) is not None:
            self.results.remove(row)
        self.entries = [(key, item) for key, (item, _) in rows]
        self.totals = {key: len(results[key]) for key in shown}
        self.empty.set_text(
            "No matching events or tasks." if words else "Type to find events and tasks."
        )
        selected = None
        for key, (item, count) in rows:
            row = self.result_row(item, count, key, names, now)
            self.results.append(row)
            if (
                selected is None
                and self.selected is not None
                and identity(item) == identity(self.selected)
            ):
                selected = row
        self.results.select_row(selected)
        self.rebuilding = False
        self.show_details(self.entries[selected.get_index()][1] if selected else None)
        if focused:
            if selected is not None:
                selected.grab_focus()
            else:
                self.entry.grab_focus()
                self.entry.set_position(-1)

    def section_header(self, row: Gtk.ListBoxRow, before: Gtk.ListBoxRow | None) -> None:
        section = self.entries[row.get_index()][0]
        if before is not None and self.entries[before.get_index()][0] == section:
            row.set_header(None)
            return
        heading = box(False, 8)
        heading.set_margin_top(16 if before is not None else 0)
        heading.set_margin_bottom(4)
        heading.append(label(TITLES[section], "heading"))
        heading.append(label(str(self.totals[section]), "chip"))
        if self.totals[section] > LIMIT:
            hint = f"Showing the first {LIMIT}. Add words to narrow the search."
            heading.append(label(hint, "small", "muted"))
        row.set_header(heading)

    def result_row(
        self, item: dict, count: int, section: str, names: dict, now: datetime
    ) -> Gtk.ListBoxRow:
        today = now.date()
        content = box(False, 10)
        if item["kind"] == "event":
            marker = dot(self.styles, item["source_id"])
            marker.set_valign(Gtk.Align.START)
            marker.set_margin_top(6)
            when = time_range(item, today)
            if count > 1:
                which = "Next" if section == "upcoming" else "Latest"
                when = f"{when} · {which} of {count} matching occurrences"
        else:
            marker = self.task_check(item)
            when = due_label(item, today)
            if item.get("completed"):
                when = f"Completed · {when}"
        content.append(marker)
        text = box(True, 2)
        text.set_hexpand(True)
        title = label(item["title"] or "(Untitled)", wrap=True, lines=2)
        if item.get("completed"):
            title.add_css_class("muted")
            attributes = Pango.AttrList()
            attributes.insert(Pango.attr_strikethrough_new(True))
            title.set_attributes(attributes)
        text.append(title)
        meta = (when, names.get(item["source_id"], ""), item.get("location"))
        text.append(
            label(" · ".join(value for value in meta if value), "small", "muted", wrap=True)
        )
        content.append(text)
        row = Gtk.ListBoxRow(child=content, tooltip_text=item["title"])
        if not item.get("completed") and is_overdue(item, now):
            row.add_css_class("overdue")
        return row

    def task_check(self, item: dict) -> Gtk.Widget:
        """A task's state; on writable lists, a button completing or reopening it."""
        done = bool(item.get("completed"))
        if done:
            mark = Gtk.Image(icon_name="object-select-symbolic")
        else:
            mark = Gtk.Box(valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER)
            mark.add_css_class("check")
        if not self.actions["can_edit"](item):
            mark.set_valign(Gtk.Align.START)
            mark.set_margin_top(4)
            return mark
        scope = "series" if item.get("recurring") else "item"
        action = completion_action(item)
        button = Gtk.Button(child=mark, tooltip_text=action, valign=Gtk.Align.START)
        button.add_css_class("flat")
        button.add_css_class("check-button")
        button.update_property([Gtk.AccessibleProperty.LABEL], [action])
        button.connect("clicked", lambda *_: self.actions["complete"](item, scope, not done))
        return button

    def row_selected(self, _list, row: Gtk.ListBoxRow | None) -> None:
        if not self.rebuilding:
            self.show_details(self.entries[row.get_index()][1] if row else None)

    def show_details(self, item: dict | None) -> None:
        # A rebuilt pane for the same item keeps the reading position in its notes.
        position = None
        if (
            self.details is not None
            and item is not None
            and identity(item) == identity(self.selected)
        ):
            position = self.details.get_vadjustment().get_value()
        self.selected = item
        self.details = None
        clear(self.pane)
        if item is None:
            self.pane.append(self.hint)
            return
        self.details = self.actions["item_details"](item, self.pane)
        # Short details leave the calendar link beneath them; long notes scroll in the pane.
        self.details.set_max_content_height(-1)
        self.pane.append(self.details)
        if position:
            keep_scroll(self.details.get_vadjustment(), position)
        day = calendar_day(item)
        if day is not None:
            button = text_button(
                "Show in calendar", lambda: self.actions["show_in_calendar"](day), "flat"
            )
            button.set_halign(Gtk.Align.START)
            self.pane.append(button)

    def entry_key_pressed(self, _controller, key, _code, _state) -> bool:
        return key in (Gdk.KEY_Down, Gdk.KEY_KP_Down) and self.focus_results()

    def focus_results(self) -> bool:
        """Move from the search field to the selected or first result."""
        row = self.results.get_selected_row() or self.results.get_row_at_index(0)
        if row is None:
            return False
        self.results.select_row(row)
        row.grab_focus()
        return True

    def keynav_failed(self, _list, direction: Gtk.DirectionType) -> bool:
        # Up from the first result returns to the search field.
        if direction != Gtk.DirectionType.UP:
            return False
        self.entry.grab_focus()
        self.entry.set_position(-1)
        return True
