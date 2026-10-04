"""Seven-day view: day headers, an all-day area, and a scrollable time grid."""

from collections.abc import Callable
from datetime import date, datetime, timedelta

from gi.repository import Gdk, Graphene, Gtk

from dayline.agenda import (
    Segment,
    all_day_spans,
    covers,
    day_events,
    event_bounds,
    is_all_day,
    layout_end,
    time_range,
    visible_hours,
    week_segments,
)
from dayline.ui.widgets import SourceStyles, box, clear, label

HOUR = 46
GUTTER = 52
ALL_DAY_ROWS = 3
# Short blocks have room for the title only.
META_MINUTES = 50

ShowItem = Callable[[dict, Gtk.Widget], None]


def _rgba(text: str) -> Gdk.RGBA:
    color = Gdk.RGBA()
    color.parse(text)
    return color


GRID_LINE = _rgba("rgba(255, 255, 255, 0.07)")
HALF_LINE = _rgba("rgba(255, 255, 255, 0.03)")
HOUR_TEXT = _rgba("rgba(236, 236, 238, 0.5)")
TODAY_TINT = _rgba("rgba(61, 126, 255, 0.06)")
NOW_LINE = _rgba("#ff7a6b")


def _rect(x: float, y: float, width: float, height: float) -> Graphene.Rect:
    return Graphene.Rect().init(x, y, width, height)


class TimeGrid(Gtk.Widget):
    """Positions one button per clipped event segment; overlapping events get lanes."""

    def __init__(self, show_item: ShowItem, styles: SourceStyles):
        super().__init__()
        self.set_overflow(Gtk.Overflow.HIDDEN)
        self.add_css_class("time-grid")
        self.show_item = show_item
        self.styles = styles
        self.first = date.today()
        self.blocks: list[tuple[Gtk.Widget, Segment]] = []
        self.hours = visible_hours([])
        self.labels = [self.create_pango_layout(f"{hour:02}:00") for hour in range(25)]

    def set_events(self, data: dict, first: date) -> None:
        for widget, _ in self.blocks:
            widget.unparent()
        self.first = first
        self.blocks = []
        today = date.today()
        segments = week_segments(data, first)
        # Working hours by default, widened to the week's earliest and latest events.
        self.hours = visible_hours(segments)
        self.queue_resize()
        for segment in segments:
            item = segment.item
            content = box(True, 0)
            content.append(label(item["title"] or "(Untitled)", "event-title"))
            if layout_end(segment) - segment.start >= META_MINUTES:
                start, end = event_bounds(item)
                meta = f"{start:%H:%M}–{end:%H:%M}" if end > start else f"{start:%H:%M}"
                if item.get("location"):
                    meta = f"{meta} · {item['location']}"
                content.append(label(meta, "event-meta"))
            button = Gtk.Button(child=content, tooltip_text=item["title"])
            button.add_css_class("event")
            self.styles.apply(button, item["source_id"])
            button.update_property(
                [Gtk.AccessibleProperty.LABEL], [f"{item['title']}, {time_range(item, today)}"]
            )
            button.connect("clicked", lambda widget, item=item: self.show_item(item, widget))
            button.set_parent(self)
            self.blocks.append((button, segment))
        self.queue_allocate()
        self.queue_draw()

    def do_dispose(self):
        for widget, _ in self.blocks:
            widget.unparent()
        self.blocks = []

    def do_get_request_mode(self):
        return Gtk.SizeRequestMode.CONSTANT_SIZE

    def do_measure(self, orientation, _for_size):
        if orientation == Gtk.Orientation.HORIZONTAL:
            return GUTTER + 7 * 60, GUTTER + 7 * 110, -1, -1
        height = (self.hours[1] - self.hours[0]) * HOUR
        return height, height, -1, -1

    def day_width(self) -> float:
        return max(1, (self.get_width() - GUTTER) / 7)

    def hour_height(self, height: float) -> float:
        # Rows stretch to fill the panel when the visible hours fit without scrolling.
        return max(HOUR, height / (self.hours[1] - self.hours[0]))

    def y(self, minutes: float, height: float) -> float:
        return (minutes / 60 - self.hours[0]) * self.hour_height(height)

    def do_size_allocate(self, width, height, _baseline):
        day_width = max(1, (width - GUTTER) / 7)
        for widget, segment in self.blocks:
            lane_width = day_width / segment.lanes
            x = GUTTER + segment.day * day_width + segment.lane * lane_width + 1
            y = self.y(segment.start, height) + 1
            bottom = self.y(layout_end(segment), height) - 1
            # GTK requires measuring before allocation; blocks may clip their own content.
            widget.measure(Gtk.Orientation.HORIZONTAL, -1)
            widget.measure(Gtk.Orientation.VERTICAL, -1)
            allocation = Gdk.Rectangle()
            allocation.x, allocation.y = round(x), round(y)
            allocation.width = max(1, round(lane_width - 3))
            allocation.height = max(1, round(bottom - y))
            widget.set_overflow(Gtk.Overflow.HIDDEN)
            widget.size_allocate(allocation, -1)

    def do_snapshot(self, snapshot):
        width, height = self.get_width(), self.get_height()
        day_width = self.day_width()
        offset = (date.today() - self.first).days
        if 0 <= offset < 7:
            snapshot.append_color(
                TODAY_TINT, _rect(GUTTER + offset * day_width, 0, day_width, height)
            )
        row = self.hour_height(height)
        for hour in range(*self.hours):
            y = self.y(hour * 60, height)
            snapshot.append_color(GRID_LINE, _rect(GUTTER, y, width - GUTTER, 1))
            snapshot.append_color(HALF_LINE, _rect(GUTTER, y + row / 2, width - GUTTER, 1))
            layout = self.labels[hour]
            text_height = layout.get_pixel_size()[1]
            # Labels sit centered on their line; the first one sits just below it.
            top = y + 2 if hour == self.hours[0] else y - text_height / 2
            snapshot.save()
            snapshot.translate(Graphene.Point().init(6, top))
            snapshot.append_layout(layout, HOUR_TEXT)
            snapshot.restore()
        for day in range(8):
            x = GUTTER + day * day_width
            snapshot.append_color(GRID_LINE, _rect(min(x, width - 1), 0, 1, height))
        for widget, _ in self.blocks:
            self.snapshot_child(widget, snapshot)
        now = datetime.now()
        minutes = now.hour * 60 + now.minute
        if 0 <= offset < 7 and self.hours[0] * 60 <= minutes < self.hours[1] * 60:
            y = self.y(minutes, height)
            x = GUTTER + offset * day_width
            snapshot.append_color(NOW_LINE, _rect(x, y - 1, day_width, 2))
            snapshot.append_color(NOW_LINE, _rect(x - 3, y - 4, 7, 7))


