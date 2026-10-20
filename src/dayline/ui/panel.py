"""A regular agenda window, a layer-shell desktop widget, and a focus indicator."""

import json
from collections.abc import Callable
from datetime import date
from pathlib import Path

import cairo
from gi.repository import Gdk, GLib, Gtk, Gtk4LayerShell

from dayline.config import write_json
from dayline.focus import FocusTracker, clock_time, duration
from dayline.hyprland import cursor_position
from dayline.ui.agenda import AgendaView
from dayline.ui.editor import EditorPage
from dayline.ui.focus import FocusClock, FocusPage
from dayline.ui.search import SearchPage
from dayline.ui.sources import SourcesPage
from dayline.ui.statistics import StatisticsPage
from dayline.ui.tasks import DesktopAgenda, TaskList
from dayline.ui.week import WeekView
from dayline.ui.widgets import SourceStyles, box, clear, icon_button, label, text_button

Edge = Gtk4LayerShell.Edge


def layer_window(app: Gtk.Application, namespace: str, layer) -> Gtk.ApplicationWindow:
    window = Gtk.ApplicationWindow(application=app, decorated=False)
    window.add_css_class("dayline")
    Gtk4LayerShell.init_for_window(window)
    Gtk4LayerShell.set_namespace(window, namespace)
    Gtk4LayerShell.set_layer(window, layer)
    return window


