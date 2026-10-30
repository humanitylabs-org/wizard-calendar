#!/usr/bin/env python3
"""Source persistence, redaction, refresh and removal tests with a synthetic feed."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
TEMP = tempfile.TemporaryDirectory(prefix='calendar-ical-source-')
DATA = Path(TEMP.name)
os.environ.update(DATA_DIR=str(DATA), ICAL_SYNC_INTERVAL='0', CALENDAR_TIMEZONE='UTC')
sys.path.insert(0, str(ROOT / 'app'))
SPEC = importlib.util.spec_from_file_location('calendar_server_ical_test', ROOT / 'app/server.py')
assert SPEC is not None and SPEC.loader is not None
server = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = server
SPEC.loader.exec_module(server)

URL = 'https://calendar.google.com/calendar/ical/person%40example.com/opaque-feed-value/basic.ics'
FEED_ONE = b'''BEGIN:VCALENDAR\r
BEGIN:VEVENT\r
UID:one\r
DTSTART:20261030T120000Z\r
DTEND:20261030T130000Z\r
SUMMARY:First event\r
END:VEVENT\r
END:VCALENDAR\r
'''
FEED_TWO = b'''BEGIN:VCALENDAR\r
BEGIN:VEVENT\r
UID:two\r
DTSTART:20261101T120000Z\r
DTEND:20261101T130000Z\r
SUMMARY:Updated event\r
END:VEVENT\r
END:VCALENDAR\r
'''
checks = []

def check(name, condition):
    assert condition, name
    checks.append(name)

source = server.add_ical_source('Personal', URL, fetcher=lambda _url: FEED_ONE, now='2026-10-30T12:00:00Z')
check('source added with redacted response', source['name'] == 'Personal' and 'url' not in source and 'opaque-feed-value' not in json.dumps(source))
check('source file private', (DATA / 'sources.json').stat().st_mode & 0o077 == 0)
private = json.loads((DATA / 'sources.json').read_text())
check('private source retains normalized subscription URL', private['sources'][0]['url'] == URL)
public = server.ical_sources_public()
check('public source projection never exposes URL', 'opaque-feed-value' not in json.dumps(public) and 'url' not in json.dumps(public))
snapshot = server.read()
check('add fetches and commits visible events', [event['title'] for event in snapshot['events']] == ['First event'])
check('MCP/view projection identifies iCal source', server.view()['mode'] == 'ical' and server.view()['connected'][0]['name'] == 'Personal')

before = json.loads((DATA / 'snapshot.json').read_text())
result = server.sync_ical_sources(fetcher=lambda _url: (_ for _ in ()).throw(ValueError('synthetic provider failure')), now='2026-10-31T12:00:00Z')
after = json.loads((DATA / 'snapshot.json').read_text())
check('failed refresh retains last-good snapshot', before == after and result['failed'] == 1)
check('failure status is useful but secret-free', 'synthetic provider failure' in json.dumps(server.ical_sources_public()) and 'opaque-feed-value' not in json.dumps(server.ical_sources_public()))

result = server.sync_ical_sources(fetcher=lambda _url: FEED_TWO, now='2026-10-31T12:00:00Z')
check('successful refresh replaces only source events', result['synced'] == 1 and [event['title'] for event in server.read()['events']] == ['Updated event'])

before_snapshot = server.read()
before_sources = server.ical_sources_public()
save_sources = getattr(server, '_save_sources')
setattr(server, '_save_sources', lambda _doc: (_ for _ in ()).throw(OSError('synthetic storage failure')))
try:
    try:
        server.remove_ical_source(source['id'])
    except OSError:
        pass
    else:
        raise AssertionError('source removal ignored a storage failure')
finally:
    setattr(server, '_save_sources', save_sources)
check('two-file mutation rolls back snapshot on source-write failure', server.read() == before_snapshot and server.ical_sources_public() == before_sources)

server.remove_ical_source(source['id'])
check('remove deletes source and its imported events', server.ical_sources_public() == [] and server.read()['events'] == [] and server.read()['calendars'] == [])
check('removed private URL is absent from source file', 'opaque-feed-value' not in (DATA / 'sources.json').read_text())

print(json.dumps({'ok': True, 'count': len(checks), 'checks': checks}, indent=2))
TEMP.cleanup()
