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
