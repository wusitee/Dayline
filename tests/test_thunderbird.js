const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const test = require("node:test");

function fixture() {
  const calls = [];
  const date = value => value ? {
    isDate: value.length === 10,
    year: Number(value.slice(0, 4)), month: Number(value.slice(5, 7)) - 1,
    day: Number(value.slice(8, 10)), value,
    timezone: { tzid: "UTC" },
    compare(other) { return Math.sign(new Date(this.value) - new Date(other.value)); },
    clone() { return this.getInTimezone(this.timezone); },
    getInTimezone(timezone) { return Object.assign(date(this.value), { timezone }); },
    addDuration(duration) { this.value = new Date(new Date(this.value).getTime() + duration).toISOString(); },
  } : null;
  class Item {
    constructor(kind) {
      this.kind = kind;
      this.id = "uid";
      this.title = "Existing item";
      this.properties = { "X-KEEP": "untouched", DESCRIPTION: "Keep notes" };
      this.alarms = [];
      this.attendees = [];
      this.isCompleted = false;
      this.recurrenceInfo = null;
      this.recurrenceId = null;
      this.startDate = kind === "event" ? date("2026-10-05T03:00:00Z") : null;
      this.endDate = kind === "event" ? date("2026-10-05T04:00:00Z") : null;
      this.entryDate = this.dueDate = null;
    }
    get icalString() {
      return JSON.stringify([this.id, this.title, this.properties, this.isCompleted,
        this.startDate?.value, this.endDate?.value, this.entryDate?.value, this.dueDate?.value,
        this.recurrenceId?.value, this.alarms]);
    }
    get recurrenceStartDate() { return this.kind === "event" ? this.startDate : this.entryDate || this.dueDate; }
    get isCompleted() { return this.completed; }
    set isCompleted(value) {
      this.completed = value;
      this.completedDate = value ? this.completedDate || date("2026-10-05T03:00:00Z") : null;
    }
    isEvent() { return this.kind === "event"; }
    getProperty(name) { return this.properties[name] ?? null; }
    setProperty(name, value) { this.properties[name] = value; }
    getAlarms() { return this.alarms; }
    getAttendees() { return this.attendees; }
    deleteAlarm(alarm) { this.alarms = this.alarms.filter(a => a !== alarm); }
    addAlarm(alarm) { this.alarms.push(alarm); }
    clone() {
      const item = Object.assign(new Item(this.kind), this);
      item.properties = { ...this.properties };
      item.alarms = [...this.alarms];
      return item;
    }
  }
  const source = id => {
    const calendar = {
      id, name: id, type: "storage", readOnly: id === "school", properties: {},
      getProperty: name => calendar.properties[name] ?? (name === "color" ? "#88aaff" : null),
      getItemsAsArray: async (filter, count, start, end) => {
        calls.push({ id, filter, count, start, end });
        if (id === "broken") throw new Error("Provider unavailable");
        return [calendar.item];
      },
      getItem: async uid => calendar.items.get(uid) || null,
      addItem: async item => {
        if (calendar.writeFailure) throw new Error("Provider write failed");
        calls.push({ operation: "add", id, item });
        calendar.items.set(item.id, item);
        return item;
      },
      modifyItem: async (item, old) => {
        if (calendar.writeFailure) throw new Error("Provider write failed");
        calls.push({ operation: "modify", id, item, old });
        if (item.recurrenceId) {
          const parent = calendar.items.get(item.id);
          parent.recurrenceInfo.modifyException(item);
          return parent;
        }
        calendar.items.set(item.id, item);
        return item;
      },
    };
    calendar.item = new Item(id === "personal" ? "task" : "event");
    calendar.item.calendar = calendar;
    calendar.item.title = id === "personal" ? "Undated task" : "Class";
    calendar.item.recurrenceId = id === "school" ? date("2026-10-05T03:00:00Z") : null;
    calendar.items = new Map([["uid", calendar.item]]);
    return calendar;
  };
  const sources = ["personal", "school", "unselected", "broken"].map(source);
  class ExtensionError extends Error {
    constructor(message) { super(message); this.name = "ExtensionError"; }
  }
  const cal = {
    manager: { getCalendars: () => sources, getCalendarById: id => sources.find(s => s.id === id) },
    dtz: {
      // Model floating wall times in Asia/Shanghai independently of the runner's TZ.
      dateTimeToJsDate: d => new Date(new Date(d.value).getTime() - (d.timezone.isFloating ? 8 * 3600000 : 0)),
      jsDateToDateTime: (d, timezone) => Object.assign(
        date(new Date(d.getTime() + (timezone?.isFloating ? 8 * 3600000 : 0)).toISOString()),
        timezone ? { timezone } : {},
      ),
    },
    createDateTime: value => date(`${value.slice(0,4)}-${value.slice(4,6)}-${value.slice(6,8)}`),
    createDuration: value => value === "P1D" ? 86400000 : 1000,
    alarms: { calculateAlarmDate: (_item, alarm) => alarm.alarmDate },
    acl: { userCanAddItemsToCalendar: () => true, userCanModifyItem: () => true },
    itip: { isInvitation: () => false },
  };
  const sandbox = {
    TextEncoder,
    Cu: { importGlobalProperties() {} },
    Cc: { "@mozilla.org/security/hash;1": { createInstance: () => ({
      SHA256: 1,
      init() { this.hash = require("node:crypto").createHash("sha256"); },
      update(bytes) { this.hash.update(bytes); },
      finish() { return this.hash.digest("latin1"); },
    }) } },
    ExtensionCommon: { ExtensionAPI: class {}, EventManager: class { api() { return {}; } } },
    ChromeUtils: { importESModule: path => {
      if (path.includes("ExtensionUtils")) return { ExtensionError };
      if (path.includes("CalEvent.sys")) return { CalEvent: class extends Item { constructor() { super("event"); this.title = ""; } } };
      if (path.includes("CalTodo.sys")) return { CalTodo: class extends Item { constructor() { super("task"); this.title = ""; } } };
      if (path.includes("CalAlarm.sys")) return { CalAlarm: class {} };
      return { cal };
    } },
    Ci: {
      calICalendar: { ITEM_FILTER_TYPE_EVENT: 8, ITEM_FILTER_CLASS_OCCURRENCES: 65536,
        ITEM_FILTER_TYPE_TODO: 4, ITEM_FILTER_COMPLETED_ALL: 3 },
      calIAlarm: { ALARM_RELATED_ABSOLUTE: 0 }, nsICryptoHash: {},
    },
    Services: { io: { offline: false } },
  };
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync("src/dayline/thunderbird/calendar.js", "utf8"), sandbox);
  const calendarExecute = new sandbox.daylineCalendar().getAPI({}).daylineCalendar.execute;
  // Thunderbird's Experiment boundary hides ordinary errors from extensions.
  const execute = async request => {
    try { return await calendarExecute(request); }
    catch (error) {
      if (error.name === "ExtensionError") throw error;
      throw new Error("An unexpected error occurred");
    }
  };
  return { execute, calls, sources, cal, date };
}

