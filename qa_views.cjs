// QA: Day / Week / Month tabs at phone size. Usage: node qa_views.cjs [url]
const path = require('path'), fs = require('fs'), home = require('os').homedir();
const {launch,url:URL,shots:SHOTS,seed}=require('./qa/parity_helpers.cjs');
let pass = 0, fail = 0;
const ok = (c, m) => { console.log((c ? 'PASS ' : 'FAIL ') + m); c ? pass++ : fail++; };
const near = (a, b, t = 2) => Math.abs(a - b) <= t;
(async () => {
  fs.mkdirSync(SHOTS, { recursive: true });
  const b = await launch();
  const ctx = await b.newContext({ viewport: { width: 412, height: 892 }, hasTouch: true, isMobile: true, deviceScaleFactor: 2, timezoneId: 'Asia/Bangkok' });
  const p = await ctx.newPage(); const errs = []; p.on('pageerror', (e) => errs.push(String(e)));
  await seed(ctx.request);await p.goto(URL); await p.waitForSelector('.tg-cols .col');
  const api = await p.evaluate(async () => (await (await fetch('api/events')).json()).events);
  const tk = await p.evaluate(() => new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Bangkok', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date()));

  // Default = Week
  ok(await p.$eval('[data-mode="week"]', (x) => x.classList.contains('on')), 'Week is the default tab');
  ok(await p.$$eval('.tg-cols .col', (c) => c.length) === 7, 'week view shows 7 day columns');
  ok(await p.$eval('[data-scroll]', (s) => s.hidden), 'month grid hidden in week view');
  const tabs = await p.$eval('.tabs', (t) => { const r = t.getBoundingClientRect(); return { top: r.top, bottom: r.bottom, h: innerHeight }; });
  ok(tabs.bottom <= tabs.h + 0.5 && tabs.top > tabs.h - 80, 'Day/Week/Month tabs sit at the bottom of the screen');
  ok(await p.$eval(`.col[data-col="${tk}"]`, (c) => !!c.querySelector('.now')), 'today column has the now line');
  const nowVis = await p.$eval('.now', (n) => { const r = n.getBoundingClientRect(), b = document.querySelector('[data-tbody]').getBoundingClientRect(); return r.top >= b.top && r.top <= b.bottom; });
  ok(nowVis, 'grid opens scrolled to the current time');
  ok(!(await p.evaluate(() => document.documentElement.scrollWidth > innerWidth)), 'no horizontal overflow');

  // Event placement against API data: every timed event in this week sits at its start time
  const week = await p.$$eval('.tg-cols .col', (cs) => cs.map((c) => c.dataset.col));
  const timed = api.filter((e) => !e.allDay && week.includes(e.start.slice(0, 10)) && e.start.slice(0, 10) === e.end.slice(0, 10));
  let placed = 0, bad = [];
  for (const e of timed) {
    const top = await p.evaluate(({ id, d }) => { const el = document.querySelector(`.col[data-col="${d}"] [data-ev="${CSS.escape(id)}"]`); return el ? parseFloat(el.style.top) : null; }, { id: e.id, d: e.start.slice(0, 10) });
    const [h, m] = e.start.slice(11, 16).split(':').map(Number);
    if (top != null && near(top, (h * 60 + m) / 60 * 48)) placed++; else bad.push(e.title);
  }
  ok(timed.length > 0 && placed === timed.length, `all ${timed.length} timed events this week placed at their Bangkok start time ${bad.join(', ')}`);
  // Overlaps render side by side
  const overl = await p.$$eval('.tg-cols .col', (cs) => cs.some((c) => { const bs = [...c.querySelectorAll('.blk')].map((x) => x.getBoundingClientRect()); return bs.some((a, i) => bs.some((b2, j) => j > i && a.top < b2.bottom - 1 && b2.top < a.bottom - 1 && a.left < b2.right - 1 && b2.left < a.right - 1)); }));
  const sideBySide = await p.$$eval('.tg-cols .col', (cs) => cs.filter((c) => [...c.querySelectorAll('.blk')].some((x) => parseFloat(x.style.width.match(/calc\(([\d.]+)%/)[1]) < 100)).length);
  console.log('     columns with side-by-side events this week:', sideBySide);
  ok(!overl, 'overlapping events never cover each other');
  const allday = api.filter((e) => e.allDay && week.some((k) => k >= e.start.slice(0, 10) && k < e.end.slice(0, 10)));
  ok(await p.$$eval('.ad', (a) => a.length) === allday.length, `all-day row shows ${allday.length} all-day events`);
  await p.screenshot({ path: path.join(SHOTS, '1-week.png') });

  // Next / previous week
  const t0 = await p.$eval('[data-month]', (x) => x.textContent);
  await p.click('[data-next-month]');
  const w1 = await p.$$eval('.tg-cols .col', (cs) => cs.map((c) => c.dataset.col));
  const diff = (Date.parse(w1[0]) - Date.parse(week[0])) / 864e5;
  ok(diff === 7 && w1.length === 7, 'Next moves forward one week');
  await p.click('[data-month]');
  ok((await p.$$eval('.tg-cols .col', (cs) => cs[0].dataset.col)) === week[0] && (await p.$eval('[data-month]', (x) => x.textContent)) === t0, 'tapping the title returns to this week');

  // Week → Day by tapping a day heading
  const histBefore = await p.evaluate(() => history.length);
  const target = week[1];
  await p.click(`.dhd[data-dayview="${target}"]`);
  ok(await p.$eval('[data-mode="day"]', (x) => x.classList.contains('on')), 'tapping a day heading opens Day view');
  ok((await p.$$eval('.tg-cols .col', (cs) => cs.map((c) => c.dataset.col))).join() === target, 'Day view shows exactly that day');
  ok(await p.$eval(`.dhd[data-dayview="${target}"]`, (x) => x.classList.contains('sel')), 'week strip marks the selected day');
  await p.screenshot({ path: path.join(SHOTS, '2-day.png') });
  await p.click('[data-next-month]');
  ok((await p.$eval('.tg-cols .col', (c) => c.dataset.col)) === week[2], 'Next in Day view moves one day');

  // Month tab
  await p.click('[data-mode="month"]');
  ok(!(await p.$eval('[data-scroll]', (s) => s.hidden)) && await p.$$eval('.grid .day', (d) => d.length) >= 28 && await p.$eval('[data-time]', (t) => t.hidden), 'Month tab shows the month grid');
  // Month matches Day/Week: same header, no widget card, grid starts right under the header
  const mTop = await p.$eval('.grid', (g) => g.getBoundingClientRect().top);
  ok(mTop < 110 && (await p.$$eval('[data-widget]', (w) => w.length)) === 0, `Month grid sits right under the header like Day/Week (top ${mTop.toFixed(0)}px)`);
  await p.screenshot({ path: path.join(SHOTS, '3-month.png') });
  ok((await p.evaluate(() => history.length)) === histBefore, 'switching views adds no Back steps');

  // Header: Today button (shows today's date) + Settings gear; no refresh button
  ok(await p.$$eval('[data-refresh]', (x) => x.length) === 0, 'no refresh button in the header');
  ok((await p.$eval('[data-today-num]', (x) => x.textContent)) === String(+tk.slice(8)), "Today button shows today's date");
  await p.click('[data-next-month]'); await p.click('[data-next-month]');
  await p.click('[data-today-btn]');
  ok((await p.$$eval('.grid .day.today.sel', (d) => d.length)) === 1, 'Today button jumps Month back to today');
  await p.click('[data-mode="week"]'); await p.click('[data-next-month]'); await p.click('[data-next-month]');
  await p.click('[data-today-btn]');
  ok((await p.$$eval(`.col[data-col="${tk}"]`, (d) => d.length)) === 1, 'Today button jumps Week back to this week');
  await p.click('[data-cals]'); await p.waitForTimeout(300);
  const st = await p.$eval('[data-sheet]', (s) => s.innerText);
  ok(/Settings/.test(st) && /Sync now/.test(st) && /Calendars/i.test(st), 'gear opens Settings with Sync now and Calendars');
  ok(await p.$eval('[data-cals]', (b) => b.getAttribute('aria-label')) === 'Settings', 'gear is labelled Settings');
  await p.goBack(); await p.waitForTimeout(300);
  ok(await p.$eval('[data-sheet]', (s) => s.hidden) && p.url().includes('/wizard-calendar/'), 'Back closes Settings and stays in the app');
  await p.click('[data-mode="month"]');

  // Colours come from the skin palette, never Google's hex colours
  const colours = async () => p.$$eval('.blk, .ad, .agenda [data-ev] i, .day .dots i', (els) => [...new Set(els.map((e) => getComputedStyle(e).borderLeftColor + '|' + getComputedStyle(e).backgroundColor))]);
  const googleHex = ['rgb(159, 225, 231)', 'rgb(204, 166, 172)', 'rgb(22, 167, 101)'];
  await p.click('[data-mode="week"]');
  const neb = await p.$eval('.blk', (b) => getComputedStyle(b).borderLeftColor);
  ok(!googleHex.includes(neb), `week events use skin colours (${neb})`);
  // Actual shared host skin transport (two skins × light/dark), document identity,
  // selected tab/date, grid scroll and open overlay are exercised by qa/hosted.cjs.
  ok(await p.evaluate(()=>typeof CalendarAppearance.colourCalendars==='function' && typeof WizardApp.theme.onChange==='function' && !localStorage.getItem('wos.skin')), 'domain palette uses shared Appearance subscription, no app-owned skin storage (standalone has no host theme)');
  await p.click('[data-mode="month"]');

  // Persistence
  await p.reload(); await p.waitForSelector('.grid .day');
  ok(await p.$eval('[data-mode="month"]', (x) => x.classList.contains('on')), 'chosen view survives a reload');
  await p.click('[data-mode="week"]');
  await p.reload(); await p.waitForSelector('.tg-cols .col');
  ok(await p.$eval('[data-mode="week"]', (x) => x.classList.contains('on')), 'Week restored after reload');

  // Event sheet from the week grid; Back closes it and stays in the app on Week
  await p.click('.blk, .ad');
  ok(!(await p.$eval('[data-sheet]', (s) => s.hidden)), 'tapping an event in the week grid opens its details');
  await p.screenshot({ path: path.join(SHOTS, '4-event.png') });
  await p.goBack(); await p.waitForTimeout(300);
  ok(await p.$eval('[data-sheet]', (s) => s.hidden) && p.url().includes('/wizard-calendar/') && await p.$eval('[data-mode="week"]', (x) => x.classList.contains('on')), 'Back closes the event and stays in Week view');

  // Narrow phone
  await p.setViewportSize({ width: 360, height: 760 }); await p.waitForTimeout(200);
  ok(!(await p.evaluate(() => document.documentElement.scrollWidth > innerWidth)), 'no overflow at 360px');
  const colW = await p.$eval('.tg-cols .col', (c) => c.getBoundingClientRect().width);
  ok(colW >= 40, `week columns stay usable at 360px (${colW.toFixed(1)}px)`);
  await p.screenshot({ path: path.join(SHOTS, '5-week-360.png') });

  ok(errs.length === 0, 'no page errors ' + errs.join(' | '));
  await b.close();
  console.log(`\n${pass} passed, ${fail} failed`); process.exit(fail ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
