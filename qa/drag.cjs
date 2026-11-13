/* Drag to move and resize (issue 19, switch drag-events, off by default).
 * - Off: events carry no drag classes and a drag changes nothing.
 * - On: an all-day bar moves between days; a timed event moves in 15-minute steps and across Week's day columns, and
 *   its bottom edge resizes it; each drop saves through api/live/update (same account and calendar as the editor) and
 *   offers Undo, which saves the old times back. A repeating event asks "This event" or "All events" (issue 33: a
 *   same-day move of a series the source names shifts every repeat; Undo shifts back). An invite you didn't
 *   organise doesn't move (not-allowed cursor). Esc cancels a drag. Touch: a short hold, then drag.
 * Run against qa/live_fake.py (loopback dev mode, WIZARD_CORE_DIR=.runtime/core):
 *   CALENDAR_LIVE_URL=<qa/live_fake.py> node qa/drag.cjs */
const {chromium} = require('playwright');
const path = require('node:path'), assert = require('node:assert/strict');
const base = process.env.CALENDAR_LIVE_URL || 'http://127.0.0.1:18930';
const shots = process.env.SHOTS_DIR || '';
const G = (n) => `live:google:me@gmail.com|primary|google-${n}`;
const sel = (id) => `[data-ev="${id}"]`;
(async () => {
  const browserPath = process.env.BROWSER_PATH;
  const browser = await chromium.launch(browserPath ? {headless:true, executablePath:browserPath} : {headless:true, channel:process.env.BROWSER_CHANNEL || 'chrome'});
  const checks = [], errors = [];
  const shot = async (page, name) => { if (shots) await page.screenshot({path: path.join(shots, name + '.png')}); };
  const setSwitch = (ctx, on) => ctx.request.post(base+'/api/switches', {headers:{'X-Wizard-Switch':'1', Origin:base}, data:{id:'drag-events', on}});
  try {
    const context = await browser.newContext({viewport:{width:1280, height:900}});
    await context.clock.setFixedTime(new Date('2026-11-04T10:00:00+07:00'));
    const updates = [];
    const page = await context.newPage();
    page.on('pageerror', e => errors.push(String(e)));
    page.on('request', (r) => { if (r.method() === 'POST' && r.url().endsWith('/api/live/update')) updates.push(r.postDataJSON()); });
    const open = async () => {
      await page.goto(base+'/');
      await page.waitForFunction(() => /visible events/.test(document.querySelector('[data-status]').textContent));
      await page.locator('[data-mode="week"]').click();
      await page.waitForSelector(sel(G(1)));
    };
    const toastSays = (re) => page.waitForFunction((src) => { const b = document.querySelector('[data-undo]'); return b && !b.hidden && new RegExp(src).test(b.textContent); }, re.source);
    // The page re-renders after each save (load), so wait for the event to settle before measuring it.
    const box = async (s) => { let b = null; for (let i = 0; i < 20 && !b; i++) { await page.waitForTimeout(i ? 100 : 0); b = await page.locator(s).first().boundingBox().catch(() => null); } assert.ok(b, s); return b; };
    const hour = () => page.evaluate(() => parseFloat(getComputedStyle(document.querySelector('[data-time]')).getPropertyValue('--hour')));
    const colWidth = async () => (await box('[data-tin] .col')).width;
    const drag = async (s, dx, dy, opts = {}) => {
      const b = await box(s), x = b.x + b.width / 2, y = opts.edge ? b.y + b.height - 1.5 : b.y + Math.min(4, b.height / 3);
      await page.mouse.move(x, y); await page.mouse.down();
      for (let i = 1; i <= 6; i++) await page.mouse.move(x + dx * i / 6, y + dy * i / 6);
      if (opts.during) await opts.during();
      await page.mouse.up();
    };

    // ---- switch off (the default) ----
    assert.equal((await setSwitch(context, false)).status(), 200);
    await open();
    assert.equal(await page.locator('.dz, .nodrag, .rsz').count(), 0, 'no drag affordances while the switch is off');
    await drag(sel(G(3)), 140, 0);
    await page.waitForTimeout(300);
    assert.equal(updates.length, 0, 'switch off: a drag saves nothing');
    checks.push('switch off: no drag handles, a drag changes nothing');
    if (await page.locator('[data-sheet]').isVisible()) { await page.evaluate(() => history.back()); await page.waitForFunction(() => document.querySelector('[data-sheet]').hidden); }

    // ---- switch on ----
    assert.equal((await setSwitch(context, true)).status(), 200);
    await open();
    assert.ok(await page.locator(`${sel(G(1))}.dz`).count(), 'an event you organise is draggable');
    assert.ok(await page.locator(`${sel(G(2))}.nodrag`).count(), "an invite you didn't organise is not");
    assert.ok(await page.locator(`${sel(G(1))} .rsz`).count(), 'a resize handle on the bottom edge');
    const cw = await colWidth(), H = await hour();

    // All-day: Trip (Fri 6 – Sat 7) one day later.
    await drag(sel(G(3)), cw, 0);
    await page.waitForSelector('[data-undo]:not([hidden])');
    assert.deepEqual(updates.at(-1), {account:'live:google:me@gmail.com', calendar_id:'primary', id:'google-3', start:'2026-11-07', end:'2026-11-09'});
    assert.equal(await page.locator('[data-sheet]').isVisible(), false, 'dropping does not open the event');
    assert.match(await page.locator('[data-undo]').textContent(), /Event moved\s*Undo/);
    await shot(page, 'drag-undo');
    checks.push('all-day bar dragged one day: saves 7–9 Nov through api/live/update, shows Undo');
    const nu = updates.length;
    await page.locator('[data-undo-btn]').click();
    await page.waitForFunction(() => document.querySelector('[data-undo]').hidden);
    for (let i = 0; i < 40 && updates.length === nu; i++) await page.waitForTimeout(50);
    await page.waitForLoadState('networkidle');
    assert.deepEqual(updates.at(-1), {account:'live:google:me@gmail.com', calendar_id:'primary', id:'google-3', start:'2026-11-06', end:'2026-11-08'});
    checks.push('Undo saves the old dates back');

    // Invite you didn't organise: not-allowed cursor, nothing saved, nothing opened.
    const before = updates.length;
    let cursor = '';
    await drag(sel(G(2)), 0, H, {during: async () => { cursor = await page.evaluate(() => document.documentElement.classList.contains('wc-nodrop') && getComputedStyle(document.querySelector('.blk')).cursor); }});
    await page.waitForTimeout(300);
    assert.equal(cursor, 'not-allowed');
    assert.equal(updates.length, before, 'an invite does not move');
    assert.equal(await page.locator('[data-sheet]').isVisible(), false);
    checks.push("an invite you didn't organise shows a not-allowed cursor and doesn't move");

    // Esc during a drag cancels it.
    let ghost = '';
    await page.mouse.move(0, 0);
    {
      const b = await box(sel(G(1))), x = b.x + b.width / 2, y = b.y + 4;
      await page.mouse.move(x, y); await page.mouse.down();
      for (let i = 1; i <= 6; i++) await page.mouse.move(x + cw * i / 6, y + H * i / 6);
      ghost = await page.locator('.blk.ghost').textContent();
      await shot(page, 'drag-ghost');
      await page.keyboard.press('Escape');
      assert.equal(await page.locator('.blk.ghost').count(), 0, 'Esc removes the ghost');
      await page.mouse.up();
    }
    await page.waitForTimeout(300);
    assert.equal(updates.length, before, 'Esc: nothing saved');
    assert.equal(await page.locator('[data-sheet]').isVisible(), false);
    assert.match(ghost, /Standup\s*10:00–10:15/, `ghost preview shows the new time: ${ghost}`);
    checks.push('ghost preview shows the new start and end (10:00–10:15); Esc cancels the drag');

    // Repeating timed event: one hour later and one day later (Week) -> asks first, then saves this event.
    await drag(sel(G(1)), cw, H + 1);
    await page.waitForSelector('[data-repeat-ask]');
    assert.equal(await page.locator('[data-repeat="one"]').textContent(), 'This event');
    assert.equal(await page.locator('[data-repeat="all"]').isDisabled(), true, 'a move to another day: All events stays off');
    assert.match(await page.locator('[data-repeat-ask]').textContent(), /same day/);
    await shot(page, 'drag-repeat');
    assert.equal(updates.length, before, 'nothing saved before the answer');
    await page.evaluate(() => { document.querySelector('[data-undo]').hidden = true; });
    await page.locator('[data-repeat="one"]').click();
    await toastSays(/Event moved/);
    assert.deepEqual(updates.at(-1), {account:'live:google:me@gmail.com', calendar_id:'primary', id:'google-1', start:'2026-11-03T10:00', end:'2026-11-03T10:15', time_zone:'Asia/Bangkok'});
    checks.push('repeating event moved a day and an hour: asks This event, then saves 3 Nov 10:00–10:15 (Asia/Bangkok)');

    // Cancel on the repeat question keeps it where it was.
    const n2 = updates.length;
    await drag(sel(G(1)), 0, H);
    await page.waitForSelector('[data-repeat-ask]');
    await page.locator('[data-repeat="cancel"]').click();
    await page.waitForTimeout(300);
    assert.equal(updates.length, n2);
    // Esc on the question (or Back, or ✕) is Cancel too: the ghost goes, nothing saved.
    await drag(sel(G(1)), 0, H);
    await page.waitForSelector('[data-repeat-ask]');
    await page.keyboard.press('Escape');
    await page.waitForFunction(() => document.querySelector('[data-sheet]').hidden && !document.querySelector('.blk.ghost'));
    assert.equal(updates.length, n2);
    checks.push('Cancel (or Esc) on the repeat question saves nothing and drops the ghost');

    // All events (issue 33): a same-day move of a repeat whose source names the series moves every repeat by the same
    // minutes (contract 1.5 scope series); Undo shifts them back.
    const series = (s, e) => ({account:'live:google:me@gmail.com', calendar_id:'primary', id:'google-standup', scope:'series', shift_start_minutes:s, shift_end_minutes:e});
    await drag(sel(G(1)), 0, H + 1);
    await page.waitForSelector('[data-repeat-ask]');
    assert.equal(await page.locator('[data-repeat="all"]').isDisabled(), false, 'All events is offered for a same-day move');
    assert.match(await page.locator('[data-repeat-ask]').textContent(), /Every repeat moves by the same amount/);
    await shot(page, 'drag-repeat-all');
    await page.evaluate(() => { document.querySelector('[data-undo]').hidden = true; });
    await page.locator('[data-repeat="all"]').click();
    await toastSays(/Every repeat moved/);
    assert.deepEqual(updates.at(-1), series(60, 60));
    await shot(page, 'drag-repeat-all-undo');
    const sent = updates.length;
    await page.locator('[data-undo-btn]').click();
    for (let i = 0; i < 40 && updates.length === sent; i++) await page.waitForTimeout(100);
    assert.deepEqual(updates.at(-1), series(-60, -60), 'Undo shifts every repeat back');
    checks.push('All events on a same-day move: sends scope series +60/+60 on google-standup; Undo sends -60/-60');
    // Resize with All events: only the end moves.
    await drag(sel(G(1)), 0, H / 2 + 2, {edge:true});
    await page.waitForSelector('[data-repeat-ask]');
    await page.evaluate(() => { document.querySelector('[data-undo]').hidden = true; });
    await page.locator('[data-repeat="all"]').click();
    await toastSays(/Every repeat resized/);
    assert.deepEqual(updates.at(-1), series(0, 30));
    checks.push('All events on a resize: shift_end_minutes 30 only (Every repeat resized)');
    // A source from before 1.5 (no series_id): All events stays off and says why.
    const M1 = sel('live:microsoft:me@outlook.com|primary|microsoft-1');
    await drag(M1, 0, H + 1);
    await page.waitForSelector('[data-repeat-ask]');
    assert.equal(await page.locator('[data-repeat="all"]').isDisabled(), true, 'no series id: All events disabled');
    assert.match(await page.locator('[data-repeat-ask]').textContent(), /newer Google or Microsoft app/);
    await page.locator('[data-repeat="cancel"]').click();
    checks.push('repeat from a source without series_id: All events disabled with a note; day change also keeps it disabled');

    // Resize: drag the bottom edge half an hour down (snaps to 15 minutes).
    await drag(sel(G(1)), 0, H / 2 + 2, {edge:true});
    await page.waitForSelector('[data-repeat-ask]');
    await page.evaluate(() => { document.querySelector('[data-undo]').hidden = true; });
    await page.locator('[data-repeat="one"]').click();
    await toastSays(/Event resized/);
    assert.deepEqual(updates.at(-1), {account:'live:google:me@gmail.com', calendar_id:'primary', id:'google-1', start:'2026-11-02T09:00', end:'2026-11-02T09:45', time_zone:'Asia/Bangkok'});
    checks.push('bottom edge dragged 30 min: saves 09:00–09:45 (Event resized, Undo)');

    // A plain click still opens the event.
    await page.locator(sel(G(3))).first().click();
    await page.waitForSelector('[data-sheet] [data-edit]');
    checks.push('a click without dragging still opens the event');
    await context.close();

    // ---- touch: hold, then drag (phone) ----
    const phone = await browser.newContext({viewport:{width:390, height:844}, hasTouch:true, isMobile:true});
    await phone.clock.setFixedTime(new Date('2026-11-04T10:00:00+07:00'));
    const p2 = await phone.newPage();
    const tUpdates = [];
    p2.on('pageerror', e => errors.push(String(e)));
    p2.on('request', (r) => { if (r.method() === 'POST' && r.url().endsWith('/api/live/update')) tUpdates.push(r.postDataJSON()); });
    await p2.goto(base+'/');
    await p2.waitForFunction(() => /visible events/.test(document.querySelector('[data-status]').textContent));
    await p2.locator('[data-mode="day"]').click();
    await p2.locator('[data-prev]').click(); await p2.locator('[data-prev]').click(); // Mon 2 Nov
    await p2.waitForSelector(sel(G(1)));
    const cdp = await phone.newCDPSession(p2);
    const tb = await p2.locator(sel(G(1))).first().boundingBox(), H2 = await p2.evaluate(() => parseFloat(getComputedStyle(document.querySelector('[data-time]')).getPropertyValue('--hour')));
    const tx = tb.x + 30, ty = tb.y + 4;
    await cdp.send('Input.dispatchTouchEvent', {type:'touchStart', touchPoints:[{x:tx, y:ty}]});
    await p2.waitForTimeout(600);
    for (let i = 1; i <= 6; i++) await cdp.send('Input.dispatchTouchEvent', {type:'touchMove', touchPoints:[{x:tx, y:ty + 2 * H2 * i / 6}]});
    await cdp.send('Input.dispatchTouchEvent', {type:'touchEnd', touchPoints:[]});
    await p2.waitForSelector('[data-repeat-ask]');
    await p2.locator('[data-repeat="one"]').click();
    await p2.waitForSelector('[data-undo]:not([hidden])');
    assert.deepEqual(tUpdates.at(-1), {account:'live:google:me@gmail.com', calendar_id:'primary', id:'google-1', start:'2026-11-02T11:00', end:'2026-11-02T11:15', time_zone:'Asia/Bangkok'});
    await shot(p2, 'drag-phone-undo');
    checks.push('touch: hold then drag two hours down in Day saves 11:00–11:15');
    await phone.close();

    // ---- touch on a phone, more (issue 19 kick-back: "not mobile friendly") ----
    // A two-hour event (Focus, Mon 2 Nov 14:00–16:00) is added to what the page loads, so a finger has room to work.
    const phone2 = await browser.newContext({viewport:{width:390, height:844}, hasTouch:true, isMobile:true});
    await phone2.clock.setFixedTime(new Date('2026-11-04T10:00:00+07:00'));
    const p3 = await phone2.newPage();
    const u3 = [];
    p3.on('pageerror', e => errors.push(String(e)));
    p3.on('request', (r) => { if (r.method() === 'POST' && r.url().endsWith('/api/live/update')) u3.push(r.postDataJSON()); });
    await p3.route(/\/api\/events\?/, async (route) => {
      const res = await route.fetch(), d = await res.json();
      d.events.push({id: G(9), cal: 'live:google:me@gmail.com', title: 'Focus', start: '2026-11-02T14:00:00+07:00', end: '2026-11-02T16:00:00+07:00',
        allDay: false, location: '', description: '', guests: '', meet: '', link: '',
        live: {account: 'live:google:me@gmail.com', calendar_id: 'primary', id: 'google-9', is_organizer: true, my_response: 'organizer',
          invited: false, recurring: false, time_zone: 'Asia/Bangkok', by_agent: false}});
      await route.fulfill({response: res, json: d});
    });
    await p3.goto(base+'/');
    await p3.waitForFunction(() => /visible events/.test(document.querySelector('[data-status]').textContent));
    await p3.locator('[data-mode="day"]').click();
    await p3.locator('[data-prev]').click(); await p3.locator('[data-prev]').click(); // Mon 2 Nov
    await p3.waitForSelector(sel(G(9)));
    const c3 = await phone2.newCDPSession(p3);
    const H3 = await p3.evaluate(() => parseFloat(getComputedStyle(document.querySelector('[data-time]')).getPropertyValue('--hour')));
    const tbox = async () => { await p3.locator(sel(G(9))).first().scrollIntoViewIfNeeded(); await p3.waitForTimeout(150); return p3.locator(sel(G(9))).first().boundingBox(); };
    const touch = async (x, y, moves, {hold = 600, pause = 0} = {}) => {
      await c3.send('Input.dispatchTouchEvent', {type:'touchStart', touchPoints:[{x, y}]});
      if (hold) await p3.waitForTimeout(hold);
      for (const [mx, my] of moves) await c3.send('Input.dispatchTouchEvent', {type:'touchMove', touchPoints:[{x: mx, y: my}]});
      if (pause) await p3.waitForTimeout(pause);
      await c3.send('Input.dispatchTouchEvent', {type:'touchEnd', touchPoints:[]});
    };
    const steps = (x, y, dx, dy, n = 8) => [...Array(n)].map((_, i) => [x + dx * (i + 1) / n, y + dy * (i + 1) / n]);

    // A quick sideways swipe that starts on an event (no hold) still turns the day and moves nothing.
    let fb = await tbox();
    const dayLabel = () => p3.locator('[data-time] .dhd.sel').first().textContent();
    const d0 = await dayLabel();
    await touch(fb.x + 150, fb.y + fb.height / 2, steps(fb.x + 150, fb.y + fb.height / 2, -150, 0), {hold: 0});
    await p3.waitForFunction((was) => document.querySelector('[data-time] .dhd.sel')?.textContent !== was, d0);
    assert.equal(u3.length, 0, 'a quick swipe saves nothing');
    assert.equal(await p3.locator('[data-sheet]').isVisible(), false, 'a swipe does not open the event');
    assert.match(await p3.locator('[data-status]').textContent(), /hold it for a moment, then drag/, 'a quick drag on an event says to hold first');
    await p3.locator('[data-prev]').click();
    await p3.waitForFunction((was) => document.querySelector('[data-time] .dhd.sel')?.textContent === was, d0);
    checks.push('touch: a quick swipe starting on an event still turns the day, saves nothing and says to hold first');

    // A tap still opens the event.
    fb = await tbox();
    await touch(fb.x + 30, fb.y + fb.height / 2, [], {hold: 0});
    await p3.waitForSelector('[data-sheet] [data-edit]');
    assert.equal(u3.length, 0);
    await p3.evaluate(() => history.back()); await p3.waitForFunction(() => document.querySelector('[data-sheet]').hidden);
    checks.push('touch: a tap still opens the event');

    // Hold the lower edge (a finger-sized band) and drag down an hour: resized to 14:00–17:00.
    fb = await tbox();
    const ey = fb.y + fb.height - 6;
    assert.ok(await p3.evaluate(() => matchMedia('(pointer: coarse)').matches), 'phone context is a coarse pointer');
    await touch(fb.x + 30, ey, steps(fb.x + 30, ey, 0, H3));
    await p3.waitForSelector('[data-undo]:not([hidden])');
    assert.deepEqual(u3.at(-1), {account:'live:google:me@gmail.com', calendar_id:'primary', id:'google-9', start:'2026-11-02T14:00', end:'2026-11-02T17:00', time_zone:'Asia/Bangkok'});
    assert.equal(await p3.locator('[data-sheet]').isVisible(), false, 'dropping does not open the event');
    checks.push('touch: hold the lower edge and drag an hour down resizes to 14:00–17:00');

    await shot(p3, 'drag-phone-resize');

    // The screen changes size mid-drag (the browser's address bar slides away, the phone turns): the grid redraws only
    // after the drop, so the drag under the finger carries on and saves.
    await p3.waitForSelector('[data-undo]', {state: 'hidden', timeout: 10000}).catch(() => {});
    fb = await tbox();
    const n3 = u3.length, my = fb.y + 6;
    await c3.send('Input.dispatchTouchEvent', {type:'touchStart', touchPoints:[{x: fb.x + 30, y: my}]});
    await p3.waitForTimeout(600);
    for (const [mx, mmy] of steps(fb.x + 30, my, 0, -H3, 4)) await c3.send('Input.dispatchTouchEvent', {type:'touchMove', touchPoints:[{x: mx, y: mmy}]});
    await p3.setViewportSize({width:390, height:760});
    await p3.waitForTimeout(300);
    for (const [mx, mmy] of steps(fb.x + 30, my - H3, 0, -H3, 4)) await c3.send('Input.dispatchTouchEvent', {type:'touchMove', touchPoints:[{x: mx, y: mmy}]});
    await c3.send('Input.dispatchTouchEvent', {type:'touchEnd', touchPoints:[]});
    await p3.waitForFunction((n) => document.querySelector('[data-undo]') && !document.querySelector('[data-undo]').hidden, n3);
    assert.equal(u3.length, n3 + 1, 'the drag saved once');
    assert.deepEqual(u3.at(-1), {account:'live:google:me@gmail.com', calendar_id:'primary', id:'google-9', start:'2026-11-02T12:00', end:'2026-11-02T14:00', time_zone:'Asia/Bangkok'});
    checks.push('touch: the screen resizing mid-drag does not drop the drag (saves 12:00–14:00)');
    await phone2.close();

    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ok:true, checks}, null, 1));
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exit(1); });
