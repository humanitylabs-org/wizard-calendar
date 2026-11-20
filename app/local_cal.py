"""The local calendar on this Wizard (issue 58, behind switch local-calendar).

Events live in DATA/local.json, so they are part of the app's data (backup and restore keep them) and need no account.
The owner creates, edits, moves and deletes them from Day / Week / Month; agents use the local_calendar_* MCP tools,
and only change anything when the owner set Settings > This Wizard's calendar > Agents to Can edit.

Repeats are RFC 5545 rules (the form offers every day / week / month / year; an imported .ics keeps its own rule when
ical_feed can expand it). One repeat can be changed (an override, like RECURRENCE-ID) or deleted (an exdate) on its
own. .ics import goes through ical_feed's bounded parser; export writes a plain VCALENDAR.
"""
from __future__ import annotations

import datetime as dt
import re
import secrets
from zoneinfo import ZoneInfo

import ical_feed
from live import LiveError

CAL_ID = 'local'
NAME = 'On this Wizard'
MAX_RECORDS = 5000
LEVELS = [
    {'id': 'no_access', 'label': 'No access', 'what': 'Agents can\u2019t see this calendar.'},
    {'id': 'read_only', 'label': 'Read-only', 'recommended': True, 'what': 'Agents see these events. They can\u2019t change anything.'},
    {'id': 'can_edit', 'label': 'Can edit', 'what': 'Agents add, change and delete events on this calendar for you.'},
]
LEVEL_IDS = [x['id'] for x in LEVELS]
DEFAULT_LEVEL = 'read_only'
REPEATS = {'none': '', 'daily': 'FREQ=DAILY', 'weekly': 'FREQ=WEEKLY', 'monthly': 'FREQ=MONTHLY', 'yearly': 'FREQ=YEARLY'}
DATE = re.compile(r'\d{4}-\d{2}-\d{2}')
UID = re.compile(r'[0-9a-f]{24}')
ZONE = re.compile(r'[A-Za-z_]+(/[A-Za-z0-9_+\-]+){0,2}')
TEXT_FIELDS = (('title', 300), ('location', 500), ('description', 4000))


def _err(code, message, status=400):
    return LiveError(status, code, message)


def _zone(name, fallback):
    name = name or fallback
    if not isinstance(name, str) or not ZONE.fullmatch(name):
        raise _err('invalid_time_zone', 'Unknown time zone.')
    try:
        ZoneInfo(name)
    except (ValueError, KeyError):
        raise _err('invalid_time_zone', 'Unknown time zone.') from None
    return name


def _wall(value, zone, name):
    """A date ('2026-11-20') or a wall time in `zone` ('2026-11-20T09:30[:00]', or with an offset, converted)."""
    if not isinstance(value, str):
        raise _err('invalid_time', f'{name} must be a date (2026-11-04) or a time (2026-11-04T09:30).')
    value = value.strip()
    try:
        if DATE.fullmatch(value):
            return dt.date.fromisoformat(value)
        parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise _err('invalid_time', f'{name} must be a date (2026-11-04) or a time (2026-11-04T09:30).') from None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(ZoneInfo(zone)).replace(tzinfo=None)
    return parsed.replace(second=0, microsecond=0)


def _str(value):
    return value.isoformat() if isinstance(value, dt.datetime) else value.isoformat()


def _aware(value, zone):
    """Stored start/end -> an iCal temporal (date, or a datetime in the event's zone)."""
    if DATE.fullmatch(value):
        return dt.date.fromisoformat(value)
    return dt.datetime.fromisoformat(value).replace(tzinfo=ZoneInfo(zone))


def _key(value, zone):
    return ical_feed._occ_key(_aware(value, zone) if isinstance(value, str) else value)


def _shift_key(key, delta, zone):
    """An occurrence key (UTC time or date) moved by a wall-clock delta in the event's zone."""
    if DATE.fullmatch(key):
        days = delta.days if isinstance(delta, dt.timedelta) else 0
        return (dt.date.fromisoformat(key) + dt.timedelta(days=days)).isoformat()
    wall = dt.datetime.fromisoformat(key).astimezone(ZoneInfo(zone)).replace(tzinfo=None) + delta
    return ical_feed._occ_key(wall.replace(tzinfo=ZoneInfo(zone)))


