"""A chronological agenda of loaded events and all unfinished tasks."""

from datetime import date, timedelta

from gi.repository import Gtk

from dayline.agenda import (
    agenda_days,
    covers,
    day_schedule,
    due,
    due_label,
    schedule_time,
    tasks,
    time_range,
)
from dayline.ui.tasks import ShowItem
from dayline.ui.widgets import SourceStyles, box, clear, dot, label


class AgendaView(Gtk.Box):
    def __init__(self, show_item: ShowItem, styles: SourceStyles):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.show_item = show_item
        self.styles = styles
        self.first = date.today()
        self.missing = label("", "notice", wrap=True)
        self.missing.set_visible(False)
        self.append(self.missing)
        self.scope = label(
            "All unfinished tasks · Events from loaded calendar dates", "small", "muted", wrap=True
        )
        self.append(self.scope)
        self.list = box(True, 28, "agenda-list")
        self.scroll = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True, child=self.list
        )
        self.append(self.scroll)

    def set_week(self, data: dict | None, first: date, loading: bool) -> None:
        self.first = first
        clear(self.list)
        available = data is not None and covers(data, first, first + timedelta(days=7))
        self.missing.set_visible(not available)
        if not available:
            if loading:
                text = "Reading this week from Thunderbird…"
            elif data is None:
                text = "No calendar data yet."
            else:
                text = (
                    "This week is not in the saved snapshot. Tasks are still shown; "
                    "refresh while Thunderbird is open to read events."
                )
            self.missing.set_text(text)
        if data is None:
            return
        sources = {source["id"]: source for source in data.get("sources", [])}
        today = date.today()
        for day in agenda_days(data, first):
            section = box(False, 16)
            heading = box(True, 2, "agenda-date")
            heading.set_size_request(64, -1)
            heading.set_valign(Gtk.Align.START)
            heading.append(label(str(day.day), "agenda-number"))
            heading.append(label(f"{day:%a · %b}", "weekday", "muted"))
            if day.year != today.year:
                heading.append(label(str(day.year), "small", "muted"))
            if day == today:
                heading.add_css_class("today")
            section.append(heading)
            rows = box(True, 12)
            rows.set_hexpand(True)
            if day < first:
                rows.append(label("Earlier tasks", "small", "muted"))
            elif not covers(data, day, day + timedelta(days=1)):
                rows.append(
                    label(
                        "Tasks only · Event data for this date is not loaded.",
                        "small",
                        "muted",
                        wrap=True,
                    )
                )
            for item in day_schedule(data, day):
                if day < first and item["kind"] == "event":
                    continue
                rows.append(self.item_row(item, day, sources))
            if rows.get_first_child() is None:
                rows.append(label("No scheduled items.", "small", "muted"))
            section.append(rows)
            self.list.append(section)
        undated = [item for item in tasks(data) if due(item) is None]
        if undated:
            section = box(True, 12)
            section.append(label("No due date", "heading"))
            for item in sorted(undated, key=lambda item: item["title"].casefold()):
                section.append(self.item_row(item, today, sources))
            self.list.append(section)

    def item_row(self, item: dict, day: date, sources: dict) -> Gtk.Widget:
        row = box(False, 12)
        when = label(schedule_time(item, day), "small", "muted")
        when.set_size_request(112, -1)
        when.set_xalign(1)
        row.append(when)
        if item["kind"] == "task":
            marker = Gtk.Box(valign=Gtk.Align.CENTER)
            marker.add_css_class("check")
        else:
            marker = dot(self.styles, item["source_id"])
        row.append(marker)
        text = box(True, 4)
        text.append(label(item["title"] or "(Untitled)", "agenda-item-title", wrap=True, lines=2))
        source = sources.get(item["source_id"], {}).get("name", "")
        meta = " · ".join(value for value in (source, item.get("location")) if value)
        if meta:
            text.append(label(meta, "small", "muted", wrap=True, lines=2))
        button = Gtk.Button(child=text, hexpand=True)
        button.add_css_class("event")
        button.add_css_class("agenda-item")
        self.styles.apply(button, item["source_id"])
        details = (
            time_range(item, date.today()) if item["kind"] == "event" else due_label(item, day)
        )
        button.set_tooltip_text(f"{item['title']}\n{details}")
        button.connect("clicked", lambda widget: self.show_item(item, widget))
        row.append(button)
        return row
