#!/usr/bin/env python3
"""The calendar on this Wizard (issue 58, switch local-calendar): no account, create / edit / move / delete with
repeats, .ics import and export, agent tools gated by the owner's level, and survival across backup and restore.

python3 qa/local_calendar.py
"""
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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
checks = []


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


class Box:
    """A scratch Calendar: fresh install, no account (CALENDAR_LIVE=off, no Connected accounts)."""

    def __init__(self, data, grants=None):
        self.port = free_port()
        self.base = f'http://127.0.0.1:{self.port}'
        env = dict(os.environ, DATA_DIR=str(data), PORT=str(self.port), CALENDAR_LIVE='off', CALENDAR_CONNECTED_ACCOUNTS='off',
                   CALENDAR_DEV_MODE='loopback-single-owner', CALENDAR_TIMEZONE='Europe/Berlin', ICAL_SYNC_INTERVAL='0',
                   WIZARD_GRANTS_FILE=str(grants or (Path(data) / 'no-grants.json')))
        self.proc = subprocess.Popen([sys.executable, str(ROOT / 'app' / 'server.py')], env=env, cwd=ROOT)
        for _ in range(100):
            try:
                urllib.request.urlopen(self.base + '/healthz', timeout=1).read()
                return
            except OSError:
                time.sleep(0.1)
        raise SystemExit('server did not start')

    def stop(self):
        self.proc.terminate()
        self.proc.wait(5)

    def call(self, method, path, body=None, owner=True, headers=None):
        h = {'Content-Type': 'application/json'}
        if owner:
            h.update({'X-Wizard-Request': 'calendar', 'Origin': self.base, 'Sec-Fetch-Site': 'same-origin'})
        h.update(headers or {})
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode() if body is not None else None, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                raw, status = r.read(), r.status
        except urllib.error.HTTPError as e:
            raw, status = e.read(), e.code
        try:
            return status, json.loads(raw)
        except ValueError:
            return status, raw.decode()

    def events(self, frm='2026-11-01', to='2026-12-31', owner=True):
        status, doc = self.call('GET', f'/api/events?from={frm}&to={to}', owner=owner)
        assert status == 200, (status, doc)
        return doc

    def tool(self, name, args=None, headers=None):
        status, out = self.call('POST', '/mcp', {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                                                  'params': {'name': name, 'arguments': args or {}}}, owner=False,
                                headers=dict({'X-Wizard-Agent': 'hermes'}, **(headers or {})))
        assert status == 200, (status, out)
        result = out['result']
        return result['isError'], json.loads(result['content'][0]['text'])

    def tools(self):
        return [t['name'] for t in self.call('POST', '/mcp', {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}, owner=False)[1]['result']['tools']]


