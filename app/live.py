"""Live calendars: the Google and Microsoft apps on this box, through their box-only `wizard.mail-calendar/1` API.

Calendar never holds a sign-in. Connecting happens in the source apps (the connect sheet in web/connect.js talks to
their owner routes); here Calendar lists events from every connected account with calendar switched on, and forwards
the owner's own changes (create, edit, delete, answer an invite). Event text is other people's data: shown, never acted on.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

DEFAULT_SOURCES = 'google=http://wizard-google:18812,microsoft=http://wizard-microsoft:18814'
NAMES = {'google': 'Google', 'microsoft': 'Microsoft'}
APPS = {'google': 'wizard-google', 'microsoft': 'wizard-microsoft'}
TTL = 60
MAX_SPAN_DAYS = 400
DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
DATETIME = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})?$')
EMAIL = re.compile(r'^[^@\s<>,;"]{1,64}@[A-Za-z0-9.-]{1,253}\.[A-Za-z]{2,}$')
RESPONSES = ('accepted', 'declined', 'tentative')
OWNER = 'owner'
AGENT_NAME = re.compile(r'[a-z0-9][a-z0-9_-]{0,62}')
SUGGESTION_ID = re.compile(r'sg_[0-9a-f]{16}')
OLD_SOURCE = ('agent_access_denied', 'agent_approve_refused')
READS = ('/v1/status', '/v1/calendar_list_events')


def agent(name):
    """The caller for a request made by an agent through Calendar's MCP. The source applies the owner's agent level."""
    name = str(name or 'main').strip().lower()
    return 'agent:' + (name if AGENT_NAME.fullmatch(name) else 'main')


class Grants:
    """Calendar's App Manager grants (`outgoing: {<app id>: <token>}` in $WIZARD_GRANTS_FILE). Calendar shows a source
    app its grant only for requests made by the owner's signed-in screen, so the source can tell the owner's own
    changes and Approve taps apart from an agent (wizard-google / wizard-microsoft `agent_access.py`). Never logged."""

    def __init__(self, path):
        self.path = path
        self.stamp, self.tokens = None, {}
        self.lock = threading.Lock()

    def token(self, app_id):
        if not self.path:
            return None
        with self.lock:
            try:
                st = os.stat(self.path)
                stamp = (st.st_mtime_ns, st.st_size, st.st_ino)
                if stamp != self.stamp:
                    with open(self.path) as f:
                        doc = json.loads(f.read(256 * 1024))
                    out = doc.get('outgoing') if isinstance(doc, dict) else None
                    self.tokens = {k: v for k, v in (out or {}).items() if isinstance(k, str) and isinstance(v, str)}
                    self.stamp = stamp
            except (OSError, ValueError, AttributeError):
                self.stamp, self.tokens = None, {}
            return self.tokens.get(app_id)


class LiveError(Exception):
    def __init__(self, status, code, message):
        super().__init__(code)
        self.status, self.code, self.message = status, code, message

    def as_dict(self):
        return {'code': self.code, 'message': self.message}


def parse_sources(value):
    found = {}
    for item in (value or DEFAULT_SOURCES).split(','):
        name, _, url = item.strip().partition('=')
        parts = urllib.parse.urlsplit(url.strip())
        if name in NAMES and parts.scheme == 'http' and parts.hostname and not parts.path.strip('/'):
            found[name] = f'http://{parts.netloc}'
    return found


class Source:
    def __init__(self, sid, base, timeout=30, grants=None):
        self.id, self.base, self.timeout = sid, base, timeout
        self.grants = grants
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def call(self, method, path, body=None, caller=None):
        data = json.dumps(body).encode() if body is not None else None
        headers = {'Accept': 'application/json', 'Content-Type': 'application/json'}
        grant = self.grants.token(APPS[self.id]) if caller == OWNER and self.grants else None
        if caller == OWNER and not grant and not path.endswith(READS):
            # Without its grant Calendar would look like an agent: the owner's change would only be suggested.
            raise LiveError(403, 'owner_not_recognised', f'Calendar can\'t prove it is you to the {NAMES[self.id]} app yet. '
                            'Update Calendar from the App Store, then try again.')
        if grant:
            headers['X-Wizard-Grant'] = grant  # the owner's own tap in Calendar
        else:
            # An agent (through Calendar's MCP) or Calendar without a grant: the source applies the owner's agent level.
            headers['X-Wizard-Agent'] = caller.split(':', 1)[-1] if caller and caller != OWNER else 'wizard-calendar'
        request = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw, status = response.read(8_000_001), response.status
        except urllib.error.HTTPError as error:
            raw, status = error.read(65536), error.code
            error.close()
        except (urllib.error.URLError, OSError, TimeoutError):
            raise LiveError(503, 'source_unavailable', f'The {NAMES[self.id]} app is not reachable.') from None
        try:
            value = json.loads(raw) if raw else {}
        except ValueError:
            value = {}
        if status >= 400:
            err = value.get('error') if isinstance(value, dict) and isinstance(value.get('error'), dict) else {}
            if caller == OWNER and err.get('code') in OLD_SOURCE:
                # The source did not recognise Calendar's grant (an older App Manager or source app): say so to the owner.
                raise LiveError(403, 'owner_not_recognised', f'The {NAMES[self.id]} app did not recognise Calendar. Update Calendar '
                                f'and the {NAMES[self.id]} app, then try again.')
            raise LiveError(status if 400 <= status < 600 else 502, str(err.get('code') or 'source_error'),
                            str(err.get('message') or f'The {NAMES[self.id]} app could not do that.')[:400])
        return value if isinstance(value, dict) else {}


def _key(sid, email):
    return f'live:{sid}:{email}'


def _split(key):
    if not isinstance(key, str) or not key.startswith('live:'):
        raise LiveError(400, 'invalid_account', 'Choose a connected calendar.')
    _, sid, email = key.split(':', 2) if key.count(':') >= 2 else ('', '', '')
    if sid not in NAMES or not EMAIL.match(email or ''):
        raise LiveError(400, 'invalid_account', 'Choose a connected calendar.')
    return sid, email


def _when(value, name, required=True):
    if value in (None, '') and not required:
        return None
    if not isinstance(value, str) or not (DATE.match(value) or DATETIME.match(value)):
        raise LiveError(400, 'invalid_time', f'{name} must be a date (2026-11-04) or a time (2026-11-04T09:30).')
    return value


def _iso(value, all_day):
    """Contract times -> Calendar's shape: all-day 'YYYY-MM-DD', else ISO 8601 with offset."""
    if not isinstance(value, dict):
        return None
    if all_day or value.get('date'):
        return str(value.get('date') or '')[:10] or None
    raw = str(value.get('date_time') or '')
    if not raw:
        return None
    if raw.endswith('Z') or re.search(r'[+-]\d{2}:\d{2}$', raw):
        return raw
    try:  # a local time plus an IANA zone
        from zoneinfo import ZoneInfo
        return dt.datetime.fromisoformat(raw).replace(tzinfo=ZoneInfo(value.get('time_zone') or 'UTC')).isoformat()
    except (ValueError, KeyError, ImportError):
        return raw + 'Z'


