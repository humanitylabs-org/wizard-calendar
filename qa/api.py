#!/usr/bin/env python3
"""Destructive synthetic QA against a disposable, initially empty Calendar."""
import argparse
import copy
import json
from pathlib import Path
import urllib.error
import urllib.request

p = argparse.ArgumentParser(); p.add_argument('--url', required=True); args = p.parse_args()
root = Path(__file__).resolve().parents[1]
results = []


def request(path, body=None, headers=None):
    h = {'Content-Type': 'application/json', **(headers or {})}
    req = urllib.request.Request(args.url + path, data=json.dumps(body).encode() if body is not None else None, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            raw = response.read()
            return response.status, json.loads(raw) if response.headers.get_content_type() == 'application/json' else raw.decode()
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def check(name, condition):
    assert condition, name
    results.append(name)


status, health = request('/healthz')
check('health identifies intended app', status == 200 and health['app'] == 'wizard-calendar')
for prefix in ('', '/wizard-calendar'):
    status, index = request(prefix + '/api')
    check('API index ' + prefix, status == 200 and '/api/events' in index['routes'])
    for route in ('/api/connect/start', '/api/connect/finish'):
        for body in (None, {'email': 'synthetic@example.invalid', 'url': 'not-a-code'}):
            status, result = request(prefix + route, body)
            check('superseded ' + prefix + route + (' POST' if body else ' GET'), status == 410 and result['setup_url'] == '/wizard-connectors/' and result['superseded_by'] == 'Connected accounts')
        check('superseded rejects untrusted origin ' + route, request(prefix + route, {}, {'Origin': 'https://untrusted.invalid'})[0] == 403)
_, initial = request('/api/events')
check('fresh install empty and unconnected', initial['events'] == [] and initial['calendars'] == [] and initial['connected'] == [])
_, sync = request('/api/sync')
check('sync status available', sync['state'] == 'not_linked' and sync['last_success'] is None)
check('health includes sync detail', request('/api/health')[1]['sync']['state'] == 'not_linked')
fixture = json.loads((root / 'fixtures/example.json').read_text())
status, first = request('/api/import', fixture)
check('fixture import', status == 200 and first['events'] == 2 and first['changed'])
_, saved = request('/api/export')
check('readback import', saved['contentSha256'] == first['contentSha256'] and len(saved['events']) == 2)
_, repeat = request('/api/import', fixture)
check('repeat import idempotent', repeat['changed'] is False and repeat['contentSha256'] == first['contentSha256'])
_, same = request('/api/export')
check('timestamp unchanged on no-op', same['syncedAt'] == saved['syncedAt'])
for name, mutate in [
    ('unknown calendar', lambda d: d['events'][0].update(cal='missing')),
    ('unsafe link', lambda d: d['events'][0].update(link='javascript:alert(1)')),
    ('naive datetime', lambda d: d['events'][0].update(start='2026-10-15T10:00:00')),
    ('invalid timezone', lambda d: d.update(timezone='Not/AZone')),
    ('duplicate ID', lambda d: d['events'].append(d['events'][0])),
    ('inverted range', lambda d: d['events'][0].update(end='2026-10-14T10:00:00Z')),
]:
    bad = copy.deepcopy(fixture); mutate(bad)
    check('reject ' + name, request('/api/import', bad)[0] == 400)
    check('preserve after ' + name, request('/api/export')[1] == saved)
check('reject cross-origin write', request('/api/import', fixture, {'Origin': 'https://untrusted.invalid'})[0] == 403)
check('reject forged forwarded host', request('/api/events', headers={'Host': 'untrusted.invalid', 'X-Forwarded-Host': '127.0.0.1:18787'})[0] == 403)
check('invalid visibility type', request('/api/calendars/visibility', {'id':'fixture','visible':'false'})[0] == 400)
check('hide calendar', request('/api/calendars/visibility', {'id':'fixture','visible':False})[0] == 200)
check('hidden event readback', request('/api/events')[1]['events'] == [])
check('export retains hidden events', len(request('/api/export')[1]['events']) == 2)
request('/api/calendars/visibility', {'id':'fixture','visible':True})
check('show readback', len(request('/api/events')[1]['events']) == 2)
for path in ('/.git/config','/app/server.py','/qa/api.py','/../README.md','/%2e%2e/README.md','/unknown','/wizard-calendar/../README.md'):
    check('static deny ' + path, request(path)[0] == 404)
_, mcp = request('/mcp', {'jsonrpc':'2.0','id':1,'method':'initialize','params':{}})
check('MCP initialize', mcp['result']['serverInfo']['name'] == 'wizard-calendar')
_, mcp = request('/mcp', {'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'calendar_events','arguments':{}}})
check('MCP events readback', len(json.loads(mcp['result']['content'][0]['text'])['events']) == 2)
_, mcp = request('/mcp', {'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'sync_status','arguments':{}}})
check('MCP sync status readback', json.loads(mcp['result']['content'][0]['text'])['state'] == 'not_linked')
check('manual snapshot source labelled', request('/api/export')[1]['source'] == 'manual_import')
# Real HTTP preferences endpoint; optional import never replaces events or timestamps.
_, before_prefs = request('/api/export')
prefs = {'calendars': [{'id': 'fixture', 'color': '#123ABC'}, {'id': 'unknown', 'color': '#abcdef'}], 'hidden': ['fixture'], 'account': 'ignored'}
check('preferences rejects cross-origin', request('/api/preferences/import', prefs, {'Origin': 'https://untrusted.invalid'})[0] == 403)
status, result = request('/api/preferences/import', prefs)
check('preferences reports matched and unmatched', status == 200 and result['matched'] == 1 and result['unmatched'] == ['unknown'])
_, after_prefs = request('/api/export')
check('preferences colors and hidden read back', after_prefs['calendars'][0]['color'] == '#123ABC' and after_prefs['hidden'] == ['fixture'])
check('preferences preserves events and timestamp', after_prefs['events'] == before_prefs['events'] and after_prefs['syncedAt'] == before_prefs['syncedAt'])
check('preferences drops legacy account field', 'account' not in after_prefs)
bad = copy.deepcopy(prefs); bad['calendars'][1]['color'] = 'red'
check('preferences rejects invalid atomically', request('/api/preferences/import', bad)[0] == 400 and request('/api/export')[1] == after_prefs)
check('preferences repeat is idempotent', request('/api/preferences/import', prefs)[0] == 200 and request('/api/export')[1] == after_prefs)
print(json.dumps({'ok': True, 'checks': results, 'count': len(results), 'contentSha256': first['contentSha256']}, indent=2))
