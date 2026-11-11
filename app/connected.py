"""Connected accounts calendars, read-only (issue 31).

Connected accounts (app id `connected-accounts`, formerly `wizard-connectors`) shares the Google calendars its owner
allowed for Calendar through a grant-scoped service API: `GET /service/calendar/status`, `POST .../calendars` ({}) and
`POST .../events` ({account, calendar_id, time_min, time_max}). It has no write operations, so these calendars are
shown next to Google and Microsoft but can't be changed in Calendar (like private iCal links). 0.3.0 had this as a
background sync; #24 dropped it by accident. Now it is read for the window the page shows, cached briefly.

The grant and endpoint come from the App Manager's grants file (re-read on every call; never logged). Without a grant
(Connected accounts not installed, or Calendar not allowed) Calendar shows nothing from it and says nothing.
Event text is other people's data: shown, never acted on.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

APP_IDS = ('connected-accounts', 'wizard-connectors', 'slot:calendar-source')
SOURCE = 'connected-accounts'
NAME = 'Connected accounts'
TTL = 300
MAX_BYTES = 4 * 1024 * 1024
MAX_CALENDARS = 100
DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
CODES = {'reauth_required': 'sign in again in Connected accounts',
         'incremental_consent_required': 'allow Calendar again in Connected accounts',
         'capability_denied': 'allow Calendar again in Connected accounts',
         'google_configuration_required': 'finish setting up your Google app in Connected accounts'}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    # Never forward a grant to a redirected host.
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class SourceError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _hash(*parts):
    return hashlib.sha256(json.dumps(parts).encode()).hexdigest()[:32]


def _when(value, all_day):
    if not isinstance(value, str):
        return None
    try:
        if all_day:
            return value if DATE.match(value) else None
        moment = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
        return value if moment.tzinfo is not None else None
    except ValueError:
        return None


def _https(value):
    if not isinstance(value, str) or len(value) > 2000:
        return ''
    url = urlsplit(value)
    return value if url.scheme == 'https' and url.hostname and not url.username and not url.password else ''


class Connected:
    def __init__(self, grants_file, url=None, clock=time.time, timeout=15):
        self.grants_file, self.url, self.clock, self.timeout = grants_file, url, clock, timeout
        self.lock = threading.Lock()
        self.cache = {}  # (start, end) -> (time, value)
        self.last_good = []  # the calendars of the last good listing, still shown when Connected accounts is down
        self.opener = urllib.request.build_opener(NoRedirect, urllib.request.ProxyHandler({}))

    def link(self):
        """(base URL, grant) for Connected accounts, or None. Re-read each time: the App Manager rotates grants."""
        try:
            with open(self.grants_file, 'rb') as handle:
                raw = handle.read(262145)
            if len(raw) > 262144:
                return None
            grants = json.loads(raw)
            outgoing, endpoints = grants.get('outgoing') or {}, grants.get('provider_endpoints') or {}
            if not isinstance(outgoing, dict) or not isinstance(endpoints, dict):
                return None
            key = next((outgoing[k] for k in APP_IDS if isinstance(outgoing.get(k), str) and outgoing[k]), None)
            base = next((endpoints[k] for k in APP_IDS if isinstance(endpoints.get(k), str) and endpoints[k]), None) or self.url
            if not key or not isinstance(base, str):
                return None
            url = urlsplit(base)
            if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or url.query or url.fragment:
                return None
            return base.rstrip('/'), key
        except (OSError, TypeError, ValueError, AttributeError):
            return None

    def _call(self, link, path, body=None):
        base, key = link
        request = urllib.request.Request(base + '/service/calendar/' + path,
                                         data=None if body is None else json.dumps(body).encode(),
                                         headers={'X-Wizard-Grant': key, 'Content-Type': 'application/json', 'Accept': 'application/json'})
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read(MAX_BYTES + 1)
        except urllib.error.HTTPError as error:
            # Only a stable code crosses over, never the body.
            try:
                code = json.loads(error.read(4096)).get('error')
            except (ValueError, AttributeError):
                code = None
            finally:
                error.close()
            raise SourceError(code if isinstance(code, str) and code in CODES else f'http_{error.code}') from None
        except (urllib.error.URLError, OSError, TimeoutError):
            raise SourceError('unreachable') from None
        if len(raw) > MAX_BYTES:
            raise SourceError('too_large')
        try:
            value = json.loads(raw)
        except ValueError:
            raise SourceError('invalid_response') from None
        if not isinstance(value, dict):
            raise SourceError('invalid_response')
        return value

    def _events(self, link, cid, account, calendar_id, start, end):
        value = self._call(link, 'events', {'account': account, 'calendar_id': calendar_id,
                                            'time_min': f'{start}T00:00:00Z', 'time_max': f'{end}T00:00:00Z'})
        if not isinstance(value.get('events'), list):
            raise SourceError('invalid_response')
        out, seen = [], set()
        for e in value['events']:
            if not isinstance(e, dict) or not isinstance(e.get('id'), str) or not e['id']:
                continue
            if e.get('status') == 'cancelled' or e.get('self_response') == 'declined':
                continue
            all_day = e.get('all_day') is True
            first, last = _when(e.get('start'), all_day), _when(e.get('end'), all_day)
            if not first:
                continue
            if all_day and (not last or last <= first):
                last = (dt.date.fromisoformat(first) + dt.timedelta(days=1)).isoformat()
            last = last or first
            eid = f'{cid}:{_hash(e["id"])}'
            if eid in seen:
                continue
            seen.add(eid)
            out.append({'id': eid, 'cal': cid, 'title': str(e.get('title') or '(No title)')[:300],
                        'start': first, 'end': last, 'allDay': all_day,
                        'location': str(e.get('location') or '')[:500], 'description': str(e.get('description') or '')[:4000],
                        'link': _https(e.get('html_link')), 'meet': _https(e.get('meet')), 'readOnly': SOURCE})
        return out, value.get('truncated') is True

    def window(self, start, end, skip_emails=()):
        """Calendars and events for [start, end) (dates). Accounts also connected through the Google app (skip_emails)
        are left out, so an account connected both ways shows once, from the source that can change it."""
        empty = {'calendars': [], 'events': [], 'errors': []}
        link = self.link()
        if not link or not (isinstance(start, str) and DATE.match(start) and isinstance(end, str) and DATE.match(end)):
            return empty
        skip = {str(x).lower() for x in skip_emails}
        key = (start, end, tuple(sorted(skip)))
        with self.lock:
            hit = self.cache.get(key)
            if hit and self.clock() - hit[0] < TTL:
                return hit[1]
        calendars, events, errors = [], [], []
        try:
            status = self._call(link, 'status')
            allowed = {a.get('account'): a for a in status.get('accounts') or []
                       if isinstance(a, dict) and a.get('calendar_allowed') is True and a.get('status') == 'active'}
            listing = self._call(link, 'calendars', {}) if allowed else {'calendars': []}
            rows = listing.get('calendars')
            if not isinstance(rows, list):
                raise SourceError('invalid_response')
            for item in rows[:MAX_CALENDARS]:
                if not isinstance(item, dict) or item.get('account') not in allowed or not isinstance(item.get('id'), str):
                    continue
                email = str(item.get('email') or allowed[item['account']].get('email') or '')[:300]
                if email.lower() in skip:
                    continue
                cid = 'ca:' + _hash(item['account'], item['id'])
                name = str(item.get('name') or email or 'Google')[:300]
                cal = {'id': cid, 'name': name, 'email': email, 'source': SOURCE, 'readOnly': True}
                try:
                    rows_, truncated = self._events(link, cid, item['account'], item['id'], start, end)
                    events += rows_
                    if truncated:
                        errors.append(f'{name}: {NAME} sent only part of this calendar')
                except SourceError as error:
                    errors.append(f'{email or name}: {CODES.get(error.code, "could not load this calendar from " + NAME)}')
                calendars.append(cal)
            self.last_good = calendars
        except SourceError as error:
            # Connected accounts is down or refused: keep showing the calendars it last shared (without events) so
            # they don't silently vanish, and say why. Nothing shared before: say nothing.
            if not self.last_good:
                return empty
            calendars = [cal for cal in self.last_good if str(cal.get('email', '')).lower() not in skip]
            errors.append(f'{NAME}: {CODES.get(error.code, "not reachable right now")}')
        value = {'calendars': calendars, 'events': events, 'errors': errors}
        with self.lock:
            self.cache = {k: v for k, v in self.cache.items() if self.clock() - v[0] < TTL}
            self.cache[key] = (self.clock(), value)
        return value


def from_env(grants_file):
    if os.environ.get('CALENDAR_CONNECTED_ACCOUNTS', 'on') == 'off':
        return None
    return Connected(grants_file, url=os.environ.get('CONNECTORS_URL') or None)
