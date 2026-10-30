#!/usr/bin/env python3
"""HTTP acceptance for redacted Google iCal source CRUD and sync."""
from __future__ import annotations

import datetime as dt
import http.client
import importlib.util
import json
import os
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'app'
sys.path.insert(0, str(APP))

with tempfile.TemporaryDirectory(prefix='calendar-http-ical-') as tmp:
    os.environ.update(DATA_DIR=tmp, CALENDAR_TIMEZONE='UTC', ICAL_SYNC_INTERVAL='0')
    spec = importlib.util.spec_from_file_location('calendar_http_server', APP / 'server.py')
    assert spec is not None and spec.loader is not None
    server = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = server
    spec.loader.exec_module(server)

    tomorrow = dt.datetime.now(dt.timezone.utc).date() + dt.timedelta(days=1)
    after = tomorrow + dt.timedelta(days=1)

    def feed(title):
        return f'''BEGIN:VCALENDAR\r
VERSION:2.0\r
PRODID:-//Wizard QA//EN\r
BEGIN:VEVENT\r
UID:http-acceptance\r
DTSTART;VALUE=DATE:{tomorrow:%Y%m%d}\r
DTEND;VALUE=DATE:{after:%Y%m%d}\r
SUMMARY:{title}\r
END:VEVENT\r
END:VCALENDAR\r
'''.encode()

    current = {'payload': feed('First title')}
    server.ical_feed.fetch_google_ical = lambda _url: current['payload']
    httpd = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
    port = httpd.server_address[1]
    host = f'127.0.0.1:{port}'
    setattr(server, 'HOSTS', {host})
    setattr(server, 'ORIGINS', {f'http://{host}'})
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    def request(method, path, body=None):
        connection = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
        payload = json.dumps(body).encode() if body is not None else None
        headers = {'Host': host}
        if payload is not None:
            headers['Content-Type'] = 'application/json'
            headers['Content-Length'] = str(len(payload))
        connection.request(method, path, body=payload, headers=headers)
        response = connection.getresponse()
        raw = response.read()
        connection.close()
        return response.status, json.loads(raw)

    checks = []
    try:
        private_url = 'webcal://calendar.google.com/calendar/ical/opaque-id%40group.calendar.google.com/opaque-value/basic.ics'
        status, added = request('POST', '/api/sources', {'name': 'Personal', 'url': private_url})
        assert status == 200 and added['ok'] is True
        source_id = added['source']['id']
        assert 'url' not in added['source'] and 'opaque-id' not in json.dumps(added)
        checks.append('POST adds and redacts source')

        status, sources = request('GET', '/api/sources')
        assert status == 200 and len(sources['sources']) == 1
        assert 'url' not in sources['sources'][0] and 'opaque-id' not in json.dumps(sources)
        checks.append('GET sources stays redacted')

        status, events = request('GET', '/api/events')
        assert status == 200 and events['events'][0]['title'] == 'First title'
        assert events['mode'] == 'ical' and len(events['connected']) == 1
        checks.append('event projection identifies iCal mode')

        current['payload'] = feed('Updated title')
        status, synced = request('POST', '/api/sync', {})
        assert status == 200 and synced['synced'] == 1 and synced['failed'] == 0
        status, events = request('GET', '/api/events')
        assert events['events'][0]['title'] == 'Updated title'
        checks.append('manual sync replaces source events')

        status, removed = request('POST', '/api/sources/remove', {'id': source_id})
        assert status == 200 and removed == {'ok': True, 'id': source_id}
        status, events = request('GET', '/api/events')
        assert events['events'] == [] and events['connected'] == []
        checks.append('remove deletes source and its events')

        print(json.dumps({'ok': True, 'count': len(checks), 'checks': checks}, indent=2))
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
