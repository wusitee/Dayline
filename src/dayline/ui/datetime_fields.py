"""Date and time entries with native calendar and half-hour pickers."""

from collections.abc import Callable
from datetime import date, datetime

from gi.repository import GLib, Gtk

from dayline.datetime_input import parse_date, parse_schedule, parse_time
from dayline.editing import entry_date
from dayline.errors import DaylineError
from dayline.ui.widgets import box, label


class DateTimeField(Gtk.Box):
    def __init__(
        self,
        value: str | None,
        changed: Callable,
        reference: Callable[[], date],
        *,
        nullable: bool = True,
        midnight_is_date: bool = False,
    ):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.changed, self.reference = changed, reference
        self.midnight_is_date = midnight_is_date
        self.updating = False
        self.last_changed = "program"
        row = box(False, 4)
        self.day = Gtk.Entry(hexpand=True, placeholder_text="Date or tomorrow")
        self.day.set_width_chars(10)
        self.day.update_property([Gtk.AccessibleProperty.LABEL], ["Date"])
        row.append(self.day)
        self.calendar = Gtk.Calendar()
        calendar_popup = Gtk.Popover(child=self.calendar)
        self.calendar_button = Gtk.MenuButton(
            icon_name="x-office-calendar-symbolic",
            popover=calendar_popup,
            tooltip_text="Choose date",
        )
        calendar_popup.connect("notify::visible", self.open_calendar)
        self.calendar.connect("day-selected", self.selected_day)
        row.append(self.calendar_button)
        self.clock = Gtk.Entry(placeholder_text="All day")
        self.clock.set_width_chars(6)
        self.clock.set_max_width_chars(8)
        self.clock.update_property([Gtk.AccessibleProperty.LABEL], ["Time"])
        row.append(self.clock)
        times = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.times = times
        for minutes in range(0, 1440, 30):
            text = label(f"{minutes // 60:02}:{minutes % 60:02}")
            text.set_margin_start(12)
            text.set_margin_end(24)
            text.set_margin_top(6)
            text.set_margin_bottom(6)
            times.append(text)
        scroll = Gtk.ScrolledWindow(
            child=times,
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            propagate_natural_height=True,
            max_content_height=240,
        )
        time_popup = Gtk.Popover(child=scroll)
        self.time_button = Gtk.MenuButton(
            icon_name="appointment-soon-symbolic", popover=time_popup, tooltip_text="Choose time"
        )
        times.connect("row-activated", self.selected_time, time_popup)
        time_popup.connect("notify::visible", self.open_times, times)
        row.append(self.time_button)
        if nullable:
            clear = Gtk.Button(icon_name="edit-clear-symbolic", tooltip_text="Clear date and time")
            clear.add_css_class("flat")
            clear.connect("clicked", lambda *_: self.set_value(None))
            row.append(clear)
        self.append(row)
        self.preview = label("", "small", "muted", wrap=True)
        self.append(self.preview)
        self.day.connect("changed", self.entry_changed, "date")
        self.clock.connect("changed", self.entry_changed, "time")
        self.set_value(value, initial=True)

    def fields(self) -> tuple[str, str]:
        return self.day.get_text().strip(), self.clock.get_text().strip()

    def set_value(self, value: str | None, *, initial: bool = False) -> None:
        text = entry_date(value)
        day, _, clock = text.partition(" ")
        if self.midnight_is_date and clock == "00:00":
            clock = ""
        self.updating = True
        self.day.set_text(day)
        self.clock.set_text(clock)
        self.updating = False
        self.program_fields, self.program_value = self.fields(), value
        if initial:
            self.initial_fields, self.initial_value, self.initial_text = self.fields(), value, text
        self.last_changed = "program"
        self.review(notify=not initial)

    def value(self) -> str | None:
        fields = self.fields()
        if fields == self.program_fields:
            return self.program_value
        if fields == self.initial_fields:
            return self.initial_value
        if fields == getattr(self, "parsed_fields", None):
            return self.parsed_value
        day, clock = fields
        if not day:
            if clock:
                raise DaylineError("Choose a date before setting a time.")
            return None
        parsed = parse_date(day, today=date.today(), reference=self.reference())
        if not clock:
            value = parsed.isoformat()
        else:
            value = datetime.combine(parsed, parse_time(clock)).astimezone().isoformat()
        # Keep relative input tied to the preview, even if Save happens after midnight.
        self.parsed_fields, self.parsed_value = fields, value
        return value

    def get_text(self) -> str:
        if self.fields() == self.initial_fields and (
            self.program_fields != self.initial_fields or self.program_value == self.initial_value
        ):
            return self.initial_text
        return self.value() or ""

    def set_text(self, text: str) -> None:
        self.set_value(parse_schedule(text, reference=self.reference()))

    def entry_changed(self, _entry, part: str) -> None:
        if not self.updating:
            self.parsed_fields = None
            self.last_changed = part
            self.review()

    def review(self, *, notify: bool = True) -> None:
        try:
            value = self.value()
            if not value:
                text = "No date"
            elif len(value) == 10:
                text = f"{date.fromisoformat(value):%a %-d %b %Y} · All day"
            else:
                text = f"{datetime.fromisoformat(value).astimezone():%a %-d %b %Y · %H:%M %Z}"
            self.preview.remove_css_class("warning")
        except DaylineError as exc:
            text = str(exc)
            self.preview.add_css_class("warning")
        self.preview.set_text(text)
        if notify:
            self.changed(self)

    def open_calendar(self, popup, *_args) -> None:
        if not popup.get_visible():
            return
        try:
            day = parse_date(self.day.get_text(), today=date.today(), reference=self.reference())
        except DaylineError:
            day = self.reference()
        self.updating = True
        self.calendar.select_day(GLib.DateTime.new_local(day.year, day.month, day.day, 12, 0, 0))
        self.updating = False

    def selected_day(self, calendar) -> None:
        if not self.updating:
            self.day.set_text(calendar.get_date().format("%Y-%m-%d"))
            self.calendar_button.get_popover().popdown()

    def selected_time(self, _list, row, popup) -> None:
        minutes = row.get_index() * 30
        self.clock.set_text(f"{minutes // 60:02}:{minutes % 60:02}")
        popup.popdown()

    def open_times(self, popup, _property, times) -> None:
        if not popup.get_visible():
            return
        try:
            clock = parse_time(self.clock.get_text())
            row = times.get_row_at_index((clock.hour * 60 + clock.minute) // 30)
            times.select_row(row)
            row.grab_focus()
        except DaylineError:
            pass
