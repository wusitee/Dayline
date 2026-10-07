"""Daily focus ring, task selection, and manual session controls."""

import math
import re
from datetime import date, datetime, time, timedelta

from gi.repository import Gdk, Gtk

from dayline.agenda import tasks
from dayline.errors import DaylineError
from dayline.focus import FocusTracker, clock_time, duration, task_key
from dayline.ui.widgets import box, clear, label, text_button

COLORS = ("#359bff", "#00c9a4", "#ffdc54", "#f26083", "#b48cff", "#ff9b54", "#68d9ef")


class FocusTaskPicker(Gtk.MenuButton):
    """A shared task selection with live, case-insensitive word filtering."""

    def __init__(self, selection: Gtk.SingleSelection):
        super().__init__()
        self.selection = selection
        self.words: list[str] = []
        row = box(False, 4)
        self.title = label("Unassigned")
        self.title.set_hexpand(True)
        row.append(self.title)
        row.append(Gtk.Image(icon_name="pan-down-symbolic"))
        self.set_child(row)
        self.update_property([Gtk.AccessibleProperty.LABEL], ["Focus task"])

        content = box(True, 8)
        content.set_size_request(300, -1)
        self.search = Gtk.SearchEntry(placeholder_text="Search tasks or lists…")
        self.search.update_property([Gtk.AccessibleProperty.LABEL], ["Search focus tasks"])
        self.search.connect("changed", self.filter_changed)
        self.search.connect("activate", self.activate_first)
        self.search.connect("stop-search", lambda *_: self.popover.popdown())
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self.search_key)
        self.search.add_controller(keys)
        content.append(self.search)
        self.results = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.results.set_filter_func(
            lambda row: all(word in row.get_child().get_text().casefold() for word in self.words)
        )
        self.results.connect("row-activated", self.selected)
        self.scroll = Gtk.ScrolledWindow(
            child=self.results,
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            propagate_natural_height=True,
            max_content_height=280,
        )
        content.append(self.scroll)
        self.empty = label("No matching tasks.", "small", "muted")
        content.append(self.empty)
        self.popover = Gtk.Popover(child=content)
        self.set_popover(self.popover)
        self.popover.connect("map", self.opened)
        selection.connect("items-changed", lambda *_: self.rebuild())
        selection.connect("notify::selected-item", self.update_title)
        self.rebuild()
        self.update_title()

    def rebuild(self) -> None:
        clear(self.results)
        for item in self.selection:
            self.results.append(label(item.get_string()))
        self.filter_changed()

    def update_title(self, *_args) -> None:
        item = self.selection.get_selected_item()
        title = item.get_string() if item else "Unassigned"
        self.title.set_text(title)
        self.set_tooltip_text(title)

    def filter_changed(self, *_args) -> None:
        self.words = re.findall(r"\w+", self.search.get_text().casefold())
        self.results.invalidate_filter()
        first = None
        row = self.results.get_first_child()
        while row is not None:
            if row.get_child_visible() and first is None:
                first = row
            row = row.get_next_sibling()
        self.results.select_row(first)
        self.empty.set_visible(first is None)
        self.scroll.set_visible(first is not None)
        self.scroll.get_vadjustment().set_value(0)

    def opened(self, *_args) -> None:
        self.search.set_text("")
        self.search.grab_focus()

    def search_key(self, _controller, key, _code, _state) -> bool:
        row = self.results.get_selected_row()
        if key == Gdk.KEY_Down and row is not None:
            row.grab_focus()
            return True
        return False

    def activate_first(self, *_args) -> None:
        row = self.results.get_selected_row()
        if row is not None:
            self.selected(self.results, row)

    def selected(self, _list, row: Gtk.ListBoxRow) -> None:
        self.selection.set_selected(row.get_index())
        self.popover.popdown()


