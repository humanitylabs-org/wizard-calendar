/* Readable hours in Day and Week (issue 42): a phone used to squeeze all 24 hours onto one screen, so events were
 * one-letter slivers.
 * - Hours are 48 px (Google Calendar's default) and the grid scrolls; a window tall enough for 24 such hours fits them.
 * - Today opens with the current time about an hour below the top; other weeks and days open at 07:00, never 00:00.
 * - Overlapping events keep a readable minimum width in a narrow Week column (they cascade), side by side in Day.
 * - Dragging an event towards the top or bottom edge scrolls the hours, so it can still reach any hour.
 * Run against qa/live_fake.py (loopback dev mode, WIZARD_CORE_DIR=.runtime/core):
 *   CALENDAR_LIVE_URL=<qa/live_fake.py> node qa/readable_hours.cjs */
const {chromium} = require('playwright');
const path = require('node:path'), assert = require('node:assert/strict');
const base = process.env.CALENDAR_LIVE_URL || 'http://127.0.0.1:18930';
const shots = process.env.SHOTS_DIR || '';
const G = (n) => `live:google:me@gmail.com|primary|google-${n}`;
const sel = (id) => `[data-ev="${id}"]`;
const ev = (n, title, start, end) => ({id: G(n), cal: 'live:google:me@gmail.com', title, start, end, allDay: false, location: '',
  description: '', guests: '', meet: '', link: '', live: {account: 'live:google:me@gmail.com', calendar_id: 'primary', id: `google-${n}`,
    is_organizer: true, my_response: 'organizer', invited: false, recurring: false, time_zone: 'Asia/Bangkok', by_agent: false}});
// Two overlapping meetings on today (Wed 4 Nov) and a lunch to drag.
const EXTRA = [ev(71, 'AI Wizard Coworking', '2026-11-04T14:00:00+07:00', '2026-11-04T15:30:00+07:00'),
  ev(72, 'Sync with Miguel', '2026-11-04T14:30:00+07:00', '2026-11-04T15:30:00+07:00'),
  ev(73, 'Lunch', '2026-11-04T12:00:00+07:00', '2026-11-04T13:00:00+07:00')];
