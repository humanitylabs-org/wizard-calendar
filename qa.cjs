// Ported live month/Settings/event suite. Disposable CALENDAR_URL only; QA_OUT for shots.
const path = require('path');
const {launch, url:URL, shots:SHOTS, seed, base}=require('./qa/parity_helpers.cjs');
let pass = 0, fail = 0;
const ok = (c, m) => { console.log((c ? 'PASS ' : 'FAIL ') + m); c ? pass++ : fail++; };
(async () => {
  require('fs').mkdirSync(SHOTS, { recursive: true });

  const b = await launch();
  const ctx = await b.newContext({ viewport: { width: 412, height: 892 }, hasTouch: true, isMobile: true, deviceScaleFactor: 2, ignoreHTTPSErrors: true });
  const p = await ctx.newPage(); await ctx.addInitScript(() => localStorage.setItem('wc.mode', 'month')); /* month-view suite */ const errs = []; p.on('pageerror', (e) => errs.push(String(e)));
  await seed(ctx.request);
  await p.route('**/api/events*', async route => { const response=await route.fetch(); const data=await response.json(); const failed=data.calendars.find(c=>c.id==='failed'); failed.ok=false; failed.error='Synthetic provider unavailable'; await route.fulfill({json:data}); });
  await p.goto(URL); await p.waitForSelector('.grid .day');
  await p.waitForFunction(() => document.querySelector('[data-foot]').innerText.includes('Updated'));
  ok(await p.$$eval('[data-widget]', (n) => n.length) === 0, 'no big widget card above the month');
  ok(await p.$$eval('.grid .day', (d) => d.length) >= 28, 'month grid renders');
  ok((await p.$eval('[data-foot]', (f) => f.innerText)).includes('Settings'), 'footer links to Settings');
  await p.screenshot({ path: path.join(SHOTS, '1-home.png') });

  // Calendars sheet from the header button
  await p.click('header [data-cals]'); await p.waitForTimeout(500);
  const sheet = await p.$eval('[data-sheet]', (s) => s.innerText);
  ok(!(await p.$eval('[data-sheet]', (s) => s.hidden)), 'Settings sheet opens from the gear');
  ok(/Synthetic Work\s+\d+ events/.test(sheet), 'lists the calendar with its event count');
  ok(/Synthetic Hidden\s+Hidden/.test(sheet), 'hidden calendar is listed as Hidden');
  ok(/Synthetic Failed\s+Sync failed/.test(sheet) && sheet.includes('Synthetic provider unavailable'), 'failed calendar retains Sync failed label and diagnostic');
  ok(await p.$eval('[data-close]', (x) => { const r = x.getBoundingClientRect(); return r.width >= 32 && r.top >= 0 && r.top < innerHeight; }), 'close button visible at the top of the sheet');
  // scroll the sheet to the bottom: close button must stay reachable
  await p.$eval('[data-sheet]', (s) => { s.scrollTop = s.scrollHeight; }); await p.waitForTimeout(150);
  ok(await p.$eval('[data-close]', (x) => { const r = x.getBoundingClientRect(); const s = document.querySelector('[data-sheet]').getBoundingClientRect(); return r.top >= s.top - 1 && r.bottom <= s.top + 60; }), 'close button stays pinned while the sheet scrolls');
  await p.$eval('[data-sheet]', (s) => { s.scrollTop = 0; });
  ok(/Open Connected accounts/.test(sheet), 'offers account setup through Connected accounts');
  await p.screenshot({ path: path.join(SHOTS, '2-calendars.png') });

  // Manual gog sign-in is explicitly superseded, never silently removed.
  for (const endpoint of ['start','finish']) {
    const response=await ctx.request.post(base+'/api/connect/'+endpoint,{data:{email:'synthetic@example.invalid',url:'not a callback'}});
    const data=await response.json();
    ok(response.status()===410 && data.setup_url==='/wizard-connectors/' && data.superseded_by==='Connected accounts', endpoint+' returns explained 410 and setup URL');
  }
  ok(await p.locator('[data-c-email], [data-c-url]').count()===0,'Calendar never collects OAuth credentials');

  // Close button closes the sheet and stays in the app
  await p.click('[data-close]'); await p.waitForTimeout(400);
  ok(await p.$eval('[data-sheet]', (s) => s.hidden), 'Close button closes the Calendars sheet');
  ok(p.url().includes('/wizard-calendar/'), 'closing stays in Wizard Calendar');
  // Hidden events are absent from the agenda data
  const evs = await p.evaluate(async () => (await (await fetch('api/events')).json()).events);
  ok(!evs.some((e) => e.cal === 'hidden'), 'no hidden-calendar events shown');
  const keys = evs.map((e) => e.title.trim().toLowerCase() + '|' + e.start);
  ok(new Set(keys).size === keys.length, `no duplicate events (${keys.length})`);
  // Event sheet: X closes it; Back closes it too and stays in app
  await p.click('.agenda [data-ev]'); await p.waitForTimeout(400);
  ok(await p.$eval('[data-close]', (x) => x.getBoundingClientRect().width >= 32), 'event sheet has a close button');
  await p.screenshot({ path: path.join(SHOTS, '3-event.png') });
  await p.click('[data-close]'); await p.waitForTimeout(400);
  ok(await p.$eval('[data-sheet]', (s) => s.hidden), 'close button closes the event sheet');
  await p.click('.agenda [data-ev]'); await p.waitForTimeout(300);
  await p.goBack(); await p.waitForTimeout(400);
  ok(await p.$eval('[data-sheet]', (s) => s.hidden) && p.url().includes('/wizard-calendar/'), 'Back closes the event sheet and stays in the app');
  await p.click('.agenda [data-ev]'); await p.waitForTimeout(300);
  await p.click('[data-sheet-back]', { position: { x: 200, y: 40 } }); await p.waitForTimeout(400);
  ok(await p.$eval('[data-sheet]', (s) => s.hidden), 'tapping outside closes the sheet');
  ok(errs.length === 0, 'no page errors ' + errs.join(' | '));
  await b.close();
  console.log(`\n${pass} passed, ${fail} failed`); process.exit(fail ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
