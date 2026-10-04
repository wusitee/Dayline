"""Single-instance GTK application: state, background reads, and change monitoring."""

import signal
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from importlib.resources import files

from gi.repository import Gdk, Gio, GLib, GLibUnix, Gtk, Gtk4LayerShell

from dayline.agenda import covers, status, timestamp_label, week_start, week_title
from dayline.bridge import CHANGE_SIGNAL, cached_snapshot, request, snapshot
from dayline.config import Config, cache_directory
from dayline.errors import DaylineError
from dayline.ui.panel import DesktopWidget, Panel
from dayline.ui.widgets import Popovers, SourceStyles, item_details

APP_ID = "io.github.wusitee.Dayline"


def same_view(a: dict, b: dict) -> bool:
    keys = ("items", "sources", "errors", "ranges")
    return all(a.get(key) == b.get(key) for key in keys)


ACTIONS = ("start", "toggle", "show", "hide", "quit")
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
        self.generation = 0
        self.loading = False
        self.pending = False
        self.debounce = 0
        self.started = False
        self.config_error: str | None = None

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
            },
        )
        self.widget = DesktopWidget(self, self.styles, self.panel.show, self.show_item)
        self.panel.popovers = self.popovers
        for window in (self.panel.window, self.widget.window):
            self.popovers.watch(window)
        cache = cache_directory()
        cache.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.monitor = Gio.File.new_for_path(str(cache)).monitor_directory(
            Gio.FileMonitorFlags.WATCH_MOVES, None
        )
        self.monitor.connect("changed", self.cache_changed)
        GLib.timeout_add_seconds(60, self.tick)
        for number in (signal.SIGINT, signal.SIGTERM):
            GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, number, self.stop)
        self.hold()

    def do_command_line(self, command_line):
        arguments = command_line.get_arguments()
        action = arguments[1] if len(arguments) > 1 else "start"
        if action == "quit":
            self.stop()
            return 0
        if not self.started:
            self.started = True
            self.widget.window.present()
            self.refresh()
        if action == "show" or (action == "toggle" and not self.panel.visible()):
            self.panel.show()
        elif action in ("hide", "toggle"):
            self.panel.hide()
        return 0

    def stop(self) -> bool:
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.quit()
        return GLib.SOURCE_REMOVE

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
        return True

    def adopt(self, config: Config) -> None:
        self.config = config
        # Results requested for the previous selection are discarded.
        self.generation += 1
        self.loading = self.pending = False
        self.panel.set_busy(False)
        self.data = cached_snapshot(config) if config.sources else None
        self.saved, self.error, self.fallback = True, None, None
        # Show the saved snapshot now; a matching live read then skips rebuilding.
        self.render()

    # Background reads

    def background(self, operation, completed) -> None:
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
                if generation == self.generation:
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
        config = Config(dict(self.config.sources))
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
        # A local date change, including after resume, moves the widget's range.
        if date.today() != self.today:
            if self.week == week_start(self.today):
                self.week = week_start(date.today())
            self.today = date.today()
            self.refresh()
        else:
            # Current/next events, overdue tasks, and the now line change with time.
            self.widget.agenda.set_data(self.data, self.warnings())
            self.panel.tasks.set_data(self.data, self.has_tasks())
            self.panel.week.grid.queue_draw()
        return GLib.SOURCE_CONTINUE

    def warnings(self) -> list[str]:
        warnings = (
            [f"{self.config_error} Using the last valid selection."] if self.config_error else []
        )
        if not self.config.sources:
            return warnings + [
                "No sources selected. Choose Sources to add calendars and To Do lists."
            ]
        return warnings + status(self.data, saved=self.saved, error=self.error, today=date.today())

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
            config = Config(apply(self.config.sources))
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
        sources = {source["id"]: source for source in (self.data or {}).get("sources", [])}
        details = item_details(item, sources, self.styles, date.today(), self.open_link)
        self.popovers.show(anchor, details)

    def open_link(self, uri: str) -> None:
        def launched(launcher, result):
            try:
                launcher.launch_finish(result)
            except GLib.Error as exc:
                self.error = f"Cannot open the link: {exc.message}"
                self.render_status()

        # Launch first, then get out of the browser's way: the panel is above it.
        Gtk.UriLauncher.new(uri).launch(None, None, launched)
        self.popovers.close()
        self.panel.hide()

    # Rendering

    def render(self) -> None:
        if self.data is not None:
            self.styles.update(self.data.get("sources", []))
        # Rebuilding the grid and widget destroys the buttons popovers point at.
        self.popovers.close()
        warnings = self.render_status()
        self.panel.title.set_text(week_title(self.week))
        self.panel.week.set_week(self.data, self.week, self.loading)
        self.panel.tasks.set_data(self.data, self.has_tasks())
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
