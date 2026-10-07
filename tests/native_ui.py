"""Native GTK regression checks; run explicitly inside a Wayland desktop session."""

# Load GTK versions and layer-shell before importing GI namespaces.
from dayline.ui.app import Application

# isort: split

import os
import shlex
import time
from datetime import UTC, date, datetime, timedelta
from importlib.resources import files
from pathlib import Path
from types import SimpleNamespace

import pytest
from gi.repository import Gdk, Gio, GLib, Gtk, Gtk4LayerShell

from dayline.agenda import week_start
from dayline.config import Config
from dayline.focus import FocusTracker, task_key
from dayline.integration import install_desktop
from dayline.reminders import Reminders
from dayline.ui.agenda import AgendaView
from dayline.ui.focus import FocusClock, FocusPage
from dayline.ui.panel import DesktopWidget, Panel
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


def test_desktop_entries_preserve_special_paths_and_launch_actions(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / 'desktop path $% "'))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    installed = install_desktop(autostart=True)
    recorder = tmp_path / "arguments.txt"
    Path(installed["launcher"]).write_text(
        f"#!/bin/sh\nprintf '%s\\n' \"$@\" > {shlex.quote(str(recorder))}\n"
    )
    for entry, action in (("application", "toggle"), ("autostart", "start")):
        application = Gio.DesktopAppInfo.new_from_filename(installed[entry])
        assert application is not None
        application.launch([], None)
        settle_until(
            lambda: recorder.exists() and recorder.read_text().splitlines() == ["ui", action]
        )
        recorder.unlink()


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
        agenda=AgendaView(lambda *_: None, styles),
        tasks=TaskList(lambda *_: None, styles),
        focus=SimpleNamespace(set_tasks=lambda *_: None),
        statistics=SimpleNamespace(set_data=lambda *_: None),
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
            app.write_status = "Saved in Thunderbird. Cloud synchronization is not confirmed."
            app.refresh()
        assert not app.loading
        assert app.panel.week.first == app.week
        if navigate:
            assert app.panel.week.missing.get_visible()
            assert "not in the saved snapshot" in app.panel.week.missing.get_text()
            assert app.panel.agenda.missing.get_visible()
            assert "not in the saved snapshot" in app.panel.agenda.missing.get_text()
            assert app.panel.agenda.list.get_first_child() is None
        else:
            assert not app.panel.week.missing.get_visible()
            assert app.panel.week.grid.blocks[0][0] is button
            assert app.widget.agenda.notice.get_visible()
            assert "Bridge unavailable" in app.widget.agenda.notice.get_text()
            app.tick()
            assert "Bridge unavailable" in app.widget.agenda.notice.get_text()
            app.write_status = None
            app.refreshed(app.data, None)
            assert app.panel.week.grid.blocks[0][0] is button
            assert not app.widget.agenda.notice.get_visible()
    finally:
        app.executor.shutdown(wait=False, cancel_futures=True)