class Live:
    def __init__(self, sources, clock=time.time, grants_file=None):
        self.grants = Grants(grants_file)
        self.sources = {sid: (s if isinstance(s, Source) else Source(sid, s, grants=self.grants)) for sid, s in sources.items()}
        self.clock, self.cache, self.lock = clock, {}, threading.Lock()
        self.pool = ThreadPoolExecutor(max_workers=8)

    def _status(self, source, caller=None):
        try:
            value = source.call('GET', '/v1/status', None, caller)
        except LiveError as error:
            return {'id': source.id, 'name': NAMES[source.id], 'app': APPS[source.id], 'available': False, 'error': error.as_dict(), 'accounts': []}
        accounts = []
        for item in value.get('accounts') or []:
            if not isinstance(item, dict) or not EMAIL.match(str(item.get('email') or '')):
                continue
            services = [s for s in item.get('services') or [] if isinstance(s, str)]
            accounts.append({'key': _key(source.id, item['email']), 'source': source.id, 'email': item['email'],
                             'label': str(item.get('label') or '')[:80], 'status': str(item.get('status') or 'active'),
                             'calendar': 'calendar' in services, 'via': str(item.get('via') or '')})
        access = value.get('calendar_access') if isinstance(value.get('calendar_access'), dict) else None
        return {'id': source.id, 'name': NAMES[source.id], 'app': APPS[source.id], 'available': True, 'error': None, 'accounts': accounts,
                'agent_access': {'level': access.get('level'), 'label': access.get('label')} if access else None}

    def status(self, caller=None):
        rows = list(self.pool.map(lambda src: self._status(src, caller), self.sources.values()))
        usable = [a for r in rows for a in r['accounts'] if a['calendar'] and a['status'] == 'active']
        return {'sources': rows, 'connected': bool(usable),
                'needs_attention': [a for r in rows for a in r['accounts'] if a['calendar'] and a['status'] != 'active']}

    def calendars(self, status=None):
        status = status or self.status()
        return [a for r in status['sources'] for a in r['accounts'] if a['calendar'] and a['status'] == 'active']

    def _list(self, account, time_min, time_max, caller=None):
        sid, email = _split(account['key'])
        out, token = [], None
        for _ in range(5):  # at most 5 pages of 100 per account and window
            args = {'account': email, 'time_min': time_min, 'time_max': time_max, 'max': 100}
            if token:
                args['page_token'] = token
            value = self.sources[sid].call('POST', '/v1/calendar_list_events', args, caller)
            out += [e for e in value.get('events') or [] if isinstance(e, dict)]
            token = value.get('next_page_token')
            if not token:
                break
        return [self._event(account, e) for e in out if e.get('id')]

    def _event(self, account, e):
        all_day = bool(e.get('all_day')) or bool((e.get('start') or {}).get('date'))
        start, end = _iso(e.get('start'), all_day), _iso(e.get('end'), all_day)
        if all_day and start and (not end or end <= start):
            end = (dt.date.fromisoformat(start) + dt.timedelta(days=1)).isoformat()
        people = [a for a in e.get('attendees') or [] if isinstance(a, dict)]
        guests = ', '.join(str(a.get('name') or a.get('email') or '')[:80] for a in people[:30] if not a.get('self'))
        meet = e.get('online_meeting')
        meet = meet.get('url') if isinstance(meet, dict) else (meet if isinstance(meet, str) else '')
        link = e.get('link') if isinstance(e.get('link'), str) and str(e.get('link')).startswith('https://') else ''
        return {
            'id': f"{account['key']}|{e.get('calendar_id') or 'primary'}|{e['id']}", 'cal': account['key'],
            'title': str(e.get('title') or '(No title)')[:300], 'start': start or '', 'end': end or start or '', 'allDay': all_day,
            'location': str(e.get('location') or '')[:300], 'description': str(e.get('description') or '')[:4000],
            'guests': guests, 'meet': meet if isinstance(meet, str) and meet.startswith('https://') else '', 'link': link,
            'live': {'account': account['key'], 'calendar_id': str(e.get('calendar_id') or 'primary'), 'id': str(e['id']),
                     'is_organizer': bool(e.get('is_organizer')), 'my_response': str(e.get('my_response') or 'none'),
                     'invited': bool(people) and not e.get('is_organizer'), 'recurring': bool(e.get('recurring')),
                     'time_zone': str((e.get('start') or {}).get('time_zone') or '')},
        }

    def window(self, start, end, caller=None):
        """Events for [start, end) (dates) from every connected calendar; cached briefly (owner and agents apart)."""
        for v in (start, end):
            if not isinstance(v, str) or not DATE.match(v):
                raise LiveError(400, 'invalid_range', 'from and to must be dates.')
        a, b = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
        if b <= a or (b - a).days > MAX_SPAN_DAYS:
            raise LiveError(400, 'invalid_range', 'Ask for at most a year at a time.')
        status = self.status(caller)
        accounts = self.calendars(status)
        # Source status projects calendar_access.level as agent_access.level; reductions must miss the cache.
        access = tuple((s['id'], (s.get('agent_access') or {}).get('level')) for s in status['sources'])
        key = (caller or '', start, end, tuple(x['key'] for x in accounts), access)  # never shared between the owner and agents
        with self.lock:
            hit = self.cache.get(key)
            if hit and self.clock() - hit[0] < TTL:
                return hit[1]
        time_min, time_max = f'{start}T00:00:00Z', f'{end}T00:00:00Z'
        jobs = {x['key']: self.pool.submit(self._list, x, time_min, time_max, caller) for x in accounts}
        events, errors = [], []
        for x in accounts:
            try:
                events += jobs[x['key']].result()
            except LiveError as error:
                errors.append({'account': x['key'], 'email': x['email'], **error.as_dict()})
        calendars = [{'id': x['key'], 'name': x['label'] or x['email'], 'email': x['email'], 'source': x['source'], 'live': True} for x in accounts]
        value = {'calendars': calendars, 'events': events, 'errors': errors, 'status': status, 'from': start, 'to': end}
        with self.lock:
            self.cache = {k: v for k, v in self.cache.items() if self.clock() - v[0] < TTL}
            self.cache[key] = (self.clock(), value)
        return value

    def changed(self):
        with self.lock:
            self.cache.clear()

    # ---------- the owner's changes ----------
    def _target(self, body):
        sid, email = _split(body.get('account'))
        return sid, email

    def _fields(self, body, partial):
        out = {}
        if not partial or 'title' in body:
            title = body.get('title')
            if not isinstance(title, str) or not title.strip() or len(title) > 300:
                raise LiveError(400, 'invalid_title', 'Give the event a title (up to 300 characters).')
            out['title'] = title.strip()
        for name in ('start', 'end'):
            if not partial or name in body:
                out[name] = _when(body.get(name), name.capitalize())
        if 'start' in out and 'end' in out and bool(DATE.match(out['start'])) != bool(DATE.match(out['end'])):
            raise LiveError(400, 'invalid_time', 'Start and end must both be dates (all day) or both times.')
        if 'start' in out and 'end' in out and out['end'] < out['start']:
            raise LiveError(400, 'invalid_time', 'The event ends before it starts.')
        for name, limit in (('location', 300), ('description', 4000)):
            if name in body:
                if not isinstance(body[name], str) or len(body[name]) > limit:
                    raise LiveError(400, f'invalid_{name}', f'{name.capitalize()} is too long.')
                out[name] = body[name]
        if 'time_zone' in body and body['time_zone']:
            if not isinstance(body['time_zone'], str) or not re.match(r'^[A-Za-z_]+(/[A-Za-z0-9_+\-]+){0,2}$', body['time_zone']):
                raise LiveError(400, 'invalid_time_zone', 'Unknown time zone.')
            out['time_zone'] = body['time_zone']
        if 'attendees' in body:
            people = body['attendees']
            if not isinstance(people, list) or len(people) > 50 or not all(isinstance(p, str) and EMAIL.match(p) for p in people):
                raise LiveError(400, 'invalid_attendees', 'Guests must be email addresses.')
            out['attendees'] = people
        return out

    def _ids(self, body):
        cal, eid = body.get('calendar_id') or 'primary', body.get('id')
        if not isinstance(eid, str) or not eid or len(eid) > 1024 or not isinstance(cal, str) or len(cal) > 512:
            raise LiveError(400, 'invalid_event', 'Unknown event.')
        return {'calendar_id': cal, 'id': eid}

    def create(self, body):
        sid, email = self._target(body)
        result = self.sources[sid].call('POST', '/v1/calendar_create_event', {'account': email, **self._fields(body, False)}, OWNER)
        self.changed()
        return {'created': True, 'id': ((result.get('event') or {}).get('id'))}

    def update(self, body):
        sid, email = self._target(body)
        fields = self._fields(body, True)
        if not fields:
            raise LiveError(400, 'nothing_to_change', 'Nothing to change.')
        self.sources[sid].call('POST', '/v1/calendar_update_event', {'account': email, **self._ids(body), **fields}, OWNER)
        self.changed()
        return {'updated': True}

    def delete(self, body):
        sid, email = self._target(body)
        self.sources[sid].call('POST', '/v1/calendar_delete_event', {'account': email, **self._ids(body)}, OWNER)
        self.changed()
        return {'deleted': True}

    def respond(self, body):
        sid, email = self._target(body)
        if body.get('response') not in RESPONSES:
            raise LiveError(400, 'invalid_response', 'Answer accepted, tentative or declined.')
        self.sources[sid].call('POST', '/v1/calendar_respond', {'account': email, **self._ids(body), 'response': body['response']}, OWNER)
        self.changed()
        return {'responded': body['response']}

    # ---------- agents' suggestions (Suggest only): kept by the source apps, applied only by the owner's Approve ----------
    def _suggestions(self, source):
        try:
            value = source.call('POST', '/v1/calendar_suggestions', {}, OWNER)
        except LiveError as error:
            return [], error
        out = []
        for item in value.get('suggestions') or []:
            if not isinstance(item, dict) or not SUGGESTION_ID.fullmatch(str(item.get('id') or '')):
                continue
            args = item.get('args') if isinstance(item.get('args'), dict) else {}
            email = str(item.get('account') or '')
            out.append({'source': source.id, 'id': item['id'], 'action': str(item.get('action') or ''), 'tool': str(item.get('tool') or ''),
                        'account': _key(source.id, email) if EMAIL.match(email) else '', 'email': email,
                        'agent': str(item.get('agent') or '').split(':', 1)[-1][:40], 'created': str(item.get('created') or ''),
                        'title': str(args.get('title') or '')[:300], 'start': args.get('start') if isinstance(args.get('start'), str) else '',
                        'end': args.get('end') if isinstance(args.get('end'), str) else '',
                        'time_zone': str(args.get('time_zone') or '')[:64], 'location': str(args.get('location') or '')[:300],
                        'description': str(args.get('description') or '')[:2000],
                        'attendees': [a for a in args.get('attendees') or [] if isinstance(a, str)][:50] if isinstance(args.get('attendees'), list) else [],
                        'event_id': str(args.get('id') or '')[:1024], 'calendar_id': str(args.get('calendar_id') or 'primary')[:512],
                        'response': str(args.get('response') or '')[:20]})
        return out, None

    def suggestions(self, available=None):
        """Pending suggestions from every source app (owner only: read with Calendar's grant)."""
        rows = [s for s in self.sources.values() if available is None or s.id in available]
        found = list(self.pool.map(self._suggestions, rows))
        items = [x for out, _ in found for x in out]
        items.sort(key=lambda x: x['created'])
        return items

    def _suggestion(self, body):
        sid, item = body.get('source'), body.get('id')
        if sid not in self.sources or not isinstance(item, str) or not SUGGESTION_ID.fullmatch(item):
            raise LiveError(400, 'invalid_suggestion', 'Unknown suggestion.')
        return self.sources[sid], item

    def approve(self, body):
        source, item = self._suggestion(body)
        source.call('POST', '/v1/calendar_suggestion_approve', {'id': item}, OWNER)
        self.changed()
        return {'approved': True, 'id': item}

    def dismiss(self, body):
        source, item = self._suggestion(body)
        source.call('POST', '/v1/calendar_suggestion_dismiss', {'id': item}, OWNER)
        return {'dismissed': True, 'id': item}