const ranges = [
  { start: "2026-10-05T00:00:00Z", end: "2026-10-12T00:00:00Z" },
  { start: "2026-10-05T00:00:00Z", end: "2026-10-12T00:00:00Z" },
];

test("source discovery reads metadata only", async () => {
  const { execute, calls } = fixture();
  const result = await execute({ command: "sources" });
  assert.equal(result.sources.length, 4);
  assert.equal(calls.length, 0);
  assert.equal(result.sources.find(s => s.id === "school").read_only, true);
  assert.equal(result.sources[0].uri, undefined);
});

test("selected events expand occurrences and personal tasks retain undated items", async () => {
  const { execute, calls } = fixture();
  const result = await execute({ command: "snapshot", ranges, selection: {
    personal: { role: "personal", events: false, tasks: true },
    school: { role: "school", events: true, tasks: false },
  } });
  assert.equal(result.errors.length, 0);
  assert.equal(result.items.length, 2); // Duplicate occurrences from overlapping ranges collapse.
  assert.equal(result.items.find(i => i.kind === "task").due, null);
  assert.ok(result.items.find(i => i.kind === "event").recurrence_id);
  assert.deepEqual(calls.map(c => c.id), ["personal", "school", "school"]);
  assert.equal(calls[0].start, null);
  assert.equal(calls[0].end, null);
  assert.equal(calls[0].filter, 7);
  assert.equal(calls[1].filter, 8 | 65536);
});

