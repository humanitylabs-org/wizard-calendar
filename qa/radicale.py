#!/usr/bin/env python3
"""Calendar on Radicale (issue 61, switch `radicale`): a real stock Radicale, a scratch Calendar, a "phone" that speaks
CalDAV/CardDAV through Calendar's /dav/ path, and Contacts' grant-scoped /service/dav/ address book.

python3 qa/radicale.py

Radicale comes from the same pinned image the app ships (docker), or `python3 -m radicale` when it is installed
(pip install radicale==3.9.2). Checks: migration of existing events (repeat, changed repeat, deleted repeat), phone
add / edit / delete showing in Calendar, Calendar and agent changes and .ics imports landing in Radicale, the agent's
tools unchanged, Contacts' address book (grant only, nothing else reachable), switching off with nothing lost, and a
Radicale outage (Calendar keeps working from its mirror and catches up).
"""
import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'qa'))
COMPOSE = json.loads((ROOT / 'runtipi' / 'docker-compose.yml').read_text())
IMAGE = COMPOSE['services']['wizard-calendar-dav']['image']
ARGS = COMPOSE['services']['wizard-calendar-dav']['command']
checks = []


def check(name, ok, detail=''):
    checks.append((name, bool(ok)))
    print(('PASS ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


class Radicale:
    def __init__(self, folder):
        self.folder, self.port = Path(folder), free_port()
        self.folder.mkdir(parents=True, exist_ok=True)
        self.name = f'qa-radicale-{os.getpid()}'
        self.proc = None

    def start(self):
        # The same arguments as the shipped compose service; only the folder is mounted from here.
        if shutil.which('docker') and not os.environ.get('QA_RADICALE_PYTHON'):
            subprocess.run(['docker', 'rm', '-f', self.name], capture_output=True)
            subprocess.run(['docker', 'run', '-d', '--name', self.name, '--user', f'{os.getuid()}:{os.getgid()}', '--cap-drop', 'ALL',
                            '--security-opt', 'no-new-privileges:true', '--read-only', '--tmpfs', '/tmp',
                            '-p', f'127.0.0.1:{self.port}:5232', '-v', f'{self.folder}:/var/lib/radicale', IMAGE, *ARGS],
                           check=True, capture_output=True)
        else:
            args = [a.replace('/var/lib/radicale', str(self.folder)) for a in ARGS]
            args[args.index('--hosts') + 1] = f'127.0.0.1:{self.port}'
            self.proc = subprocess.Popen([sys.executable, '-m', 'radicale', *args], stderr=subprocess.DEVNULL)
        self.wait()

    def wait(self):
        for _ in range(150):
            try:
                urllib.request.urlopen(f'http://127.0.0.1:{self.port}/.web/', timeout=1).read()
                return
            except urllib.error.HTTPError:
                return
            except OSError:
                time.sleep(0.2)
        raise SystemExit('radicale did not start')

    def stop(self):
        if self.proc:
            self.proc.terminate()
            self.proc.wait(5)
            self.proc = None
        else:
            subprocess.run(['docker', 'rm', '-f', self.name], capture_output=True)

    def stored(self):
        """Calendar's collection as Radicale keeps it on disk."""
        root = self.folder / 'collections' / 'collection-root' / 'owner' / 'calendar'
        return {f.name: f.read_text() for f in root.glob('*.ics')} if root.is_dir() else None


class Box:
    def __init__(self, data, radicale, grants):
        self.port = free_port()
        self.base = f'http://127.0.0.1:{self.port}'
        env = dict(os.environ, DATA_DIR=str(data), PORT=str(self.port), CALENDAR_LIVE='off', CALENDAR_CONNECTED_ACCOUNTS='off',
                   CALENDAR_DEV_MODE='loopback-single-owner', CALENDAR_TIMEZONE='Europe/Berlin', ICAL_SYNC_INTERVAL='0',
                   WIZARD_GRANTS_FILE=str(grants), CALENDAR_RADICALE_URL=f'http://127.0.0.1:{radicale.port}',
                   CALENDAR_RADICALE_USERS=str(radicale.folder / 'users'))
        self.proc = subprocess.Popen([sys.executable, str(ROOT / 'app' / 'server.py')], env=env, cwd=ROOT, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                urllib.request.urlopen(self.base + '/healthz', timeout=1).read()
                return
            except OSError:
                time.sleep(0.1)
        raise SystemExit('calendar did not start')

    def stop(self):
        self.proc.terminate()
        self.proc.wait(5)

    def raw(self, method, path, body=None, headers=None):
        req = urllib.request.Request(self.base + path, data=body.encode() if isinstance(body, str) else body, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status, dict(r.headers), r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read().decode()

    def call(self, method, path, body=None, owner=True, headers=None):
        h = {'Content-Type': 'application/json'}
        if owner:
            h.update({'X-Wizard-Request': 'calendar', 'Origin': self.base, 'Sec-Fetch-Site': 'same-origin'})
        h.update(headers or {})
        status, _, raw = self.raw(method, path, json.dumps(body) if body is not None else None, h)
        try:
            return status, json.loads(raw)
        except ValueError:
            return status, raw

    def titles(self):
        status, doc = self.call('GET', '/api/events?from=2026-11-01&to=2027-01-31')
        assert status == 200, (status, doc)
        return sorted({e['title'] for e in doc['events'] if e['cal'] == 'local'}), doc

    def tool(self, name, args=None):
        status, out = self.call('POST', '/mcp', {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                                                  'params': {'name': name, 'arguments': args or {}}}, owner=False,
                                headers={'X-Wizard-Agent': 'hermes'})
        return out['result']['isError'], json.loads(out['result']['content'][0]['text'])


def _status(url, userpass):
    req = urllib.request.Request(url, method='PROPFIND', headers={'Authorization': 'Basic ' + base64.b64encode(userpass.encode()).decode(), 'Depth': '0'})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def phone(box, password, method, path, body=None, headers=None):
    h = {'Authorization': 'Basic ' + base64.b64encode(f'owner:{password}'.encode()).decode(), **(headers or {})}
    return box.raw(method, path, body, h)


def vevent(uid, title, start, end):
    return ('BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//QA phone//EN\r\nBEGIN:VEVENT\r\n'
            f'UID:{uid}\r\nDTSTAMP:20261120T090000Z\r\nDTSTART;TZID=Europe/Berlin:{start}\r\nDTEND;TZID=Europe/Berlin:{end}\r\n'
            f'SUMMARY:{title}\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n')


SEED = {'schemaVersion': 1, 'agentAccess': 'can_edit', 'events': [
    {'uid': 'a' * 24, 'title': 'Dentist', 'start': '2026-11-24T09:00', 'end': '2026-11-24T10:00', 'time_zone': 'Europe/Berlin',
     'location': 'Main St', 'description': 'Bring card', 'rrule': '', 'exdates': [], 'overrides': {},
     'created': '2026-11-01T00:00:00+00:00', 'updated': '2026-11-01T00:00:00+00:00', 'by_agent': False},
    {'uid': 'b' * 24, 'title': 'Standup', 'start': '2026-11-23T09:30', 'end': '2026-11-23T09:45', 'time_zone': 'Europe/Berlin',
     'location': '', 'description': '', 'rrule': 'FREQ=DAILY;COUNT=10', 'exdates': ['2026-11-25T08:30:00+00:00'],
     'overrides': {'2026-11-26T08:30:00+00:00': {'title': 'Standup (late)', 'start': '2026-11-26T11:00', 'end': '2026-11-26T11:15',
                                                 'time_zone': 'Europe/Berlin'}},
     'created': '2026-11-01T00:00:00+00:00', 'updated': '2026-11-01T00:00:00+00:00', 'by_agent': False},
    {'uid': 'c' * 24, 'title': 'Holiday', 'start': '2026-12-24', 'end': '2026-12-27', 'time_zone': 'Europe/Berlin',
     'location': '', 'description': '', 'rrule': '', 'exdates': [], 'overrides': {},
     'created': '2026-11-01T00:00:00+00:00', 'updated': '2026-11-01T00:00:00+00:00', 'by_agent': False},
]}


def main():
    tmp = Path(tempfile.mkdtemp(prefix='cal-radicale-'))
    data, folder = tmp / 'data', tmp / 'radicale'
    data.mkdir()
    (data / 'local.json').write_text(json.dumps(SEED))
    grants = tmp / 'grants.json'
    grants.write_text(json.dumps({'incoming': [{'from': 'contacts', 'sha256': hashlib.sha256(b'contacts-grant').hexdigest()}]}))
    rad = Radicale(folder)
    box = Box(data, rad, grants)  # writes Radicale's password file on start
    rad.start()
    try:
        before, doc = box.titles()
        check('switch is listed, off by default', any(s['id'] == 'radicale' and s['on'] is False and 'humanitylabs-org/wizard-calendar#61' in s['issues']
                                                     for s in box.call('GET', '/api/switches', headers={'X-Wizard-Switch': '1'})[1]['switches']))
        check('off: phones get nothing', phone(box, 'x', 'PROPFIND', '/dav/', '', {'Depth': '0'})[0] == 404)
        check('off: nothing is put in Radicale', rad.stored() is None)
        users = (folder / 'users').read_text()
        check('Radicale gets a SHA-512 hash, never a clear password', users.startswith('owner:$6$') and len(users.strip()) > 90, users[:12])
        check('Radicale itself refuses anyone without Calendar\'s password', urllib.request.Request is not None and
              _status(f'http://127.0.0.1:{rad.port}/owner/', 'owner:guess') == 401)

        (data / 'switches.json').write_text(json.dumps({'radicale': True}))
        after, doc = box.titles()
        check('on: the same events show (migrated)', after == before == ['Dentist', 'Holiday', 'Standup', 'Standup (late)'], after)
        listing = ''.join((rad.stored() or {}).values())
        check('Radicale holds every event, with its repeat, changed repeat and deleted repeat',
              listing.count('BEGIN:VEVENT') == 4 and 'RRULE:FREQ=DAILY;COUNT=10' in listing
              and 'EXDATE;TZID=Europe/Berlin:20261125T093000' in listing and 'RECURRENCE-ID;TZID=Europe/Berlin:20261126T093000' in listing
              and 'Bring card' in listing, listing[:300])
        standups = [e for e in doc['events'] if e['title'].startswith('Standup')]
        check('repeats expand the same (10 - 1 deleted)', len(standups) == 9, len(standups))

        # Phone sync password
        st, setup = box.call('POST', '/api/dav/setup', {})
        password = setup.get('password', '')
        check('phone password made once in Settings', st == 200 and setup['enabled'] and password and setup['url'].endswith('/dav/'), setup)
        check('wrong password refused', phone(box, 'nope', 'PROPFIND', '/dav/', '', {'Depth': '0'})[0] == 401)
        st, h, body = phone(box, password, 'PROPFIND', '/dav/', '<d:propfind xmlns:d="DAV:"><d:prop><d:current-user-principal/></d:prop></d:propfind>', {'Depth': '0'})
        check('phone finds its account (principal under /dav/)', st == 207 and '<href>/dav/owner/</href>' in body, body[:300])
        st, h, body = phone(box, password, 'PROPFIND', '/dav/owner/', '', {'Depth': '1'})
        check('phone sees a calendar and an address book', st == 207 and '/dav/owner/calendar/' in body and '/dav/owner/contacts/' in body and 'addressbook' in body)
        st, h, body = phone(box, password, 'PROPFIND', '/dav/owner/', '', {'Depth': '0', 'Origin': 'https://evil.example'})
        check('web pages cannot use it (Origin refused)', st == 403)
        st, _, _ = phone(box, password, 'PROPFIND', '/dav/', '', {'Depth': '0', 'Host': 'evil.example'})
        check('unknown host refused', st == 403)

        # Phone adds, edits and deletes
        st, h, _ = phone(box, password, 'PUT', '/dav/owner/calendar/phone-1.ics', vevent('phone-1@iphone', 'Lunch with Ana', '20261127T123000', '20261127T133000'),
                         {'Content-Type': 'text/calendar'})
        check('phone adds an event', st == 201, st)
        titles, doc = box.titles()
        lunch = [e for e in doc['events'] if e['title'] == 'Lunch with Ana']
        check('Calendar shows the phone\'s event', len(lunch) == 1 and lunch[0]['start'] == '2026-11-27T12:30:00+01:00', lunch)
        st, h, body = phone(box, password, 'GET', '/dav/owner/calendar/' + 'a' * 24 + '.ics')
        etag = h.get('ETag') or h.get('Etag')
        edited = body.replace('SUMMARY:Dentist', 'SUMMARY:Dentist (moved)').replace('DTSTART;TZID=Europe/Berlin:20261124T090000', 'DTSTART;TZID=Europe/Berlin:20261124T140000').replace('DTEND;TZID=Europe/Berlin:20261124T100000', 'DTEND;TZID=Europe/Berlin:20261124T150000')
        st, _, _ = phone(box, password, 'PUT', '/dav/owner/calendar/' + 'a' * 24 + '.ics', edited, {'Content-Type': 'text/calendar', 'If-Match': etag})
        titles, doc = box.titles()
        moved = [e for e in doc['events'] if e['title'] == 'Dentist (moved)']
        check('phone edits a Calendar event; Calendar shows it', st in (201, 204) and moved and moved[0]['start'].startswith('2026-11-24T14:00')
              and moved[0]['location'] == 'Main St', (st, moved))
        multiget = ('<c:calendar-multiget xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop><d:getetag/><c:calendar-data/></d:prop>'
                    '<d:href>/dav/owner/calendar/phone-1.ics</d:href></c:calendar-multiget>')
        st, _, body = phone(box, password, 'REPORT', '/dav/owner/calendar/', multiget, {'Depth': '1', 'Content-Type': 'application/xml'})
        check('phone multiget (how iPhone fetches changes) works through the prefix', st == 207 and 'Lunch with Ana' in body, body[:300])
        st, _, _ = phone(box, password, 'DELETE', '/dav/owner/calendar/' + 'c' * 24 + '.ics')
        titles, doc = box.titles()
        check('phone deletes an event; it is gone in Calendar', st in (200, 204) and 'Holiday' not in titles, titles)

        # Calendar and agent changes land in Radicale
        st, made = box.call('POST', '/api/live/create', {'account': 'local', 'title': 'Made in Calendar', 'start': '2026-11-28T10:00'})
        st2, h, body = phone(box, password, 'GET', f"/dav/owner/calendar/{made.get('id')}.ics")
        check('an event made in Calendar reaches the phone', st == 200 and st2 == 200 and 'SUMMARY:Made in Calendar' in body, (st, made, st2))
        moved_id = moved[0]['live']['id'] if moved else ''
        st, _ = box.call('POST', '/api/live/update', {'account': 'local', 'id': moved_id, 'title': 'Dentist (Calendar)'})
        st2, h, body = phone(box, password, 'GET', '/dav/owner/calendar/' + 'a' * 24 + '.ics')
        check('a change in Calendar to a phone-edited event reaches the phone', st == 200 and 'SUMMARY:Dentist (Calendar)' in body, (st, body[:200]))
        err, out = box.tool('local_calendar_list', {'from': '2026-11-20', 'to': '2026-12-31'})
        check('agent tool lists the same events', not err and {'Lunch with Ana', 'Made in Calendar', 'Dentist (Calendar)'} <= {e['title'] for e in out['events']}, out)
        err, out = box.tool('local_calendar_create', {'title': 'Agent booked', 'start': '2026-11-29T08:00'})
        st2, h, body = phone(box, password, 'GET', f"/dav/owner/calendar/{out.get('id')}.ics")
        check('agent tool create lands in Radicale', not err and st2 == 200 and 'Agent booked' in body, (err, out, st2))
        agent_id = out.get('id')
        err, out = box.tool('local_calendar_delete', {'id': agent_id})
        st2, _, _ = phone(box, password, 'GET', f'/dav/owner/calendar/{agent_id}.ics')
        titles, _ = box.titles()
        check('agent tool delete removes it from Radicale too', not err and st2 == 404 and 'Agent booked' not in titles, (err, out, st2))
        ics = vevent('google-export-1@google.com', 'From Google export', '20261130T100000', '20261130T110000')
        st, out = box.call('POST', '/api/local/import', {'ics': ics})
        listing = ''.join((rad.stored() or {}).values())
        check('an .ics import (Google / Outlook export) lands in Radicale', st == 200 and out.get('added') == 1 and 'From Google export' in listing, (st, out))

        # Contacts' address book through its grant
        card = 'BEGIN:VCARD\r\nVERSION:3.0\r\nUID:c1\r\nFN:Ana Lima\r\nTEL:+351 900 000 000\r\nEND:VCARD\r\n'
        st, _, _ = box.raw('PUT', '/service/dav/c1.vcf', card, {'Content-Type': 'text/vcard', 'X-Wizard-Grant': 'contacts-grant'})
        check('Contacts stores a card with its grant', st == 201, st)
        st, _, body = phone(box, password, 'GET', '/dav/owner/contacts/c1.vcf')
        check('the phone sees that contact (same server)', st == 200 and 'FN:Ana Lima' in body)
        st, _, body = box.raw('REPORT', '/service/dav/', '<card:addressbook-query xmlns:d="DAV:" xmlns:card="urn:ietf:params:xml:ns:carddav"><d:prop><d:getetag/><card:address-data/></d:prop></card:addressbook-query>',
                              {'Depth': '1', 'X-Wizard-Grant': 'contacts-grant', 'Content-Type': 'application/xml'})
        check('Contacts lists its cards with plain names', st == 207 and '<href>/service/dav/c1.vcf</href>' in body and '/owner/' not in body, body[:300])
        check('no grant, no address book', box.raw('GET', '/service/dav/c1.vcf', None, {'X-Wizard-Grant': 'other'})[0] == 403)
        check('Contacts cannot reach the calendar', box.raw('GET', '/service/dav/..%2Fcalendar%2F' + 'a' * 24 + '.ics', None, {'X-Wizard-Grant': 'contacts-grant'})[0] == 400)
        check('Contacts cannot make collections', box.raw('MKCOL', '/service/dav/x', None, {'X-Wizard-Grant': 'contacts-grant'})[0] == 405)

        # Radicale down: Calendar keeps working, catches up later
        rad.stop()
        st, made2 = box.call('POST', '/api/live/create', {'account': 'local', 'title': 'Made while down', 'start': '2026-12-01T10:00'})
        titles, _ = box.titles()
        check('Radicale down: Calendar still saves and shows events', st == 200 and 'Made while down' in titles and 'Lunch with Ana' in titles, (st, titles))
        rad.start()
        box.titles()
        st, _, body = phone(box, password, 'GET', f"/dav/owner/calendar/{made2.get('id')}.ics")
        check('back up: the pending event is pushed', st == 200 and 'Made while down' in body, st)

        # Switch off: the old store, every event kept (phone's included)
        on_titles, _ = box.titles()
        (data / 'switches.json').write_text(json.dumps({'radicale': False}))
        off_titles, _ = box.titles()
        check('off again: the same events from the old store, nothing lost', off_titles == on_titles and 'Lunch with Ana' in off_titles, (on_titles, off_titles))
        check('off again: phones are shut out', phone(box, password, 'PROPFIND', '/dav/', '', {'Depth': '0'})[0] == 404)
        st, h, body = box.raw('GET', '/service/dav/c1.vcf', None, {'X-Wizard-Grant': 'contacts-grant'})
        check('off again: Contacts can still read its cards once (told it is off)', st == 200 and 'Ana Lima' in body and h.get('X-Wizard-Radicale') == 'off', (st, h))
        check('off again: Contacts cannot write', box.raw('PUT', '/service/dav/c2.vcf', card, {'Content-Type': 'text/vcard', 'X-Wizard-Grant': 'contacts-grant'})[0] == 404)
        st, made3 = box.call('POST', '/api/live/create', {'account': 'local', 'title': 'Made while off', 'start': '2026-12-02T10:00'})
        (data / 'switches.json').write_text(json.dumps({'radicale': True}))
        titles, _ = box.titles()
        st, _, body = phone(box, password, 'GET', f"/dav/owner/calendar/{made3.get('id')}.ics")
        check('on again: changes made while off are synced', 'Made while off' in titles and st == 200 and titles == sorted(set(on_titles) | {'Made while off'}), titles)
        # Radicale's data lost (e.g. its folder wiped): Calendar keeps every event and copies them across again.
        rad.stop()
        shutil.rmtree(folder / 'collections', ignore_errors=True)
        rad.start()
        wiped, _ = box.titles()
        st, _, body = phone(box, password, 'GET', f"/dav/owner/calendar/{made3.get('id')}.ics")
        ids_after = {e['uid'] for e in json.loads((data / 'local.json').read_text())['events']}
        check('Radicale reset: no event lost, all copied across again (same ids)', wiped == titles and st == 200 and made3.get('id') in ids_after, (wiped, st))
        rad.stop()
        shutil.rmtree(folder / 'collections', ignore_errors=True)
        rad.start()
        st, made4 = box.call('POST', '/api/live/create', {'account': 'local', 'title': 'First after reset', 'start': '2026-12-03T10:00'})
        st2, _, body = phone(box, password, 'GET', f"/dav/owner/calendar/{made4.get('id')}.ics")
        after_reset, _ = box.titles()
        check('Radicale reset, then a change first: saved, pushed, nothing lost', st == 200 and st2 == 200
              and after_reset == sorted(set(titles) | {'First after reset'}), (st, st2, after_reset))
        check('mobileconfig link works once', box.raw('GET', '/api/dav/profile.mobileconfig?token=' + setup['profile_token'])[0] == 200
              and box.raw('GET', '/api/dav/profile.mobileconfig?token=' + setup['profile_token'])[0] == 404)
    finally:
        box.stop()
        rad.stop()
        shutil.rmtree(tmp, ignore_errors=True)
    failed = [n for n, ok in checks if not ok]
    print(f'{len(checks) - len(failed)}/{len(checks)} passed')
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
