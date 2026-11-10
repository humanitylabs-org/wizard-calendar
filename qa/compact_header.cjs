/* Real-browser QA for the Compact top bar switch (compact-header, off by default; issue 20).
   Measures how many hours of the time grid show without scrolling, off vs on, and checks the header is one row
   with every control fully on screen at phone, narrow and desktop widths. Synthetic data only.
   Usage: CALENDAR_URL=http://127.0.0.1:18787 BROWSER_PATH=<chromium> node qa/compact_header.cjs */
const {chromium} = require(process.env.QA_PLAYWRIGHT || 'playwright');
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const base = process.env.CALENDAR_URL || 'http://127.0.0.1:18787';
const out = process.env.QA_OUT || path.join(__dirname, '../evidence');
fs.mkdirSync(out, {recursive: true});
const CONTROLS = ['[data-prev]', '[data-month]', '[data-next-month]', '[data-today-btn]', '.bar [data-cals]', '[data-mode="day"]', '[data-mode="week"]', '[data-mode="month"]'];

async function setSwitch(request, on) {
  const r = await request.post(base + '/api/switches', {data: {id: 'compact-header', on}, headers: {Origin: base, 'X-Wizard-Switch': '1'}});
  assert.equal(r.status(), 200);
}

async function measure(page) {
  return page.evaluate((controls) => {
    const body = document.querySelector('[data-tbody]').getBoundingClientRect();
    const bar = document.querySelector('.bar').getBoundingClientRect();
    const rects = controls.map((s) => { const r = document.querySelector(s).getBoundingClientRect(); return {s, l: r.left, r: r.right, t: r.top, b: r.bottom, w: r.width, h: r.height}; });
    const month = document.querySelector('[data-month]');
    return {hours: body.height / 48, barHeight: bar.height, rects, vw: innerWidth, vh: innerHeight,
      monthWraps: month.scrollWidth > month.clientWidth + 1 || month.getBoundingClientRect().height > 40,
      compact: document.documentElement.hasAttribute('data-compact-header')};
  }, CONTROLS);
}

(async () => {
  const browserPath = process.env.BROWSER_PATH || process.env.QA_CHROME;
  const browser = await chromium.launch(browserPath ? {headless: true, executablePath: browserPath} : {headless: true, channel: process.env.BROWSER_CHANNEL || 'chrome'});
  const report = [], errors = [];
  try {
    const setup = await browser.newContext();
    await setup.request.post(base + '/api/import', {data: JSON.parse(fs.readFileSync(path.join(__dirname, '../fixtures/example.json')))});
    for (const size of [{width: 320, height: 640, touch: true}, {width: 390, height: 844, touch: true}, {width: 700, height: 800}, {width: 1280, height: 900}]) {
      for (const mode of ['week', 'day']) {
        const row = {size: `${size.width}x${size.height}`, mode};
        for (const on of [false, true]) {
          await setSwitch(setup.request, on);
          const context = await browser.newContext({viewport: {width: size.width, height: size.height}, hasTouch: !!size.touch, isMobile: !!size.touch});
          await context.addInitScript((m) => localStorage.setItem('wc.mode', m), mode);
          const page = await context.newPage();
          page.on('pageerror', (e) => errors.push(String(e)));
          await page.goto(base + '/');
          await page.waitForFunction(() => /visible events/.test(document.querySelector('[data-status]').textContent));
          await page.waitForFunction((want) => document.documentElement.hasAttribute('data-compact-header') === want, on);
          const m = await measure(page);
          for (const r of m.rects) {
            assert.ok(r.w > 0 && r.h > 0, `${row.size} ${mode} ${on ? 'on' : 'off'}: ${r.s} visible`);
            assert.ok(r.l >= -0.5 && r.r <= m.vw + 0.5 && r.t >= -0.5 && r.b <= m.vh + 0.5, `${row.size} ${mode} ${on ? 'on' : 'off'}: ${r.s} fully on screen`);
          }
          if (on) assert.ok(!m.monthWraps, `${row.size} ${mode}: date label does not wrap`);
          if (on) assert.ok(m.barHeight <= 44, `${row.size} ${mode}: compact header is one slim row (${m.barHeight}px)`);
          row[on ? 'on' : 'off'] = {hours: +m.hours.toFixed(2), bar: Math.round(m.barHeight)};
          await page.screenshot({path: path.join(out, `compact-header-${size.width}-${mode}-${on ? 'on' : 'off'}.png`)});
          if (on && mode === 'week' && size.width === 390) {
            await page.locator('.bar [data-cals]').click();
            const sw = page.locator('[data-switch="compact-header"]');
            assert.equal(await sw.getAttribute('aria-checked'), 'true');
            await sw.scrollIntoViewIfNeeded(); await page.waitForTimeout(400);
            await page.screenshot({path: path.join(out, 'compact-header-settings-390.png')});
            await sw.click();
            await page.waitForFunction(() => !document.documentElement.hasAttribute('data-compact-header'));
            assert.equal((await (await context.request.get(base + '/api/switches')).json()).switches[0].on, false, 'Settings toggle persists on the box');
          }
          await context.close();
        }
        row.extraHours = +(row.on.hours - row.off.hours).toFixed(2);
        assert.ok(row.extraHours >= 0.9, `${row.size} ${mode}: at least ~1 more hour visible (${row.extraHours})`);
        report.push(row);
      }
    }
    await setSwitch(setup.request, false);
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ok: true, report}, null, 1));
  } finally { await browser.close(); }
})().catch((e) => { console.error(e); process.exit(1); });
