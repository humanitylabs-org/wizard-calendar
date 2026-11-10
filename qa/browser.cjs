/* Real-browser smoke: synthetic import, views, persistence and shared Back. */
const {chromium} = require('playwright');
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const base = process.env.CALENDAR_URL || 'http://127.0.0.1:18787';
const out = process.env.QA_OUT || path.join(__dirname, '../evidence');
fs.mkdirSync(out, {recursive:true});
(async () => {
  const browserPath = process.env.BROWSER_PATH;
  const browser = await chromium.launch(browserPath
    ? {headless:true, executablePath:browserPath}
    : {headless:true, channel:process.env.BROWSER_CHANNEL || 'chrome'});
  const checks = [], errors = [];
  try {
    for (const size of [{width:390,height:844},{width:1280,height:900}]) {
      for (const scheme of ['dark','light']) {
        const context = await browser.newContext({viewport:size, colorScheme:scheme});
        const page = await context.newPage();
        page.on('pageerror', e => errors.push(String(e)));
        page.on('dialog', dialog => dialog.accept());
        await context.request.post(base+'/api/import', {data:JSON.parse(fs.readFileSync(path.join(__dirname,'../fixtures/empty.json')))});
        await page.goto(base+'/');
        await page.waitForFunction(() => document.querySelector('[data-status]').textContent.includes('No calendar yet'));
        assert.equal(await page.evaluate(() => WizardApp.version),1);
        checks.push(`${size.width}/${scheme}: empty install opens with real WizardApp`);
        await page.locator('[data-cals]').first().click();
        await page.locator('[data-import]').setInputFiles(path.join(__dirname,'../fixtures/example.json'));
        await page.waitForFunction(() => document.querySelector('[data-c-msg]')?.textContent.includes('Imported 2 events'));
        const saved = await (await context.request.get(base+'/api/export')).json();
        assert.equal(saved.events.length,2);
        checks.push(`${size.width}/${scheme}: UI import persisted and read back`);
        await page.locator('[data-close]').click();
        await page.locator('[data-mode="month"]').click();
        // Jump directly through the actual month navigation controls, not an injected app state.
        for (let i=0; i<120; i++) {
          const title = await page.locator('[data-month]').textContent();
          if (title === 'October 2026') break;
          const d = new Date(title+' 15');
          await page.locator(d > new Date('2026-10-15') ? '[data-prev]' : '[data-next-month]').click();
        }
        await page.locator('[data-day="2026-10-15"]').click();
        await page.locator('[data-ev="fixture:timed"]').first().click();
        await page.waitForSelector('[data-sheet][role="dialog"]');
        assert.match(await page.locator('[data-sheet]').textContent(),/Synthetic planning session/);
        await page.evaluate(() => history.back());
        await page.waitForFunction(() => document.querySelector('[data-sheet]').hidden);
        assert.ok(page.url().startsWith(base));
        checks.push(`${size.width}/${scheme}: event Back closes overlay and stays`);
        await page.locator('[data-mode="day"]').click();
        assert.equal(await page.locator('.blk').count(),1);
        await page.locator('[data-mode="week"]').click();
        assert.equal(await page.locator('.blk').count(),1);
        await page.locator('[data-cals]').first().click();
        await page.locator('[data-vis="fixture"]').click();
        await page.waitForFunction(() => document.querySelector('[data-vis]')?.getAttribute('aria-checked')==='false');
        assert.equal((await (await context.request.get(base+'/api/events')).json()).events.length,0);
        await page.locator('[data-vis="fixture"]').click();
        await page.waitForFunction(() => document.querySelector('[data-vis]')?.getAttribute('aria-checked')==='true');
        await page.locator('[data-close]').click();
        checks.push(`${size.width}/${scheme}: day/week/month, visibility and close parity`);
        await page.screenshot({path:path.join(out,`calendar-${size.width}-${scheme}.png`),fullPage:true});
        await page.reload();
        await page.waitForFunction(() => document.querySelector('[data-status]').textContent.includes('2 visible events'));
        checks.push(`${size.width}/${scheme}: refresh retains snapshot`);
        await page.locator('[data-cals]').first().click(); await page.locator('[data-close]').click();
        await page.evaluate(() => history.back());
        await page.waitForSelector('#wizard-app-back-notice');
        assert.ok(page.url().startsWith(base));
        checks.push(`${size.width}/${scheme}: first root Back stays with shared warning`);
        await context.close();
      }
    }
    assert.deepEqual(errors, []);
    fs.writeFileSync(path.join(out,'browser.json'), JSON.stringify({ok:true,count:checks.length,checks,errors},null,2));
    console.log(JSON.stringify({ok:true,count:checks.length,checks,errors},null,2));
  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exit(1);});
