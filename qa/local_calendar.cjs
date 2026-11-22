/* The calendar on this Wizard (issue 58, on for everyone), on a phone, with no account:
 * - Fresh install: the Week grid shows (no "Connect your calendar" wall) and + adds an event.
 * - Add a weekly event from +; it shows this week and next week; Month shows it too.
 * - Edit it from a later repeat with "All events": every repeat changes. Delete one repeat with "This event": only
 *   that one goes.
 * - Hold and drag a repeat to another time, "This event": only that one moves.
 * - Settings > This Wizard's calendar: Agents level, .ics import (the events show), .ics export (a file downloads).
 * Run against app/server.py with CALENDAR_LIVE=off CALENDAR_DEV_MODE=loopback-single-owner,
 * WIZARD_CORE_DIR=<wizard-ux>/web/core:
 *   CALENDAR_URL=http://127.0.0.1:<port> node qa/local_calendar.cjs */
const {chromium} = require('playwright');
const fs = require('node:fs'), os = require('node:os'), path = require('node:path'), assert = require('node:assert/strict');
const base = process.env.CALENDAR_URL || 'http://127.0.0.1:18931';
const shots = process.env.SHOTS_DIR || '';
(async () => {
  const browserPath = process.env.BROWSER_PATH;
  const browser = await chromium.launch(browserPath ? {headless: true, executablePath: browserPath} : {headless: true, channel: process.env.BROWSER_CHANNEL || 'chrome'});
  const checks = [], errors = [];
  const shot = async (name) => { if (shots) { await page.waitForTimeout(300); await page.screenshot({path: path.join(shots, name + '.png')}); } };
  const context = await browser.newContext({viewport: {width: 390, height: 844}, hasTouch: true, isMobile: true, acceptDownloads: true, timezoneId: 'Europe/Berlin'});
  await context.clock.setFixedTime(new Date('2026-11-04T10:00:00+01:00')); // a Wednesday
  const page = await context.newPage(); page.on('pageerror', (e) => errors.push(String(e)));
  const open = async () => {
    await page.goto(base + '/');
    await page.waitForFunction(() => /visible events/.test(document.querySelector('[data-status]').textContent));
    await page.waitForTimeout(400);
  };
  const titles = () => page.$$eval('[data-tin] .blk:not(.ghost) b', (bs) => bs.map((b) => b.textContent));
  const answer = async (which) => { await page.waitForSelector('[data-repeat-ask]'); await page.click(`[data-repeat="${which}"]`); };
  const settled = () => page.waitForTimeout(700);

  await open();
  if (await page.$eval('[data-mode="week"]', (b) => !b.classList.contains('on'))) await page.click('[data-mode="week"]');
  assert.equal(await page.$eval('[data-hello]', (h) => h.hidden), true, 'no Connect wall');
  assert.equal(await page.$eval('.tab-new[data-new]', (b) => b.hidden), false, '+ shows');
  checks.push('no account: the Week grid shows and + is there');
  await shot('local-1-empty-week');

  // Add a weekly event from +.
  await page.click('.tab-new[data-new]');
  await page.waitForSelector('[data-form]');
  assert.equal(await page.$eval('[data-form] select[name=cal]', (s) => s.selectedOptions[0].textContent), 'On this Wizard');
  assert.equal(await page.$eval('[data-repeat-field]', (f) => f.hidden), false, 'Repeat shows for this Wizard\'s calendar');
  await page.fill('[data-form] [name=title]', 'Yoga');
  await page.fill('[data-form] [name=day]', '2026-11-05');
  await page.fill('[data-form] [name=endDay]', '2026-11-05');
  await page.fill('[data-form] [name=start]', '18:00');
  await page.fill('[data-form] [name=end]', '19:00');
  await page.fill('[data-form] [name=location]', 'Studio');
  await page.selectOption('[data-form] [name=repeat]', 'weekly');
  await shot('local-2-new-event-form');
  await page.click('[data-form] [type=submit]');
  await page.waitForFunction(() => [...document.querySelectorAll('[data-tin] .blk b')].some((b) => b.textContent === 'Yoga'));
  assert.deepEqual(await page.$eval('[data-tin] .col[data-col="2026-11-05"]', (c) => [...c.querySelectorAll('.blk b')].map((b) => b.textContent)), ['Yoga']);
  checks.push('+ adds a weekly event on a phone: it shows on Thursday');
  await page.click('[data-step="7"]').catch(async () => { await page.click('[data-next-month]'); });
  await settled();
  const wk2 = await page.$$eval('[data-tin] .col', (cs) => cs.map((c) => c.dataset.col));
  assert.ok(wk2.includes('2026-11-12'), wk2.join());
  assert.deepEqual(await page.$eval('[data-tin] .col[data-col="2026-11-12"]', (c) => [...c.querySelectorAll('.blk b')].map((b) => b.textContent)), ['Yoga']);
  checks.push('the repeat shows the next week too');
  await shot('local-3-next-week');

  // Edit from the second repeat, "All events".
  await page.click('[data-tin] .col[data-col="2026-11-12"] .blk');
  await page.waitForSelector('[data-repeats]');
  await shot('local-4-event-sheet');
  await page.click('[data-edit]');
  await page.fill('[data-form] [name=title]', 'Yoga class');
  await page.fill('[data-form] [name=start]', '18:30');
  await page.fill('[data-form] [name=end]', '19:30');
  await page.click('[data-form] [type=submit]');
  await answer('all');
  await page.waitForFunction(() => [...document.querySelectorAll('[data-tin] .blk b')].some((b) => b.textContent === 'Yoga class'));
  const r = await (await page.request.get(base + '/api/events?from=2026-11-01&to=2026-12-01', {headers: {'X-Wizard-Request': 'calendar'}})).json();
  const yoga = r.events.filter((e) => e.cal === 'local');
  assert.ok(yoga.length >= 4 && yoga.every((e) => e.title === 'Yoga class' && e.start.slice(11, 16) === '18:30'), JSON.stringify(yoga.map((e) => [e.title, e.start])));
  checks.push('Edit from a later repeat, All events: every repeat gets the new title and time');

  // Delete this week's repeat only.
  await page.click('[data-tin] .col[data-col="2026-11-12"] .blk');
  await page.click('[data-del]');
  await page.click('[data-del]'); // "Delete for good?"
  await answer('one');
  await settled();
  assert.deepEqual(await page.$eval('[data-tin] .col[data-col="2026-11-12"]', (c) => c.querySelectorAll('.blk').length), 0);
  await page.click('[data-step="7"]');
  await settled();
  assert.deepEqual(await page.$eval('[data-tin] .col[data-col="2026-11-19"]', (c) => [...c.querySelectorAll('.blk b')].map((b) => b.textContent)), ['Yoga class']);
  checks.push('Delete one repeat, This event: that one goes, the next week\'s stays');

  // Hold and drag the 19 Nov repeat one hour later, "This event".
  // 17:00 at the top of the hours, so the drag stays clear of the edge auto-scroll.
  const hour = await page.evaluate(() => parseFloat(getComputedStyle(document.querySelector('[data-time]')).getPropertyValue('--hour')));
  await page.evaluate((h) => { document.querySelector('[data-tbody]').scrollTop = 17 * h; }, hour);
  await page.waitForTimeout(200);
  const box = await (await page.$('[data-tin] .col[data-col="2026-11-19"] .blk')).boundingBox();
  const cdp = await context.newCDPSession(page);
  const x = box.x + box.width / 2, y = box.y + 8;
  await cdp.send('Input.dispatchTouchEvent', {type: 'touchStart', touchPoints: [{x, y}]});
  await page.waitForTimeout(450);
  for (let i = 1; i <= 6; i++) { await cdp.send('Input.dispatchTouchEvent', {type: 'touchMove', touchPoints: [{x, y: y + hour * i / 6}]}); await page.waitForTimeout(30); }
  await cdp.send('Input.dispatchTouchEvent', {type: 'touchEnd', touchPoints: []});
  await answer('one');
  await settled();
  const r2 = await (await page.request.get(base + '/api/events?from=2026-11-01&to=2026-12-01', {headers: {'X-Wizard-Request': 'calendar'}})).json();
  const starts = r2.events.filter((e) => e.cal === 'local').map((e) => e.start.slice(0, 16));
  assert.ok(starts.includes('2026-11-19T19:30') && starts.includes('2026-11-26T18:30') && starts.includes('2026-11-05T18:30'), starts.join());
  checks.push('hold and drag one repeat an hour later, This event: only that one moves');
  await shot('local-5-dragged');

  // Month shows the events.
  await page.click('[data-mode="month"]');
  await settled();
  assert.ok(await page.$eval('[data-day="2026-11-26"]', (d) => d.querySelectorAll('.dots i').length) >= 1);
  checks.push('Month view shows the repeats');
  await shot('local-6-month');

  // Settings: agents level, .ics import and export.
  await page.click('.bar [data-cals]');
  await page.waitForSelector('[data-local-level]');
  assert.equal(await page.$eval('[data-local-level]', (s) => s.value), 'read_only');
  await page.selectOption('[data-local-level]', 'can_edit');
  await page.waitForFunction(() => /Agents: Can edit/.test(document.querySelector('[data-c-msg]')?.textContent || ''));
  checks.push('Settings > This Wizard\'s calendar: Agents set to Can edit');
  const ics = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'cal-ics-')), 'dentist.ics');
  fs.writeFileSync(ics, 'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:dentist@example.com\r\nDTSTART;TZID=Europe/Berlin:20261127T090000\r\nDTEND;TZID=Europe/Berlin:20261127T100000\r\nSUMMARY:Dentist\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n');
  await page.setInputFiles('[data-local-import]', ics);
  await page.waitForFunction(() => /Imported 1 event/.test(document.querySelector('[data-c-msg]')?.textContent || ''));
  checks.push('.ics import from Settings: "Imported 1 event"');
  await shot('local-7-settings');
  const [dl] = await Promise.all([page.waitForEvent('download'), page.click('[data-local-export]')]);
  const text = fs.readFileSync(await dl.path(), 'utf8');
  assert.ok(text.includes('SUMMARY:Dentist') && text.includes('SUMMARY:Yoga class') && text.includes('RRULE:FREQ=WEEKLY'), text);
  checks.push('Export .ics downloads calendar.ics with the events');
  await page.click('[data-sheet] [data-close]');
  await page.click('[data-day="2026-11-27"]');
  await settled();
  assert.ok(await page.$$eval('[data-agenda] .ev b', (bs) => bs.some((b) => b.textContent === 'Dentist')));
  checks.push('the imported event shows in the calendar');

  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ok: true, count: checks.length, checks}, null, 2));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
