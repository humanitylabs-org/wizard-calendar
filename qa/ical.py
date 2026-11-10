#!/usr/bin/env python3
"""Focused Google iCal parsing and URL-boundary tests."""
from __future__ import annotations
import importlib.util
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('ical_feed', ROOT / 'app/ical_feed.py')
assert SPEC is not None and SPEC.loader is not None
ical = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ical
SPEC.loader.exec_module(ical)

checks = []

def check(name, condition):
    assert condition, name
    checks.append(name)

raw = 'webcal://calendar.google.com/calendar/ical/person%40example.com/opaque-value/basic.ics'
normalized = ical.normalize_google_ical_url(raw)
check('webcal normalizes to HTTPS', normalized == 'https://calendar.google.com/calendar/ical/person%40example.com/opaque-value/basic.ics')
for bad in [
    'http://calendar.google.com/calendar/ical/a/opaque-value/basic.ics',
    'https://example.com/calendar/ical/a/opaque-value/basic.ics',
    'https://calendar.google.com.evil.invalid/calendar/ical/a/opaque-value/basic.ics',
    'https://calendar.google.com:444/calendar/ical/a/opaque-value/basic.ics',
    'https://user:pass@calendar.google.com/calendar/ical/a/opaque-value/basic.ics',
    'https://calendar.google.com/calendar/ical/a/opaque-value/basic.ics?next=http://127.0.0.1',
    'https://calendar.google.com/other/basic.ics',
]:
    try:
        ical.normalize_google_ical_url(bad)
    except ValueError:
        pass
    else:
        raise AssertionError('accepted unsafe URL: ' + bad)
checks.append('non-Google and ambiguous URLs rejected')

try:
    ical.normalize_google_ical_url('https://calendar.google.com:notaport/calendar/ical/a/value/basic.ics')
except ValueError as exc:
    check('malformed ports fail with a generic URL error', str(exc) == 'Use a Google Calendar iCal link ending in /basic.ics')
else:
    raise AssertionError('accepted a malformed port')

try:
    ical._NoRedirect().redirect_request(urllib.request.Request(normalized), None, 302, 'Found', {}, normalized)
except urllib.error.HTTPError:
    checks.append('feed redirects are refused before forwarding the bearer URL')
else:
    raise AssertionError('Google iCal redirects were followed')

class FakeResponse:
    def __enter__(self):
        return self
    def __exit__(self, *_args):
        return False
    def read(self, _limit):
        return b'BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n'

class FakeOpener:
    def open(self, request, timeout):
        assert request.full_url == normalized and timeout == 15
        return FakeResponse()

handlers = []
build_opener = ical.urllib.request.build_opener
prior_proxy = os.environ.get('HTTPS_PROXY')
os.environ['HTTPS_PROXY'] = 'http://127.0.0.1:9'
try:
    ical.urllib.request.build_opener = lambda *items: (handlers.extend(items), FakeOpener())[1]
    check('private feed fetch disables inherited proxies', ical.fetch_google_ical(normalized).startswith(b'BEGIN:VCALENDAR'))
    check('empty proxy handler is installed explicitly', isinstance(handlers[0], urllib.request.ProxyHandler) and getattr(handlers[0], 'proxies', None) == {})
finally:
    ical.urllib.request.build_opener = build_opener
    if prior_proxy is None:
        os.environ.pop('HTTPS_PROXY', None)
    else:
        os.environ['HTTPS_PROXY'] = prior_proxy

feed = b'''BEGIN:VCALENDAR\r
VERSION:2.0\r
PRODID:-//Fixture//EN\r
X-WR-CALNAME:Fixture Calendar\r
BEGIN:VEVENT\r
UID:one@example\r
DTSTAMP:20261001T120000Z\r
DTSTART;TZID=America/Vancouver:20261030T090000\r
DTEND;TZID=America/Vancouver:20261030T100000\r
SUMMARY:Planning\\, weekly\r
LOCATION:Home\r
DESCRIPTION:Line one\\nLine two that is folded across a very long source\r
 line\r
URL:https://calendar.google.com/calendar/event?eid=abc\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:weekly@example\r
DTSTAMP:20261001T120000Z\r
DTSTART:20261026T170000Z\r
DTEND:20261026T180000Z\r
RRULE:FREQ=WEEKLY;COUNT=4;BYDAY=MO\r
EXDATE:20261102T170000Z\r
SUMMARY:Weekly class\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:weekly@example\r
RECURRENCE-ID:20261109T170000Z\r
DTSTART:20261109T190000Z\r
DTEND:20261109T200000Z\r
SUMMARY:Weekly class moved\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:first-monday@example\r
DTSTART;VALUE=DATE:20261005\r
DTEND;VALUE=DATE:20261006\r
RRULE:FREQ=MONTHLY;COUNT=3;BYDAY=1MO\r
SUMMARY:First Monday\r
END:VEVENT\r
END:VCALENDAR\r
'''
parsed = ical.parse_ical(
    feed,
    calendar_id='ical:fixture',
    calendar_name='Personal',
    timezone='America/Vancouver',
    now='2026-10-30T12:00:00Z',
    past_days=60,
    future_days=400,
)
check('calendar identity preserved', parsed['calendars'] == [{'id': 'ical:fixture', 'name': 'Personal'}])
check('timed, weekly and monthly recurrences expanded', len(parsed['events']) == 7)
by_title = {}
for event in parsed['events']:
    by_title.setdefault(event['title'], []).append(event)
