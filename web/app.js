/* Wizard Calendar — Day / Week / Month views (bottom tabs, Week default), agenda, event sheet. Data: ./api/events — connected
 * Google/Microsoft calendars (through their apps; add, edit, delete, answer invites), private iCal links and snapshot import. */
(() => {
  const $ = (s) => document.querySelector(s);
  const API = new URL('api/events', location.href).pathname;
  let TZ = 'UTC';
  let doc = null, byDay = new Map(), view = null, sel = null, sheetOpen = false;
  const MODES = ['day', 'week', 'month'], HOUR = 48;
  let mode = MODES.includes(localStorage.getItem('wc.mode')) ? localStorage.getItem('wc.mode') : 'week';
  let needScroll = true; // scroll the time grid to "now" on the next render
  let range = null, loading = null; // the loaded live window [from, to)

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

  const liveCals = () => (doc?.calendars || []).filter((c) => c.live);
  function render() {
    skinColours(); index(); renderTodayBtn(); renderView(); renderFoot(); renderSugg();
    const none = !doc.calendars?.length;
    $('[data-hello]').hidden = !none;
    document.querySelector('.app').classList.toggle('is-empty', none);
    $('[data-new]').hidden = !liveCals().length;
    $('[data-status]').textContent = none ? '' : `${doc.events.length} visible events · ${TZ}`;
    $('[data-status]').hidden = none;
  }

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
      ${e.guests ? `<div class="row"><span class="k">Guests</span><span class="v">${esc(e.guests)}</span></div>` : ''}
      ${desc ? `<div class="row"><span class="k">Notes</span><span class="v">${esc(desc)}</span></div>` : ''}
      <div class="acts">${e.meet ? `<a href="${esc(e.meet)}" target="_blank" rel="noopener">Join Meet</a>` : ''}${maps ? `<a href="${esc(maps)}" target="_blank" rel="noopener">Map</a>` : ''}${e.link ? `<a href="${esc(e.link)}" target="_blank" rel="noopener">${e.live ? 'Open in ' + (cal?.source === 'microsoft' ? 'Outlook' : 'Google Calendar') : 'Open in Google Calendar'}</a>` : ''}</div>
      ${e.live ? liveActions(e) : ''}<div class="msg" data-c-msg role="status"></div>`;
    showSheet();
    if (!sheetOpen) { sheetOpen = true; sheetBack = WizardApp.back.push(() => { closeSheet(); return true; }); }
  }
  // role/aria-modal only while open: the Wizard shell reads them to confirm a Back press closed something.
  // ---- connected calendars: answer, add, edit, delete (the source app does the work) ----
  const RSVP = [['accepted', 'Going'], ['tentative', 'Maybe'], ['declined', 'Not going']];
  function liveActions(e) {
    const L = e.live;
    const rsvp = L.invited ? `<div class="sec">Your answer</div><div class="rsvp">${RSVP.map(([v, t]) => `<button class="chip-btn${L.my_response === v ? ' on' : ''}" data-rsvp="${v}" data-evid="${esc(e.id)}" aria-pressed="${L.my_response === v}">${t}</button>`).join('')}</div>` : '';
    const edit = L.is_organizer || !L.invited ? `<button class="btn" data-edit="${esc(e.id)}">Edit</button><button class="btn danger" data-del="${esc(e.id)}">Delete</button>` : '';
    return `${rsvp}${edit ? `<div class="live-acts">${edit}</div>` : ''}${L.recurring ? '<p class="note">Repeating event: changes here apply to this one only where your calendar allows; otherwise to the series.</p>' : ''}`;
  }
  async function livePost(path, body) {
    const r = await fetch(new URL(path, location.href).pathname, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-Wizard-Request': 'calendar' }, body: JSON.stringify(body) });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.error || `Request failed (${r.status})`);
    return d;
  }
  const evById = (id) => (doc?.events || []).find((x) => x.id === id);
  const target = (e) => ({ account: e.live.account, calendar_id: e.live.calendar_id, id: e.live.id });
  async function rsvp(btn) {
    const e = evById(btn.dataset.evid); if (!e) return;
    for (const b of btn.parentElement.children) { b.disabled = true; }
    try { await livePost('api/live/respond', { ...target(e), response: btn.dataset.rsvp }); await load(false); openSheet(e.id); say('Answer sent.', true); }
    catch (err) { for (const b of btn.parentElement.children) b.disabled = false; say(err.message); }
  }
  async function del(btn) {
    const e = evById(btn.dataset.del); if (!e) return;
    if (btn.dataset.sure !== '1') { btn.dataset.sure = '1'; btn.textContent = 'Delete for good?'; return; }
    btn.disabled = true;
    try { await livePost('api/live/delete', target(e)); closeSheet(); await load(false); }
    catch (err) { btn.disabled = false; say(err.message); }
  }
  const pad = (n) => String(n).padStart(2, '0');
  const hhmm = (mins) => `${pad(Math.floor(mins / 60) % 24)}:${pad(mins % 60)}`;
  function openForm(e, preset) {
    const cals = liveCals(); if (!cals.length) return connect();
    const all = e ? e.allDay : !!preset?.allDay;
    const day = e ? (e.allDay ? e.start.slice(0, 10) : dayKey(new Date(e.start))) : (preset?.day || sel || todayKey());
    const endDay = e ? (e.allDay ? addDays(e.end.slice(0, 10), -1) : dayKey(new Date(e.end))) : day;
    const sm = e && !e.allDay ? hm(e.start) : (preset?.mins ?? Math.min(23 * 60, Math.ceil((nowMins() + 1) / 30) * 30));
    const em = e && !e.allDay ? hm(e.end) : Math.min(sm + 60, 23 * 60 + 59);
    const opts = cals.map((c) => `<option value="${esc(c.id)}"${e && e.cal === c.id ? ' selected' : ''}>${esc(c.name)}</option>`).join('');
    $('[data-sheet]').innerHTML = `<div class="sh-top"><span class="grab"></span><button class="x" data-close aria-label="Close">✕</button></div><h2>${e ? 'Edit event' : 'New event'}</h2>
      <form class="ev-form" data-form novalidate>
        <label class="field">Title<input type="text" name="title" maxlength="300" required value="${esc(e?.title || '')}" autocomplete="off"></label>
        <label class="check"><input type="checkbox" name="allDay"${all ? ' checked' : ''}> All day</label>
        <div class="two"><label class="field">Starts<input type="date" name="day" value="${day}" required></label><label class="field t">Time<input type="time" name="start" value="${hhmm(sm)}" step="300"></label></div>
        <div class="two"><label class="field">Ends<input type="date" name="endDay" value="${endDay}" required></label><label class="field t">Time<input type="time" name="end" value="${hhmm(em)}" step="300"></label></div>
        <label class="field">Where<input type="text" name="location" maxlength="300" value="${esc(e?.location || '')}" autocomplete="off"></label>
        <label class="field">Notes<textarea name="description" rows="3" maxlength="4000">${esc(e?.description || '')}</textarea></label>
        ${e ? '' : `<label class="field">Calendar<select name="cal">${opts}</select></label>`}
        <p class="note">${e ? 'Saved to' : 'Adds the event to'} your ${e ? esc((cals.find((c) => c.id === e.cal) || {}).name || 'calendar') : 'chosen calendar'}. Times are ${esc(TZ)}.</p>
        <div class="live-acts"><button class="btn primary" type="submit">${e ? 'Save' : 'Add event'}</button></div>
        <div class="msg" data-c-msg role="status"></div>
      </form>`;
    const f = $('[data-form]');
    const sync = () => { for (const n of f.querySelectorAll('.t')) n.hidden = f.allDay.checked; };
    f.allDay.addEventListener('change', sync); sync();
    f.day.addEventListener('change', () => { if (f.endDay.value < f.day.value) f.endDay.value = f.day.value; });
    f.addEventListener('submit', (ev) => { ev.preventDefault(); save(f, e); });
    showSheet();
    if (!sheetOpen) { sheetOpen = true; sheetBack = WizardApp.back.push(() => { closeSheet(); return true; }); }
    if (!e) setTimeout(() => f.title.focus(), 60);
  }
  async function save(f, e) {
    const title = f.title.value.trim();
    if (!title) return say('Give the event a title.');
    if (!f.day.value || !f.endDay.value) return say('Choose the dates.');
    const all = f.allDay.checked;
    const body = { title, location: f.location.value.trim(), description: f.description.value };
    if (all) { body.start = f.day.value; body.end = addDays(f.endDay.value < f.day.value ? f.day.value : f.endDay.value, 1); }
    else {
      body.start = `${f.day.value}T${f.start.value || '09:00'}`; body.end = `${f.endDay.value}T${f.end.value || '10:00'}`; body.time_zone = TZ;
      if (body.end <= body.start) return say('The event ends before it starts.');
    }
    const btn = f.querySelector('[type=submit]'); btn.disabled = true; btn.textContent = 'Saving…';
    try {
      if (e) await livePost('api/live/update', { ...target(e), ...body });
      else await livePost('api/live/create', { account: f.cal.value, ...body });
      sel = f.day.value; closeSheet(); await load(false);
    } catch (err) { btn.disabled = false; btn.textContent = e ? 'Save' : 'Add event'; say(err.message); }
  }
  function connect(source, backToSettings) {
    if (!window.WizardConnect) return;
    if (sheetOpen) closeSheet();
    window.WizardConnect.open({ purpose: 'calendar', source, onDone: async () => {
      range = null;
      await load(false).catch(() => {});
      if (backToSettings) openCals();
    } });
  }

  // ---- agents' suggestions (Suggest only): kept by the Google / Microsoft apps, shown here with Approve / Dismiss.
  // Only the owner's tap applies one: Calendar's server forwards it with Calendar's App Manager grant. ----
  const ANSWER = { accepted: 'Going', tentative: 'Maybe', declined: 'Not going' };
  const sgKey = (s) => `${s.source}:${s.id}`;
  const sgEvent = (s) => (doc?.events || []).find((e) => e.live && e.live.id === s.event_id && (!s.account || e.live.account === s.account));
  function sgPart(v) {
    if (!v || typeof v !== 'string') return null;
    if (/^\d{4}-\d{2}-\d{2}$/.test(v)) return { day: v, all: true };
    if (/(Z|[+-]\d{2}:\d{2})$/.test(v)) return { day: dayKey(new Date(v)), time: fmtT(v) };
    return { day: v.slice(0, 10), time: v.slice(11, 16) };
  }
  function sgWhen(start, end) {
    const a = sgPart(start), b = sgPart(end);
    if (!a) return '';
    const d = (k) => fmtC(k, { weekday: 'short', day: 'numeric', month: 'short' });
    if (a.all) { const last = b ? addDays(b.day, -1) : a.day; return `${d(a.day)}${last > a.day ? ` – ${d(last)}` : ''} · All day`; }
    return `${d(a.day)} · ${a.time}${b ? `–${b.day !== a.day ? `${d(b.day)} ` : ''}${b.time}` : ''}`;
  }
  function evWhen(e) { return e ? (e.allDay ? sgWhen(e.start.slice(0, 10), e.end.slice(0, 10)) : sgWhen(e.start, e.end)) : ''; }
  function sgTitle(s) {
    const ev = sgEvent(s), name = ev?.title || s.title || 'an event';
    if (s.action === 'respond') return `Answer “${name}”: ${ANSWER[s.response] || s.response}`;
    if (s.action === 'delete') return `Delete “${name}”`;
    if (s.action === 'update') return `Change “${ev?.title || 'an event'}”`;
    return `Add “${s.title || 'New event'}”`;
  }
  function sgSub(s) {
    const ev = sgEvent(s), bits = [];
    if (s.action === 'create') bits.push(sgWhen(s.start, s.end));
    else if (s.action === 'update') {
      if (s.title && s.title !== ev?.title) bits.push(`rename to “${s.title}”`);
      if (s.start) bits.push(`move to ${sgWhen(s.start, s.end)}`);
      if (!bits.length) bits.push('new details');
    } else bits.push(evWhen(ev));
    return bits.filter(Boolean).join(' · ');
  }
  const pending = () => doc?.suggestions || [];
  function renderSugg() {
    const box = $('[data-sugg]'), list = pending();
    box.hidden = !list.length;
    if (!list.length) { box.replaceChildren(); return; }
    const s = list[0];
    box.innerHTML = `<div class="wcs-sg"><button class="wcs-sg-main" data-sg-open><span class="wcs-sg-who">Your agent suggests</span><b>${esc(sgTitle(s))}</b><span>${esc(sgSub(s))}</span></button>
      <span class="wcs-sg-acts"><button class="wcs-btn" data-sg-dismiss="${esc(sgKey(s))}">Dismiss</button><button class="wcs-btn wcs-primary" data-sg-approve="${esc(sgKey(s))}">Approve</button></span></div>
      ${list.length > 1 ? `<button class="wcs-sg-more" data-sg-open>${list.length - 1} more suggestion${list.length > 2 ? 's' : ''}</button>` : ''}<p class="wcs-sg-err" data-sg-err role="alert"></p>`;
  }
  function openSuggestions() {
    const list = pending();
    if (!list.length) return;
    const rows = list.map((s) => {
      const ev = sgEvent(s), cal = (doc.calendars || []).find((c) => c.id === s.account);
      const facts = [['Calendar', cal?.name || s.email], s.location && ['Where', s.location], s.attendees?.length && ['Guests', s.attendees.join(', ')],
        s.description && ['Notes', s.description], ev && s.action !== 'create' && ['Now', evWhen(ev)]].filter(Boolean);
      return `<div class="wcs-sgi" data-sg-row="${esc(sgKey(s))}"><b>${esc(sgTitle(s))}</b><span class="wcs-sgi-when">${esc(sgSub(s))}</span>
        ${facts.map(([k, v]) => `<div class="row"><span class="k">${esc(k)}</span><span class="v">${esc(v)}</span></div>`).join('')}
        <div class="wcs-sg-acts"><button class="wcs-btn" data-sg-dismiss="${esc(sgKey(s))}">Dismiss</button><button class="wcs-btn wcs-primary" data-sg-approve="${esc(sgKey(s))}">Approve</button></div></div>`;
    }).join('');
    $('[data-sheet]').innerHTML = `<div class="sh-top"><span class="grab"></span><button class="x" data-close aria-label="Close">✕</button></div><h2>Suggestions</h2>
      <p class="note">Your agent suggested ${list.length === 1 ? 'this change' : 'these changes'}. Nothing changes until you approve.</p>${rows}<div class="msg" data-c-msg role="status"></div>`;
    showSheet();
    if (!sheetOpen) { sheetOpen = true; sheetBack = WizardApp.back.push(() => { closeSheet(); return true; }); }
  }
  async function decide(btn, approve) {
    const key = approve ? btn.dataset.sgApprove : btn.dataset.sgDismiss;
    const s = pending().find((x) => sgKey(x) === key); if (!s) return;
    const acts = btn.parentElement; for (const b of acts.children) b.disabled = true;
    btn.textContent = approve ? 'Approving…' : 'Dismissing…';
    const err = $('[data-sg-err]'); if (err) err.textContent = '';
    try {
      await livePost(`api/live/suggestions/${approve ? 'approve' : 'dismiss'}`, { source: s.source, id: s.id });
      doc.suggestions = pending().filter((x) => sgKey(x) !== key);
      renderSugg();
      const row = document.querySelector(`[data-sg-row="${CSS.escape(key)}"]`);
      if (row) { row.remove(); if (!pending().length) closeSheet(); }  // the last one handled: back to the calendar
      if (approve) load(false).catch(() => {});
    } catch (e) {
      for (const b of acts.children) b.disabled = false;
      btn.textContent = approve ? 'Approve' : 'Dismiss';
      if (sheetOpen) say(e.message); else if (err) err.textContent = e.message;
    }
  }

  function showSheet() { const sh = $('[data-sheet]'); sh.hidden = false; sh.setAttribute('role', 'dialog'); sh.setAttribute('aria-modal', 'true'); $('[data-sheet-back]').hidden = false; }
  function hideSheet() { const sh = $('[data-sheet]'); sh.hidden = true; sh.removeAttribute('role'); sh.removeAttribute('aria-modal'); $('[data-sheet-back]').hidden = true; }
  function closeSheet() { sheetOpen = false; hideSheet(); sheetBack?.release(); sheetBack = null; }
  if (!window.WizardApp) {
    document.querySelector('[data-status]').textContent = 'Wizard core is missing. Follow the standalone setup in README.md.';
    return;
  }
  WizardApp.ready({ name: 'Calendar', version: '0.3.0' });

  // Settings: Connected accounts + Agent access (settings.js, Mail's and Messenger's design), then private iCal links
  // and the snapshot (read-only). The private iCal URL is submitted once and never rendered back into the page.
  const SHEET_TOP = '<div class="sh-top"><span class="grab"></span><button class="x" data-close aria-label="Close">✕</button></div>';
  function openCals() {
    const list = (doc?.calendars || []).filter(c => !c.live).map(c => `<button class="cal${c.hidden ? ' off' : ''}" data-vis="${esc(c.id)}" role="switch" aria-checked="${!c.hidden}"><i style="background:${esc(c.color)}"></i><span class="nm">${esc(c.name)}<small>${c.hidden ? 'Hidden' : `${c.count} events`}</small></span><span class="sw"></span></button>`).join('');
    const sources = (doc?.connected || []).map(source => `<div class="source"><span class="nm">${esc(source.name)}<small>${source.error ? esc(source.error) : source.lastSyncedAt ? `Updated ${esc(fmtSynced(source.lastSyncedAt))}` : 'Google iCal'}</small></span><button class="remove" data-remove-source="${esc(source.id)}">Remove</button></div>`).join('');
    const sync = (doc?.connected || []).length ? `<div class="sync"><span>${doc?.syncedAt ? `Updated ${esc(fmtSynced(doc.syncedAt))}` : 'Not updated yet'}</span><button class="btn" data-sync>Sync now</button></div>` : '';
    $('[data-sheet]').innerHTML = `${SHEET_TOP}<h2>Settings</h2><div class="wcs" data-wcs></div>
      <h3 class="wcs-h">Private iCal links</h3><p class="note">Read-only. Anyone with the link can read that calendar, so it stays private on this Wizard.</p>${sync}${sources}
      <label class="field">Calendar name<input type="text" data-source-name maxlength="300" autocomplete="off" placeholder="Personal"></label><label class="field">Google iCal link<input type="text" data-source-url maxlength="4096" inputmode="url" autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="https://calendar.google.com/…/basic.ics"></label><button class="btn" data-add-source>Add link</button>
      ${list ? `<h3 class="wcs-h">Shown calendars</h3>${list}` : ''}
      <h3 class="wcs-h">Snapshot</h3><p class="note">Importing replaces the current snapshot, not your Google calendar. Saved iCal links come back on the next sync.</p><input type="file" data-import accept="application/json,.json" aria-label="Import snapshot JSON"><a class="btn" href="api/export" download="calendar-snapshot.json">Export snapshot</a><div class="msg" data-c-msg role="status"></div>`;
    showSheet();
    if (!sheetOpen) { sheetOpen = true; sheetBack = WizardApp.back.push(() => { closeSheet(); return true; }); }
    if (window.WizardCalendarSettings && window.WizardConnect && window.WizardConnect.client) {
      window.WizardCalendarSettings.render($('[data-wcs]'), {
        say, accounts: () => doc?.accounts || [], connect: (source) => connect(source, true), home: openCals,
        changed: async () => { range = null; await load(false).catch(() => {}); },
        page: (title, nodes) => {
          $('[data-sheet]').innerHTML = `${SHEET_TOP}<h2></h2><div class="wcs" data-wcs-page></div><div class="msg" data-c-msg role="status"></div>`;
          $('[data-sheet] h2').textContent = title;
          $('[data-wcs-page]').append(...nodes);
          $('[data-sheet]').scrollTop = 0;
        },
      });
    }
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
    if (t.dataset.sgApprove) return decide(t, true);
    if (t.dataset.sgDismiss) return decide(t, false);
    if (t.matches('[data-sg-open]')) return openSuggestions();
    if (t.dataset.connect) return connect(t.dataset.connect);
    if (t.dataset.fix) return WizardApp.nav?.openApp ? WizardApp.nav.openApp(`wizard-${t.dataset.fix}`) : connect(t.dataset.fix);
    if (t.matches('[data-new]')) return openForm(null, { day: sel });
    if (t.dataset.rsvp) return rsvp(t);
    if (t.dataset.edit) { const e = evById(t.dataset.edit); return e && openForm(e); }
    if (t.dataset.del) return del(t);
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
      needScroll = true; renderTime(); return ensureRange();
    }
    if (t.matches('[data-prev], [data-next-month]')) {
      const d = new Date(Date.UTC(view[0], view[1] + (t.matches('[data-prev]') ? -1 : 1), 1));
      view = [d.getUTCFullYear(), d.getUTCMonth()];
      sel = keyOf(new Date(Date.UTC(view[0], view[1], 1, 12)));
      if (sel.slice(0, 7) === todayKey().slice(0, 7)) sel = todayKey();
      renderGrid(); renderAgenda(); return ensureRange();
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

  // Tap an empty spot in Day/Week to add an event there (connected calendars only).
  $('[data-tin]').addEventListener('click', (ev) => {
    const col = ev.target.closest('.col');
    if (!col || ev.target.closest('button') || !liveCals().length) return;
    const y = ev.clientY - col.getBoundingClientRect().top;
    openForm(null, { day: col.dataset.col, mins: Math.max(0, Math.min(23 * 60, Math.floor(y / HOUR * 2) * 30)) });
  });

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
      if (sheetOpen) {
        openCals();
        if (result.syncing) say('A calendar sync is already running.');
        else say(result.failed ? `${result.failed} calendar failed to sync.` : 'Calendars updated.', !result.failed);
      }
    } catch (e) { btn.disabled = false; btn.textContent = 'Sync now'; say(e.message); }
  }

  // The live window follows the view: about two weeks before the shown month to two months after.
  function wanted() {
    const k = sel || todayKey(), first = `${k.slice(0, 7)}-01`;
    return [addDays(first, -21), addDays(first, 70)];
  }
  function ensureRange() {
    if (!range || !sel) return;
    const k = mode === 'month' ? `${(view ? `${view[0]}-${pad(view[1] + 1)}` : sel.slice(0, 7))}-15` : sel;
    if (!loading && (addDays(k, -14) < range[0] || addDays(k, 21) > range[1])) { loading = load(false).catch(() => {}).finally(() => { loading = null; }); }
  }
  async function load(refresh) {
    try {
      const [from, to] = wanted();
      // X-Wizard-Request marks the owner's own page: Calendar then reads with its grant and lists the agents' suggestions.
      const r = await fetch(`${API}?from=${from}&to=${to}${refresh ? '&refresh=1' : ''}`, { cache: 'no-store', credentials: 'same-origin', headers: { 'X-Wizard-Request': 'calendar' } });
      if (!r.ok) throw new Error(`Load failed (${r.status})`);
      const d = await r.json();
      if (d.timezone) TZ = d.timezone;
      doc = d; range = d.liveRange || null;
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
