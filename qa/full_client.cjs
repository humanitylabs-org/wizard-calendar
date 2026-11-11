/* Calendar is a full calendar client (issue 29): never a silent read-only view.
 * - Only private iCal / snapshot calendars: + still shows; it (and a tap on an empty slot) explains those are read-only
 *   and offers Connect Google / Microsoft. An iCal event says it is read-only and offers the same.
 * - Connected calendars: an event the source app marks as made by an agent shows "by your agent".
 * - Right after connecting, the owner chooses what agents may do (the source app's levels); the choice is saved there.
 * Run against two disposable instances (both on a loopback dev mode, WIZARD_CORE_DIR=.runtime/core):
 *   CALENDAR_URL=<snapshot-only Calendar, CALENDAR_LIVE=off>  CALENDAR_LIVE_URL=<qa/live_fake.py>  node qa/full_client.cjs */
const {chromium} = require('playwright');
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const base = process.env.CALENDAR_URL || 'http://127.0.0.1:18787';
const liveBase = process.env.CALENDAR_LIVE_URL || 'http://127.0.0.1:18930';
const shots = process.env.SHOTS_DIR || '';
const LEVELS = [['no_access', 'No access'], ['read_only', 'Read-only'], ['suggest_only', 'Suggest only'], ['can_edit', 'Can edit']]
  .map(([id, label]) => ({id, label, what: label, recommended: id === 'suggest_only'}));