class Panel:
    """The toggleable app window with week, agenda, and task views."""

    def __init__(
        self,
        app: Gtk.Application,
        styles: SourceStyles,
        actions: dict[str, Callable],
        focus: FocusTracker,
    ):
        self.window = Gtk.ApplicationWindow(
            application=app, title="Dayline", default_width=1280, default_height=800
        )
        self.window.add_css_class("dayline")
        self.window.add_css_class("main-window")
        titlebar = Gtk.HeaderBar(decoration_layout=":minimize,maximize,close")
        titlebar.pack_end(text_button("Sources", actions["sources"]))
        self.statistics_button = text_button("Statistics", self.show_statistics)
        titlebar.pack_end(self.statistics_button)
        self.search_button = text_button("Search", self.show_search)
        self.search_button.set_tooltip_text("Search events and tasks (Ctrl+F)")
        titlebar.pack_end(self.search_button)
        self.tasks_toggle = Gtk.ToggleButton(
            label="Tasks", tooltip_text="Show or hide task sidebar"
        )
        self.add_toggle = Gtk.ToggleButton(
            label="Add", active=True, tooltip_text="Show or hide add task/event area"
        )
        self.focus_toggle = Gtk.ToggleButton(
            label="Focus", tooltip_text="Show or hide daily focus timer"
        )
        self.sidebar_toggles = {
            "add": self.add_toggle,
            "tasks": self.tasks_toggle,
            "focus": self.focus_toggle,
        }
        self.switching_sidebar = False
        for name, toggle in self.sidebar_toggles.items():
            toggle.connect("toggled", self.sidebar_selected, name)
        titlebar.pack_end(self.focus_toggle)
        titlebar.pack_end(self.tasks_toggle)
        titlebar.pack_end(self.add_toggle)
        self.window.set_titlebar(titlebar)
        self.window.connect("close-request", self.close_requested)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self.key_pressed)
        self.window.add_controller(keys)
        self.actions = actions
        self.popovers = None  # Set by the application after both windows exist.

        root = box(True, 10, "panel")
        self.window.set_child(root)
        header = box(False, 6)
        self.calendar_navigation = box(False, 6)
        self.calendar_navigation.set_hexpand(True)
        # Navigation comes first so its position never depends on the title's length.
        self.calendar_navigation.append(
            icon_button("go-previous-symbolic", "Previous week", actions["previous"])
        )
        self.calendar_navigation.append(text_button("Today", actions["today"]))
        self.calendar_navigation.append(
            icon_button("go-next-symbolic", "Next week", actions["next"])
        )
        self.title = label("", "title")
        self.title.set_margin_start(10)
        self.title.set_hexpand(True)
        self.calendar_navigation.append(self.title)
        self.view_selector = Gtk.DropDown.new_from_strings(["Week", "Agenda"])
        self.view_selector.update_property([Gtk.AccessibleProperty.LABEL], ["Calendar view"])
        self.view_selector.connect("notify::selected", self.view_changed)
        self.calendar_navigation.append(self.view_selector)
        header.append(self.calendar_navigation)
        self.summary = label("", "small", "muted")
        header.append(self.summary)
        self.spinner = Gtk.Spinner()
        header.append(self.spinner)
        self.refresh_button = icon_button("view-refresh-symbolic", "Refresh", actions["refresh"])
        header.append(self.refresh_button)
        reminder_menu = Gtk.MenuButton(icon_name="alarm-symbolic", tooltip_text="Reminders")
        reminder_menu.update_property([Gtk.AccessibleProperty.LABEL], ["Reminders"])
        reminder_options = box(True, 10)
        for edge in ("top", "bottom", "start", "end"):
            getattr(reminder_options, f"set_margin_{edge}")(12)
        self.reminders = Gtk.CheckButton(label="Task due-date reminders")
        reminder_options.append(self.reminders)
        reminder_options.append(
            label(
                "Without an alarm: 09:00 on the due day,\nor 30 minutes before a timed deadline.",
                "small",
                "muted",
            )
        )
        self.reminders.connect(
            "toggled", lambda button: actions["task_reminders"](button.get_active())
        )
        self.explicit_alarms = Gtk.CheckButton(label="Explicit calendar and task alarms")
        self.explicit_alarms.connect(
            "toggled", lambda button: actions["explicit_alarms"](button.get_active())
        )
        reminder_options.append(self.explicit_alarms)
        reminder_options.append(
            label(
                "Thunderbird may also show these alerts.\nIts reminder preferences stay unchanged.",
                "small",
                "muted",
            )
        )
        reminder_popover = Gtk.Popover()
        reminder_popover.set_child(reminder_options)
        reminder_menu.set_popover(reminder_popover)
        header.append(reminder_menu)
        root.append(header)
        self.banner = box(True, 2, "banner")
        self.banner.set_visible(False)
        root.append(self.banner)

        self.stack = Gtk.Stack(vexpand=True, transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.body = Gtk.Paned(
            orientation=Gtk.Orientation.HORIZONTAL,
            resize_start_child=True,
            resize_end_child=False,
            shrink_start_child=False,
            shrink_end_child=False,
            wide_handle=True,
        )
        self.week = WeekView(actions["show_item"], styles)
        self.agenda = AgendaView(actions["show_item"], styles)
        self.views = Gtk.Stack(hexpand=True, vexpand=True)
        self.views.add_named(self.week, "week")
        self.views.add_named(self.agenda, "agenda")
        self.body.set_start_child(self.views)
        self.views.set_margin_end(8)
        self.sidebar_container = box(False)
        self.sidebar_container.set_margin_start(8)
        self.tasks = TaskList(actions["show_item"], styles)
        # Keep the sidebar compact by default; the divider can widen it.
        self.tasks.set_size_request(320, -1)
        self.tasks.set_hexpand(False)
        self.sidebar = Gtk.Stack(hhomogeneous=False, vhomogeneous=False)
        self.compose = box(True, 12, "card")
        self.compose.set_size_request(320, -1)
        self.compose.append(label("Add task or event", "heading"))
        self.compose_kind = Gtk.DropDown.new_from_strings(["Task", "Event"])
        self.compose_kind.update_property([Gtk.AccessibleProperty.LABEL], ["New item type"])
        self.compose.append(self.compose_kind)
        self.quick_title = Gtk.Entry(placeholder_text="Task or event title")
        self.quick_title.update_property([Gtk.AccessibleProperty.LABEL], ["New item title"])
        self.compose.append(self.quick_title)
        self.compose_button = text_button("Add details", self.create_draft, "suggested-action")
        self.compose_button.set_sensitive(False)
        self.quick_title.connect(
            "changed",
            lambda entry: self.compose_button.set_sensitive(bool(entry.get_text().strip())),
        )
        self.quick_title.connect("activate", lambda *_: self.create_draft())
        self.compose.append(self.compose_button)
        self.compose.append(
            label(
                "Add dates and notes, then Save. Dates in your title appear as suggestions.",
                "small",
                "muted",
                wrap=True,
            )
        )
        self.sidebar.add_named(self.compose, "add")
        self.sidebar.add_named(self.tasks, "tasks")
        self.focus = FocusPage(focus)
        self.sidebar.add_named(self.focus, "focus")
        self.editor = EditorPage(
            actions["save_item"], actions["cancel_editor"], actions.get("open_link")
        )
        self.editor.set_size_request(360, -1)
        self.sidebar.add_named(self.editor, "editor")
        self.sidebar_container.append(self.sidebar)
        self.body.set_end_child(self.sidebar_container)
        self.stack.add_named(self.body, "agenda")
        self.sources = SourcesPage(styles, actions["save_sources"], self.show_agenda)
        self.stack.add_named(self.sources, "sources")
        self.statistics = StatisticsPage(focus, self.show_agenda)
        self.stack.add_named(self.statistics, "statistics")
        self.search = SearchPage(styles, self.show_agenda, actions)
        self.stack.add_named(self.search, "search")
        root.append(self.stack)

    def key_pressed(self, _controller, key, _code, state) -> bool:
        if key in (Gdk.KEY_f, Gdk.KEY_F) and state & Gdk.ModifierType.CONTROL_MASK:
            self.show_search()
            return True
        if key != Gdk.KEY_Escape:
            return False
        if self.popovers.close():
            return True
        if self.stack.get_visible_child_name() in ("sources", "statistics", "search"):
            self.show_agenda()
        elif self.editing():
            if not self.editor.busy:
                self.actions["cancel_editor"]()
        else:
            self.hide()
        return True

    def visible(self) -> bool:
        return self.window.get_visible()

    def show(self) -> None:
        opening = not self.visible()
        self.window.present()
        if opening and self.views.get_visible_child_name() == "week":
            self.week.scroll_to_start()

    def hide(self) -> None:
        self.popovers.close()
        self.show_agenda()
        self.window.set_visible(False)

    def show_focus(self) -> None:
        self.show()
        if not self.editing():
            self.show_agenda()
            self.focus_toggle.set_active(True)

    def show_agenda(self) -> None:
        self.editor.stop_detection()
        self.calendar_navigation.set_visible(True)
        self.summary.set_hexpand(False)
        self.summary.set_xalign(0)
        for toggle in self.sidebar_toggles.values():
            toggle.set_visible(True)
        self.stack.set_visible_child_name("agenda")
        page = next(
            (name for name, toggle in self.sidebar_toggles.items() if toggle.get_active()), "add"
        )
        self.sidebar.set_visible_child_name(page)
        self.view_selector.set_sensitive(True)
        self.update_sidebar()

    def show_page(self, name: str) -> bool:
        """Show a full-width page; unavailable while the side editor holds a draft."""
        if self.editing():
            return False
        self.popovers.close()
        self.stack.set_visible_child_name(name)
        self.calendar_navigation.set_visible(False)
        self.summary.set_hexpand(True)
        self.summary.set_xalign(1)
        for toggle in self.sidebar_toggles.values():
            toggle.set_visible(False)
        return True

    def show_statistics(self) -> None:
        self.show_page("statistics")

    def show_search(self) -> None:
        if self.show_page("search"):
            self.search.entry.grab_focus()

    def leave_editor(self) -> None:
        """Close the side editor; other pages and the chosen sidebar stay open."""
        if self.editing():
            self.show_agenda()

    def show_sources(self) -> None:
        self.stack.set_visible_child_name("sources")
        self.view_selector.set_sensitive(False)

    def show_editor(self) -> None:
        self.stack.set_visible_child_name("agenda")
        self.sidebar.set_visible_child_name("editor")
        self.view_selector.set_sensitive(True)
        self.update_sidebar()

    def update_sidebar(self) -> None:
        editing = self.sidebar.get_visible_child_name() == "editor"
        self.sidebar_container.set_visible(
            editing or any(toggle.get_active() for toggle in self.sidebar_toggles.values())
        )
        for toggle in self.sidebar_toggles.values():
            toggle.set_sensitive(not editing)
        self.statistics_button.set_sensitive(not editing)
        self.search_button.set_sensitive(not editing)

    def sidebar_selected(self, button: Gtk.ToggleButton, page: str) -> None:
        if self.switching_sidebar:
            return
        self.switching_sidebar = True
        if button.get_active():
            for name, toggle in self.sidebar_toggles.items():
                if name != page:
                    toggle.set_active(False)
            self.sidebar.set_visible_child_name(page)
        self.switching_sidebar = False
        self.update_sidebar()

    def create_draft(self) -> None:
        title = self.quick_title.get_text().strip()
        if title:
            self.actions["compose"]("event" if self.compose_kind.get_selected() else "task", title)

    def editing(self) -> bool:
        return (
            self.stack.get_visible_child_name() == "agenda"
            and self.sidebar.get_visible_child_name() == "editor"
        )

    def close_requested(self, _window) -> bool:
        self.hide()
        return True

    def view_changed(self, *_args) -> None:
        if self.popovers is not None:
            self.popovers.close()
        self.views.set_visible_child_name("agenda" if self.view_selector.get_selected() else "week")
        if self.views.get_visible_child_name() == "week":
            self.week.scroll_to_start()

    def set_warnings(self, warnings: list[str], action: tuple[str, Callable] | None) -> None:
        clear(self.banner)
        for text in warnings:
            self.banner.append(label(text, "small", "warning", wrap=True))
        if action is not None:
            button = text_button(action[0], action[1], "flat", "small")
            button.set_halign(Gtk.Align.START)
            self.banner.append(button)
        self.banner.set_visible(bool(warnings))

    def set_busy(self, busy: bool) -> None:
        self.spinner.set_spinning(busy)
        self.spinner.set_visible(busy)
        self.refresh_button.set_sensitive(not busy)


class DesktopWidget:
    """A compact agenda above application windows, like SwayNC's notifications.

    The top layer stays below fullscreen windows. The
    widget reserves no space and accepts keyboard focus on user interaction.

    The layer surface spans the available screen height so the focus card can
    use the space below the agenda. Only the content changes height when browsing
    days; input outside the cards passes through to the windows below.
    """

    WIDTH = 320
    HEIGHT = 640

    def __init__(
        self,
        app: Gtk.Application,
        styles: SourceStyles,
        open_panel: Callable,
        show_item,
        new_item,
        focus: FocusTracker,
        focus_action,
        open_focus,
        focus_selection: Gtk.SingleSelection,
    ):
        self.window = layer_window(app, "dayline-widget", Gtk4LayerShell.Layer.TOP)
        Gtk4LayerShell.set_keyboard_mode(self.window, Gtk4LayerShell.KeyboardMode.ON_DEMAND)
        Gtk4LayerShell.set_anchor(self.window, Edge.TOP, True)
        Gtk4LayerShell.set_anchor(self.window, Edge.BOTTOM, True)
        Gtk4LayerShell.set_anchor(self.window, Edge.RIGHT, True)
        Gtk4LayerShell.set_margin(self.window, Edge.TOP, 16)
        Gtk4LayerShell.set_margin(self.window, Edge.BOTTOM, 16)
        Gtk4LayerShell.set_margin(self.window, Edge.RIGHT, 16)
        self.window.set_default_size(self.WIDTH, self.HEIGHT)
        self.agenda = DesktopAgenda(styles, show_item)
        self.agenda.on_resize = self.update_input
        self.scroll = self.agenda.scroll
        self.footer = box(False, 6, "surface", "widget-actions")
        self.footer.set_homogeneous(True)
        self.footer.append(text_button("New task", lambda: new_item("task"), "flat", "small"))
        self.footer.append(text_button("New event", lambda: new_item("event"), "flat", "small"))
        self.card = box(True)
        self.card.set_valign(Gtk.Align.START)
        self.card.append(self.agenda)
        self.card.append(self.footer)
        self.focus = FocusClock(focus, focus_action, open_focus, focus_selection)
        self.card.append(self.focus)
        self.window.set_child(self.card)
        self.update_input()
        self.window.connect("realize", self.realized)
        self.window.connect("map", lambda *_: self.update_input())
        self.popovers = None  # Set by the application after both windows exist.
        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self.key_pressed)
        self.window.add_controller(keys)
        # Rows open their details; the rest of the widget opens the panel.
        click = Gtk.GestureClick()
        click.connect("released", self.clicked, open_panel)
        self.agenda.add_controller(click)

    def realized(self, _window) -> None:
        self.window.get_surface().connect("layout", lambda *_: self.update_input())

    def key_pressed(self, _controller, key, _code, _state) -> bool:
        if key != Gdk.KEY_Escape:
            return False
        if self.focus.task.popover.get_visible():
            self.focus.task.popover.popdown()
        elif self.popovers is not None and self.popovers.close():
            pass
        else:
            self.window.set_visible(False)
        return True

    def update_input(self) -> None:
        # Exclude the scroll viewport to measure only the fixed header and borders.
        fixed_height = (
            self.agenda.measure(Gtk.Orientation.VERTICAL, self.WIDTH).minimum
            - self.scroll.measure(Gtk.Orientation.VERTICAL, self.WIDTH).minimum
        )
        footer_height = self.footer.measure(Gtk.Orientation.VERTICAL, self.WIDTH).natural
        focus_height = self.focus.measure(Gtk.Orientation.VERTICAL, self.WIDTH).natural
        surface = self.window.get_surface()
        height = surface.get_height() if surface is not None else self.HEIGHT
        viewport = max(1, height - fixed_height - footer_height - focus_height)
        if self.scroll.get_max_content_height() != viewport:
            self.scroll.set_max_content_height(viewport)
        # Measure after layout so the region matches the card being shown.
        GLib.idle_add(self.apply_input_region)

    def set_focus(self, selected_title: str, error: str | None) -> None:
        if self.focus.update(selected_title, error):
            self.update_input()

    def apply_input_region(self) -> bool:
        surface = self.window.get_surface()
        if surface is not None:
            height = self.card.measure(Gtk.Orientation.VERTICAL, self.WIDTH).natural
            card = cairo.RectangleInt(0, 0, self.WIDTH, min(surface.get_height(), height))
            surface.set_input_region(cairo.Region(card))
        return GLib.SOURCE_REMOVE

    def clicked(self, gesture, _presses, x, y, open_panel) -> None:
        target = self.agenda.pick(x, y, Gtk.PickFlags.DEFAULT)
        while target is not None and target is not self.agenda:
            if isinstance(target, (Gtk.Button, Gtk.Expander, Gtk.Scrollbar)):
                return
            target = target.get_parent()
        open_panel()


