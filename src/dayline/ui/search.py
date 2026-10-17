"""A full-width page searching tasks and events."""

from datetime import date, datetime

from gi.repository import Gtk, Pango

from dayline.agenda import due_label, is_overdue, time_range
from dayline.search import query_words, search, search_window
from dayline.ui.tasks import ShowItem
from dayline.ui.widgets import SourceStyles, box, clear, dot, icon_button, label

# Rows per section; more matches ask for a narrower query.
LIMIT = 50
SECTIONS = (
    ("tasks", "Tasks", "task"),
    ("upcoming", "Upcoming events", "event"),
    ("past", "Past events", "event"),
)


class SearchPage(Gtk.Box):
    def __init__(self, show_item: ShowItem, styles: SourceStyles, back, close_popovers):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.show_item = show_item
        self.styles = styles
        self.close_popovers = close_popovers
        self.signature = None
        self.data: dict | None = None
        self.events: list[dict] = []
        self.event_sources: list[dict] = []
        self.reading = False
        self.warnings: list[str] = []
        header = box(False, 10)
        header.append(icon_button("go-previous-symbolic", "Back to calendar", back))
        self.entry = Gtk.SearchEntry(placeholder_text="Search events and tasks", hexpand=True)
        self.entry.update_property([Gtk.AccessibleProperty.LABEL], ["Search events and tasks"])
        self.entry.connect("search-changed", lambda *_: self.update())
        # The entry consumes Escape; leave the page like Escape elsewhere on it.
        self.entry.connect("stop-search", lambda *_: back())
        self.entry.set_key_capture_widget(self)
        header.append(self.entry)
        self.kind = Gtk.DropDown.new_from_strings(["All", "Events", "Tasks"])
        self.kind.update_property([Gtk.AccessibleProperty.LABEL], ["Search item type"])
        self.kind.connect("notify::selected", lambda *_: self.update())
        header.append(self.kind)
        self.append(header)
        self.status = label("", "small", "muted", wrap=True)
        self.append(self.status)
        self.notice = label("", "small", "warning", wrap=True)
        self.append(self.notice)
        self.results = box(True, 16)
        self.results.set_margin_bottom(12)
        self.results.set_margin_end(6)
        self.scroll = Gtk.ScrolledWindow(
            child=self.results, hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True
        )
        self.append(self.scroll)
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
        # Snapshot items first: they are at least as fresh as the search index.
        results = search(
            data.get("items", []) + self.events,
            names,
            self.entry.get_text(),
            datetime.now().astimezone(),
        )
        kind = (None, "event", "task")[self.kind.get_selected()]
        shown = [(key, title) for key, title, section in SECTIONS if kind in (None, section)]
        # Unchanged results keep the list, its scroll position, and an open details popover.
        signature = (
            today,
            names,
            [(key, results[key]) for key, _ in shown],
            query_words(self.entry.get_text()),
        )
        if signature == self.signature:
            return
        self.signature = signature
        self.close_popovers()
        clear(self.results)
        if not signature[-1]:
            return
        if not any(results[key] for key, _ in shown):
            self.results.append(label("No matching events or tasks.", "muted", wrap=True))
            return
        for key, title in shown:
            matches = results[key]
            if not matches:
                continue
            section = box(True, 4)
            heading = box(False, 8)
            heading.append(label(title, "heading"))
            heading.append(label(str(len(matches)), "chip"))
            section.append(heading)
            for match in matches[:LIMIT]:
                item, count = match if key != "tasks" else (match, 1)
                section.append(self.result_row(item, count, key, names, today))
            if len(matches) > LIMIT:
                section.append(
                    label(
                        f"Showing the first {LIMIT}. Add words to narrow the search.",
                        "small",
                        "muted",
                        wrap=True,
                    )
                )
            self.results.append(section)

    def result_row(
        self, item: dict, count: int, section: str, names: dict, today: date
    ) -> Gtk.Button:
        row = box(False, 10)
        if item["kind"] == "event":
            marker = dot(self.styles, item["source_id"])
            marker.set_valign(Gtk.Align.START)
            marker.set_margin_top(6)
            when = time_range(item, today)
            if count > 1:
                which = "Next" if section == "upcoming" else "Latest"
                when = f"{when} · {which} of {count} matching occurrences"
        elif item.get("completed"):
            marker = Gtk.Image(icon_name="object-select-symbolic", valign=Gtk.Align.START)
            when = f"Completed · {due_label(item, today)}"
        else:
            marker = Gtk.Box(valign=Gtk.Align.START)
            marker.set_margin_top(4)
            marker.add_css_class("check")
            when = due_label(item, today)
        row.append(marker)
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
        row.append(text)
        button = Gtk.Button(child=row, tooltip_text=item["title"])
        button.add_css_class("flat")
        button.add_css_class("row")
        if not item.get("completed") and is_overdue(item, datetime.now().astimezone()):
            button.add_css_class("overdue")
        button.connect("clicked", lambda widget: self.show_item(item, widget))
        return button