def test_busy_widget_uses_full_column_and_keeps_last_task_reachable(styles, tmp_path):
    app = Gtk.Application(application_id=f"io.github.wusitee.Dayline.Test{os.getpid()}")
    app.register(None)
    shown = []
    drafts = []
    opened = []
    tracker = FocusTracker(tmp_path / "focus.json")
    tracker.load()
    widget = DesktopWidget(
        app,
        styles,
        lambda: opened.append(True),
        lambda item, _: shown.append(item),
        drafts.append,
        tracker,
        lambda *_: None,
        lambda: opened.append(True),
        Gtk.SingleSelection.new(Gtk.StringList.new(["Unassigned"])),
    )
    widget.scroll.set_overlay_scrolling(False)
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
        items.append(
            {
                "kind": "task",
                "source_id": "source",
                "uid": f"completed-{i}",
                "title": f"Completed task {i}",
                "due": (tomorrow + timedelta(days=i - 1)).isoformat() if i < 4 else None,
                "completed": True,
                # Local midnight may still be yesterday in the bridge's UTC form.
                "completed_at": datetime.combine(date.today(), datetime.min.time())
                .astimezone()
                .astimezone(UTC)
                .isoformat(),
            }
        )
    widget.agenda.offset = 1
    for uid, timestamp in (
        ("completed-yesterday", datetime.now().astimezone() - timedelta(days=1)),
        ("completed-unknown", None),
    ):
        items.append(
            {
                "kind": "task",
                "source_id": "source",
                "uid": uid,
                "title": uid,
                "due": date.today().isoformat(),
                "completed": True,
                "completed_at": timestamp.isoformat() if timestamp else None,
            }
        )
    items.extend(
        {
            "kind": "task",
            "source_id": "source",
            "uid": f"future-{i}",
            "title": f"Future task {i}",
            "due": (tomorrow + timedelta(days=4 if i == 7 else 1 + i % 3)).isoformat(),
        }
        for i in range(8)
    )
    widget.agenda.set_data(snapshot(items), ["A selected source could not be read."])
    headings = {}
    child = widget.agenda.body.get_first_child()
    while child is not None:
        if isinstance(child, Gtk.Box) and isinstance(child.get_first_child(), Gtk.Label):
            headings[child.get_first_child().get_text()] = child
        child = child.get_next_sibling()
    assert headings["Tasks"].get_last_child().get_text() == "5 due"
    completed = widget.agenda.body.get_last_child()
    assert isinstance(completed, Gtk.Expander)
    assert completed.get_label_widget().get_last_child().get_text() == "5"
    assert not completed.get_expanded()
    assert "Upcoming" not in headings and "Next 4 days" not in headings
    for days in range(1, 5):
        due_day = tomorrow + timedelta(days=days)
        detail = f"{due_day:%a} {due_day.day} {due_day:%b}"
        if due_day.year != date.today().year:
            detail += f" {due_day.year}"
        assert f"{detail} · In {days + 1} days" in headings
    widget.window.present()
    try:
        settle_until(lambda: widget.agenda.body.get_height() > widget.scroll.get_height() > 0)
        surface_size = (widget.window.get_width(), widget.window.get_height())
        assert surface_size[0] == 320
        assert Gtk4LayerShell.get_anchor(widget.window, Gtk4LayerShell.Edge.BOTTOM)
        viewport_height = widget.scroll.get_height()
        focus_height = widget.focus.get_height()
        if surface_size[1] >= 640 + focus_height:
            assert widget.agenda.get_height() + widget.footer.get_height() >= 640
        bottom_margin = Gtk4LayerShell.get_margin(widget.window, Gtk4LayerShell.Edge.BOTTOM)
        for reduction in (120, 0):
            Gtk4LayerShell.set_margin(
                widget.window, Gtk4LayerShell.Edge.BOTTOM, bottom_margin + reduction
            )
            settle_until(
                lambda: (
                    widget.window.get_height() == surface_size[1] - reduction
                    and widget.scroll.get_height() == viewport_height - reduction
                )
            )
            success, bounds = widget.focus.compute_bounds(widget.window)
            assert success and bounds.get_y() + bounds.get_height() <= widget.window.get_height()
        header = widget.agenda.header
        success, header_bounds = header.compute_bounds(widget.window)
        assert success and header_bounds.get_y() >= 0
        assert header.get_last_child().get_text().endswith(" · Tomorrow")
        assert not header.get_last_child().get_layout().is_ellipsized()
        adjustment = widget.scroll.get_vadjustment()
        offset = widget.agenda.offset
        adjustment.set_value(adjustment.get_upper() - adjustment.get_page_size())
        task = completed.get_prev_sibling().get_last_child()
        assert task.get_tooltip_text().startswith("Future task 7\nDue ")
        assert not task.has_css_class("overdue")

        def visible():
            adjustment.set_value(adjustment.get_upper() - adjustment.get_page_size())
            success, bounds = task.compute_bounds(widget.scroll)
            return (
                success
                and bounds.get_y() >= 0
                and bounds.get_y() + bounds.get_height() <= widget.scroll.get_height()
            )

        settle_until(visible)
        assert widget.agenda.offset == offset
        success, scrolled_header = header.compute_bounds(widget.window)
        assert success and scrolled_header.get_y() == header_bounds.get_y()
        assert scrolled_header.get_height() == header_bounds.get_height()
        success, bounds = widget.scroll.get_vscrollbar().compute_bounds(widget.agenda)
        assert success
        widget.clicked(
            None,
            1,
            bounds.get_x() + bounds.get_width() / 2,
            bounds.get_y() + bounds.get_height() / 2,
            lambda: opened.append(True),
        )
        assert opened == []
        task.emit("clicked")
        assert shown[0]["uid"] == "future-7"
        success, bounds = completed.get_label_widget().compute_bounds(widget.agenda)
        assert success
        widget.clicked(None, 1, bounds.get_x() + 2, bounds.get_y() + 2, lambda: opened.append(True))
        assert opened == []
        completed.emit("activate")
        assert completed.get_expanded()
        widget.agenda.set_data(snapshot(items), [])
        completed = widget.agenda.body.get_last_child()
        assert completed.get_expanded()
        # Synced completion/reopening changes the full history regardless of deadline.
        changed = [dict(item) for item in items]
        changed[-1]["completed"] = True
        changed[-1]["completed_at"] = datetime.now().astimezone().isoformat()
        widget.agenda.set_data(snapshot(changed), [])
        completed = widget.agenda.body.get_last_child()
        assert completed.get_expanded()
        assert completed.get_label_widget().get_last_child().get_text() == "6"
        widget.agenda.set_data(snapshot(items), [])
        completed = widget.agenda.body.get_last_child()
        assert completed.get_expanded()
        assert completed.get_label_widget().get_last_child().get_text() == "5"
        adjustment.set_value(adjustment.get_upper() - adjustment.get_page_size())
        task = completed.get_child().get_last_child()
        settle_until(visible)
        task.emit("clicked")
        assert shown[-1]["uid"] == "completed-4"
        header.get_first_child().get_last_child().emit("clicked")
        assert widget.agenda.offset == offset + 1
        assert header.get_last_child().get_text().endswith(" · In 2 days")
        settle_until(lambda: adjustment.get_value() == 0)
        header.get_first_child().get_first_child().get_next_sibling().emit("clicked")
        assert widget.agenda.offset == offset
        success, bounds = widget.footer.compute_bounds(widget.window)
        assert success and bounds.get_y() + bounds.get_height() <= widget.window.get_height()
        success, focus_bounds = widget.focus.compute_bounds(widget.window)
        assert success
        assert focus_bounds.get_y() + focus_bounds.get_height() <= widget.window.get_height()
        assert focus_bounds.get_y() >= bounds.get_y() + bounds.get_height()
        widget.agenda.set_data(snapshot([]), [])
        settle_until(lambda: widget.scroll.get_vadjustment().get_upper() <= widget.HEIGHT)
        empty = []
        child = widget.agenda.body.get_first_child()
        while child is not None:
            if isinstance(child, Gtk.Label) and child.get_visible():
                empty.append(child.get_text())
            child = child.get_next_sibling()
        assert empty == [
            "No events or tasks due.",
            f"No tasks due {tomorrow + timedelta(days=1):%-d %b}–"
            f"{tomorrow + timedelta(days=4):%-d %b}.",
        ]
        assert (widget.window.get_width(), widget.window.get_height()) == surface_size
        widget.footer.get_first_child().emit("clicked")
        widget.footer.get_last_child().emit("clicked")
        assert drafts == ["task", "event"]
        header.get_first_child().get_first_child().get_next_sibling().emit("clicked")
        assert widget.agenda.offset == offset - 1
        assert header.get_last_child().get_text().endswith(" · Today")
        header.get_first_child().get_first_child().get_next_sibling().emit("clicked")
        assert header.get_last_child().get_text().endswith(" · Yesterday")
        header.get_first_child().get_last_child().get_prev_sibling().emit("clicked")
        assert widget.agenda.offset == 0
    finally:
        widget.window.destroy()


