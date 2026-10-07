"""A read-only statistics page for tasks and locally recorded focus time."""

from datetime import datetime

from gi.repository import Gtk

from dayline.focus import FocusTracker, duration
from dayline.statistics import summarize
from dayline.ui.widgets import box, clear, icon_button, label

PERIODS = (1, 7, 30)


class StatisticsPage(Gtk.Box):
    def __init__(self, tracker: FocusTracker, back):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.tracker = tracker
        self.data = None
        self.signature = None
        header = box(False, 10)
        header.append(icon_button("go-previous-symbolic", "Back to calendar", back))
        title = label("Statistics", "title")
        title.set_hexpand(True)
        header.append(title)
        self.period = Gtk.DropDown.new_from_strings(["Today", "Last 7 days", "Last 30 days"])
        self.period.update_property([Gtk.AccessibleProperty.LABEL], ["Statistics period"])
        self.period.set_selected(1)
        self.period.connect("notify::selected", lambda *_: self.update())
        header.append(self.period)
        self.append(header)
        self.dates = label("", "small", "muted")
        self.append(self.dates)
        self.content = box(True, 16)
        self.content.set_margin_bottom(12)
        self.content.set_margin_end(6)
        self.scroll = Gtk.ScrolledWindow(
            child=self.content, hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True
        )
        self.append(self.scroll)
        self.connect("map", lambda *_: self.update())

    def set_data(self, data: dict | None) -> None:
        self.data = data
        self.signature = None
        self.update()

    def metrics(self, heading: str, values: list[tuple[str, str]]) -> None:
        self.content.append(label(heading, "heading"))
        grid = Gtk.Grid(column_spacing=10, column_homogeneous=True)
        for index, (name, value) in enumerate(values):
            card = box(True, 4, "card")
            card.set_hexpand(True)
            card.append(label(name, "small", "muted", wrap=True))
            number = label(value, "stat-value")
            number.set_max_width_chars(1)
            card.append(number)
            grid.attach(card, index, 0, 1, 1)
        self.content.append(grid)

    def update(self) -> None:
        if not self.get_mapped():
            return
        result = summarize(
            self.data,
            self.tracker.sessions,
            datetime.now().astimezone(),
            PERIODS[self.period.get_selected()],
        )
        counts, focus = result["tasks"], result["focus"]
        task_values = [
            (name, str(counts[key]) if self.data is not None else "—")
            for name, key in (
                ("Open tasks", "open"),
                ("Overdue now", "overdue"),
                ("Due today", "due_today"),
                ("Completed in period", "completed"),
            )
        ]
        focus_values = [
            ("Focus time", duration(focus["seconds"])),
            ("Sessions", str(focus["sessions"])),
            ("Avg. session", duration(focus["average"])),
            ("Focus days", str(focus["days"])),
        ]
        if not self.tracker.loaded:
            focus_values = [(name, "—") for name, _ in focus_values]
        signature = (
            task_values,
            focus_values,
            self.tracker.loaded,
            [(day["day"], duration(day["seconds"]), day["completed"]) for day in result["daily"]],
            [(g["key"], g["title"], duration(g["seconds"])) for g in result["by_task"]],
            result["by_list"],
            result["unknown_completions"],
        )
        if signature == self.signature:
            return
        self.signature = signature
        first, last = result["daily"][0]["day"], result["daily"][-1]["day"]
        self.dates.set_text(f"{first:%-d %b %Y} – {last:%-d %b %Y}")
        clear(self.content)
        self.metrics("To Do", task_values)
        self.metrics("Focus", focus_values)

        activity = box(True, 10, "card")
        activity.append(label("Daily activity", "heading"))
        activity.append(label("Focus time and tasks completed each day", "small", "muted"))
        grid = Gtk.Grid(column_spacing=12, row_spacing=8)
        grid.attach(label("Day", "small", "muted"), 0, 0, 1, 1)
        grid.attach(label("Focus", "small", "muted"), 1, 0, 2, 1)
        grid.attach(label("Completed", "small", "muted"), 3, 0, 1, 1)
        maximum = max((day["seconds"] for day in result["daily"]), default=0)
        for index, day in enumerate(result["daily"], 1):
            text = label(f"{day['day']:%a %-d %b}", "small")
            text.set_width_chars(12)
            grid.attach(text, 0, index, 1, 1)
            progress = Gtk.ProgressBar(hexpand=True, valign=Gtk.Align.CENTER)
            progress.add_css_class("statistics-focus")
            progress.set_fraction(day["seconds"] / maximum if maximum else 0)
            progress.update_property(
                [Gtk.AccessibleProperty.LABEL],
                [f"{day['day']:%A %-d %B}: {duration(day['seconds'])} focus"],
            )
            grid.attach(progress, 1, index, 1, 1)
            grid.attach(
                label(duration(day["seconds"]) if self.tracker.loaded else "—", "small"),
                2,
                index,
                1,
                1,
            )
            grid.attach(
                label(str(day["completed"]) if self.data is not None else "—", "small"),
                3,
                index,
                1,
                1,
            )
        activity.append(grid)
        self.content.append(activity)

        breakdowns = box(False, 12)
        breakdowns.set_homogeneous(True)
        for heading, groups, task_focus in (
            ("Focus by task", result["by_task"], True),
            ("To Do lists", result["by_list"], False),
        ):
            card = box(True, 8, "card")
            card.append(label(heading, "heading"))
            for group in groups:
                row = box(False, 10)
                title = label(group["title"])
                title.set_max_width_chars(1)
                title.set_hexpand(True)
                title.set_tooltip_text(group["title"])
                row.append(title)
                detail = (
                    duration(group["seconds"])
                    if task_focus
                    else f"{group['open']} open · {group['completed']} completed"
                )
                row.append(label(detail, "small"))
                card.append(row)
            if not groups:
                if task_focus:
                    empty = (
                        "No focus recorded in this period."
                        if self.tracker.loaded
                        else "Focus history unavailable."
                    )
                else:
                    empty = (
                        "No tasks in selected lists."
                        if self.data is not None
                        else "No task data yet."
                    )
                card.append(label(empty, "small", "muted", wrap=True))
            breakdowns.append(card)
        self.content.append(breakdowns)
        notes = [
            "To Do reflects your selected lists. Focus includes all locally recorded sessions."
        ]
        if self.data is None:
            notes.append("Task data is unavailable. Refresh or choose To Do lists in Sources.")
        if not self.tracker.loaded:
            notes.append("Focus history could not be loaded. Check the Focus sidebar for details.")
        if result["unknown_completions"]:
            notes.append(
                f"{result['unknown_completions']} completed tasks have no completion date "
                "and are excluded from this period's completion counts."
            )
        self.content.append(label("\n".join(notes), "small", "muted", wrap=True))
