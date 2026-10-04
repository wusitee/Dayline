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
    task_groups,
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
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add_css_class("surface")
        self.add_css_class("widget")
        self.styles = styles
        self.show_item = show_item
        self.set_size_request(320, -1)
        self.set_valign(Gtk.Align.START)
        self.offset = 0
        self.on_resize = None
        self.data: dict | None = None
        self.warnings: list[str] = []
        scroll = Gtk.EventControllerScroll(
            flags=Gtk.EventControllerScrollFlags.VERTICAL | Gtk.EventControllerScrollFlags.DISCRETE
        )
        scroll.connect("scroll", self.scrolled)
        self.add_controller(scroll)

    def scrolled(self, _controller, _dx, dy) -> bool:
        scroll = self.get_ancestor(Gtk.ScrolledWindow)
        if scroll is not None:
            adjustment = scroll.get_vadjustment()
            if adjustment.get_upper() > adjustment.get_page_size():
                # Let the parent scroll long agendas so every visible item can be reached.
                return False
        self.move(1 if dy > 0 else -1)
        return True

    def move(self, days: int) -> None:
        first, last = WIDGET_DAYS
        offset = min(last - 1, max(first, self.offset + days))
        if offset != self.offset:
            self.offset = offset
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
        clear(self)
        now = datetime.now().astimezone()
        today = now.date()
        day = today + timedelta(days=self.offset)
        header = box(False, 4)
        title = box(True, 0)
        title.set_hexpand(True)
        title.append(label(f"{day:%A}", "title"))
        detail = f"{day.day} {day:%B}"
        # Name nearby days; further days are identified by the date alone.
        if abs(self.offset) == 1:
            detail = f"{day_label(day, today)} · {detail}"
        title.append(label(detail, "muted"))
        header.append(title)
        first, last = WIDGET_DAYS
        back = icon_button("go-previous-symbolic", "Previous day", lambda: self.move(-1))
        back.set_sensitive(self.offset > first)
        header.append(back)
        if self.offset:
            header.append(text_button("Today", lambda: self.move(-self.offset), "flat"))
        forward = icon_button("go-next-symbolic", "Next day", lambda: self.move(1))
        forward.set_sensitive(self.offset < last - 1)
        header.append(forward)
        self.append(header)
        self.notice = label("", "small", "warning", wrap=True, lines=3)
        self.append(self.notice)
        self.set_warnings(self.warnings)
        if self.data is None:
            self.append(label("Open the agenda to choose sources.", "muted", wrap=True))
            return self.fit()
        events, due = day_agenda(self.data, day, now, include_completed=True)
        if not covers(self.data, day, day + timedelta(days=1)):
            events = []
            self.append(
                label("Event data for this day is not in the saved snapshot.", "muted", wrap=True)
            )
        completed = [item for item in due if item.get("completed")]
        due = [item for item in due if not item.get("completed")]
        for item in events[: self.EVENTS]:
            self.append(self.event_row(item, now))
        if len(events) > self.EVENTS:
            self.append(label(f"+{len(events) - self.EVENTS} more events", "small", "muted"))
        if not events and covers(self.data, day, day + timedelta(days=1)):
            self.append(label("Nothing else today." if not self.offset else "No events.", "muted"))
        heading = box(False, 6)
        heading.set_margin_top(4)
        heading.append(label("Tasks", "heading"))
        overdue = [item for item in due if is_overdue(item, now)]
        if overdue:
            heading.append(label(f"{len(overdue)} overdue", "chip", "warning"))
        heading.append(label(f"{len(due) - len(overdue)} due", "chip"))
        self.append(heading)
        for item in due:
            self.append(self.task_row(item, is_overdue(item, now)))
        if not due:
            self.append(label("No tasks due.", "small", "muted"))
        if completed:
            heading = box(False, 6)
            heading.set_margin_top(4)
            heading.append(label("Completed", "heading"))
            heading.append(label(str(len(completed)), "chip"))
            self.append(heading)
            for item in completed:
                self.append(self.task_row(item, False))
        upcoming = upcoming_task_days(self.data, day)
        heading = box(False, 6)
        heading.set_margin_top(8)
        heading.append(label("Next 4 days", "heading"))
        heading.append(label(str(sum(len(items) for items in upcoming.values())), "chip"))
        self.append(heading)
        for due_day, items in upcoming.items():
            # Date labels stay explicit while browsing days other than today.
            heading = label(f"{due_day:%a} {due_day.day} {due_day:%b}", "small", "muted")
            heading.set_margin_top(4)
            self.append(heading)
            for item in items:
                self.append(self.task_row(item, is_overdue(item, now)))
        if not upcoming:
            first, last = day + timedelta(days=1), day + timedelta(days=4)
            self.append(
                label(f"No tasks due {first:%-d %b}–{last:%-d %b}.", "small", "muted", wrap=True)
            )
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
        button.set_tooltip_text(f"{item['title']}\n{due_label(item, date.today())}")
        if item.get("completed"):
            button.set_tooltip_text(f"Completed · {item['title']}")
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
