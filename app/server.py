#!/usr/bin/env python3
"""Calendar snapshot service. No credentials, provider calls or implicit imports."""
from __future__ import annotations
import datetime as dt
import hashlib
import json
import mimetypes
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get('DATA_DIR', './data')).resolve()
PORT = int(os.environ.get('PORT', '8799'))
BIND = os.environ.get('BIND', '127.0.0.1')
TZ = os.environ.get('CALENDAR_TIMEZONE', 'UTC')
ZoneInfo(TZ)  # fail explicitly on an invalid deployment timezone
CORE = Path(os.environ['WIZARD_CORE_DIR']).resolve() if os.environ.get('WIZARD_CORE_DIR') else None
HOSTS = set(filter(None, os.environ.get('WIZARD_TRUSTED_HOSTS', '').split(','))) or {f'127.0.0.1:{PORT}', f'localhost:{PORT}'}
ORIGINS = set(filter(None, os.environ.get('WIZARD_TRUSTED_ORIGINS', '').split(','))) or {f'http://{h}' for h in HOSTS}
LOCK = threading.RLock()
MAX_BYTES = 4 * 1024 * 1024
WEB = {'index.html', 'app.js', 'app.css', 'icon.svg'}


def empty():
    return {'schemaVersion': 1, 'timezone': TZ, 'calendars': [], 'events': [], 'syncedAt': None}


def read():
    with LOCK:
        path = DATA / 'snapshot.json'
        return json.loads(path.read_text()) if path.exists() else empty()


def save(doc):
    DATA.mkdir(parents=True, exist_ok=True)
    tmp = DATA / 'snapshot.tmp'
    with tmp.open('w') as f:
        json.dump(doc, f); f.flush(); os.fsync(f.fileno())
    tmp.replace(DATA / 'snapshot.json')


def text(value, name, limit=300, required=False):
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise ValueError(f'{name}: expected {"nonempty " if required else ""}string up to {limit} characters')
    return value


def validate(doc):
    if not isinstance(doc, dict) or doc.get('schemaVersion') != 1:
        raise ValueError('schemaVersion must be 1')
    timezone = text(doc.get('timezone', TZ), 'timezone', 100, True)
    try: ZoneInfo(timezone)
    except (ValueError, KeyError): raise ValueError('timezone must be an IANA timezone')
    cals, events = doc.get('calendars'), doc.get('events')
    if not isinstance(cals, list) or len(cals) > 100 or not isinstance(events, list) or len(events) > 10000:
        raise ValueError('calendars (max 100) and events (max 10000) must be arrays')
    ids, normalized_cals = set(), []
    for cal in cals:
        if not isinstance(cal, dict): raise ValueError('calendar must be an object')
        cid = text(cal.get('id'), 'calendar.id', 300, True)
        if cid in ids: raise ValueError('duplicate calendar id')
        ids.add(cid)
        normalized_cals.append({'id': cid, 'name': text(cal.get('name'), 'calendar.name', 300, True)})
    ev_ids, normalized = set(), []
    for ev in events:
        if not isinstance(ev, dict): raise ValueError('event must be an object')
        eid = text(ev.get('id'), 'event.id', 650, True)
        if eid in ev_ids: raise ValueError('duplicate event id')
        ev_ids.add(eid)
        cid = text(ev.get('cal'), 'event.cal', 300, True)
        if cid not in ids: raise ValueError('event references unknown calendar')
        allday = ev.get('allDay')
        if not isinstance(allday, bool): raise ValueError('allDay must be boolean')
        start, end = text(ev.get('start'), 'start', 50, True), text(ev.get('end'), 'end', 50, True)
        try:
            if allday:
                if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', start) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', end): raise ValueError()
                s, e = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
            else:
                s, e = dt.datetime.fromisoformat(start.replace('Z', '+00:00')), dt.datetime.fromisoformat(end.replace('Z', '+00:00'))
                if s.tzinfo is None or e.tzinfo is None: raise ValueError()
            if e <= s: raise ValueError()
        except (ValueError, TypeError): raise ValueError('start/end must be valid dates or offset timestamps; end must follow start')
        row = {'id': eid, 'cal': cid, 'title': text(ev.get('title'), 'title', 300, True), 'start': start, 'end': end, 'allDay': allday}
        for key, limit in [('location', 500), ('description', 4000), ('link', 2000), ('meet', 2000)]:
            value = text(ev.get(key, ''), key, limit)
            if key in ('link', 'meet') and value:
                url = urlsplit(value)
                if url.scheme != 'https' or not url.hostname or url.username or url.password: raise ValueError(f'{key} must be an https URL without credentials')
            row[key] = value
        normalized.append(row)
    normalized.sort(key=lambda e: (e['start'], e['id']))
    return {'schemaVersion': 1, 'timezone': timezone, 'calendars': normalized_cals, 'events': normalized}