check('escaped and folded text decoded', by_title['Planning, weekly'][0]['description'] == 'Line one\nLine two that is folded across a very long sourceline')
check('TZID converted with offset', by_title['Planning, weekly'][0]['start'] == '2026-10-30T09:00:00-07:00')
check('EXDATE removes one recurring instance', len(by_title['Weekly class']) == 2)
check('RECURRENCE-ID override replaces the original occurrence', by_title['Weekly class moved'][0]['start'] == '2026-11-09T19:00:00+00:00')
check('monthly ordinal BYDAY expands', [e['start'] for e in by_title['First Monday']] == ['2026-10-05', '2026-11-02', '2026-12-07'])
check('stable unique event ids', len({e['id'] for e in parsed['events']}) == len(parsed['events']))

unsupported = b'''BEGIN:VCALENDAR\r
BEGIN:VEVENT\r
UID:x\r
DTSTART:20261030T120000Z\r
DTEND:20261030T130000Z\r
RRULE:FREQ=HOURLY\r
SUMMARY:Unsupported\r
END:VEVENT\r
END:VCALENDAR\r
'''
try:
    ical.parse_ical(unsupported, calendar_id='ical:x', calendar_name='X', timezone='UTC', now='2026-10-30T12:00:00Z')
except ValueError as exc:
    check('unsupported recurrence fails closed', 'unsupported RRULE' in str(exc))
else:
    raise AssertionError('unsupported recurrence was silently accepted')

malformed_interval = b'''BEGIN:VCALENDAR\r
BEGIN:VEVENT\r
UID:bad-interval\r
DTSTART;VALUE=DATE:20261030\r
DTEND;VALUE=DATE:20261031\r
RRULE:FREQ=DAILY;INTERVAL=\r
SUMMARY:Malformed interval\r
END:VEVENT\r
END:VCALENDAR\r
'''
try:
    ical.parse_ical(malformed_interval, calendar_id='ical:x', calendar_name='X', timezone='UTC', now='2026-10-30T12:00:00Z')
except ValueError as exc:
    check('empty RRULE singleton fails as a parser error', 'invalid RRULE' in str(exc))
else:
    raise AssertionError('empty RRULE interval was accepted')

multi_count = malformed_interval.replace(b'INTERVAL=', b'COUNT=1,2')
try:
    ical.parse_ical(multi_count, calendar_id='ical:x', calendar_name='X', timezone='UTC', now='2026-10-30T12:00:00Z')
except ValueError as exc:
    check('multi-value RRULE singleton fails closed', 'RRULE number' in str(exc))
else:
    raise AssertionError('multi-value RRULE count was accepted')

def oversized_rule_feed(field: bytes, values: bytes):
    return (
        b'BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:oversized-rule\r\n'
        b'DTSTART;VALUE=DATE:20261030\r\nDTEND;VALUE=DATE:20261031\r\n'
        + b'RRULE:FREQ=MONTHLY;' + field + b'=' + values
        + b'\r\nSUMMARY:Oversized rule\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n'
    )

for field, values in [
    (b'BYDAY', b'MO,' * 600_000 + b'MO'),
    (b'BYMONTH', b'1,' * 600_000 + b'1'),
]:
    oversized_rule = oversized_rule_feed(field, values)
    check(f'oversized {field.decode()} fixture stays under the feed byte limit', len(oversized_rule) < getattr(ical, 'MAX_FEED_BYTES'))
    try:
        ical.parse_ical(oversized_rule, calendar_id='ical:x', calendar_name='X', timezone='UTC', now='2026-10-30T12:00:00Z')
    except ValueError as exc:
        check(f'oversized {field.decode()} fails before cardinality materialization', 'too long' in str(exc))
    else:
        raise AssertionError(f'oversized {field.decode()} was accepted')

