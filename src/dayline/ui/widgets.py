"""Small GTK building blocks shared by the panel and the desktop widget."""

import re
from datetime import date

from gi.repository import Gdk, GLib, Gtk, Pango

from dayline.agenda import due_label, link_markup, time_range
from dayline.markdown import markdown_markup

DEFAULT_COLOR = "#8a9bb0"
# Item details wrap at a fixed line length; their height follows the text.
DETAILS_WIDTH = 340
DETAILS_CHARS = 44
_COLOR = re.compile(r"#[0-9a-fA-F]{6}")


def label(
    text: str, *classes: str, wrap: bool = False, lines: int = 0, chars: int = 1
) -> Gtk.Label:
    widget = Gtk.Label(label=text, xalign=0)
    if wrap:
        widget.set_wrap(True)
        widget.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        widget.set_natural_wrap_mode(Gtk.NaturalWrapMode.WORD)
        # By default wrap to the assigned width, so text length never widens columns.
        # Popovers have no assigned width and pass their own line length instead.
        widget.set_max_width_chars(chars)
    if lines:
        widget.set_lines(lines)
    if not wrap or lines:
        widget.set_ellipsize(Pango.EllipsizeMode.END)
    for name in classes:
        widget.add_css_class(name)
    return widget


def box(vertical: bool = True, spacing: int = 0, *classes: str) -> Gtk.Box:
    orientation = Gtk.Orientation.VERTICAL if vertical else Gtk.Orientation.HORIZONTAL
    widget = Gtk.Box(orientation=orientation, spacing=spacing)
    for name in classes:
        widget.add_css_class(name)
    return widget


class NotesLabel(Gtk.Label):
    """Wrapped notes with checklist colors independent of web-link styling."""

    def __init__(self, *classes: str, chars: int = 1, checklists: bool = False):
        super().__init__(xalign=0, wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR)
        self.set_natural_wrap_mode(Gtk.NaturalWrapMode.WORD)
        self.set_max_width_chars(chars)
        for name in classes:
            self.add_css_class(name)
        self.notes = ""
        self.checklists = checklists
        self.hovered = None
        motion = Gtk.EventControllerMotion()
        # Read the hovered URI after GTK's own link controller processes the event.
        motion.connect("motion", lambda controller, *_: GLib.idle_add(self.hover, controller))
        motion.connect("leave", lambda *_: self.set_hovered(None))
        self.add_controller(motion)

    def set_notes(self, text: str) -> None:
        self.notes = text
        self.set_markup(markdown_markup(text, checklists=self.checklists, hovered=self.hovered))

    def set_hovered(self, line: int | None) -> None:
        if line != self.hovered:
            self.hovered = line
            self.set_notes(self.notes)

    def hover(self, motion: Gtk.EventControllerMotion) -> bool:
        uri = (self.get_current_uri() or "") if motion.contains_pointer() else ""
        self.set_hovered(int(uri.split(":")[1]) if uri.startswith("dayline-checklist:") else None)
        return GLib.SOURCE_REMOVE


def icon_button(icon: str, tooltip: str, callback) -> Gtk.Button:
    widget = Gtk.Button(icon_name=icon, tooltip_text=tooltip)
    widget.add_css_class("flat")
    widget.update_property([Gtk.AccessibleProperty.LABEL], [tooltip])
    widget.connect("clicked", lambda *_: callback())
    return widget


def text_button(text: str, callback, *classes: str) -> Gtk.Button:
    widget = Gtk.Button(label=text)
    for name in classes:
        widget.add_css_class(name)
    widget.connect("clicked", lambda *_: callback())
    return widget


def clear(container: Gtk.Widget) -> None:
    while child := container.get_first_child():
        container.remove(child)


class SourceStyles:
    """Color classes for source colors, keyed by color so classes stay stable."""

    def __init__(self):
        self.provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), self.provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1
        )
        self.classes: dict[str, str] = {}
        self.colors: set[str] = set()

    def update(self, sources: list[dict]) -> None:
        for source in sources:
            # Only plain hex colors reach the stylesheet.
            color = source.get("color") or ""
            color = color.lower() if _COLOR.fullmatch(color) else DEFAULT_COLOR
            self.classes[source["id"]] = f"color-{color[1:]}"
            self.colors.add(color)
        rules = []
        for color in sorted(self.colors):
            name = f"color-{color[1:]}"
            rules.append(
                f".dayline button.{name} {{ background: alpha({color}, 0.28);"
                f" border-left-color: {color}; }}\n"
                f".dayline button.{name}:hover {{ background: alpha({color}, 0.4); }}\n"
                f".dayline .dot.{name}, .dayline .bar.{name} {{ background: {color}; }}\n"
            )
        self.provider.load_from_string("".join(rules))

    def apply(self, widget: Gtk.Widget, source_id: str) -> Gtk.Widget:
        widget.add_css_class(self.classes.get(source_id, f"color-{DEFAULT_COLOR[1:]}"))
        return widget


def dot(styles: SourceStyles, source_id: str, css: str = "dot") -> Gtk.Widget:
    widget = Gtk.Box(valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER)
    widget.add_css_class(css)
    return styles.apply(widget, source_id)


def completion_action(task: dict) -> str:
    """Completing or reopening a recurring task applies to its series."""
    verb = "Reopen" if task.get("completed") else "Complete"
    return f"{verb} {'series' if task.get('recurring') else 'task'}"


