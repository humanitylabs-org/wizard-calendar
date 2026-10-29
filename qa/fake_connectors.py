#!/usr/bin/env python3
"""Synthetic Connected accounts contract server. Never contacts Google."""
import datetime as dt
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

KEY = 'synthetic-calendar-grant'
MODE = 'ok'
CALLS = []
ACCOUNTS = [{'account': a, 'email': a + '@example.invalid', 'calendar_allowed': True, 'status': 'ok'} for a in ('alpha', 'beta')]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass

    def send(self, value, status=200):
        raw = json.dumps(value).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self): self.handle_request()
    def do_POST(self): self.handle_request()

    def handle_request(self):
        global MODE
        if self.path == '/__qa/calls': return self.send(CALLS)
        if self.path == '/__qa/mode':
            MODE = json.loads(self.rfile.read(int(self.headers['Content-Length'])))['mode']
            return self.send({'mode': MODE})
        valid = self.headers.get('X-Wizard-Grant') == KEY
        CALLS.append({'path': self.path, 'grant_valid': valid})
        if not valid: return self.send({'error': 'grant_denied'}, 403)
        if MODE == 'configuration_error': return self.send({'error': 'google_configuration_required'}, 503)
        if self.path.endswith('/status'):
            accounts = [] if MODE == 'no_accounts' else [dict(a, calendar_allowed=MODE != 'denied') for a in ACCOUNTS]
            return self.send({'client_configured': MODE != 'no_client', 'accounts': accounts, 'setup_url': '/wizard-connectors/'})
        if self.path.endswith('/calendars'):
            return self.send({'calendars': [{'account': a['account'], 'email': a['email'], 'id': 'primary', 'name': a['account'].title(), 'color': '#398abc' if MODE != 'recolor' else '#abcdef', 'primary': True, 'access_role': 'owner'} for a in ACCOUNTS]})
        if self.path.endswith('/events'):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            if MODE == 'partial' and body['account'] == 'beta': return self.send({'error': 'temporary'}, 500)
            a, cid = body['account'], body['calendar_id']
            start = dt.datetime.fromisoformat(body['time_min'])
            end = dt.datetime.fromisoformat(body['time_max'])
            assert dt.timedelta(days=219) <= end-start <= dt.timedelta(days=241)
            CALLS[-1].update(time_min=body['time_min'], time_max=body['time_max'])
            day = dt.datetime.now(dt.timezone.utc).date().isoformat()
            def event(eid, title):
                return {'id': eid, 'calendar_id': cid, 'account': a, 'title': title, 'start': day+'T10:00:00Z', 'end': day+'T11:00:00Z', 'all_day': False, 'location': 'Synthetic', 'status': 'confirmed', 'html_link': 'https://calendar.google.com/', 'description':'Synthetic notes', 'meet':'https://meet.google.com/qa-fixture', 'attendee_count':2, 'ical_uid':('shared' if eid=='shared' else a+'-'+eid)+'@example.invalid', 'self_response':'accepted'}
            rows = [event('shared', 'Shared meeting'), event('own', a + (' refreshed' if MODE == 'partial' else ' meeting'))]
            if MODE == 'invalid': rows[0]['end'] = 'not-a-date'
            if MODE == 'unsafe': rows[0]['html_link'] = 'javascript:alert(1)'
            if MODE == 'declined': rows[0]['self_response'] = 'declined'
            return self.send({'events': rows, 'truncated': MODE == 'truncated'})
        self.send({'error': 'not_found'}, 404)


if __name__ == '__main__':
    ThreadingHTTPServer(('0.0.0.0', int(os.environ.get('PORT', '8800'))), Handler).serve_forever()