def test_panel_is_regular_window_and_agenda_items_remain_reachable(styles, tmp_path):
    app = Gtk.Application(application_id=f"io.github.wusitee.Dayline.Panel{os.getpid()}")
    app.register(None)
    shown = []
    actions = dict.fromkeys(
        (
            "previous",
            "next",
            "today",
            "refresh",
            "sources",
            "save_sources",
            "save_item",
            "cancel_editor",
            "task_reminders",
            "explicit_alarms",
            "compose",
        ),
        lambda *_: None,
    )
    actions["show_item"] = lambda item, _: shown.append(item)
    drafts = []
    actions["compose"] = lambda *draft: drafts.append(draft)
    panel = Panel(app, styles, actions, FocusTracker(tmp_path / "focus.json"))
    panel.popovers = Popovers()
    first = week_start(date.today())
    items = [
        {
            "kind": "task",
            "source_id": "source",
            "uid": f"task-{day}-{i}",
            "title": f"Task {i}",
            "due": (first + timedelta(days=day)).isoformat(),
        }
        for day in range(7)
        for i in range(5)
    ]
    panel.agenda.set_week(snapshot(items), first, False)
    panel.week.set_week(snapshot(items), first, False)
    panel.view_selector.set_selected(1)
    adjustment = panel.agenda.scroll.get_vadjustment()
    try:
        # Allocate directly so compositor tiling does not constrain the resize checks.
        panel.body.allocate(1280, 700, -1, None)
        assert panel.sidebar.get_width() == 320
        calendar_width = panel.views.get_width()
        panel.body.set_position(panel.body.get_position() - 120)
        panel.body.allocate(1280, 700, -1, None)
        assert panel.sidebar.get_width() == 440
        assert panel.views.get_width() == calendar_width - 120
        panel.body.allocate(1480, 700, -1, None)
        assert panel.sidebar.get_width() == 440
        assert panel.views.get_width() == calendar_width + 80
        panel.body.set_position(panel.body.get_position() + 60)
        panel.body.allocate(1480, 700, -1, None)
        assert panel.sidebar.get_width() == 380
        panel.focus_toggle.set_active(True)
        panel.body.allocate(1480, 700, -1, None)
        assert panel.focus.get_width() == 380
        assert panel.sidebar.get_visible_child_name() == "focus"
        assert not panel.add_toggle.get_active() and not panel.tasks_toggle.get_active()
        panel.show_editor()
        assert not panel.focus_toggle.get_sensitive()
        panel.show_focus()
        assert panel.editing()  # Opening Focus must preserve an open editor.
        panel.show_agenda()
        assert panel.sidebar.get_visible_child_name() == "focus"
        panel.focus_toggle.set_active(False)
        panel.tasks.set_data(snapshot(items), True)
        panel.tasks_toggle.set_active(True)
        panel.body.allocate(1480, 700, -1, None)
        assert panel.tasks.get_width() == 380
        panel.editor.load("task", [{"id": "source", "name": "Tasks"}], items[-1], "item")
        panel.show_editor()
        panel.body.allocate(1480, 700, -1, None)
        assert panel.sidebar.get_width() == 380
        panel.show_agenda()
        panel.tasks_toggle.set_active(False)
        panel.body.allocate(1480, 700, -1, None)
        assert panel.sidebar_container.get_width() == 0
        assert panel.views.get_width() > calendar_width + 80
        panel.add_toggle.set_active(True)
        panel.body.allocate(1480, 700, -1, None)
        assert panel.sidebar.get_width() == 380
        panel.show()
        assert not Gtk4LayerShell.is_layer_window(panel.window)
        assert panel.window.get_decorated()
        assert panel.window.get_resizable()
        assert panel.views.get_visible_child_name() == "agenda"
        assert panel.sidebar.get_visible_child_name() == "add"
        assert not panel.compose_button.get_sensitive()
        panel.quick_title.set_text("  Review tomorrow at 9am  ")
        assert panel.compose_button.get_sensitive()
        panel.quick_title.emit("activate")
        panel.compose_kind.set_selected(1)
        panel.compose_button.emit("clicked")
        assert drafts == [
            ("task", "Review tomorrow at 9am"),
            ("event", "Review tomorrow at 9am"),
        ]
        panel.add_toggle.set_active(False)
        assert not panel.sidebar_container.get_visible()
        panel.tasks_toggle.set_active(True)
        assert panel.sidebar_container.get_visible()
        assert panel.sidebar.get_visible_child_name() == "tasks"
        settle_until(lambda: adjustment.get_upper() > adjustment.get_page_size() > 0)
        assert isinstance(panel.window.get_surface(), Gdk.Toplevel)
        adjustment.set_value(adjustment.get_upper() - adjustment.get_page_size())
        last_row = panel.agenda.list.get_last_child().get_last_child().get_last_child()

        def visible():
            success, bounds = last_row.compute_bounds(panel.agenda.scroll)
            return (
                success
                and bounds.get_y() >= 0
                and bounds.get_y() + bounds.get_height() <= panel.agenda.scroll.get_height()
            )

        settle_until(visible)
        last_row.get_last_child().emit("clicked")
        assert shown[0]["uid"] == "task-6-4"
        panel.tasks_toggle.set_active(False)
        panel.editor.load("task", [{"id": "source", "name": "Tasks"}], items[-1], "item")
        panel.show_editor()
        assert panel.editing()
        assert panel.sidebar_container.get_visible()
        assert not panel.tasks_toggle.get_sensitive()
        assert panel.views.get_visible_child_name() == "agenda"
        assert panel.view_selector.get_sensitive()
        assert panel.views.get_visible()
        actions["cancel_editor"] = panel.show_agenda
        field = panel.editor.entries["due"]
        field.calendar_button.popup()
        settle_until(lambda: field.calendar.get_mapped())
        chosen = first + timedelta(days=1)
        field.calendar.select_day(
            GLib.DateTime.new_local(chosen.year, chosen.month, chosen.day, 12, 0, 0)
        )
        assert field.day.get_text() == chosen.isoformat()
        field.time_button.popup()
        times = field.times
        settle_until(lambda: times.get_mapped())
        times.emit("row-activated", times.get_row_at_index(19))
        assert field.clock.get_text() == "09:30"
        panel.key_pressed(None, Gdk.KEY_Escape, 0, 0)
        assert not panel.editing()
        assert not panel.sidebar_container.get_visible()
        panel.show_sources()
        panel.key_pressed(None, Gdk.KEY_Escape, 0, 0)
        assert panel.views.get_visible_child_name() == "agenda"
        panel.window.close()
        assert not panel.visible()
        panel.show()
        assert panel.views.get_visible_child_name() == "agenda"
        panel.view_selector.set_selected(0)
        assert panel.views.get_visible_child_name() == "week"
        # More than four tasks remain accessible through the day overflow.
        more = panel.week.task_columns.get_child_at(0, 4)
        assert more.get_label() == "+1 more"
        assert panel.week.task_columns.get_child_at(0, 0).has_css_class("calendar-task")
        panel.key_pressed(None, Gdk.KEY_Escape, 0, 0)
        assert not panel.visible()
    finally:
        panel.popovers.close()
        panel.window.destroy()


def test_statistics_navigation_periods_and_live_focus_updates(styles, tmp_path, monkeypatch):
    for setting in ("XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME"):
        monkeypatch.setenv(setting, str(tmp_path / setting))
    monkeypatch.setattr("dayline.ui.app.APP_ID", f"io.github.wusitee.Dayline.Stats{os.getpid()}")
    clock = SimpleNamespace(
        wall=datetime.now().replace(hour=12, minute=0, second=0, microsecond=0).timestamp(),
        mono=100.0,
    )
    monkeypatch.setattr("dayline.focus.wall_time", lambda: clock.wall)
    monkeypatch.setattr("dayline.focus.monotonic", lambda: clock.mono)
    app = Application()
    app.register(None)
    app.refresh = lambda: None
    item = {"kind": "task", "source_id": "source", "uid": "essay", "title": "Essay " * 40}
    app.data = snapshot([item])
    app.render()
    app.panel.view_selector.set_selected(1)
    app.panel.focus_toggle.set_active(True)
    app.panel.show()
    page = app.panel.statistics

    def value(section, column):
        heading = page.content.get_first_child()
        if section == "focus":
            heading = heading.get_next_sibling().get_next_sibling()
        return heading.get_next_sibling().get_child_at(column, 0).get_last_child().get_text()

    try:
        app.panel.statistics_button.emit("clicked")
        settle_until(lambda: page.get_mapped())
        assert not app.panel.calendar_navigation.get_visible()
        assert not app.panel.focus_toggle.get_visible()
        assert value("tasks", 0) == "1" and value("focus", 0) == "0m"
        app.focus.start(item)
        clock.wall += 90
        clock.mono += 90
        app.focus_tick()
        assert value("focus", 0) == "1m" and value("focus", 1) == "1"
        assert app.focus.running
        page.period.set_selected(0)
        activity = page.content.get_first_child()
        for _ in range(4):
            activity = activity.get_next_sibling()
        assert activity.get_last_child().get_child_at(0, 1) is not None
        assert activity.get_last_child().get_child_at(0, 2) is None
        completed = {
            **item,
            "completed": True,
            "completed_at": datetime.now().astimezone().isoformat(),
        }
        app.data = snapshot([completed])
        app.render()
        assert value("tasks", 0) == "0" and value("tasks", 3) == "1"
        assert app.panel.stack.get_visible_child_name() == "statistics"
        page.set_data(None)
        assert value("tasks", 0) == "—" and value("focus", 0) == "1m"
        app.render()
        page.period.set_selected(2)
        adjustment = page.scroll.get_vadjustment()
        settle_until(lambda: adjustment.get_upper() > adjustment.get_page_size() > 0)
        adjustment.set_value(adjustment.get_upper() - adjustment.get_page_size())
        footer = page.content.get_last_child()

        def footer_visible():
            success, bounds = footer.compute_bounds(page.scroll)
            return success and 0 <= bounds.get_y() < page.scroll.get_height()

        settle_until(footer_visible)
        app.panel.key_pressed(None, Gdk.KEY_Escape, 0, 0)
        assert app.panel.stack.get_visible_child_name() == "agenda"
        assert app.panel.views.get_visible_child_name() == "agenda"
        assert app.panel.focus_toggle.get_active() and app.panel.focus_toggle.get_visible()
        app.panel.show_editor()
        assert not app.panel.statistics_button.get_sensitive()
        app.panel.show_statistics()
        assert app.panel.editing()
    finally:
        app.stop()
        for window in app.get_windows():
            window.destroy()