for field, values in [
    (b'BYDAY', b','.join([b'MO'] * 65)),
    (b'BYMONTH', b','.join([b'1'] * 13)),
]:
    try:
        ical.parse_ical(oversized_rule_feed(field, values), calendar_id='ical:x', calendar_name='X', timezone='UTC', now='2026-10-30T12:00:00Z')
    except ValueError as exc:
        check(f'{field.decode()} value cardinality is capped while streaming', 'too many' in str(exc))
    else:
        raise AssertionError(f'{field.decode()} value cardinality limit was bypassed')

mixed_rdate = b'''BEGIN:VCALENDAR\r
BEGIN:VEVENT\r
UID:mixed-rdate\r
DTSTART;VALUE=DATE:20261030\r
DTEND;VALUE=DATE:20261031\r
RDATE:20261101T120000Z\r
SUMMARY:Mixed recurrence\r
END:VEVENT\r
END:VCALENDAR\r
'''
try:
    ical.parse_ical(mixed_rdate, calendar_id='ical:x', calendar_name='X', timezone='UTC', now='2026-10-30T12:00:00Z')
except ValueError as exc:
    check('mixed date and date-time recurrences fail closed', 'RDATE' in str(exc))
else:
    raise AssertionError('mixed date and date-time recurrence was accepted')

mixed_exdate = b'''BEGIN:VCALENDAR\r
BEGIN:VEVENT\r
UID:mixed-exdate\r
DTSTART;VALUE=DATE:20261030\r
DTEND;VALUE=DATE:20261031\r
RRULE:FREQ=DAILY;COUNT=2\r
EXDATE:20261031T120000Z\r
SUMMARY:Mixed exclusion\r
END:VEVENT\r
END:VCALENDAR\r
'''
try:
    ical.parse_ical(mixed_exdate, calendar_id='ical:x', calendar_name='X', timezone='UTC', now='2026-10-30T12:00:00Z')
except ValueError as exc:
    check('mixed date and date-time exclusions fail closed', 'EXDATE' in str(exc))
else:
    raise AssertionError('mixed date and date-time exclusion was accepted')

mixed_recurrence_id = b'''BEGIN:VCALENDAR\r
BEGIN:VEVENT\r
UID:mixed-override\r
DTSTART;VALUE=DATE:20261030\r
DTEND;VALUE=DATE:20261031\r
RRULE:FREQ=DAILY;COUNT=2\r
SUMMARY:Master\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:mixed-override\r
RECURRENCE-ID:20261031T120000Z\r
DTSTART:20261031T130000Z\r
DTEND:20261031T140000Z\r
SUMMARY:Override\r
END:VEVENT\r
END:VCALENDAR\r
'''
try:
    ical.parse_ical(mixed_recurrence_id, calendar_id='ical:x', calendar_name='X', timezone='UTC', now='2026-10-30T12:00:00Z')
except ValueError as exc:
    check('mixed recurrence identifiers fail closed', 'RECURRENCE-ID' in str(exc))
else:
    raise AssertionError('mixed recurrence identifier was accepted')

local_until = b'''BEGIN:VCALENDAR\r
BEGIN:VEVENT\r
UID:local-until\r
DTSTART;TZID=America/Vancouver:20261030T090000\r
DTEND;TZID=America/Vancouver:20261030T100000\r
RRULE:FREQ=DAILY;UNTIL=20261102T090000\r
SUMMARY:Local until\r
END:VEVENT\r
END:VCALENDAR\r
'''
until_events = ical.parse_ical(local_until, calendar_id='ical:x', calendar_name='X', timezone='UTC', now='2026-10-30T12:00:00Z')['events']
check('floating UNTIL uses DTSTART timezone', len(until_events) == 4 and until_events[-1]['start'].startswith('2026-11-02T09:00:00'))

ancient = b'''BEGIN:VCALENDAR\r
BEGIN:VEVENT\r
UID:ancient\r
DTSTART;VALUE=DATE:19000101\r
DTEND;VALUE=DATE:19000102\r
RRULE:FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR,SA,SU\r
SUMMARY:Ancient dense recurrence\r
END:VEVENT\r
END:VCALENDAR\r
'''
old_steps = getattr(ical, 'MAX_EXPANSION_STEPS')
setattr(ical, 'MAX_EXPANSION_STEPS', 50)
try:
    try:
        ical.parse_ical(ancient, calendar_id='ical:x', calendar_name='X', timezone='UTC', now='2026-10-30T12:00:00Z')
    except ValueError as exc:
        check('recurrence candidate emissions are bounded before materialization', 'recurrence is too large' in str(exc))
    else:
        raise AssertionError('dense historical recurrence bypassed the candidate bound')
