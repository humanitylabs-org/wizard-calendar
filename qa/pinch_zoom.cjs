/* Pinch to zoom the hours (switch pinch-zoom, issue 43; like Google Calendar).
 * - Switch off: a two-finger pinch changes nothing (48 px hours as before).
 * - Switch on: pinching out in Week makes the hours taller, pinching in shorter, within 0.5x..3x of 48 px and never
 *   shorter than a grid that fills the window; the time between the fingers stays under them.
 * - The level is shared by Day and Week and survives a reload.
 * - One finger still swipes the day, and hold-then-drag still moves an event to the right time at the zoomed size.
 * - Desktop: Ctrl + wheel (Chrome's trackpad pinch) zooms the same way.
 * Run against qa/live_fake.py (loopback dev mode, WIZARD_CORE_DIR=<wizard-ux>/web/core):
 *   CALENDAR_LIVE_URL=<qa/live_fake.py> node qa/pinch_zoom.cjs */
const {chromium} = require('playwright');
const path = require('node:path'), assert = require('node:assert/strict');
const base = process.env.CALENDAR_LIVE_URL || 'http://127.0.0.1:18930';
const shots = process.env.SHOTS_DIR || '';
const G = (n) => `live:google:me@gmail.com|primary|google-${n}`;
const sel = (id) => `[data-ev="${id}"]`;
const ev = (n, title, start, end) => ({id: G(n), cal: 'live:google:me@gmail.com', title, start, end, allDay: false, location: '',
  description: '', guests: '', meet: '', link: '', live: {account: 'live:google:me@gmail.com', calendar_id: 'primary', id: `google-${n}`,
    is_organizer: true, my_response: 'organizer', invited: false, recurring: false, time_zone: 'Asia/Bangkok', by_agent: false}});