def test_focus_timer_keeps_active_task_through_refresh_hiding_and_restart(
    styles, tmp_path, monkeypatch
):
    clock = SimpleNamespace(wall=datetime.now().timestamp(), mono=100.0)
    monkeypatch.setattr("dayline.focus.wall_time", lambda: clock.wall)
    monkeypatch.setattr("dayline.focus.monotonic", lambda: clock.mono)
    tracker = FocusTracker(tmp_path / "focus.json")
    page = FocusPage(tracker)
    item = {"kind": "task", "source_id": "tasks", "uid": "essay", "title": "Essay " * 40}
    page.set_tasks(snapshot([item]))
    page.selection.set_selected(1)
    page.set_tasks(snapshot([item]))
    assert page.selection.get_selected() == 1
    # Long task titles must not force the compact sidebar wider.
    assert page.measure(Gtk.Orientation.HORIZONTAL, -1)[0] == 320
    page.start_button.emit("clicked")
    assert tracker.current["key"] == task_key(item)
    assert page.start_button.get_label() == "Pause" and page.task.get_sensitive()
    clock.wall += 61
    clock.mono += 61
    page.tick()  # An unmapped sidebar still tracks and checkpoints time.
    page.set_tasks(snapshot([{**item, "completed": True}]))
    assert page.selection.get_selected() == 1
    restored = FocusPage(FocusTracker(tracker.path))
    assert restored.start_button.get_label() == "Resume"
    assert restored.selection.get_selected() == 1 and restored.task.get_sensitive()
    assert restored.total.get_text() == "1m"
    page.start_button.emit("clicked")
    clock.wall += 120
    clock.mono += 120
    page.start_button.emit("clicked")
    clock.wall += 30
    clock.mono += 30
    page.finish_button.emit("clicked")
    assert tracker.sessions[0]["days"][date.today().isoformat()] == 91
    assert page.start_button.get_label() == "Start focus"
    assert page.task.get_sensitive() and page.selection.get_selected() == 0
    assert not page.finish_button.get_visible()
    assert page.expander.get_label() == "Today’s sessions · 1"
    page.start_button.emit("clicked")
    assert tracker.current["key"] is None
    page.finish_button.emit("clicked")
    assert len(tracker.sessions) == 1  # Discard sessions with no recorded time.


def test_widget_focus_actions_share_sidebar_state(styles, tmp_path, monkeypatch):
    clock = SimpleNamespace(wall=datetime.now().timestamp(), mono=100.0)
    monkeypatch.setattr("dayline.focus.wall_time", lambda: clock.wall)
    monkeypatch.setattr("dayline.focus.monotonic", lambda: clock.mono)
    app = Application()
    app.focus = FocusTracker(tmp_path / "focus.json")
    page = FocusPage(app.focus)
    compact = FocusClock(app.focus, app.focus_action, lambda: None, page.selection)
    app.panel = SimpleNamespace(focus=page, statistics=SimpleNamespace(update=lambda: None))
    app.widget = SimpleNamespace(set_focus=compact.update)
    essay = {"kind": "task", "source_id": "tasks", "uid": "essay", "title": "Essay"}
    review = {**essay, "uid": "review", "title": "Review"}
    page.set_tasks(snapshot([essay, review]))
    page.selection.set_selected(1)
    try:
        compact.start_button.emit("clicked")
        assert page.start_button.get_label() == "Pause"
        assert compact.task.get_sensitive() and page.task.get_sensitive()
        assert "moves this session's recorded time" in compact.task.get_tooltip_text()
        clock.wall += 90
        clock.mono += 90
        app.focus_tick()
        assert compact.clock.get_text() == "01:30"
        row = compact.task.results.get_row_at_index(2)
        compact.task.selected(compact.task.results, row)
        app.focus_tick()
        assert app.focus.current["key"] == task_key(review) and app.focus.running
        assert compact.clock.get_text() == "01:30"
        assert page.task.title.get_text() == compact.task.title.get_text() == "Review"
        page.set_tasks(snapshot([essay, review]))
        assert app.focus.current["key"] == task_key(review) and app.focus.elapsed == 90
        restored = FocusTracker(app.focus.path)
        restored.load()
        assert restored.current["key"] == task_key(review) and restored.elapsed == 90
        clock.wall += 30
        clock.mono += 30
        page.start_button.emit("clicked")
        app.focus_tick()
        assert compact.start_button.get_label() == "Resume"
        page.selection.set_selected(0)
        app.focus_tick()
        assert app.focus.current["key"] is None and not app.focus.running
        assert app.focus.elapsed == 120 and len(app.focus.sessions) == 1
        assert app.focus.groups(date.today()) == [
            {"key": None, "title": "Unassigned", "seconds": 120}
        ]
        compact.start_button.emit("clicked")
        assert app.focus.current["key"] is None and app.focus.running
        assert app.focus.elapsed == 120
        compact.finish_button.emit("clicked")
        assert page.start_button.get_label() == "Start focus"
        assert compact.start_button.get_label() == "Start"
        assert compact.ring.total.get_text() == "2m"
    finally:
        app.executor.shutdown(wait=False, cancel_futures=True)


def test_focus_history_error_disables_recording(styles, tmp_path):
    path = tmp_path / "focus.json"
    path.write_text("invalid")
    page = FocusPage(FocusTracker(path))
    assert page.notice.get_visible() and "Cannot read focus history" in page.notice.get_text()
    assert not page.start_button.get_sensitive() and not page.task.get_sensitive()
    assert path.read_text() == "invalid"


