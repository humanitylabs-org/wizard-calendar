/* Wizard Calendar — Day / Week / Month views (bottom tabs, Week default), widget, agenda, event sheet. Data: ./api/events (explicit snapshot import). */
(() => {
  const $ = (s) => document.querySelector(s);
  const API = new URL('api/events', location.href).pathname;
  let TZ = 'UTC';
  let doc = null, byDay = new Map(), view = null, sel = null, sheetOpen = false;
  const MODES = ['day', 'week', 'month'], HOUR = 48;
  let mode = MODES.includes(localStorage.getItem('wc.mode')) ? localStorage.getItem('wc.mode') : 'week';
  let needScroll = true; // scroll the time grid to "now" on the next render

  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const keyFmt = () => new Intl.DateTimeFormat('en-CA', { timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit' });
  const dayKey = (d) => keyFmt().format(d);
  const civil = (k) => { const [y, m, d] = k.split('-').map(Number); return new Date(Date.UTC(y, m - 1, d, 12)); };
  const keyOf = (c) => c.toISOString().slice(0, 10);
  const addDays = (k, n) => { const c = civil(k); c.setUTCDate(c.getUTCDate() + n); return keyOf(c); };
  const fmtC = (k, o) => new Intl.DateTimeFormat('en-GB', { timeZone: 'UTC', ...o }).format(civil(k));
  const fmtT = (iso) => new Intl.DateTimeFormat('en-GB', { timeZone: TZ, hour: '2-digit', minute: '2-digit' }).format(new Date(iso));
  const todayKey = () => dayKey(new Date());

  // Spread every event across the local days it covers.
  function index() {
    byDay = new Map();
    for (const e of doc?.events || []) {
      let a, b;
      if (e.allDay) { a = e.start.slice(0, 10); b = addDays(e.end.slice(0, 10), -1); if (b < a) b = a; }
      else {
        a = dayKey(new Date(e.start));
        const end = new Date(e.end);
        b = dayKey(new Date(end.getTime() - 1));
        if (b < a) b = a;
      }
      for (let k = a, i = 0; k <= b && i < 60; k = addDays(k, 1), i++) {
        if (!byDay.has(k)) byDay.set(k, []);
        byDay.get(k).push(e);
      }
    }
    for (const list of byDay.values()) list.sort((x, y) => (y.allDay - x.allDay) || x.start.localeCompare(y.start));
  }



  function renderGrid() {
    const [y, m] = view;
    $('[data-month]').textContent = new Intl.DateTimeFormat('en-GB', { timeZone: 'UTC', month: 'long', year: 'numeric' }).format(new Date(Date.UTC(y, m, 15)));
    const first = `${y}-${String(m + 1).padStart(2, '0')}-01`;
    const lead = (civil(first).getUTCDay() + 6) % 7; // Monday first
    const start = addDays(first, -lead);
    const tk = todayKey();
    let html = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map((d) => `<div class="wd">${d}</div>`).join('');
    for (let i = 0; i < 42; i++) {
      const k = addDays(start, i);
      const c = civil(k);
      if (i === 35 && c.getUTCMonth() !== m) break;
      const evs = byDay.get(k) || [];
      const dots = [...new Set(evs.map((e) => e.color))].slice(0, 3).map((c) => `<i style="background:${esc(c)}"></i>`).join('');
      const cls = ['day', c.getUTCMonth() !== m && 'out', k === tk && 'today', k === sel && 'sel', [0, 6].includes(c.getUTCDay()) && 'wkend'].filter(Boolean).join(' ');
      html += `<button class="${cls}" data-day="${k}" aria-label="${fmtC(k, { weekday: 'long', day: 'numeric', month: 'long' })}, ${evs.length} events"><span class="n">${c.getUTCDate()}</span><span class="dots">${dots}</span></button>`;
    }
    $('[data-grid]').innerHTML = html;
  }

  function evRow(e, k, now) {
    let tm;
    if (e.allDay) tm = 'All day';
    else {
      const sk = dayKey(new Date(e.start)), ek = dayKey(new Date(new Date(e.end) - 1));
      tm = sk === k ? fmtT(e.start) : 'cont.';
      tm += `<br>${ek === k ? fmtT(e.end) : '→'}`;
    }
    const s = new Date(e.allDay ? civil(e.start.slice(0, 10)) : e.start).getTime(), en = e.allDay ? civil(e.end.slice(0, 10)).getTime() - 12 * 36e5 : new Date(e.end).getTime();
    const cls = ['ev', en < now && 'past', !e.allDay && s <= now && en > now && 'now'].filter(Boolean).join(' ');
    return `<button class="${cls}" data-ev="${esc(e.id)}"><i style="background:${esc(e.color)}"></i><span class="tm">${tm}</span><span class="tt"><b>${esc(e.title)}</b>${e.location ? `<span>${esc(e.location)}</span>` : ''}</span></button>`;
  }

  function renderAgenda() {
    const tk = todayKey(), now = Date.now();
    let html = '', shown = 0;
    for (let i = 0, k = sel; i < 60 && (shown < 12 || i < 7); i++, k = addDays(k, 1)) {
      const evs = byDay.get(k) || [];
      if (!evs.length && i > 0) continue;
      const rel = k === tk ? 'Today' : k === addDays(tk, 1) ? 'Tomorrow' : fmtC(k, { weekday: 'long' });
      html += `<div class="dh${k === tk ? ' is-today' : ''}">${rel}<small>${fmtC(k, { day: 'numeric', month: 'long', year: k.slice(0, 4) === tk.slice(0, 4) ? undefined : 'numeric' })}</small></div>`;
      html += evs.length ? evs.map((e) => evRow(e, k, now)).join('') : `<div class="free">Nothing scheduled.</div>`;
      shown++;
    }
    $('[data-agenda]').innerHTML = html;
  }

  const fmtSynced = (iso) => new Intl.DateTimeFormat('en-GB', { timeZone: TZ, day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }).format(new Date(iso));
  function renderFoot() {
    if (!doc) return;
    const when = doc.syncedAt ? fmtSynced(doc.syncedAt) : 'never';
    const cals = (doc.calendars || []).filter((c) => !c.hidden).map((c) => `${esc(c.name)}`).join(' · ');
    const err = doc.syncError || (doc.errors || []).join('; ');
    const source = (doc.connected || []).length ? 'Updated' : 'Imported';
    $('[data-foot]').innerHTML = `Calendar · ${cals}<br>${source} ${when} · <button class="lnk" data-cals>Settings</button>${err ? `<br><span class="err">Sync issue: ${esc(err)}</span>` : ''}`;
  }

  // ---- Day / Week time grid ----
  const weekStart = (k) => addDays(k, -((civil(k).getUTCDay() + 6) % 7)); // Monday first
  const hm = (iso) => {
    const p = new Intl.DateTimeFormat('en-GB', { timeZone: TZ, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).formatToParts(new Date(iso));
    return +p.find((x) => x.type === 'hour').value * 60 + +p.find((x) => x.type === 'minute').value;
  };
  const minsIn = (iso, k) => { const dk = dayKey(new Date(iso)); return dk < k ? 0 : dk > k ? 1440 : hm(iso); };
  const nowMins = () => hm(new Date().toISOString());

  // Timed events of one day, packed into side-by-side columns where they overlap.
  function layoutDay(k) {
    const items = (byDay.get(k) || []).filter((e) => !e.allDay).map((e) => {
      const s = minsIn(e.start, k), en = minsIn(e.end, k);
      return { e, s, en: Math.max(en, s + 20) };
    }).sort((a, b) => a.s - b.s || b.en - a.en);
    let cluster = [], cols = [], end = -1;
    const flush = () => { for (const it of cluster) it.n = cols.length; cluster = []; cols = []; };
    for (const it of items) {
      if (it.s >= end) { flush(); end = -1; }
      let c = cols.findIndex((x) => x <= it.s);
      if (c < 0) { c = cols.length; cols.push(0); }
      cols[c] = it.en; it.col = c; cluster.push(it); end = Math.max(end, it.en);
    }
    flush();
    return items;
  }

  // All-day events as bars across the visible days, stacked into lanes.
  function allDayLanes(days) {
    const first = days[0], last = days[days.length - 1], seen = new Set(), bars = [];
    for (const k of days) for (const e of byDay.get(k) || []) {
      if (!e.allDay || seen.has(e.id)) continue;
      seen.add(e.id);
      const a = e.start.slice(0, 10), b = addDays(e.end.slice(0, 10), -1);
      const s = days.indexOf(a < first ? first : a), en = days.indexOf(b > last ? last : (b < a ? a : b));
      bars.push({ e, s, en, cutL: a < first, cutR: b > last });
    }
    bars.sort((x, y) => x.s - y.s || (y.en - y.s) - (x.en - x.s));
    const lanes = [];
    for (const bar of bars) {
      let l = lanes.findIndex((end) => end < bar.s);
      if (l < 0) { l = lanes.length; lanes.push(-1); }
      lanes[l] = bar.en; bar.lane = l;
    }
    return bars;
  }

  function renderTime() {
    const tk = todayKey(), now = Date.now(), ws = weekStart(sel);
    const strip = [...Array(7)].map((_, i) => addDays(ws, i));
    const days = mode === 'week' ? strip : [sel];
    const n = days.length, tg = $('[data-time]');
    tg.classList.toggle('is-day', mode === 'day');
    tg.style.setProperty('--n', n);

    // Title
    if (mode === 'week') {
      const a = civil(strip[0]), b = civil(strip[6]);
      const mo = (c, y) => new Intl.DateTimeFormat('en-GB', { timeZone: 'UTC', month: y ? 'long' : 'short', ...(y ? { year: 'numeric' } : {}) }).format(c);
      $('[data-month]').textContent = a.getUTCMonth() === b.getUTCMonth() ? mo(a, 1)
        : `${mo(a)} – ${mo(b)} ${b.getUTCFullYear()}`;
    } else {
      $('[data-month]').textContent = fmtC(sel, { weekday: 'short', day: 'numeric', month: 'long' }) + (sel.slice(0, 4) === tk.slice(0, 4) ? '' : ` ${sel.slice(0, 4)}`);
    }

    // Day heads: Week → tap opens that day; Day → week strip to hop between days.
    $('[data-heads]').innerHTML = strip.map((k) => {
      const c = civil(k), evs = (byDay.get(k) || []).length;
      const cls = ['dhd', k === tk && 'today', mode === 'day' && k === sel && 'sel', k < tk && 'past', [0, 6].includes(c.getUTCDay()) && 'wkend'].filter(Boolean).join(' ');
      return `<button class="${cls}" data-dayview="${k}" aria-label="${fmtC(k, { weekday: 'long', day: 'numeric', month: 'long' })}, ${evs} events"><span class="w">${fmtC(k, { weekday: 'short' })}</span><span class="n">${c.getUTCDate()}</span></button>`;
    }).join('');

    // All-day row
    const bars = allDayLanes(days);
    $('[data-allrow]').hidden = !bars.length;
    $('[data-lanes]').innerHTML = bars.map(({ e, s, en, lane, cutL, cutR }) =>
      `<button class="ad${cutL ? ' cut-l' : ''}${cutR ? ' cut-r' : ''}" data-ev="${esc(e.id)}" style="--c:${esc(e.color)};grid-column:${s + 1} / ${en + 2};grid-row:${lane + 1}">${esc(e.title)}</button>`).join('');

    // Hours + columns
    let hours = '';
    for (let h = 1; h < 24; h++) hours += `<span style="top:${h * HOUR}px">${String(h).padStart(2, '0')}:00</span>`;
    const cols = days.map((k) => {
      const blocks = layoutDay(k).map(({ e, s, en, col, n: nc }) => {
        const top = s / 60 * HOUR, h = Math.max((en - s) / 60 * HOUR, 18);
        const past = new Date(e.end).getTime() < now;
        const live = new Date(e.start).getTime() <= now && !past;
        const time = `${minsIn(e.start, k) === 0 && dayKey(new Date(e.start)) < k ? '…' : fmtT(e.start)}–${dayKey(new Date(new Date(e.end) - 1)) > k ? '…' : fmtT(e.end)}`;
        const sub = mode === 'day' ? `${time}${e.location ? ` · ${esc(e.location)}` : ''}` : (h >= 44 ? fmtT(e.start) : '');
        return `<button class="blk${past ? ' past' : ''}${live ? ' live' : ''}" data-ev="${esc(e.id)}" style="--c:${esc(e.color)};top:${top}px;height:${h - 2}px;left:calc(${col / nc * 100}% + 1px);width:calc(${100 / nc}% - 2px)" aria-label="${esc(e.title)}, ${time}"><b>${esc(e.title)}</b>${sub ? `<span>${sub}</span>` : ''}</button>`;
      }).join('');
      const nowLine = k === tk ? `<i class="now" style="top:${nowMins() / 60 * HOUR}px"></i>` : '';
      return `<div class="col${k === tk ? ' today' : ''}" data-col="${k}">${blocks}${nowLine}</div>`;
    }).join('');
    $('[data-tin]').innerHTML = `<div class="tg-hrs">${hours}</div><div class="tg-cols">${cols}</div>`;

    if (needScroll) {
      needScroll = false;
      let m;
      if (days.includes(tk)) m = nowMins() - 90;
      else {
        const starts = days.flatMap((k) => layoutDay(k).map((x) => x.s));
        m = starts.length ? Math.min(...starts) - 30 : 8 * 60;
      }
      $('[data-tbody]').scrollTop = Math.max(0, m) / 60 * HOUR;
    }
  }

  function applyMode() {
    const month = mode === 'month';
    $('[data-scroll]').hidden = !month;
    $('[data-time]').hidden = month;
    for (const b of document.querySelectorAll('[data-mode]')) { const on = b.dataset.mode === mode; b.classList.toggle('on', on); b.setAttribute('aria-selected', String(on)); }
    const unit = { day: 'day', week: 'week', month: 'month' }[mode];
    $('[data-prev]').setAttribute('aria-label', `Previous ${unit}`);
    $('[data-next-month]').setAttribute('aria-label', `Next ${unit}`);
  }

  function setMode(m) {
    if (!MODES.includes(m)) return;
    mode = m; localStorage.setItem('wc.mode', m); needScroll = true;
    if (m === 'month' && sel) view = [+sel.slice(0, 4), +sel.slice(5, 7) - 1];
    applyMode(); render();
  }

  function renderView() {
    if (!sel) return;
    if (mode === 'month') { renderGrid(); renderAgenda(); } else renderTime();
  }

  // Calendars take the skin's palette (CSS --k0…, --k-holiday), not Google's colours. Stable by calendar order.
  function skinColours() {
    const slot = new Map(); let n = 0;
    for (const c of doc.calendars || []) slot.set(c.id, /#holiday@/.test(c.id) ? 'var(--k-holiday)' : `var(--k${n++ % 5})`);
    for (const c of doc.calendars || []) c.color = slot.get(c.id);
    for (const e of doc.events || []) if (slot.has(e.cal)) e.color = slot.get(e.cal);
  }
  function renderTodayBtn() { $('[data-today-num]').textContent = +todayKey().slice(8); }
  function goToday() {
    sel = todayKey(); needScroll = true;
    if (mode === 'month') { view = [+sel.slice(0, 4), +sel.slice(5, 7) - 1]; $('[data-scroll]').scrollTo({ top: 0, behavior: 'smooth' }); renderView(); }
    else renderTime();
  }

  function render() { skinColours(); index(); renderTodayBtn(); renderView(); renderFoot(); $('[data-status]').textContent = doc.calendars?.length ? `${doc.events.length} visible events · ${TZ}` : 'No calendar yet. Open Settings to add a Google iCal link.'; }

  // Domain overlays use the shared Back stack, never app-owned root guards.
  let sheetBack = null;
  function openSheet(id) {
    const e = (doc?.events || []).find((x) => x.id === id);
    if (!e) return;
    const cal = (doc.calendars || []).find((c) => c.id === e.cal);
    let when;
    if (e.allDay) {
      const a = e.start.slice(0, 10), b = addDays(e.end.slice(0, 10), -1);
      when = fmtC(a, { weekday: 'long', day: 'numeric', month: 'long' }) + (b > a ? ` – ${fmtC(b, { weekday: 'short', day: 'numeric', month: 'short' })}` : '') + ' · All day';
    } else {
      const a = dayKey(new Date(e.start)), b = dayKey(new Date(new Date(e.end) - 1));
      when = `${fmtC(a, { weekday: 'long', day: 'numeric', month: 'long' })} · ${fmtT(e.start)} – ${b !== a ? fmtC(b, { day: 'numeric', month: 'short' }) + ' ' : ''}${fmtT(e.end)}`;
    }
    const maps = e.location ? `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(e.location)}` : '';
    const desc = e.description ? e.description.replace(/<br\s*\/?>/gi, '\n').replace(/<[^>]+>/g, '') : '';
    $('[data-sheet]').innerHTML = `<div class="sh-top"><span class="grab"></span><button class="x" data-close aria-label="Close">✕</button></div><h2>${esc(e.title)}</h2>
      <div class="row"><span class="k">When</span><span class="v">${when}</span></div>
      <div class="row"><span class="k">Calendar</span><span class="v chip"><i style="background:${esc(e.color)}"></i>${esc(cal?.name || '')}</span></div>
      ${e.location ? `<div class="row"><span class="k">Where</span><span class="v">${esc(e.location)}</span></div>` : ''}
      ${e.attendees ? `<div class="row"><span class="k">Guests</span><span class="v">${e.attendees}</span></div>` : ''}
      ${desc ? `<div class="row"><span class="k">Notes</span><span class="v">${esc(desc)}</span></div>` : ''}
      <div class="acts">${e.meet ? `<a href="${esc(e.meet)}" target="_blank" rel="noopener">Join Meet</a>` : ''}${maps ? `<a href="${esc(maps)}" target="_blank" rel="noopener">Map</a>` : ''}${e.link ? `<a href="${esc(e.link)}" target="_blank" rel="noopener">Open in Google Calendar</a>` : ''}</div>`;
    showSheet();
    if (!sheetOpen) { sheetOpen = true; sheetBack = WizardApp.back.push(() => { closeSheet(); return true; }); }
  }
  // role/aria-modal only while open: the Wizard shell reads them to confirm a Back press closed something.
  function showSheet() { const sh = $('[data-sheet]'); sh.hidden = false; sh.setAttribute('role', 'dialog'); sh.setAttribute('aria-modal', 'true'); $('[data-sheet-back]').hidden = false; }
  function hideSheet() { const sh = $('[data-sheet]'); sh.hidden = true; sh.removeAttribute('role'); sh.removeAttribute('aria-modal'); $('[data-sheet-back]').hidden = true; }
  function closeSheet() { sheetOpen = false; hideSheet(); sheetBack?.release(); sheetBack = null; }
  if (!window.WizardApp) {
    document.querySelector('[data-status]').textContent = 'Wizard core is missing. Follow the standalone setup in README.md.';
    return;
  }
  WizardApp.ready({ name: 'Calendar', version: '0.1.0' });

  // Read-only sources: the private iCal URL is submitted once and never rendered back into the page.
  function openCals() {
    const list = (doc?.calendars || []).map(c => `<button class="cal${c.hidden ? ' off' : ''}" data-vis="${esc(c.id)}" role="switch" aria-checked="${!c.hidden}"><i style="background:${esc(c.color)}"></i><span class="nm">${esc(c.name)}<small>${c.hidden ? 'Hidden' : `${c.count} events`}</small></span><span class="sw"></span></button>`).join('');
    const sources = (doc?.connected || []).map(source => `<div class="source"><span class="nm">${esc(source.name)}<small>${source.error ? esc(source.error) : source.lastSyncedAt ? `Updated ${esc(fmtSynced(source.lastSyncedAt))}` : 'Google iCal'}</small></span><button class="remove" data-remove-source="${esc(source.id)}">Remove</button></div>`).join('');
    $('[data-sheet]').innerHTML = `<div class="sh-top"><span class="grab"></span><button class="x" data-close aria-label="Close">✕</button></div><h2>Settings</h2><p class="note">Calendar is read-only. Add a private Google iCal link to see that calendar here.</p><div class="sync"><span>${doc?.syncedAt ? `Updated ${esc(fmtSynced(doc.syncedAt))}` : 'No calendar added'}</span><button class="btn" data-sync>Sync now</button></div><div class="sec">Your calendars</div>${sources || '<p class="note">No Google iCal calendars added.</p>'}<div class="sec">Add calendar</div><label class="field">Calendar name<input type="text" data-source-name maxlength="300" autocomplete="off" placeholder="Personal"></label><label class="field">Google iCal link<input type="text" data-source-url maxlength="4096" inputmode="url" autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="https://calendar.google.com/…/basic.ics"></label><p class="note">Use the private iCal link from Google Calendar settings. Anyone with that link can read the calendar, so it stays private on this Wizard.</p><button class="btn" data-add-source>Add calendar</button><div class="sec">Visible calendars</div>${list || '<p class="note">Calendars appear here after they are added.</p>'}<div class="sec">Advanced</div><p class="note">Snapshot import replaces the current visible snapshot, not your Google calendar. Your saved iCal links remain and return on the next sync.</p><input type="file" data-import accept="application/json,.json" aria-label="Import snapshot JSON"><a class="btn" href="api/export" download="calendar-snapshot.json">Export snapshot</a><div class="msg" data-c-msg role="status"></div>`;
    showSheet();
    if (!sheetOpen) { sheetOpen = true; sheetBack = WizardApp.back.push(() => { closeSheet(); return true; }); }
  }

  async function post(path, body) {
    const r = await fetch(new URL(path, location.href).pathname, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.error || `Request failed (${r.status})`);
    return d;
  }
  async function toggleCal(btn) {
    const id = btn.dataset.vis, visible = btn.classList.contains('off');
    btn.classList.toggle('off', !visible); btn.setAttribute('aria-checked', String(visible)); btn.disabled = true;
    btn.querySelector('small').textContent = visible ? 'Showing…' : 'Hidden';
    try { await post('api/calendars/visibility', { id, visible }); await load(false); if (sheetOpen) openCals(); }
    catch (e) { btn.classList.toggle('off', visible); btn.disabled = false; say(e.message); }
  }

  async function addSource(btn) {
    const name = $('[data-source-name]')?.value.trim(), url = $('[data-source-url]')?.value.trim();
    if (!name || !url) return say('Enter a calendar name and Google iCal link.');
    const hold = WizardApp.update.hold('adding calendar source');
    btn.disabled = true; btn.textContent = 'Adding…';
    try {
      await post('api/sources', { name, url });
      await load(false); openCals(); say('Calendar added.', true);
    } catch (e) { btn.disabled = false; btn.textContent = 'Add calendar'; say(e.message); }
    finally { hold.release(); }
  }

  async function removeSource(btn) {
    const hold = WizardApp.update.hold('removing calendar source');
    btn.disabled = true;
    try {
      await post('api/sources/remove', { id: btn.dataset.removeSource });
      await load(false); openCals(); say('Calendar removed.', true);
    } catch (e) { btn.disabled = false; say(e.message); }
    finally { hold.release(); }
  }

  const say = (t, ok) => { const m = $('[data-c-msg]'); if (m) { m.className = `msg ${ok ? 'ok' : 'err'}`; m.textContent = t; } };

  document.addEventListener('change', async event => {
    if (!event.target.matches('[data-import]')) return;
    const input = event.target, file = input.files[0];
    if (!file) return;
    if (!confirm('Replace the current snapshot with this file?')) { input.value = ''; return; }
    const hold = WizardApp.update.hold('calendar import');
    input.disabled = true;
    try {
      if (file.size > 4 * 1024 * 1024) throw new Error('File exceeds 4 MiB.');
      const result = await post('api/import', JSON.parse(await file.text()));
      await load(false);
      if (doc?.contentSha256 !== result.contentSha256) throw new Error('Import readback failed. Reload to verify.');
      if (sheetOpen) { openCals(); say(`Imported ${result.events} events.`, true); }
    } catch (e) { say(e.message); input.disabled = false; }
    finally { hold.release(); }
  });

  function select(k, scroll) {
    sel = k; view = [+k.slice(0, 4), +k.slice(5, 7) - 1];
    renderGrid(); renderAgenda();
    if (scroll) $('[data-agenda]').scrollIntoView({ block: 'start', behavior: 'smooth' });
  }

  document.addEventListener('click', (ev) => {
    const t = ev.target.closest('button, [data-sheet-back]');
    if (!t) return;
    if (t.matches('[data-sheet-back], [data-close]')) return closeSheet();
    if (t.matches('[data-add-source]')) return addSource(t);
    if (t.dataset.removeSource) return removeSource(t);
    if (t.dataset.vis) return toggleCal(t);
    if (t.dataset.ev) return openSheet(t.dataset.ev);
    if (t.dataset.day) return select(t.dataset.day, true);
    if (t.dataset.mode) return setMode(t.dataset.mode);
    if (t.dataset.dayview) { sel = t.dataset.dayview; return setMode('day'); }
    if (t.matches('[data-month]')) {
      return goToday();
    }
    if (t.matches('[data-today-btn]')) return goToday();
    if (t.matches('[data-sync]')) return syncNow(t);
    if (mode !== 'month' && t.matches('[data-prev], [data-next-month]')) {
      const dir = t.matches('[data-prev]') ? -1 : 1, tk = todayKey();
      sel = addDays(sel, dir * (mode === 'week' ? 7 : 1));
      if (mode === 'week' && weekStart(sel) === weekStart(tk)) sel = tk;
      needScroll = true; return renderTime();
    }
    if (t.matches('[data-prev], [data-next-month]')) {
      const d = new Date(Date.UTC(view[0], view[1] + (t.matches('[data-prev]') ? -1 : 1), 1));
      view = [d.getUTCFullYear(), d.getUTCMonth()];
      sel = keyOf(new Date(Date.UTC(view[0], view[1], 1, 12)));
      if (sel.slice(0, 7) === todayKey().slice(0, 7)) sel = todayKey();
      renderGrid(); renderAgenda(); return;
    }
    if (t.matches('[data-cals]')) return openCals();

  });

  // Drag the sheet's top bar down to close it.
  let gy = null;
  $('[data-sheet]').addEventListener('touchstart', (e) => { gy = e.target.closest('.sh-top') ? e.touches[0].clientY : null; }, { passive: true });
  $('[data-sheet]').addEventListener('touchend', (e) => { if (gy != null && e.changedTouches[0].clientY - gy > 60) closeSheet(); gy = null; }, { passive: true });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && sheetOpen) closeSheet(); });

  // Horizontal swipe on the grid changes month.
  let sx = null, sy = null;
  $('[data-grid]').addEventListener('touchstart', (e) => { sx = e.touches[0].clientX; sy = e.touches[0].clientY; }, { passive: true });
  $('[data-grid]').addEventListener('touchend', (e) => {
    if (sx == null) return;
    const dx = e.changedTouches[0].clientX - sx, dy = e.changedTouches[0].clientY - sy; sx = null;
    if (Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy) * 1.5) $(dx < 0 ? '[data-next-month]' : '[data-prev]').click();
  }, { passive: true });

  // Horizontal swipe on the time grid changes week/day.
  let tx = null, ty = null;
  $('[data-time]').addEventListener('touchstart', (e) => { tx = e.touches[0].clientX; ty = e.touches[0].clientY; }, { passive: true });
  $('[data-time]').addEventListener('touchend', (e) => {
    if (tx == null) return;
    const dx = e.changedTouches[0].clientX - tx, dy = e.changedTouches[0].clientY - ty; tx = null;
    if (Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy) * 1.5) $(dx < 0 ? '[data-next-month]' : '[data-prev]').click();
  }, { passive: true });

  async function syncNow(btn) {
    btn.disabled = true; btn.textContent = 'Syncing…';
    try {
      const result = await post('api/sync', {});
      await load(false);
      if (sheetOpen) { openCals(); say(result.failed ? `${result.failed} calendar failed to sync.` : 'Calendars updated.', !result.failed); }
    } catch (e) { btn.disabled = false; btn.textContent = 'Sync now'; say(e.message); }
  }

  async function load(refresh) {
    try {
      const r = await fetch(API + (refresh ? '?refresh=1' : ''), { cache: 'no-store' });
      if (!r.ok) throw new Error(`Load failed (${r.status})`);
      const d = await r.json();
      if (d.timezone) TZ = d.timezone;
      doc = d;
      if (!sel) sel = todayKey();
      if (!view) view = [+sel.slice(0, 4), +sel.slice(5, 7) - 1];
      render();
      if (refresh && d.syncing) { await new Promise((ok) => setTimeout(ok, 2500)); return load(false); }
    } catch (err) {
      $('[data-status]').textContent = 'Unable to load calendar. Open Settings and Sync now to retry.';
      $('[data-foot]').textContent = 'Unable to load calendar. Open Settings and Sync now to retry.';
      throw err;
    }
  }

  sel = null; view = null;
  applyMode();
  renderTodayBtn();
  load(false).catch(() => {});
  setInterval(() => { renderTodayBtn(); if (doc && mode !== 'month') renderTime(); }, 60e3);
  WizardApp.theme.onChange(() => { if (doc) render(); });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) load(false).catch(() => {}); });
})();
