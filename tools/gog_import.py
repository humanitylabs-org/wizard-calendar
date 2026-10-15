#!/usr/bin/env python3
"""Explicit opt-in Google -> snapshot adapter, run outside the app container."""
import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from server import validate


def export(config, gog):
    account = config['account']
    if not isinstance(account, str) or '@' not in account or account == 'you@example.com':
        raise ValueError('Set the explicitly authorized account in the private connector config')
    calendars = config['calendars']
    if not calendars or len(calendars) > 100: raise ValueError('Select 1–100 calendars explicitly')
    now = dt.datetime.now(dt.timezone.utc)
    start = (now - dt.timedelta(days=int(config.get('pastDays', 60)))).isoformat()
    end = (now + dt.timedelta(days=int(config.get('futureDays', 400)))).isoformat()
    doc = {'schemaVersion': 1, 'timezone': config.get('timezone', 'UTC'), 'calendars': [], 'events': []}
    for cal in calendars:
        cid = cal['id']
        if not isinstance(cid, str) or not cid or cid.startswith('-'): raise ValueError('Invalid calendar id')
        result = subprocess.run([gog, '--no-input', '--readonly', '-a', account, 'calendar', 'events', cid, '--from', start, '--to', end, '--sort', 'start', '--all-pages', '--max', '250', '--json'], capture_output=True, text=True, timeout=120)
        if result.returncode: raise RuntimeError('gog failed; no import performed. Check authorization with gog locally.')
        raw = json.loads(result.stdout)
        if not isinstance(raw, dict) or not isinstance(raw.get('events'), list) or raw.get('nextPageToken'):
            raise ValueError('Incomplete or unexpected gog result; no import performed')
        doc['calendars'].append({'id': cid, 'name': cal['name']})
        seen = set()
        for event in raw['events']:
            if event.get('status') == 'cancelled': continue
            if any(a.get('self') and a.get('responseStatus') == 'declined' for a in event.get('attendees', [])): continue
            s, e = event.get('start', {}), event.get('end', {})
            allday = 'date' in s and 'dateTime' not in s
            eid = str(event['id'])
            if eid in seen: continue
            seen.add(eid)
            doc['events'].append({'id': cid + '::' + eid, 'cal': cid, 'title': (event.get('summary') or '(No title)')[:300], 'start': s.get('date') if allday else s.get('dateTime'), 'end': e.get('date') if allday else e.get('dateTime'), 'allDay': allday, 'description': (event.get('description') or '')[:4000], 'location': (event.get('location') or '')[:500], 'link': event.get('htmlLink') or '', 'meet': event.get('hangoutLink') or ''})
    return validate(doc)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--gog', default='gog')
    parser.add_argument('--output', type=Path, help='Write snapshot file (0600) instead of importing')
    parser.add_argument('--url', default='http://127.0.0.1:18787', help='Loopback or authenticated private gateway origin')
    args = parser.parse_args()
    doc = export(json.loads(args.config.read_text()), args.gog)
    data = json.dumps(doc).encode()
    if args.output:
        fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as out: out.write(data)
        print(json.dumps({'ok': True, 'events': len(doc['events']), 'mode': 'file'})); return
    from urllib.parse import urlsplit
    url = urlsplit(args.url)
    if url.scheme != 'http' or url.hostname not in ('127.0.0.1', 'localhost') or url.username or url.password:
        raise ValueError('This test adapter only sends to loopback http. Use --output and your authenticated gateway importer for remote installation.')
    req = urllib.request.Request(args.url.rstrip('/') + '/api/import', data=data, headers={'Content-Type': 'application/json'}, method='POST')
    with urllib.request.urlopen(req, timeout=30) as response: receipt = json.load(response)
    with urllib.request.urlopen(args.url.rstrip('/') + '/api/export', timeout=30) as response: saved = json.load(response)
    if saved.get('contentSha256') != receipt.get('contentSha256'): raise RuntimeError('Import readback mismatch')
    print(json.dumps(receipt))


if __name__ == '__main__': main()
