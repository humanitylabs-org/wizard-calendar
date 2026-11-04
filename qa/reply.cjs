/* Reply on an event: hidden without the shell's openContextDraft; with it, one synchronous unsent Chats draft
 * carrying the event, a "Nothing sent" status, and no write requests from the app.
 * Run against a disposable instance: CALENDAR_URL=http://127.0.0.1:18787 node qa/reply.cjs (imports the synthetic fixture). */
const {chromium} = require('playwright');
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const base = process.env.CALENDAR_URL || 'http://127.0.0.1:18787';
(async () => {
  const browserPath = process.env.BROWSER_PATH;
  const browser = await chromium.launch(browserPath ? {headless:true, executablePath:browserPath} : {headless:true, channel:process.env.BROWSER_CHANNEL || 'chrome'});
  const checks = [], errors = [];
  try {
    for (const size of [{width:390,height:844},{width:1280,height:900}]) {
      const context = await browser.newContext({viewport:size});
      await context.request.post(base+'/api/import', {data:JSON.parse(fs.readFileSync(path.join(__dirname,'../fixtures/example.json')))});
      // WizardApp is frozen: stand in for the shell by wrapping it as it is defined. qa.reply=old drops
      // openContextDraft (an older shell); otherwise the stub answers with window.__receipt / throws window.__throw.
      await context.addInitScript(() => {
        let app;
        Object.defineProperty(window, 'WizardApp', { configurable: true, get: () => app, set: (real) => {
          const nav = { ...real.nav };
          if (localStorage.getItem('qa.reply') === 'old') delete nav.openContextDraft;
          else nav.openContextDraft = (c) => { if (window.__throw) throw new Error(window.__throw); (window.__drafts ||= []).push(c); return window.__receipt || {kind:'unsent-draft', sent:false}; };
          app = Object.freeze({ ...real, back: real.back, nav: Object.freeze(nav) });
        } });
      });
      const page = await context.newPage(), writes = [];
      page.on('pageerror', e => errors.push(String(e)));
      page.on('request', r => { if (!['GET','HEAD'].includes(r.method())) writes.push(r.method()+' '+r.url()); });
      await page.goto(base+'/');
      await page.evaluate(() => localStorage.setItem('qa.reply', 'old'));
      await page.reload();
      await page.waitForFunction(() => /visible events/.test(document.querySelector('[data-status]').textContent));
      const open = async () => { await page.locator('[data-ev="fixture:timed"]').first().click(); await page.waitForSelector('[data-sheet][role="dialog"]'); };
      const shut = async () => { await page.evaluate(() => history.back()); await page.waitForFunction(() => document.querySelector('[data-sheet]').hidden); };
      const toOct = async () => {
        await page.locator('[data-mode="month"]').click();
        for (let i=0; i<120; i++) {
          const m = (await page.locator('[data-month]').textContent()).match(/^([A-Z][a-z]+ \d{4})/)[1]; // long + short titles
          if (m === 'October 2026') break;
          await page.locator(new Date(m+' 15') > new Date('2026-10-15') ? '[data-prev]' : '[data-next-month]').click();
        }
        await page.locator('[data-day="2026-10-15"]').click();
      };
      await toOct();
      // Older shell (no openContextDraft): no Reply.
      await open(); assert.equal(await page.locator('[data-reply]').count(), 0); await shut();
      checks.push(`${size.width}: Reply hidden without openContextDraft`);
      // Shell with openContextDraft: Reply opens one unsent draft.
      await page.evaluate(() => localStorage.removeItem('qa.reply'));
      await page.reload(); await page.waitForFunction(() => /visible events/.test(document.querySelector('[data-status]').textContent));
      await toOct();
      await open();
      assert.equal(await page.locator('[data-reply]').textContent(), 'Reply');
      await page.locator('[data-reply]').click();
      const d = await page.evaluate(() => window.__drafts);
      assert.equal(d.length, 1);
      assert.match(d[0].id, /^[A-Za-z0-9_-]{1,128}$/);
      assert.equal(d[0].title, 'Calendar: Synthetic planning session');
      assert.match(d[0].message, /^Calendar event: Synthetic planning session\nWhen: /);
      assert.match(d[0].message, /\nCalendar: Synthetic test calendar \(private iCal \/ snapshot\)\nCalendar app event id: fixture:timed\n/);
      assert.match(d[0].message, /\nStart 2026-10-15T10:00:00Z; end 2026-10-15T11:00:00Z/);
      assert.match(d[0].message, /Test-only data\. Not a real appointment\./);
      assert.match(await page.locator('[data-c-msg]').textContent(), /Nothing sent/);
      checks.push(`${size.width}: Reply opens one unsent context draft`);
      // A receipt that is not an unsent draft is refused; a stale shell asks for a reload.
      await page.evaluate(() => { window.__receipt = {kind:'sent', sent:true}; });
      await page.locator('[data-reply]').click();
      assert.equal(await page.locator('[data-c-msg]').textContent(), 'Could not confirm an unsent draft. Nothing was sent.');
      await page.evaluate(() => { window.__throw = 'Context draft unavailable'; });
      await page.locator('[data-reply]').click();
      assert.equal(await page.locator('[data-c-msg]').textContent(), 'Reload Wizard (refresh the whole page) to turn on Reply. Nothing sent.');
      checks.push(`${size.width}: unconfirmed receipt and stale shell say nothing was sent`);
      await shut();
      assert.deepEqual(writes, []);
      await context.close();
    }
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ok:true, count:checks.length, checks, errors}, null, 2));
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exit(1); });