(async () => {
  const browserPath = process.env.BROWSER_PATH;
  const browser = await chromium.launch(browserPath ? {headless:true, executablePath:browserPath} : {headless:true, channel:process.env.BROWSER_CHANNEL || 'chrome'});
  const checks = [], errors = [];
  const shot = async (page, name) => { if (shots) { await page.waitForTimeout(300); await page.screenshot({path: path.join(shots, name + '.png')}); } };
  const openPage = async (opts) => {
    const context = await browser.newContext(opts);
    await context.clock.setFixedTime(new Date('2026-11-04T10:00:00+07:00'));
    const page = await context.newPage();
    page.on('pageerror', e => errors.push(String(e)));
    await page.route(/\/api\/events\?/, async (route) => {
      const res = await route.fetch(), d = await res.json();
      d.events.push(...EXTRA);
      await route.fulfill({response: res, json: d});
    });
    await page.goto(base+'/');
    await page.waitForFunction(() => /visible events/.test(document.querySelector('[data-status]').textContent));
    return {context, page};
  };
  const hour = (page) => page.evaluate(() => parseFloat(getComputedStyle(document.querySelector('[data-time]')).getPropertyValue('--hour')));
  const top = (page) => page.evaluate(() => document.querySelector('[data-tbody]').scrollTop);
  try {
    // ---- phone ----
    const {context: phone, page} = await openPage({viewport:{width:390, height:844}, hasTouch:true, isMobile:true});
    await page.locator('[data-mode="week"]').click();
    await page.waitForSelector(sel(G(71)));
    assert.equal(await hour(page), 48, 'a phone hour is 48 px, not squeezed to fit 24 hours');
    const view = await page.evaluate(() => document.querySelector('[data-tbody]').clientHeight);
    assert.ok(view / 48 >= 10 && view / 48 <= 14, `about 10 to 14 hours show at once: ${(view / 48).toFixed(1)}`);
    assert.equal(await page.locator('.tg-hrs span').count(), 24, 'every hour has its label');
    assert.equal(await top(page), 9 * 48, 'today opens with now (10:00) an hour below the top (09:00)');
    const [a, b] = [await page.locator(sel(G(71))).boundingBox(), await page.locator(sel(G(72))).boundingBox()];
    const col = await page.locator('[data-tin] .col.today').boundingBox();
    assert.ok(a.width >= 35 && b.width >= 35, `overlapping events keep a readable width: ${a.width}, ${b.width}`);
    assert.ok(b.x > a.x && b.x + b.width <= col.x + col.width + 0.5 && a.x >= col.x, 'they cascade inside the day column');
    assert.ok((await page.locator(`${sel(G(71))} b`).textContent()).startsWith('AI Wizard'), 'title is there');
    assert.ok(a.height >= 70, `a 90-minute event is tall enough to read (${a.height} px)`);
    await shot(page, 'phone-week');
    checks.push('phone Week: 48 px hours (~13 in view), all 24 labels, opens at 09:00 for now 10:00, overlaps keep >= 36 px and cascade');

    // Another week: opens at 07:00.
    await page.locator('[data-step="7"]').click();
    await page.waitForFunction(() => !document.querySelector('[data-tin] .col.today'));
    assert.equal(await top(page), 7 * 48, 'a week without today opens at 07:00');
    checks.push('phone Week, next week: opens at 07:00, not midnight');

    // Day (today): same hour height; the overlaps sit side by side at half the width.
    await page.locator('[data-today-btn]').click();
    await page.locator('[data-mode="day"]').click();
    await page.waitForSelector(sel(G(71)));
    assert.equal(await hour(page), 48);
    assert.equal(await top(page), 9 * 48, 'Day on today opens at 09:00');
    const [da, db] = [await page.locator(sel(G(71))).boundingBox(), await page.locator(sel(G(72))).boundingBox()];
    const dc = await page.locator('[data-tin] .col').boundingBox();
    assert.ok(Math.abs(da.width - (dc.width / 2 - 2)) < 1.5 && Math.abs(db.x - (dc.x + dc.width / 2 + 1)) < 1.5, 'Day: two halves side by side');
    await shot(page, 'phone-day');
    checks.push('phone Day: 48 px hours, opens at 09:00 today, overlapping events side by side at half width');
    await phone.close();

    // ---- desktop ----
    const {context: desk, page: dp} = await openPage({viewport:{width:1280, height:900}});
    await dp.locator('[data-mode="week"]').click();
    await dp.waitForSelector(sel(G(73)));
    assert.equal(await hour(dp), 48, 'desktop 900 px tall: 48 px hours too');
    const tall = await openPage({viewport:{width:1280, height:1500}});
    await tall.page.locator('[data-mode="week"]').click();
    await tall.page.waitForSelector(sel(G(73)));
    const th = await hour(tall.page);
    assert.ok(th > 48, `a window tall enough fits the whole day (${th} px hours)`);
    assert.equal(await top(tall.page), 0, 'nothing to scroll');
    await tall.context.close();
    checks.push('desktop: 48 px hours at 900 px tall; a 1500 px window still fits all 24 hours (bigger rows, no scroll)');

    // Drag Lunch (12:00) to the bottom edge and hold: the hours scroll and the ghost moves later than what was in view.
    await dp.evaluate(() => { document.querySelector('[data-tbody]').scrollTop = 0; });
    const lb = await dp.locator(sel(G(73))).boundingBox(), body = await dp.locator('[data-tbody]').boundingBox();
    const x = lb.x + lb.width / 2, y = lb.y + 4, t0 = await top(dp);
    await dp.mouse.move(x, y); await dp.mouse.down();
    for (let i = 1; i <= 8; i++) await dp.mouse.move(x, y + (body.y + body.height - 6 - y) * i / 8);
    await dp.waitForTimeout(350);
    const t1 = await top(dp), ghost = await dp.locator('.blk.ghost').textContent();
    await shot(dp, 'desk-edge-scroll');
    await dp.keyboard.press('Escape'); await dp.mouse.up();
    assert.ok(t1 > t0 + 48, `holding a dragged event at the bottom edge scrolls the hours (${t0} -> ${t1})`);
    const gh = +/(\d\d):\d\d–/.exec(ghost)[1];
    const lastInView = Math.floor((t0 + body.height) / 48);
    assert.ok(gh >= lastInView, `the ghost reached an hour that was below the view (${ghost}, view ended ~${lastInView}:00)`);
    // Grabbing an event that sits right at the top edge and dragging down does not scroll up.
    await dp.evaluate(() => { document.querySelector('[data-tbody]').scrollTop = 12 * 48 - 4; });
    const lb2 = await dp.locator(sel(G(73))).boundingBox(), t2 = await top(dp);
    await dp.mouse.move(lb2.x + lb2.width / 2, lb2.y + lb2.height / 2); await dp.mouse.down();
    await dp.mouse.move(lb2.x + lb2.width / 2, lb2.y + lb2.height / 2 + 30, {steps: 4});
    await dp.waitForTimeout(400);
    assert.equal(await top(dp), t2, 'no upward scroll when dragging down from near the top edge');
    await dp.keyboard.press('Escape'); await dp.mouse.up();
    checks.push(`drag to the bottom edge scrolls the hours (${t0} -> ${t1} px, ghost ${ghost.replace(/^\D+/, '')}); dragging down near the top edge does not scroll up`);
    await desk.close();

    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ok:true, checks}, null, 1));
  } catch (e) {
    console.error(e); console.error(JSON.stringify({ok:false, checks, errors}, null, 1)); process.exitCode = 1;
  } finally { await browser.close(); }
})();
