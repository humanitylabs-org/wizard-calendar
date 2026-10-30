#!/usr/bin/env python3
"""Strict Google iCal fetch and bounded RFC 5545 event expansion.

The private iCal URL is a bearer secret. This module accepts only Google's canonical
HTTPS feed shape, disables inherited proxies, and never includes the URL in errors or
parsed output.
"""
from __future__ import annotations

import calendar
import datetime as dt
import hashlib
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

MAX_FEED_BYTES = 8 * 1024 * 1024
MAX_EVENTS = 10_000
MAX_EXPANSION_STEPS = 100_000
_ALLOWED_HOST = 'calendar.google.com'
_WEEKDAY = {'MO': 0, 'TU': 1, 'WE': 2, 'TH': 3, 'FR': 4, 'SA': 5, 'SU': 6}
Temporal = dt.date | dt.datetime


def normalize_google_ical_url(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError('Google iCal link is required')
    value = value.strip()
    if value.lower().startswith('webcal://'):
        value = 'https://' + value[9:]
    if not value or len(value) > 4096:
        raise ValueError('Google iCal link is invalid')
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError('Use a Google Calendar iCal link ending in /basic.ics') from exc
    if (
        parsed.scheme != 'https'
        or parsed.hostname != _ALLOWED_HOST
        or port not in (None, 443)
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or not parsed.path.startswith('/calendar/ical/')
        or not parsed.path.endswith('/basic.ics')
        or len(parsed.path.split('/')) < 6
    ):
        raise ValueError('Use a Google Calendar iCal link ending in /basic.ics')
    return urlunsplit(('https', _ALLOWED_HOST, parsed.path, '', ''))


def source_id(url: str) -> str:
    normalized = normalize_google_ical_url(url)
    return 'ical:' + hashlib.sha256(normalized.encode()).hexdigest()[:20]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, 'Google iCal redirect refused', headers, fp)


def fetch_google_ical(url: str, *, timeout: int = 15, opener=None) -> bytes:
    safe = normalize_google_ical_url(url)
    # The path contains a bearer secret. Never let HTTP(S)_PROXY receive it.
    client = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    request = urllib.request.Request(safe, headers={'Accept': 'text/calendar,*/*;q=0.1', 'User-Agent': 'Wizard-Calendar/0.2'})
    try:
        with client.open(request, timeout=timeout) as response:
            body = response.read(MAX_FEED_BYTES + 1)
    except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
        raise ValueError('Google iCal could not be downloaded') from exc
    if len(body) > MAX_FEED_BYTES:
        raise ValueError('Google iCal feed exceeds 8 MiB')
    if not body:
        raise ValueError('Google iCal feed is empty')
    return body


def _unfold(payload: bytes) -> list[str]:
    if len(payload) > MAX_FEED_BYTES:
        raise ValueError('Google iCal feed exceeds 8 MiB')
    try:
        text = payload.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        raise ValueError('Google iCal feed must be UTF-8') from exc
    if '\x00' in text:
        raise ValueError('Google iCal feed contains invalid bytes')
    out: list[str] = []
    for line in text.replace('\r\n', '\n').replace('\r', '\n').split('\n'):
        if line[:1] in (' ', '\t') and out:
            out[-1] += line[1:]
        else:
            out.append(line)
    return out


def _parts(left: str) -> list[str]:
    parts, buf, quoted = [], [], False
    for char in left:
        if char == '"':
            quoted = not quoted
            buf.append(char)
        elif char == ';' and not quoted:
            parts.append(''.join(buf))
            buf = []
        else:
            buf.append(char)
    parts.append(''.join(buf))
    return parts


def _property(line: str):
    if ':' not in line:
        raise ValueError('Google iCal contains a malformed property')
    left, value = line.split(':', 1)
    bits = _parts(left)
    name = bits[0].upper()
    params = {}
    for bit in bits[1:]:
        if '=' not in bit:
            raise ValueError('Google iCal contains a malformed parameter')
        key, item = bit.split('=', 1)
        params[key.upper()] = item.strip('"')
    return name, params, value


def _text(value: str) -> str:
    out, i = [], 0
    while i < len(value):
        if value[i] == '\\' and i + 1 < len(value):
            nxt = value[i + 1]
            out.append('\n' if nxt in ('n', 'N') else nxt)
            i += 2
        else:
            out.append(value[i])
            i += 1
    return ''.join(out)


