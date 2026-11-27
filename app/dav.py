"""Calendar on Radicale (issue 61; on for everyone, its `radicale` switch is gone).

Calendar ships a stock Radicale (ghcr.io/kozea/radicale, no fork) as a second service in its runtipi compose. It is on
the app's own network only (no port, not on the Wizard's main network), so nothing but Calendar's server reaches it.
Calendar talks to it with a random password it makes at each start and keeps only in memory (Radicale's htpasswd file,
DATA/radicale/users, gets its SHA-512-crypt hash), and phones reach it only through Calendar's `/dav/` path on the Wizard
(the tailnet), with a separate phone password.

Collections, all owned by Radicale user `owner`:
  /owner/calendar/  the calendar on this Wizard (what was DATA/local.json): one .ics object per event series
  /owner/contacts/  the address book Contacts keeps there (humanitylabs-org/contacts, through /service/dav/)

Radicale holds the events and DATA/local.json stays as a full mirror of them (written on every change and every read
that pulled something new). So:
  - the first read (or Calendar's start) migrates every existing event across (each one is PUT once; nothing is
    removed from local.json),
  - a phone's change shows in Calendar on the next read (the collection's ctag changed: changed objects are parsed),
  - when Radicale is down, or its data is wiped, Calendar keeps working from the mirror and pushes the pending changes
    (or everything again) later.

Book-keeping lives in local.json under `dav`: {objects: {uid: {href, etag, hash}}, ctag}. `hash` is the event as
Calendar last synced it, so a change made in Calendar (hash differs) is pushed and one made on a phone (etag differs)
is pulled. If both changed the same event, the phone's copy wins and Calendar's edit is kept as a separate event.
"""
from __future__ import annotations

import base64
import hashlib
import http.client
import json
import os
import re
import secrets
import threading
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

USER = 'owner'
CALENDAR = f'/{USER}/calendar/'
CONTACTS = f'/{USER}/contacts/'
NS = {'d': 'DAV:', 'c': 'urn:ietf:params:xml:ns:caldav', 'cs': 'http://calendarserver.org/ns/',
      'card': 'urn:ietf:params:xml:ns:carddav'}
MAX_BODY = 32 * 1024 * 1024
FIELDS = ('title', 'start', 'end', 'time_zone', 'location', 'description', 'rrule', 'exdates', 'overrides')
HREF_NAME = re.compile(r'[A-Za-z0-9@._-]{1,200}')


class DavError(OSError):
    """Radicale could not be reached or refused a request."""


def rec_hash(rec):
    """The content of one stored event (what a phone can change), independent of Calendar's book-keeping."""
    return hashlib.sha256(json.dumps({k: rec.get(k) for k in FIELDS}, sort_keys=True).encode()).hexdigest()[:32]


