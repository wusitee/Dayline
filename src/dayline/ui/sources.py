"""Source selection: the user assigns Personal or School to each Thunderbird source."""

from collections.abc import Callable

from gi.repository import Gtk

from dayline.config import check_selection
from dayline.errors import DaylineError
from dayline.ui.widgets import SourceStyles, box, clear, dot, label, text_button

ROLES = ("Off", "Personal", "School")


class SourceRow:
    def __init__(self, source: dict, selected: dict | None, styles: SourceStyles):
        self.source = source
        self.widget = box(False, 10, "card")
        self.widget.append(dot(styles, source["id"]))
        text = box(True, 2)
        text.set_hexpand(True)
        text.append(label(source["name"], wrap=True))
        kinds = [name for name, key in (("Events", "events"), ("Tasks", "tasks")) if source[key]]
        notes = [" and ".join(kinds) or "No supported items"]
        if source["disabled"]:
            notes.append("Disabled in Thunderbird")
        if source["read_only"]:
            notes.append("Read-only")
        text.append(label(" · ".join(notes), "small", "muted", wrap=True))
        self.widget.append(text)
        self.role = Gtk.DropDown.new_from_strings(ROLES)
        self.role.set_valign(Gtk.Align.CENTER)
        self.role.update_property([Gtk.AccessibleProperty.LABEL], [f"Role for {source['name']}"])
        selected = selected or {}
        self.role.set_selected({"personal": 1, "school": 2}.get(selected.get("role"), 0))
        self.events = Gtk.CheckButton(label="Events", valign=Gtk.Align.CENTER)
        self.events.set_active(selected.get("events", source["events"]))
        self.tasks = Gtk.CheckButton(label="Tasks", valign=Gtk.Align.CENTER)
        self.tasks.set_active(selected.get("tasks", False))
        for widget in (self.role, self.events, self.tasks):
            self.widget.append(widget)
        self.role.connect("notify::selected", lambda *_: self.update())
        self.update()

    def update(self) -> None:
        role = self.role.get_selected()
        usable = not self.source["disabled"]
        self.role.set_sensitive(usable or role != 0)
        self.events.set_sensitive(role != 0 and usable and self.source["events"])
        # School sources never supply tasks.
        self.tasks.set_sensitive(role == 1 and usable and self.source["tasks"])
        if not self.events.get_sensitive():
            self.events.set_active(False if role == 0 else self.events.get_active())
        if not self.tasks.get_sensitive():
            self.tasks.set_active(False)

    def selection(self) -> dict | None:
        role = self.role.get_selected()
        if role == 0:
            return None
        options = {
            "role": "personal" if role == 1 else "school",
            "events": self.events.get_active() and self.source["events"],
            "tasks": self.tasks.get_active() and role == 1 and self.source["tasks"],
        }
        check_selection(options, self.source)
        return options


class SourcesPage(Gtk.Box):
    def __init__(self, styles: SourceStyles, save: Callable[[dict], None], close: Callable):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.styles = styles
        self.save_selection = save
        self.rows: list[SourceRow] = []
        self.missing: dict[str, dict] = {}
        header = box(False, 8)
        header.append(label("Sources", "title"))
        spacer = Gtk.Box(hexpand=True)
        header.append(spacer)
        header.append(text_button("Cancel", close))
        self.save_button = text_button("Save", self.save, "suggested-action")
        header.append(self.save_button)
        self.append(header)
        self.append(
            label(
                "Assign each calendar or To Do list to Personal or School. Roles are your own "
                "labels, not account verification. Only Personal sources can supply tasks.",
                "small",
                "muted",
                wrap=True,
            )
        )
        self.error = label("", "small", "warning", wrap=True)
        self.error.set_visible(False)
        self.append(self.error)
        self.list = box(True, 6)
        self.append(
            Gtk.ScrolledWindow(
                hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True, child=self.list
            )
        )

    def loading(self) -> None:
        clear(self.list)
        self.rows = []
        self.show_error(None)
        self.save_button.set_sensitive(False)
        self.list.append(label("Reading sources from Thunderbird…", "muted"))

    def show_error(self, message: str | None) -> None:
        self.error.set_text(message or "")
        self.error.set_visible(bool(message))

    def set_sources(self, sources: list[dict] | None, selection: dict, error: str | None) -> None:
        clear(self.list)
        self.rows = []
        self.show_error(error)
        self.save_button.set_sensitive(sources is not None)
        if sources is None:
            self.list.append(
                label("Open Thunderbird with Dayline Bridge enabled, then try again.", "muted")
            )
            return
        self.styles.update(sources)
        known = {source["id"] for source in sources}
        # A selected source missing from Thunderbird stays selected until the user removes it.
        self.missing = {uid: options for uid, options in selection.items() if uid not in known}
        if self.missing:
            self.list.append(
                label(
                    f"{len(self.missing)} selected source(s) are no longer in Thunderbird and "
                    "will be kept. Remove them with 'dayline unselect'.",
                    "small",
                    "warning",
                    wrap=True,
                )
            )
        if not sources:
            self.list.append(label("Thunderbird has no calendars or task lists.", "muted"))
        for source in sources:
            row = SourceRow(source, selection.get(source["id"]), self.styles)
            self.rows.append(row)
            self.list.append(row.widget)

    def save(self) -> None:
        selection = dict(self.missing)
        try:
            for row in self.rows:
                options = row.selection()
                if options is not None:
                    selection[row.source["id"]] = options
        except DaylineError as exc:
            self.show_error(f"{row.source['name']}: {exc}")
            return
        self.save_selection(selection)