def item_details(
    item: dict, sources: dict[str, dict], styles: SourceStyles, today: date, open_link, actions=None
):
    """Return item details and their optional focus action button."""
    content = box(True, 8)
    content.set_size_request(DETAILS_WIDTH, -1)
    title = label(item["title"] or "(Untitled)", "heading", wrap=True, chars=DETAILS_CHARS)
    content.append(title)
    when = time_range(item, today) if item["kind"] == "event" else due_label(item, today)
    content.append(label(when, "muted"))
    source = sources.get(item["source_id"], {})
    row = box(False, 8)
    row.append(dot(styles, item["source_id"]))
    role = {"personal": "Personal", "school": "School"}.get(source.get("role"), "")
    name = source.get("name", "Unknown source")
    row.append(label(f"{name} · {role}" if role else name, "small", wrap=True, chars=DETAILS_CHARS))
    content.append(row)
    if item["kind"] == "event" and item.get("recurrence_id"):
        content.append(label("One occurrence of a recurring series", "small", "muted"))
    elif item.get("recurring"):
        content.append(label("Recurring series", "small", "muted"))
    checklist_action = actions.get("checklist") if actions and source.get("writable") else None
    current = dict(item)
    checklist_error = label("", "small", "warning", wrap=True, chars=DETAILS_CHARS)
    checklist_error.set_visible(False)

    def activate_notes(text, uri):
        if uri.startswith("dayline-checklist:"):
            if checklist_action:
                text.set_sensitive(False)
                buttons.set_sensitive(False)
                checklist_error.set_visible(False)

                def saved(updated, error):
                    text.set_sensitive(True)
                    buttons.set_sensitive(True)
                    checklist_error.set_text(error or "")
                    checklist_error.set_visible(bool(error))
                    if updated is not None:
                        current.update(updated)
                        text.set_notes(current["description"])

                checklist_action(current, int(uri.split(":")[1]), saved)
        else:
            open_link(uri)
        return True

    for key in ("location", "description"):
        if item.get(key):
            classes = ("small",) if key == "description" else ()
            if key == "description":
                text = NotesLabel(*classes, chars=DETAILS_CHARS, checklists=bool(checklist_action))
                text.set_notes(item[key])
                text.connect("activate-link", activate_notes)
            else:
                text = label("", *classes, wrap=True, chars=DETAILS_CHARS)
                text.set_markup(link_markup(item[key].strip()))
                text.connect("activate-link", lambda _label, uri: open_link(uri) or True)
            content.append(text)
    content.append(checklist_error)
    if item.get("alarms"):
        times = ", ".join(time_range({"start": value}, today) for value in item["alarms"][:3])
        content.append(
            label(f"Reminder: {times}", "small", "muted", wrap=True, chars=DETAILS_CHARS)
        )
    buttons = box(False, 6)
    if actions and source.get("writable"):
        if item.get("recurrence_id"):
            buttons.append(
                text_button("Edit occurrence", lambda: actions["edit"](current, "occurrence"))
            )
        scope = "series" if item.get("recurring") else "item"
        buttons.append(
            text_button(
                "Edit series" if scope == "series" else "Edit",
                lambda: actions["edit"](current, scope),
            )
        )
        if item["kind"] == "task":
            done = bool(item.get("completed"))
            buttons.append(
                text_button(
                    completion_action(item), lambda: actions["complete"](current, scope, not done)
                )
            )
    else:
        content.append(label("Read-only in Dayline.", "small", "muted"))
    focus_button = None
    if item["kind"] == "task" and not item.get("completed") and actions and actions.get("focus"):
        focus_button = text_button("Focus", lambda: actions["focus"](item), "suggested-action")
        buttons.append(focus_button)
    if buttons.get_first_child() is not None:
        content.append(buttons)
    scroll = Gtk.ScrolledWindow(
        hscrollbar_policy=Gtk.PolicyType.NEVER,
        propagate_natural_height=True,
        max_content_height=420,
    )
    scroll.set_child(content)
    return scroll, focus_button


class Popovers:
    """At most one details popover; clicking elsewhere closes it in the same click.

    Popovers do not autohide: an autohiding popover grabs input, so the click that
    dismisses it never reaches the item underneath and a second click is needed.
    """

    def __init__(self):
        self.current: Gtk.Popover | None = None

    def watch(self, window: Gtk.Window) -> None:
        click = Gtk.GestureClick(button=0)
        # Capture phase: close before the clicked widget handles the same press.
        click.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        click.connect("pressed", self.pressed)
        window.add_controller(click)

    def pressed(self, gesture: Gtk.GestureClick, *_args) -> None:
        # Popovers are children of their anchor, so their presses propagate here too.
        event = gesture.get_current_event()
        if self.current is not None and event.get_surface() is not self.current.get_surface():
            self.close()

    def close(self) -> bool:
        popover, self.current = self.current, None
        if popover is None:
            return False
        popover.popdown()
        return True

    def show(self, anchor: Gtk.Widget, child: Gtk.Widget) -> Gtk.Popover:
        self.close()
        popover = Gtk.Popover(child=child, position=Gtk.PositionType.RIGHT, autohide=False)
        popover.add_css_class("details")
        popover.set_parent(anchor)
        # Unparent after closing so rebuilt views do not keep stale popovers.
        popover.connect("closed", self.closed)
        popover.popup()
        self.current = popover
        return popover

    def closed(self, popover: Gtk.Popover) -> None:
        if self.current is popover:
            self.current = None
        popover.unparent()