def _safe_https(value: str) -> str:
    value = _text(value).strip()
    if not value:
        return ''
    parsed = urlsplit(value)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        return ''
    return value[:2000]


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ValueError, KeyError) as exc:
        raise ValueError('Google iCal uses an unknown timezone') from exc


def _temporal(value: str, params: dict[str, str], default_zone: ZoneInfo):
    value = value.strip()
    if params.get('VALUE', '').upper() == 'DATE' or re.fullmatch(r'\d{8}', value):
        try:
            return dt.datetime.strptime(value, '%Y%m%d').date()
        except ValueError as exc:
            raise ValueError('Google iCal contains an invalid date') from exc
    match = re.fullmatch(r'(\d{8})T(\d{6})(Z?)', value)
    if not match:
        raise ValueError('Google iCal contains an invalid date-time')
    parsed = dt.datetime.strptime(match.group(1) + match.group(2), '%Y%m%d%H%M%S')
    if match.group(3):
        return parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.replace(tzinfo=_zone(params.get('TZID', '')) if params.get('TZID') else default_zone)


def _occ_key(value) -> str:
    if isinstance(value, dt.datetime):
        return value.astimezone(dt.timezone.utc).isoformat()
    return value.isoformat()


def _parse_now(value, zone: ZoneInfo) -> dt.datetime:
    if value is None:
        return dt.datetime.now(dt.timezone.utc)
    if isinstance(value, dt.datetime):
        parsed = value
    else:
        parsed = dt.datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=zone)
    return parsed.astimezone(dt.timezone.utc)


def _rrule(value: str) -> dict[str, str]:
    rule = {}
    for item in value.split(';'):
        if '=' not in item:
            raise ValueError('Google iCal contains an invalid RRULE')
        key, val = item.split('=', 1)
        key = key.upper()
        if key in rule:
            raise ValueError('Google iCal contains an invalid RRULE')
        rule[key] = val.upper()
    allowed = {'FREQ', 'UNTIL', 'COUNT', 'INTERVAL', 'BYDAY', 'BYMONTHDAY', 'BYMONTH', 'BYSETPOS', 'WKST'}
    unknown = set(rule) - allowed
    if unknown or rule.get('FREQ') not in {'DAILY', 'WEEKLY', 'MONTHLY', 'YEARLY'}:
        raise ValueError('unsupported RRULE in Google iCal feed')
    return rule


def _ints(value: str | None, minimum: int, maximum: int, *, nonzero=False) -> list[int]:
    if not value:
        return []
    try:
        result = [int(item) for item in value.split(',')]
    except ValueError as exc:
        raise ValueError('Google iCal contains an invalid RRULE number') from exc
    if any(item < minimum or item > maximum or (nonzero and item == 0) for item in result):
        raise ValueError('Google iCal contains an out-of-range RRULE number')
    return result


def _bydays(value: str | None) -> list[tuple[int | None, int]]:
    if not value:
        return []
    result = []
    for item in value.split(','):
        match = re.fullmatch(r'([+-]?\d{1,2})?(MO|TU|WE|TH|FR|SA|SU)', item)
        if not match:
            raise ValueError('Google iCal contains an invalid BYDAY')
        ordinal = int(match.group(1)) if match.group(1) else None
        if ordinal == 0 or (ordinal is not None and abs(ordinal) > 53):
            raise ValueError('Google iCal contains an invalid BYDAY ordinal')
        result.append((ordinal, _WEEKDAY[match.group(2)]))
    return result


def _monthday_matches(day: dt.date, values: list[int]) -> bool:
    if not values:
        return True
    last = calendar.monthrange(day.year, day.month)[1]
    return day.day in values or day.day - last - 1 in values


