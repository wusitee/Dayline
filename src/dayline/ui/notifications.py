"""Asynchronous freedesktop notifications, with actions while Dayline is running."""

from collections.abc import Callable
from datetime import date

from gi.repository import Gio, GLib

from dayline.agenda import due_label, time_range
from dayline.reminders import Reminder

SERVICE = "org.freedesktop.Notifications"
PATH = "/org/freedesktop/Notifications"


class Notifications:
    def __init__(self, open_item: Callable[[dict], None]):
        self.open_item = open_item
        self.connection = None
        self.subscription = 0
        self.closed = False
        self.targets: dict[int, dict] = {}
        Gio.bus_get(Gio.BusType.SESSION, None, self.connected)

    def connected(self, _source, result) -> None:
        try:
            connection = Gio.bus_get_finish(result)
        except GLib.Error:
            return  # The next attempt reports the missing connection in the UI.
        if self.closed:
            return
        self.connection = connection
        self.subscription = connection.signal_subscribe(
            SERVICE, SERVICE, None, PATH, None, Gio.DBusSignalFlags.NONE, self.signal
        )

    def signal(self, _connection, _sender, _path, _interface, name, parameters) -> None:
        values = parameters.unpack()
        item = self.targets.get(values[0])
        if name == "ActionInvoked" and item is not None and values[1] in ("default", "open"):
            self.open_item(item)
        elif name == "NotificationClosed":
            self.targets.pop(values[0], None)

    def send(self, reminder: Reminder, completed: Callable[[str | None], None]) -> None:
        item = reminder.item
        action = "Open task" if item["kind"] == "task" else "Open event"
        body = (
            due_label(item, date.today())
            if item["kind"] == "task"
            else time_range(item, date.today())
        )
        self.notify(
            item["title"] or "Reminder",
            body,
            completed,
            actions=["default", action, "open", action],
            item=item,
        )

    def notify(
        self,
        summary: str,
        body: str,
        completed: Callable[[str | None], None],
        *,
        actions: list[str] | None = None,
        item: dict | None = None,
    ) -> None:
        """Show a notification; actions open item."""
        if self.connection is None:
            completed("The desktop notification service is not connected.")
            return
        parameters = GLib.Variant(
            "(susssasa{sv}i)",
            (
                "Dayline",
                0,
                "alarm-symbolic",
                summary,
                GLib.markup_escape_text(body),
                actions or [],
                {"urgency": GLib.Variant("y", 1)},
                -1,
            ),
        )

        def sent(connection, result):
            try:
                notification_id = connection.call_finish(result).unpack()[0]
            except GLib.Error as exc:
                completed(exc.message)
                return
            if item is not None:
                self.targets[notification_id] = item
            completed(None)

        self.connection.call(
            SERVICE,
            PATH,
            SERVICE,
            "Notify",
            parameters,
            GLib.VariantType.new("(u)"),
            Gio.DBusCallFlags.NONE,
            5000,
            None,
            sent,
        )

    def close(self) -> None:
        self.closed = True
        if self.connection is not None:
            self.connection.signal_unsubscribe(self.subscription)
        self.targets.clear()
