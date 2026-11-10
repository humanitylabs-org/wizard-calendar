/* Calendar Settings, top part: the same design as Wizard Mail's and Messenger's Settings (Miguel). "Connected accounts"
 * as flat brand tiles with a status dot, a + tile that opens the in-app Quick connect sheet (connect.js), and "Agent
 * access": one row with Messenger's picker (No access / Read-only / Suggest only (recommended) / Can edit).
 *
 * The level is kept and enforced by the source apps (wizard-google, wizard-microsoft: agent_access.py), so it holds
 * even when an agent calls their calendar tools directly. This screen reads and writes it through their owner routes on
 * this same origin (`/wizard-google/api/calendar-settings`, `api/agent-access`), which need the owner's Wizard session:
 * no agent or bearer path can change it. Classes are prefixed `wcs-` (host apps' generic classes leak in). */
(() => {
  'use strict';
  const NS = 'http://www.w3.org/2000/svg';
  // Brand marks (official four-colour Google G and Microsoft squares), drawn without a background, like Messenger.
  const MARKS = {
    google: { box: '0 0 48 48', paths: [
      ['rgb(234 67 53)', 'M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z'],
      ['rgb(66 133 244)', 'M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z'],
      ['rgb(251 188 5)', 'M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z'],
      ['rgb(52 168 83)', 'M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z']] },
    microsoft: { box: '0 0 23 23', paths: [
      ['rgb(242 80 34)', 'M1 1h10v10H1z'], ['rgb(127 186 0)', 'M12 1h10v10H12z'],
      ['rgb(0 164 239)', 'M1 12h10v10H1z'], ['rgb(255 185 0)', 'M12 12h10v10H12z']] },
  };
  const NAMES = { google: 'Google', microsoft: 'Microsoft' };
  const VIA = { composio: 'Quick connect', 'own-client': 'Your own Google app', 'own-app': 'Your own Microsoft app' };
  const LEVEL_TEXT = {
    no_access: 'Agents can\u2019t see your calendar.',
    read_only: 'Agents see your events. They can\u2019t change anything.',
    suggest_only: 'Agents suggest changes. Nothing changes until you approve it here.',
    can_edit: 'Agents add, change and delete events and answer invites for you.',
  };
  const RANK = { no_access: 0, read_only: 1, suggest_only: 2, can_edit: 3 };

  function el(tag, text, cls, attrs) {
    const n = document.createElement(tag);
    if (text != null) n.textContent = text;
    if (cls) n.className = cls;
    for (const [k, v] of Object.entries(attrs || {})) if (v != null) n.setAttribute(k, v);
    return n;
  }
  function button(text, fn, cls, attrs) { const b = el('button', text, cls, { type: 'button', ...attrs }); b.onclick = fn; return b; }
  function mark(source) {
    const m = MARKS[source];
    const svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('viewBox', m ? m.box : '0 0 24 24'); svg.setAttribute('aria-hidden', 'true'); svg.setAttribute('class', 'wcs-mark');
    for (const [fill, d] of (m ? m.paths : [])) { const p = document.createElementNS(NS, 'path'); p.setAttribute('fill', fill); p.setAttribute('d', d); svg.append(p); }
    return svg;
  }
  const client = id => window.WizardConnect.client(id);

  let opts = {}, data = null, box = null;

  // ---------- data: each source app's owner view (accounts, how to disconnect, agent levels) ----------
  async function load() {
    const views = await Promise.all(Object.keys(NAMES).map(async id => {
      try {
        const v = await client(id).api('api/calendar-settings');
        return { id, available: true, accounts: v.accounts || [], access: v.agent_access && v.agent_access.calendar ? v.agent_access : null };
      } catch (e) {
        // Not installed, or an older source app: show what Calendar knows; managing and agent access need the newer app.
        const known = (opts.accounts() || []).filter(a => a.source === id);
        return { id, available: known.length > 0, old: known.length > 0, error: e.message,
          accounts: known.map(a => ({ email: a.email, label: a.label, status: a.status, via: a.via, services: [] })), access: null };
      }
    }));
    data = { sources: views };
    return data;
  }

  async function render(target, options) {
    box = target; opts = options || opts;
    box.replaceChildren(el('p', 'Loading\u2026', 'wcs-muted'));
    try { await load(); } catch (e) { box.replaceChildren(el('p', e.message, 'wcs-bad')); return; }
    draw();
  }
  function draw() {
    if (!box || !box.isConnected) return;
    const tiles = el('div', null, 'wcs-tiles', { role: 'list' });
    for (const s of data.sources) for (const a of s.accounts) tiles.append(tile(s, a));
    const plus = button('', () => opts.connect(), 'wcs-tile wcs-plus', { 'aria-label': 'Connect another account', role: 'listitem' });
    plus.append(el('span', null, 'wcs-plus-mark', { 'aria-hidden': 'true' }), el('span', 'Add', 'wcs-name'));
    tiles.append(plus);
    const parts = [el('h3', 'Connected accounts', 'wcs-h'), tiles];
    if (!data.sources.some(s => s.accounts.length)) parts.push(el('p', 'Connect Google or Microsoft to see your calendar here.', 'wcs-muted'));
    parts.push(...agentAccess());
    box.replaceChildren(...parts);
  }
  function tile(s, a) {
    const ok = a.status === 'active';
    const [user, domain] = String(a.email || '').split('@');
    const b = button('', () => manage(s, a), 'wcs-tile' + (ok ? ' wcs-on' : ' wcs-warn'),
      { role: 'listitem', title: a.email, 'aria-label': `${a.email}, ${NAMES[s.id]}${ok ? '' : ', needs a new sign-in'}` });
    const icon = el('span', null, 'wcs-icon');
    icon.append(mark(s.id), el('span', null, 'wcs-dot', { 'aria-hidden': 'true' }));
    b.append(icon, el('span', a.label || user || NAMES[s.id], 'wcs-name'), el('span', domain ? '@' + domain : '', 'wcs-sub'));
    return b;
  }

  // ---------- agent access: one row, Messenger's picker ----------
  function agentAccess() {
    const known = data.sources.filter(s => s.access);
    const old = data.sources.filter(s => s.available && !s.access && s.accounts.length);
    const out = [el('h3', 'Agent access', 'wcs-h')];
    if (!known.length) {
      out.push(el('p', old.length ? `Update the ${old.map(s => NAMES[s.id]).join(' and ')} app to choose what agents may do.`
        : 'Connect an account first.', 'wcs-muted'));
      return out;
    }
    // One level for every source; if they ever differ, show the stricter one (choosing sets both).
    const level = known.map(s => s.access.calendar).sort((x, y) => RANK[x] - RANK[y])[0];
    const levels = known[0].access.calendar_levels;
    const group = el('div', null, 'wcs-group');
    const row = el('div', null, 'wcs-row');
    const choice = el('select', null, 'wcs-level', { 'aria-label': 'What your agents may do with your calendar' });
    for (const l of levels) choice.append(el('option', l.label + (l.recommended ? ' (recommended)' : ''), null, { value: l.id, title: LEVEL_TEXT[l.id] || l.what }));
    choice.value = level;
    const note = el('p', LEVEL_TEXT[level] || '', 'wcs-note');
    choice.onchange = async () => {
      const want = choice.value;
      choice.disabled = true;
      try {
        for (const s of known) s.access = (await client(s.id).api('api/agent-access', { calendar: want })).agent_access;
        note.textContent = LEVEL_TEXT[want] || '';
        opts.say(`Agent access: ${levels.find(l => l.id === want).label}`, true);
        if (opts.levelChanged) opts.levelChanged(want);
      } catch (e) {
        choice.value = level;
        opts.say(e.message);
      } finally { choice.disabled = false; }
    };
    row.append(el('strong', 'Agents', 'wcs-agent'), choice);
    group.append(row);
    out.push(group, note);
    if (known.some(s => s.access.calendar !== level)) out.push(el('p', 'Google and Microsoft were set differently; choosing sets both.', 'wcs-muted'));
    return out;
  }

  // ---------- one account: what it is, and Disconnect (two taps, inside the sheet) ----------
  function manage(s, a) {
    const ok = a.status === 'active';
    const facts = el('div', null, 'wcs-group');
    const fact = (k, v) => { const r = el('div', null, 'wcs-row wcs-fact'); r.append(el('span', k, 'wcs-k'), el('span', v, 'wcs-v')); return r; };
    facts.append(fact('Account', a.email), fact('Connected with', `${NAMES[s.id]} \u00b7 ${VIA[a.via] || a.via || '\u2014'}`),
      fact('Status', ok ? 'Working' : 'Needs a new sign-in'));
    const back = button('\u2039 Settings', () => opts.home(), 'wcs-back');
    const acts = el('div', null, 'wcs-actions');
    if (!ok) acts.append(button('Sign in again', () => opts.connect(s.id), 'btn primary'));
    if (a.disconnect) acts.append(button('Disconnect', () => askDisconnect(s, a), 'btn danger wcs-danger'));
    else acts.append(el('p', `Update the ${NAMES[s.id]} app to disconnect from Calendar, or open the ${NAMES[s.id]} app.`, 'wcs-muted'));
    opts.page(a.label || a.email, [back, facts, acts]);
  }
  function askDisconnect(s, a) {
    const msg = el('p', `Calendar, Mail and your agents stop using ${a.email}. Your events stay with ${NAMES[s.id]}; you can connect it again any time.`, 'wcs-text');
    const err = el('p', '', 'wcs-bad', { role: 'alert' });
    const no = button('Cancel', () => manage(s, a), 'btn');
    const yes = button('Disconnect', async () => {
      yes.disabled = no.disabled = true; err.textContent = '';
      try {
        await client(s.id).api(a.disconnect, {});
        await opts.changed();
        opts.home();  // back to Settings, the tile gone
        opts.say(`Disconnected ${a.email}.`, true);
      } catch (e) { err.textContent = e.message; yes.disabled = no.disabled = false; }
    }, 'btn danger wcs-danger');
    const acts = el('div', null, 'wcs-actions'); acts.append(no, yes);
    opts.page(`Disconnect ${a.email}?`, [msg, err, acts]);
  }

  window.WizardCalendarSettings = { render, LEVEL_TEXT };
})();
