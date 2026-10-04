"""Native GTK regression checks; run explicitly inside a Wayland desktop session."""

# Load GTK versions and layer-shell before importing GI namespaces.
from dayline.ui.app import Application

# isort: split

import os
import time
from datetime import date, datetime, timedelta
from importlib.resources import files
from types import SimpleNamespace

import pytest
from gi.repository import Gdk, GLib, Gtk

from dayline.agenda import week_start
from dayline.config import Config
from dayline.ui.panel import DesktopWidget
from dayline.ui.tasks import DesktopAgenda, TaskList
from dayline.ui.week import WeekView
from dayline.ui.widgets import Popovers, SourceStyles


@pytest.fixture
def styles():
    Gtk.init()
    css = Gtk.CssProvider()
    css.load_from_string(files("dayline").joinpath("ui/style.css").read_text())
    display = Gdk.Display.get_default()
    Gtk.StyleContext.add_provider_for_display(display, css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    yield SourceStyles()
    Gtk.StyleContext.remove_provider_for_display(display, css)


def settle_until(predicate):
    loop = GLib.MainLoop()
    deadline = time.monotonic() + 3

    def check():
        if predicate() or time.monotonic() >= deadline:
            loop.quit()
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    GLib.timeout_add(10, check)
    loop.run()
    assert predicate()


def snapshot(items):
    first = week_start(date.today())
    return {
        "generated_at": datetime.now().astimezone().isoformat(),
        "ranges": [{"start": first.isoformat(), "end": (first + timedelta(days=14)).isoformat()}],
        "sources": [],
        "items": items,
        "errors": [],
        "offline": False,
    }


@pytest.mark.parametrize("navigate", [False, True])
def test_failed_read_finishes_week_notice_and_preserves_unchanged_grid(styles, navigate):
    app = Application()
    first = week_start(date.today())
    start = datetime.now().astimezone()
    app.data = snapshot(
        [
            {
                "kind": "event",
                "source_id": "source",
                "uid": "event",
                "title": "Meeting",
                "start": start.isoformat(),
                "end": (start + timedelta(hours=1)).isoformat(),
            }
        ]
    )
    app.config = Config({"source": {"role": "personal", "events": True, "tasks": False}})
    app.reload_config = lambda: True
    app.styles, app.popovers = styles, Popovers()
    app.panel = SimpleNamespace(
        week=WeekView(lambda *_: None, styles),
        tasks=TaskList(lambda *_: None, styles),
        title=Gtk.Label(),
        summary=Gtk.Label(),
        set_busy=lambda _: None,
        set_warnings=lambda *_: None,
    )
    app.widget = SimpleNamespace(agenda=DesktopAgenda(styles, lambda *_: None))
    app.background = lambda operation, completed: completed(None, "Bridge unavailable")
    try:
        app.render()
        button = app.panel.week.grid.blocks[0][0]
        if navigate:
            app.go_to(first + timedelta(days=28))
        else:
            app.refresh()
        assert not app.loading
        assert app.panel.week.first == app.week
        if navigate:
            assert app.panel.week.missing.get_visible()
            assert "not in the saved snapshot" in app.panel.week.missing.get_text()
        else:
            assert not app.panel.week.missing.get_visible()
            assert app.panel.week.grid.blocks[0][0] is button
            assert app.widget.agenda.notice.get_visible()
            assert "Bridge unavailable" in app.widget.agenda.notice.get_text()
            app.refreshed(app.data, None)
            assert app.panel.week.grid.blocks[0][0] is button
            assert not app.widget.agenda.notice.get_visible()
    finally:
        app.executor.shutdown(wait=False, cancel_futures=True)


def test_busy_widget_keeps_fixed_surface_and_last_task_reachable(styles):
    app = Gtk.Application(application_id=f"io.github.wusitee.Dayline.Test{os.getpid()}")
    app.register(None)
    shown = []
    widget = DesktopWidget(app, styles, lambda: None, lambda item, _: shown.append(item))
    tomorrow = date.today() + timedelta(days=1)
    start = datetime.combine(tomorrow, datetime.min.time()).astimezone() + timedelta(hours=9)
    items = []
    for i in range(5):
        items.append(
            {
                "kind": "event",
                "source_id": "source",
                "uid": f"event-{i}",
                "title": "A long calendar event title that takes two lines to display",
                "start": start.isoformat(),
                "end": (start + timedelta(hours=1)).isoformat(),
                "location": "A long location name displayed below the event title",
            }
        )
        items.append(
            {
                "kind": "task",
                "source_id": "source",
                "uid": f"task-{i}",
                "title": f"Task {i}",
                "due": tomorrow.isoformat(),
            }
        )
    widget.agenda.offset = 1
    widget.agenda.set_data(snapshot(items), ["A selected source could not be read."])
    widget.window.present()
    try:
        settle_until(lambda: widget.agenda.get_height() > widget.HEIGHT)
        assert (widget.window.get_width(), widget.window.get_height()) == (320, 640)
        adjustment = widget.scroll.get_vadjustment()
        offset = widget.agenda.offset
        assert not widget.agenda.scrolled(None, 0, 1)
        assert widget.agenda.offset == offset
        adjustment.set_value(adjustment.get_upper() - adjustment.get_page_size())
        task = widget.agenda.get_last_child()

        def visible():
            success, bounds = task.compute_bounds(widget.scroll)
            return success and bounds.get_y() >= 0 and bounds.get_y() + bounds.get_height() <= 640

        settle_until(visible)
        task.emit("clicked")
        assert shown[0]["uid"] == "task-4"
        widget.agenda.set_data(snapshot([]), [])
        settle_until(lambda: widget.scroll.get_vadjustment().get_upper() <= widget.HEIGHT)
        assert (widget.window.get_width(), widget.window.get_height()) == (320, 640)
        assert widget.agenda.scrolled(None, 0, -1)
        assert widget.agenda.offset == offset - 1
    finally:
        widget.window.destroy()


def test_widget_toggle_starts_visible_and_keeps_panel_independent(styles, monkeypatch):
    monkeypatch.setattr("dayline.ui.app.APP_ID", f"io.github.wusitee.Dayline.Toggle{os.getpid()}")
    app = Application()
    app.register(None)
    app.refresh = lambda: None
    command = SimpleNamespace(get_arguments=lambda: ["dayline", "toggle-widget"])
    try:
        app.do_command_line(command)
        assert app.widget.window.get_visible()
        assert not app.panel.visible()
        app.do_command_line(command)
        assert not app.widget.window.get_visible()
        app.panel.show()
        app.do_command_line(command)
        assert app.widget.window.get_visible()
        assert app.panel.visible()
        app.do_command_line(command)
        assert not app.widget.window.get_visible()
        assert app.panel.visible()
    finally:
        app.stop()
        for window in app.get_windows():
            window.destroy()


def test_calendar_starts_at_seven_and_scrolls_to_both_ends(styles):
    window = Gtk.Window(default_width=900, default_height=650)
    week = WeekView(lambda *_: None, styles)
    first = week_start(date.today())
    week.set_week(snapshot([]), first, False)
    window.set_child(week)
    # Request the initial position before the first layout, as Panel.show does.
    week.scroll_to_start()
    window.present()
    adjustment = week.scroll.get_vadjustment()
    try:
        settle_until(lambda: adjustment.get_page_size() > 0 and adjustment.get_value() > 0)
        seven = week.grid.y(7 * 60, week.grid.get_height())
        assert adjustment.get_value() == pytest.approx(seven)
        assert adjustment.get_upper() > adjustment.get_page_size()
        adjustment.set_value(0)
        assert adjustment.get_value() == 0
        adjustment.set_value(adjustment.get_upper())
        assert adjustment.get_value() > seven
        assert week.grid.y(23 * 60, week.grid.get_height()) >= adjustment.get_value()
    finally:
        window.destroy()


def test_editor_sends_only_changed_fields_and_reuses_creation_identity(styles):
    from dayline.ui.editor import EditorPage

    saved = []
    editor = EditorPage(lambda *args: saved.append(args), lambda: None)
    source = {"id": "source", "name": "Test calendar"}
    item = {
        "kind": "event",
        "source_id": "source",
        "uid": "uid",
        "revision": "revision",
        "title": "Meeting",
        "start": "2026-10-05T03:00:45Z",
        "end": "2026-10-05T04:00:45Z",
        "description": "Keep notes",
        "alarms": ["2026-10-05T02:30:45Z"],
    }
    editor.load("event", [source], item, "item")
    editor.entries["title"].set_text("Renamed")
    editor.save()
    assert saved[-1][0] == "update"
    assert saved[-1][2] == {"title": "Renamed"}
    editor.load("task", [source], None, "item")
    editor.entries["title"].set_text("New task")
    editor.save()
    uid = saved[-1][1]["uid"]
    editor.save()
    assert saved[-1][0] == "create"
    assert saved[-1][1]["uid"] == uid
    assert saved[-1][2]["due"] is None
    editor.load("task", [], None, "item")
    assert not editor.save_button.get_sensitive()
