"""Layer-shell windows: the overlay agenda panel and the background desktop widget."""

from collections.abc import Callable

import cairo
from gi.repository import Gdk, GLib, Gtk, Gtk4LayerShell

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
    """The toggleable week calendar and task list, drawn above application windows."""

    def __init__(self, app: Gtk.Application, styles: SourceStyles, actions: dict[str, Callable]):
        self.window = layer_window(app, "dayline-panel", Gtk4LayerShell.Layer.OVERLAY)
        # Fill the output except for margins; Waybar's exclusive zone keeps it below the bar.
        for edge in (Edge.TOP, Edge.BOTTOM, Edge.LEFT, Edge.RIGHT):
            Gtk4LayerShell.set_anchor(self.window, edge, True)
        for edge, margin in ((Edge.TOP, 12), (Edge.BOTTOM, 24), (Edge.LEFT, 48), (Edge.RIGHT, 48)):
            Gtk4LayerShell.set_margin(self.window, edge, margin)
        # Like SwayNC's control center, take the keyboard while open so Escape always works.
        Gtk4LayerShell.set_keyboard_mode(self.window, Gtk4LayerShell.KeyboardMode.EXCLUSIVE)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self.key_pressed)
        self.window.add_controller(keys)
        self.actions = actions
        self.popovers = None  # Set by the application after both windows exist.

        root = box(True, 10, "surface", "panel")
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
        self.summary = label("", "small", "muted")
        header.append(self.summary)
        self.spinner = Gtk.Spinner()
        header.append(self.spinner)
        self.refresh_button = icon_button("view-refresh-symbolic", "Refresh", actions["refresh"])
        header.append(self.refresh_button)
        header.append(text_button("New task", actions["new_task"]))
        header.append(text_button("New event", actions["new_event"]))
        header.append(text_button("Sources", actions["sources"]))
        header.append(icon_button("window-close-symbolic", "Close (Escape)", self.hide))
        root.append(header)
        self.banner = box(True, 2, "banner")
        self.banner.set_visible(False)
        root.append(self.banner)

        self.stack = Gtk.Stack(vexpand=True, transition_type=Gtk.StackTransitionType.CROSSFADE)
        body = box(False, 16)
        self.week = WeekView(actions["show_item"], styles)
        self.week.set_hexpand(True)
        body.append(self.week)
        body.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        self.tasks = TaskList(actions["show_item"], styles)
        # A fixed column: expanding task rows must not take width from the calendar.
        self.tasks.set_size_request(320, -1)
        self.tasks.set_hexpand(False)
        body.append(self.tasks)
        self.stack.add_named(body, "agenda")
        self.sources = SourcesPage(styles, actions["save_sources"], self.show_agenda)
        self.stack.add_named(self.sources, "sources")
        self.editor = EditorPage(actions["save_item"], actions["cancel_editor"])
        self.stack.add_named(self.editor, "editor")
        root.append(self.stack)

    def key_pressed(self, _controller, key, _code, _state) -> bool:
        if key != Gdk.KEY_Escape:
            return False
        if self.popovers.close():
            return True
        if self.stack.get_visible_child_name() == "editor":
            if not self.editor.busy:
                self.actions["cancel_editor"]()
        elif self.stack.get_visible_child_name() == "sources":
            self.show_agenda()
        else:
            self.hide()
        return True

    def visible(self) -> bool:
        return self.window.get_visible()

    def show(self) -> None:
        self.window.present()
        self.week.scroll_to_start()

    def hide(self) -> None:
        self.popovers.close()
        self.show_agenda()
        self.window.set_visible(False)

    def show_agenda(self) -> None:
        self.stack.set_visible_child_name("agenda")

    def show_sources(self) -> None:
        self.stack.set_visible_child_name("sources")

    def show_editor(self) -> None:
        self.stack.set_visible_child_name("editor")

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

    The top layer stays below fullscreen windows and the overlay panel. The
    widget reserves no space and takes no focus.

    The layer surface keeps a fixed size so the compositor never animates a
    resize; only the card inside changes height, and input outside it passes
    through to the windows below.
    """

    WIDTH = 320
    HEIGHT = 640

    def __init__(self, app: Gtk.Application, styles: SourceStyles, open_panel: Callable, show_item):
        self.window = layer_window(app, "dayline-widget", Gtk4LayerShell.Layer.TOP)
        Gtk4LayerShell.set_keyboard_mode(self.window, Gtk4LayerShell.KeyboardMode.NONE)
        Gtk4LayerShell.set_anchor(self.window, Edge.TOP, True)
        Gtk4LayerShell.set_anchor(self.window, Edge.RIGHT, True)
        Gtk4LayerShell.set_margin(self.window, Edge.TOP, 16)
        Gtk4LayerShell.set_margin(self.window, Edge.RIGHT, 16)
        self.window.set_default_size(self.WIDTH, self.HEIGHT)
        self.agenda = DesktopAgenda(styles, show_item)
        self.agenda.on_resize = self.update_input
        self.scroll = Gtk.ScrolledWindow(
            child=self.agenda,
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            vscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
            propagate_natural_height=True,
            max_content_height=self.HEIGHT,
            valign=Gtk.Align.START,
        )
        self.window.set_child(self.scroll)
        self.window.connect("map", lambda *_: self.update_input())
        # Rows open their details; the rest of the widget opens the panel.
        click = Gtk.GestureClick()
        click.connect("released", self.clicked, open_panel)
        self.agenda.add_controller(click)

    def update_input(self) -> None:
        # Measure after layout so the region matches the card being shown.
        GLib.idle_add(self.apply_input_region)

    def apply_input_region(self) -> bool:
        surface = self.window.get_surface()
        if surface is not None:
            height = self.scroll.measure(Gtk.Orientation.VERTICAL, self.WIDTH).natural
            card = cairo.RectangleInt(0, 0, self.WIDTH, min(self.HEIGHT, height))
            surface.set_input_region(cairo.Region(card))
        return GLib.SOURCE_REMOVE

    def clicked(self, gesture, _presses, x, y, open_panel) -> None:
        target = self.agenda.pick(x, y, Gtk.PickFlags.DEFAULT)
        while target is not None and target is not self.agenda:
            if isinstance(target, Gtk.Button):
                return
            target = target.get_parent()
        open_panel()
