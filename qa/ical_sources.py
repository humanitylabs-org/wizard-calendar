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

observed_modes = []
dump_json = server.json.dump
def observe_mode(doc, handle):
    observed_modes.append(os.fstat(handle.fileno()).st_mode & 0o077)
    return dump_json(doc, handle)
server.json.dump = observe_mode
try:
    source = server.add_ical_source('Personal', URL, fetcher=lambda _url: FEED_ONE, now='2026-10-30T12:00:00Z')
finally:
    server.json.dump = dump_json
check('source added with redacted response', source['name'] == 'Personal' and 'url' not in source and 'opaque-feed-value' not in json.dumps(source))
check('temporary state file is private before its first write', observed_modes and observed_modes == [0])
check('state file and directory are private', (DATA / 'state.json').stat().st_mode & 0o077 == 0 and DATA.stat().st_mode & 0o077 == 0)
private = json.loads((DATA / 'state.json').read_text())
check('one atomic state file retains source and snapshot', private['sources'][0]['url'] == URL and private['snapshot']['events'][0]['title'] == 'First event')
public = server.ical_sources_public()
check('public source projection never exposes URL', 'opaque-feed-value' not in json.dumps(public) and 'url' not in json.dumps(public))
snapshot = server.read()
check('add fetches and commits visible events', [event['title'] for event in snapshot['events']] == ['First event'])
check('MCP/view projection identifies iCal source', server.view()['mode'] == 'ical' and server.view()['connected'][0]['name'] == 'Personal')

before = server.read()
result = server.sync_ical_sources(fetcher=lambda _url: (_ for _ in ()).throw(ValueError('synthetic provider failure')), now='2026-10-31T12:00:00Z')
after = server.read()
check('failed refresh retains last-good snapshot', before == after and result['failed'] == 1)
check('failure status is useful but secret-free', 'synthetic provider failure' in json.dumps(server.ical_sources_public()) and 'opaque-feed-value' not in json.dumps(server.ical_sources_public()))

result = server.sync_ical_sources(fetcher=lambda _url: FEED_TWO, now='2026-10-31T12:00:00Z')
check('successful refresh replaces only source events', result['synced'] == 1 and [event['title'] for event in server.read()['events']] == ['Updated event'])

before_snapshot = server.read()
before_sources = server.ical_sources_public()
replace = server.os.replace
server.os.replace = lambda _source, _target: (_ for _ in ()).throw(OSError('synthetic replacement failure'))
try:
    try:
        server.remove_ical_source(source['id'])
    except OSError:
        pass
    else:
        raise AssertionError('source removal ignored a storage failure')
finally:
    server.os.replace = replace
check('failed atomic replacement preserves the complete prior generation', server.read() == before_snapshot and server.ical_sources_public() == before_sources)
check('failed replacement leaves no temporary state file', not list(DATA.glob('.state.json.*')))

server.remove_ical_source(source['id'])
check('remove deletes source and its imported events', server.ical_sources_public() == [] and server.read()['events'] == [] and server.read()['calendars'] == [])
check('removed private URL is absent from atomic state', 'opaque-feed-value' not in (DATA / 'state.json').read_text())

with tempfile.TemporaryDirectory(prefix='calendar-legacy-snapshot-') as legacy_tmp:
    legacy_data = Path(legacy_tmp)
    legacy_snapshot = {
        'schemaVersion': 1,
        'timezone': 'UTC',
        'calendars': [{'id': 'legacy', 'name': 'Legacy'}],
        'events': [],
        'syncedAt': '2026-10-01T00:00:00Z',
    }
    (legacy_data / 'snapshot.json').write_text(json.dumps(legacy_snapshot))
    active_data = getattr(server, 'DATA')
    setattr(server, 'DATA', legacy_data)
    try:
        check('legacy snapshot is the pre-subscription migration baseline', server.read() == legacy_snapshot)
        server._commit_snapshot_and_sources(server.read(), {'schemaVersion': 1, 'sources': []})
        migrated = json.loads((legacy_data / 'state.json').read_text())
        check('first write folds the legacy snapshot into atomic state', migrated['snapshot'] == legacy_snapshot and migrated['sources'] == [])
    finally:
        setattr(server, 'DATA', active_data)

print(json.dumps({'ok': True, 'count': len(checks), 'checks': checks}, indent=2))
TEMP.cleanup()
