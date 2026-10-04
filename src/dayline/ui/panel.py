"""A regular agenda window and a layer-shell desktop widget."""

from collections.abc import Callable

import cairo
from gi.repository import Gdk, GLib, Gtk, Gtk4LayerShell

from dayline.ui.agenda import AgendaView
from dayline.ui.editor import EditorPage
from dayline.ui.sources import SourcesPage
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

    def __init__(self, app: Gtk.Application, styles: SourceStyles, actions: dict[str, Callable]):
        self.window = Gtk.ApplicationWindow(
            application=app, title="Dayline", default_width=1280, default_height=800
        )
        self.window.add_css_class("dayline")
        self.window.add_css_class("main-window")
        titlebar = Gtk.HeaderBar(decoration_layout=":minimize,maximize,close")
        titlebar.pack_end(text_button("Sources", actions["sources"]))
        self.tasks_toggle = Gtk.ToggleButton(
            label="Tasks", tooltip_text="Show or hide task sidebar"
        )
        self.add_toggle = Gtk.ToggleButton(
            label="Add", active=True, tooltip_text="Show or hide add task/event area"
        )
        self.switching_sidebar = False
        self.tasks_toggle.connect("toggled", self.sidebar_selected, "tasks")
        self.add_toggle.connect("toggled", self.sidebar_selected, "add")
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
        # Navigation comes first so its position never depends on the title's length.
        header.append(icon_button("go-previous-symbolic", "Previous week", actions["previous"]))
        header.append(text_button("Today", actions["today"]))
        header.append(icon_button("go-next-symbolic", "Next week", actions["next"]))
        self.title = label("", "title")
        self.title.set_margin_start(10)
        self.title.set_hexpand(True)
        header.append(self.title)
        self.view_selector = Gtk.DropDown.new_from_strings(["Week", "Agenda"])
        self.view_selector.update_property([Gtk.AccessibleProperty.LABEL], ["Calendar view"])
        self.view_selector.connect("notify::selected", self.view_changed)
        header.append(self.view_selector)
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
        root.append(self.stack)

    def key_pressed(self, _controller, key, _code, _state) -> bool:
        if key != Gdk.KEY_Escape:
            return False
        if self.popovers.close():
            return True
        if self.stack.get_visible_child_name() == "sources":
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

    def show_agenda(self) -> None:
        self.editor.stop_detection()
        self.stack.set_visible_child_name("agenda")
        self.sidebar.set_visible_child_name("tasks" if self.tasks_toggle.get_active() else "add")
        self.view_selector.set_sensitive(True)
        self.update_sidebar()

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
            editing or self.tasks_toggle.get_active() or self.add_toggle.get_active()
        )
        self.tasks_toggle.set_sensitive(not editing)
        self.add_toggle.set_sensitive(not editing)

    def sidebar_selected(self, button: Gtk.ToggleButton, page: str) -> None:
        if self.switching_sidebar:
            return
        self.switching_sidebar = True
        if button.get_active():
            (self.add_toggle if page == "tasks" else self.tasks_toggle).set_active(False)
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
    widget reserves no space and takes no focus.

    The layer surface keeps a fixed size so the compositor never animates a
    resize; only the card inside changes height, and input outside it passes
    through to the windows below.
    """

    WIDTH = 320
    HEIGHT = 640

    def __init__(
        self, app: Gtk.Application, styles: SourceStyles, open_panel: Callable, show_item, new_item
    ):
        self.window = layer_window(app, "dayline-widget", Gtk4LayerShell.Layer.TOP)
        Gtk4LayerShell.set_keyboard_mode(self.window, Gtk4LayerShell.KeyboardMode.NONE)
        Gtk4LayerShell.set_anchor(self.window, Edge.TOP, True)
        Gtk4LayerShell.set_anchor(self.window, Edge.RIGHT, True)
        Gtk4LayerShell.set_margin(self.window, Edge.TOP, 16)
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
        self.window.set_child(self.card)
        self.update_input()
        self.window.connect("map", lambda *_: self.update_input())
        # Rows open their details; the rest of the widget opens the panel.
        click = Gtk.GestureClick()
        click.connect("released", self.clicked, open_panel)
        self.agenda.add_controller(click)

    def update_input(self) -> None:
        # Exclude the scroll viewport to measure only the fixed header and borders.
        fixed_height = (
            self.agenda.measure(Gtk.Orientation.VERTICAL, self.WIDTH).minimum
            - self.scroll.measure(Gtk.Orientation.VERTICAL, self.WIDTH).minimum
        )
        footer_height = self.footer.measure(Gtk.Orientation.VERTICAL, self.WIDTH).natural
        self.scroll.set_max_content_height(self.HEIGHT - fixed_height - footer_height)
        # Measure after layout so the region matches the card being shown.
        GLib.idle_add(self.apply_input_region)

    def apply_input_region(self) -> bool:
        surface = self.window.get_surface()
        if surface is not None:
            height = self.card.measure(Gtk.Orientation.VERTICAL, self.WIDTH).natural
            card = cairo.RectangleInt(0, 0, self.WIDTH, min(self.HEIGHT, height))
            surface.set_input_region(cairo.Region(card))
        return GLib.SOURCE_REMOVE

    def clicked(self, gesture, _presses, x, y, open_panel) -> None:
        target = self.agenda.pick(x, y, Gtk.PickFlags.DEFAULT)
        while target is not None and target is not self.agenda:
            if isinstance(target, (Gtk.Button, Gtk.Expander, Gtk.Scrollbar)):
                return
            target = target.get_parent()
        open_panel()