class Radicale:
    """A tiny CalDAV/CardDAV client for the bundled Radicale (stdlib only)."""

    def __init__(self, url, users_file, timeout=10):
        parts = urlsplit(url)
        if parts.scheme != 'http' or not parts.hostname:
            raise ValueError('CALENDAR_RADICALE_URL must be http://host:port')
        self.host, self.port, self.timeout = parts.hostname, parts.port or 80, timeout
        self.users_file = Path(users_file)
        self.lock = threading.Lock()
        self._ready = False
        self._secret = None

    # ---------- the box-local password Calendar uses ----------
    # A fresh random password each time Calendar starts, kept only in memory; Radicale's htpasswd file gets its
    # SHA-512-crypt hash (Radicale re-reads the file on every login, so the new one works at once).
    def secret(self):
        with self.lock:
            if self._secret is None:
                # A 256-bit random machine key (not something a person types), so a fast hash is enough.
                token = secrets.token_urlsafe(32)
                self.users_file.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.users_file.with_name('.users.tmp')
                tmp.write_text(f'{USER}:{sha512_crypt(token, secrets.token_hex(8))}\n')
                os.chmod(tmp, 0o600)
                os.replace(tmp, self.users_file)
                self._secret = token
            return self._secret

    def auth(self):
        try:
            secret = self.secret()
        except OSError as exc:  # its folder not writable yet (a fresh install): Radicale is not usable yet either
            raise DavError(f'Radicale password file: {type(exc).__name__}') from None
        return 'Basic ' + base64.b64encode(f'{USER}:{secret}'.encode()).decode()

    # ---------- HTTP ----------
    def request(self, method, path, body=None, headers=None, script_name=None):
        """(status, headers dict (lower-case names), body bytes). Raises DavError when Radicale is not reachable."""
        if isinstance(body, str):
            body = body.encode()
        head = {'Authorization': self.auth(), **(headers or {})}
        if script_name:
            head['X-Script-Name'] = script_name
        if body is not None:
            head['Content-Length'] = str(len(body))
        conn = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
        try:
            conn.request(method, path, body=body, headers=head)
            resp = conn.getresponse()
            data = resp.read(MAX_BODY + 1)
            if len(data) > MAX_BODY:
                raise DavError('Radicale answer too large')
            return resp.status, {k.lower(): v for k, v in resp.getheaders()}, data
        except (OSError, http.client.HTTPException) as exc:
            raise DavError(f'Radicale unreachable: {type(exc).__name__}') from None
        finally:
            conn.close()

    def ensure(self):
        """Create the owner's calendar and address book once (idempotent)."""
        if self._ready:
            return
        status, _, _ = self.request('PROPFIND', CALENDAR, '', {'Depth': '0'})
        if status == 404:
            body = ('<?xml version="1.0" encoding="utf-8"?><c:mkcalendar xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
                    '<d:set><d:prop><d:displayname>On this Wizard</d:displayname><c:supported-calendar-component-set>'
                    '<c:comp name="VEVENT"/></c:supported-calendar-component-set></d:prop></d:set></c:mkcalendar>')
            status, _, _ = self.request('MKCALENDAR', CALENDAR, body, {'Content-Type': 'application/xml; charset=utf-8'})
            if status not in (201, 405):
                raise DavError(f'Radicale refused the calendar ({status})')
        elif status >= 400:
            raise DavError(f'Radicale refused Calendar ({status})')
        status, _, _ = self.request('PROPFIND', CONTACTS, '', {'Depth': '0'})
        if status == 404:
            body = ('<?xml version="1.0" encoding="utf-8"?><d:mkcol xmlns:d="DAV:" xmlns:card="urn:ietf:params:xml:ns:carddav">'
                    '<d:set><d:prop><d:resourcetype><d:collection/><card:addressbook/></d:resourcetype>'
                    '<d:displayname>Contacts</d:displayname></d:prop></d:set></d:mkcol>')
            status, _, _ = self.request('MKCOL', CONTACTS, body, {'Content-Type': 'application/xml; charset=utf-8'})
            if status not in (201, 405):
                raise DavError(f'Radicale refused the address book ({status})')
        self._ready = True

    def ctag(self, collection):
        body = ('<?xml version="1.0" encoding="utf-8"?><d:propfind xmlns:d="DAV:" xmlns:cs="http://calendarserver.org/ns/">'
                '<d:prop><cs:getctag/></d:prop></d:propfind>')
        status, _, data = self.request('PROPFIND', collection, body, {'Depth': '0', 'Content-Type': 'application/xml; charset=utf-8'})
        if status == 404 and self._ready:
            self._ready = False  # Radicale's data was reset: make the collections again
            self.ensure()
            status, _, data = self.request('PROPFIND', collection, body, {'Depth': '0', 'Content-Type': 'application/xml; charset=utf-8'})
        if status != 207:
            raise DavError(f'Radicale ctag failed ({status})')
        node = ET.fromstring(data).find('.//cs:getctag', NS)
        return (node.text or '') if node is not None else ''

    def objects(self, collection, kind='calendar'):
        """{href name: (etag, text)} of every object in a collection (one REPORT)."""
        if kind == 'calendar':
            body = ('<?xml version="1.0" encoding="utf-8"?><c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
                    '<d:prop><d:getetag/><c:calendar-data/></d:prop><c:filter><c:comp-filter name="VCALENDAR"/></c:filter>'
                    '</c:calendar-query>')
            data_tag = 'c:calendar-data'
        else:
            body = ('<?xml version="1.0" encoding="utf-8"?><card:addressbook-query xmlns:d="DAV:" xmlns:card="urn:ietf:params:xml:ns:carddav">'
                    '<d:prop><d:getetag/><card:address-data/></d:prop></card:addressbook-query>')
            data_tag = 'card:address-data'
        status, _, data = self.request('REPORT', collection, body, {'Depth': '1', 'Content-Type': 'application/xml; charset=utf-8'})
        if status != 207:
            raise DavError(f'Radicale listing failed ({status})')
        out = {}
        for resp in ET.fromstring(data).findall('d:response', NS):
            href = resp.findtext('d:href', '', NS)
            name = unquote(href.rstrip('/').rsplit('/', 1)[-1])
            if not href or href.endswith('/') or not name:
                continue
            etag = resp.findtext('.//d:getetag', '', NS)
            text = resp.findtext('.//' + data_tag, '', NS)
            out[name] = (etag, text)
        return out

    def put(self, collection, name, text, etag=None, create=False, content_type='text/calendar; charset=utf-8'):
        head = {'Content-Type': content_type}
        if create:
            head['If-None-Match'] = '*'
        elif etag:
            head['If-Match'] = etag
        status, headers, _ = self.request('PUT', collection + quote(name), text, head)
        if status in (404, 409) and self._ready:
            self._ready = False  # Radicale's data was reset: make the collections again, then retry once
            self.ensure()
            status, headers, _ = self.request('PUT', collection + quote(name), text, head)
        if status == 412:
            return None  # changed (or created) on the server meanwhile
        if status not in (200, 201, 204):
            raise DavError(f'Radicale refused a change ({status})')
        return headers.get('etag') or ''

    def delete(self, collection, name, etag=None):
        status, _, _ = self.request('DELETE', collection + quote(name), None, {'If-Match': etag} if etag else {})
        if status not in (200, 204, 404, 412):
            raise DavError(f'Radicale refused a delete ({status})')
        return status != 412