def _repeat_name(rrule):
    for name, rule in REPEATS.items():
        if rule == rrule:
            return name
    return 'custom'


def _check_rule(start, rrule, zone):
    """True when ical_feed can expand this rule for this start (else the event is kept as a single one)."""
    try:
        horizon = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)
        next(iter(ical_feed._recurrences(_aware(start, zone), rrule, ZoneInfo(zone), horizon)), None)
        return True
    except (ValueError, TypeError, OverflowError):
        return False


class Local:
    def __init__(self, load, save, timezone, now=None):
        self._load, self._save, self.tz = load, save, timezone
        self.now = now or (lambda: dt.datetime.now(dt.timezone.utc))

    # ---------- storage ----------
    def doc(self):
        doc = self._load()
        if not isinstance(doc, dict) or doc.get('schemaVersion') != 1 or not isinstance(doc.get('events'), list):
            doc = {'schemaVersion': 1, 'events': [], 'agentAccess': DEFAULT_LEVEL}
        if doc.get('agentAccess') not in LEVEL_IDS:
            doc['agentAccess'] = DEFAULT_LEVEL
        return doc

    def level(self):
        return self.doc()['agentAccess']

    def set_level(self, level):
        if level not in LEVEL_IDS:
            raise _err('invalid_level', 'Choose No access, Read-only or Can edit.')
        doc = self.doc()
        doc['agentAccess'] = level
        self._save(doc)
        return self.access()

    def access(self):
        return {'level': self.level(), 'levels': LEVELS}

    def _find(self, doc, uid):
        rec = next((r for r in doc['events'] if r.get('uid') == uid), None)
        if rec is None:
            raise _err('not_found', 'That event is no longer on this calendar.', 404)
        return rec

    @staticmethod
    def _ids(value):
        """'<uid>' or '<uid>|<occurrence key>' (also with the view's 'local:' prefix)."""
        if not isinstance(value, str) or len(value) > 200:
            raise _err('invalid_event', 'Unknown event.')
        value = value[len('local:'):] if value.startswith('local:') else value
        uid, _, occ = value.partition('|')
        if not UID.fullmatch(uid):
            raise _err('invalid_event', 'Unknown event.')
        return uid, occ or None

    # ---------- reading ----------
    def _occurrences(self, rec, first, last):
        """(key, start, end, override) of one record inside [first, last) (aware datetimes, UTC)."""
        zone = rec['time_zone']
        start, end = _aware(rec['start'], zone), _aware(rec['end'], zone)
        duration = end - start
        if rec.get('rrule'):
            try:
                starts = ical_feed._recurrences(start, rec['rrule'], ZoneInfo(zone), last)
            except ValueError:
                starts = iter((start,))
        else:
            starts = iter((start,))
        exdates, overrides = set(rec.get('exdates') or []), rec.get('overrides') or {}
        out, count = [], 0
        try:
            for occ in starts:
                count += 1
                if count > 20000:
                    break
                key = ical_feed._occ_key(occ)
                if key in exdates:
                    continue
                ov = overrides.get(key)
                if ov:
                    s, e = _aware(ov['start'], ov.get('time_zone') or zone), _aware(ov['end'], ov.get('time_zone') or zone)
                else:
                    s, e = occ, occ + duration
                if _inside(s, e, first, last, self.tz):
                    out.append((key, s, e, ov))
                elif not ov and _after(s, last, self.tz):
                    break
        except ValueError:
            pass
        # An override moved into the window from a repeat that is outside it.
        for key, ov in overrides.items():
            if key in exdates or any(k == key for k, *_ in out):
                continue
            s, e = _aware(ov['start'], ov.get('time_zone') or zone), _aware(ov['end'], ov.get('time_zone') or zone)
            if _inside(s, e, first, last, self.tz):
                out.append((key, s, e, ov))
        return out

    def window(self, start, end):
        """The view's calendar row and events for [start, end) (dates)."""
        first = dt.datetime.combine(dt.date.fromisoformat(start), dt.time(), ZoneInfo(self.tz))
        last = dt.datetime.combine(dt.date.fromisoformat(end), dt.time(), ZoneInfo(self.tz))
        events = []
        for rec in self.doc()['events']:
            recurring = bool(rec.get('rrule'))
            for key, s, e, ov in self._occurrences(rec, first, last):
                src = dict(rec, **(ov or {}))
                lid = f"{rec['uid']}|{key}" if recurring else rec['uid']
                events.append({
                    'id': f'local:{lid}', 'cal': CAL_ID, 'title': src['title'], 'start': _str(s), 'end': _str(e),
                    'allDay': not isinstance(s, dt.datetime), 'location': src.get('location', ''),
                    'description': src.get('description', ''), 'guests': '', 'meet': '', 'link': '',
                    'live': {'account': CAL_ID, 'calendar_id': CAL_ID, 'id': lid, 'local': True, 'is_organizer': True,
                             'my_response': 'none', 'invited': False, 'recurring': recurring,
                             'time_zone': src.get('time_zone') or rec['time_zone'], 'series_id': rec['uid'],
                             'repeat': _repeat_name(rec.get('rrule') or ''), 'by_agent': bool(src.get('by_agent'))},
                })
                if len(events) >= 10000:
                    break
        events.sort(key=lambda x: (x['start'], x['id']))
        return {'calendar': {'id': CAL_ID, 'name': NAME, 'source': 'local', 'live': True, 'local': True}, 'events': events}

    # ---------- changing ----------
    def _fields(self, body, partial, zone):
        out = {}
        for name, limit in TEXT_FIELDS:
            if name in body or (name == 'title' and not partial):
                value = body.get(name)
                if value is None and name != 'title':
                    value = ''
                if not isinstance(value, str) or len(value) > limit or (name == 'title' and not value.strip()):
                    raise _err(f'invalid_{name}', 'Give the event a title (up to 300 characters).' if name == 'title'
                               else f'{name.capitalize()} is too long.')
                out[name] = value.strip() if name == 'title' else value
        if not partial or 'start' in body or 'end' in body:
            start = _wall(body.get('start'), zone, 'Start')
            all_day = not isinstance(start, dt.datetime)
            if body.get('all_day') is True and not all_day:
                start, all_day = start.date(), True
            raw_end = body.get('end')
            if raw_end in (None, ''):
                end = start + (dt.timedelta(days=1) if all_day else dt.timedelta(hours=1))
            else:
                end = _wall(raw_end, zone, 'End')
                if all_day and isinstance(end, dt.datetime):
                    end = end.date() if end.time() == dt.time() else end.date() + dt.timedelta(days=1)
                if isinstance(end, dt.datetime) != (not all_day):
                    raise _err('invalid_time', 'Start and end must both be dates (all day) or both times.')
            if all_day and end == start:
                end = start + dt.timedelta(days=1)
            if end <= start:
                raise _err('invalid_time', 'The event ends before it starts.')
            out['start'], out['end'] = _str(start), _str(end)
        return out

    def _rule(self, body, start, zone):
        repeat = body.get('repeat', 'none')
        if repeat not in REPEATS:
            raise _err('invalid_repeat', 'Repeat must be none, daily, weekly, monthly or yearly.')
        rule = REPEATS[repeat]
        until = body.get('repeat_until')
        if rule and until not in (None, ''):
            if not isinstance(until, str) or not DATE.fullmatch(until):
                raise _err('invalid_repeat', 'repeat_until must be a date (2026-12-31).')
            stamp = until.replace('-', '')
            rule += ';UNTIL=' + (stamp if DATE.fullmatch(start) else stamp + 'T235959')
        return rule

    def create(self, body, by_agent=False):
        zone = _zone(body.get('time_zone'), self.tz)
        fields = self._fields(body, False, zone)
        doc = self.doc()
        if len(doc['events']) >= MAX_RECORDS:
            raise _err('too_many_events', f'This calendar holds up to {MAX_RECORDS} events.')
        stamp = self.now().isoformat()
        rec = {'uid': secrets.token_hex(12), **fields, 'time_zone': zone, 'rrule': self._rule(body, fields['start'], zone),
               'exdates': [], 'overrides': {}, 'created': stamp, 'updated': stamp, 'by_agent': bool(by_agent)}
        rec.setdefault('location', ''); rec.setdefault('description', '')
        doc['events'].append(rec)
        self._save(doc)
        return {'created': True, 'id': rec['uid'], 'event': self.public(rec)}

    def update(self, body, by_agent=False):
        uid, occ = self._ids(body.get('id'))
        doc = self.doc()
        rec = self._find(doc, uid)
        zone = rec['time_zone']
        series = not occ or not rec.get('rrule') or body.get('scope') == 'series'
        if series and ('shift_start_minutes' in body or 'shift_end_minutes' in body):
            self._shift(rec, body)
        elif series:
            if 'time_zone' in body and body['time_zone']:
                zone = _zone(body['time_zone'], self.tz)
            fields = self._fields(body, True, zone)
            if 'start' in fields:
                new_start, new_end = fields['start'], fields['end']
                was_all_day = bool(DATE.fullmatch(rec['start']))
                now_all_day = bool(DATE.fullmatch(new_start))
                if occ and rec.get('rrule') and was_all_day == now_all_day:
                    # Edited from one repeat: the series moves by the same amount (and the same length as asked).
                    old = rec.get('overrides', {}).get(occ, {}).get('start') or _occ_wall(occ, rec)
                    delta = _parse(new_start) - _parse(old)
                    first = _parse(rec['start']) + delta
                    fields['start'] = _str(first)
                    fields['end'] = _str(first + (_parse(new_end) - _parse(new_start)))
                    rec['exdates'] = [_shift_key(k, delta, rec['time_zone']) for k in rec.get('exdates') or []]
                    rec['overrides'] = {_shift_key(k, delta, rec['time_zone']): v for k, v in (rec.get('overrides') or {}).items()}
                elif was_all_day != now_all_day:
                    rec['exdates'], rec['overrides'] = [], {}
            if 'repeat' in body or 'repeat_until' in body:
                rule = self._rule(body, fields.get('start', rec['start']), zone)
                if rule != rec.get('rrule'):
                    rec['rrule'], rec['exdates'], rec['overrides'] = rule, [], {}
            if not fields and 'repeat' not in body:
                raise _err('nothing_to_change', 'Nothing to change.')
            rec.update(fields, time_zone=zone)
            if rec.get('rrule') and not _check_rule(rec['start'], rec['rrule'], zone):
                rec['rrule'] = ''
        else:
            fields = self._fields(body, True, zone)
            if not fields:
                raise _err('nothing_to_change', 'Nothing to change.')
            ov = dict(rec.get('overrides', {}).get(occ) or {})
            if not ov:
                ov = {'start': _occ_wall(occ, rec)}
                ov['end'] = _str(_parse(ov['start']) + (_parse(rec['end']) - _parse(rec['start'])))
            ov.update(fields, time_zone=zone)
            if by_agent:
                ov['by_agent'] = True
            rec.setdefault('overrides', {})[occ] = ov
        rec['updated'] = self.now().isoformat()
        if by_agent:
            rec['by_agent'] = True
        self._save(doc)
        return {'updated': True, 'scope': 'series' if series else 'one'}

    def _shift(self, rec, body):
        """Drag with "All events": every repeat moves by the same minutes (days for all-day events)."""
        moves = []
        for name in ('shift_start_minutes', 'shift_end_minutes'):
            value = body.get(name, 0)
            if isinstance(value, bool) or not isinstance(value, int) or abs(value) > 366 * 1440:
                raise _err('invalid_shift', 'Move a series by less than a year.')
            moves.append(value)
        if not any(moves):
            raise _err('nothing_to_change', 'Nothing to change.')
        start, end = _parse(rec['start']), _parse(rec['end'])
        if isinstance(start, dt.datetime):
            ds, de = dt.timedelta(minutes=moves[0]), dt.timedelta(minutes=moves[1])
        else:
            ds, de = dt.timedelta(days=moves[0] // 1440), dt.timedelta(days=moves[1] // 1440)
        if end + de <= start + ds:
            raise _err('invalid_time', 'The event ends before it starts.')
        rec['start'], rec['end'] = _str(start + ds), _str(end + de)
        if ds:
            rec['exdates'] = [_shift_key(k, ds, rec['time_zone']) for k in rec.get('exdates') or []]
            rec['overrides'] = {_shift_key(k, ds, rec['time_zone']): v for k, v in (rec.get('overrides') or {}).items()}

    def delete(self, body, by_agent=False):
        uid, occ = self._ids(body.get('id'))
        doc = self.doc()
        rec = self._find(doc, uid)
        if occ and rec.get('rrule') and body.get('scope') != 'series':
            rec.setdefault('exdates', [])
            if occ not in rec['exdates']:
                rec['exdates'].append(occ)
            (rec.get('overrides') or {}).pop(occ, None)
            rec['updated'] = self.now().isoformat()
            self._save(doc)
            return {'deleted': True, 'scope': 'one'}
        doc['events'] = [r for r in doc['events'] if r.get('uid') != uid]
        self._save(doc)
        return {'deleted': True, 'scope': 'series'}

    def public(self, rec):
        """One stored event for an agent: plain fields, the repeat as a word."""
        return {'id': rec['uid'], 'title': rec['title'], 'start': rec['start'], 'end': rec['end'],
                'all_day': bool(DATE.fullmatch(rec['start'])), 'time_zone': rec['time_zone'],
                'location': rec.get('location', ''), 'description': rec.get('description', ''),
                'repeat': _repeat_name(rec.get('rrule') or ''), 'rrule': rec.get('rrule') or ''}

    # ---------- .ics ----------
    def import_ics(self, payload):
        if isinstance(payload, str):
            payload = payload.encode()
        zone = ZoneInfo(self.tz)
        try:
            records = ical_feed._events(payload, zone)
        except ValueError as exc:
            raise _err('invalid_ics', str(exc).replace('Google iCal feed', 'The .ics file').replace('Google iCal', 'The .ics file')[:300]) from None
        doc = self.doc()
        # A file exported from this calendar names its events '<uid>@wizard-calendar': importing it again updates them.
        by_ical = {r.get('ical_uid') or f"{r['uid']}@wizard-calendar": r for r in doc['events']}
        masters = [r for r in records if r.recurrence_id is None]
        changes = [r for r in records if r.recurrence_id is not None]
        added = updated = simplified = skipped = 0
        stamp = self.now().isoformat()
        for ev in masters:
            if ev.status == 'CANCELLED' or ev.start is None:
                skipped += 1
                continue
            tz, start, end = _stored(ev.start, self.tz), None, None
            start, end = _stored_value(ev.start, tz), _stored_value(ev.end, tz)
            rule = ev.rrule or ''
            if rule and not _check_rule(start, rule, tz):
                rule, simplified = '', simplified + 1
            rec = by_ical.get(ev.uid)
            if rec is None:
                if len(doc['events']) >= MAX_RECORDS:
                    raise _err('too_many_events', f'This calendar holds up to {MAX_RECORDS} events.')
                rec = {'uid': secrets.token_hex(12), 'ical_uid': ev.uid, 'created': stamp}
                doc['events'].append(rec)
                by_ical[ev.uid] = rec
                added += 1
            else:
                updated += 1
            rec.update(title=ev.title, start=start, end=end, time_zone=tz, location=ev.location, description=ev.description,
                       rrule=rule, exdates=sorted(ev.exdates) if rule else [], overrides={}, updated=stamp, by_agent=False)
        for ev in changes:
            rec = by_ical.get(ev.uid)
            if rec is None or not rec.get('rrule'):
                skipped += 1
                continue
            key = ical_feed._occ_key(ev.recurrence_id)
            if ev.status == 'CANCELLED' or ev.start is None:
                if key not in rec['exdates']:
                    rec['exdates'].append(key)
                continue
            tz = _stored(ev.start, rec['time_zone'])
            rec['overrides'][key] = {'title': ev.title, 'start': _stored_value(ev.start, tz), 'end': _stored_value(ev.end, tz),
                                     'time_zone': tz, 'location': ev.location, 'description': ev.description}
        self._save(doc)
        return {'imported': True, 'added': added, 'updated': updated, 'simplified': simplified, 'skipped': skipped}

    def export_ics(self):
        stamp = self.now().strftime('%Y%m%dT%H%M%SZ')
        lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Humanity Labs//Wizard Calendar//EN', 'CALSCALE:GREGORIAN',
                 f'X-WR-CALNAME:{_esc(NAME)}']
        for rec in self.doc()['events']:
            uid = rec.get('ical_uid') or f"{rec['uid']}@wizard-calendar"
            lines += _vevent(uid, stamp, rec, rec['time_zone'])
            if rec.get('rrule'):
                lines.append('RRULE:' + rec['rrule'])
                for key in rec.get('exdates') or []:
                    lines.append(_prop('EXDATE', _occ_temporal(key, rec)))
            lines.append('END:VEVENT')
            for key, ov in (rec.get('overrides') or {}).items():
                lines += _vevent(uid, stamp, dict(rec, **ov), ov.get('time_zone') or rec['time_zone'])
                lines.append(_prop('RECURRENCE-ID', _occ_temporal(key, rec)))
                lines.append('END:VEVENT')
        lines.append('END:VCALENDAR')
        return ''.join(_fold(line) + '\r\n' for line in lines)


