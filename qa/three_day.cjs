/* 3 Day view (issue 47, on for everyone; its switch three-day is gone): the view switcher reads Day, 3 Day, Week, Month.
 * The 3 Day tab sits between Day and Week; it shows three columns starting on the selected day (or today); ‹ › and a
 * sideways swipe move three days; dragging an event to the next column moves it a day; the choice is remembered across
 * a reload. Day and Week keep 1 and 7 columns, and no three-day switch is listed.
 * Run against qa/live_fake.py (loopback dev mode, WIZARD_CORE_DIR=<wizard-ux>/web/core):
 *   CALENDAR_LIVE_URL=<qa/live_fake.py> node qa/three_day.cjs */
const {chromium} = require('playwright');
const path = require('node:path'), assert = require('node:assert/strict');
const base = process.env.CALENDAR_LIVE_URL || 'http://127.0.0.1:18930';
const shots = process.env.SHOTS_DIR || '';
const G = (n) => `live:google:me@gmail.com|primary|google-${n}`;
const sel = (id) => `[data-ev="${id}"]`;
const ev = (n, title, start, end) => ({id: G(n), cal: 'live:google:me@gmail.com', title, start, end, allDay: false, location: '',
  description: '', guests: '', meet: '', link: '', live: {account: 'live:google:me@gmail.com', calendar_id: 'primary', id: `google-${n}`,
    is_organizer: true, my_response: 'organizer', invited: false, recurring: false, time_zone: 'Asia/Bangkok', by_agent: false}});