class DavCalendar:
    """local_cal.Local's load/save: Radicale is the store, local.json the mirror."""

    def __init__(self, radicale, read_mirror, write_mirror, local_mod, timezone, log=None):
        self.rad, self.read_mirror, self.write_mirror, self.lc, self.tz = radicale, read_mirror, write_mirror, local_mod, timezone
        self.lock = threading.RLock()
        self.log = log or (lambda message: None)
        self.last_error = ''

    @staticmethod
    def _base(doc):
        if not isinstance(doc, dict) or doc.get('schemaVersion') != 1 or not isinstance(doc.get('events'), list):
            doc = {'schemaVersion': 1, 'events': [], 'agentAccess': 'read_only'}
        dav = doc.get('dav') if isinstance(doc.get('dav'), dict) else {}
        objects = dav.get('objects') if isinstance(dav.get('objects'), dict) else {}
        doc['dav'] = {'objects': {k: v for k, v in objects.items() if isinstance(v, dict) and isinstance(v.get('href'), str)},
                      'ctag': dav.get('ctag') if isinstance(dav.get('ctag'), str) else ''}
        return doc

    def ics(self, rec):
        """One event series (master + changed repeats) as its own VCALENDAR object."""
        one = self.lc.Local(lambda: {'schemaVersion': 1, 'events': [rec]}, lambda d: None, self.tz)
        return one.export_ics()

    def _parse(self, text, old=None):
        """A Radicale object -> a stored event (None for anything Calendar can't show, e.g. a VTODO)."""
        tmp = {'schemaVersion': 1, 'events': [], 'agentAccess': 'read_only'}
        one = self.lc.Local(lambda: tmp, lambda d: None, self.tz)
        try:
            one.import_ics(text)
        except Exception:  # noqa: BLE001 - a phone's odd object never breaks the calendar
            return None
        if not tmp['events']:
            return None
        rec = tmp['events'][0]
        if old is not None:
            rec['uid'] = old['uid']
            rec['created'] = old.get('created', rec.get('created'))
        rec['by_agent'] = False
        return rec

    # ---------- the two calls local_cal.Local makes ----------
    def load(self):
        with self.lock:
            doc = self._base(self.read_mirror())
            try:
                self.rad.ensure()
                changed = self._push(doc)
                ctag = self.rad.ctag(CALENDAR)
                if ctag != doc['dav']['ctag']:
                    self._pull(doc)
                    doc['dav']['ctag'] = ctag  # read before the listing: a change made meanwhile is pulled next time
                    changed = True
                if changed:
                    self.write_mirror(doc)
                self.last_error = ''
            except (DavError, ET.ParseError) as exc:
                # Radicale down: the mirror has every event; pending changes are pushed on a later read.
                self.last_error = str(exc)
                self.log(f'radicale: {exc}')
            return doc

    def save(self, doc):
        with self.lock:
            doc = self._base(doc)
            self.write_mirror(doc)  # the mirror first: an owner's change is never lost to a Radicale outage
            try:
                self.rad.ensure()
                if self._push(doc):
                    self.write_mirror(doc)
                self.last_error = ''
            except (DavError, ET.ParseError) as exc:
                self.last_error = str(exc)
                self.log(f'radicale: {exc}')

    # ---------- sync ----------
    def _push(self, doc):
        """Send Calendar's own changes (new, edited, deleted events). True when anything was sent."""
        objects, sent = doc['dav']['objects'], False
        uids = set()
        for rec in doc['events']:
            uid = rec.get('uid')
            if not isinstance(uid, str):
                continue
            uids.add(uid)
            known, digest = objects.get(uid), rec_hash(rec)
            if known and known.get('hash') == digest:
                continue
            name = known['href'] if known else f'{uid}.ics'
            etag = self.rad.put(CALENDAR, name, self.ics(rec), etag=known.get('etag') if known else None, create=not known)
            if etag is None:
                # Changed on a phone too (or already there): the pull below brings the phone's copy; Calendar's edit
                # is kept as its own event so nothing is lost.
                if known:
                    copy = dict(rec, uid=secrets.token_hex(12))
                    copy.pop('ical_uid', None)
                    doc['events'].append(copy)
                    objects[uid] = dict(known, hash='')
                continue
            objects[uid] = {'href': name, 'etag': etag, 'hash': digest}
            sent = True
        for uid in [u for u in objects if u not in uids and not objects[u].get('foreign')]:
            if self.rad.delete(CALENDAR, objects[uid]['href'], objects[uid].get('etag')):
                objects.pop(uid)
                sent = True
            else:
                objects[uid]['etag'] = ''  # changed on a phone: the pull brings it back
        return sent

    def _pull(self, doc):
        """Bring the phone's changes (new, edited, deleted objects) into the stored events."""
        objects = doc['dav']['objects']
        server = self.rad.objects(CALENDAR)
        known = {v['href'] for v in objects.values() if not v.get('foreign')}
        if len(known) >= 3 and not known & set(server):
            # None of Calendar's objects is there any more: Radicale's data was reset (a phone deletes one by one).
            # Keep every event and copy them across again.
            objects.clear()
            self._push(doc)
            server = self.rad.objects(CALENDAR)
        by_href = {v['href']: uid for uid, v in objects.items()}
        recs = {r.get('uid'): r for r in doc['events']}
        for name, (etag, text) in server.items():
            uid = by_href.get(name)
            if uid is None and name.endswith('.ics') and name[:-4] in recs:
                uid = name[:-4]  # Calendar's own object whose book-keeping was lost (e.g. a restored mirror)
            known = objects.get(uid) if uid else None
            if known and known.get('etag') == etag and (uid in recs or known.get('foreign')):
                continue  # unchanged since Calendar wrote or read it
            old = recs.get(uid) if uid else None
            rec = self._parse(text, old)
            if rec is None:
                objects[uid or f'foreign:{name}'] = {'href': name, 'etag': etag, 'hash': '', 'foreign': True}
                continue
            if old is not None:
                old.clear()
                old.update(rec)
            else:
                doc['events'].append(rec)
                recs[rec['uid']] = rec
            if uid and uid != rec['uid']:
                objects.pop(uid, None)
            objects[rec['uid']] = {'href': name, 'etag': etag, 'hash': rec_hash(rec)}
        # Objects deleted on a phone: their events go too.
        gone = {uid for uid, v in objects.items() if v['href'] not in server}
        for uid in gone:
            objects.pop(uid)
        if gone:
            doc['events'] = [r for r in doc['events'] if r.get('uid') not in gone]


