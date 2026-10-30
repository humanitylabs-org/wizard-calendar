/* Browser acceptance for owner-facing Google iCal source setup. */
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

const base = process.env.CALENDAR_URL || 'http://127.0.0.1:18787';
const out = process.env.QA_OUT || path.join(__dirname, '../evidence');
fs.mkdirSync(out, {recursive: true});

function day(offset) {
  const value = new Date();
  value.setUTCDate(value.getUTCDate() + offset);
  return value.toISOString().slice(0, 10);
}

(async () => {
  const browserPath = process.env.BROWSER_PATH;
  const browser = await chromium.launch(browserPath
    ? {headless: true, executablePath: browserPath}
    : {headless: true, channel: process.env.BROWSER_CHANNEL || 'chrome'});
  const checks = [], errors = [];
  try {
    for (const size of [{width: 390, height: 844}, {width: 1280, height: 900}]) {
      for (const scheme of ['dark', 'light']) {
        const context = await browser.newContext({viewport: size, colorScheme: scheme, hasTouch: size.width < 500, isMobile: size.width < 500});
        const page = await context.newPage();
        page.on('pageerror', error => errors.push(String(error)));
        let source = null;
        let calendar = null;
        let events = [];
        let submitted = null;
        let syncBusy = false;
        const sourceId = 'ical:' + crypto.randomUUID().replaceAll('-', '');
        const privateUrl = `https://calendar.google.com/calendar/ical/${crypto.randomUUID()}%40group.calendar.google.com/${crypto.randomUUID()}/basic.ics`;

        await page.route('**/api/**', async route => {
          const request = route.request();
          const url = new URL(request.url());
          const method = request.method();
          if (method === 'GET' && url.pathname.endsWith('/api/events')) {
            const syncedAt = new Date().toISOString();
            return route.fulfill({json: {
              schemaVersion: 1,
              timezone: 'UTC',
              calendars: calendar ? [{...calendar, hidden: false, ok: true, count: events.length}] : [],
              events,
              syncedAt,
              connected: source ? [{...source, lastSyncedAt: syncedAt, error: ''}] : [],
              errors: [], syncing: false, syncError: '', mode: source ? 'ical' : 'snapshot'
            }});
          }
          if (method === 'POST' && url.pathname.endsWith('/api/sources')) {
            submitted = request.postDataJSON();
            source = {id: sourceId, name: submitted.name, provider: 'Google iCal'};
            calendar = {id: sourceId, name: submitted.name};
            events = [{id: `${sourceId}:event`, cal: sourceId, title: 'Private calendar event', start: day(1), end: day(2), allDay: true, location: '', description: '', link: '', meet: ''}];
            return route.fulfill({json: {ok: true, source}});
          }
          if (method === 'POST' && url.pathname.endsWith('/api/sources/remove')) {
            source = null; calendar = null; events = [];
            return route.fulfill({json: {ok: true, id: sourceId}});
          }
          if (method === 'POST' && url.pathname.endsWith('/api/sync')) {
            return route.fulfill({status: syncBusy ? 202 : 200, json: {ok: true, syncing: syncBusy, synced: syncBusy ? 0 : source ? 1 : 0, failed: 0}});
          }
          return route.continue();
        });

        await page.goto(base + '/');
        await page.waitForFunction(() => document.querySelector('[data-status]')?.textContent.includes('No calendar yet'));
        await page.locator('[data-cals]').first().click();
        await page.getByLabel('Calendar name').fill('Personal');
        await page.getByLabel('Google iCal link').fill(privateUrl);
        await page.getByRole('button', {name: 'Add calendar'}).click();
        await page.waitForFunction(() => document.querySelector('[data-c-msg]')?.textContent === 'Calendar added.');
        assert.deepEqual(submitted, {name: 'Personal', url: privateUrl});
        assert.match(await page.locator('[data-sheet]').textContent(), /Personal/);
        assert.doesNotMatch(await page.locator('html').innerHTML(), new RegExp(privateUrl.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
        assert.match(await page.locator('[data-status]').textContent(), /1 visible event/);
        const geometry = await page.evaluate(() => {
          const sheet = document.querySelector('[data-sheet]');
          const controls = [...sheet.querySelectorAll('[data-source-name], [data-source-url], [data-add-source], [data-remove-source]')]
            .map(node => ({height: node.getBoundingClientRect().height, width: node.getBoundingClientRect().width}));
          return {fits: sheet.scrollWidth <= sheet.clientWidth + 1, controls};
        });
        assert.equal(geometry.fits, true);
        assert.ok(geometry.controls.every(control => control.width > 0 && control.height >= 44));
        checks.push(`${size.width}/${scheme}: private link adds a read-only calendar and leaves the DOM`);

        await page.getByRole('button', {name: 'Sync now'}).click();
        await page.waitForFunction(() => document.querySelector('[data-c-msg]')?.textContent === 'Calendars updated.');
        checks.push(`${size.width}/${scheme}: manual sync reads back updated state`);
        syncBusy = true;
        await page.getByRole('button', {name: 'Sync now'}).click();
        await page.waitForFunction(() => document.querySelector('[data-c-msg]')?.textContent === 'A calendar sync is already running.');
        syncBusy = false;
        checks.push(`${size.width}/${scheme}: concurrent sync is not reported as completed`);

        await page.screenshot({path: path.join(out, `calendar-ical-${size.width}-${scheme}.png`), fullPage: true});
        await page.getByRole('button', {name: 'Remove'}).click();
        await page.waitForFunction(() => document.querySelector('[data-c-msg]')?.textContent === 'Calendar removed.');
        assert.match(await page.locator('[data-sheet]').textContent(), /No Google iCal calendars added/);
        assert.match(await page.locator('[data-status]').textContent(), /No calendar yet/);
        checks.push(`${size.width}/${scheme}: remove clears the source and imported events`);
        await context.close();
      }
    }
    assert.deepEqual(errors, []);
    const receipt = {ok: true, count: checks.length, checks, errors};
    fs.writeFileSync(path.join(out, 'ical-browser.json'), JSON.stringify(receipt, null, 2));
    console.log(JSON.stringify(receipt, null, 2));
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
