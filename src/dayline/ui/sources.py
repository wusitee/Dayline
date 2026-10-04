"""Source selection: the user assigns Personal or School to each Thunderbird source."""

from collections.abc import Callable

from gi.repository import Gtk

from dayline.config import allows_writes, merge_selection
from dayline.ui.widgets import SourceStyles, box, clear, dot, label, text_button

ROLES = ("Off", "Personal", "School")
# Receives a function that applies the page's edits to the latest saved selection.
SaveSelection = Callable[[Callable[[dict], dict]], None]


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
        self.saved = selected
        selected = selected or {}
        self.role.set_selected({"personal": 1, "school": 2}.get(selected.get("role"), 0))
        self.events = Gtk.CheckButton(label="Events", valign=Gtk.Align.CENTER)
        self.events.set_active(selected.get("events", False))
        self.tasks = Gtk.CheckButton(label="Tasks", valign=Gtk.Align.CENTER)
        self.tasks.set_active(selected.get("tasks", False))
        self.edits = Gtk.CheckButton(label="Allow edits", valign=Gtk.Align.CENTER)
        self.edits.set_tooltip_text(
            "Enable only for owned writable calendars; leave subscriptions off."
        )
        self.edits.set_active(allows_writes(selected))
        for widget in (self.role, self.events, self.tasks, self.edits):
            self.widget.append(widget)
        self.role.connect("notify::selected", lambda *_: self.role_changed())
        # Show saved options as they are; only an edit may change them.
        self.update_sensitivity()

    def update_sensitivity(self) -> None:
        role = self.role.get_selected()
        usable = not self.source["disabled"]
        # A disabled source can be turned Off, but not newly selected.
        self.role.set_sensitive(usable or role != 0)
        self.events.set_sensitive(role != 0 and usable and self.source["events"])
        # School sources never supply tasks.
        self.tasks.set_sensitive(role == 1 and usable and self.source["tasks"])
        self.edits.set_sensitive(usable and role != 0 and not self.source["read_only"])

    def role_changed(self) -> None:
        was_off = not (self.events.get_active() or self.tasks.get_active())
        self.update_sensitivity()
        # Turning a source on selects everything its role may supply.
        self.edits.set_active(self.role.get_selected() == 1 and self.edits.get_sensitive())
        for check in (self.events, self.tasks):
            if not check.get_sensitive():
                check.set_active(False)
            elif was_off:
                check.set_active(True)

    def options(self) -> dict | None:
        role = self.role.get_selected()
        if role == 0:
            return None
        options = {
            "role": "personal" if role == 1 else "school",
            "events": self.events.get_active(),
            "tasks": self.tasks.get_active(),
        }
        if (self.saved and "writable" in self.saved) or self.edits.get_active() != (role == 1):
            options["writable"] = self.edits.get_active()
        return options

    def edited(self) -> bool:
        return self.options() != self.saved


class SourcesPage(Gtk.Box):
    def __init__(self, styles: SourceStyles, save: SaveSelection, close: Callable):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.styles = styles
        self.save_selection = save
        self.rows: list[SourceRow] = []
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
        missing = [uid for uid in selection if uid not in known]
        if missing:
            self.list.append(
                label(
                    f"{len(missing)} selected source(s) are no longer in Thunderbird and "
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
        # Only edited rows are applied, onto the selection saved on disk at that moment.
        changes = {row.source["id"]: row.options() for row in self.rows if row.edited()}
        metadata = {row.source["id"]: row.source for row in self.rows}
        self.save_selection(lambda current: merge_selection(current, changes, metadata))
