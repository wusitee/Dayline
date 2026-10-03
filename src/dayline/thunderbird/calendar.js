// Calendar access stays inside Thunderbird, so its providers own synchronization.
var daylineCalendar = class extends ExtensionCommon.ExtensionAPI {
  getAPI(context) {
    const { cal } = ChromeUtils.importESModule("resource:///modules/calendar/calUtils.sys.mjs");
    const metadata = calendar => ({
      id: calendar.id,
      name: calendar.name,
      type: calendar.type,
      color: calendar.getProperty("color") || "#91b8ff",
      read_only: !!calendar.readOnly,
      disabled: !!calendar.getProperty("disabled"),
      events: calendar.getProperty("capabilities.events.supported") !== false,
      tasks: calendar.getProperty("capabilities.tasks.supported") !== false,
    });
    const dateValue = value => {
      if (!value) {
        return null;
      }
      if (value.isDate) {
        return `${value.year}-${String(value.month + 1).padStart(2, "0")}-${String(value.day).padStart(2, "0")}`;
      }
      return cal.dtz.dateTimeToJsDate(value).toISOString();
    };
    const serialize = (item, kind) => ({
      uid: item.id,
      recurrence_id: dateValue(item.recurrenceId),
      kind,
      source_id: item.calendar.id,
      title: item.title || "Untitled",
      start: dateValue(kind === "event" ? item.startDate : item.entryDate),
      end: dateValue(kind === "event" ? item.endDate : null),
      due: dateValue(kind === "task" ? item.dueDate : null),
      completed: kind === "task" && item.isCompleted,
      cancelled: item.getProperty("STATUS") === "CANCELLED",
      location: item.getProperty("LOCATION") || "",
      description: item.getProperty("DESCRIPTION") || "",
      recurring: !!item.recurrenceInfo || !!item.recurrenceId,
      alarms: item.getAlarms().filter(alarm => alarm.action === "DISPLAY").map(alarm =>
        dateValue(cal.alarms.calculateAlarmDate(item, alarm))
      ).filter(Boolean),
    });
    return {
      daylineCalendar: {
        execute: async request => {
          if (request.command === "sources") {
            // Metadata only; don't read another account's items before source selection.
            return { sources: cal.manager.getCalendars().map(metadata) };
          }
          if (request.command !== "snapshot") {
            throw new Error("Unsupported Dayline command.");
          }
          const selection = request.selection;
          if (!selection || typeof selection !== "object" || Array.isArray(selection)) {
            throw new Error("Invalid source selection.");
          }
          const ranges = request.ranges;
          if (!Array.isArray(ranges) || !ranges.length || ranges.length > 2) {
            throw new Error("Choose one or two bounded date ranges.");
          }
          const bounds = ranges.map(range => {
            const start = new Date(range.start);
            const end = new Date(range.end);
            const duration = end - start;
            // Allow DST changes at local midnight.
            if (!Number.isFinite(duration) || duration <= 0 || duration > 36 * 86400000) {
              throw new Error("Date ranges must be no longer than 35 days.");
            }
            return [cal.dtz.jsDateToDateTime(start), cal.dtz.jsDateToDateTime(end)];
          });
          const sources = [];
          const items = new Map();
          const errors = [];
          for (const [id, settings] of Object.entries(selection)) {
            if (!settings || !["personal", "school"].includes(settings.role) ||
                typeof settings.events !== "boolean" || typeof settings.tasks !== "boolean" ||
                (settings.role === "school" && settings.tasks)) {
              throw new Error("Invalid selection: only personal sources may supply tasks.");
            }
            const calendar = cal.manager.getCalendarById(id);
            if (!calendar) {
              errors.push({ source_id: id, message: "Calendar no longer exists in Thunderbird." });
              continue;
            }
            sources.push({ ...metadata(calendar), role: settings.role });
            try {
              if (calendar.getProperty("disabled")) {
                throw new Error("Calendar is disabled in Thunderbird.");
              }
              if ((settings.events && calendar.getProperty("capabilities.events.supported") === false) ||
                  (settings.tasks && calendar.getProperty("capabilities.tasks.supported") === false)) {
                throw new Error("Calendar no longer supports the selected item type.");
              }
              if (settings.events && calendar.getProperty("capabilities.events.supported") !== false) {
                const filter = Ci.calICalendar.ITEM_FILTER_TYPE_EVENT |
                  Ci.calICalendar.ITEM_FILTER_CLASS_OCCURRENCES;
                for (const [start, end] of bounds) {
                  for (const item of await calendar.getItemsAsArray(filter, 0, start, end)) {
                    const record = serialize(item, "event");
                    items.set(JSON.stringify([id, record.uid, record.recurrence_id, record.start]), record);
                  }
                }
              }
              if (settings.tasks && calendar.getProperty("capabilities.tasks.supported") !== false) {
                // No date filter: include undated tasks and every selected personal list.
                const filter = Ci.calICalendar.ITEM_FILTER_TYPE_TODO |
                  Ci.calICalendar.ITEM_FILTER_COMPLETED_ALL;
                for (const item of await calendar.getItemsAsArray(filter, 0, null, null)) {
                  const record = serialize(item, "task");
                  items.set(JSON.stringify([id, record.uid, record.recurrence_id]), record);
                }
              }
            } catch (error) {
              errors.push({ source_id: id, message: error.message || "Calendar read failed." });
            }
          }
          return {
            generated_at: new Date().toISOString(),
            offline: Services.io.offline,
            ranges,
            sources,
            items: Array.from(items.values()),
            errors,
          };
        },
        onChanged: new ExtensionCommon.EventManager({
          context,
          name: "daylineCalendar.onChanged",
          register: fire => {
            const changed = () => fire.async();
            const observer = {
              QueryInterface: ChromeUtils.generateQI(["calIObserver"]),
              onStartBatch() {},
              onEndBatch: changed,
              onLoad: changed,
              onAddItem: changed,
              onModifyItem: changed,
              onDeleteItem: changed,
              onError: changed,
              onPropertyChanged: changed,
              onPropertyDeleting: changed,
            };
            cal.manager.addCalendarObserver(observer);
            return () => cal.manager.removeCalendarObserver(observer);
          },
        }).api(),
      },
    };
  }

  onShutdown(isAppShutdown) {
    if (!isAppShutdown) {
      Services.obs.notifyObservers(null, "startupcache-invalidate", null);
    }
  }
};