class FocusIndicator:
    """A compact session timer shown while the desktop widget is hidden.

    It starts in the widget's corner; clicking it expands back into the widget and
    its focus card. Dragging moves it like a window. It never takes keyboard focus
    from the application in use.
    """

    MARGIN = 16

    def __init__(
        self,
        app: Gtk.Application,
        tracker: FocusTracker,
        toggle: Callable,
        expand: Callable,
        path: Path,
    ):
        self.tracker = tracker
        self.path = path
        self.window = layer_window(app, "dayline-focus", Gtk4LayerShell.Layer.TOP)
        Gtk4LayerShell.set_keyboard_mode(self.window, Gtk4LayerShell.KeyboardMode.NONE)
        Gtk4LayerShell.set_anchor(self.window, Edge.TOP, True)
        Gtk4LayerShell.set_anchor(self.window, Edge.RIGHT, True)
        self.pill = box(False, 2, "surface", "focus-pill")
        summary = box(False, 8)
        dot = Gtk.Box(valign=Gtk.Align.CENTER)
        dot.add_css_class("focus-dot")
        summary.append(dot)
        self.clock = label("00:00", "focus-pill-clock")
        summary.append(self.clock)
        self.title = label("", "small")
        self.title.set_max_width_chars(24)
        summary.append(self.title)
        self.expand_button = Gtk.Button(child=summary)
        self.expand_button.add_css_class("flat")
        self.expand_button.add_css_class("focus-pill-summary")
        self.expand_button.update_property([Gtk.AccessibleProperty.LABEL], ["Show focus controls"])
        self.expand_button.connect("clicked", lambda *_: expand())
        self.pill.append(self.expand_button)
        self.toggle_button = Gtk.Button(valign=Gtk.Align.CENTER)
        self.toggle_button.add_css_class("flat")
        self.toggle_button.add_css_class("circular")
        self.toggle_button.connect("clicked", lambda *_: toggle())
        self.pill.append(self.toggle_button)
        self.window.set_child(self.pill)
        self.dragging = False
        # The margins and Hyprland cursor position when the current drag began.
        self.drag_start: tuple[tuple[int, int], tuple[float, float] | None] | None = None
        drag = Gtk.GestureDrag()
        # Capture: a drag claims the press before either button turns it into a click.
        drag.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        drag.connect("drag-begin", self.drag_begin)
        drag.connect("drag-update", self.drag_update)
        drag.connect("drag-end", self.drag_end)
        self.pill.add_controller(drag)
        # The chosen offsets from the top-right corner, and those applied on this monitor.
        self.position = self.load_position()
        self.margins = self.position
        self.place()
        self.window.connect(
            "realize",
            lambda window: window.get_surface().connect("enter-monitor", lambda *_: self.place()),
        )

    def load_position(self) -> tuple[int, int]:
        try:
            data = json.loads(self.path.read_text())
            right, top = data["right"], data["top"]
            if type(right) is int and type(top) is int and right >= 0 and top >= 0:
                return right, top
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return self.MARGIN, self.MARGIN

    def bounds(self, right: int, top: int) -> tuple[int, int]:
        """Margins keeping the whole pill on its monitor."""
        surface = self.window.get_surface()
        monitor = surface and self.window.get_display().get_monitor_at_surface(surface)
        if monitor:
            area = monitor.get_geometry()
            width = self.pill.measure(Gtk.Orientation.HORIZONTAL, -1).natural
            height = self.pill.measure(Gtk.Orientation.VERTICAL, width).natural
            right, top = min(right, area.width - width), min(top, area.height - height)
        return max(0, right), max(0, top)

    def place(self) -> None:
        self.margins = self.bounds(*self.position)
        Gtk4LayerShell.set_margin(self.window, Edge.RIGHT, self.margins[0])
        Gtk4LayerShell.set_margin(self.window, Edge.TOP, self.margins[1])

    def drag_begin(self, _gesture: Gtk.GestureDrag, _x: float, _y: float) -> None:
        self.drag_start = (self.margins, cursor_position())

    def drag_update(self, gesture: Gtk.GestureDrag, dx: float, dy: float) -> None:
        if not self.dragging:
            if not self.pill.drag_check_threshold(0, 0, round(dx), round(dy)):
                return
            self.dragging = True
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            self.window.set_cursor_from_name("grabbing")
        (right, top), start = self.drag_start
        # Compositors measure drag offsets from different positions: sway keeps the
        # pill's position at the press, while Hyprland uses its animated position.
        # Hyprland's global cursor position avoids depending on either.
        if start is not None and (cursor := cursor_position()) is not None:
            dx, dy = cursor[0] - start[0], cursor[1] - start[1]
        self.position = self.bounds(right - round(dx), top + round(dy))
        self.place()

    def drag_end(self, gesture: Gtk.GestureDrag, dx: float, dy: float) -> None:
        if not self.dragging:
            return
        self.drag_update(gesture, dx, dy)
        self.dragging = False
        self.window.set_cursor(None)
        try:
            write_json(self.path, {"right": self.position[0], "top": self.position[1]})
        except OSError:
            pass  # The pill keeps its place for this session.

    def update(self, error: str | None, shown: bool) -> None:
        current = self.tracker.current
        if current is None or not shown:
            self.window.set_visible(False)
            return
        running = self.tracker.running
        self.clock.set_text(clock_time(self.tracker.elapsed))
        if self.title.get_text() != current["title"]:
            self.title.set_text(current["title"])
            # A wider pill grows leftwards; keep it on the monitor.
            self.place()
        for name, active in (("paused", not running), ("error", error is not None)):
            if active:
                self.pill.add_css_class(name)
            else:
                self.pill.remove_css_class(name)
        action = "Pause focus" if running else "Resume focus"
        self.toggle_button.set_icon_name(
            "media-playback-pause-symbolic" if running else "media-playback-start-symbolic"
        )
        self.toggle_button.set_tooltip_text(action)
        self.toggle_button.update_property([Gtk.AccessibleProperty.LABEL], [action])
        today = sum(group["seconds"] for group in self.tracker.groups(date.today()))
        state = "Focusing on" if running else "Paused:"
        details = [f"{state} {current['title']}", f"Focus today: {duration(today)}"]
        if error:
            details.append(error)
        details.append("Click to show focus controls; drag to move.")
        self.expand_button.set_tooltip_text("\n".join(details))
        self.window.set_visible(True)
