// Isolated editor regression: Node/vm only; no browser, HTTP, owner data or dependencies.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');

const source = fs.readFileSync(path.join(__dirname, '../web/app.js'), 'utf8');
const bootstrap = '  sel = null; view = null;';
assert.equal(source.split(bootstrap).length, 2, 'unique bootstrap boundary');

function editor(timezone) {
  const controls = {};
  const submit = { disabled: false, textContent: '' };
  const noop = () => {};
  const form = {
    querySelectorAll: () => [], querySelector: () => submit, addEventListener: noop,
  };
  const sheet = {
    addEventListener: noop, setAttribute: noop, removeAttribute: noop,
    set innerHTML(html) {
      // Only parse the input values emitted by the actual editor, not its date logic.
      for (const match of html.matchAll(/<input\b([^>]+)>/g)) {
        const attrs = match[1];
        const name = /\bname="([^"]+)"/.exec(attrs)?.[1];
        if (!name) continue;
        controls[name] = form[name] = {
          value: /\bvalue="([^"]*)"/.exec(attrs)?.[1] || '',
          checked: /\bchecked\b/.test(attrs), addEventListener: noop,
        };
      }
      form.description = { value: '' };
    },
  };
  const nodes = new Map([['[data-sheet]', sheet], ['[data-form]', form]]);
  const node = (selector) => {
    if (!nodes.has(selector)) nodes.set(selector, {
      addEventListener: noop, setAttribute: noop, removeAttribute: noop,
    });
    return nodes.get(selector);
  };
  const calls = [];
  const WizardApp = { ready: noop, back: { push: () => ({ release: noop }) } };
  const context = vm.createContext({
    URL, Intl, location: { href: 'https://calendar.example/wizard-calendar/' },
    localStorage: { getItem: () => null },
    document: { querySelector: node, querySelectorAll: () => [], addEventListener: noop },
    window: { WizardApp }, WizardApp,
    fetch: async (url, options) => {
      calls.push({ url, body: JSON.parse(options.body) });
      return { ok: true, json: async () => ({ updated: true }) };
    },
    setTimeout: () => { throw new Error('Unexpected timer'); },
    setInterval: () => { throw new Error('Unexpected interval'); },
  });
  // Keep all editor/render/save functions intact. Skip only startup load, timers and
  // theme subscriptions; expose closure state in this test VM, never in production.
  const hook = `  globalThis.editor = { openForm, save, setup(data, zone) { doc = data; TZ = zone; } };
  load = async () => {}; // save's refresh is outside this isolated editor test
  return;
`;
  vm.runInContext(source.replace(bootstrap, hook + bootstrap), context, { filename: 'web/app.js' });
  context.editor.setup({ calendars: [{ id: 'synthetic-calendar', name: 'Synthetic calendar', live: true }] }, timezone);
  return { api: context.editor, form, controls, calls };
}

const cases = [
  { name: 'UTC timed midnight retains the next date', timezone: 'UTC', allDay: false,
    start: '2026-11-02T23:00:00Z', end: '2026-11-03T00:00:00Z',
    day: '2026-11-02', endDay: '2026-11-03', startTime: '23:00', endTime: '00:00' },
  { name: 'local timed midnight retains the next date (positive offset)', timezone: 'Asia/Bangkok', allDay: false,
    start: '2026-11-02T23:00:00+07:00', end: '2026-11-03T00:00:00+07:00',
    day: '2026-11-02', endDay: '2026-11-03', startTime: '23:00', endTime: '00:00' },
  { name: 'local timed midnight retains the next date (negative offset)', timezone: 'America/New_York', allDay: false,
    start: '2026-11-02T23:00:00-05:00', end: '2026-11-03T00:00:00-05:00',
    day: '2026-11-02', endDay: '2026-11-03', startTime: '23:00', endTime: '00:00' },
  { name: 'timed non-midnight end stays unchanged', timezone: 'UTC', allDay: false,
    start: '2026-11-02T09:00:00Z', end: '2026-11-02T10:00:00Z',
    day: '2026-11-02', endDay: '2026-11-02', startTime: '09:00', endTime: '10:00' },
  { name: 'single all-day exclusive end becomes inclusive only in the form', timezone: 'UTC', allDay: true,
    start: '2026-11-02', end: '2026-11-03', day: '2026-11-02', endDay: '2026-11-02' },
  { name: 'multi-day exclusive end becomes inclusive only in the form', timezone: 'Asia/Bangkok', allDay: true,
    start: '2026-11-02', end: '2026-11-05', day: '2026-11-02', endDay: '2026-11-04' },
];

for (const sample of cases) test(sample.name, async () => {
  const { api, form, controls, calls } = editor(sample.timezone);
  const event = { id: 'synthetic-event', cal: 'synthetic-calendar', title: 'Synthetic event',
    start: sample.start, end: sample.end, allDay: sample.allDay,
    live: { account: 'live:google:synthetic@example.com', calendar_id: 'primary', id: 'synthetic-event' } };
  api.openForm(event);
  assert.equal(controls.day.value, sample.day);
  assert.equal(controls.endDay.value, sample.endDay, 'editor must use actual timed end, not end minus 1ms');
  assert.equal(controls.allDay.checked, sample.allDay);
  if (!sample.allDay) {
    assert.equal(controls.start.value, sample.startTime);
    assert.equal(controls.end.value, sample.endTime);
  }
  await api.save(form, event);
  assert.equal(calls.length, 1, 'unchanged event must save');
  assert.equal(calls[0].url, '/wizard-calendar/api/live/update');
  assert.equal(calls[0].body.start, sample.allDay ? sample.start : `${sample.day}T${sample.startTime}`);
  assert.equal(calls[0].body.end, sample.allDay ? sample.end : `${sample.endDay}T${sample.endTime}`);
  if (!sample.allDay) assert.equal(calls[0].body.time_zone, sample.timezone);
});