class FocusRing(Gtk.Overlay):
    def __init__(self, tracker: FocusTracker, *, compact: bool = False):
        super().__init__()
        self.tracker = tracker
        self.groups: list[dict] = []
        self.line_width = 10 if compact else 18
        size = 128 if compact else 240
        self.area = Gtk.DrawingArea(
            content_width=size, content_height=size, halign=Gtk.Align.CENTER
        )
        self.area.set_draw_func(self.draw_ring)
        self.area.update_property([Gtk.AccessibleProperty.LABEL], ["Focus today: 0m"])
        self.set_child(self.area)
        center = box(True, 2)
        center.set_halign(Gtk.Align.CENTER)
        center.set_valign(Gtk.Align.CENTER)
        self.total = label("0m", "focus-mini-total" if compact else "focus-total")
        self.total.set_xalign(0.5)
        center.append(self.total)
        caption = label("Focus today", "muted")
        if compact:
            caption.add_css_class("small")
        caption.set_xalign(0.5)
        center.append(caption)
        self.add_overlay(center)

    def color(self, key: str | None) -> Gdk.RGBA:
        keys = list(dict.fromkeys(session["key"] for session in self.tracker.sessions))
        color = Gdk.RGBA()
        color.parse(COLORS[keys.index(key) % len(COLORS)])
        return color

    def update(self) -> None:
        groups = self.tracker.groups(date.today())
        if groups == self.groups:
            return
        self.groups = groups
        total = duration(sum(group["seconds"] for group in self.groups))
        self.total.set_text(total)
        self.area.update_property([Gtk.AccessibleProperty.LABEL], [f"Focus today: {total}"])
        self.area.queue_draw()

    def draw_ring(self, _area, cr, width: int, height: int) -> None:
        radius = min(width, height) / 2 - self.line_width / 2 - 3
        cr.set_line_width(self.line_width)
        cr.set_source_rgba(1, 1, 1, 0.08)
        cr.arc(width / 2, height / 2, radius, 0, math.tau)
        cr.stroke()
        total = sum(group["seconds"] for group in self.groups)
        angle = -math.pi / 2
        for group in self.groups:
            end = angle + math.tau * group["seconds"] / total
            color = self.color(group["key"])
            cr.set_source_rgb(color.red, color.green, color.blue)
            cr.arc(width / 2, height / 2, radius, angle, end)
            cr.stroke()
            angle = end


class FocusClock(Gtk.Box):
    """A fixed focus card below the compact widget's scrollable agenda."""

    def __init__(self, tracker: FocusTracker, action, open_focus, selection: Gtk.SingleSelection):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.add_css_class("surface")
        self.add_css_class("focus-widget")
        self.set_margin_top(10)
        self.tracker = tracker
        row = box(False, 12)
        self.ring = FocusRing(tracker, compact=True)
        row.append(self.ring)
        controls = box(True, 6)
        controls.set_hexpand(True)
        header = text_button("Focus", open_focus, "flat", "small")
        header.set_halign(Gtk.Align.START)
        controls.append(header)
        self.state = label("New session", "small", "muted")
        controls.append(self.state)
        self.clock = label("00:00", "focus-clock")
        controls.append(self.clock)
        self.task = FocusTaskPicker(selection)
        self.task.add_css_class("small")
        controls.append(self.task)
        buttons = box(False, 6)
        self.start_button = text_button(
            "Start", lambda: action("toggle"), "suggested-action", "small"
        )
        self.start_button.set_hexpand(True)
        buttons.append(self.start_button)
        self.finish_button = text_button("Finish", lambda: action("finish"), "small")
        buttons.append(self.finish_button)
        controls.append(buttons)
        row.append(controls)
        self.append(row)
        self.notice = label("", "small", "warning", wrap=True)
        self.append(self.notice)
        self.signature = None
        self.update("Unassigned", None)

    def update(self, selected_title: str, error: str | None) -> bool:
        current = self.tracker.current
        self.ring.update()
        self.clock.set_text(clock_time(self.tracker.elapsed))
        self.state.set_text(
            "Focusing now" if self.tracker.running else "Paused" if current else "New session"
        )
        title = current["title"] if current else selected_title
        self.task.set_sensitive(self.tracker.loaded)
        self.task.set_tooltip_text(
            self.task.title.get_text()
            + ("\nChanging tasks moves this session's recorded time." if current else "")
        )
        self.start_button.set_label(
            "Pause" if self.tracker.running else "Resume" if current else "Start"
        )
        self.start_button.set_sensitive(self.tracker.loaded)
        self.finish_button.set_visible(current is not None)
        self.notice.set_text(error or "")
        self.notice.set_visible(error is not None)
        signature = (title, current is not None, self.tracker.running, error)
        changed = signature != self.signature
        self.signature = signature
        return changed


