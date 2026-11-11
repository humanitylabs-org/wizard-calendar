// Real wizard-ux shell (routed, no backend) + real Calendar server under /wizard-calendar/. Open an event, tap Reply.
// Also STANDALONE=1: Calendar on its own at /wizard-calendar/ (a browser tab / home-screen icon).
const fs = require('fs'), path = require('path');
const { chromium } = require('playwright');
const UX = process.env.UX;
const CAL = process.env.CAL || 'http://127.0.0.1:18787';
const OUT = process.env.OUT || __dirname;
const ORIGIN = 'http://localhost:9481';
const type = f => f.endsWith('.js') || f.endsWith('.mjs') ? 'application/javascript' : f.endsWith('.css') ? 'text/css' : f.endsWith('.html') ? 'text/html' : f.endsWith('.json') ? 'application/json' : f.endsWith('.png') ? 'image/png' : 'image/svg+xml';
(async () => {
  const b = await chromium.launch({ executablePath: process.env.CHROMIUM || undefined });
  const res = [];
  const surfaces = process.env.STANDALONE ? ['standalone'] : (process.env.ONLY ? [process.env.ONLY] : ['phone', 'desktop']);
  for (const surface of surfaces) {
    const desktop = surface !== 'phone';
    const ctx = await b.newContext({ viewport: desktop ? { width: 1440, height: 900 } : { width: 390, height: 844 }, isMobile: !desktop, hasTouch: !desktop, serviceWorkers: 'block' });
    const sends = [];
    await ctx.route('**/*', async r => {
      const q = r.request(), u = new URL(q.url()), p = u.pathname, json = (o, s = 200) => r.fulfill({ status: s, contentType: 'application/json', body: JSON.stringify(o) });
      if (u.origin !== ORIGIN) return r.abort();
      if (p.startsWith('/wizard-calendar/') || p === '/wizard-calendar') {
        const resp = await r.fetch({ url: CAL + (p.slice('/wizard-calendar'.length) || '/') + u.search, headers: { ...q.headers(), origin: CAL } });
        return r.fulfill({ response: resp });
      }
      if (q.method() === 'GET' && p.startsWith('/wizard-os-home/')) {
        let f = p.slice('/wizard-os-home/'.length) || 'index.html'; f = path.join(UX, 'web', f);
        if (fs.existsSync(f) && fs.statSync(f).isFile()) return r.fulfill({ body: fs.readFileSync(f), contentType: type(f) });
        return r.fulfill({ status: 404, body: '' });
      }
      if (p === '/wizard/v1/setup') return json({ first_run: false });
      if (p.endsWith('/bootstrap')) return json({ bootstrap: 1, display: { agent_name: 'Wizard', owner_name: 'Tester' }, endpoints: { apps: '/wizard/v1/apps' } });
      if (p === '/wizard/v1/apps') return json({ apps: [{ id: 'wizard-calendar', name: 'Calendar', url: '/wizard-calendar/', source: 'apps.json', type: 'view', category: 'app' }] });
      if (/\/runs|\/messages|\/send/.test(p) && q.method() === 'POST') sends.push(p);
      if (p.endsWith('/api/sessions')) return json({ sessions: [], has_more: false });
      if (p.endsWith('/agents')) return json({ agents: [{ id: 'hermes', label: 'Wizard', is_default: true, status: 'running' }] });
      if (p.endsWith('/api/jobs')) return json({ jobs: [] });
      if (q.method() !== 'GET') return json({ accepted: true });
      return json({});
    });
    await ctx.addInitScript(() => { for (const [k, v] of Object.entries({ 'wos.wsync.off': 'true', 'wos.tour.v1': 'true', 'wos.tour.done': '1', 'wos.coached': 'true', 'wos.welcome.v1': 'done' })) localStorage.setItem(k, v); });
    const p = await ctx.newPage(); const errors = [];
    p.on('pageerror', e => errors.push(String(e)));
    let f;
    if (surface === 'standalone') {
      await p.goto(ORIGIN + '/wizard-calendar/');
      f = p.mainFrame();
    } else {
      await p.goto(ORIGIN + '/wizard-os-home/' + (desktop ? 'desktop.html' : ''));
      await p.waitForFunction(() => !!(window.__wos || window.__wux), null, { timeout: 60000 });
      await p.waitForTimeout(1500);
      await p.evaluate(() => WizCore.deeplink.route('/wizard-os-home/?open=wizard-calendar'));
      await p.waitForFunction(() => [...document.querySelectorAll('iframe')].some(f => f.src.includes('/wizard-calendar/')), null, { timeout: 30000 });
      await p.waitForTimeout(2500);
      await p.evaluate(() => document.getElementById('wosWelcome')?.remove());
      f = p.frames().find(f => f.url().includes('/wizard-calendar/'));
    }
    await f.waitForFunction(() => /visible events/.test(document.querySelector('[data-status]')?.textContent || ''), null, { timeout: 30000 });
    const hostInfo = await f.evaluate(() => ({ hosted: window.WizardApp?.hosted, href: location.href }));
    // go to 15 Oct 2026 (fixture day)
    await f.locator('[data-mode="month"]').click();
    for (let i = 0; i < 120; i++) {
      const m = (await f.locator('[data-month]').textContent()).match(/^([A-Z][a-z]+ \d{4})/)[1];
      if (m === 'October 2026') break;
      await f.locator(new Date(m + ' 15') > new Date('2026-10-15') ? '[data-prev]' : '[data-next-month]').click();
    }
    await f.locator('[data-day="2026-10-15"]').click();
    await f.locator('[data-ev="fixture:timed"]').first().click();
    await f.waitForSelector('[data-sheet][role="dialog"]');
    const reply = f.locator('[data-reply]');
    const shown = await reply.count() > 0;
    let status = null;
    if (shown) { await reply.click(); await p.waitForTimeout(1000); status = await f.locator('[data-c-msg]').innerText().catch(() => null); }
    const draft = surface === 'standalone' ? {} : await p.evaluate(() => JSON.parse(localStorage.getItem('wos.chat.drafts.v1') || '{}'));
    const name = surface + (process.env.TAG ? '-' + process.env.TAG : '');
    await p.screenshot({ path: path.join(OUT, name + '.png') });
    res.push({ surface: name, hostInfo, replyShown: shown, status, draftReply: draft.new?.reply || null, draftText: draft.new?.text ?? null, sends, errors: errors.slice(0, 5) });
    await ctx.close();
  }
  console.log(JSON.stringify(res, null, 2));
  await b.close();
})().catch(e => { console.error(e); process.exit(1); });
