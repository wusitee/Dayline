"""Personal task list and the compact desktop agenda."""

from collections.abc import Callable
from datetime import date, datetime, timedelta

from gi.repository import Gtk, Pango

from dayline.agenda import (
    covers,
    day_agenda,
    day_label,
    due_label,
    event_bounds,
    is_all_day,
    is_overdue,
    local_datetime,
    relative_day,
    task_groups,
    tasks,
    upcoming_task_days,
)
from dayline.bridge import WIDGET_DAYS
from dayline.ui.widgets import SourceStyles, box, clear, dot, icon_button, label, text_button

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
    """Selected-day events and tasks, plus unfinished tasks for the next four days."""

    EVENTS = 5

    def __init__(self, styles: SourceStyles, show_item: ShowItem):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.add_css_class("surface")
        self.add_css_class("widget")
        self.styles = styles
        self.show_item = show_item
        self.set_size_request(320, -1)
        self.set_valign(Gtk.Align.START)
        self.offset = 0
        self.completed_expanded = False
        self.on_resize = None
        self.data: dict | None = None
        self.warnings: list[str] = []
        self.header = box(True, 0, "widget-header")
        self.body = box(True, 8, "widget-content")
        self.scroll = Gtk.ScrolledWindow(
            child=self.body,
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            vscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
            propagate_natural_height=True,
            max_content_height=640,
            valign=Gtk.Align.START,
        )
        self.append(self.header)
        self.append(self.scroll)

    def move(self, days: int) -> None:
        first, last = WIDGET_DAYS
        offset = min(last - 1, max(first, self.offset + days))
        if offset != self.offset:
            self.offset = offset
            self.scroll.get_vadjustment().set_value(0)
            self.render()

    def set_data(self, data: dict | None, warnings: list[str]) -> None:
        self.data, self.warnings = data, warnings
        self.render()

    def set_warnings(self, warnings: list[str]) -> None:
        self.warnings = warnings
        self.notice.set_text(warnings[0] if warnings else "")
        self.notice.set_visible(bool(warnings))
        self.fit()

    def render(self) -> None:
        clear(self.header)
        clear(self.body)
        now = datetime.now().astimezone()
        today = now.date()
        day = today + timedelta(days=self.offset)
        header = box(False, 4)
        title = label(f"{day:%A}", "title")
        title.set_hexpand(True)
        header.append(title)
        first, last = WIDGET_DAYS
        back = icon_button("go-previous-symbolic", "Previous day", lambda: self.move(-1))
        back.add_css_class("flat")
        back.set_sensitive(self.offset > first)
        header.append(back)
        if self.offset:
            header.append(text_button("Today", lambda: self.move(-self.offset), "flat"))
        forward = icon_button("go-next-symbolic", "Next day", lambda: self.move(1))
        forward.add_css_class("flat")
        forward.set_sensitive(self.offset < last - 1)
        header.append(forward)
        self.header.append(header)
        detail = f"{day.day} {day:%B}"
        if day.year != today.year:
            detail += f" {day.year}"
        self.header.append(label(f"{detail} · {relative_day(day, today)}", "small", "muted"))
        self.notice = label("", "small", "warning", wrap=True, lines=3)
        self.body.append(self.notice)
        self.set_warnings(self.warnings)
        if self.data is None:
            self.body.append(label("Open the agenda to choose sources.", "muted", wrap=True))
            return self.fit()
        events, due = day_agenda(self.data, day, now)
        available = covers(self.data, day, day + timedelta(days=1))
        if not available:
            events = []
            self.body.append(
                label("Event data for this day is not in the saved snapshot.", "muted", wrap=True)
            )
        completed = sorted(
            (
                item
                for item in tasks(self.data, include_completed=True)
                if item.get("completed")
                and item.get("completed_at")
                and local_datetime(item["completed_at"]).date() == today
            ),
            key=lambda item: item["title"].casefold(),
        )
        schedule = box(True, 4)
        for item in events[: self.EVENTS]:
            schedule.append(self.event_row(item, now))
        if len(events) > self.EVENTS:
            schedule.append(label(f"+{len(events) - self.EVENTS} more events", "small", "muted"))
        if events:
            self.body.append(schedule)
        upcoming = upcoming_task_days(self.data, day)
        if due or upcoming:
            heading = box(False, 6)
            heading.set_margin_top(4)
            heading.append(label("Tasks", "heading"))
            overdue = [item for item in due if is_overdue(item, now)]
            if overdue:
                heading.append(label(f"{len(overdue)} overdue", "chip", "warning"))
            heading.append(label(f"{len(due) - len(overdue)} due", "chip"))
            self.body.append(heading)
        if due:
            rows = box(True, 2)
            for item in due:
                rows.append(self.task_row(item, is_overdue(item, now)))
            self.body.append(rows)
        elif not events and not upcoming:
            text = "Nothing else today." if not self.offset else "No events or tasks due."
            if not available:
                text = "No tasks due."
            self.body.append(label(text, "small", "muted"))
        for due_day, items in upcoming.items():
            detail = f"{due_day:%a} {due_day.day} {due_day:%b}"
            if due_day.year != today.year:
                detail += f" {due_day.year}"
            rows = box(True, 2)
            rows.append(label(f"{detail} · {relative_day(due_day, today)}", "small", "muted"))
            for item in items:
                rows.append(self.task_row(item, is_overdue(item, now)))
            self.body.append(rows)
        if not upcoming:
            first, last = day + timedelta(days=1), day + timedelta(days=4)
            self.body.append(
                label(f"No tasks due {first:%-d %b}–{last:%-d %b}.", "small", "muted", wrap=True)
            )
        if completed:
            heading = box(False, 6)
            heading.append(label("Completed today", "small", "muted"))
            heading.append(label(str(len(completed)), "chip", "muted"))
            rows = box(True, 2)
            for item in completed:
                rows.append(self.task_row(item, False))
            section = Gtk.Expander(
                label_widget=heading, child=rows, expanded=self.completed_expanded
            )
            section.set_margin_top(4)
            section.connect("notify::expanded", self.completed_toggled)
            self.body.append(section)
        self.fit()

    def completed_toggled(self, expander: Gtk.Expander, _property) -> None:
        self.completed_expanded = expander.get_expanded()
        self.fit()

    def fit(self) -> None:
        if self.on_resize is not None:
            self.on_resize()

    def task_row(self, item: dict, overdue: bool) -> Gtk.Button:
        row = box(False, 8)
        if item.get("completed"):
            check = Gtk.Image(icon_name="object-select-symbolic", valign=Gtk.Align.CENTER)
        else:
            check = Gtk.Box(valign=Gtk.Align.CENTER)
            check.add_css_class("check")
        row.append(check)
        title = label(item["title"] or "(Untitled)", "small")
        if item.get("completed"):
            title.add_css_class("muted")
            attributes = Pango.AttrList()
            attributes.insert(Pango.attr_strikethrough_new(True))
            title.set_attributes(attributes)
        row.append(title)
        button = self.item_button(row, item)
        detail = due_label(item, date.today())
        if item.get("completed"):
            detail = f"Completed · {detail}"
        button.set_tooltip_text(f"{item['title']}\n{detail}")
        if overdue:
            button.add_css_class("overdue")
        return button

    def item_button(self, child: Gtk.Widget, item: dict) -> Gtk.Button:
        button = Gtk.Button(child=child, tooltip_text=item["title"])
        button.add_css_class("flat")
        button.add_css_class("widget-row")
        button.connect("clicked", lambda widget: self.show_item(item, widget))
        return button

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
        return self.item_button(row, item)