class WeekView(Gtk.Box):
    """Day headers and all-day spans aligned with the time grid's columns."""

    def __init__(self, show_item: ShowItem, styles: SourceStyles):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.show_item = show_item
        self.styles = styles
        self.first = date.today()
        top = box(False, 0)
        spacer = Gtk.Box()
        spacer.set_size_request(GUTTER, -1)
        top.append(spacer)
        self.columns = Gtk.Grid(column_homogeneous=True, hexpand=True, row_spacing=2)
        top.append(self.columns)
        self.append(top)
        self.grid = TimeGrid(show_item, styles)
        self.scroll = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True, child=self.grid
        )
        self.scroll.set_overlay_scrolling(True)
        self.overlay = Gtk.Overlay(child=self.scroll, vexpand=True)
        self.missing = label("", "notice", wrap=True)
        self.missing.set_halign(Gtk.Align.CENTER)
        self.missing.set_valign(Gtk.Align.START)
        self.missing.set_margin_top(48)
        self.missing.set_max_width_chars(48)
        self.missing.set_visible(False)
        self.overlay.add_overlay(self.missing)
        self.append(self.overlay)

    def set_week(self, data: dict | None, first: date, loading: bool) -> None:
        self.first = first
        shown = (
            data if data is not None and covers(data, first, first + timedelta(days=7)) else None
        )
        if shown is None:
            if loading:
                text = "Reading this week from Thunderbird…"
            elif data is None:
                text = "No calendar data yet."
            else:
                text = "This week is not in the saved snapshot. Refresh while Thunderbird is open."
            self.missing.set_text(text)
        self.missing.set_visible(shown is None)
        content = shown or {"items": []}
        self.grid.set_events(content, first)
        self.set_headers(content)

    def set_headers(self, data: dict) -> None:
        clear(self.columns)
        today = date.today()
        for day in range(7):
            current = self.first + timedelta(days=day)
            head = box(False, 6, "day-head")
            head.set_halign(Gtk.Align.CENTER)
            weekday = label(f"{current:%a}", "weekday", "muted")
            number = Gtk.Label(label=str(current.day))
            number.add_css_class("day-number")
            head.append(weekday)
            head.append(number)
            if current == today:
                head.add_css_class("today")
            self.columns.attach(head, day, 0, 1, 1)
        spans = all_day_spans(data, self.first)
        hidden = [0] * 7
        for span in spans:
            if span.row >= ALL_DAY_ROWS:
                for day in range(span.first, span.last + 1):
                    hidden[day] += 1
                continue
            item = span.item
            title = label(item["title"] or "(Untitled)", "event-title")
            # Day columns share the width equally; long titles ellipsize instead.
            title.set_max_width_chars(1)
            button = Gtk.Button(child=title)
            button.set_tooltip_text(f"{item['title']}\n{time_range(item, today)}")
            button.add_css_class("allday")
            self.styles.apply(button, item["source_id"])
            button.connect("clicked", lambda widget, item=item: self.show_item(item, widget))
            self.columns.attach(button, span.first, span.row + 1, span.last - span.first + 1, 1)
        for day, count in enumerate(hidden):
            if count:
                more = Gtk.Button(label=f"+{count} more")
                more.add_css_class("flat")
                more.add_css_class("small")
                current = self.first + timedelta(days=day)
                more.connect(
                    "clicked",
                    lambda widget, current=current, data=data: self.show_day(data, current, widget),
                )
                self.columns.attach(more, day, ALL_DAY_ROWS + 1, 1, 1)

    def show_day(self, data: dict, day: date, anchor: Gtk.Widget) -> None:
        content = box(True, 4)
        content.append(label(f"All-day · {day:%A %-d %B}", "heading"))
        for item in day_events(data, day):
            if not is_all_day(item):
                continue
            row = Gtk.Button(child=label(item["title"] or "(Untitled)"))
            row.add_css_class("allday")
            self.styles.apply(row, item["source_id"])
            row.connect("clicked", lambda widget, item=item: self.show_item(item, widget))
            content.append(row)
        self.show_popover(anchor, content)

    def show_popover(self, anchor: Gtk.Widget, content: Gtk.Widget) -> None:
        self.get_root().get_application().popovers.show(anchor, content)

    def scroll_to_start(self) -> None:
        self.scroll.get_vadjustment().set_value(0)