test("school tasks and unbounded recurrence expansion are rejected before reads", async () => {
  const { execute, calls } = fixture();
  await assert.rejects(execute({ command: "snapshot", ranges, selection: {
    school: { role: "school", events: false, tasks: true },
  } }), /only personal/);
  await assert.rejects(execute({ command: "snapshot", selection: {}, ranges: [
    { start: "2026-01-01", end: "2027-01-01" },
  ] }), /no longer than 35/);
  assert.equal(calls.length, 0);
});

test("provider failure and deleted calendars are explicit, not empty successes", async () => {
  const { execute } = fixture();
  const result = await execute({ command: "snapshot", ranges, selection: {
    broken: { role: "personal", events: true, tasks: false },
    removed: { role: "school", events: true, tasks: false },
  } });
  assert.equal(result.errors.length, 2);
  assert.equal(result.errors[0].message, "Provider unavailable");
  assert.match(result.errors[1].message, /no longer exists/);
});

test("background routes native requests and coalesces change bursts", async () => {
  const timers = [];
  const sent = [];
  let changed, incoming;
  const port = {
    onMessage: { addListener: callback => { incoming = callback; } },
    onDisconnect: { addListener: () => {} },
    postMessage: message => sent.push(message),
  };
  const sandbox = {
    browser: {
      runtime: { connectNative: name => {
        assert.equal(name, "io.github.wusitee.dayline");
        return port;
      } },
      daylineCalendar: {
        execute: async request => ({ command: request.command }),
        onChanged: { addListener: callback => { changed = callback; } },
      },
    },
    setTimeout: callback => { timers.push(callback); return timers.length; },
  };
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync("src/dayline/thunderbird/background.js", "utf8"), sandbox);
  incoming({ id: 9, command: "sources" });
  await vm.runInContext("queue", sandbox);
  assert.equal(sent[0].id, 9);
  assert.equal(sent[0].result.command, "sources");
  changed(); changed(); changed();
  assert.equal(timers.length, 1);
  timers[0]();
  assert.equal(sent.filter(message => message.event === "changed").length, 1);
});

const personalTasks = { personal: { role: "personal", events: false, tasks: true } };
const eventSelection = { unselected: { role: "personal", events: true, tasks: false } };
const uuid = "11111111-1111-4111-8111-111111111111";

function taskRequest(command, fields = {}) {
  return { command, selection: personalTasks, source_id: "personal", kind: "task",
    uid: command === "create" ? uuid : "uid", scope: "item", fields };
}

test("task edits preserve provider fields, reject stale saves, and report local acceptance", async () => {
  const { execute, sources, calls } = fixture();
  const read = await execute(taskRequest("item"));
  const saved = await execute({ ...taskRequest("update", { title: "Edited", completed: true }), revision: read.item.revision });
  assert.equal(saved.state, "local");
  assert.equal(saved.cloud_confirmed, false);
  assert.equal(saved.item.completed, true);
  assert.equal(saved.item.completed_at, "2026-10-05T03:00:00.000Z");
  assert.equal(sources[0].items.get("uid").getProperty("X-KEEP"), "untouched");
  assert.equal(saved.item.description, "Keep notes");
  await assert.rejects(execute({ ...taskRequest("update", { title: "Overwrite" }), revision: read.item.revision }), /changed since/);
  const reopened = await execute({ ...taskRequest("update", { completed: false }), revision: saved.item.revision });
  assert.equal(reopened.item.completed, false);
  assert.equal(reopened.item.completed_at, null);
  const created = await execute(taskRequest("create", { title: "Undated" }));
  assert.equal(created.item.uid, uuid);
  assert.equal(created.item.due, null);
  const dated = await execute({ ...taskRequest("update", { start: "2026-10-05T02:00:00Z", due: "2026-10-05" }), uid: uuid, revision: created.item.revision });
  assert.equal(dated.item.due, "2026-10-05");
  await assert.rejects(execute(taskRequest("create", { title: "Duplicate" })), /already created/);
  assert.equal(calls.filter(c => c.operation).length, 4);
});