const EXTRA = [ev(74, 'Lunch', '2026-11-04T12:00:00+07:00', '2026-11-04T13:00:00+07:00')];
(async () => {
  const browserPath = process.env.BROWSER_PATH;
  const browser = await chromium.launch(browserPath ? {headless:true, executablePath:browserPath} : {headless:true, channel:process.env.BROWSER_CHANNEL || 'chrome'});
  const checks = [], errors = [];
  const shot = async (page, name) => { if (shots) { await page.waitForTimeout(300); await page.screenshot({path: path.join(shots, name + '.png')}); } };
  const context = await browser.newContext({viewport: {width: 390, height: 844}, hasTouch: true, isMobile: true});
  await context.clock.setFixedTime(new Date('2026-11-04T10:00:00+07:00')); // a Wednesday
  await context.route(/\/api\/events\?/, async (route) => {
    const res = await route.fetch(), d = await res.json();
    d.events.push(...EXTRA);
    await route.fulfill({response: res, json: d});
  });
  const page = await context.newPage(); page.on('pageerror', (e) => errors.push(String(e)));
  let switchIds = null;
  const open = async () => {
    const sw = page.waitForResponse((r) => /\/api\/switches$/.test(r.url()) && r.request().method() === 'GET');
    await page.goto(base + '/');
    switchIds = ((await (await sw).json()).switches || []).map((x) => x.id);
    await page.waitForFunction(() => /visible events/.test(document.querySelector('[data-status]').textContent));
    await page.waitForTimeout(400); // switches loaded
  };
  const tabs = () => page.$$eval('[data-mode]', (bs) => bs.filter((b) => !b.hidden).map((b) => b.textContent.trim()));
  const cols = () => page.$$eval('[data-tin] .col', (cs) => cs.map((c) => c.dataset.col));
  const heads = () => page.$$eval('[data-heads] .dhd', (hs) => hs.length);
  const mode = () => page.$eval('[data-mode].on', (b) => b.dataset.mode);
  // Every day label sits centred over its own column (Miguel's kick-back: in 3 Day they kept Week's 1/7 widths).
  const aligned = async (what) => {
    const g = await page.evaluate(() => ({
      h: [...document.querySelectorAll('[data-heads] .dhd')].map((e) => { const r = e.getBoundingClientRect(); return [r.left, r.right]; }),
      c: [...document.querySelectorAll('[data-tin] .col')].map((e) => { const r = e.getBoundingClientRect(); return [r.left, r.right]; })}));
    assert.equal(g.h.length, g.c.length, `${what}: one label per column`);
    g.h.forEach(([l, r], i) => {
      const hc = (l + r) / 2, [cl, cr] = g.c[i], cc = (cl + cr) / 2;
      assert.ok(Math.abs(hc - cc) <= 4, `${what}: label ${i + 1} centred over its column (label ${hc.toFixed(0)}, column ${cc.toFixed(0)})`);
      assert.ok(r - l >= (cr - cl) * 0.8, `${what}: label ${i + 1} as wide as its column`);
    });
  };
  try {
    await open();
    assert.ok(!switchIds.includes('three-day'), `no three-day switch listed (${switchIds})`);
    assert.deepEqual(await tabs(), ['Day', '3 Day', 'Week', 'Month'], '3 Day sits between Day and Week, no switch needed');
    await page.locator('[data-mode="week"]').click();
    assert.equal((await cols()).length, 7, 'Week still shows 7 days');
    await aligned('Week');
    await page.locator('[data-mode="day"]').click();
    assert.deepEqual(await cols(), ['2026-11-04'], 'Day still shows one day');
    checks.push('no three-day switch listed; tabs read Day, 3 Day, Week, Month; Day 1 and Week 7 columns as before');

    await page.locator('[data-mode="3day"]').click();
    await page.waitForSelector(sel(G(74)));
    assert.equal(await mode(), '3day');
    assert.deepEqual(await cols(), ['2026-11-04', '2026-11-05', '2026-11-06'], '3 Day starts on the selected day (today)');
    assert.equal(await heads(), 3, 'three day heads');
    await aligned('3 Day');
    checks.push('3 Day: each of the three day labels is centred over its own column (390px phone)');
    await shot(page, 'three-day');
    checks.push('3 Day shows Wed 4 to Fri 6 Nov starting today');

    await page.locator('[data-next-month]').click();
    assert.deepEqual(await cols(), ['2026-11-07', '2026-11-08', '2026-11-09'], '› moves three days');
    assert.equal(await page.getAttribute('[data-next-month]', 'aria-label'), 'Forward 3 days');
    await page.locator('[data-prev]').click();
    await page.locator('[data-prev]').click();
    assert.deepEqual(await cols(), ['2026-11-01', '2026-11-02', '2026-11-03'], '‹ moves back three days');
    assert.equal(await page.locator('[data-step]:not([hidden])').count(), 0, 'no week-jump buttons in 3 Day');
    checks.push('‹ › move three days at a time (labelled Back/Forward 3 days); the week buttons stay hidden');

    // Swipe left on the hours: forward three days.
    const cdp = await context.newCDPSession(page);
    let body = await page.locator('[data-tbody]').boundingBox();
    const sy = body.y + 40;
    await cdp.send('Input.dispatchTouchEvent', {type: 'touchStart', touchPoints: [{x: body.x + 300, y: sy}]});
    for (let i = 1; i <= 8; i++) await cdp.send('Input.dispatchTouchEvent', {type: 'touchMove', touchPoints: [{x: body.x + 300 - 20 * i, y: sy}]});
    await cdp.send('Input.dispatchTouchEvent', {type: 'touchEnd', touchPoints: []});
    await page.waitForFunction(() => document.querySelector('[data-tin] .col')?.dataset.col === '2026-11-04');
    assert.deepEqual(await cols(), ['2026-11-04', '2026-11-05', '2026-11-06'], 'a swipe moves three days');
    checks.push('a sideways swipe moves three days');

    // Month: pick the 20th, then 3 Day starts there.
    await page.locator('[data-mode="month"]').click();
    await page.locator('[data-day="2026-11-20"]').click();
    await page.locator('[data-mode="3day"]').click();
    assert.deepEqual(await cols(), ['2026-11-20', '2026-11-21', '2026-11-22'], '3 Day starts on the day picked in Month');
    await page.locator('[data-today-btn]').click();
    assert.deepEqual((await cols())[0], '2026-11-04', 'Today brings 3 Day back to today');
    checks.push('3 Day starts on the day picked in Month; Today returns to today');

    // Drag Lunch one column to the right: Thursday, same time.
    const updates = [];
    page.on('request', (r) => { if (r.method() === 'POST' && r.url().endsWith('/api/live/update')) updates.push(r.postDataJSON()); });
    await page.locator(sel(G(74))).scrollIntoViewIfNeeded();
    const lb = await page.locator(sel(G(74))).boundingBox(), colW = (await page.locator('[data-tin] .col').first().boundingBox()).width;
    const tx = lb.x + 20, ty = lb.y + 4;
    await cdp.send('Input.dispatchTouchEvent', {type: 'touchStart', touchPoints: [{x: tx, y: ty}]});
    await page.waitForTimeout(600);
    for (let i = 1; i <= 6; i++) await cdp.send('Input.dispatchTouchEvent', {type: 'touchMove', touchPoints: [{x: tx + colW * i / 6, y: ty}]});
    await cdp.send('Input.dispatchTouchEvent', {type: 'touchEnd', touchPoints: []});
    await page.waitForFunction(() => !document.querySelector('[data-undo]')?.hidden);
    assert.deepEqual(updates.at(-1), {account: 'live:google:me@gmail.com', calendar_id: 'primary', id: 'google-74', start: '2026-11-05T12:00', end: '2026-11-05T13:00', time_zone: 'Asia/Bangkok'});
    checks.push('hold-then-drag one column right moves Lunch Wed 12:00 -> Thu 12:00');

    // Remembered across a reload.
    await open();
    await page.waitForFunction(() => document.querySelector('[data-mode].on')?.dataset.mode === '3day');
    assert.equal((await cols()).length, 3);
    checks.push('3 Day is remembered across a reload');

    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ok: true, count: checks.length, checks}, null, 2));
  } catch (e) {
    console.error(e);
    if (shots) await page.screenshot({path: path.join(shots, 'three-day-fail.png')}).catch(() => {});
    console.log(JSON.stringify({ok: false, checks, errors}, null, 2));
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
})();
