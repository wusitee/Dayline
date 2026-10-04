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