test("source/type permissions and school opt-in are enforced before provider writes", async () => {
  const { execute, sources, calls } = fixture();
  const create = taskRequest("create", { title: "Test" });
  await assert.rejects(execute(taskRequest("create", { title: "Test", location: "Not a To Do field" })), /Unsupported/);
  await assert.rejects(execute({ ...create, scope: "occurrence" }), /non-recurring item scope/);
  await assert.rejects(execute({ ...create, selection: {} }), /Select this source/);
  await assert.rejects(execute({ ...create, kind: "event" }), /not selected/);
  await assert.rejects(execute({ ...create, selection: { personal: { role: "school", events: false, tasks: true } } }), /Select this source/);
  sources[0].readOnly = true;
  await assert.rejects(execute(create), /read-only/);
  sources[0].readOnly = false;
  sources[0].properties.disabled = true;
  await assert.rejects(execute(create), /disabled/);
  sources[0].properties.disabled = false;
  sources[0].properties["capabilities.tasks.supported"] = false;
  await assert.rejects(execute(create), /does not support/);
  const school = { command: "create", kind: "event", source_id: "school", uid: uuid, scope: "item",
    fields: { title: "Appointment", start: "2026-10-05", end: "2026-10-06" },
    selection: { school: { role: "school", events: true, tasks: false } } };
  sources[1].readOnly = false;
  await assert.rejects(execute(school), /explicit editing opt-in/);
  assert.equal(calls.filter(c => c.operation).length, 0);
  school.selection.school.writable = true;
  assert.equal((await execute(school)).item.kind, "event");
});

test("event dates and explicit DISPLAY reminders round-trip without touching other alarms", async () => {
  const { execute, sources, calls } = fixture();
  const request = { command: "create", kind: "event", source_id: "unselected", uid: uuid, scope: "item",
    selection: eventSelection, fields: { title: "All-day", start: "2026-10-05", end: "2026-10-06" } };
  for (const fields of [
    { start: "2026-02-30" }, { start: "2026-02-30T10:00:00Z" }, { end: "2026-10-04" },
    { start: "2026-10-05T10:00:00" }, { reminder: "2026-10-05" }, { attendees: [] },
  ]) await assert.rejects(execute({ ...request, fields: { ...request.fields, ...fields } }));
  assert.equal(calls.filter(c => c.operation).length, 0);
  const result = await execute(request);
  assert.equal(result.item.start, "2026-10-05");
  const item = sources[2].items.get(uuid);
  item.alarms.push({ action: "EMAIL" });
  const current = await execute({ ...request, command: "item", scope: "item" });
  const saved = await execute({ ...request, command: "update", scope: "item", revision: current.item.revision,
    fields: { reminder: "2026-10-05T01:00:00Z" } });
  assert.deepEqual(Array.from(saved.item.alarms), ["2026-10-05T01:00:00.000Z"]);
  assert.equal(sources[2].items.get(uuid).getAlarms().filter(a => a.action === "EMAIL").length, 1);
});

