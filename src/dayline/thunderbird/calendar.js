// Calendar access stays inside Thunderbird, so its providers own synchronization.
var daylineCalendar = class extends ExtensionCommon.ExtensionAPI {
  getAPI(context) {
    Cu.importGlobalProperties(["TextEncoder"]);
    const { cal } = ChromeUtils.importESModule("resource:///modules/calendar/calUtils.sys.mjs");
    const { ExtensionError } = ChromeUtils.importESModule("resource://gre/modules/ExtensionUtils.sys.mjs");
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
    const revision = item => {
      const hash = Cc["@mozilla.org/security/hash;1"].createInstance(Ci.nsICryptoHash);
      hash.init(hash.SHA256);
      const bytes = new TextEncoder().encode(item.icalString);
      hash.update(bytes, bytes.length);
      return Array.from(hash.finish(false), c => c.charCodeAt(0).toString(16).padStart(2, "0")).join("");
    };
    const canWrite = (calendar, settings) => !calendar.readOnly &&
      !calendar.getProperty("disabled") &&
      (settings.writable ?? (settings.role === "personal")) === true;
    const serialize = (item, kind) => ({
      uid: item.id,
      revision: revision(item),
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
    const selectedCalendar = request => {
      const settings = request.selection?.[request.source_id];
      if (!settings || !["personal", "school"].includes(settings.role) ||
          typeof settings.events !== "boolean" || typeof settings.tasks !== "boolean" ||
          (settings.role === "school" && settings.tasks) ||
          (settings.writable !== undefined && typeof settings.writable !== "boolean")) {
        throw new ExtensionError("Select this source and item type before editing.");
      }
      if (!["event", "task"].includes(request.kind) ||
          !settings[request.kind === "event" ? "events" : "tasks"] ||
          (request.kind === "task" && settings.role !== "personal")) {
        throw new ExtensionError("This item type is not selected for this source.");
      }
      const calendar = cal.manager.getCalendarById(request.source_id);
      if (!calendar || calendar.getProperty("disabled")) {
        throw new ExtensionError("The source is missing or disabled in Thunderbird.");
      }
      if (calendar.getProperty(`capabilities.${request.kind === "event" ? "events" : "tasks"}.supported`) === false) {
        throw new ExtensionError("This source does not support the item type.");
      }
      return [calendar, settings];
    };
    const parseDate = (value, timezone = null) => {
      if (value === null) {
        return null;
      }
      if (typeof value !== "string") {
        throw new ExtensionError("Use a date or an ISO timestamp with a timezone.");
      }
      const day = value.slice(0, 10);
      const check = new Date(`${day}T00:00:00Z`);
      if (!Number.isFinite(check.getTime()) || check.toISOString().slice(0, 10) !== day) {
        throw new ExtensionError("Invalid calendar date.");
      }
      if (/^\d{4}-\d{2}-\d{2}$/.test(value)) {
        const result = cal.createDateTime(value.replaceAll("-", ""));
        result.isDate = true;
        return result;
      }
      if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})$/.test(value) ||
          !Number.isFinite(new Date(value).getTime())) {
        throw new ExtensionError("Use a date or an ISO timestamp with a timezone.");
      }
      const date = new Date(value);
      // Floating times are serialized using the machine's local wall clock.
      if (timezone?.isFloating) return cal.dtz.jsDateToDateTime(date, timezone);
      const result = cal.dtz.jsDateToDateTime(date);
      return timezone ? result.getInTimezone(timezone) : result;
    };
    const target = async (request, calendar) => {
      if (typeof request.uid !== "string" || !request.uid) {
        throw new ExtensionError("An item UID is required.");
      }
      const parent = await calendar.getItem(request.uid);
      if (!parent || (parent.isEvent() ? "event" : "task") !== request.kind) {
        throw new ExtensionError("The item was removed or its type changed; refresh first.");
      }
      const recurring = !!parent.recurrenceInfo;
      if (!["item", "series", "occurrence"].includes(request.scope) ||
          (recurring && request.scope === "item") ||
          (!recurring && (request.scope !== "item" || request.recurrence_id))) {
        throw new ExtensionError("Choose this occurrence or the entire recurring series explicitly.");
      }
      if (request.scope !== "occurrence") {
        return parent;
      }
      const id = parseDate(request.recurrence_id, parent.recurrenceStartDate?.timezone);
      if (!id) {
        throw new ExtensionError("An occurrence recurrence ID is required.");
      }
      if (!parent.recurrenceStartDate || id.isDate !== parent.recurrenceStartDate.isDate) {
        throw new ExtensionError("Recurrence IDs must match the item's date-only or timed type.");
      }
      const exception = parent.recurrenceInfo.getExceptionFor(id);
      if (!exception) {
        const end = id.clone();
        end.addDuration(cal.createDuration(id.isDate ? "P1D" : "PT1S"));
        if (!parent.recurrenceInfo.getOccurrenceDates(id, end, 1).some(d => d.compare(id) === 0)) {
          throw new ExtensionError("This occurrence no longer exists; refresh first.");
        }
      }
      return exception || parent.recurrenceInfo.getOccurrenceFor(id);
    };
    const write = async request => {
      const [calendar, settings] = selectedCalendar(request);
      if (!canWrite(calendar, settings)) {
        throw new ExtensionError("This source is read-only in Dayline. School calendars require an explicit editing opt-in in Sources; keep subscriptions read-only.");
      }
      const creating = request.command === "create";
      let original = null;
      let item;
      if (creating) {
        if (request.scope !== "item" || request.recurrence_id) {
          throw new ExtensionError("New items must use the non-recurring item scope.");
        }
        if (!cal.acl.userCanAddItemsToCalendar(calendar)) {
          throw new ExtensionError("Thunderbird does not permit creating items in this source.");
        }
        const { CalEvent } = ChromeUtils.importESModule("resource:///modules/CalEvent.sys.mjs");
        const { CalTodo } = ChromeUtils.importESModule("resource:///modules/CalTodo.sys.mjs");
        item = request.kind === "event" ? new CalEvent() : new CalTodo();
        item.calendar = calendar;
        if (typeof request.uid !== "string" || !/^[0-9a-f-]{36}$/i.test(request.uid)) {
          throw new ExtensionError("Creation requires a stable UUID.");
        }
        if (await calendar.getItem(request.uid)) {
          throw new ExtensionError("This item was already created; refresh before retrying.");
        }
        item.id = request.uid;
      } else {
        original = await target(request, calendar);
        if (!cal.acl.userCanModifyItem(original) || original.getAttendees().length ||
            cal.itip.isInvitation(original)) {
          throw new ExtensionError("This item cannot be edited here; manage invitations in Thunderbird.");
        }
        if (request.revision !== revision(original)) {
          throw new ExtensionError("This item changed since it was opened; reopen it before saving.");
        }
        item = original.clone();
      }
      const fields = request.fields;
      const allowed = request.kind === "event" ?
        ["title", "start", "end", "location", "description", "reminder"] :
        ["title", "start", "due", "location", "description", "reminder", "completed"];
      if (!fields || typeof fields !== "object" || Array.isArray(fields) ||
          !Object.keys(fields).length || Object.keys(fields).some(k => !allowed.includes(k))) {
        throw new ExtensionError("Unsupported or empty item changes.");
      }
      for (const name of ["title", "location", "description"]) {
        if (name in fields) {
          if (typeof fields[name] !== "string" || (name === "title" && !fields[name].trim())) {
            throw new ExtensionError("An item needs a nonempty title and plain-text fields.");
          }
          if (name === "title") {
            item.title = fields.title.trim();
          } else {
            item.setProperty(name.toUpperCase(), fields[name]);
          }
        }
      }
      if (!item.title?.trim()) {
        throw new ExtensionError("An item needs a nonempty title.");
      }
      const dates = request.kind === "event" ?
        { start: "startDate", end: "endDate" } : { start: "entryDate", due: "dueDate" };
      for (const [name, property] of Object.entries(dates)) {
        if (name in fields) {
          const previous = item[property];
          // Keep a series' local recurrence time across daylight-saving changes.
          item[property] = parseDate(fields[name], previous && !previous.isDate ? previous.timezone : null);
        }
      }
      const start = item[request.kind === "event" ? "startDate" : "entryDate"];
      const end = item[request.kind === "event" ? "endDate" : "dueDate"];
      if (request.kind === "event" && (!start || !end || start.isDate !== end.isDate ||
          end.compare(start) < 0 || (start.isDate && end.compare(start) === 0))) {
        throw new ExtensionError("Events need matching start/end dates or times; all-day end is exclusive.");
      }
      if (request.kind === "task" && start && end) {
        const deadline = end.clone();
        if (end.isDate) deadline.addDuration(cal.createDuration("P1D"));
        if (end.isDate ? deadline.compare(start) <= 0 : deadline.compare(start) < 0) {
          throw new ExtensionError("Task due time cannot precede its start.");
        }
      }
      if ("completed" in fields) {
        if (typeof fields.completed !== "boolean") {
          throw new ExtensionError("Task completion must be true or false.");
        }
        item.isCompleted = fields.completed;
      }
      if ("reminder" in fields) {
        const when = parseDate(fields.reminder);
        if (when?.isDate) {
          throw new ExtensionError("A reminder needs an explicit time with a timezone.");
        }
        // Replace DISPLAY alarms only; preserve alarms the editor does not support.
        for (const alarm of item.getAlarms()) {
          if (alarm.action === "DISPLAY") item.deleteAlarm(alarm);
        }
        if (when) {
          const { CalAlarm } = ChromeUtils.importESModule("resource:///modules/CalAlarm.sys.mjs");
          const alarm = new CalAlarm();
          alarm.action = "DISPLAY";
          alarm.related = Ci.calIAlarm.ALARM_RELATED_ABSOLUTE;
          alarm.alarmDate = when;
          item.addAlarm(alarm);
        }
      }
      let saved;
      try {
        saved = creating ? await calendar.addItem(item) : await calendar.modifyItem(item, original);
      } catch (error) {
        throw new ExtensionError(`Thunderbird rejected the write: ${error.message || String(error)}`);
      }
      try {
        // Storage providers can return the parent series after an occurrence edit.
        const result = request.scope === "occurrence" ? await target(request, calendar) : saved;
        return { state: "local", cloud_confirmed: false, item: serialize(result, request.kind) };
      } catch (error) {
        throw new ExtensionError(`Saved locally in Thunderbird, but rereading failed: ${error.message || String(error)}. Refresh before retrying.`);
      }
    };
    return {
      daylineCalendar: {
        execute: async request => {
          if (request.command === "sources") {
            // Metadata only; don't read another account's items before source selection.
            return { sources: cal.manager.getCalendars().map(metadata) };
          }
          if (["create", "update"].includes(request.command)) {
            try {
              return await write(request);
            } catch (error) {
              throw new ExtensionError(error.message || "Thunderbird could not save this item.");
            }
          }
          if (request.command === "item") {
            const [calendar] = selectedCalendar(request);
            try {
              return { item: serialize(await target(request, calendar), request.kind) };
            } catch (error) {
              throw new ExtensionError(error.message || "Cannot read this item.");
            }
          }
          if (request.command !== "snapshot") {
            throw new ExtensionError("Unsupported Dayline command.");
          }
          const selection = request.selection;
          if (!selection || typeof selection !== "object" || Array.isArray(selection)) {
            throw new ExtensionError("Invalid source selection.");
          }
          const ranges = request.ranges;
          if (!Array.isArray(ranges) || !ranges.length || ranges.length > 2) {
            throw new ExtensionError("Choose one or two bounded date ranges.");
          }
          const bounds = ranges.map(range => {
            const start = new Date(range.start);
            const end = new Date(range.end);
            const duration = end - start;
            // Allow DST changes at local midnight.
            if (!Number.isFinite(duration) || duration <= 0 || duration > 36 * 86400000) {
              throw new ExtensionError("Date ranges must be no longer than 35 days.");
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
              throw new ExtensionError("Invalid selection: only personal sources may supply tasks.");
            }
            const calendar = cal.manager.getCalendarById(id);
            if (!calendar) {
              errors.push({ source_id: id, message: "Calendar no longer exists in Thunderbird." });
              continue;
            }
            sources.push({ ...metadata(calendar), role: settings.role, writable: canWrite(calendar, settings) });
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