data = Path(tempfile.mkdtemp(prefix='cal-local-'))
box = Box(data)
try:
    # ---- switched off: nothing changes ----
    doc = box.events()
    assert doc['calendars'] == [] and doc['events'] == [] and doc['localCalendar'] is None, doc
    assert box.tools() == ['calendar_events']
    status, out = box.call('POST', '/api/live/create', {'account': 'local', 'title': 'x', 'start': '2026-11-20'})
    assert status == 404 and out['code'] == 'switch_off', (status, out)
    checks.append('switch off: fresh install stays empty, no local tools, local writes refused')

    status, out = box.call('POST', '/api/switches', {'id': 'local-calendar', 'on': True}, headers={'X-Wizard-Switch': '1'})
    assert status == 200 and any(s['id'] == 'local-calendar' and s['on'] for s in out['switches']), out

    # ---- switched on: a local calendar with no account ----
    doc = box.events()
    assert [c['id'] for c in doc['calendars']] == ['local'] and doc['calendars'][0]['live'] and doc['events'] == []
    assert doc['localCalendar']['agentAccess'] == 'read_only'
    checks.append('switch on: a fresh install with no account has an empty writable calendar "On this Wizard"')

    # The owner's form (same route as Google/Microsoft events): a weekly event and an all-day one.
    status, out = box.call('POST', '/api/live/create', {'account': 'local', 'title': 'Swim', 'start': '2026-11-02T07:30', 'end': '2026-11-02T08:15',
                                                         'time_zone': 'Europe/Berlin', 'location': 'Pool', 'description': 'Bring towel', 'repeat': 'weekly'})
    assert status == 200 and out['created'], out
    status, out = box.call('POST', '/api/live/create', {'account': 'local', 'title': 'Holiday', 'start': '2026-11-12', 'end': '2026-11-14'})
    assert status == 200, out
    swims = [e for e in box.events()['events'] if e['title'] == 'Swim']
    assert [e['start'] for e in swims[:3]] == ['2026-11-02T07:30:00+01:00', '2026-11-09T07:30:00+01:00', '2026-11-16T07:30:00+01:00'], swims
    assert all(e['live']['recurring'] and e['live']['repeat'] == 'weekly' and e['location'] == 'Pool' for e in swims)
    assert len(swims) == 9, len(swims)
    hol = [e for e in box.events()['events'] if e['title'] == 'Holiday']
    assert len(hol) == 1 and hol[0]['allDay'] and hol[0]['end'] == '2026-11-14'
    checks.append('owner adds a weekly timed event (title, time, place, notes) and an all-day event; the repeat shows every week')

    # Move one repeat (drag "This event"), delete another, then move every repeat to another day (drag "All events").
    second, third = swims[1], swims[2]
    status, out = box.call('POST', '/api/live/update', {'account': 'local', 'calendar_id': 'local', 'id': second['live']['id'],
                                                         'start': '2026-11-10T18:00', 'end': '2026-11-10T19:00', 'time_zone': 'Europe/Berlin'})
    assert status == 200 and out['scope'] == 'one', out
    status, out = box.call('POST', '/api/live/delete', {'account': 'local', 'calendar_id': 'local', 'id': third['live']['id']})
    assert status == 200 and out['scope'] == 'one', out
    swims = [e for e in box.events()['events'] if e['title'] == 'Swim']
    assert [e['start'][:16] for e in swims[:3]] == ['2026-11-02T07:30', '2026-11-10T18:00', '2026-11-23T07:30'], swims
    status, out = box.call('POST', '/api/live/update', {'account': 'local', 'calendar_id': 'local', 'id': swims[0]['live']['series_id'], 'scope': 'series',
                                                         'shift_start_minutes': 1440 + 60, 'shift_end_minutes': 1440 + 60})
    assert status == 200 and out['scope'] == 'series', out
    swims = [e for e in box.events()['events'] if e['title'] == 'Swim']
    assert [e['start'][:16] for e in swims[:3]] == ['2026-11-03T08:30', '2026-11-10T18:00', '2026-11-24T08:30'], swims
    checks.append('one repeat moves on its own, one is deleted on its own, then every repeat moves a day and an hour; the moved and deleted ones stay so')

    # Edit the whole series from one repeat (form "All events"): new title and time; then stop repeating.
    status, out = box.call('POST', '/api/live/update', {'account': 'local', 'calendar_id': 'local', 'id': swims[2]['live']['id'], 'scope': 'series',
                                                         'title': 'Swim club', 'start': '2026-11-24T09:00', 'end': '2026-11-24T10:00', 'time_zone': 'Europe/Berlin'})
    assert status == 200, out
    swims = [e for e in box.events()['events'] if e['title'].startswith('Swim')]
    assert swims[0]['title'] == 'Swim club' and swims[0]['start'][:16] == '2026-11-03T09:00' and swims[0]['end'][:16] == '2026-11-03T10:00', swims[0]
    status, out = box.call('POST', '/api/live/update', {'account': 'local', 'calendar_id': 'local', 'id': swims[0]['live']['id'], 'scope': 'series', 'repeat': 'none'})
    assert status == 200, out
    swims = [e for e in box.events()['events'] if e['title'].startswith('Swim')]
    assert len(swims) == 1 and not swims[0]['live']['recurring'], swims
    status, out = box.call('POST', '/api/live/delete', {'account': 'local', 'calendar_id': 'local', 'id': swims[0]['live']['id']})
    assert status == 200 and not [e for e in box.events()['events'] if e['title'].startswith('Swim')]
    checks.append('editing "every repeat" from one repeat moves the series by the same amount; Repeat: none and Delete work')

    # Not the owner: no changes.
    status, out = box.call('POST', '/api/live/create', {'account': 'local', 'title': 'x', 'start': '2026-11-20'}, owner=False)
    assert status == 403, (status, out)
    status, out = box.call('POST', '/api/local/agent-access', {'level': 'can_edit'}, owner=False)
    assert status == 403, (status, out)
    checks.append('changes and the agent level need the owner\'s own Calendar page')

    # ---- .ics import and export ----
    ics = '\r\n'.join([
        'BEGIN:VCALENDAR', 'VERSION:2.0',
        'BEGIN:VEVENT', 'UID:standup@example.com', 'DTSTART;TZID=Europe/Berlin:20261102T093000', 'DTEND;TZID=Europe/Berlin:20261102T094500',
        'RRULE:FREQ=WEEKLY;BYDAY=MO,WE', 'EXDATE;TZID=Europe/Berlin:20261104T093000', 'SUMMARY:Stand-up\\, team', 'LOCATION:Room 1', 'END:VEVENT',
        'BEGIN:VEVENT', 'UID:standup@example.com', 'RECURRENCE-ID;TZID=Europe/Berlin:20261109T093000', 'DTSTART;TZID=Europe/Berlin:20261109T110000',
        'DTEND;TZID=Europe/Berlin:20261109T111500', 'SUMMARY:Stand-up (late)', 'END:VEVENT',
        'BEGIN:VEVENT', 'UID:dentist@example.com', 'DTSTART:20261118T130000Z', 'DTEND:20261118T140000Z', 'SUMMARY:Dentist', 'END:VEVENT',
        'END:VCALENDAR', ''])
    status, out = box.call('POST', '/api/local/import', {'ics': ics})
    assert status == 200 and out['added'] == 2, out
    ev = box.events()['events']
    stand = [e for e in ev if e['title'].startswith('Stand-up')]
    assert [e['start'][:16] for e in stand[:3]] == ['2026-11-02T09:30', '2026-11-09T11:00', '2026-11-11T09:30'], stand[:3]
    assert stand[0]['title'] == 'Stand-up, team' and stand[1]['title'] == 'Stand-up (late)' and stand[0]['live']['repeat'] == 'custom'
    assert [e['start'] for e in ev if e['title'] == 'Dentist'] == ['2026-11-18T13:00:00+00:00']
    status, out = box.call('POST', '/api/local/import', {'ics': ics})
    assert status == 200 and out['added'] == 0 and out['updated'] == 2, out
    assert len([e for e in box.events()['events'] if e['title'].startswith('Stand-up')]) == len(stand)
    status, out = box.call('POST', '/api/local/import', {'ics': 'BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nEND:VCALENDAR'})
    assert status == 400 and 'Google' not in out['error'], out
    checks.append('.ics import: a weekly Mon/Wed rule with an exception and a moved repeat, a UTC event; importing again updates, never duplicates; a broken file is refused')

    status, text = box.call('GET', '/api/local/export.ics')
    assert status == 200 and text.startswith('BEGIN:VCALENDAR') and 'RRULE:FREQ=WEEKLY;BYDAY=MO,WE' in text and 'SUMMARY:Stand-up\\, team' in text, text
    assert 'RECURRENCE-ID;TZID=Europe/Berlin:20261109T093000' in text and 'UID:standup@example.com' in text
    assert box.call('GET', '/api/local/export.ics', owner=False)[0] == 403
    data2 = Path(tempfile.mkdtemp(prefix='cal-local-2-'))
    (data2 / 'switches.json').write_text(json.dumps({'local-calendar': True}))
    other = Box(data2)
    try:
        status, out = other.call('POST', '/api/local/import', {'ics': text})
        assert status == 200 and out['added'] == 3, out
        strip = lambda doc: [(e['title'], e['start'], e['end'], e['allDay']) for e in doc['events']]
        assert strip(other.events()) == strip(box.events()), (strip(other.events()), strip(box.events()))
    finally:
        other.stop()
    checks.append('.ics export (owner only) imports into another Wizard as the very same events')

    # ---- agents ----
    assert set(box.tools()) == {'calendar_events', 'local_calendar_list', 'local_calendar_create', 'local_calendar_update', 'local_calendar_delete'}
    err, out = box.tool('local_calendar_list', {'from': '2026-11-01', 'to': '2026-11-30'})
    assert not err and any(e['title'] == 'Dentist' for e in out['events']), out
    err, out = box.tool('local_calendar_create', {'title': 'Agent call', 'start': '2026-11-20T15:00'})
    assert err and out['error']['code'] == 'agent_access_denied' and 'Read-only' in out['error']['message'], out
    checks.append('agent at Read-only (the default): lists local events, cannot create')

    status, out = box.call('POST', '/api/local/agent-access', {'level': 'can_edit'})
    assert status == 200 and out['level'] == 'can_edit', out
    err, out = box.tool('local_calendar_create', {'title': 'Piano lesson', 'start': '2026-11-05T17:00', 'end': '2026-11-05T18:00', 'repeat': 'weekly',
                                                 'repeat_until': '2026-11-26', 'location': 'Music school'})
    assert not err and out['created'], out
    piano = [e for e in box.events()['events'] if e['title'] == 'Piano lesson']
    assert [e['start'][:10] for e in piano] == ['2026-11-05', '2026-11-12', '2026-11-19', '2026-11-26'] and all(e['live']['by_agent'] for e in piano), piano
    err, out = box.tool('local_calendar_update', {'id': piano[1]['live']['id'], 'title': 'Piano (recital)'})
    assert not err and out['scope'] == 'one', out
    err, out = box.tool('local_calendar_delete', {'id': piano[3]['live']['id']})
    assert not err, out
    assert [e['title'] for e in box.events()['events'] if e['title'].startswith('Piano')] == ['Piano lesson', 'Piano (recital)', 'Piano lesson']
    err, out = box.tool('calendar_events')
    assert not err and any(e['title'] == 'Piano (recital)' for e in out['events']), out
    checks.append('agent at Can edit: creates a repeating event (shown "by your agent"), changes one repeat, deletes one; calendar_events includes them')

    status, out = box.call('POST', '/api/local/agent-access', {'level': 'no_access'})
    assert status == 200
    err, out = box.tool('local_calendar_list')
    assert err and out['error']['code'] == 'agent_access_denied', out
    err, out = box.tool('calendar_events')
    assert not err and not any(e['cal'] == 'local' for e in out['events']), out
    assert any(e['cal'] == 'local' for e in box.events()['events'])
    status, out = box.call('POST', '/api/local/agent-access', {'level': 'can_edit'})
    checks.append('agent at No access: sees nothing of this calendar (the owner still does)')
