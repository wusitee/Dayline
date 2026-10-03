"""Small GTK building blocks shared by the panel and the desktop widget."""

import re
from datetime import date

from gi.repository import Gdk, Gtk, Pango

from dayline.agenda import due_label, time_range

DEFAULT_COLOR = "#8a9bb0"
_COLOR = re.compile(r"#[0-9a-fA-F]{6}")


def label(text: str, *classes: str, wrap: bool = False, lines: int = 0) -> Gtk.Label:
    widget = Gtk.Label(label=text, xalign=0)
    if wrap:
        widget.set_wrap(True)
        widget.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        widget.set_natural_wrap_mode(Gtk.NaturalWrapMode.WORD)
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


def item_details(item: dict, sources: dict[str, dict], styles: SourceStyles, today: date):
    """A read-only summary of one event occurrence or task."""
    content = box(True, 8)
    content.set_size_request(320, -1)
    title = label(item["title"] or "(Untitled)", "heading", wrap=True)
    title.set_max_width_chars(44)
    content.append(title)
    when = time_range(item, today) if item["kind"] == "event" else due_label(item, today)
    content.append(label(when, "muted"))
    source = sources.get(item["source_id"], {})
    row = box(False, 8)
    row.append(dot(styles, item["source_id"]))
    role = {"personal": "Personal", "school": "School"}.get(source.get("role"), "")
    name = source.get("name", "Unknown source")
    row.append(label(f"{name} · {role}" if role else name, "small", wrap=True))
    content.append(row)
    if item["kind"] == "event" and item.get("recurrence_id"):
        content.append(label("One occurrence of a recurring series", "small", "muted"))
    elif item.get("recurring"):
        content.append(label("Recurring series", "small", "muted"))
    for key in ("location", "description"):
        if item.get(key):
            classes = ("small",) if key == "description" else ()
            text = label(item[key].strip(), *classes, wrap=True)
            text.set_max_width_chars(52)
            content.append(text)
    if item.get("alarms"):
        times = ", ".join(time_range({"start": value}, today) for value in item["alarms"][:3])
        content.append(label(f"Reminder: {times}", "small", "muted", wrap=True))
    content.append(label("Editing is not available yet.", "small", "muted"))
    scroll = Gtk.ScrolledWindow(
        hscrollbar_policy=Gtk.PolicyType.NEVER,
        propagate_natural_height=True,
        max_content_height=420,
    )
    scroll.set_child(content)
    return scroll


def show_popover(anchor: Gtk.Widget, child: Gtk.Widget) -> Gtk.Popover:
    popover = Gtk.Popover(child=child, position=Gtk.PositionType.RIGHT)
    popover.add_css_class("details")
    popover.set_parent(anchor)
    # Unparent after closing so rebuilt views do not keep stale popovers.
    popover.connect("closed", lambda widget: widget.unparent())
    popover.popup()
    return popover
