/* Pinch to zoom inside the Wizard shell (issue 43 kick-back, 18 Nov: "pinch to zoom doesn't work" on Android in the
 * WizardOS app). In the shell, Calendar runs in a same-origin iframe and the shell binds its own window pinch
 * (spread = full screen, pinch in = tiles/overview) on the frame's document in the capture phase. An app that zooms
 * its own content claims two-finger gestures with <meta name="wizard-os-pinch" content="app"> (wizard-ux web/app.js
 * bindWinPinch / pinchClaimed). This test hosts Calendar in a frame with a faithful copy of that shell code and checks:
 * - (no switch since issue 43's switch-default) Calendar claims the pinch (meta present), a two-finger pinch zooms the hours and the shell's window
 *   pinch does not fire (no full screen, no window scale);
 * - a diagonal or mostly sideways pinch zooms too (only the fingers' distance counts, as on Android);
 * - real-finger timing: the first finger is already scrolling the hours when the second lands, and the pinch still
 *   zooms (a phone starts a scroll after a few pixels; 18 Nov kick-back, pinch tested on a real phone);
 * - Month: no claim, the shell keeps its window pinch.
 * Run against qa/live_fake.py (loopback dev mode, WIZARD_CORE_DIR=<wizard-ux>/web/core):
 *   CALENDAR_LIVE_URL=<qa/live_fake.py> node qa/pinch_in_shell.cjs */
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const base = process.env.CALENDAR_LIVE_URL || 'http://127.0.0.1:18930';

// The shell's window pinch, as in wizard-ux web/app.js (bindWinPinch + pinchClaimed), with the window/desk helpers
// reduced to one window whose full-screen state and live scale are recorded on window.shellLog.
const SHELL = `<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1">
<style>html,body{margin:0;height:100%}.win{position:absolute;inset:0}iframe{border:0;width:100%;height:100%}</style></head>
<body><div class="win" data-win="cal"><iframe src="${base}/" title="Calendar"></iframe></div><script>
window.shellLog = { full: 0, scaled: 0, pinches: 0 };
const winEl = (id) => document.querySelector('.win[data-win="' + id + '"]');
const desks = { d: { full: false, focus: null } }, deskOf = () => 'd', device = document.body;
function setFull(id, on) { if (on) shellLog.full++; desks.d.full = on; desks.d.focus = on ? id : null; }
function openOverview() {}
function bindWinPinch(root, fixedId) {
  if (root._wpinch) return; root._wpinch = true;
  let p = null;
  const dist = (a, b) => Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY);
  root.addEventListener('touchstart', e => {
    if (e.touches.length !== 2) return;
    const t0 = e.touches[0].target, el = t0.closest ? t0 : t0.parentElement;
    const id = fixedId || el.closest('.win')?.dataset.win;
    if (!id) { if (el.closest('.desk')) p = { id: null, d0: dist(e.touches[0], e.touches[1]), s: 1 }; return; }
    if (fixedId && pinchClaimed(fixedId)) return;
    shellLog.pinches++;
    p = { id, d0: dist(e.touches[0], e.touches[1]), s: 1 };
  }, { passive: true, capture: true });
  root.addEventListener('touchmove', e => {
    if (!p || e.touches.length !== 2) return;
    if (e.cancelable) e.preventDefault();
    p.s = dist(e.touches[0], e.touches[1]) / p.d0;
    const we = p.id && winEl(p.id); if (we) { shellLog.scaled++; we.style.setProperty('--pinch', String(Math.max(.9, Math.min(1.06, 1 + (p.s - 1) * .25)))); }
  }, { passive: false, capture: true });
  const end = () => {
    if (!p) return; const q = p; p = null;
    if (!q.id) return;
    const we = winEl(q.id); if (we) we.style.removeProperty('--pinch');
    const d = desks[deskOf(q.id)]; if (!d) return;
    if (q.s > 1.25 && !(d.full && d.focus === q.id)) setFull(q.id, true);
    else if (q.s < .8 && d.full) setFull(q.id, false);
  };
  root.addEventListener('touchend', e => { if (p && e.touches.length < 2) end(); }, { capture: true });
  root.addEventListener('touchcancel', end, { capture: true });
}
function pinchClaimed(id) { try { return winEl(id)?.querySelector('iframe')?.contentDocument?.querySelector('meta[name="wizard-os-pinch"]')?.content === 'app'; } catch (e) { return false; } }
document.querySelector('iframe').addEventListener('load', (e) => bindWinPinch(e.target.contentWindow.document, 'cal'));
</script></body></html>`;