def test_focus_time_rows_edit_groups_and_individual_sessions_compactly(
    styles, tmp_path, monkeypatch
):
    clock = SimpleNamespace(wall=datetime.now().timestamp(), mono=100.0)
    monkeypatch.setattr("dayline.focus.wall_time", lambda: clock.wall)
    monkeypatch.setattr("dayline.focus.monotonic", lambda: clock.mono)
    tracker = FocusTracker(tmp_path / "focus.json")
    page = FocusPage(tracker)
    essay = {"kind": "task", "source_id": "tasks", "uid": "essay", "title": "Essay " * 40}
    correct = {**essay, "uid": "correct", "title": "Correct task", "completed": True}
    other = {**essay, "uid": "other", "title": "Other task"}
    page.set_tasks(snapshot([essay, correct, other]))
    for seconds in (10, 20):
        tracker.start(essay)
        clock.wall += seconds
        clock.mono += seconds
        tracker.finish()
    tracker.start(other)
    clock.wall += 10
    clock.mono += 10
    tracker.tick()
    page.set_tasks(page.data)
    page.update()
    page.expander.set_expanded(True)
    window = Gtk.Window(child=page, default_width=320, default_height=700)
    window.add_css_class("dayline")
    window.add_css_class("main-window")
    window.present()

    def choose(row, title):
        row.emit("clicked")
        dialog = next(
            dialog for dialog in Gtk.Window.get_toplevels() if dialog.get_transient_for() is window
        )
        settle_until(lambda: dialog.is_active())
        content = dialog.get_child()
        picker = content.get_first_child().get_next_sibling().get_next_sibling()
        picker.popup()
        settle_until(lambda: picker.get_popover().get_mapped())
        picker.search.set_text(title)
        picker.search.emit("activate")
        return dialog, content.get_last_child().get_last_child()

    try:
        settle_until(lambda: page.history.get_first_child().get_height() > 0)
        group = page.breakdown.get_first_child()
        session = page.history.get_first_child()
        assert group.get_height() <= 32 and session.get_height() <= 32
        assert not group.get_child().get_first_child().get_next_sibling().get_wrap()
        assert "Running" in session.get_tooltip_text()
        dialog, save = choose(group, "Correct task")
        assert (
            "All 2 sessions" in dialog.get_child().get_first_child().get_next_sibling().get_text()
        )
        dialog.get_child().get_last_child().get_first_child().emit("clicked")
        assert tracker.sessions[0]["key"] == task_key(essay)
        dialog, save = choose(page.breakdown.get_first_child(), "Correct task")
        with monkeypatch.context() as patch:
            patch.setattr("dayline.focus.write_json", lambda *_: (_ for _ in ()).throw(OSError()))
            save.emit("clicked")
        assert dialog.get_visible()
        notice = dialog.get_child().get_last_child().get_prev_sibling()
        assert notice.get_visible() and "Cannot save focus history" in notice.get_text()
        save.emit("clicked")
        assert not dialog.get_visible()
        assert [session["key"] for session in tracker.sessions[:2]] == [task_key(correct)] * 2
        assert tracker.running and tracker.current["key"] == task_key(other)
        assert tracker.elapsed == 10
        session = page.history.get_first_child().get_next_sibling()
        dialog, save = choose(session, "Other task")
        save.emit("clicked")
        assert tracker.sessions[0]["key"] == task_key(correct)
        assert tracker.sessions[1]["key"] == task_key(other)
        # Titles refresh even when both task totals still round to 0m.
        session = page.history.get_first_child().get_next_sibling()
        assert session.get_child().get_first_child().get_next_sibling().get_text() == "Other task"
        restored = FocusTracker(tracker.path)
        restored.load()
        assert restored.sessions == tracker.sessions
        assert len(tracker.sessions) == 3 and tracker.running
    finally:
        window.destroy()


