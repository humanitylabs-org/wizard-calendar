/* Connected accounts calendars (issue 31): calendars shared from Connected accounts show next to Google and Microsoft,
 * read-only. Their event says where it comes from and offers no Edit or Delete.
 * Run against qa/live_fake.py with its Connected accounts fake (loopback dev mode, WIZARD_CORE_DIR=.runtime/core):
 *   CONNECTED_ACCOUNTS=1 PORT=18930 python3 qa/live_fake.py &  CALENDAR_LIVE_URL=http://127.0.0.1:18930 node qa/connected.cjs */
const {chromium} = require('playwright');
const path = require('node:path'), assert = require('node:assert/strict');
const base = process.env.CALENDAR_LIVE_URL || 'http://127.0.0.1:18930';
const shots = process.env.SHOTS_DIR || '';
(async () => {
  const browserPath = process.env.BROWSER_PATH;
  const browser = await chromium.launch(browserPath ? {headless:true, executablePath:browserPath} : {headless:true, channel:process.env.BROWSER_CHANNEL || 'chrome'});
  const checks = [], errors = [];
  const shot = async (page, name) => { if (!shots) return; await page.waitForTimeout(450); await page.screenshot({path: path.join(shots, name + '.png')}); };
  try {
    for (const size of [{width:390,height:844},{width:1280,height:900}]) {
      const w = size.width;
      const context = await browser.newContext({viewport:size, timezoneId:'Asia/Bangkok'});
      await context.clock.setFixedTime(new Date('2026-11-04T08:00:00+07:00'));
      const page = await context.newPage();
      page.on('pageerror', e => errors.push(String(e)));
      await page.goto(base + '/');
      await page.locator('[data-ev]').first().waitFor({timeout:15000});
      if (w === 390) await page.locator('[data-mode="day"]').click().catch(() => {});
      const planning = page.locator('[data-ev]', {hasText:'Planning'});
      await planning.first().waitFor({timeout:10000});
      checks.push(`${w}: a Connected accounts event shows next to Google and Microsoft`);
      await shot(page, `connected-${w}`);
      await planning.first().click();
      const note = page.locator('[data-sheet] [data-read-only]');
      await note.waitFor({timeout:5000});
      assert.match(await note.textContent(), /Connected accounts, which shares calendars read-only/);
      assert.equal(await page.locator('[data-sheet] [data-edit], [data-sheet] [data-del]').count(), 0);
      assert.match(await page.locator('[data-sheet] .chip').textContent(), /Work/);
      checks.push(`${w}: its details say it is read-only, from Connected accounts, with no Edit or Delete`);
      await shot(page, `connected-event-${w}`);
      await context.close();
    }
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ok:true, count:checks.length, checks}, null, 1));
  } catch (e) {
    console.log(JSON.stringify({ok:false, checks, errors, error:String(e && e.stack || e)}, null, 1));
    process.exitCode = 1;
  } finally { await browser.close(); }
})();