(async () => {
  const browserPath = process.env.BROWSER_PATH;
  const browser = await chromium.launch(browserPath ? {headless:true, executablePath:browserPath} : {headless:true, channel:process.env.BROWSER_CHANNEL || 'chrome'});
  const checks = [], errors = [];
  const phone = {viewport: {width: 390, height: 844}, hasTouch: true, isMobile: true};
  const open = async () => {
    const context = await browser.newContext(phone);
    await context.clock.setFixedTime(new Date('2026-11-04T10:00:00+07:00'));
    await context.route(/\/__shell\.html$/, (route) => route.fulfill({contentType: 'text/html', body: SHELL}));
    const page = await context.newPage();
    page.on('pageerror', (e) => errors.push(String(e)));
    await page.goto(base + '/__shell.html');
    const frame = page.frames().find((f) => f !== page.mainFrame());
    await frame.waitForFunction(() => /visible events/.test(document.querySelector('[data-status]')?.textContent || ''));
    await frame.locator('[data-mode="week"]').click();
    await page.waitForTimeout(400); // switches loaded
    return {context, page, frame, cdp: await context.newCDPSession(page)};
  };
  const hour = (frame) => frame.evaluate(() => parseFloat(getComputedStyle(document.querySelector('[data-time]')).getPropertyValue('--hour')));
  const claimed = (frame) => frame.evaluate(() => document.querySelector('meta[name="wizard-os-pinch"]')?.content || '');
  const log = (page) => page.evaluate(() => ({...window.shellLog}));
  // Two fingers around (x, y): gap d0 -> d1 at angle deg (90 = one above the other, 0 = side by side).
  // scrollFirst: the first finger lands lower and drags up past the scroll threshold before the second finger lands.
  const pinch = async (cdp, x, y, d0, d1, deg = 90, n = 10, scrollFirst = false) => {
    const r = deg * Math.PI / 180, pts = (d) => [{x: x - Math.cos(r) * d / 2, y: y - Math.sin(r) * d / 2, id: 1}, {x: x + Math.cos(r) * d / 2, y: y + Math.sin(r) * d / 2, id: 2}];
    const p0 = pts(d0)[0];
    if (scrollFirst) {
      await cdp.send('Input.dispatchTouchEvent', {type: 'touchStart', touchPoints: [{...p0, y: p0.y + 30}]});
      for (let k = 1; k <= 6; k++) {
        await cdp.send('Input.dispatchTouchEvent', {type: 'touchMove', touchPoints: [{...p0, y: p0.y + 30 - k * 5}]});
        await new Promise((res) => setTimeout(res, 16));
      }
    } else await cdp.send('Input.dispatchTouchEvent', {type: 'touchStart', touchPoints: [p0]});
    await cdp.send('Input.dispatchTouchEvent', {type: 'touchStart', touchPoints: pts(d0)});
    for (let i = 1; i <= n; i++) {
      await cdp.send('Input.dispatchTouchEvent', {type: 'touchMove', touchPoints: pts(d0 + (d1 - d0) * i / n)});
      await new Promise((res) => setTimeout(res, 20));
    }
    await cdp.send('Input.dispatchTouchEvent', {type: 'touchEnd', touchPoints: [pts(d1)[0]]});
    await cdp.send('Input.dispatchTouchEvent', {type: 'touchEnd', touchPoints: []});
    await new Promise((res) => setTimeout(res, 250));
  };
  try {
    // ---- Calendar owns two fingers on its hours (always, no switch) ----
    let {context, page, frame, cdp} = await open();
    assert.equal(await claimed(frame), 'app', 'Calendar claims the pinch from the shell');
    let box = await frame.locator('[data-tbody]').boundingBox();
    const cx = box.x + box.width / 2, cy = box.y + box.height / 2;
    assert.equal(await hour(frame), 48);
    await pinch(cdp, cx, cy, 100, 200);
    const h1 = await hour(frame), l1 = await log(page);
    assert.ok(Math.abs(h1 - 96) <= 1, `in the shell, a vertical pinch out doubles the hours: ${h1}`);
    assert.equal(l1.full, 0, 'the shell does not make the window full screen');
    assert.equal(l1.scaled, 0, 'the shell does not scale the window');
    checks.push(`in the shell: vertical pinch 100 -> 200 px gives ${h1} px hours; shell window pinch untouched (${JSON.stringify(l1)})`);

    await pinch(cdp, cx, cy, 200, 100, 0); // side by side, pinch in
    const h2 = await hour(frame);
    assert.ok(Math.abs(h2 - 48) <= 1, `a sideways pinch in zooms back: ${h2}`);
    await pinch(cdp, cx, cy, 100, 150, 35); // diagonal, like a thumb and index finger
    const h3 = await hour(frame);
    assert.ok(Math.abs(h3 - 72) <= 1, `a diagonal pinch out zooms by the fingers' distance: ${h3}`);
    checks.push(`any finger angle: sideways pinch in -> ${h2} px, diagonal pinch out x1.5 -> ${h3} px`);

    // Real fingers: the first one is already scrolling when the second lands.
    const top0 = await frame.evaluate(() => document.querySelector('[data-tbody]').scrollTop);
    await pinch(cdp, cx, cy, 100, 200, 80, 10, true);
    const h4 = await hour(frame), l4 = await log(page);
    const top1 = await frame.evaluate(() => document.querySelector('[data-tbody]').scrollTop);
    assert.ok(Math.abs(h4 - 144) <= 1.5, `a pinch that starts while one finger is scrolling still zooms: ${h4}`);
    assert.equal(l4.full, 0, 'and the shell still does not go full screen');
    checks.push(`first finger already scrolling (scrollTop ${top0} -> ${top1}) when the second lands: x2 pinch -> ${h4} px`);

    // Month: nothing to zoom, so the shell gets its pinch back.
    await frame.locator('[data-mode="month"]').click();
    await page.waitForTimeout(300);
    assert.equal(await claimed(frame), '', 'Month view leaves two fingers to the shell');
    checks.push('Month view: no claim, the shell keeps its window pinch');
    await context.close();

    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ok: true, count: checks.length, checks}, null, 2));
  } catch (e) {
    console.log(JSON.stringify({ok: false, error: String(e && e.stack || e), checks, errors}, null, 2));
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
})();
