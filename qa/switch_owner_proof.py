#!/usr/bin/env python3
"""Switch owner check QA (wizard-os#133): with the platform owner-proof key, /api/switches takes only a valid signed
proof. Host, Origin, Tailscale-User-Login and X-Wizard-Switch are client-set, so any process on the box that reaches
Calendar's port could forge them; without a key the Serve-login check stays as it was.

python3 qa/switch_owner_proof.py
"""
import hashlib
import hmac
import http.client
import json
import os
import secrets
import socket
import sys
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
data = Path(tempfile.mkdtemp(prefix='cal-proof-'))
with socket.socket() as s:
    s.bind(('127.0.0.1', 0))
    PORT = s.getsockname()[1]
BOX = 'wizard.example.com'
os.environ.update({'DATA_DIR': str(data), 'CALENDAR_LIVE': 'off', 'PORT': str(PORT), 'WIZARD_TRUSTED_HOSTS': BOX,
                   'WIZARD_TRUSTED_ORIGINS': f'https://{BOX}', 'WIZARD_SHELL_AUTH': 'tailscale-serve'})
for k in ('WIZARD_OWNER_PROOF_KEY_FILE', 'WIZARD_OWNER_PROOF_APP', 'WIZARD_OWNER_LOGINS', 'CALENDAR_DEV_MODE'):
    os.environ.pop(k, None)
sys.path.insert(0, str(ROOT / 'app'))
import server  # noqa: E402

KEY = bytes(range(32))
APP = 'wizard-calendar'
SWITCH = server.SWITCHES[0]['id']
FORGED = {'X-Wizard-Switch': '1', 'Host': BOX, 'Origin': f'https://{BOX}', 'Sec-Fetch-Site': 'same-origin',
          'Tailscale-User-Login': 'owner@example.com'}
httpd = ThreadingHTTPServer(('127.0.0.1', PORT), server.Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
checks = []


def sign(method, target, key=KEY, app=APP, ts=None):
    ts = str(int(time.time()) if ts is None else ts)
    nonce = secrets.token_hex(24)
    msg = '\n'.join(('wizard-app-owner-v1', app, ts, nonce, method, target)).encode()
    return f'{ts}.{nonce}.{hmac.new(key, msg, hashlib.sha256).hexdigest()}'


def call(method, headers, on=None, path='/api/switches'):
    c = http.client.HTTPConnection('127.0.0.1', PORT, timeout=5)
    h = {'Host': f'127.0.0.1:{PORT}', **headers}
    body = json.dumps({'id': SWITCH, 'on': on}).encode() if on is not None else None
    if body is not None:
        h.update({'Content-Type': 'application/json', 'Content-Length': str(len(body))})
    c.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
    for k, v in h.items():
        c.putheader(k, v)
    c.endheaders(body)
    status = c.getresponse().status
    c.close()
    return status


def is_on():
    return server.switch_on(SWITCH) if hasattr(server, 'switch_on') else \
        {s['id']: s['on'] for s in server.switches_doc()['switches']}[SWITCH]


def check(name, ok):
    assert ok, name
    checks.append(name)


def keyed(path):
    os.environ['WIZARD_OWNER_PROOF_KEY_FILE'] = str(path)
    os.environ['WIZARD_OWNER_PROOF_APP'] = APP


check('keyless: the owner login through Serve still reads the switches', call('GET', FORGED) == 200)
check('keyless: a box-local host is still refused', call('GET', {**FORGED, 'Host': f'127.0.0.1:{PORT}'}) == 403)

(data.parent / 'cal-proof-key').write_bytes(KEY)
keyed(data.parent / 'cal-proof-key')
check('keyed: the forgeable headers can no longer read', call('GET', FORGED) == 403)
check('keyed: the forgeable headers can no longer flip', call('POST', FORGED, True) == 403 and not is_on())

h = {'X-Wizard-Switch': '1', 'X-Wizard-App-Owner-Proof': sign('POST', '/api/switches')}
check('keyed: a valid signed proof flips the switch', call('POST', h, True) == 200 and is_on())
check('keyed: the same proof twice is refused (replay)', call('POST', h, False) == 403 and is_on())
g = {'X-Wizard-Switch': '1', 'X-Wizard-App-Owner-Proof': sign('GET', '/wizard-calendar/api/switches')}
check('keyed: a proof for the prefixed path reads it', call('GET', g, path='/wizard-calendar/api/switches') == 200)

for name, proof in (('wrong method', sign('GET', '/api/switches')),
                    ('wrong target', sign('POST', '/other/api/switches')),
                    ('wrong app', sign('POST', '/api/switches', app='wizard-notes')),
                    ('wrong key', sign('POST', '/api/switches', key=bytes(32))),
                    ('stale', sign('POST', '/api/switches', ts=int(time.time()) - 31)),
                    ('garbage', 'not-a-proof')):
    check(f'keyed: {name} proof refused', call('POST', {**FORGED, 'X-Wizard-App-Owner-Proof': proof}, False) == 403)
check('keyed: nothing above changed the switch', is_on())
check('keyed: a proof never rides on a bearer',
      call('GET', {'X-Wizard-Switch': '1', 'Authorization': 'Bearer x',
                   'X-Wizard-App-Owner-Proof': sign('GET', '/api/switches')}) == 403)

keyed(data.parent / 'cal-proof-missing')
check('unreadable key: forged headers refused (no fallback)', call('GET', FORGED) == 403)
check('unreadable key: even a well-formed proof is refused',
      call('GET', {'X-Wizard-Switch': '1', 'X-Wizard-App-Owner-Proof': sign('GET', '/api/switches')}) == 403)

httpd.shutdown()
print(json.dumps({'ok': True, 'count': len(checks), 'checks': checks}, indent=2))