class FocusPage(Gtk.Box):
    def __init__(self, tracker: FocusTracker):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.set_size_request(320, -1)
        self.tracker = tracker
        self.choices: list[dict | None] = [None]
        self.data: dict | None = None
        self.groups: list[dict] = []
        self.signature = None
        self.append(label("Focus", "heading"))
        self.day = label("", "small", "muted")
        self.append(self.day)
        self.notice = label("", "small", "warning", wrap=True)
        self.notice.set_visible(False)
        self.append(self.notice)

        content = box(True, 16)
        self.scroll = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True, child=content
        )
        self.append(self.scroll)
        self.ring = FocusRing(tracker)
        self.total = self.ring.total
        content.append(self.ring)
        self.breakdown = box(True, 2)
        content.append(self.breakdown)

        timer = box(True, 10, "card")
        top = box(False, 8)
        self.state = label("New session", "small", "muted", wrap=True)
        self.state.set_hexpand(True)
        top.append(self.state)
        self.clock = label("00:00", "focus-clock")
        top.append(self.clock)
        timer.append(top)
        timer.append(label("Task", "small", "muted"))
        self.selection = Gtk.SingleSelection.new(Gtk.StringList.new(["Unassigned"]))
        self.task = FocusTaskPicker(self.selection)
        timer.append(self.task)
        buttons = box(False, 8)
        self.start_button = text_button("Start focus", self.toggle_timer, "suggested-action")
        self.start_button.set_hexpand(True)
        buttons.append(self.start_button)
        self.finish_button = text_button("Finish", self.finish)
        buttons.append(self.finish_button)
        timer.append(buttons)
        content.append(timer)

        self.history = box(True, 2)
        self.expander = Gtk.Expander(label="Today’s sessions", child=self.history)
        content.append(self.expander)
        self.perform(self.tracker.load)
        self.selection.connect("notify::selected-item", self.task_changed)
        self.set_tasks(None)
        self.connect("map", lambda *_: self.update())

    def set_tasks(self, data: dict | None) -> None:
        self.data = data
        selected = self.choices[self.selection.get_selected()]
        key = task_key(selected) if selected else None
        if self.tracker.current:
            key = self.tracker.current["key"]
        self.choices = [None] + sorted(
            tasks(data or {}), key=lambda item: (item["title"].casefold(), item["source_id"])
        )
        keys = [task_key(item) if item else None for item in self.choices]
        names = ["Unassigned"] + [item["title"] or "(Untitled)" for item in self.choices[1:]]
        sources = {source["id"]: source["name"] for source in (data or {}).get("sources", [])}
        for i, item in enumerate(self.choices[1:], 1):
            if source := sources.get(item["source_id"]):
                names[i] += f" · {source}"
        # Keep the active association when a task is completed, deleted, or unavailable.
        if self.tracker.current and key not in keys:
            keys.append(key)
            names.append(self.tracker.current["title"])
            self.choices.append(None)
        # Notify only after restoring the association, so refreshes never switch tasks.
        self.selection.freeze_notify()
        self.selection.set_model(Gtk.StringList.new(names))
        self.selection.set_selected(keys.index(key) if key in keys else 0)
        self.selection.thaw_notify()

    def task_changed(self, *_args) -> None:
        current = self.tracker.current
        if current is None:
            return
        index = self.selection.get_selected()
        item = self.choices[index]
        if index and item is None:  # The retained association for an unavailable task.
            return
        key = task_key(item) if item else None
        if key != current["key"]:
            self.perform(lambda: self.tracker.reassign(item))
            self.set_tasks(self.data)

    def perform(self, operation) -> bool:
        try:
            operation()
        except DaylineError as exc:
            self.notice.set_text(str(exc))
            self.notice.set_visible(True)
            success = False
        else:
            self.notice.set_visible(False)
            success = True
        self.update()
        return success

    def toggle_timer(self) -> None:
        if self.tracker.running:
            self.perform(self.tracker.pause)
        else:
            item = self.choices[self.selection.get_selected()]
            self.perform(lambda: self.tracker.start(item))

    def finish(self) -> None:
        self.perform(self.tracker.finish)
        self.set_tasks(self.data)

    def edit_sessions(self, sessions: list[dict]) -> None:
        choices = [None] + sorted(
            tasks(self.data or {}, include_completed=True),
            key=lambda item: (item["title"].casefold(), item["source_id"]),
        )
        keys = [task_key(item) if item else None for item in choices]
        names = ["Unassigned"] + [item["title"] or "(Untitled)" for item in choices[1:]]
        sources = {source["id"]: source["name"] for source in (self.data or {}).get("sources", [])}
        for index, item in enumerate(choices[1:], 1):
            if source := sources.get(item["source_id"]):
                names[index] += f" · {source}"
        original = sessions[0]["key"]
        if original not in keys:
            keys.append(original)
            choices.append(None)
            names.append(sessions[-1]["title"])
        selection = Gtk.SingleSelection.new(Gtk.StringList.new(names))
        selection.set_selected(keys.index(original))
        picker = FocusTaskPicker(selection)
        content = box(True, 12, "panel")
        content.set_size_request(360, -1)
        content.append(label("Change focus task", "heading"))
        scope = (
            "This session" if len(sessions) == 1 else f"All {len(sessions)} sessions in this row"
        )
        content.append(label(f"{scope} will move to the chosen task.", "small", "muted", wrap=True))
        content.append(picker)
        notice = label("", "small", "warning", wrap=True)
        notice.set_visible(False)
        content.append(notice)
        dialog = Gtk.Window(
            title="Change focus task",
            child=content,
            transient_for=self.get_root(),
            modal=True,
            destroy_with_parent=True,
            resizable=False,
        )
        dialog.add_css_class("dayline")
        dialog.add_css_class("main-window")

        def save() -> None:
            item = choices[selection.get_selected()]
            if self.perform(lambda: self.tracker.reassign(item, sessions=sessions)):
                self.set_tasks(self.data)
                dialog.close()
            else:
                notice.set_text(self.notice.get_text())
                notice.set_visible(True)

        buttons = box(False, 8)
        buttons.set_halign(Gtk.Align.END)
        buttons.append(text_button("Cancel", dialog.close))
        apply = text_button("Save", save, "suggested-action")
        apply.set_sensitive(False)
        selection.connect(
            "notify::selected-item",
            lambda *_: apply.set_sensitive(keys[selection.get_selected()] != original),
        )
        buttons.append(apply)
        content.append(buttons)

        def escape(_controller, key, _code, _state) -> bool:
            if key != Gdk.KEY_Escape:
                return False
            dialog.close()
            return True

        keys_controller = Gtk.EventControllerKey()
        keys_controller.connect("key-pressed", escape)
        dialog.add_controller(keys_controller)
        dialog.present()

    def time_row(self, item: dict, seconds: float, action, detail: str = "") -> Gtk.Button:
        row = box(False, 10)
        color = self.ring.color(item["key"])
        hex_color = "#" + "".join(
            f"{round(c * 255):02x}" for c in (color.red, color.green, color.blue)
        )
        dot = label("●")
        dot.set_markup(f'<span foreground="{hex_color}">●</span>')
        row.append(dot)
        title = label(item["title"])
        title.set_max_width_chars(1)
        title.set_hexpand(True)
        row.append(title)
        row.append(label(duration(seconds), "small"))
        button = Gtk.Button(child=row, tooltip_text=f"{item['title']}\n{detail or 'Change task'}")
        button.add_css_class("flat")
        button.add_css_class("focus-row")
        button.update_property(
            [Gtk.AccessibleProperty.LABEL], [f"Change task: {item['title']}, {duration(seconds)}"]
        )
        button.connect("clicked", lambda *_: action())
        return button

    def tick(self) -> None:
        if not self.tracker.loaded:
            return
        # A previous failed save remains visible until a successful retry.
        had_dirty = self.tracker.dirty
        try:
            self.tracker.tick()
        except DaylineError as exc:
            self.notice.set_text(str(exc))
            self.notice.set_visible(True)
        else:
            if had_dirty and not self.tracker.dirty:
                self.notice.set_visible(False)
        if self.get_mapped():
            self.update()

    def update(self) -> None:
        today = date.today()
        self.day.set_text(f"Today · {today:%A, %d %B}")
        self.ring.update()
        self.groups = self.ring.groups
        self.clock.set_text(clock_time(self.tracker.elapsed))
        current = self.tracker.current
        self.state.set_text(
            "Focusing now" if self.tracker.running else "Paused" if current else "New session"
        )
        self.start_button.set_label(
            "Pause" if self.tracker.running else "Resume" if current else "Start focus"
        )
        self.start_button.set_sensitive(self.tracker.loaded)
        self.task.set_sensitive(self.tracker.loaded)
        self.task.set_tooltip_text(
            self.task.title.get_text()
            + ("\nChanging tasks moves this session's recorded time." if current else "")
        )
        self.finish_button.set_visible(current is not None)
        sessions = [
            s for s in reversed(self.tracker.sessions) if s["days"].get(today.isoformat(), 0)
        ]
        signature = (
            today,
            tuple((g["key"], g["title"], duration(g["seconds"])) for g in self.groups),
            tuple(
                (s["start"], s["key"], s["title"], duration(s["days"][today.isoformat()]))
                for s in sessions
            ),
            self.tracker.active,
            self.tracker.running,
        )
        if signature == self.signature:
            return
        self.signature = signature
        clear(self.breakdown)
        for group in self.groups:
            self.breakdown.append(
                self.time_row(
                    group,
                    group["seconds"],
                    lambda key=group["key"]: self.edit_sessions(
                        [
                            session
                            for session in self.tracker.sessions
                            if session["key"] == key and session["days"].get(today.isoformat(), 0)
                        ]
                    ),
                )
            )
        if not self.groups:
            self.breakdown.append(label("No focus time recorded today.", "small", "muted"))
        clear(self.history)
        self.expander.set_label(f"Today’s sessions · {len(sessions)}")
        for session in sessions:
            start = max(session["start"], datetime.combine(today, time.min).timestamp())
            end = min(
                session["end"], datetime.combine(today + timedelta(days=1), time.min).timestamp()
            )
            when = f"{datetime.fromtimestamp(start):%H:%M} – {datetime.fromtimestamp(end):%H:%M}"
            if session is current:
                when += " · Running" if self.tracker.running else " · Paused"
            self.history.append(
                self.time_row(
                    session,
                    session["days"][today.isoformat()],
                    lambda session=session: self.edit_sessions([session]),
                    f"{when}\nChange task",
                )
            )
        if not sessions:
            self.history.append(label("Your sessions will appear here.", "small", "muted"))
