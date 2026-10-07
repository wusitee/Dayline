"""Single-instance GTK application: state, background reads, and change monitoring."""

import signal
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, datetime, timedelta
from importlib.resources import files

from gi.repository import Gdk, Gio, GLib, GLibUnix, Gtk, Gtk4LayerShell

from dayline.agenda import (
    covers,
    status,
    timestamp_label,
    week_start,
    week_title,
)
from dayline.bridge import CHANGE_SIGNAL, cached_snapshot, read_item, request, snapshot, write_item
from dayline.config import Config, allows_writes, cache_directory, xdg_directory
from dayline.errors import DaylineError
from dayline.focus import FocusTracker, task_key
from dayline.reminders import Reminder, Reminders
from dayline.ui.editor import EditorPage
from dayline.ui.notifications import Notifications
from dayline.ui.panel import DesktopWidget, Panel
from dayline.ui.widgets import Popovers, SourceStyles, item_details

APP_ID = "io.github.wusitee.Dayline"


def same_view(a: dict, b: dict) -> bool:
    keys = ("items", "sources", "errors", "ranges")
    return all(a.get(key) == b.get(key) for key in keys)


ACTIONS = ("start", "toggle", "toggle-widget", "show", "hide", "focus", "quit")
# TbSync often writes several items in a burst; read once after it settles.
CHANGE_DEBOUNCE_MS = 1500


