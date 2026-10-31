#!/usr/bin/env python3
"""Connected-calendar QA: fake Google and Microsoft source apps (synthetic, labelled) speaking wizard.mail-calendar/1,
and a real Calendar server process pointed at them. Nothing talks to Google, Microsoft or Composio.

python3 qa/live.py
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
results = []


def check(name, condition):
    assert condition, name
    results.append(name)


class Fake:
    def __init__(self, sid, email):
        self.sid, self.email, self.calls = sid, email, []
        self.events = [
            {'id': f'{sid}-1', 'calendar_id': 'primary', 'title': 'Standup', 'all_day': False,
             'start': {'date_time': '2026-11-02T09:00:00+07:00', 'time_zone': 'Asia/Bangkok'}, 'end': {'date_time': '2026-11-02T09:15:00+07:00', 'time_zone': 'Asia/Bangkok'},
             'attendees': [], 'is_organizer': True, 'my_response': 'organizer', 'link': 'https://calendar.example/1', 'recurring': True},
            {'id': f'{sid}-2', 'calendar_id': 'primary', 'title': 'Lunch <b>invite</b>', 'all_day': False,
             'start': {'date_time': '2026-11-03T12:00:00', 'time_zone': 'Asia/Bangkok'}, 'end': {'date_time': '2026-11-03T13:00:00', 'time_zone': 'Asia/Bangkok'},
             'attendees': [{'email': email, 'self': True, 'response': 'none'}, {'email': 'anna@example.com', 'name': 'Anna', 'organizer': True}],
             'is_organizer': False, 'my_response': 'none', 'link': 'javascript:alert(1)', 'online_meeting': {'url': 'https://meet.example/x'}},
            {'id': f'{sid}-3', 'calendar_id': 'primary', 'title': 'Trip', 'all_day': True, 'start': {'date': '2026-11-06'}, 'end': {'date': '2026-11-08'}},
        ]
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def reply(self, status, value):
                raw = json.dumps(value).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                assert not self.headers.get('Origin') and not self.headers.get('Cookie')
                self.reply(200, {'accounts': [{'email': fake.email, 'status': 'active', 'services': ['gmail' if sid == 'google' else 'mail', 'calendar'], 'via': 'composio'}]})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                tool = self.path.rsplit('/', 1)[1]
                fake.calls.append((tool, body, self.headers.get('X-Wizard-Agent')))
                if tool == 'calendar_list_events':
                    return self.reply(200, {'events': fake.events, 'next_page_token': None})
                if tool == 'calendar_create_event':
                    return self.reply(200, {'created': True, 'event': {'id': 'new-1'}})
                if tool in ('calendar_update_event', 'calendar_delete_event', 'calendar_respond'):
                    if body.get('id') == 'missing':
                        return self.reply(404, {'error': {'code': 'not_found', 'message': 'That event is gone.'}})
                    return self.reply(200, {'ok': True})
                self.reply(404, {'error': {'code': 'not_found', 'message': 'no'}})

        self.srv = ThreadingHTTPServer(('127.0.0.1', 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f'http://127.0.0.1:{self.srv.server_address[1]}'


def free_port():
    s = socket.socket(); s.bind(('127.0.0.1', 0)); port = s.getsockname()[1]; s.close(); return port


def main():
    g, m = Fake('google', 'me@gmail.com'), Fake('microsoft', 'me@outlook.com')
    port, data = free_port(), tempfile.mkdtemp()
    host = f'127.0.0.1:{port}'
    env = dict(os.environ, PORT=str(port), DATA_DIR=data, ICAL_SYNC_INTERVAL='0', CALENDAR_TIMEZONE='Asia/Bangkok',
               CALENDAR_SOURCES=f'google={g.base},microsoft={m.base}')
    proc = subprocess.Popen([sys.executable, str(ROOT / 'app/server.py')], env=env, cwd=ROOT / 'app')
    try:
        for _ in range(50):
            try:
                urllib.request.urlopen(f'http://{host}/healthz', timeout=1); break
            except OSError:
                time.sleep(.1)

        def req(path, body=None, headers=None):
            h = {'Content-Type': 'application/json', **(headers or {})}
            r = urllib.request.Request(f'http://{host}{path}', data=json.dumps(body).encode() if body is not None else None, headers=h)
            try:
                with urllib.request.urlopen(r, timeout=15) as response:
                    return response.status, json.loads(response.read())
            except urllib.error.HTTPError as exc:
                return exc.code, json.loads(exc.read())

        owner = {'Origin': f'http://{host}', 'Sec-Fetch-Site': 'same-origin', 'X-Wizard-Request': 'calendar'}
        status, health = req('/healthz')
        check('health reports 0.2.1', status == 200 and health['version'] == '0.2.1')
        status, live = req('/api/live')
        check('both sources connected', status == 200 and live['connected'] and len(live['sources']) == 2)
        status, view = req('/api/events?from=2026-10-12&to=2026-12-21')
        check('events load', status == 200, )
        cals = [c for c in view['calendars'] if c.get('live')]
        check('one live calendar per account', sorted(c['id'] for c in cals) == ['live:google:me@gmail.com', 'live:microsoft:me@outlook.com'])
        check('mode is live', view['mode'] == 'live' and view['liveRange'] == ['2026-10-12', '2026-12-21'])
        ev = {e['live']['id']: e for e in view['events'] if e['cal'] == 'live:google:me@gmail.com'}
        check('timed event keeps its offset', ev['google-1']['start'] == '2026-11-02T09:00:00+07:00' and not ev['google-1']['allDay'])
        check('local time gets the zone', ev['google-2']['start'] == '2026-11-03T12:00:00+07:00')
        check('all-day stays dates', ev['google-3']['allDay'] and ev['google-3']['start'] == '2026-11-06' and ev['google-3']['end'] == '2026-11-08')
        check('invite flags', ev['google-2']['live']['invited'] and ev['google-2']['live']['my_response'] == 'none' and ev['google-1']['live']['is_organizer'])
        check('unsafe link dropped, meeting kept', ev['google-2']['link'] == '' and ev['google-2']['meet'] == 'https://meet.example/x')
        check('guests are plain text', ev['google-2']['guests'] == 'Anna')
        listed = [c for c in g.calls if c[0] == 'calendar_list_events'][-1]
        check('asks the source for the window', listed[1]['time_min'] == '2026-10-12T00:00:00Z' and listed[1]['time_max'] == '2026-12-21T00:00:00Z' and listed[2] == 'wizard-calendar')
        status, _ = req('/api/events?from=2026-12-21&to=2026-10-12')
        check('bad range refused', status == 400)
        status, mcp = req('/mcp', {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': 'calendar_events'}})
        check('agent reads live events (read only)', 'Standup' in mcp['result']['content'][0]['text'])
        status, tools = req('/mcp', {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'})
        check('agent has no write tool', [t['name'] for t in tools['result']['tools']] == ['calendar_events'])

        body = {'account': 'live:microsoft:me@outlook.com', 'title': 'Dentist', 'start': '2026-11-05T10:00', 'end': '2026-11-05T11:00', 'time_zone': 'Asia/Bangkok', 'location': 'Soi 24'}
        for name, headers in (('no origin', {}), ('other origin', {**owner, 'Origin': 'https://evil.example'}), ('cross-site', {**owner, 'Sec-Fetch-Site': 'cross-site'}),
                              ('no app header', {k: v for k, v in owner.items() if k != 'X-Wizard-Request'})):
            status, value = req('/api/live/create', body, headers)
            check(f'write refused: {name}', status == 403)
        check('nothing written yet', not [c for c in m.calls if c[0] == 'calendar_create_event'])
        status, value = req('/api/live/create', body, owner)
        check('create goes to Microsoft', status == 200 and value['created'])
        sent = [c for c in m.calls if c[0] == 'calendar_create_event'][-1][1]
        check('create arguments', sent == {'account': 'me@outlook.com', 'title': 'Dentist', 'start': '2026-11-05T10:00', 'end': '2026-11-05T11:00', 'location': 'Soi 24', 'time_zone': 'Asia/Bangkok'})
        for bad in ({**body, 'title': ' '}, {**body, 'end': '2026-11-05'}, {**body, 'end': '2026-11-04T10:00'}, {**body, 'account': 'live:yahoo:me@yahoo.com'},
                    {**body, 'start': 'tomorrow'}, {**body, 'attendees': ['nope']}):
            status, value = req('/api/live/create', bad, owner)
            check(f'invalid create refused: {value.get("code")}', status == 400)
        target = {'account': 'live:google:me@gmail.com', 'calendar_id': 'primary', 'id': 'google-1'}
        status, value = req('/api/live/update', {**target, 'title': 'Standup (moved)', 'start': '2026-11-02T09:30', 'end': '2026-11-02T09:45', 'time_zone': 'Asia/Bangkok'}, owner)
        check('update', status == 200 and [c for c in g.calls if c[0] == 'calendar_update_event'][-1][1]['title'] == 'Standup (moved)')
        status, value = req('/api/live/update', target, owner)
        check('empty update refused', status == 400)
        status, value = req('/api/live/respond', {**target, 'id': 'google-2', 'response': 'accepted'}, owner)
        check('answer an invite', status == 200 and [c for c in g.calls if c[0] == 'calendar_respond'][-1][1]['response'] == 'accepted')
        status, value = req('/api/live/respond', {**target, 'response': 'maybe'}, owner)
        check('bad answer refused', status == 400)
        status, value = req('/api/live/delete', {**target, 'id': 'missing'}, owner)
        check('source errors pass through', status == 404 and value['error'] == 'That event is gone.')
        status, value = req('/api/live/delete', target, owner)
        check('delete', status == 200 and value['deleted'])

        g.srv.shutdown(); g.srv.server_close()
        status, view = req('/api/events?from=2026-10-13&to=2026-12-21')
        check('one source down: the other still shows', status == 200 and [c['id'] for c in view['calendars'] if c.get('live')] == ['live:microsoft:me@outlook.com'])
        status, live = req('/api/live')
        check('down source reported', not [s for s in live['sources'] if s['id'] == 'google'][0]['available'])
        status, page = 200, urllib.request.urlopen(f'http://{host}/connect.js').read().decode()
        check('connect sheet served', 'WizardConnect' in page)
    finally:
        proc.terminate(); proc.wait(5)
    print(json.dumps({'ok': True, 'checks': len(results)}))


if __name__ == '__main__':
    main()