finally:
    box.stop()

# A box that enforces grants (wizard-os PERMISSIONS layer 2): writes need the gateway's grant.
grants = data / 'grants.json'
key = 'ab' * 32
import hashlib  # noqa: E402
grants.write_text(json.dumps({'incoming': [{'from': 'host:agent-service', 'sha256': hashlib.sha256(key.encode()).hexdigest()}], 'enforce': True}))
box = Box(data, grants)
try:
    err, out = box.tool('local_calendar_create', {'title': 'No grant', 'start': '2026-11-21'})
    assert err and out['error']['code'] == 'grant_required', out
    err, out = box.tool('local_calendar_create', {'title': 'Through the gateway', 'start': '2026-11-21'}, headers={'X-Wizard-Grant': key})
    assert not err, out
    checks.append('with enforce on, an agent write without the gateway\'s grant is refused; with it, it works')
    before = [(e['title'], e['start']) for e in box.events()['events']]
finally:
    box.stop()

# ---- backup and restore: the app data folder is the backup ----
backup = Path(tempfile.mkdtemp(prefix='cal-local-backup-')) / 'data'
shutil.copytree(data, backup)
shutil.rmtree(data)
restored = Path(tempfile.mkdtemp(prefix='cal-local-restored-')) / 'data'
shutil.copytree(backup, restored)
box = Box(restored)
try:
    after = [(e['title'], e['start']) for e in box.events()['events']]
    assert after == before and any(t == 'Piano lesson' for t, _ in after) and any(t == 'Holiday' for t, _ in after), after
    assert box.events()['localCalendar']['agentAccess'] == 'can_edit'
    checks.append('backup and restore: the owner\'s and the agent\'s repeating events and the agent level come back')
finally:
    box.stop()

print(json.dumps({'ok': True, 'count': len(checks), 'checks': checks}, indent=2))
