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
  } : null;
  const source = id => ({
    id, name: id, type: "storage", readOnly: id === "school",
    getProperty: name => name === "color" ? "#88aaff" : null,
    getItemsAsArray: async (filter, count, start, end) => {
      calls.push({ id, filter, count, start, end });
      if (id === "broken") {
        throw new Error("Provider unavailable");
      }
      return [{
        id: "uid", calendar: { id }, title: id === "personal" ? "Undated task" : "Class",
        startDate: date("2026-10-05T03:00:00Z"), endDate: date("2026-10-05T04:00:00Z"),
        recurrenceId: id === "school" ? date("2026-10-05T03:00:00Z") : null,
        getProperty: () => null, getAlarms: () => [],
        isCompleted: false, dueDate: null, entryDate: null,
      }];
    },
  });
  const sources = ["personal", "school", "unselected", "broken"].map(source);
  class ExtensionError extends Error {
    constructor(message) {
      super(message);
      this.name = "ExtensionError";
    }
  }
  const sandbox = {
    ExtensionCommon: {
      ExtensionAPI: class {},
      EventManager: class { api() { return {}; } },
    },
    ChromeUtils: {
      importESModule: path => path.includes("ExtensionUtils") ? { ExtensionError } : { cal: {
        manager: {
          getCalendars: () => sources,
          getCalendarById: id => sources.find(s => s.id === id),
        },
        dtz: { dateTimeToJsDate: d => new Date(d.value), jsDateToDateTime: d => d },
      } },
    },
    Ci: { calICalendar: {
      ITEM_FILTER_TYPE_EVENT: 8, ITEM_FILTER_CLASS_OCCURRENCES: 65536,
      ITEM_FILTER_TYPE_TODO: 4, ITEM_FILTER_COMPLETED_ALL: 3,
    } },
    Services: { io: { offline: false } },
  };
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync("src/dayline/thunderbird/calendar.js", "utf8"), sandbox);
  const calendarExecute = new sandbox.daylineCalendar().getAPI({}).daylineCalendar.execute;
  // Thunderbird's Experiment boundary hides ordinary errors from extensions.
  const execute = async request => {
    try {
      return await calendarExecute(request);
    } catch (error) {
      if (error.name === "ExtensionError") {
        throw error;
      }
      throw new Error("An unexpected error occurred");
    }
  };
  return { execute, calls };
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