test("recurring edits require an explicit valid occurrence or series and keep their identity", async () => {
  const { execute, sources, date, calls } = fixture();
  const parent = sources[2].item;
  const timezone = { tzid: "Europe/London" };
  parent.startDate.timezone = parent.endDate.timezone = timezone;
  const exceptions = new Map();
  parent.recurrenceInfo = {
    getExceptionFor: id => exceptions.get(new Date(id.value).getTime()) || null,
    modifyException: item => exceptions.set(new Date(item.recurrenceId.value).getTime(), item),
    getOccurrenceDates: () => [date("2026-10-05T03:00:00Z")],
    getOccurrenceFor: id => { const occurrence = parent.clone(); occurrence.recurrenceId = id; occurrence.recurrenceInfo = null; return occurrence; },
  };
  const request = { command: "item", source_id: "unselected", kind: "event", uid: "uid", selection: eventSelection };
  await assert.rejects(execute({ ...request, scope: "item" }), /explicitly/);
  await assert.rejects(execute({ ...request, scope: "occurrence", recurrence_id: "2026-10-05" }), /date-only or timed/);
  await assert.rejects(execute({ ...request, scope: "occurrence", recurrence_id: "2026-10-07T03:00:00Z" }), /no longer exists/);
  const occurrence = await execute({ ...request, scope: "occurrence", recurrence_id: "2026-10-05T03:00:00Z" });
  const saved = await execute({ ...request, command: "update", scope: "occurrence", recurrence_id: occurrence.item.recurrence_id,
    revision: occurrence.item.revision, fields: { title: "One occurrence" } });
  assert.equal(saved.item.title, "One occurrence");
  assert.equal(saved.item.recurrence_id, occurrence.item.recurrence_id);
  assert.equal(calls.at(-1).old.recurrenceId.value, "2026-10-05T03:00:00.000Z");
  assert.equal(parent.title, "Class");
  const series = await execute({ ...request, scope: "series" });
  await execute({ ...request, command: "update", scope: "series", revision: series.item.revision,
    fields: { title: "Entire series", start: "2026-10-05T04:00:00Z", end: "2026-10-05T05:00:00Z" } });
  assert.equal(calls.at(-1).old.recurrenceId, null);
  assert.equal(sources[2].items.get("uid").startDate.timezone.tzid, "Europe/London");
  assert.equal(sources[2].items.get("uid").endDate.timezone.tzid, "Europe/London");
  sources[2].items.get("uid").startDate = date("2026-10-05");
  await assert.rejects(execute({ ...request, scope: "occurrence", recurrence_id: "2026-10-05T12:00:00Z" }), /date-only or timed/);
});

test("floating occurrence identities reconstruct local wall time before lookup", async () => {
  const { execute, sources, date } = fixture();
  const parent = sources[2].item;
  const timezone = { tzid: "floating", isFloating: true };
  parent.startDate = Object.assign(date("2026-10-05T11:00:00Z"), { timezone });
  parent.endDate = Object.assign(date("2026-10-05T12:00:00Z"), { timezone });
  parent.recurrenceInfo = {
    getExceptionFor: () => null,
    getOccurrenceDates: () => [parent.startDate],
    getOccurrenceFor: id => { const item = parent.clone(); item.recurrenceId = id; return item; },
  };
  const request = { command: "item", source_id: "unselected", kind: "event", uid: "uid",
    selection: eventSelection, scope: "occurrence", recurrence_id: "2026-10-05T03:00:00.000Z" };
  const current = await execute(request);
  assert.equal(current.item.recurrence_id, request.recurrence_id);
  assert.equal(current.item.start, "2026-10-05T03:00:00.000Z");
});

test("provider write failures remain actionable and invitations cannot be edited", async () => {
  const { execute, sources } = fixture();
  sources[0].writeFailure = true;
  await assert.rejects(execute(taskRequest("create", { title: "Test" })), /Provider write failed/);
  const item = sources[0].item;
  item.attendees.push({ id: "mailto:guest@example.invalid" });
  const current = await execute(taskRequest("item"));
  await assert.rejects(execute({ ...taskRequest("update", { title: "Test" }), revision: current.item.revision }), /invitations/);
});