class Application(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dayline-read")
        self.config = Config()
        self.data: dict | None = None
        self.saved = True
        self.error: str | None = None
        self.fallback: dict | None = None
        self.week = week_start(date.today())
        self.today = date.today()
        self.last_tick = datetime.now().timestamp()
        self.generation = 0
        self.loading = False
        self.pending = False
        self.debounce = 0
        self.started = False
        self.config_error: str | None = None
        self.write_status: str | None = None
        self.writing = False
        self.editor_generation = 0
        self.editor_popup: Gtk.Window | None = None
        self.reminders = Reminders(cache_directory() / "task-reminders.json")
        self.reminder_pending: set[str] = set()
        self.reminder_error: str | None = None
        self.focus = FocusTracker(
            xdg_directory("XDG_STATE_HOME", ".local/state") / "dayline" / "focus.json"
        )
        self.focus_details: tuple[dict, Gtk.Button] | None = None

    # Startup and command-line entry points

    def do_startup(self):
        Gtk.Application.do_startup(self)
        if not Gtk4LayerShell.is_supported():
            raise DaylineError("Dayline requires a Wayland compositor with layer-shell support.")
        Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme", True)
        css = Gtk.CssProvider()
        css.load_from_string(files("dayline").joinpath("ui/style.css").read_text())
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        self.styles = SourceStyles()
        self.popovers = Popovers()
        self.panel = Panel(
            self,
            self.styles,
            {
                "previous": lambda: self.move_week(-7),
                "next": lambda: self.move_week(7),
                "today": self.go_today,
                "refresh": self.refresh,
                "sources": self.open_sources,
                "save_sources": self.save_sources,
                "show_item": self.show_item,
                "compose": self.new_item,
                "save_item": self.save_item,
                "cancel_editor": self.cancel_editor,
                "task_reminders": lambda enabled: self.set_reminders("task_reminders", enabled),
                "explicit_alarms": lambda enabled: self.set_reminders("explicit_alarms", enabled),
                "open_link": self.open_link,
            },
            self.focus,
        )
        self.widget = DesktopWidget(
            self,
            self.styles,
            self.panel.show,
            self.show_item,
            lambda kind: self.new_item(kind, popup=True),
            self.focus,
            self.focus_action,
            self.panel.show_focus,
            self.panel.focus.selection,
        )
        self.panel.focus.selection.connect("notify::selected-item", lambda *_: self.focus_tick())
        self.notifications = Notifications(self.open_reminder)
        self.panel.popovers = self.popovers
        self.widget.popovers = self.popovers
        for window in (self.panel.window, self.widget.window):
            self.popovers.watch(window)
        cache = cache_directory()
        cache.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.monitor = Gio.File.new_for_path(str(cache)).monitor_directory(
            Gio.FileMonitorFlags.WATCH_MOVES, None
        )
        self.monitor.connect("changed", self.cache_changed)
        GLib.timeout_add_seconds(60, self.tick)
        GLib.timeout_add_seconds(1, self.focus_tick)
        for number in (signal.SIGINT, signal.SIGTERM):
            GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, number, self.stop)
        self.hold()

    def do_command_line(self, command_line):
        arguments = command_line.get_arguments()
        action = arguments[1] if len(arguments) > 1 else "start"
        if action == "quit":
            self.stop()
            return 0
        starting = not self.started
        if starting:
            self.started = True
            self.widget.window.present()
            self.refresh()
        if action == "toggle-widget":
            if not starting:
                self.widget.window.set_visible(not self.widget.window.get_visible())
            return 0
        if action == "focus":
            self.panel.show_focus()
            return 0
        if action == "show" or (action == "toggle" and not self.panel.visible()):
            self.panel.show()
        elif action in ("hide", "toggle"):
            self.panel.hide()
        return 0

    def stop(self) -> bool:
        if self.focus.loaded:
            self.panel.focus.perform(self.focus.pause)
        self.close_editor_popup(force=True)
        self.popovers.close()
        self.notifications.close()
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.quit()
        return GLib.SOURCE_REMOVE

    def focus_tick(self) -> bool:
        self.panel.focus.tick()
        page = self.panel.focus
        error = page.notice.get_text() if page.notice.get_visible() else None
        item = page.selection.get_selected_item()
        selected = item.get_string() if item else "Unassigned"
        self.widget.set_focus(selected, error)
        self.update_focus_details()
        return GLib.SOURCE_CONTINUE

    def update_focus_details(self) -> None:
        if self.focus_details is None:
            return
        item, button = self.focus_details
        current = self.focus.current
        same_task = current is not None and current["key"] == task_key(item)
        if same_task:
            title = "Focusing on this task" if self.focus.running else "Resume focus"
        else:
            title = "Switch focus to this task" if current else "Focus on this task"
        button.set_label("Focusing" if same_task and self.focus.running else "Focus")
        button.set_tooltip_text(title)
        button.set_sensitive(not (same_task and self.focus.running))

    def focus_action(self, action: str) -> None:
        if action == "toggle":
            self.panel.focus.toggle_timer()
        else:
            self.panel.focus.finish()
        self.focus_tick()

    def focus_task(self, item: dict) -> None:
        self.popovers.close()
        page = self.panel.focus
        current = self.focus.current
        if current and current["key"] != task_key(item):
            if not page.perform(self.focus.finish):
                self.focus_tick()
                return
        if not self.focus.running:
            page.perform(lambda: self.focus.start(item))
        page.set_tasks(self.data)
        self.focus_tick()

    def reload_config(self) -> bool:
        """Adopt the selection on disk, which the CLI may have changed.

        Returns False when config.json is invalid; the current selection is kept.
        """
        try:
            config = Config.load()
        except DaylineError as exc:
            self.config_error = str(exc)
            return False
        self.config_error = None
        if config.sources != self.config.sources:
            self.adopt(config)
        else:
            self.config = config
        self.panel.reminders.set_active(config.task_reminders)
        self.panel.explicit_alarms.set_active(config.explicit_alarms)
        return True

    def adopt(self, config: Config) -> None:
        self.config = config
        self.panel.reminders.set_active(config.task_reminders)
        self.panel.explicit_alarms.set_active(config.explicit_alarms)
        # Results requested for the previous selection are discarded.
        self.generation += 1
        self.editor_generation += 1
        self.close_editor_popup(force=True)
        self.popovers.close()
        self.panel.editor.set_busy(self.writing)
        self.panel.show_agenda()
        self.loading = self.pending = False
        self.panel.set_busy(False)
        self.data = cached_snapshot(config) if config.sources else None
        self.saved, self.error, self.fallback = True, None, None
        # Show the saved snapshot now; a matching live read then skips rebuilding.
        self.render()

    # Background reads

    def background(self, operation, completed, *, discard_on_change: bool = True) -> None:
        """Run a blocking bridge call off GTK's main thread; deliver results on it."""
        generation = self.generation

        def finished(future):
            try:
                value, error = future.result(), None
            except (DaylineError, OSError, ValueError) as exc:
                value, error = None, str(exc)
            except Exception as exc:  # A bug must not leave the UI waiting forever.
                value, error = None, f"Unexpected read failure: {exc}"

            def deliver():
                # Discard results requested before a selection change.
                if not discard_on_change or generation == self.generation:
                    completed(value, error)
                return GLib.SOURCE_REMOVE

            GLib.idle_add(deliver)

        try:
            self.executor.submit(operation).add_done_callback(finished)
        except RuntimeError:  # Shutting down.
            pass

    def refresh(self) -> None:
        self.reload_config()
        if not self.config.sources:
            self.render()
            return
        if self.loading:
            self.pending = True
            return
        self.loading = True
        self.panel.set_busy(True)
        config = replace(self.config, sources=dict(self.config.sources))
        week = self.week
        self.background(lambda: snapshot(config, week), self.refreshed)
        self.render_status()

    def refreshed(self, data: dict | None, error: str | None) -> None:
        self.loading = False
        self.panel.set_busy(False)
        previous = self.data
        if data is not None:
            self.data, self.saved, self.error = data, False, None
            # Provider failures leave the last complete snapshot in place; offer it.
            self.fallback = cached_snapshot(self.config) if data.get("errors") else None
        else:
            self.error = error
            if self.data is None:
                self.data = cached_snapshot(self.config)
                self.saved = True
        if (
            self.data is not None
            and previous is not None
            and same_view(previous, self.data)
            and self.panel.week.first == self.week
            and covers(self.data, self.week, self.week + timedelta(days=7))
        ):
            # A read that changes nothing keeps open details and avoids rebuilding.
            self.widget.agenda.set_warnings(self.render_status())
        else:
            self.render()
        self.check_reminders()
        if self.pending:
            self.pending = False
            self.refresh()

    def cache_changed(self, _monitor, file, other, _event) -> None:
        names = {file.get_basename(), other.get_basename() if other else None}
        # Only the bridge's change signal triggers a read; snapshot writes would loop.
        if CHANGE_SIGNAL not in names:
            return
        if self.debounce:
            GLib.source_remove(self.debounce)
        self.debounce = GLib.timeout_add(CHANGE_DEBOUNCE_MS, self.changed_settled)

    def changed_settled(self) -> bool:
        self.debounce = 0
        self.refresh()
        return GLib.SOURCE_REMOVE

    def tick(self) -> bool:
        now = datetime.now().timestamp()
        resumed = now - self.last_tick > 120
        self.last_tick = now
        # A local date change, including after resume, moves the widget's range.
        if date.today() != self.today:
            if self.week == week_start(self.today):
                self.week = week_start(date.today())
            self.today = date.today()
            self.render()
            self.refresh()
        else:
            # Current/next events, overdue tasks, and the now line change with time.
            self.widget.agenda.set_data(self.data, self.warnings())
            self.panel.tasks.set_data(self.data, self.has_tasks())
            self.panel.week.grid.queue_draw()
        if resumed:
            self.refresh()
        self.check_reminders()
        return GLib.SOURCE_CONTINUE

    def warnings(self) -> list[str]:
        warnings = (
            [f"{self.config_error} Using the last valid selection."] if self.config_error else []
        )
        if not self.config.sources:
            warnings.append("No sources selected. Choose Sources to add calendars and To Do lists.")
        else:
            warnings.extend(
                status(self.data, saved=self.saved, error=self.error, today=date.today())
            )
        if self.write_status:
            warnings.append(self.write_status)
        if (self.config.task_reminders or self.config.explicit_alarms) and self.reminder_error:
            warnings.append(self.reminder_error)
        return warnings

    def has_tasks(self) -> bool:
        return any(options["tasks"] for options in self.config.sources.values())

    # Navigation and sources

    def move_week(self, days: int) -> None:
        self.go_to(self.week + timedelta(days=days))

    def go_today(self) -> None:
        self.go_to(week_start(date.today()))
        self.panel.week.scroll_to_start()

    def go_to(self, week: date) -> None:
        # Show the week from the current data at once; the read replaces it when done.
        self.week = week
        self.popovers.close()
        self.panel.title.set_text(week_title(week))
        self.panel.week.set_week(self.data, week, loading=True)
        self.panel.agenda.set_week(self.data, week, loading=True)
        self.refresh()

    def open_sources(self) -> None:
        self.reload_config()
        self.render()
        self.panel.show_sources()
        self.panel.sources.loading()
        self.background(lambda: request("sources")["sources"], self.sources_received)

    def sources_received(self, sources: list | None, error: str | None) -> None:
        self.panel.sources.set_sources(sources, self.config.sources, error)

    def save_sources(self, apply) -> None:
        # Merge into the selection on disk so CLI changes since opening are kept.
        if not self.reload_config():
            self.panel.sources.show_error(f"{self.config_error} Fix it before saving.")
            return
        try:
            config = replace(self.config, sources=apply(self.config.sources))
            if config.sources != self.config.sources:
                config.save()
        except DaylineError as exc:
            self.panel.sources.show_error(str(exc))
            return
        except OSError:
            self.panel.sources.show_error("Cannot save the selection; check config permissions.")
            return
        self.panel.show_agenda()
        if config.sources != self.config.sources:
            self.adopt(config)
            self.refresh()

    def show_saved(self) -> None:
        if self.fallback is not None:
            self.data, self.saved, self.fallback = self.fallback, True, None
            self.render()

    def show_item(self, item: dict, anchor: Gtk.Widget) -> None:
        if self.writing:
            return
        sources = {source["id"]: source for source in (self.data or {}).get("sources", [])}
        writable = {source["id"] for source in self.editable_sources(item["kind"])}
        if (
            item["source_id"] in writable
            and not item.get("recurring")
            and self.popup_anchor(anchor) is None
        ):
            self.edit_item(item, "item")
            return
        for uid, source in sources.items():
            source = dict(source)
            source["writable"] = uid in writable
            sources[uid] = source
        details, focus_button = item_details(
            item,
            sources,
            self.styles,
            date.today(),
            self.open_link,
            {
                "edit": lambda item, scope: self.edit_item(item, scope, self.popup_anchor(anchor)),
                "complete": self.complete_item,
                "focus": self.focus_task if self.focus.loaded else None,
            },
        )
        popover = self.popovers.show(anchor, details)
        if focus_button is not None:
            self.focus_details = (item, focus_button)
            self.update_focus_details()

            def closed(*_args):
                if self.focus_details and self.focus_details[1] is focus_button:
                    self.focus_details = None

            popover.connect("closed", closed)

    def popup_anchor(self, anchor: Gtk.Widget) -> Gtk.Widget | None:
        if (
            anchor.get_root() is self.widget.window
            or self.panel.views.get_visible_child_name() == "week"
        ):
            return anchor
        return None

    @property
    def editor(self) -> EditorPage:
        return self.editor_popup.get_child() if self.editor_popup else self.panel.editor

    def editable_sources(self, kind: str) -> list[dict]:
        return [
            source
            for source in (self.data or {}).get("sources", [])
            if not source["read_only"]
            and not source["disabled"]
            and source["id"] in self.config.sources
            and allows_writes(self.config.sources[source["id"]])
            and self.config.sources[source["id"]]["events" if kind == "event" else "tasks"]
        ]

    def cancel_editor(self) -> None:
        if not self.writing:
            self.editor_generation += 1
            self.close_editor_popup()
            self.popovers.close()
            self.panel.show_agenda()

    def new_item(self, kind: str, title: str = "", *, popup: bool = False) -> None:
        if self.writing:
            return
        self.reload_config()
        self.close_editor_popup()
        self.editor_generation += 1
        self.popovers.close()
        editor = self.open_editor_popup(kind) if popup else self.panel.editor
        editor.load(kind, self.editable_sources(kind), None, "item")
        editor.entries["title"].set_text(title)
        if not popup:
            self.panel.show_editor()
            self.panel.show()
        editor.entries["title"].grab_focus()

    def edit_item(self, item: dict, scope: str, anchor: Gtk.Widget | None = None) -> None:
        if self.writing:
            return
        self.reload_config()
        self.close_editor_popup()
        self.popovers.close()
        self.editor_generation += 1
        generation = self.editor_generation
        if anchor is not None:
            editor = self.open_editor_popup(item["kind"])
            editor.loading()
        else:
            editor = self.panel.editor
            editor.loading()
            self.panel.show_editor()
            self.panel.show()

        def loaded(current, error):
            if generation != self.editor_generation:
                return
            editor.set_busy(False)
            sources = self.editable_sources(item["kind"])
            if error or not any(s["id"] == item["source_id"] for s in sources):
                editor.show_error(error or "This source is read-only in Dayline.")
                editor.save_button.set_sensitive(False)
            else:
                editor.load(item["kind"], sources, current, scope)
                editor.entries["title"].grab_focus()

        config = replace(self.config, sources=dict(self.config.sources))
        self.background(lambda: read_item(config, item, scope), loaded)

    def open_editor_popup(self, kind: str) -> EditorPage:
        self.panel.show_agenda()
        editor = EditorPage(self.save_item, self.cancel_editor, self.open_link)
        self.editor_popup = Gtk.Window(
            application=self,
            title=f"{kind.capitalize()} details — Dayline",
            child=editor,
            default_width=440,
            default_height=640,
            resizable=False,
            modal=True,
            transient_for=self.panel.window,
        )
        self.editor_popup.add_css_class("dayline")
        self.editor_popup.add_css_class("main-window")
        self.editor_popup.connect("close-request", lambda *_: self.close_editor_popup())
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self.popup_key_pressed)
        self.editor_popup.add_controller(keys)
        self.editor_popup.present()
        return editor

    def close_editor_popup(self, *, force: bool = False) -> bool:
        if self.editor_popup is None:
            return False
        if self.writing and not force:
            return True
        popup, self.editor_popup = self.editor_popup, None
        self.editor_generation += 1
        popup.get_child().stop_detection()
        popup.destroy()
        return True

    def popup_key_pressed(self, _controller, key, _code, _state) -> bool:
        return self.close_editor_popup() if key == Gdk.KEY_Escape else False

    def complete_item(self, item: dict, scope: str) -> None:
        self.popovers.close()
        self.save_item("update", item, {"completed": True}, scope)

    def save_item(self, command: str, item: dict, fields: dict, scope: str) -> None:
        if self.writing:
            return
        if not self.reload_config():
            self.editor.show_error(f"{self.config_error} Fix it before saving.")
            self.widget.agenda.set_warnings(self.render_status())
            return
        self.writing = True
        editor = self.editor
        editor.set_busy(True)
        config = replace(self.config, sources=dict(self.config.sources))

        def saved(result, error):
            self.writing = False
            editor.set_busy(False)
            if error:
                editor.show_error(error)
                self.write_status = f"Could not save: {error}"
            else:
                self.write_status = None
                self.close_editor_popup()
                self.popovers.close()
                if command == "create" and editor is self.panel.editor:
                    self.panel.quick_title.set_text("")
                self.panel.show_agenda()
                if (
                    command == "update"
                    and "completed" in fields
                    and self.data is not None
                    and config.sources == self.config.sources
                ):
                    # Show accepted completion changes without waiting for a full read.
                    current = result["item"]
                    self.data = {
                        **self.data,
                        "items": [
                            existing
                            for existing in self.data.get("items", [])
                            if any(
                                existing.get(key) != current.get(key)
                                for key in ("kind", "source_id", "uid", "recurrence_id")
                            )
                        ]
                        + [current],
                    }
                    self.render()
                self.refresh()
            self.widget.agenda.set_warnings(self.render_status())

        self.background(
            lambda: write_item(config, command, item, fields, scope), saved, discard_on_change=False
        )

    def open_link(self, uri: str) -> None:
        def launched(launcher, result):
            try:
                launcher.launch_finish(result)
            except GLib.Error as exc:
                self.error = f"Cannot open the link: {exc.message}"
                self.render_status()

        Gtk.UriLauncher.new(uri).launch(None, None, launched)
        self.popovers.close()

    # Local reminders

    def set_reminders(self, setting: str, enabled: bool) -> None:
        if enabled == getattr(self.config, setting):
            return
        if not self.reload_config():
            self.panel.reminders.set_active(self.config.task_reminders)
            self.panel.explicit_alarms.set_active(self.config.explicit_alarms)
            self.render_status()
            return
        config = replace(self.config, **{setting: enabled})
        try:
            config.save()
        except OSError:
            self.reminder_error = "Cannot save reminder settings; check config permissions."
            self.panel.reminders.set_active(self.config.task_reminders)
            self.panel.explicit_alarms.set_active(self.config.explicit_alarms)
            self.panel.set_warnings([self.reminder_error], None)
            return
        self.config = config
        self.panel.reminders.set_active(config.task_reminders)
        self.panel.explicit_alarms.set_active(config.explicit_alarms)
        self.check_reminders()
        self.widget.agenda.set_warnings(self.render_status())

    def check_reminders(self) -> None:
        if (
            not (self.config.task_reminders or self.config.explicit_alarms)
            or self.data is None
            or self.writing
            or self.loading
        ):
            return
        # A saved fallback may contain deleted items or sources no longer selected.
        data = dict(self.data)
        data["items"] = [
            item
            for item in self.data.get("items", [])
            if self.config.sources.get(item["source_id"], {}).get(
                "tasks" if item["kind"] == "task" else "events"
            )
        ]
        try:
            ready = self.reminders.ready(
                data,
                datetime.now().astimezone(),
                task_due=self.config.task_reminders,
                explicit=self.config.explicit_alarms,
            )
        except DaylineError as exc:
            self.reminder_error = str(exc)
            self.render_status()
            return
        for reminder in ready:
            if reminder.key in self.reminder_pending:
                continue
            self.reminder_pending.add(reminder.key)
            self.notifications.send(
                reminder, lambda error, reminder=reminder: self.reminder_sent(reminder, error)
            )

    def reminder_sent(self, reminder: Reminder, error: str | None) -> None:
        self.reminder_pending.discard(reminder.key)
        self.reminder_error = f"Could not deliver reminder: {error}" if error else None
        if error is None:
            try:
                self.reminders.mark_sent(reminder)
            except OSError:
                self.reminder_error = "Reminder sent, but its history could not be saved."
        self.render_status()

    def open_reminder(self, target: dict) -> None:
        self.panel.show_agenda()
        self.panel.view_selector.set_selected(1)
        self.panel.show()
        if not self.config.sources.get(target["source_id"], {}).get(
            "tasks" if target["kind"] == "task" else "events"
        ):
            return

        def show_current(item, error=None):
            if error:
                self.reminder_error = f"Cannot open reminder: {error}"
                self.render_status()
                return
            if item is None or item.get("completed") or item.get("cancelled"):
                return
            self.show_item(item, self.panel.view_selector)

        for item in (self.data or {}).get("items", []):
            if (
                item["kind"] == target["kind"]
                and item["source_id"] == target["source_id"]
                and item["uid"] == target["uid"]
                and item.get("recurrence_id") == target.get("recurrence_id")
            ):
                show_current(item)
                return
        # Calendar navigation can drop events outside the current read ranges.
        scope = (
            "occurrence"
            if target.get("recurrence_id")
            else ("series" if target.get("recurring") else "item")
        )
        config = replace(self.config, sources=dict(self.config.sources))
        self.background(lambda: read_item(config, target, scope), show_current)

    # Rendering

    def render(self) -> None:
        if self.data is not None:
            self.styles.update(self.data.get("sources", []))
        self.popovers.close()
        warnings = self.render_status()
        self.panel.title.set_text(week_title(self.week))
        self.panel.week.set_week(self.data, self.week, self.loading)
        self.panel.agenda.set_week(self.data, self.week, self.loading)
        self.panel.tasks.set_data(self.data, self.has_tasks())
        self.panel.focus.set_tasks(self.data)
        self.widget.agenda.set_data(self.data, warnings)

    def render_status(self) -> list[str]:
        """Update the banner and freshness summary only."""
        today = date.today()
        warnings = self.warnings()
        action = None
        if self.fallback is not None:
            read = timestamp_label(self.fallback["generated_at"], today)
            action = (f"Show complete snapshot from {read}", self.show_saved)
        self.panel.set_warnings(warnings, action)
        if self.loading:
            self.panel.summary.set_text("Reading Thunderbird…")
        elif self.data is not None:
            read = timestamp_label(self.data["generated_at"], today)
            self.panel.summary.set_text(f"Saved {read}" if self.saved else f"Updated {read}")
        else:
            self.panel.summary.set_text("")
        return warnings


def run(action: str) -> int:
    return Application().run(["dayline", action])