const EXTRA = [ev(73, 'Lunch', '2026-11-04T12:00:00+07:00', '2026-11-04T13:00:00+07:00')];
(async () => {
  const browserPath = process.env.BROWSER_PATH;
  const browser = await chromium.launch(browserPath ? {headless:true, executablePath:browserPath} : {headless:true, channel:process.env.BROWSER_CHANNEL || 'chrome'});
  const checks = [], errors = [];
  const shot = async (page, name) => { if (shots) { await page.waitForTimeout(300); await page.screenshot({path: path.join(shots, name + '.png')}); } };
  const openContext = async (opts, on) => {
    const context = await browser.newContext(opts);
    await context.clock.setFixedTime(new Date('2026-11-04T10:00:00+07:00'));
    // The owner's switch state, as the box would serve it.
    await context.route(/\/api\/switches$/, async (route) => {
      if (route.request().method() !== 'GET') return route.continue();
      const res = await route.fetch(), d = await res.json();
      for (const s of d.switches) if (s.id === 'pinch-zoom') s.on = on;
      await route.fulfill({response: res, json: d});
    });
    await context.route(/\/api\/events\?/, async (route) => {
      const res = await route.fetch(), d = await res.json();
      d.events.push(...EXTRA);
      await route.fulfill({response: res, json: d});
    });
    return context;
  };
  const ready = async (page, m = 'week') => {
    await page.goto(base + '/');
    await page.waitForFunction(() => /visible events/.test(document.querySelector('[data-status]').textContent));
    await page.locator(`[data-mode="${m}"]`).click();
    await page.waitForSelector(sel(G(73)));
    await page.waitForTimeout(300); // switches loaded
  };
  const hour = (page) => page.evaluate(() => parseFloat(getComputedStyle(document.querySelector('[data-time]')).getPropertyValue('--hour')));
  // Minutes since 00:00 at screen height y.
  const minsAt = (page, y) => page.evaluate((y) => {
    const tin = document.querySelector('[data-tin]'), h = parseFloat(getComputedStyle(document.querySelector('[data-time]')).getPropertyValue('--hour'));
    return (y - tin.getBoundingClientRect().top) / h * 60;
  }, y);
  // Two fingers at x, centred on y, from gap d0 to gap d1 (vertical), in n steps.
  const pinch = async (cdp, x, y, d0, d1, n = 10) => {
    const pts = (d) => [{x, y: y - d / 2, id: 1}, {x: x + 20, y: y + d / 2, id: 2}];
    await cdp.send('Input.dispatchTouchEvent', {type: 'touchStart', touchPoints: [pts(d0)[0]]});
    await cdp.send('Input.dispatchTouchEvent', {type: 'touchStart', touchPoints: pts(d0)});
    for (let i = 1; i <= n; i++) {
      await cdp.send('Input.dispatchTouchEvent', {type: 'touchMove', touchPoints: pts(d0 + (d1 - d0) * i / n)});
      await new Promise((r) => setTimeout(r, 20));
    }
    await cdp.send('Input.dispatchTouchEvent', {type: 'touchEnd', touchPoints: [pts(d1)[0]]});
    await cdp.send('Input.dispatchTouchEvent', {type: 'touchEnd', touchPoints: []});
  };
  const phone = {viewport: {width: 390, height: 844}, hasTouch: true, isMobile: true};
  try {
    // ---- switch off: nothing changes ----
    let ctx = await openContext(phone, false);
    let page = await ctx.newPage(); page.on('pageerror', (e) => errors.push(String(e)));
    await ready(page);
    let cdp = await ctx.newCDPSession(page);
    let body = await page.locator('[data-tbody]').boundingBox();
    await pinch(cdp, body.x + 150, body.y + body.height / 2, 100, 250);
    await page.waitForTimeout(200);
    assert.equal(await hour(page), 48, 'switch off: a pinch leaves the 48 px hours alone');
    assert.equal(await page.evaluate(() => localStorage.getItem('wc.zoom')), null);
    checks.push('switch off: a two-finger pinch changes nothing (48 px hours)');
    await ctx.close();

    // ---- switch on: phone ----
    ctx = await openContext(phone, true);
    page = await ctx.newPage(); page.on('pageerror', (e) => errors.push(String(e)));
    await ready(page);
    cdp = await ctx.newCDPSession(page);
    body = await page.locator('[data-tbody]').boundingBox();
    const cy = body.y + body.height / 2, cx = body.x + 150;
    assert.equal(await hour(page), 48, 'switch on starts at the 48 px default');
    const m0 = await minsAt(page, cy);
    await pinch(cdp, cx, cy, 100, 200);
    await page.waitForTimeout(200);
    const h1 = await hour(page);
    assert.ok(Math.abs(h1 - 96) <= 1, `pinch out to twice the gap doubles the hour: ${h1}`);
    const m1 = await minsAt(page, cy);
    assert.ok(Math.abs(m1 - m0) <= 5, `the time between the fingers stays put: ${m0.toFixed(1)} -> ${m1.toFixed(1)} min`);
    const lunch = await page.locator(sel(G(73))).boundingBox();
    assert.ok(Math.abs(lunch.height - 95) <= 2, `a one-hour event grows with the hours: ${lunch.height}`);
    assert.equal(await page.locator('.tg-hrs span').count(), 24, 'every hour keeps its label');
    await shot(page, 'pinch-out-week');
    checks.push(`phone Week: pinch out 100 -> 200 px gives ${h1} px hours; time under the fingers ${m0.toFixed(0)} -> ${m1.toFixed(0)} min`);

    await pinch(cdp, cx, cy, 60, 400);
    await page.waitForTimeout(200);
    assert.equal(await hour(page), 144, 'zoom stops at 3x (144 px)');
    await pinch(cdp, cx, cy, 400, 31);
    await page.waitForTimeout(200);
    const fill = await page.evaluate(() => {
      const b = document.querySelector('[data-tbody]'), cs = getComputedStyle(document.querySelector('[data-tin]'));
      return Math.floor((b.clientHeight - parseFloat(cs.marginTop) - parseFloat(cs.marginBottom) - 1) / 24 * 4) / 4;
    });
    const hMin = await hour(page);
    assert.equal(hMin, Math.max(24, fill), `zoom-out stops at 0.5x or a grid that fills the window: ${hMin}`);
    await shot(page, 'pinch-in-week');
    checks.push(`limits: pinching far out stops at 144 px (3x); far in stops at ${hMin} px (0.5x, or the window fill)`);

    // Back to about 1.5x; kept across Day/Week and a reload.
    await pinch(cdp, cx, cy, 100, 100 * 72 / hMin);
    await page.waitForTimeout(200);
    const hk = await hour(page);
    assert.ok(Math.abs(hk - 72) <= 1, `zoomed to ~72 px: ${hk}`);
    await page.locator('[data-mode="day"]').click();
    await page.waitForSelector(sel(G(73)));
    assert.equal(await hour(page), hk, 'Day uses the same zoom as Week');
    await page.reload();
    await page.waitForFunction(() => /visible events/.test(document.querySelector('[data-status]').textContent));
    await page.waitForSelector(sel(G(73)));
    await page.waitForFunction((h) => parseFloat(getComputedStyle(document.querySelector('[data-time]')).getPropertyValue('--hour')) === h, hk);
    checks.push(`level ${hk} px is shared by Day and Week and survives a reload`);

    // One finger: a sideways swipe still turns the day.
    const dayLabel = () => page.locator('[data-time] .dhd.sel').first().textContent();
    const d0 = await dayLabel();
    body = await page.locator('[data-tbody]').boundingBox();
    const sy = body.y + 40;
    await cdp.send('Input.dispatchTouchEvent', {type: 'touchStart', touchPoints: [{x: body.x + 300, y: sy}]});
    for (let i = 1; i <= 8; i++) await cdp.send('Input.dispatchTouchEvent', {type: 'touchMove', touchPoints: [{x: body.x + 300 - 20 * i, y: sy}]});
    await cdp.send('Input.dispatchTouchEvent', {type: 'touchEnd', touchPoints: []});
    await page.waitForFunction((was) => document.querySelector('[data-time] .dhd.sel')?.textContent !== was, d0);
    assert.equal(await hour(page), hk, 'a swipe keeps the zoom');
    await page.locator('[data-prev]').click();
    await page.waitForFunction((was) => document.querySelector('[data-time] .dhd.sel')?.textContent === was, d0);
    checks.push('one-finger sideways swipe still turns the day, zoom kept');

    // A pinch whose fingers end apart sideways is not a swipe.
    body = await page.locator('[data-tbody]').boundingBox();
    const by = body.y + body.height / 2;
    await cdp.send('Input.dispatchTouchEvent', {type: 'touchStart', touchPoints: [{x: body.x + 200, y: by - 40, id: 1}]});
    await cdp.send('Input.dispatchTouchEvent', {type: 'touchStart', touchPoints: [{x: body.x + 200, y: by - 40, id: 1}, {x: body.x + 220, y: by + 40, id: 2}]});
    for (let i = 1; i <= 6; i++) await cdp.send('Input.dispatchTouchEvent', {type: 'touchMove', touchPoints: [{x: body.x + 200 - 25 * i, y: by - 40, id: 1}, {x: body.x + 220 - 25 * i, y: by + 40, id: 2}]});
    await cdp.send('Input.dispatchTouchEvent', {type: 'touchEnd', touchPoints: [{x: body.x + 70, y: by + 40, id: 2}]});
    await cdp.send('Input.dispatchTouchEvent', {type: 'touchEnd', touchPoints: []});
    await page.waitForTimeout(300);
    assert.equal(await dayLabel(), d0, 'two fingers moving sideways do not turn the day');
    checks.push('two fingers never count as a day swipe');

    // Hold-then-drag still moves an event to the right time at the zoomed size: Lunch 12:00 down one hour.
    const updates = [];
    page.on('request', (r) => { if (r.method() === 'POST' && r.url().endsWith('/api/live/update')) updates.push(r.postDataJSON()); });
    await page.locator(sel(G(73))).scrollIntoViewIfNeeded();
    const lb = await page.locator(sel(G(73))).boundingBox(), H = await hour(page);
    const tx = lb.x + 30, ty = lb.y + 4;
    await cdp.send('Input.dispatchTouchEvent', {type: 'touchStart', touchPoints: [{x: tx, y: ty}]});
    await page.waitForTimeout(600);
    for (let i = 1; i <= 6; i++) await cdp.send('Input.dispatchTouchEvent', {type: 'touchMove', touchPoints: [{x: tx, y: ty + (H + 1) * i / 6}]});
    await cdp.send('Input.dispatchTouchEvent', {type: 'touchEnd', touchPoints: []});
    await page.waitForFunction(() => !document.querySelector('[data-undo]')?.hidden);
    assert.deepEqual(updates.at(-1), {account: 'live:google:me@gmail.com', calendar_id: 'primary', id: 'google-73', start: '2026-11-04T13:00', end: '2026-11-04T14:00', time_zone: 'Asia/Bangkok'});
    assert.equal(await hour(page), hk, 'drag keeps the zoom');
    checks.push(`hold-then-drag at ${H} px hours moves Lunch 12:00 -> 13:00`);
    await ctx.close();

    // ---- desktop: Ctrl + wheel ----
    ctx = await openContext({viewport: {width: 1280, height: 700}}, true);
    page = await ctx.newPage(); page.on('pageerror', (e) => errors.push(String(e)));
    await ready(page);
    const h0 = await hour(page);
    body = await page.locator('[data-tbody]').boundingBox();
    const wy = body.y + body.height / 2;
    await page.mouse.move(body.x + 400, wy);
    const wm0 = await minsAt(page, wy);
    await page.keyboard.down('Control');
    for (let i = 0; i < 5; i++) { await page.mouse.wheel(0, -60); await page.waitForTimeout(30); }
    await page.keyboard.up('Control');
    await page.waitForTimeout(200);
    const hw = await hour(page);
    assert.ok(hw > h0 * 1.8, `Ctrl + wheel up zooms in: ${h0} -> ${hw}`);
    const wm1 = await minsAt(page, wy);
    assert.ok(Math.abs(wm1 - wm0) <= 5, `time under the pointer stays: ${wm0.toFixed(1)} -> ${wm1.toFixed(1)}`);
    const st = await page.evaluate(() => document.querySelector('[data-tbody]').scrollTop);
    await page.mouse.wheel(0, 120); await page.waitForTimeout(200);
    assert.equal(await hour(page), hw, 'a plain wheel scrolls, no zoom');
    assert.ok(await page.evaluate(() => document.querySelector('[data-tbody]').scrollTop) > st, 'plain wheel scrolls the hours');
    await shot(page, 'desktop-ctrl-wheel');
    checks.push(`desktop: Ctrl + wheel zooms ${h0} -> ${hw} px around the pointer; a plain wheel still scrolls`);
    await ctx.close();

    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ok: true, count: checks.length, checks}, null, 2));
  } catch (e) {
    console.error(e); console.error(JSON.stringify({ok: false, checks, errors}, null, 2)); process.exitCode = 1;
  } finally { await browser.close(); }
})();