def _weekday_matches(day: dt.date, values: list[tuple[int | None, int]]) -> bool:
    if not values:
        return True
    last = calendar.monthrange(day.year, day.month)[1]
    for ordinal, weekday in values:
        if day.weekday() != weekday:
            continue
        if ordinal is None:
            return True
        if ordinal > 0 and (day.day - 1) // 7 + 1 == ordinal:
            return True
        if ordinal < 0 and -((last - day.day) // 7 + 1) == ordinal:
            return True
    return False


def _apply_positions(days: list[dt.date], positions: list[int]) -> list[dt.date]:
    if not positions:
        return days
    selected = []
    for position in positions:
        index = position - 1 if position > 0 else len(days) + position
        if 0 <= index < len(days) and days[index] not in selected:
            selected.append(days[index])
    return sorted(selected)


def _month_candidates(year, month, start_day, monthdays, bydays, positions):
    last = calendar.monthrange(year, month)[1]
    if not monthdays and not bydays:
        days = [dt.date(year, month, start_day)] if start_day <= last else []
    else:
        days = [
            dt.date(year, month, day)
            for day in range(1, last + 1)
            if _monthday_matches(dt.date(year, month, day), monthdays)
            and _weekday_matches(dt.date(year, month, day), bydays)
        ]
    return _apply_positions(days, positions)


def _as_start(day: dt.date, original):
    if isinstance(original, dt.datetime):
        return dt.datetime.combine(day, original.timetz())
    return day


def _until_allows(candidate, until) -> bool:
    if until is None:
        return True
    if isinstance(candidate, dt.date) and not isinstance(candidate, dt.datetime):
        if isinstance(until, dt.datetime):
            return candidate <= until.date()
        return candidate <= until
    if isinstance(until, dt.date) and not isinstance(until, dt.datetime):
        return candidate.date() <= until
    return candidate.astimezone(dt.timezone.utc) <= until.astimezone(dt.timezone.utc)


def _recurrences(start, raw_rule: str, default_zone: ZoneInfo, horizon: dt.datetime):
    rule = _rrule(raw_rule)
    interval = _ints(rule.get('INTERVAL', '1'), 1, 10_000)[0]
    count = _ints(rule.get('COUNT'), 1, 1_000_000)
    limit = count[0] if count else None
    until = _temporal(rule['UNTIL'], {}, default_zone) if rule.get('UNTIL') else None
    bymonth = _ints(rule.get('BYMONTH'), 1, 12)
    bymonthday = _ints(rule.get('BYMONTHDAY'), -31, 31, nonzero=True)
    byday = _bydays(rule.get('BYDAY'))
    positions = _ints(rule.get('BYSETPOS'), -366, 366, nonzero=True)
    wkst = _WEEKDAY.get(rule.get('WKST', 'MO'))
    if wkst is None:
        raise ValueError('Google iCal contains an invalid WKST')
    if rule['FREQ'] in {'DAILY', 'WEEKLY'} and any(item[0] is not None for item in byday):
        raise ValueError('unsupported RRULE in Google iCal feed')
    if rule['FREQ'] == 'YEARLY' and any(item[0] is not None for item in byday) and not bymonth:
        raise ValueError('unsupported RRULE in Google iCal feed')

    horizon_date = horizon.astimezone(start.tzinfo if isinstance(start, dt.datetime) else default_zone).date()
    start_date = start.date() if isinstance(start, dt.datetime) else start
    yielded = 0
    steps = 0

    def emit(days):
        nonlocal yielded
        for day in days:
            if day < start_date:
                continue
            candidate = _as_start(day, start)
            if not _until_allows(candidate, until):
                return False
            yielded += 1
            if limit is not None and yielded > limit:
                return False
            yield candidate
        return True

    freq = rule['FREQ']
    if freq == 'DAILY':
        day = start_date
        while day <= horizon_date:
            steps += 1
            if steps > MAX_EXPANSION_STEPS:
                raise ValueError('Google iCal recurrence is too large')
            delta = (day - start_date).days
            candidates = []
            if delta % interval == 0 and (not bymonth or day.month in bymonth) and _monthday_matches(day, bymonthday) and _weekday_matches(day, byday):
                candidates = _apply_positions([day], positions)
            for candidate in emit(candidates):
                yield candidate
            if limit is not None and yielded >= limit:
                return
            day += dt.timedelta(days=1)
    elif freq == 'WEEKLY':
        anchor = start_date - dt.timedelta(days=(start_date.weekday() - wkst) % 7)
        week = 0
        wanted = {weekday for _, weekday in byday} or {start_date.weekday()}
        while anchor + dt.timedelta(days=week * 7) <= horizon_date:
            steps += 1
            if steps > MAX_EXPANSION_STEPS:
                raise ValueError('Google iCal recurrence is too large')
            base = anchor + dt.timedelta(days=week * 7)
            days = sorted(base + dt.timedelta(days=(weekday - wkst) % 7) for weekday in wanted)
            days = [day for day in days if (not bymonth or day.month in bymonth) and _monthday_matches(day, bymonthday)]
            for candidate in emit(_apply_positions(days, positions)):
                yield candidate
            if limit is not None and yielded >= limit:
                return
            week += interval
    elif freq == 'MONTHLY':
        offset = 0
        while True:
            absolute = start_date.year * 12 + start_date.month - 1 + offset
            year, month0 = divmod(absolute, 12)
            month = month0 + 1
            if dt.date(year, month, 1) > horizon_date:
                return
            steps += 1
            if steps > MAX_EXPANSION_STEPS:
                raise ValueError('Google iCal recurrence is too large')
            days = [] if bymonth and month not in bymonth else _month_candidates(year, month, start_date.day, bymonthday, byday, positions)
            for candidate in emit(days):
                yield candidate
            if limit is not None and yielded >= limit:
                return
            offset += interval
    else:  # YEARLY
        year = start_date.year
        while dt.date(year, 1, 1) <= horizon_date:
            steps += 1
            if steps > MAX_EXPANSION_STEPS:
                raise ValueError('Google iCal recurrence is too large')
            months = bymonth or [start_date.month]
            days = []
            for month in months:
                days.extend(_month_candidates(year, month, start_date.day, bymonthday, byday, []))
            for candidate in emit(_apply_positions(sorted(days), positions)):
                yield candidate
            if limit is not None and yielded >= limit:
                return
            year += interval


@dataclass
class _Event:
    uid: str
    start: Temporal | None
    end: Temporal | None
    recurrence_id: Temporal | None
    rrule: str
    rdates: list
    exdates: set[str]
    title: str
    location: str
    description: str
    link: str
    meet: str
    status: str


def _events(payload: bytes, default_zone: ZoneInfo) -> list[_Event]:
    records, current = [], None
    for line in _unfold(payload):
        upper = line.upper()
        if upper == 'BEGIN:VEVENT':
            if current is not None:
                raise ValueError('Google iCal contains nested events')
            current = []
            continue
        if upper == 'END:VEVENT':
            if current is None:
                raise ValueError('Google iCal contains an unmatched event end')
            props = {}
            for name, params, value in current:
                props.setdefault(name, []).append((params, value))
            uid = _text(props.get('UID', [({}, '')])[0][1]).strip()
            if not uid or len(uid) > 650:
                raise ValueError('Google iCal event UID is invalid')
            status = props.get('STATUS', [({}, '')])[0][1].upper()
            recurrence_id = _temporal(props['RECURRENCE-ID'][0][1], props['RECURRENCE-ID'][0][0], default_zone) if props.get('RECURRENCE-ID') else None
            start = _temporal(props['DTSTART'][0][1], props['DTSTART'][0][0], default_zone) if props.get('DTSTART') else None
            if start is None and not (status == 'CANCELLED' and recurrence_id is not None):
                raise ValueError('Google iCal event has no start')
            end = _temporal(props['DTEND'][0][1], props['DTEND'][0][0], default_zone) if props.get('DTEND') else None
            if start is not None and end is None:
                end = start + (dt.timedelta(days=1) if not isinstance(start, dt.datetime) else dt.timedelta(hours=1))
            if start is not None:
                if end is None or isinstance(start, dt.datetime) != isinstance(end, dt.datetime) or end <= start:
                    raise ValueError('Google iCal event has an invalid end')
            rdates = []
            for params, value in props.get('RDATE', []):
                rdates.extend(_temporal(item, params, default_zone) for item in value.split(','))
            if start is not None and any(isinstance(item, dt.datetime) != isinstance(start, dt.datetime) for item in rdates):
                raise ValueError('Google iCal RDATE must match the event date type')
            exdates = set()
            for params, value in props.get('EXDATE', []):
                exdates.update(_occ_key(_temporal(item, params, default_zone)) for item in value.split(','))
            description = _text(props.get('DESCRIPTION', [({}, '')])[0][1])[:4000]
            meet_match = re.search(r'https://meet\.google\.com/[a-z0-9-]+', description, re.I)
            records.append(_Event(
                uid=uid,
                start=start,
                end=end,
                recurrence_id=recurrence_id,
                rrule=props.get('RRULE', [({}, '')])[0][1],
                rdates=rdates,
                exdates=exdates,
                title=(_text(props.get('SUMMARY', [({}, 'Untitled event')])[0][1]).strip() or 'Untitled event')[:300],
                location=_text(props.get('LOCATION', [({}, '')])[0][1])[:500],
                description=description,
                link=_safe_https(props.get('URL', [({}, '')])[0][1]),
                meet=_safe_https(meet_match.group(0)) if meet_match else '',
                status=status,
            ))
            current = None
            continue
        if current is not None:
            current.append(_property(line))
    if current is not None:
        raise ValueError('Google iCal contains an unterminated event')
    return records


def _window_contains(start, end, window_start: dt.datetime, window_end: dt.datetime, zone: ZoneInfo) -> bool:
    if isinstance(start, dt.datetime):
        return end.astimezone(dt.timezone.utc) > window_start and start.astimezone(dt.timezone.utc) < window_end
    first, last = window_start.astimezone(zone).date(), window_end.astimezone(zone).date()
    return end > first and start < last


def _render(event: _Event, start, end, calendar_id: str, occurrence_key: str):
    all_day = not isinstance(start, dt.datetime)
    digest = hashlib.sha256(f'{calendar_id}|{event.uid}|{occurrence_key}'.encode()).hexdigest()[:40]
    return {
        'id': f'{calendar_id}:{digest}',
        'cal': calendar_id,
        'title': event.title,
        'start': start.isoformat(),
        'end': end.isoformat(),
        'allDay': all_day,
        'location': event.location,
        'description': event.description,
        'link': event.link,
        'meet': event.meet,
    }


def parse_ical(
    payload: bytes,
    *,
    calendar_id: str,
    calendar_name: str,
    timezone: str = 'UTC',
    now=None,
    past_days: int = 60,
    future_days: int = 400,
):
    zone = _zone(timezone)
    anchor = _parse_now(now, zone)
    window_start = anchor - dt.timedelta(days=past_days)
    window_end = anchor + dt.timedelta(days=future_days)
    records = _events(payload, zone)
    overrides: dict[str, dict[str, _Event]] = {}
    masters: list[_Event] = []
    for event in records:
        if event.recurrence_id is not None:
            overrides.setdefault(event.uid, {})[_occ_key(event.recurrence_id)] = event
        else:
            masters.append(event)

    output, used_overrides = [], set()
    for event in masters:
        if event.status == 'CANCELLED' or event.start is None:
            continue
        if isinstance(event.start, dt.datetime):
            if not isinstance(event.end, dt.datetime):
                raise ValueError('Google iCal event has an invalid end')
            duration = event.end - event.start
        else:
            if event.end is None or isinstance(event.end, dt.datetime):
                raise ValueError('Google iCal event has an invalid end')
            duration = event.end - event.start
        occurrences = [event.start]
        if event.rrule:
            occurrences = list(_recurrences(event.start, event.rrule, zone, window_end))
        occurrences.extend(event.rdates)
        seen = set()
        for original_start in sorted(occurrences, key=_occ_key):
            key = _occ_key(original_start)
            if key in seen:
                continue
            seen.add(key)
            replacement = overrides.get(event.uid, {}).get(key)
            if replacement is not None:
                used_overrides.add((event.uid, key))
                if replacement.status == 'CANCELLED' or replacement.start is None:
                    continue
                selected = replacement
                start, end = replacement.start, replacement.end
            else:
                if key in event.exdates:
                    continue
                selected = event
                start, end = original_start, original_start + duration
            if _window_contains(start, end, window_start, window_end, zone):
                output.append(_render(selected, start, end, calendar_id, key))
                if len(output) > MAX_EVENTS:
                    raise ValueError('Google iCal feed has more than 10000 events in the visible range')

    # Keep detached overrides visible even when a provider omitted the matching master instance.
    for uid, rows in overrides.items():
        for key, event in rows.items():
            if (uid, key) in used_overrides or event.status == 'CANCELLED' or event.start is None:
                continue
            if _window_contains(event.start, event.end, window_start, window_end, zone):
                output.append(_render(event, event.start, event.end, calendar_id, key))
                if len(output) > MAX_EVENTS:
                    raise ValueError('Google iCal feed has more than 10000 events in the visible range')

    output.sort(key=lambda event: (event['start'], event['id']))
    return {
        'schemaVersion': 1,
        'timezone': timezone,
        'calendars': [{'id': calendar_id, 'name': calendar_name}],
        'events': output,
    }
