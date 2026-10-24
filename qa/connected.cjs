/* Real Compose Calendar + stdlib fake provider. Synthetic account data only. */
const {chromium} = require('playwright');
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path');
const base = process.env.CALENDAR_URL;
const out = process.env.QA_OUT || path.join(__dirname, '../evidence');
(async () => {
  const browser = await chromium.launch({headless:true, channel:'chrome'});
  const checks = [], errors = [];
  try {
    for (const size of [{width:390,height:844},{width:1440,height:1000}]) {
      for (const scheme of ['dark','light']) {
        const context = await browser.newContext({viewport:size, colorScheme:scheme, timezoneId:'UTC'});
        const page = await context.newPage();
        page.on('pageerror', e => errors.push(String(e)));
        await page.goto(base + '/');
        await page.waitForFunction(() => document.querySelector('[data-status]').textContent.includes('visible events'));
        assert.equal(await page.locator('[data-setup]').isVisible(), false);
        await page.locator('[data-cals]').first().click();
        const section = await page.locator('[data-sync-section]').textContent();
        assert.match(section, /alpha@example.invalid/); assert.match(section, /beta@example.invalid/);
        assert.match(section, /Last sync/); assert.match(section, /Connected accounts/);
        await page.locator('[data-sync]').click();
        await page.waitForFunction(() => document.querySelector('[data-sync]')?.textContent === 'Sync now' && !document.querySelector('[data-sync]').disabled);
        await page.screenshot({path:path.join(out, `calendar-sync-linked-${size.width}-${scheme}.png`), fullPage:true});
        await page.evaluate(() => history.back());
        await page.waitForFunction(() => document.querySelector('[data-sheet]').hidden);
        assert.equal(new URL(page.url()).pathname, '/');
        checks.push(`${size.width}/${scheme}: Compose accounts, last success, Sync now and Settings Back`);
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
        await context.close();
      }
    }
    assert.deepEqual(errors, []);
    const result = {ok:true, checks, count:checks.length, errors};
    fs.writeFileSync(path.join(out,'connected-browser.json'), JSON.stringify(result,null,2));
    console.log(JSON.stringify(result,null,2));
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exit(1); });