def test_widget_focus_search_and_task_popup_start_the_selected_task(styles, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setattr("dayline.ui.app.APP_ID", f"io.github.wusitee.Dayline.Search{os.getpid()}")
    clock = SimpleNamespace(wall=datetime.now().timestamp(), mono=100.0)
    monkeypatch.setattr("dayline.focus.wall_time", lambda: clock.wall)
    monkeypatch.setattr("dayline.focus.monotonic", lambda: clock.mono)
    app = Application()
    app.register(None)
    app.refresh = lambda: None
    quiz = {
        "kind": "task",
        "source_id": "moodle",
        "uid": "quiz",
        "title": "COMP2113 Asgn 1 AI Quiz",
        "due": date.today().isoformat(),
    }
    tutorial = {**quiz, "uid": "tutorial", "title": "MATH1013 Tutorial 4"}
    duplicate = {**quiz, "source_id": "personal"}
    app.data = snapshot([quiz, tutorial, duplicate])
    app.data["sources"] = [
        {"id": "moodle", "name": "Moodle", "read_only": True, "disabled": False},
        {"id": "personal", "name": "Personal", "read_only": True, "disabled": False},
    ]
    app.render()
    app.widget.window.present()
    page = app.panel.focus
    picker = app.widget.focus.task

    def matches():
        names = []
        row = picker.results.get_first_child()
        while row is not None:
            if row.get_child_visible():
                names.append(row.get_child().get_text())
            row = row.get_next_sibling()
        return names

    try:
        settle_until(lambda: picker.get_mapped())
        picker.popup()
        settle_until(lambda: picker.popover.get_mapped())
        assert app.widget.window.get_focus() is not None
        for query in ("q", "qu", "QUIZ comp-2113"):
            picker.search.set_text(query)
            assert matches() == [quiz["title"] + " · Moodle", quiz["title"] + " · Personal"]
            assert page.selection.get_selected() == 0  # Typing never changes the association.
        picker.search.set_text("MOODLE quiz 2113")
        assert matches() == [quiz["title"] + " · Moodle"]
        page.set_tasks(app.data)
        assert picker.search.get_text() == "MOODLE quiz 2113" and len(matches()) == 1
        picker.search.emit("activate")
        assert task_key(page.choices[page.selection.get_selected()]) == task_key(quiz)
        assert page.task.title.get_text() == picker.title.get_text()
        app.widget.focus.start_button.emit("clicked")
        assert app.focus.current["key"] == task_key(quiz)
        assert picker.get_sensitive() and page.task.get_sensitive()
        clock.wall += 65
        clock.mono += 65
        app.focus_task(quiz)
        assert app.focus.elapsed == 65 and len(app.focus.sessions) == 1
        anchor = app.widget.agenda.header
        app.show_item(quiz, anchor)
        details = app.popovers.current.get_child().get_child().get_child()
        focus_button = details.get_last_child().get_last_child()
        assert focus_button.get_label() == "Focusing" and not focus_button.get_sensitive()
        app.focus_action("toggle")
        assert focus_button.get_label() == "Focus" and focus_button.get_sensitive()
        assert not app.focus.running and app.focus.elapsed == 65
        focus_button.emit("clicked")
        assert app.focus.running
        assert app.focus.elapsed == 65 and len(app.focus.sessions) == 1
        app.show_item(tutorial, anchor)
        details = app.popovers.current.get_child().get_child().get_child()
        assert (
            details.get_last_child().get_last_child().get_tooltip_text()
            == "Switch focus to this task"
        )
        with monkeypatch.context() as patch:
            patch.setattr("dayline.focus.write_json", lambda *_: (_ for _ in ()).throw(OSError()))
            details.get_last_child().get_last_child().emit("clicked")
        assert app.focus.current is None and not app.focus.running
        assert page.notice.get_visible() and "Cannot save focus history" in page.notice.get_text()
        app.show_item(tutorial, anchor)
        details = app.popovers.current.get_child().get_child().get_child()
        details.get_last_child().get_last_child().emit("clicked")
        assert app.popovers.current is None
        assert app.focus.current["key"] == task_key(tutorial) and app.focus.running
        assert app.focus.sessions[0]["days"][date.today().isoformat()] == 65
        app.widget.focus.finish_button.emit("clicked")
        assert picker.get_sensitive()
        picker.popup()
        settle_until(lambda: picker.popover.get_mapped())
        picker.search.set_text("no such task")
        assert not matches() and picker.empty.get_visible()
        selected = page.selection.get_selected()
        picker.search.emit("activate")
        assert page.selection.get_selected() == selected
        picker.search.set_text("")
        assert len(matches()) == 4
    finally:
        picker.popover.popdown()
        app.popovers.close()
        app.executor.shutdown(wait=False, cancel_futures=True)
        app.panel.window.destroy()
        app.widget.window.destroy()


def test_widget_escape_closes_popups_then_hides_without_stopping_focus(
    styles, tmp_path, monkeypatch
):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setattr("dayline.ui.app.APP_ID", f"io.github.wusitee.Dayline.Escape{os.getpid()}")
    app = Application()
    app.register(None)
    app.refresh = lambda: None
    item = {"kind": "task", "source_id": "tasks", "uid": "essay", "title": "Essay"}
    app.data = snapshot([item])
    app.render()
    widget = app.widget
    picker = widget.focus.task
    controllers = widget.window.observe_controllers()
    keys = next(
        controller for controller in controllers if isinstance(controller, Gtk.EventControllerKey)
    )
    try:
        widget.window.present()
        settle_until(lambda: picker.get_mapped())
        assert not keys.emit("key-pressed", Gdk.KEY_a, 0, 0)
        assert widget.window.get_visible()
        picker.popup()
        settle_until(lambda: picker.popover.get_mapped())
        picker.search.set_text("essay")
        assert keys.emit("key-pressed", Gdk.KEY_Escape, 0, 0)
        settle_until(lambda: not picker.popover.get_mapped())
        assert widget.window.get_visible()
        app.focus_task(item)
        app.show_item(item, widget.agenda.header)
        settle_until(lambda: app.popovers.current.get_mapped())
        assert keys.emit("key-pressed", Gdk.KEY_Escape, 0, 0)
        assert app.popovers.current is None and widget.window.get_visible()
        assert keys.emit("key-pressed", Gdk.KEY_Escape, 0, 0)
        assert not widget.window.get_visible()
        assert app.focus.running and app.focus.current["key"] == task_key(item)
    finally:
        picker.popover.popdown()
        app.popovers.close()
        app.executor.shutdown(wait=False, cancel_futures=True)
        app.panel.window.destroy()
        widget.window.destroy()


def test_week_keeps_tasks_above_events_and_outside_event_coverage(styles):
    app = Gtk.Application(application_id=f"io.github.wusitee.Dayline.Week{os.getpid()}")
    app.register(None)
    app.popovers = Popovers()
    window = Gtk.ApplicationWindow(application=app, default_width=900, default_height=600)
    shown = []
    week = WeekView(lambda item, _: shown.append(item["uid"]), styles)
    window.set_child(week)
    first = week_start(date.today())
    items = [
        {
            "kind": "task",
            "uid": f"task-{i}",
            "source_id": "source",
            "title": f"Task {i}",
            "due": first.isoformat(),
        }
        for i in range(5)
    ]
    clock = datetime.combine(first + timedelta(days=1), datetime.min.time()).astimezone()
    items.append(
        {**items[0], "uid": "timed", "due": (clock + timedelta(hours=17, minutes=30)).isoformat()}
    )
    items.extend(
        [
            {**items[0], "uid": "completed", "completed": True},
            {**items[0], "uid": "cancelled", "cancelled": True},
            {**items[0], "uid": "undated", "due": None},
            {
                "kind": "event",
                "uid": "event",
                "source_id": "source",
                "title": "Class",
                "start": clock.isoformat(),
                "end": (clock + timedelta(hours=1)).isoformat(),
            },
        ]
    )
    data = snapshot(items)
    week.set_week(data, first, False)
    window.present()
    try:
        assert [segment.item["kind"] for _, segment in week.grid.blocks] == ["event"]
        assert "17:30" in week.task_columns.get_child_at(1, 0).get_child().get_text()
        assert isinstance(week.task_columns.get_child_at(6, 0), Gtk.Box)
        more = week.task_columns.get_child_at(0, 4)
        assert more.get_label() == "+2 more"
        settle_until(lambda: more.get_mapped())
        more.emit("clicked")
        content = app.popovers.current.get_child().get_child().get_child()
        completed = content.get_last_child()
        assert completed.get_child().get_text().startswith("☑ ")
        assert completed.get_child().get_attributes() is not None
        assert "Completed" in completed.get_tooltip_text()
        completed.emit("clicked")
        content.get_last_child().get_prev_sibling().emit("clicked")
        assert shown == ["completed", "task-4"]
        app.popovers.close()
        week.set_week({**data, "ranges": []}, first, False)
        assert week.missing.get_visible()
        assert not week.grid.blocks
        assert week.task_columns.get_child_at(0, 4).get_label() == "+2 more"
        # A completion refreshed from Thunderbird stays visible on the due date.
        week.set_week(snapshot([{**items[5], "completed": True}]), first, False)
        completed = week.task_columns.get_child_at(1, 0)
        assert completed.get_child().get_text().startswith("☑ 17:30")
        completed.emit("clicked")
        assert shown[-1] == "timed"
        week.set_week(snapshot([items[5]]), first, False)
        assert week.task_columns.get_child_at(1, 0).get_child().get_text().startswith("☐ 17:30")
    finally:
        app.popovers.close()
        window.destroy()


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


@pytest.mark.parametrize("kind", ["task", "event"])
def test_reminders_retry_failed_delivery_and_open_the_current_item(
    styles, tmp_path, kind, monkeypatch
):
    app = Application()
    item = {
        "kind": kind,
        "source_id": "source",
        "uid": "task",
        "title": "Task",
        "due": (datetime.now().astimezone() + timedelta(minutes=1)).isoformat(),
        "start": datetime.now().astimezone().isoformat(),
        "end": (datetime.now().astimezone() + timedelta(hours=1)).isoformat(),
        "alarms": [datetime.now().astimezone().isoformat()] if kind == "event" else [],
    }
    app.data = snapshot([item])
    app.config.task_reminders = True
    app.config.explicit_alarms = True
    app.config.sources = {"source": {"role": "personal", "events": True, "tasks": True}}
    app.reminders = Reminders(tmp_path / "reminders.json")
    deliveries = []
    app.notifications = SimpleNamespace(send=lambda *args: deliveries.append(args))
    app.render_status = lambda: None
    shown = []
    app.show_item = lambda current, _anchor: shown.append(current)
    app.go_to = lambda *_: pytest.fail("Opening details must not refresh and close the popover")
    app.panel = SimpleNamespace(
        show_agenda=lambda: None,
        show=lambda: None,
        view_selector=Gtk.DropDown.new_from_strings(["Week", "Agenda"]),
    )
    try:
        app.loading = True
        app.check_reminders()
        assert deliveries == []  # Wait for the fresh snapshot after a save.
        app.loading = False
        app.check_reminders()
        app.check_reminders()
        assert len(deliveries) == 1  # An in-flight notification is not submitted twice.
        deliveries[0][1]("Service unavailable")
        assert "Service unavailable" in app.reminder_error
        app.check_reminders()
        assert len(deliveries) == 2
        deliveries[1][1](None)
        app.check_reminders()
        assert len(deliveries) == 2
        assert app.reminder_error is None
        app.config.sources = {}
        app.reminders = Reminders(tmp_path / "unselected.json")
        app.check_reminders()
        assert len(deliveries) == 2
        app.open_reminder(item)
        assert shown == []
        app.config.sources = {"source": {"role": "personal", "events": True, "tasks": True}}
        app.data["items"] = [{**item, "title": "Edited after notification"}]
        app.open_reminder(item)
        assert shown[0]["title"] == "Edited after notification"
        assert app.panel.view_selector.get_selected() == 1
        app.data["items"][0]["completed"] = True
        app.open_reminder(item)
        assert len(shown) == 1
        app.data["items"] = []

        def fetched(config, target, scope):
            assert config.sources == app.config.sources
            assert target is item and scope == "item"
            return {**item, "title": "Fetched"}

        monkeypatch.setattr("dayline.ui.app.read_item", fetched)
        app.background = lambda operation, completed: completed(operation(), None)
        app.open_reminder(item)
        assert shown[-1]["title"] == "Fetched"
        app.background = lambda operation, completed: completed(None, "Item no longer exists")
        app.open_reminder(item)
        assert "Item no longer exists" in app.reminder_error
    finally:
        app.executor.shutdown(wait=False, cancel_futures=True)


def test_resume_refreshes_before_checking_reminders(styles):
    app = Application()
    calls = []
    app.widget = SimpleNamespace(agenda=SimpleNamespace(set_data=lambda *_: None))
    app.panel = SimpleNamespace(
        tasks=SimpleNamespace(set_data=lambda *_: None),
        week=SimpleNamespace(grid=SimpleNamespace(queue_draw=lambda: None)),
    )

    def refresh():
        app.loading = True
        calls.append("refresh")

    app.refresh = refresh
    app.check_reminders = lambda: calls.append(("reminders", app.loading))
    app.last_tick -= 180
    try:
        app.tick()
        assert calls == ["refresh", ("reminders", True)]
    finally:
        app.executor.shutdown(wait=False, cancel_futures=True)


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
    # A date-only task deadline includes the whole due day, unlike a timed deadline.
    start = datetime(2026, 10, 5, 9).astimezone()
    task = {**item, "kind": "task", "start": start.isoformat()}
    for deadline, valid in (
        ("2026-10-05", True),
        ("2026-10-04", False),
        (start.isoformat(), True),
        ((start - timedelta(hours=1)).isoformat(), False),
    ):
        editor.load("task", [source], {**task, "due": deadline}, "item")
        editor.entries["title"].set_text("Renamed")
        count = len(saved)
        editor.save()
        if valid:
            assert len(saved) == count + 1
            assert saved[-1][2] == {"title": "Renamed"}
        else:
            assert len(saved) == count
            assert "cannot precede Start" in editor.error.get_text()
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


def test_agenda_keeps_later_and_undated_tasks_when_calendar_range_is_unavailable(styles):
    shown = []
    agenda = AgendaView(lambda item, _: shown.append(item["uid"]), styles)
    first = week_start(date.today())
    later = first + timedelta(days=50)
    data = snapshot(
        [
            {
                "kind": "task",
                "source_id": "s",
                "uid": "late",
                "title": "Later task",
                "due": later.isoformat(),
            },
            {"kind": "task", "source_id": "s", "uid": "undated", "title": "No deadline"},
        ]
    )
    agenda.set_week(data, first + timedelta(days=28), False)
    assert agenda.missing.get_visible()
    dated = agenda.list.get_first_child().get_last_child()
    assert "not loaded" in dated.get_first_child().get_text()
    dated.get_last_child().get_last_child().emit("clicked")
    undated = agenda.list.get_last_child()
    assert undated.get_first_child().get_text() == "No due date"
    undated.get_last_child().get_last_child().emit("clicked")
    assert shown == ["late", "undated"]


def test_editor_duration_suggestions_and_overnight_times_produce_explicit_patches(styles):
    from dayline.agenda import local_datetime
    from dayline.ui.editor import EditorPage

    saved = []
    editor = EditorPage(lambda *args: saved.append(args), lambda: None)
    source = {"id": "source", "name": "Test calendar"}
    start = datetime(2026, 10, 6, 23, 59, 45).astimezone()
    item = {
        "kind": "event",
        "source_id": "source",
        "uid": "uid",
        "title": "Meeting",
        "start": start.isoformat(),
        "end": (start + timedelta(hours=1)).isoformat(),
        "description": "Due 10 Oct 23:59\nhttps://example.test/2026-10-09/15:30",
        "alarms": ["2026-10-05T02:30:45Z", "2026-10-05T02:45:00Z"],
    }
    editor.load("event", [source], item, "item")
    editor.duration.set_text("1h 30m")
    editor.save()
    assert local_datetime(saved[-1][2]["end"]) == start + timedelta(minutes=90)
    assert set(saved[-1][2]) == {"end"}  # Unchanged seconds, notes, and multiple alarms survive.
    editor.load("event", [source], item, "item")
    editor.suggestions.get_first_child().emit("clicked")
    assert editor.entries["start"].day.get_text() == "2026-10-10"
    assert editor.notes_text() == item["description"]
    assert editor.entries["title"].get_text() == "Meeting"
    editor.save()
    assert set(saved[-1][2]) == {"start", "end"}
    editor.quick.set_text("2026-10-12 at 9am")
    assert editor.quick_apply.get_sensitive()
    editor.apply_quick()
    assert editor.entries["start"].clock.get_text() == "09:00"
    assert editor.entries["end"].clock.get_text() == "10:00"
    editor.all_day.set_active(True)
    editor.save()
    assert saved[-1][2]["start"] == "2026-10-12"
    assert saved[-1][2]["end"] == "2026-10-13"
    editor.duration.set_text("30m")
    previous = len(saved)
    editor.save()
    assert len(saved) == previous
    assert "whole days" in editor.error.get_text()
    editor.load("event", [source], {**item, "end": start.replace(second=45).isoformat()}, "item")
    editor.entries["end"].clock.set_text("00:30")
    assert editor.entries["end"].day.get_text() == "2026-10-07"
    editor.entries["start"].day.set_text("tomorrow")
    assert not editor.entries["start"].preview.has_css_class("warning")
    editor.stop_detection()


@pytest.mark.parametrize("outcome", ["accepted", "rejected", "selection_changed"])
def test_widget_completion_updates_on_save_before_refresh(styles, monkeypatch, tmp_path, outcome):
    monkeypatch.setattr(
        "dayline.ui.app.APP_ID", f"io.github.wusitee.Dayline.Completion{outcome}{os.getpid()}"
    )
    for setting in ("XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME"):
        monkeypatch.setenv(setting, str(tmp_path / setting))
    app = Application()
    app.register(None)
    callbacks, refreshes = [], []
    app.background = lambda operation, done, **kwargs: callbacks.append(done)
    app.refresh = lambda: refreshes.append(True)
    app.reload_config = lambda: True
    options = {"role": "personal", "events": False, "tasks": True}
    app.config = Config({"source": dict(options), "other": dict(options)})
    item = {
        "kind": "task",
        "source_id": "source",
        "uid": "task",
        "revision": "original",
        "title": "Task to complete",
        "due": date.today().isoformat(),
        "alarms": [],
    }
    other = {**item, "source_id": "other", "title": "Same UID in another list"}
    app.data = snapshot([item, other])
    app.data["sources"] = [
        {"id": source, "name": source, "read_only": False, "disabled": False}
        for source in app.config.sources
    ]
    app.widget.agenda.completed_expanded = True
    app.render()
    app.widget.window.present()
    try:
        settle_until(lambda: app.widget.agenda.get_mapped())
        app.show_item(item, app.widget.agenda.header)
        details = app.popovers.current.get_child().get_child().get_child()
        complete = details.get_last_child().get_first_child().get_next_sibling()
        assert complete.get_label() == "Complete task"
        complete.emit("clicked")
        assert app.writing
        assert not any(task.get("completed") for task in app.data["items"])
        saved = {
            **item,
            "completed": True,
            "completed_at": datetime.now().astimezone().isoformat(),
            "revision": "completed",
        }
        if outcome == "selection_changed":
            app.config = Config({"other": dict(options)})
            app.data = snapshot([other])
            app.render()
        callbacks.pop()(
            None if outcome == "rejected" else {"state": "local", "item": saved},
            "Provider rejected completion" if outcome == "rejected" else None,
        )
        assert not app.writing
        if outcome != "accepted":
            assert not any(task.get("completed") for task in app.data["items"])
            if outcome == "selection_changed":
                assert app.data["items"] == [other]
            return
        # The full refresh has only been requested; its result is still unavailable.
        assert refreshes == [True]
        assert app.data["items"] == [other, saved]
        section = app.widget.agenda.body.get_last_child()
        assert isinstance(section, Gtk.Expander)
        assert section.get_expanded()
        assert section.get_label_widget().get_last_child().get_text() == "1"
        assert section.get_child().get_first_child().get_tooltip_text().startswith(item["title"])
        app.refreshed(None, "Full refresh failed")
        assert app.data["items"] == [other, saved]
        assert "Full refresh failed" in app.widget.agenda.notice.get_text()
        app.save_item("update", saved, {"completed": False}, "item")
        reopened = {**saved, "completed": False, "completed_at": None, "revision": "reopened"}
        callbacks.pop()({"state": "local", "item": reopened}, None)
        assert app.data["items"] == [other, reopened]
        assert not isinstance(app.widget.agenda.body.get_last_child(), Gtk.Expander)
    finally:
        app.stop()
        for window in app.get_windows():
            window.destroy()


def test_widget_task_popup_keeps_edits_through_refresh_pickers_and_failed_save(styles, monkeypatch):
    monkeypatch.setattr("dayline.ui.app.APP_ID", f"io.github.wusitee.Dayline.Popup{os.getpid()}")
    app = Application()
    app.register(None)
    callbacks = []
    app.refresh = lambda: None
    app.reload_config = lambda: True
    app.background = lambda operation, done, **kwargs: callbacks.append(done)
    app.config = Config({"source": {"role": "personal", "events": True, "tasks": True}})
    item = {
        "kind": "task",
        "source_id": "source",
        "uid": "task",
        "revision": "original",
        "title": "Task to edit",
        "due": date.today().isoformat(),
        "description": "Keep notes",
        "alarms": [],
    }
    app.data = snapshot([item])
    app.data["sources"] = [{"id": "source", "name": "Tasks", "read_only": False, "disabled": False}]
    app.render()
    app.widget.window.present()
    try:
        settle_until(lambda: app.widget.agenda.get_mapped())
        anchor = app.widget.agenda.get_first_child()
        app.show_item(item, anchor)
        assert app.editor_popup is None
        assert not callbacks
        details = app.popovers.current.get_child().get_child().get_child()
        assert details.get_first_child().get_text() == item["title"]
        details.get_last_child().get_first_child().emit("clicked")
        popup = app.editor_popup
        settle_until(lambda: popup.get_mapped())
        assert not popup.get_resizable()
        assert not app.panel.visible()
        assert (
            Gtk4LayerShell.get_keyboard_mode(app.widget.window)
            == Gtk4LayerShell.KeyboardMode.ON_DEMAND
        )
        callbacks.pop()(dict(item), None)
        editor = app.editor
        assert editor.entries["title"].get_text() == item["title"]
        settle_until(lambda: popup.get_focus() is not None)
        editor.entries["title"].set_text("Edited in popup")
        app.render()
        assert app.editor_popup is popup
        assert popup.get_mapped()
        assert editor.entries["title"].get_text() == "Edited in popup"
        field = editor.entries["due"]
        settle_until(lambda: field.time_button.get_mapped())
        field.time_button.popup()
        nested = field.time_button.get_popover()
        settle_until(lambda: nested.get_mapped() and field.times.get_width() > 0)
        for index in range(48):
            choice = field.times.get_row_at_index(index).get_child()
            assert not choice.get_layout().is_ellipsized()
            assert choice.get_width() >= choice.get_layout().get_pixel_size()[0]
        field.times.emit("row-activated", field.times.get_row_at_index(19))
        assert field.clock.get_text() == "09:30"
        editor.save()
        assert app.writing
        popup.close()
        assert app.editor_popup is popup
        callbacks.pop()(None, "Revision changed; reopen the task")
        assert not app.writing
        assert app.editor_popup is popup
        assert "Revision changed" in editor.error.get_text()
        assert editor.entries["title"].get_text() == "Edited in popup"
        editor.save()
        callbacks.pop()({"state": "local"}, None)
        assert app.write_status is None
        settle_until(lambda: app.editor_popup is None)
        assert not app.panel.visible()
        assert (
            Gtk4LayerShell.get_keyboard_mode(app.widget.window)
            == Gtk4LayerShell.KeyboardMode.ON_DEMAND
        )
        # A dismissed read cannot populate the next popup.
        anchor = app.widget.agenda.get_first_child()
        app.edit_item(item, "item", anchor)
        stale = callbacks.pop()
        app.cancel_editor()
        app.edit_item(item, "item", anchor)
        stale({**item, "title": "Stale read"}, None)
        callbacks.pop()(dict(item), None)
        assert app.editor.entries["title"].get_text() == item["title"]
        app.cancel_editor()
        # Week tasks use the same dialog while leaving the calendar visible.
        app.panel.show()
        day = (date.today() - app.week).days
        anchor = app.panel.week.task_columns.get_child_at(day, 0)
        settle_until(lambda: anchor.get_mapped() and anchor.get_width() > 0)
        app.show_item(item, anchor)
        assert app.editor_popup is None
        details = app.popovers.current.get_child().get_child().get_child()
        details.get_last_child().get_first_child().emit("clicked")
        callbacks.pop()(item, None)
        assert app.editor_popup is not None
        assert app.panel.visible()
        app.cancel_editor()
        # The preferred Agenda side editor is retained.
        app.panel.view_selector.set_selected(1)
        app.panel.show()
        app.show_item(item, app.panel.view_selector)
        callbacks.pop()(dict(item), None)
        assert app.editor_popup is None
        assert app.panel.editing()
        app.cancel_editor()
        app.panel.hide()
        # Both widget creation actions use a popup and preserve the main draft.
        app.panel.quick_title.set_text("Keep this draft")
        for button, kind in (
            (app.widget.footer.get_first_child(), "task"),
            (app.widget.footer.get_last_child(), "event"),
        ):
            button.emit("clicked")
            editor = app.editor
            assert app.editor_popup is not None
            assert editor.creating
            assert editor.item["kind"] == kind
            assert not app.panel.visible()
            editor.entries["title"].set_text(f"New {kind}")
            editor.save()
            assert app.writing
            callbacks.pop()({"state": "local"}, None)
            assert app.write_status is None
            assert app.editor_popup is None
            assert app.panel.quick_title.get_text() == "Keep this draft"
            assert not app.panel.visible()
    finally:
        app.stop()
        for window in app.get_windows():
            window.destroy()
