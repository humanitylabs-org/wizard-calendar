#!/usr/bin/env python3
"""Owner switch list QA (wizard.app-switches/1): the list has only live switches, and a removed switch's saved value
(reply-on-event, dropped in issue 35) is ignored and dropped from DATA/switches.json without touching the others.

python3 qa/switches.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
data = Path(tempfile.mkdtemp(prefix='cal-switches-'))
os.environ['DATA_DIR'] = str(data)
os.environ.setdefault('CALENDAR_LIVE', 'off')
sys.path.insert(0, str(ROOT / 'app'))
import server  # noqa: E402

checks = []
ids = [s['id'] for s in server.SWITCHES]
assert 'reply-on-event' not in ids, ids
assert all(s['default'] is False and s['issues'] for s in server.SWITCHES)
checks.append('switch list has no reply-on-event; every switch off by default with its issue')

(data / 'switches.json').write_text(json.dumps({'reply-on-event': True, 'compact-header': True, 'trackpad-swipe': 'yes'}))
doc = server.switches_doc()
assert [s['id'] for s in doc['switches']] == ids
assert {s['id']: s['on'] for s in doc['switches']}['compact-header'] is True
checks.append('a saved reply-on-event value is ignored; other saved switches keep their state')

server.prune_switches()
assert json.loads((data / 'switches.json').read_text()) == {'compact-header': True}
server.prune_switches()  # idempotent
server.set_switch('drag-events', True)
assert json.loads((data / 'switches.json').read_text()) == {'compact-header': True, 'drag-events': True}
checks.append('start-up prune drops the removed value from switches.json; later changes keep it out')

(data / 'switches.json').write_text('not json')
server.prune_switches()
assert (data / 'switches.json').read_text() == 'not json'
assert all(s['on'] is False for s in server.switches_doc()['switches'])
checks.append('unreadable switches.json is left alone and reads as all off')

print(json.dumps({'ok': True, 'count': len(checks), 'checks': checks}, indent=2))