def view():
    doc = read()
    hidden = set(doc.get('hidden', []))
    for c in doc['calendars']:
        c.update(hidden=c['id'] in hidden, ok=True, count=sum(e['cal'] == c['id'] for e in doc['events']))
    doc['events'] = [e for e in doc['events'] if e['cal'] not in hidden]
    return dict(doc, connected=[], errors=[], syncing=False, syncError='', mode='snapshot')


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass

    def respond(self, value, status=200, mime='application/json'):
        body = json.dumps(value).encode() if mime == 'application/json' else value
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        if self.command != 'HEAD': self.wfile.write(body)

    def trusted(self):
        if self.headers.get('Host') not in HOSTS or self.headers.get('Sec-Fetch-Site') == 'cross-site':
            self.respond({'error': 'untrusted_host_or_site'}, 403); return False
        if self.headers.get('Origin') and self.headers['Origin'] not in ORIGINS:
            self.respond({'error': 'untrusted_origin'}, 403); return False
        return True

    def route(self):
        p = urlsplit(self.path).path
        if p == '/wizard-calendar': return '/'
        return p[len('/wizard-calendar'):] if p.startswith('/wizard-calendar/') else p

    def do_HEAD(self): self.do_GET()

    def do_GET(self):
        if not self.trusted(): return
        p = self.route()
        if p in ('/healthz', '/api/health'):
            return self.respond({'ok': True, 'app': 'wizard-calendar', 'version': '0.1.0', 'mode': 'snapshot', 'configured': bool(read()['calendars'])})
        if p == '/api/events': return self.respond(view())
        if p == '/api/export': return self.respond(read())
        if p == '/openapi.json': return self.respond((ROOT / 'openapi.json').read_bytes(), mime='application/octet-stream')
        if p == '/wizard-os-home/core/app-client.js':
            if not CORE or not (CORE / 'app-client.js').is_file(): return self.respond({'error': 'shared_core_required', 'instructions': 'See README.md standalone setup'}, 503)
            return self.respond((CORE / 'app-client.js').read_bytes(), mime='text/javascript')
        name = 'index.html' if p == '/' else p[1:]
        if name not in WEB: return self.respond({'error': 'not_found'}, 404)
        return self.respond((ROOT / 'web' / name).read_bytes(), mime=mimetypes.guess_type(name)[0] or 'application/octet-stream')

    def do_POST(self):
        if not self.trusted(): return
        p = self.route()
        if p not in ('/api/import', '/api/calendars/visibility', '/mcp'): return self.respond({'error': 'not_found'}, 404)
        try:
            n = int(self.headers.get('Content-Length', '0'))
            if n <= 0 or n > MAX_BYTES: return self.respond({'error': 'body_size_limit'}, 413)
            body = json.loads(self.rfile.read(n))
            if not isinstance(body, dict): raise ValueError('body must be an object')
            if p == '/mcp': return self.mcp(body)
            with LOCK:
                if p == '/api/import':
                    normalized = validate(body)
                    previous = read()
                    digest = hashlib.sha256(json.dumps(normalized, sort_keys=True).encode()).hexdigest()
                    changed = digest != previous.get('contentSha256')
                    if changed:
                        normalized.update(contentSha256=digest, syncedAt=dt.datetime.now(dt.timezone.utc).isoformat(), hidden=[c for c in previous.get('hidden', []) if c in {x['id'] for x in normalized['calendars']}])
                        save(normalized)
                    return self.respond({'ok': True, 'changed': changed, 'events': len(normalized['events']), 'contentSha256': digest})
                doc = read()
                cid = body.get('id')
                if cid not in {c['id'] for c in doc['calendars']} or not isinstance(body.get('visible'), bool): raise ValueError('known calendar id and boolean visible are required')
                hidden = set(doc.get('hidden', []))
                if body['visible']: hidden.discard(cid)
                else: hidden.add(cid)
                doc['hidden'] = sorted(hidden); save(doc)
                return self.respond({'ok': True, 'hidden': doc['hidden']})
        except (ValueError, TypeError, KeyError) as exc:
            return self.respond({'error': str(exc)[:300]}, 400)
        except OSError:
            return self.respond({'error': 'storage_failure; previous snapshot retained'}, 500)

    def mcp(self, req):
        method, rid = req.get('method'), req.get('id')
        if method == 'notifications/initialized': return self.respond({}, 202)
        result = None
        if method == 'initialize': result = {'protocolVersion': '2024-11-05', 'capabilities': {'tools': {}}, 'serverInfo': {'name': 'wizard-calendar', 'version': '0.1.0'}}
        elif method == 'tools/list': result = {'tools': [{'name': 'calendar_events', 'description': 'Read the imported calendar snapshot; no provider access.', 'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False}, 'annotations': {'readOnlyHint': True}}]}
        elif method == 'tools/call' and isinstance(req.get('params'), dict) and req['params'].get('name') == 'calendar_events': result = {'content': [{'type': 'text', 'text': json.dumps(view())}], 'isError': False}
        elif method == 'ping': result = {}
        if result is None: return self.respond({'jsonrpc': '2.0', 'id': rid, 'error': {'code': -32601, 'message': 'Method or tool not found'}})
        return self.respond({'jsonrpc': '2.0', 'id': rid, 'result': result})


if __name__ == '__main__':
    DATA.mkdir(parents=True, exist_ok=True)
    ThreadingHTTPServer((BIND, PORT), Handler).serve_forever()
