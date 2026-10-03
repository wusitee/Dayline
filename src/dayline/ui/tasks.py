"""Personal task list and the compact desktop agenda."""

from collections.abc import Callable
from datetime import date, datetime, timedelta

from gi.repository import Gtk

from dayline.agenda import (
    day_label,
    due_label,
    event_bounds,
    is_all_day,
    task_groups,
    upcoming_events,
)
from dayline.ui.widgets import SourceStyles, box, clear, dot, label

ShowItem = Callable[[dict, Gtk.Widget], None]
GROUPS = (
    ("overdue", "Overdue"),
    ("today", "Due today"),
    ("upcoming", "Upcoming"),
    ("undated", "No due date"),
)


def task_row(
    item: dict, sources: dict, styles: SourceStyles, show_item: ShowItem, overdue: bool
) -> Gtk.Button:
    row = box(False, 10)
    check = Gtk.Box(valign=Gtk.Align.START)
    check.set_margin_top(3)
    check.add_css_class("check")
    row.append(check)
    text = box(True, 2)
    text.set_hexpand(True)
    text.append(label(item["title"] or "(Untitled)", wrap=True, lines=2))
    meta = box(False, 6)
    meta.append(dot(styles, item["source_id"]))
    source = sources.get(item["source_id"], {}).get("name", "")
    details = due_label(item, date.today())
    meta.append(label(f"{details} · {source}" if source else details, "small", "muted"))
    text.append(meta)
    row.append(text)
    button = Gtk.Button(child=row, tooltip_text=item["title"])
    button.add_css_class("flat")
    button.add_css_class("row")
    if overdue:
        button.add_css_class("overdue")
    button.connect("clicked", lambda widget: show_item(item, widget))
    return button


class TaskList(Gtk.Box):
    def __init__(self, show_item: ShowItem, styles: SourceStyles):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.show_item = show_item
        self.styles = styles
        header = box(False, 8)
        header.append(label("Tasks", "heading"))
        self.count = label("", "chip")
        header.append(self.count)
        self.append(header)
        self.list = box(True, 2)
        scroll = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True, child=self.list
        )
        self.append(scroll)

    def set_data(self, data: dict | None, has_task_sources: bool) -> None:
        clear(self.list)
        if data is None:
            self.count.set_visible(False)
            self.list.append(label("No task data yet.", "muted", wrap=True))
            return
        groups = task_groups(data, datetime.now().astimezone())
        total = sum(len(items) for items in groups.values())
        self.count.set_text(str(total))
        self.count.set_visible(True)
        if not has_task_sources:
            self.list.append(
                label("Select a Personal To Do list in Sources to show tasks.", "muted", wrap=True)
            )
            return
        if not total:
            self.list.append(label("No unfinished tasks.", "muted", wrap=True))
            return
        sources = {source["id"]: source for source in data.get("sources", [])}
        for name, title in GROUPS:
            if not groups[name]:
                continue
            heading = label(f"{title} · {len(groups[name])}", "small", "muted")
            if name == "overdue":
                heading.add_css_class("warning")
            heading.set_margin_top(8)
            self.list.append(heading)
            for item in groups[name]:
                self.list.append(
                    task_row(item, sources, self.styles, self.show_item, name == "overdue")
                )


class DesktopAgenda(Gtk.Box):
    """Today's current and next events, a short task list, and task counts."""

    EVENTS = 4
    TASKS = 4

    def __init__(self, styles: SourceStyles):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add_css_class("surface")
        self.add_css_class("widget")
        self.styles = styles
        self.set_size_request(320, -1)

    def set_data(self, data: dict | None, warnings: list[str]) -> None:
        clear(self)
        now = datetime.now().astimezone()
        today = now.date()
        header = box(False, 8)
        header.append(label(f"{today:%A}", "title"))
        header.append(label(f"{today.day} {today:%B}", "muted"))
        self.append(header)
        if warnings:
            self.append(label(warnings[0], "small", "warning", wrap=True, lines=3))
        if data is None:
            self.append(label("Open the agenda to choose sources.", "muted", wrap=True))
            return
        upcoming = upcoming_events(data, now)
        today_items = [item for item in upcoming if event_bounds(item)[0].date() <= today]
        later = [item for item in upcoming if event_bounds(item)[0].date() > today]
        if today_items:
            for item in today_items[: self.EVENTS]:
                self.append(self.event_row(item, now))
            if len(today_items) > self.EVENTS:
                more = len(today_items) - self.EVENTS
                self.append(label(f"+{more} more today", "small", "muted"))
        else:
            self.append(label("Nothing else today.", "muted"))
            if later:
                # Show only the next day with events, so the widget stays compact.
                first = event_bounds(later[0])[0].date()
                self.append(label(day_label(first, today), "small", "muted"))
                for item in [i for i in later if event_bounds(i)[0].date() == first][:2]:
                    self.append(self.event_row(item, now))
        groups = task_groups(data, now)
        counts = box(False, 6)
        counts.set_margin_top(4)
        counts.append(label("Tasks", "heading"))
        if groups["overdue"]:
            counts.append(label(f"{len(groups['overdue'])} overdue", "chip", "warning"))
        counts.append(label(f"{len(groups['today'])} today", "chip"))
        self.append(counts)
        shown = (groups["overdue"] + groups["today"] + groups["upcoming"] + groups["undated"])[
            : self.TASKS
        ]
        if not shown:
            self.append(label("No unfinished tasks.", "small", "muted"))
        for item in shown:
            row = box(False, 8)
            check = Gtk.Box(valign=Gtk.Align.CENTER)
            check.add_css_class("check")
            row.append(check)
            row.append(label(item["title"] or "(Untitled)", "small"))
            if item in groups["overdue"]:
                row.add_css_class("overdue")
            self.append(row)

    def event_row(self, item: dict, now: datetime) -> Gtk.Widget:
        start, end = event_bounds(item)
        row = box(False, 10)
        bar = dot(self.styles, item["source_id"], "bar")
        bar.set_valign(Gtk.Align.FILL)
        row.append(bar)
        text = box(True, 1)
        text.set_hexpand(True)
        if is_all_day(item):
            when = "All day"
        elif start <= now < end:
            when = f"Now · until {end:%H:%M}"
        elif start.date() != end.date() and end - start > timedelta(hours=1):
            when = f"{start:%H:%M} – {day_label(end.date(), now.date())} {end:%H:%M}"
        else:
            when = f"{start:%H:%M}–{end:%H:%M}" if end > start else f"{start:%H:%M}"
        time = label(when, "small", "muted")
        if start <= now < end and not is_all_day(item):
            time.add_css_class("now-chip")
        text.append(time)
        text.append(label(item["title"] or "(Untitled)", wrap=True, lines=2))
        if item.get("location"):
            text.append(label(item["location"], "small", "muted"))
        row.append(text)
        return row
