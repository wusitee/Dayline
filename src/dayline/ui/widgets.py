"""Small GTK building blocks shared by the panel and the desktop widget."""

import re
from datetime import date

from gi.repository import Gdk, Gtk, Pango

from dayline.agenda import due_label, link_markup, time_range

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
    for key in ("location", "description"):
        if item.get(key):
            classes = ("small",) if key == "description" else ()
            text = label("", *classes, wrap=True, chars=DETAILS_CHARS)
            # Escaped text with http(s) links, opened in the default browser.
            text.set_markup(link_markup(item[key].strip()))
            text.connect("activate-link", lambda _label, uri: open_link(uri) or True)
            content.append(text)
    if item.get("alarms"):
        times = ", ".join(time_range({"start": value}, today) for value in item["alarms"][:3])
        content.append(
            label(f"Reminder: {times}", "small", "muted", wrap=True, chars=DETAILS_CHARS)
        )
    buttons = box(False, 6)
    if actions and source.get("writable"):
        if item.get("recurrence_id"):
            buttons.append(
                text_button("Edit occurrence", lambda: actions["edit"](item, "occurrence"))
            )
        scope = "series" if item.get("recurring") else "item"
        buttons.append(
            text_button(
                "Edit series" if scope == "series" else "Edit", lambda: actions["edit"](item, scope)
            )
        )
        if item["kind"] == "task" and not item.get("completed"):
            buttons.append(
                text_button(
                    "Complete series" if scope == "series" else "Complete task",
                    lambda: actions["complete"](item, scope),
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
