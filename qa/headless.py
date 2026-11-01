#!/usr/bin/env python3
"""Fast stdlib QA in disposable local directories; no Docker or browser."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]

def run(*args):
    subprocess.run([sys.executable, *args], cwd=ROOT, check=True)

for test in ('qa/package.py', 'qa/data_init.py', 'qa/worker.py', 'qa/sync.py', 'qa/connector.py', 'tools/check_view.py'):
    run(test)
with tempfile.TemporaryDirectory(prefix='calendar-headless-') as tmp:
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    base = f'http://127.0.0.1:{port}'
    env = dict(os.environ, BIND='127.0.0.1', PORT=str(port), DATA_DIR=tmp,
               WIZARD_GRANTS_FILE=tmp + '/missing-grants.json', CONNECTORS_URL='',
               WIZARD_TRUSTED_HOSTS='', WIZARD_TRUSTED_ORIGINS='',
               WIZARD_LOCAL_HOSTS='', CALENDAR_TIMEZONE='', CALENDAR_SYNC_MINUTES='10')
    with (Path(tmp) / 'server.log').open('w') as log:
        proc = subprocess.Popen([sys.executable, 'app/server.py'], cwd=ROOT, env=env, stdout=log, stderr=log)
        try:
            for _ in range(100):
                if proc.poll() is not None:
                    raise RuntimeError('Disposable server exited: ' + (Path(tmp) / 'server.log').read_text())
                try:
                    with urllib.request.urlopen(base + '/healthz', timeout=1) as response:
                        if response.status == 200:
                            break
                except OSError:
                    time.sleep(.05)
            else:
                raise RuntimeError('Disposable server never became ready')
            run('qa/api.py', '--url', base)
            # Same-host defaults work without knowing the owner's box in advance.
            for origin in (base, base.replace('http:', 'https:')):
                req = urllib.request.Request(base + '/wizard-calendar/api/events', headers={'Origin': origin})
                with urllib.request.urlopen(req, timeout=2) as response:
                    assert response.status == 200
            print('PASS API HTTP suite and same-host HTTP/HTTPS origin defaults')
        finally:
            proc.terminate()
            proc.wait(timeout=10)
print('PASS all headless QA (no Docker, browser, live data or credentials)')
