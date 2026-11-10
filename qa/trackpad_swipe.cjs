/* Real-browser QA for the Trackpad day swipe switch (trackpad-swipe, off by default; issue 21).
   Sends real wheel events: off does nothing sideways; on, Week slides one day at a time, Day moves a day, a long swipe
   moves several days, the grid follows the fingers mid-gesture, vertical wheels still scroll the hours, Shift + wheel
   works, and reduced motion jumps without following. Synthetic data only.
   Usage: CALENDAR_URL=http://127.0.0.1:18787 BROWSER_PATH=<chromium> node qa/trackpad_swipe.cjs */
const {chromium} = require(process.env.QA_PLAYWRIGHT || 'playwright');
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const base = process.env.CALENDAR_URL || 'http://127.0.0.1:18787';
const out = process.env.QA_OUT || path.join(__dirname, '../evidence');
fs.mkdirSync(out, {recursive: true});

async function setSwitch(request, on) {
  const r = await request.post(base + '/api/switches', {data: {id: 'trackpad-swipe', on}, headers: {Origin: base, 'X-Wizard-Switch': '1'}});
  assert.equal(r.status(), 200);
}
// First visible day: the column whose left edge sits at the clip's left edge.
const firstVisible = (page) => page.evaluate(() => {
  const clip = document.querySelector('.tg-cols').getBoundingClientRect();
  const cols = [...document.querySelectorAll('[data-col]')];
  return (cols.find((c) => Math.abs(c.getBoundingClientRect().left - clip.left) < 2) || cols[0]).dataset.col;
});
const step = (page, mode) => page.evaluate((m) => document.querySelector('.tg-cols').clientWidth / (m === 'week' ? 7 : 1), mode);
const addDays = (k, n) => { const d = new Date(k + 'T12:00:00Z'); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };
// A two-finger swipe: `total` px of deltaX in small events, then the gesture goes quiet and settles.
async function swipe(page, total, {events = 12, y = 0, settle = true} = {}) {
  for (let i = 0; i < events; i++) { await page.mouse.wheel(total / events, y / events); await page.waitForTimeout(16); }
  if (settle) await page.waitForTimeout(500);
}

