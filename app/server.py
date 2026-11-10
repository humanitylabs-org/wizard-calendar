#!/usr/bin/env python3
"""Read-only Calendar: validated local snapshots, private Google iCal subscriptions and grant-scoped Connected accounts sync."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import mimetypes
import os
import re
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import ical_feed

VERSION = '0.3.0'
ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get('DATA_DIR', './data')).resolve()
PORT = int(os.environ.get('PORT', '8799'))
BIND = os.environ.get('BIND', '127.0.0.1')
TZ = os.environ.get('CALENDAR_TIMEZONE') or 'UTC'
DISPLAY_TZ = os.environ.get('CALENDAR_TIMEZONE') or None
SYNC_MINUTES = max(0.01, float(os.environ.get('CALENDAR_SYNC_MINUTES', '10')))
SYNC_LOCK = threading.Lock()
SYNC_WAKE = threading.Event()
STATE = {'state': 'not_linked', 'last_success': None, 'last_error': None, 'accounts': [],
         'calendar_errors': {}, 'setup_url': '/connected-accounts/', 'syncing': False}
ZoneInfo(TZ)  # fail explicitly on an invalid deployment timezone
CORE = Path(os.environ['WIZARD_CORE_DIR']).resolve() if os.environ.get('WIZARD_CORE_DIR') else None
LOCAL_HOSTS = {f'127.0.0.1:{PORT}', f'localhost:{PORT}'} | set(filter(None, os.environ.get('WIZARD_LOCAL_HOSTS', '').split(',')))
# Owner-facing hosts are added to, never replace, the local agent route (MCP over loopback / the app network).
HOSTS = set(filter(None, os.environ.get('WIZARD_TRUSTED_HOSTS', '').split(','))) | LOCAL_HOSTS
# Without an explicit override, browser Origins must match the validated Host.
# Both HTTP loopback and HTTPS gateway origins work without an owner-specific URL.
ORIGINS = set(filter(None, os.environ.get('WIZARD_TRUSTED_ORIGINS', '').split(',')))
LOCK = threading.RLock()
# Private Google iCal subscriptions refresh independently of the Connected accounts sync above.
ICAL_SYNC_LOCK = threading.Lock()
ICAL_SYNC_STATE = {'syncing': False, 'lastError': ''}
ICAL_SYNC_INTERVAL = max(0, int(os.environ.get('ICAL_SYNC_INTERVAL', '900')))
MAX_BYTES = 4 * 1024 * 1024
MAX_SOURCES = 20
WEB = {'index.html', 'app.js', 'app.css', 'icon.svg', 'wizard-appearance.js'}
# Owner feature switches (wizard.app-switches/1, wizardos-tracker docs/app-switches.md). Off by default;
# the state lives on the box in DATA/switches.json so the app, the Tracker card and the agent see one state.
SWITCHES = [
    {'id': 'compact-header', 'name': 'Compact top bar',
     'description': 'Slimmer header: date, navigation, view switcher and buttons share one row, so the time grid shows more hours.',
     'default': False, 'issues': ['humanitylabs-org/wizard-calendar#20']},
    {'id': 'trackpad-swipe', 'name': 'Trackpad day swipe',
     'description': 'In Day and Week, a two-finger sideways swipe (or Shift + mouse wheel) glides the calendar and settles one day at a time, like Mac Calendar.',
     'default': False, 'issues': ['humanitylabs-org/wizard-calendar#21']},
]


def _saved_switches():
    try: saved = _read_json(DATA / 'switches.json', {})
    except (OSError, ValueError): saved = {}  # unreadable state falls back to the defaults (off)
    return saved if isinstance(saved, dict) else {}


def switches_doc():
    saved = _saved_switches()
    return {'contract': 'wizard.app-switches/1', 'switches': [
        dict(s, on=saved[s['id']] if isinstance(saved.get(s['id']), bool) else s['default']) for s in SWITCHES]}


def set_switch(switch_id, on):
    with LOCK:
        saved = {k: v for k, v in _saved_switches().items() if k in {s['id'] for s in SWITCHES} and isinstance(v, bool)}
        saved[switch_id] = on
        _save_path(DATA / 'switches.json', saved)
    return switches_doc()


def empty():
    return {'schemaVersion': 1, 'timezone': TZ, 'calendars': [], 'events': [], 'syncedAt': None}


def _read_json(path: Path, fallback):
    return json.loads(path.read_text()) if path.exists() else fallback


def _save_path(path: Path, doc):
    DATA.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(DATA, 0o700)
    fd, tmp_name = tempfile.mkstemp(prefix=f'.{path.name}.', dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, 'w') as handle:
            json.dump(doc, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        directory_flag = getattr(os, 'O_DIRECTORY', 0)
        directory_fd = os.open(path.parent, os.O_RDONLY | directory_flag)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _validate_sources(sources):
    if not isinstance(sources, list) or len(sources) > MAX_SOURCES:
        raise ValueError('Calendar source configuration is invalid')
    ids = set()
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError('Calendar source configuration is invalid')
        required = {'id', 'name', 'url'}
        if not required.issubset(source) or not all(isinstance(source[key], str) for key in required):
            raise ValueError('Calendar source configuration is invalid')
        if source['id'] in ids or source['id'] != ical_feed.source_id(source['url']):
            raise ValueError('Calendar source configuration is invalid')
        ids.add(source['id'])
    return sources


def _load_state():
    state_path = DATA / 'state.json'
    if state_path.exists():
        state = _read_json(state_path, None)
    else:
        state = {
            'schemaVersion': 1,
            'snapshot': _read_json(DATA / 'snapshot.json', empty()),
            'sources': [],
        }
    if (
        not isinstance(state, dict)
        or state.get('schemaVersion') != 1
        or not isinstance(state.get('snapshot'), dict)
    ):
        raise ValueError('Calendar state is invalid')
    _validate_sources(state.get('sources'))
    return state


def read():
    with LOCK:
        return _load_state()['snapshot']


def _source_doc():
    with LOCK:
        return {'schemaVersion': 1, 'sources': _load_state()['sources']}


def _commit_snapshot_and_sources(snapshot, sources):
    """Commit source authority and its derived snapshot with one atomic replacement."""
    source_rows = sources['sources'] if isinstance(sources, dict) else sources
    _validate_sources(source_rows)
    _save_path(DATA / 'state.json', {
        'schemaVersion': 1,
        'snapshot': snapshot,
        'sources': source_rows,
    })


def save(doc):
    """Persist the snapshot with the saved iCal subscriptions in one atomic generation."""
    with LOCK:
        _commit_snapshot_and_sources(doc, _load_state()['sources'])


def text(value, name, limit=300, required=False):
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise ValueError(f'{name}: expected {"nonempty " if required else ""}string up to {limit} characters')
    return value


def validate(doc):
    if not isinstance(doc, dict) or type(doc.get('schemaVersion')) is not int or doc.get('schemaVersion') != 1:
        raise ValueError('schemaVersion must be 1')
    timezone = text(doc.get('timezone', TZ), 'timezone', 100, True)
    try:
        ZoneInfo(timezone)
    except (ValueError, KeyError):
        raise ValueError('timezone must be an IANA timezone')
    cals, events = doc.get('calendars'), doc.get('events')
    if not isinstance(cals, list) or len(cals) > 100 or not isinstance(events, list) or len(events) > 10000:
        raise ValueError('calendars (max 100) and events (max 10000) must be arrays')
    ids, normalized_cals = set(), []
    for cal in cals:
        if not isinstance(cal, dict):
            raise ValueError('calendar must be an object')
        cid = text(cal.get('id'), 'calendar.id', 300, True)
        if cid in ids:
            raise ValueError('duplicate calendar id')
        ids.add(cid)
        row = {'id': cid, 'name': text(cal.get('name'), 'calendar.name', 300, True)}
        for key in ('account', 'email', 'provider_id'):
            if key in cal: row[key] = text(cal[key], 'calendar.' + key, 300, True)
        if cal.get('color'):
            if not isinstance(cal['color'], str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', cal['color']): raise ValueError('calendar.color must be #RRGGBB')
            row['color'] = cal['color']
        normalized_cals.append(row)
    ev_ids, normalized = set(), []
    for ev in events:
        if not isinstance(ev, dict):
            raise ValueError('event must be an object')
        eid = text(ev.get('id'), 'event.id', 650, True)
        if eid in ev_ids:
            raise ValueError('duplicate event id')
        ev_ids.add(eid)
        cid = text(ev.get('cal'), 'event.cal', 300, True)
        if cid not in ids:
            raise ValueError('event references unknown calendar')
        allday = ev.get('allDay')
        if not isinstance(allday, bool):
            raise ValueError('allDay must be boolean')
        start, end = text(ev.get('start'), 'start', 50, True), text(ev.get('end'), 'end', 50, True)
        try:
            if allday:
                if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', start) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', end):
                    raise ValueError()
                first, last = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
            else:
                first = dt.datetime.fromisoformat(start.replace('Z', '+00:00'))
                last = dt.datetime.fromisoformat(end.replace('Z', '+00:00'))
                if first.tzinfo is None or last.tzinfo is None:
                    raise ValueError()
            if last <= first:
                raise ValueError()
        except (ValueError, TypeError):
            raise ValueError('start/end must be valid dates or offset timestamps; end must follow start')
        row = {'id': eid, 'cal': cid, 'title': text(ev.get('title'), 'title', 300, True), 'start': start, 'end': end, 'allDay': allday}
        if 'uid' in ev: row['uid'] = text(ev['uid'], 'event.uid', 1024, True)
        if 'attendees' in ev:
            if type(ev['attendees']) is not int or not 0 <= ev['attendees'] <= 10000: raise ValueError('attendees must be a bounded nonnegative count')
            row['attendees'] = ev['attendees']
        for key, limit in [('location', 500), ('description', 4000), ('link', 2000), ('meet', 2000)]:
            value = text(ev.get(key, ''), key, limit)
            if key in ('link', 'meet') and value:
                url = urlsplit(value)
                if url.scheme != 'https' or not url.hostname or url.username or url.password:
                    raise ValueError(f'{key} must be an https URL without credentials')
            row[key] = value
        normalized.append(row)
    normalized.sort(key=lambda event: (event['start'], event['id']))
    return {'schemaVersion': 1, 'timezone': timezone, 'calendars': normalized_cals, 'events': normalized}


def import_snapshot(body, source='manual_import', metadata=None):
    """The single validated, atomic write path. Caller holds LOCK."""
    normalized = validate(body)
    previous = read()
    old = {c['id']: c for c in previous['calendars']}
    for c in normalized['calendars']:
        if old.get(c['id'], {}).get('color'): c['color'] = old[c['id']]['color']
    digest = hashlib.sha256(json.dumps(normalized, sort_keys=True).encode()).hexdigest()
    changed = digest != previous.get('contentSha256')
    normalized.update(contentSha256=digest,
                      syncedAt=dt.datetime.now(dt.timezone.utc).isoformat() if changed else previous.get('syncedAt'),
                      hidden=sorted(c for c in previous.get('hidden', []) if c in {x['id'] for x in normalized['calendars']}),
                      source=source)
    if metadata: normalized.update(metadata)
    if changed or normalized != previous: save(normalized)
    return {'ok': True, 'changed': changed, 'events': len(normalized['events']), 'contentSha256': digest}


def import_preferences(body):
    """Optional owner-run legacy config import. Caller holds LOCK; never reads legacy files.

    Only calendar ids/colors and hidden are consumed. Match exact local ids or Google
    provider_id (possibly present through multiple accounts), never display names.
    """
    rows, hidden = body.get('calendars'), body.get('hidden')
    if not isinstance(rows, list) or len(rows) > 100 or not isinstance(hidden, list) or len(hidden) > 100:
        raise ValueError('calendars and hidden must be arrays (max 100 each)')
    prefs = {}
    for row in rows:
        if not isinstance(row, dict): raise ValueError('calendar preference must be an object')
        cid = text(row.get('id'), 'calendar.id', 300, True)
        if cid in prefs: raise ValueError('duplicate calendar preference id')
        color = row.get('color')
        if color is not None and (not isinstance(color, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', color)):
            raise ValueError('calendar.color must be #RRGGBB')
        prefs[cid] = color
    hidden = {text(cid, 'hidden id', 300, True) for cid in hidden}
    if hidden - prefs.keys(): raise ValueError('hidden ids must appear in calendars')
    doc = read()
    matches, matched = {}, set()
    for cal in doc['calendars']:
        # An exact local id is more specific than a provider id.
        source = cal['id'] if cal['id'] in prefs else cal.get('provider_id')
        if source in prefs:
            matches[cal['id']] = source; matched.add(source)
            if prefs[source] is not None: cal['color'] = prefs[source]
    current_hidden = set(doc.get('hidden', []))
    for cid, source in matches.items():
        if source in hidden: current_hidden.add(cid)
        else: current_hidden.discard(cid)
    doc['hidden'] = sorted(current_hidden)
    if matches:
        doc['contentSha256'] = hashlib.sha256(json.dumps(validate(doc), sort_keys=True).encode()).hexdigest()
        save(doc)
    return {'ok': True, 'matched': len(matches), 'unmatched': sorted(prefs.keys() - matched),
            'hidden': doc['hidden']}


class ProviderError(Exception):
    def __init__(self, code, status=0): self.code, self.status = code, status


class NoRedirect(urllib.request.HTTPRedirectHandler):
    # Never forward a grant to a redirected host.
    def redirect_request(self, req, fp, code, msg, headers, newurl): return None


def provider_link():
    """Re-read rotating grants/endpoints on each sync. Never log their contents."""
    try:
        raw = Path(os.environ.get('WIZARD_GRANTS_FILE') or '/wizard/grants.json').read_bytes()
        if len(raw) > 262144: return None
        grants = json.loads(raw)
        if not isinstance(grants, dict): return None
        outgoing, endpoints = grants.get('outgoing', {}), grants.get('provider_endpoints', {})
        if not isinstance(outgoing, dict) or not isinstance(endpoints, dict): return None
        # The provider app is installed as 'connected-accounts' (formerly 'wizard-connectors').
        key = outgoing.get('connected-accounts') or outgoing.get('wizard-connectors') or outgoing.get('slot:calendar-source')
        # Permission broker endpoint takes precedence over an optional operator override.
        base = (endpoints.get('connected-accounts') or endpoints.get('wizard-connectors') or endpoints.get('slot:calendar-source')
                or os.environ.get('CONNECTORS_URL'))
        if not isinstance(key, str) or not key: return None
        if not isinstance(base, str): return None
        url = urlsplit(base)
        if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or url.query or url.fragment: return None
        return base.rstrip('/'), key
    except (OSError, ValueError, KeyError, TypeError, AttributeError): return None


def provider_call(link, path, body=None):
    base, key = link
    req = urllib.request.Request(base + '/service/calendar/' + path,
        data=None if body is None else json.dumps(body).encode(),
        headers={'X-Wizard-Grant': key, 'Content-Type': 'application/json'})
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=15) as response:
            raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES: raise ValueError('provider response too large')
            result = json.loads(raw)
            if not isinstance(result, dict): raise ValueError('provider response must be an object')
            return result
    except urllib.error.HTTPError as exc:
        # Only expose stable codes, never a provider body (which could contain secrets).
        try: code = json.loads(exc.read(4096)).get('error')
        except (ValueError, AttributeError): code = None
        finally: exc.close()
        allowed = {'reauth_required', 'not_bound', 'google_configuration_required', 'grant_required', 'grant_denied', 'permission_denied'}
        raise ProviderError(code if code in allowed else 'provider_http_' + str(exc.code), exc.code) from None
    except (urllib.error.URLError, TimeoutError, ConnectionError): raise ProviderError('provider_unreachable') from None


def sync_status():
    with LOCK:
        result = json.loads(json.dumps(STATE))
        result['interval_minutes'] = SYNC_MINUTES
        result['last_success'] = result['last_success'] or read().get('syncLastSuccess')
        return result


def set_state(**values):
    with LOCK: STATE.update(values)


def dedupe(events):
    # Match across accounts/calendars; normalize case/whitespace and offset instants.
    seen, result = set(), []
    for e in sorted(events, key=lambda e: (e['cal'], e['id'])):
        stamp = lambda v: v if e['allDay'] else dt.datetime.fromisoformat(v.replace('Z', '+00:00')).astimezone(dt.timezone.utc).isoformat()
        keys = {('title', e['title'].strip().lower(), stamp(e['start']))}
        if e.get('uid'): keys.add(('uid', e['uid'], stamp(e['start'])))
        if not (keys & seen): seen.update(keys); result.append(e)
    return result


def sync_once():
    if not SYNC_LOCK.acquire(blocking=False): return sync_status()
    set_state(syncing=True)
    try:
        link = provider_link()
        if not link:
            set_state(state='not_linked', accounts=[], last_error=None, calendar_errors={}, syncing=False)
            return sync_status()
        status = provider_call(link, 'status')
        if type(status.get('client_configured')) is not bool or not isinstance(status.get('accounts'), list): raise ValueError('invalid provider status')
        accounts = []
        for a in status['accounts']:
            if not isinstance(a, dict) or type(a.get('calendar_allowed')) is not bool: raise ValueError('invalid provider account')
            accounts.append({k: text(a.get(k), 'account.' + k, 300, True) for k in ('account', 'email', 'status')} | {'calendar_allowed': a['calendar_allowed']})
        setup = status.get('setup_url', '/connected-accounts/')
        # Only an app path or a credential-free http(s) destination can reach the UI.
        if not isinstance(setup, str) or not (setup.startswith('/') and not setup.startswith('//') or urlsplit(setup).scheme in ('http', 'https') and urlsplit(setup).hostname and not urlsplit(setup).username and not urlsplit(setup).password): raise ValueError('invalid setup_url')
        set_state(accounts=accounts, setup_url=setup, last_error=None, calendar_errors={})
        if not status['client_configured']:
            set_state(state='needs_google_app', syncing=False); return sync_status()
        if not accounts:
            set_state(state='needs_account', syncing=False); return sync_status()
        allowed = {a['account'] for a in accounts if a['calendar_allowed'] and a['status'] not in ('reauth_required', 'not_bound')}
        if not allowed:
            set_state(state='needs_permission', syncing=False); return sync_status()
        listing = provider_call(link, 'calendars', {})
        if not isinstance(listing.get('calendars'), list) or len(listing['calendars']) > 100: raise ValueError('invalid provider calendars')
        previous = read()
        raw_cache = previous.get('calendarEvents', {})
        cals, cache, errors = [], {}, {}
        today = dt.datetime.now(ZoneInfo(TZ)).date()
        boundary = lambda days: dt.datetime.combine(today + dt.timedelta(days=days), dt.time(), ZoneInfo(TZ)).isoformat()
        for item in listing['calendars']:
            if not isinstance(item, dict): raise ValueError('invalid provider calendar')
            account = text(item.get('account'), 'account', 300, True)
            if account not in allowed: raise ValueError('calendar account not authorized')
            provider_id = text(item.get('id'), 'calendar_id', 300, True)
            cid = 'google:' + hashlib.sha256(json.dumps([account, provider_id]).encode()).hexdigest()
            if cid in cache: raise ValueError('duplicate provider calendar')
            cal = {'id': cid, 'name': item.get('name'), 'account': account, 'email': item.get('email'), 'provider_id': provider_id}
            if item.get('color'): cal['color'] = item['color']
            # Validate metadata even when this calendar's network request fails.
            cal = validate({'schemaVersion': 1, 'calendars': [cal], 'events': []})['calendars'][0]
            cals.append(cal)
            try:
                # Live range is -60/+400 days; the provider caps a request at 400.
                # Overlapping multi-day events can occur in both half-open windows.
                rows = {}
                for first, last in ((-60, 180), (180, 400)):
                    response = provider_call(link, 'events', {'account': account, 'calendar_id': provider_id, 'time_min': boundary(first), 'time_max': boundary(last)})
                    if not isinstance(response.get('events'), list) or type(response.get('truncated')) is not bool: raise ValueError('invalid provider events')
                    if response['truncated']: raise ProviderError('events_truncated')
                    for row in response['events']:
                        if not isinstance(row, dict): raise ValueError('invalid provider event')
                        key = text(row.get('id'), 'provider event id', 650, True)
                        if key in rows and rows[key] != row: raise ValueError('inconsistent event across windows')
                        rows[key] = row
                events = []
                for e in rows.values():
                    if not isinstance(e, dict) or e.get('account') != account or e.get('calendar_id') != provider_id: raise ValueError('event calendar mismatch')
                    if e.get('status') == 'cancelled' or e.get('self_response') == 'declined': continue
                    eid = text(e.get('id'), 'provider event id', 650, True)
                    events.append({'id': cid + ':' + hashlib.sha256(eid.encode()).hexdigest(), 'cal': cid,
                        'title': e.get('title'), 'start': e.get('start'), 'end': e.get('end'), 'allDay': e.get('all_day'),
                        'location': e.get('location', ''), 'link': e.get('html_link', ''),
                        'description': e.get('description', ''), 'meet': e.get('meet', ''),
                        **({'attendees': e['attendee_count']} if 'attendee_count' in e else {}),
                        **({'uid': e['ical_uid']} if e.get('ical_uid') else {})})
                cache[cid] = validate({'schemaVersion': 1, 'calendars': [cal], 'events': events})['events']
            except ProviderError as exc:
                if exc.status == 403: raise
                errors[cid] = exc.code
                cache[cid] = raw_cache.get(cid, [e for e in previous['events'] if e['cal'] == cid])
        # An account needing reauthorization may disappear from the provider listing.
        # Keep its last good calendars rather than treating permission failure as deletion.
        listed = {c['id'] for c in cals}
        for cal in previous['calendars']:
            if cal.get('account') and cal['account'] not in allowed and cal['id'] not in listed:
                cals.append(cal)
                errors[cal['id']] = 'reauth_required'
                cache[cal['id']] = raw_cache.get(cal['id'], [e for e in previous['events'] if e['cal'] == cal['id']])
        # All provider payloads must validate before any write. Retain raw per-calendar
        # rows so a cross-calendar duplicate remains available if its other copy vanishes.
        all_events = [e for rows in cache.values() for e in rows]
        if len(all_events) > 10000: raise ValueError('provider event limit exceeded')
        doc = validate({'schemaVersion': 1, 'timezone': TZ, 'calendars': sorted(cals, key=lambda c: c['id']), 'events': all_events})
        connected_events = dedupe(doc['events'])
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        denied = any(a['account'] not in allowed for a in accounts)
        with LOCK:
            # Private iCal subscriptions are not Connected accounts data: keep their calendars and
            # events exactly as stored (read under the lock, so a concurrent iCal refresh is not lost).
            state = _load_state()
            ical_ids = {source['id'] for source in state['sources']}
            kept_calendars = [c for c in state['snapshot']['calendars'] if c['id'] in ical_ids]
            kept_events = [e for e in state['snapshot']['events'] if e['cal'] in ical_ids]
            if len(connected_events) + len(kept_events) > 10000: raise ValueError('event limit exceeded')
            doc = validate({'schemaVersion': 1, 'timezone': TZ, 'calendars': sorted(doc['calendars'] + kept_calendars, key=lambda c: c['id']),
                            'events': connected_events + kept_events})
            import_snapshot(doc, 'connected_accounts', {'calendarEvents': cache, 'calendarErrors': errors,
                'syncLastSuccess': previous.get('syncLastSuccess') if errors or denied else now})
        set_state(state='error' if errors else 'needs_permission' if denied else 'ok',
                  last_success=previous.get('syncLastSuccess') if errors or denied else now,
                  last_error='Some calendars could not sync; last good events retained.' if errors else 'Some accounts need calendar permission.' if denied else None,
                  calendar_errors=errors)
    except ProviderError as exc:
        state = 'needs_permission' if exc.status in (403, 409) else 'needs_google_app' if exc.code == 'google_configuration_required' else 'error'
        set_state(state=state, last_error=exc.code)
    except (ValueError, TypeError, KeyError, AttributeError, OSError):
        set_state(state='error', last_error='Invalid provider response or storage failure; previous snapshot retained.')
    finally:
        set_state(syncing=False)
        SYNC_LOCK.release()
    return sync_status()


def request_sync():
    set_state(syncing=True)
    SYNC_WAKE.set()
    return sync_status()


def sync_worker():
    while True:
        SYNC_WAKE.wait(SYNC_MINUTES * 60)
        SYNC_WAKE.clear()
        sync_once()


def start_sync_worker():
    request_sync()
    threading.Thread(target=sync_worker, name='calendar-sync', daemon=True).start()


def _stamp_snapshot(candidate, previous, now=None):
    normalized = validate(candidate)
    digest = hashlib.sha256(json.dumps(normalized, sort_keys=True).encode()).hexdigest()
    hidden_ids = {cal['id'] for cal in normalized['calendars']}
    normalized.update(
        contentSha256=digest,
        syncedAt=now or dt.datetime.now(dt.timezone.utc).isoformat(),
        hidden=[item for item in previous.get('hidden', []) if item in hidden_ids],
    )
    # An iCal change must not erase what Connected accounts or a manual import recorded.
    for key in ('source', 'calendarEvents', 'calendarErrors', 'syncLastSuccess'):
        if key in previous:
            normalized[key] = previous[key]
    return normalized


def _public_source(source):
    return {
        'id': source['id'],
        'name': source['name'],
        'provider': 'Google iCal',
        'lastSyncedAt': source.get('lastSyncedAt'),
        'error': source.get('error', ''),
    }


def ical_sources_public():
    with LOCK:
        return [_public_source(source) for source in _source_doc()['sources']]


def _replace_source_snapshot(previous, source, parsed, now=None):
    source_id = source['id']
    candidate = {
        'schemaVersion': 1,
        'timezone': previous.get('timezone', TZ),
        'calendars': [cal for cal in previous.get('calendars', []) if cal.get('id') != source_id] + parsed['calendars'],
        'events': [event for event in previous.get('events', []) if event.get('cal') != source_id] + parsed['events'],
    }
    return _stamp_snapshot(candidate, previous, now)


def add_ical_source(name, url, *, fetcher=None, now=None):
    if fetcher is None:
        fetcher = ical_feed.fetch_google_ical
    name = text(name, 'name', 300, True).strip()
    safe_url = ical_feed.normalize_google_ical_url(url)
    source_id = ical_feed.source_id(safe_url)
    with LOCK:
        sources = _source_doc()
        if any(source['id'] == source_id for source in sources['sources']):
            raise ValueError('That Google iCal link is already added')
        if len(sources['sources']) >= MAX_SOURCES:
            raise ValueError('Calendar supports up to 20 iCal links')
    try:
        payload = fetcher(safe_url)
    except OSError as exc:
        raise ValueError(str(exc)[:300] or 'Could not fetch the Google iCal feed') from None
    parsed = ical_feed.parse_ical(payload, calendar_id=source_id, calendar_name=name, timezone=TZ, now=now)
    timestamp = now or dt.datetime.now(dt.timezone.utc).isoformat()
    source = {'id': source_id, 'name': name, 'url': safe_url, 'createdAt': timestamp, 'lastSyncedAt': timestamp, 'error': ''}
    with LOCK:
        sources = _source_doc()
        if any(item['id'] == source_id for item in sources['sources']):
            raise ValueError('That Google iCal link is already added')
        if len(sources['sources']) >= MAX_SOURCES:
            raise ValueError('Calendar supports up to 20 iCal links')
        previous = read()
        updated = _replace_source_snapshot(previous, source, parsed, timestamp)
        sources['sources'].append(source)
        _commit_snapshot_and_sources(updated, sources)
    return _public_source(source)


def remove_ical_source(source_id):
    source_id = text(source_id, 'id', 300, True)
    with LOCK:
        sources = _source_doc()
        if not any(source['id'] == source_id for source in sources['sources']):
            raise ValueError('Calendar source was not found')
        sources['sources'] = [source for source in sources['sources'] if source['id'] != source_id]
        previous = read()
        candidate = {
            'schemaVersion': 1,
            'timezone': previous.get('timezone', TZ),
            'calendars': [cal for cal in previous.get('calendars', []) if cal.get('id') != source_id],
            'events': [event for event in previous.get('events', []) if event.get('cal') != source_id],
        }
        _commit_snapshot_and_sources(_stamp_snapshot(candidate, previous), sources)
    return {'ok': True, 'id': source_id}


def sync_ical_sources(*, fetcher=None, now=None):
    if fetcher is None:
        fetcher = ical_feed.fetch_google_ical
    if not ICAL_SYNC_LOCK.acquire(blocking=False):
        return {'ok': True, 'syncing': True, 'synced': 0, 'failed': 0}
    ICAL_SYNC_STATE.update(syncing=True, lastError='')
    synced = failed = 0
    try:
        with LOCK:
            source_ids = [source['id'] for source in _source_doc()['sources']]
        for source_id in source_ids:
            with LOCK:
                sources = _source_doc()
                source = next((item.copy() for item in sources['sources'] if item['id'] == source_id), None)
            if source is None:
                continue
            try:
                payload = fetcher(source['url'])
                parsed = ical_feed.parse_ical(payload, calendar_id=source_id, calendar_name=source['name'], timezone=TZ, now=now)
                timestamp = now or dt.datetime.now(dt.timezone.utc).isoformat()
                with LOCK:
                    sources = _source_doc()
                    current = next((item for item in sources['sources'] if item['id'] == source_id), None)
                    if current is None:
                        continue
                    previous = read()
                    current.update(lastSyncedAt=timestamp, error='')
                    _commit_snapshot_and_sources(_replace_source_snapshot(previous, current, parsed, timestamp), sources)
                synced += 1
            except (ValueError, OSError) as exc:
                message = str(exc)[:300] or 'Google iCal sync failed'
                with LOCK:
                    sources = _source_doc()
                    current = next((item for item in sources['sources'] if item['id'] == source_id), None)
                    if current is not None:
                        current['error'] = message
                        _commit_snapshot_and_sources(read(), sources)
                ICAL_SYNC_STATE['lastError'] = message
                failed += 1
        return {'ok': failed == 0, 'syncing': False, 'synced': synced, 'failed': failed}
    finally:
        ICAL_SYNC_STATE['syncing'] = False
        ICAL_SYNC_LOCK.release()


def view_mode(doc, source_count):
    source = doc.get('source')
    return 'connected_accounts' if source == 'connected_accounts' else 'ical' if source_count else source or 'empty'


def view():
    doc = read()
    hidden = set(doc.get('hidden', []))
    errors = doc.get('calendarErrors', {})
    # Connected accounts keep raw per-calendar rows so a cross-calendar duplicate survives its twin vanishing.
    cache = doc.get('calendarEvents', {}) if doc.get('source') == 'connected_accounts' else {}
    try:
        sources = ical_sources_public()
        source_errors = [source['error'] for source in sources if source['error']]
    except ValueError as exc:
        sources, source_errors = [], [str(exc)]
    for c in doc['calendars']:
        c.update(hidden=c['id'] in hidden, ok=c['id'] not in errors,
                 error=errors.get(c['id']), count=sum(e['cal'] == c['id'] for e in doc['events']))
    if cache:
        rows = [e for cached in cache.values() for e in cached] + [e for e in doc['events'] if e['cal'] not in cache]
        doc['events'] = dedupe([e for e in rows if e['cal'] not in hidden])
    else:
        doc['events'] = [e for e in doc['events'] if e['cal'] not in hidden]
    doc.pop('calendarEvents', None)
    status = sync_status()
    return dict(doc, display_timezone=DISPLAY_TZ, sync=status,
                connected=sources,
                connected_accounts=[a['email'] for a in status['accounts'] if a['calendar_allowed']],
                errors=list(errors.values()) + source_errors,
                syncing=status['syncing'] or ICAL_SYNC_STATE['syncing'],
                syncError=status['last_error'] or ICAL_SYNC_STATE['lastError'],
                mode=view_mode(doc, len(sources)))


def _ical_loop():
    if ICAL_SYNC_INTERVAL <= 0:
        return
    while True:
        threading.Event().wait(ICAL_SYNC_INTERVAL)
        try:
            if ical_sources_public():
                sync_ical_sources()
        except (ValueError, OSError):
            pass


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def respond(self, value, status=200, mime='application/json'):
        body = json.dumps(value).encode() if mime == 'application/json' else value
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def trusted(self):
        if self.headers.get('Host') not in HOSTS or self.headers.get('Sec-Fetch-Site') == 'cross-site':
            self.respond({'error': 'untrusted_host_or_site'}, 403); return False
        origins = ORIGINS or {f'{scheme}://{self.headers.get("Host")}' for scheme in ('http', 'https')}
        if self.headers.get('Origin') and self.headers['Origin'] not in origins:
            self.respond({'error': 'untrusted_origin'}, 403); return False
        return True

    def route(self):
        path = urlsplit(self.path).path
        if path == '/wizard-calendar':
            return '/'
        return path[len('/wizard-calendar'):] if path.startswith('/wizard-calendar/') else path

    def do_HEAD(self):
        self.do_GET()

    def superseded_connect(self):
        return self.respond({'error': 'manual_google_linking_superseded',
            'message': 'Manual Google linking moved to Connected accounts. Open setup there; Calendar never accepts OAuth credentials.',
            'setup_url': '/connected-accounts/', 'superseded_by': 'Connected accounts'}, 410)

    def sync_now(self):
        """Refresh everything Calendar reads: iCal subscriptions now, Connected accounts in the background."""
        try: has_ical = bool(ical_sources_public())
        except ValueError: has_ical = False
        # With nothing but iCal links the refresh is complete when this returns (200); otherwise a
        # Connected accounts refresh is queued and the caller polls GET /api/sync (202).
        queued = provider_link() is not None or not has_ical
        result = request_sync() if queued else {}
        if has_ical:
            result = dict(result, **sync_ical_sources())
            result['syncing'] = bool(result['syncing'] or (queued and sync_status()['syncing']))
        return self.respond(result, 202 if queued else 200)

    def do_GET(self):
        if not self.trusted(): return
        path = self.route()
        if path in ('/api/connect/start', '/api/connect/finish'): return self.superseded_connect()
        if path.rstrip('/') == '/api':
            return self.respond({'app': 'wizard-calendar', 'openapi_url': '/wizard-calendar/openapi.json',
                'routes': ['/api/events', '/api/health', '/api/sync', '/api/import', '/api/export', '/api/preferences/import', '/api/calendars/visibility', '/api/sources', '/api/sources/remove', '/api/switches'],
                'superseded': {'/api/connect/start': '/connected-accounts/', '/api/connect/finish': '/connected-accounts/'}})
        if path in ('/healthz', '/api/health'):
            try: source_count = len(ical_sources_public())
            except ValueError: source_count = 0
            doc = read()
            return self.respond({'ok': True, 'app': 'wizard-calendar', 'version': VERSION, 'mode': view_mode(doc, source_count),
                'configured': bool(source_count or doc['calendars']), 'sources': source_count, 'sync': sync_status()})
        if path == '/api/sync': return self.respond(sync_status())
        if path == '/api/switches': return self.respond(switches_doc())
        if path == '/api/events': return self.respond(view())
        if path == '/api/export': return self.respond(read())
        if path == '/api/sources': return self.respond({'sources': ical_sources_public()})
        if path == '/openapi.json': return self.respond((ROOT / 'openapi.json').read_bytes(), mime='application/octet-stream')
        if path == '/wizard-os-home/core/app-client.js':
            if not CORE or not (CORE / 'app-client.js').is_file(): return self.respond({'error': 'shared_core_required', 'instructions': 'See README.md standalone setup'}, 503)
            return self.respond((CORE / 'app-client.js').read_bytes(), mime='text/javascript')
        name = 'index.html' if path == '/' else path[1:]
        if name not in WEB:
            return self.respond({'error': 'not_found'}, 404)
        return self.respond((ROOT / 'web' / name).read_bytes(), mime=mimetypes.guess_type(name)[0] or 'application/octet-stream')

    def do_POST(self):
        if not self.trusted(): return
        path = self.route()
        if path in ('/api/connect/start', '/api/connect/finish'): return self.superseded_connect()
        if path == '/api/switches': return self.post_switch()
        if path not in ('/api/import', '/api/preferences/import', '/api/calendars/visibility', '/api/sources', '/api/sources/remove', '/api/sync', '/mcp'):
            return self.respond({'error': 'not_found'}, 404)
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if size <= 0 or size > MAX_BYTES: return self.respond({'error': 'body_size_limit'}, 413)
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict): raise ValueError('body must be an object')
            if path == '/mcp': return self.mcp(body)
            if path == '/api/sources': return self.respond({'ok': True, 'source': add_ical_source(body.get('name'), body.get('url'))})
            if path == '/api/sources/remove': return self.respond(remove_ical_source(body.get('id')))
            if path == '/api/sync': return self.sync_now()
            with LOCK:
                if path == '/api/import': return self.respond(import_snapshot(body))
                if path == '/api/preferences/import': return self.respond(import_preferences(body))
                doc = read()
                calendar_id = body.get('id')
                if calendar_id not in {c['id'] for c in doc['calendars']} or not isinstance(body.get('visible'), bool):
                    raise ValueError('known calendar id and boolean visible are required')
                hidden = set(doc.get('hidden', []))
                if body['visible']:
                    hidden.discard(calendar_id)
                else:
                    hidden.add(calendar_id)
                doc['hidden'] = sorted(hidden)
                save(doc)
                return self.respond({'ok': True, 'hidden': doc['hidden']})
        except (ValueError, TypeError, KeyError) as exc:
            return self.respond({'error': str(exc)[:300]}, 400)
        except OSError:
            return self.respond({'error': 'storage_failure; previous snapshot retained'}, 500)

    def post_switch(self):
        if self.headers.get('X-Wizard-Switch') != '1' or not self.headers.get('Origin'):
            return self.respond({'error': 'owner_browser_request_required'}, 403)
        try:
            if (self.headers.get('Content-Type') or '').split(';')[0].strip() != 'application/json': raise ValueError('json body required')
            size = int(self.headers.get('Content-Length', '0'))
            if size <= 0 or size > 4096: raise ValueError('body size')
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict) or not isinstance(body.get('id'), str) or not isinstance(body.get('on'), bool):
                raise ValueError('string id and boolean on are required')
        except (ValueError, TypeError):
            return self.respond({'error': 'bad_request: string id and boolean on are required'}, 400)
        if body['id'] not in {s['id'] for s in SWITCHES}: return self.respond({'error': 'unknown_switch'}, 404)
        try: return self.respond(set_switch(body['id'], body['on']))
        except OSError: return self.respond({'error': 'storage_failure'}, 500)

    def mcp(self, request):
        method, request_id = request.get('method'), request.get('id')
        if method == 'notifications/initialized':
            return self.respond({}, 202)
        result = None
        if method == 'initialize': result = {'protocolVersion': '2024-11-05', 'capabilities': {'tools': {}}, 'serverInfo': {'name': 'wizard-calendar', 'version': VERSION}}
        elif method == 'tools/list': result = {'tools': [{'name': name, 'description': description, 'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False}, 'annotations': {'readOnlyHint': True}} for name, description in [('calendar_events', 'Read visible events from the local snapshot.'), ('sync_status', 'Read Connected accounts sync health, setup state and last success.')]]}
        elif method == 'tools/call' and isinstance(request.get('params'), dict) and request['params'].get('name') == 'calendar_events': result = {'content': [{'type': 'text', 'text': json.dumps(view())}], 'isError': False}
        elif method == 'tools/call' and isinstance(request.get('params'), dict) and request['params'].get('name') == 'sync_status': result = {'content': [{'type': 'text', 'text': json.dumps(sync_status())}], 'isError': False}
        elif method == 'ping': result = {}
        if result is None: return self.respond({'jsonrpc': '2.0', 'id': request_id, 'error': {'code': -32601, 'message': 'Method or tool not found'}})
        return self.respond({'jsonrpc': '2.0', 'id': request_id, 'result': result})


if __name__ == '__main__':
    DATA.mkdir(parents=True, exist_ok=True)
    start_sync_worker()
    if ICAL_SYNC_INTERVAL > 0:
        threading.Thread(target=_ical_loop, name='ical-sync', daemon=True).start()
    ThreadingHTTPServer((BIND, PORT), Handler).serve_forever()