_B64 = './0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'
_ORDER = ((0, 21, 42), (22, 43, 1), (44, 2, 23), (3, 24, 45), (25, 46, 4), (47, 5, 26), (6, 27, 48), (28, 49, 7), (50, 8, 29),
          (9, 30, 51), (31, 52, 10), (53, 11, 32), (12, 33, 54), (34, 55, 13), (56, 14, 35), (15, 36, 57), (37, 58, 16),
          (59, 17, 38), (18, 39, 60), (40, 61, 19), (62, 20, 41))


def sha512_crypt(key, salt, rounds=5000):
    """The `$6$` SHA-512-crypt hash (glibc crypt(3), what Radicale's htpasswd `sha512` reads) of Calendar's random
    machine key, stdlib only."""
    p, s = key.encode(), salt.encode()[:16]
    b = hashlib.sha512(p + s + p).digest()
    a = hashlib.sha512(p + s)
    n = len(p)
    while n > 64:
        a.update(b)
        n -= 64
    a.update(b[:n])
    n = len(p)
    while n:
        a.update(b if n & 1 else p)
        n >>= 1
    c = a.digest()
    dp = hashlib.sha512(p * len(p)).digest()
    pb = (dp * (len(p) // 64 + 1))[:len(p)]
    ds = hashlib.sha512(s * (16 + c[0])).digest()
    sb = (ds * (len(s) // 64 + 1))[:len(s)]
    for r in range(rounds):
        h = hashlib.sha512(pb if r & 1 else c)
        if r % 3:
            h.update(sb)
        if r % 7:
            h.update(pb)
        h.update(c if r & 1 else pb)
        c = h.digest()
    out = []
    for x, y, z in _ORDER:
        w = (c[x] << 16) | (c[y] << 8) | c[z]
        out += [_B64[(w >> (6 * i)) & 63] for i in range(4)]
    w = c[63]
    out += [_B64[w & 63], _B64[(w >> 6) & 63]]
    prefix = '$6$' if rounds == 5000 else f'$6$rounds={rounds}$'
    return prefix + s.decode() + '$' + ''.join(out)


def safe_name(name):
    return bool(HREF_NAME.fullmatch(name)) and name not in ('.', '..')