(async () => {
  const browserPath = process.env.BROWSER_PATH || process.env.QA_CHROME;
  const browser = await chromium.launch(browserPath ? {headless: true, executablePath: browserPath} : {headless: true, channel: process.env.BROWSER_CHANNEL || 'chrome'});
  const report = {}, errors = [];
  try {
    const setup = await browser.newContext();
    await setup.request.post(base + '/api/import', {data: JSON.parse(fs.readFileSync(path.join(__dirname, '../fixtures/example.json')))});
    const open = async (mode, on, extra = {}) => {
      await setSwitch(setup.request, on);
      const context = await browser.newContext({viewport: {width: 1280, height: 900}, ...extra});
      await context.addInitScript((m) => localStorage.setItem('wc.mode', m), mode);
      const page = await context.newPage();
      page.on('pageerror', (e) => errors.push(String(e)));
      await page.goto(base + '/');
      await page.waitForFunction(() => /visible events/.test(document.querySelector('[data-status]').textContent));
      await page.waitForFunction((want) => document.querySelector('[data-time]').classList.contains('is-pan') === want, on);
      await page.mouse.move(700, 600);
      return {context, page};
    };

    // Off: sideways wheel changes nothing.
    {
      const {context, page} = await open('week', false);
      const before = await firstVisible(page);
      await swipe(page, 600);
      assert.equal(await firstVisible(page), before, 'switch off: sideways wheel does not move the week');
      report.off = 'unchanged';
      await context.close();
    }

    // On, Week: sliding window one day at a time.
    {
      const {context, page} = await open('week', true);
      const w = await step(page, 'week'), start = await firstVisible(page);
      report.weekStart = start;
      // Mid-gesture the grid follows the fingers.
      await swipe(page, w * 0.5, {settle: false});
      const mid = await page.evaluate(() => getComputedStyle(document.querySelector('[data-time]')).getPropertyValue('--dx').trim());
      assert.ok(parseFloat(mid) < -w * 0.3, `grid follows the fingers mid-swipe (${mid})`);
      await page.screenshot({path: path.join(out, 'trackpad-swipe-week-mid.png')});
      await page.waitForTimeout(500);
      assert.equal(await firstVisible(page), addDays(start, 1), 'half a day left settles one day forward');
      await swipe(page, -w);
      assert.equal(await firstVisible(page), start, 'one day right goes back a day');
      await swipe(page, w * 0.15);
      assert.equal(await firstVisible(page), start, 'a tiny sideways drift snaps back');
      await swipe(page, w * 10, {events: 40});
      assert.equal(await firstVisible(page), addDays(start, 10), 'a long swipe moves several days (10)');
      const heads = await page.evaluate(() => [...document.querySelectorAll('[data-heads] [data-dayview]')].filter((b) => { const r = b.getBoundingClientRect(), c = document.querySelector('[data-heads]').getBoundingClientRect(); return r.left >= c.left - 1 && r.right <= c.right + 1; }).map((b) => b.dataset.dayview));
      assert.equal(heads[0], addDays(start, 10), 'day heads move with the columns');
      assert.equal(heads.length, 7, 'seven heads visible');
      await page.screenshot({path: path.join(out, 'trackpad-swipe-week-on.png')});
      // Vertical scroll still scrolls the hours and leaves the days alone.
      const top = await page.evaluate(() => document.querySelector('[data-tbody]').scrollTop);
      for (let i = 0; i < 6; i++) { await page.mouse.wheel(4, 120); await page.waitForTimeout(16); }
      await page.waitForTimeout(400);
      assert.ok(await page.evaluate((t) => document.querySelector('[data-tbody]').scrollTop > t, top), 'vertical wheel still scrolls the hours');
      assert.equal(await firstVisible(page), addDays(start, 10), 'vertical wheel does not change the days');
      // Shift + wheel (mouse) moves a day.
      await page.keyboard.down('Shift');
      await page.mouse.wheel(0, 100); await page.waitForTimeout(500);
      await page.keyboard.up('Shift');
      assert.equal(await firstVisible(page), addDays(start, 11), 'Shift + wheel moves a day forward');
      // Next/previous buttons still page by a week; Today returns to the Monday-first week.
      await page.locator('[data-next-month]').click();
      assert.equal(await firstVisible(page), addDays(start, 18), 'Next still moves a whole week');
      await page.locator('[data-today-btn]').click();
      assert.equal(await firstVisible(page), start, 'Today returns to this week');
      await context.close();
    }

    // On, Day: one day per swipe.
    {
      const {context, page} = await open('day', true);
      const w = await step(page, 'day'), start = await firstVisible(page);
      await swipe(page, w * 0.6);
      assert.equal(await firstVisible(page), addDays(start, 1), 'Day: swipe left is the next day');
      await swipe(page, -w * 5, {events: 30});
      assert.equal(await firstVisible(page), addDays(start, -4), 'Day: a long swipe right goes back several days');
      await page.screenshot({path: path.join(out, 'trackpad-swipe-day-on.png')});
      await context.close();
    }

    // Reduced motion: no following, just jump.
    {
      const {context, page} = await open('week', true, {reducedMotion: 'reduce'});
      const w = await step(page, 'week'), start = await firstVisible(page);
      await swipe(page, w * 2, {settle: false});
      const mid = await page.evaluate(() => getComputedStyle(document.querySelector('[data-time]')).getPropertyValue('--dx').trim());
      assert.ok(!mid || parseFloat(mid) === 0, `reduced motion: grid does not follow (${mid})`);
      await page.waitForTimeout(500);
      assert.equal(await firstVisible(page), addDays(start, 2), 'reduced motion: jumps by the swiped days');
      await context.close();
    }

    // Settings lists the switch and the toggle persists on the box.
    {
      const {context, page} = await open('week', true);
      await page.locator('.bar [data-cals]').click();
      const sw = page.locator('[data-switch="trackpad-swipe"]');
      assert.equal(await sw.getAttribute('aria-checked'), 'true');
      await sw.scrollIntoViewIfNeeded(); await page.waitForTimeout(300);
      await page.screenshot({path: path.join(out, 'trackpad-swipe-settings.png')});
      await sw.click();
      await page.waitForFunction(() => !document.querySelector('[data-time]').classList.contains('is-pan'));
      const listed = (await (await context.request.get(base + '/api/switches')).json()).switches.find((x) => x.id === 'trackpad-swipe');
      assert.equal(listed.on, false, 'Settings toggle persists on the box');
      await context.close();
    }
    await setSwitch(setup.request, false);
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ok: true, report}, null, 1));
  } finally { await browser.close(); }
})().catch((e) => { console.error(e); process.exit(1); });