finally:
    setattr(ical, 'MAX_EXPANSION_STEPS', old_steps)

rdate_quota = b'''BEGIN:VCALENDAR\r
BEGIN:VEVENT\r
UID:rdate-quota\r
DTSTART;VALUE=DATE:20261030\r
DTEND;VALUE=DATE:20261031\r
RDATE;VALUE=DATE:20261101,20261102,20261103\r
SUMMARY:RDATE quota\r
END:VEVENT\r
END:VCALENDAR\r
'''
exdate_quota = rdate_quota.replace(b'RDATE;VALUE=DATE:', b'EXDATE;VALUE=DATE:')
old_dates = getattr(ical, 'MAX_DATE_VALUES')
setattr(ical, 'MAX_DATE_VALUES', 2)
try:
    for label, payload in [('RDATE', rdate_quota), ('EXDATE', exdate_quota)]:
        try:
            ical.parse_ical(payload, calendar_id='ical:x', calendar_name='X', timezone='UTC', now='2026-10-30T12:00:00Z')
        except ValueError as exc:
            check(f'oversized {label} collections fail before materialization', 'too many recurrence dates' in str(exc))
        else:
            raise AssertionError(f'oversized {label} collection was accepted')
finally:
    setattr(ical, 'MAX_DATE_VALUES', old_dates)

old_steps = getattr(ical, 'MAX_EXPANSION_STEPS')
setattr(ical, 'MAX_EXPANSION_STEPS', 1)
try:
    try:
        ical.parse_ical(rdate_quota.replace(b',20261102,20261103', b''), calendar_id='ical:x', calendar_name='X', timezone='UTC', now='2026-10-30T12:00:00Z')
    except ValueError as exc:
        check('RDATE candidates share the recurrence expansion budget', 'recurrence is too large' in str(exc))
    else:
        raise AssertionError('RDATE candidates bypassed the recurrence budget')
finally:
    setattr(ical, 'MAX_EXPANSION_STEPS', old_steps)

record_quota = b'''BEGIN:VCALENDAR\r
BEGIN:VEVENT\r
UID:record-1\r
DTSTART;VALUE=DATE:20261030\r
DTEND;VALUE=DATE:20261031\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:record-2\r
DTSTART;VALUE=DATE:20261031\r
DTEND;VALUE=DATE:20261101\r
END:VEVENT\r
END:VCALENDAR\r
'''
old_records = getattr(ical, 'MAX_EVENT_RECORDS')
setattr(ical, 'MAX_EVENT_RECORDS', 1)
try:
    try:
        ical.parse_ical(record_quota, calendar_id='ical:x', calendar_name='X', timezone='UTC', now='2026-10-30T12:00:00Z')
    except ValueError as exc:
        check('VEVENT records have an independent parser bound', 'too many event records' in str(exc))
    else:
        raise AssertionError('VEVENT record limit was bypassed')
finally:
    setattr(ical, 'MAX_EVENT_RECORDS', old_records)

old_lines = getattr(ical, 'MAX_ICAL_LINES')
setattr(ical, 'MAX_ICAL_LINES', 2)
try:
    try:
        ical.parse_ical(record_quota, calendar_id='ical:x', calendar_name='X', timezone='UTC', now='2026-10-30T12:00:00Z')
    except ValueError as exc:
        check('unfolded feed lines are streamed under a hard bound', 'too many lines' in str(exc))
    else:
        raise AssertionError('iCal line limit was bypassed')
finally:
    setattr(ical, 'MAX_ICAL_LINES', old_lines)

detached = ['BEGIN:VCALENDAR']
for index in range(3):
    detached.extend([
        'BEGIN:VEVENT', f'UID:detached-{index}', f'RECURRENCE-ID;VALUE=DATE:2026110{index + 1}',
        f'DTSTART;VALUE=DATE:2026110{index + 1}', f'DTEND;VALUE=DATE:2026110{index + 2}',
        'SUMMARY:Detached', 'END:VEVENT',
    ])
detached.append('END:VCALENDAR')
old_limit = getattr(ical, 'MAX_EVENTS')
setattr(ical, 'MAX_EVENTS', 2)
try:
    try:
        ical.parse_ical(('\r\n'.join(detached) + '\r\n').encode(), calendar_id='ical:x', calendar_name='X', timezone='UTC', now='2026-10-30T12:00:00Z')
    except ValueError as exc:
        check('detached overrides obey the event bound', 'more than 10000 events' in str(exc))
    else:
        raise AssertionError('detached overrides bypassed the event bound')
finally:
    setattr(ical, 'MAX_EVENTS', old_limit)

print({'ok': True, 'count': len(checks), 'checks': checks})
