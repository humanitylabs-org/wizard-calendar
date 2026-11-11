#!/usr/bin/env python3
"""A disposable Calendar with two fake source apps (qa/live.py's Fake: synthetic Google and Microsoft accounts speaking
wizard.mail-calendar/1) and the owner grant in place, for browser QA. Nothing talks to Google, Microsoft or Composio.

PORT=18930 python3 qa/live_fake.py   (prints "ready <url>" once Calendar answers; Ctrl-C stops everything)
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'qa'))
import live  # noqa: E402  (the fakes)


def main():
    g, m = live.Fake('google', 'me@gmail.com'), live.Fake('microsoft', 'me@outlook.com')
    g.suggestions = m.suggestions = []
    port, data = int(os.environ.get('PORT', '18930')), tempfile.mkdtemp()
    grants = Path(data) / 'grants.json'
    grants.write_text(json.dumps({'outgoing': {'wizard-google': 'grant-google-0123456789', 'wizard-microsoft': 'grant-microsoft-0123456789'}}))
    env = dict(os.environ, PORT=str(port), DATA_DIR=data, ICAL_SYNC_INTERVAL='0', CALENDAR_TIMEZONE='Asia/Bangkok',
               CALENDAR_SOURCES=f'google={g.base},microsoft={m.base}', CALENDAR_DEV_MODE='loopback-single-owner',
               WIZARD_GRANTS_FILE=str(grants))
    proc = subprocess.Popen([sys.executable, str(ROOT / 'app/server.py')], env=env, cwd=ROOT / 'app')
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(f'http://127.0.0.1:{port}/healthz', timeout=1)
                break
            except OSError:
                time.sleep(.1)
        print(f'ready http://127.0.0.1:{port}', flush=True)
        proc.wait()
    except KeyboardInterrupt:
        pass
    finally:
        proc.kill()


if __name__ == '__main__':
    main()