# ---------- helpers ----------
def _parse(value):
    return dt.date.fromisoformat(value) if DATE.fullmatch(value) else dt.datetime.fromisoformat(value)


def _occ_wall(key, rec):
    """An occurrence key back to the stored wall form in the event's zone."""
    if DATE.fullmatch(key):
        return key
    return _str(dt.datetime.fromisoformat(key).astimezone(ZoneInfo(rec['time_zone'])).replace(tzinfo=None))


def _occ_temporal(key, rec):
    if DATE.fullmatch(key):
        return dt.date.fromisoformat(key)
    return dt.datetime.fromisoformat(key).astimezone(ZoneInfo(rec['time_zone']))


def _stored(value, fallback):
    """The IANA zone an imported time is kept in (UTC for a fixed offset)."""
    if isinstance(value, dt.datetime):
        return getattr(value.tzinfo, 'key', None) or 'UTC'
    return fallback


def _stored_value(value, zone):
    if isinstance(value, dt.datetime):
        return _str(value.astimezone(ZoneInfo(zone)).replace(tzinfo=None, second=value.second, microsecond=0))
    return value.isoformat()


def _inside(s, e, first, last, tz):
    if isinstance(s, dt.datetime):
        return e > first and s < last
    zone = ZoneInfo(tz)
    return e > first.astimezone(zone).date() and s < last.astimezone(zone).date()


