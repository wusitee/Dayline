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
from gi.repository import Gdk, GLib, Gtk, Gtk4LayerShell

from dayline.agenda import week_start
from dayline.config import Config
from dayline.reminders import TaskReminders
from dayline.ui.agenda import AgendaView
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


def test_busy_widget_keeps_fixed_surface_and_last_task_reachable(styles):
    app = Gtk.Application(application_id=f"io.github.wusitee.Dayline.Test{os.getpid()}")
    app.register(None)
    shown = []
    drafts = []
    widget = DesktopWidget(
        app, styles, lambda: None, lambda item, _: shown.append(item), drafts.append
    )
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
                "due": tomorrow.isoformat(),
                "completed": True,
            }
        )
    widget.agenda.offset = 1
    items.extend(
        {
            "kind": "task",
            "source_id": "source",
            "uid": f"future-{i}",
            "title": f"Future task {i}",
            "due": (tomorrow + timedelta(days=4)).isoformat(),
        }
        for i in range(8)
    )
    widget.agenda.set_data(snapshot(items), ["A selected source could not be read."])
    headings = {}
    child = widget.agenda.get_first_child()
    while child is not None:
        if isinstance(child, Gtk.Box) and isinstance(child.get_first_child(), Gtk.Label):
            headings[child.get_first_child().get_text()] = child
        child = child.get_next_sibling()
    assert headings["Tasks"].get_last_child().get_text() == "5 due"
    assert headings["Completed"].get_last_child().get_text() == "5"
    assert headings["Next 4 days"].get_last_child().get_text() == "8"
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
        assert task.get_tooltip_text().startswith("Future task 7\nDue ")
        assert not task.has_css_class("overdue")

        def visible():
            success, bounds = task.compute_bounds(widget.scroll)
            return success and bounds.get_y() >= 0 and bounds.get_y() + bounds.get_height() <= 640

        settle_until(visible)
        task.emit("clicked")
        assert shown[0]["uid"] == "future-7"
        success, bounds = widget.footer.compute_bounds(widget.window)
        assert success and bounds.get_y() + bounds.get_height() <= widget.HEIGHT
        widget.agenda.set_data(snapshot([]), [])
        settle_until(lambda: widget.scroll.get_vadjustment().get_upper() <= widget.HEIGHT)
        assert (widget.window.get_width(), widget.window.get_height()) == (320, 640)
        widget.footer.get_first_child().emit("clicked")
        widget.footer.get_last_child().emit("clicked")
        assert drafts == ["task", "event"]
        assert widget.agenda.scrolled(None, 0, -1)
        assert widget.agenda.offset == offset - 1
    finally:
        widget.window.destroy()


def test_panel_is_regular_window_and_agenda_items_remain_reachable(styles):
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
            "new_task",
            "new_event",
            "save_item",
            "cancel_editor",
            "task_reminders",
            "compose",
        ),
        lambda *_: None,
    )
    actions["show_item"] = lambda item, _: shown.append(item)
    drafts = []
    actions["compose"] = lambda *draft: drafts.append(draft)
    panel = Panel(app, styles, actions)
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
    panel.show()
    adjustment = panel.agenda.scroll.get_vadjustment()
    try:
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
            {**items[0], "completed": True},
            {**items[0], "cancelled": True},
            {**items[0], "due": None},
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
        assert more.get_label() == "+1 more"
        settle_until(lambda: more.get_mapped())
        more.emit("clicked")
        content = app.popovers.current.get_child().get_child().get_child()
        content.get_last_child().emit("clicked")
        assert shown == ["task-4"]
        app.popovers.close()
        week.set_week({**data, "ranges": []}, first, False)
        assert week.missing.get_visible()
        assert not week.grid.blocks
        assert week.task_columns.get_child_at(0, 4).get_label() == "+1 more"
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


def test_task_reminders_retry_failed_delivery_and_open_the_current_task(styles, tmp_path):
    app = Application()
    item = {
        "kind": "task",
        "source_id": "source",
        "uid": "task",
        "title": "Task",
        "due": (datetime.now().astimezone() + timedelta(minutes=1)).isoformat(),
    }
    app.data = snapshot([item])
    app.config.task_reminders = True
    app.reminders = TaskReminders(tmp_path / "reminders.json")
    deliveries = []
    app.notifications = SimpleNamespace(send=lambda *args: deliveries.append(args))
    app.render_status = lambda: None
    shown = []
    app.show_item = lambda current, _anchor: shown.append(current)
    app.panel = SimpleNamespace(
        show_agenda=lambda: None,
        show=lambda: None,
        view_selector=Gtk.DropDown.new_from_strings(["Week", "Agenda"]),
    )
    try:
        app.loading = True
        app.check_task_reminders()
        assert deliveries == []  # Wait for the fresh snapshot after a save.
        app.loading = False
        app.check_task_reminders()
        app.check_task_reminders()
        assert len(deliveries) == 1  # An in-flight notification is not submitted twice.
        deliveries[0][1]("Service unavailable")
        assert "Service unavailable" in app.reminder_error
        app.check_task_reminders()
        assert len(deliveries) == 2
        deliveries[1][1](None)
        app.check_task_reminders()
        assert len(deliveries) == 2
        assert app.reminder_error is None
        app.data["items"] = [{**item, "title": "Edited after notification"}]
        app.open_reminder(item)
        assert shown[0]["title"] == "Edited after notification"
        assert app.panel.view_selector.get_selected() == 1
        app.data["items"][0]["completed"] = True
        app.open_reminder(item)
        assert len(shown) == 1
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
            Gtk4LayerShell.get_keyboard_mode(app.widget.window) == Gtk4LayerShell.KeyboardMode.NONE
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
        settle_until(lambda: nested.get_mapped())
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
        settle_until(lambda: app.editor_popup is None)
        assert not app.panel.visible()
        assert (
            Gtk4LayerShell.get_keyboard_mode(app.widget.window) == Gtk4LayerShell.KeyboardMode.NONE
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
        app.popovers.current.get_child().get_child().get_child().get_last_child().get_first_child().emit(
            "clicked"
        )
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
            assert app.editor_popup is None
            assert app.panel.quick_title.get_text() == "Keep this draft"
            assert not app.panel.visible()
    finally:
        app.stop()
        for window in app.get_windows():
            window.destroy()