(async () => {
  const browserPath = process.env.BROWSER_PATH;
  const browser = await chromium.launch(browserPath ? {headless:true, executablePath:browserPath} : {headless:true, channel:process.env.BROWSER_CHANNEL || 'chrome'});
  const checks = [], errors = [];
  const shot = async (page, name) => { if (!shots) return; await page.waitForTimeout(450); await page.screenshot({path: path.join(shots, name + '.png')}); };
  try {
    for (const size of [{width:390,height:844},{width:1280,height:900}]) {
      const w = size.width;
      // ---- only a snapshot / private iCal calendar ----
      let context = await browser.newContext({viewport:size});
      await context.clock.setFixedTime(new Date('2026-10-15T10:00:00+07:00'));
      const imp = await context.request.post(base+'/api/import', {data:JSON.parse(fs.readFileSync(path.join(__dirname,'../fixtures/example.json')))});
      assert.equal(imp.status(), 200, await imp.text());
      let page = await context.newPage();
      page.on('pageerror', e => errors.push(String(e)));
      await page.goto(base+'/');
      await page.waitForFunction(() => /visible events/.test(document.querySelector('[data-status]').textContent));
      await page.locator('[data-mode="week"]').click();
      await shot(page, `${w}-ical-week`);
      const plus = page.locator('[data-new]:visible').first();
      assert.equal(await plus.count(), 1, 'a + button is visible with only iCal calendars');
      checks.push(`${w}: + shows with only private iCal calendars`);
      await plus.click();
      await page.waitForSelector('[data-writable-help]');
      assert.match(await page.locator('[data-writable-help]').textContent(), /read-only.*Connect Google or Microsoft/s);
      assert.equal(await page.locator('[data-sheet] [data-connect="google"]').count(), 1);
      assert.equal(await page.locator('[data-sheet] [data-connect="microsoft"]').count(), 1);
      await shot(page, `${w}-ical-add`);
      checks.push(`${w}: + explains iCal is read-only and offers Google / Microsoft`);
      await page.evaluate(() => history.back()); await page.waitForFunction(() => document.querySelector('[data-sheet]').hidden);
      // A tap on an empty slot does the same instead of nothing.
      await page.locator('[data-tin] .col').first().click({position:{x:10, y:200}});
      await page.waitForSelector('[data-writable-help]');
      checks.push(`${w}: tapping an empty slot explains it too`);
      await page.evaluate(() => history.back()); await page.waitForFunction(() => document.querySelector('[data-sheet]').hidden);
      await page.locator('[data-ev="fixture:timed"]').first().click();
      await page.waitForSelector('[data-read-only]');
      assert.match(await page.locator('[data-read-only]').textContent(), /private iCal link, which is read-only/);
      assert.equal(await page.locator('[data-sheet] [data-connect-any]').count(), 1);
      await shot(page, `${w}-ical-event`);
      checks.push(`${w}: an iCal event says it is read-only and offers Connect`);
      await context.close();

      // ---- connected Google and Microsoft calendars ----
      context = await browser.newContext({viewport:size});
      await context.clock.setFixedTime(new Date('2026-11-04T10:00:00+07:00'));
      const posts = [];
      let level = 'suggest_only';
      await context.route(/\/wizard-(google|microsoft)\/api\//, async (route) => {
        const req = route.request(), u = new URL(req.url());
        const json = (v) => route.fulfill({status:200, contentType:'application/json', body:JSON.stringify(v)});
        if (u.pathname.endsWith('/api/session')) return json({csrf:'qa'});
        if (u.pathname.endsWith('/api/agent-access')) { const b = req.postDataJSON(); posts.push([u.pathname, b, req.headers()['x-csrf-token']]); level = b.calendar; }
        const google = u.pathname.startsWith('/wizard-google/');
        return json({accounts:[{email: google ? 'me@gmail.com' : 'me@outlook.com', status:'active'}],
          agent_access:{calendar: level, calendar_levels: LEVELS}});
      });
      page = await context.newPage();
      page.on('pageerror', e => errors.push(String(e)));
      await page.goto(liveBase+'/');
      await page.waitForFunction(() => /visible events/.test(document.querySelector('[data-status]').textContent));
      await page.locator('[data-mode="week"]').click();
      await page.locator('[data-ev="live:google:me@gmail.com|primary|google-3"]').first().click();
      await page.waitForSelector('[data-by-agent]');
      assert.equal((await page.locator('[data-by-agent] .v').textContent()).trim(), 'by your agent');
      assert.equal(await page.locator('[data-sheet] [data-edit]').count(), 1, 'an agent-made event is still editable');
      await shot(page, `${w}-by-agent`);
      await page.evaluate(() => history.back()); await page.waitForFunction(() => document.querySelector('[data-sheet]').hidden);
      await page.locator('[data-ev="live:google:me@gmail.com|primary|google-1"]').first().click();
      await page.waitForSelector('[data-sheet] [data-edit]');
      assert.equal(await page.locator('[data-by-agent]').count(), 0);
      assert.equal(await page.locator('[data-read-only]').count(), 0);
      checks.push(`${w}: an agent-made event shows "by your agent"; the owner's own does not`);
      await page.evaluate(() => history.back()); await page.waitForFunction(() => document.querySelector('[data-sheet]').hidden);
      // Connecting (the sign-in itself is the source app's; stand in for its finish) asks for agent access.
      await page.evaluate(() => { window.WizardConnect.open = (o) => o.onDone({source:'google', connected:true}); });
      await page.locator('[data-cals]').first().click();
      await page.waitForSelector('[data-wcs] .wcs-plus');
      await page.locator('[data-wcs] .wcs-plus').click();
      await page.waitForSelector('[data-level="can_edit"]');
      assert.equal(await page.locator('[data-sheet] h2').textContent(), 'What may your agents do?');
      assert.equal(await page.locator('[data-level]').count(), 4);
      assert.equal(await page.locator('[data-level="suggest_only"]').getAttribute('aria-pressed'), 'true');
      await shot(page, `${w}-choose-access`);
      await page.locator('[data-level="can_edit"]').click();
      await page.waitForFunction(() => document.querySelector('[data-wcs]'));  // back in Settings
      assert.deepEqual(posts.at(-1), ['/wizard-google/api/agent-access', {calendar:'can_edit'}, 'qa']);
      checks.push(`${w}: after connecting, the owner chooses agent access and it is saved in the source app`);
      await context.close();
    }
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ok:true, checks}, null, 1));
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exit(1); });