def _after(s, last, tz):
    if isinstance(s, dt.datetime):
        return s >= last
    return s >= last.astimezone(ZoneInfo(tz)).date()


def _esc(text):
    return str(text).replace('\\', '\\\\').replace(';', '\\;').replace(',', '\\,').replace('\r\n', '\\n').replace('\n', '\\n')


def _prop(name, value):
    if isinstance(value, dt.datetime):
        zone = getattr(value.tzinfo, 'key', 'UTC')
        if zone == 'UTC':
            return f"{name}:{value.astimezone(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        return f"{name};TZID={zone}:{value.strftime('%Y%m%dT%H%M%S')}"
    return f"{name};VALUE=DATE:{value.strftime('%Y%m%d')}"


def _vevent(uid, stamp, rec, zone):
    out = ['BEGIN:VEVENT', f'UID:{_esc(uid)}', f'DTSTAMP:{stamp}',
           _prop('DTSTART', _aware(rec['start'], zone)), _prop('DTEND', _aware(rec['end'], zone)),
           f"SUMMARY:{_esc(rec.get('title', ''))}"]
    if rec.get('location'):
        out.append(f"LOCATION:{_esc(rec['location'])}")
    if rec.get('description'):
        out.append(f"DESCRIPTION:{_esc(rec['description'])}")
    return out


def _fold(line):
    raw = line.encode()
    if len(raw) <= 75:
        return line
    parts, cur = [], b''
    for ch in line:
        b = ch.encode()
        if len(cur) + len(b) > (75 if not parts else 74):
            parts.append(cur.decode())
            cur = b''
        cur += b
    parts.append(cur.decode())
    return '\r\n '.join(parts)
