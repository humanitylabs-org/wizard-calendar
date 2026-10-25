#!/usr/bin/env python3
"""Stdlib integration tests: real HTTP provider + real atomic Calendar snapshots."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer
import fake_connectors as fake

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('calendar_server', ROOT / 'app/server.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class SyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.provider = ThreadingHTTPServer(('127.0.0.1', 0), fake.Handler)
        threading.Thread(target=cls.provider.serve_forever, daemon=True).start()
        cls.base = 'http://127.0.0.1:' + str(cls.provider.server_port)

    @classmethod
    def tearDownClass(cls): cls.provider.shutdown(); cls.provider.server_close()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {'WIZARD_GRANTS_FILE': self.temp.name + '/grants.json', 'CONNECTORS_URL': 'http://invalid.invalid'})
        self.env.start(); self.addCleanup(self.env.stop)
        self.data = patch.object(m, 'DATA', Path(self.temp.name) / 'data')
        self.data.start(); self.addCleanup(self.data.stop)
        m.STATE.update(state='not_linked', last_success=None, last_error=None, accounts=[], calendar_errors={}, syncing=False)
        fake.MODE = 'ok'; fake.CALLS.clear()

    def grant(self, key=fake.KEY, slot=False):
        Path(os.environ['WIZARD_GRANTS_FILE']).write_text(json.dumps({'outgoing': {'slot:calendar-source' if slot else 'wizard-connectors': key}, 'provider_endpoints': {'wizard-connectors': self.base}, 'incoming': [], 'enforce': True}))

    def sync(self, mode='ok'):
        fake.MODE = mode; m.sync_once(); return m.sync_status()

    def test_owner_timezone_contract_and_browser_fallback(self):
        field = next(f for f in json.loads((ROOT / 'runtipi/config.json').read_text())['form_fields'] if f['env_variable'] == 'CALENDAR_TIMEZONE')
        self.assertFalse(field['required'])
        with patch.object(m, 'DISPLAY_TZ', None):
            self.assertIsNone(m.view()['display_timezone'])
        with patch.object(m, 'DISPLAY_TZ', 'Asia/Bangkok'):
            self.assertEqual(m.view()['display_timezone'], 'Asia/Bangkok')

    def test_not_linked(self):
        self.assertEqual(self.sync()['state'], 'not_linked')
        self.assertEqual(fake.CALLS, [])
        Path(os.environ['WIZARD_GRANTS_FILE']).write_text('{}')
        self.assertEqual(self.sync()['state'], 'not_linked')

    def test_standard_grants_endpoint_precedence_and_fallback(self):
        self.grant()
        self.assertEqual(m.provider_link(), (self.base, fake.KEY))
        grants = Path(os.environ['WIZARD_GRANTS_FILE'])
        body = json.loads(grants.read_text()); body['provider_endpoints'] = {}
        grants.write_text(json.dumps(body))
        with patch.dict(os.environ, {'CONNECTORS_URL': self.base}):
            self.assertEqual(m.provider_link(), (self.base, fake.KEY))
        for invalid in ('[]', '{bad', '{"outgoing": []}', '{"outgoing": {"wizard-connectors":"key"}, "provider_endpoints": []}'):
            grants.write_text(invalid)
            self.assertIsNone(m.provider_link())

    def test_legacy_preferences_map_provider_ids_and_survive_sync(self):
        self.grant(); self.sync()
        before = m.read(); cal = before['calendars'][0]
        payload = {'calendars': [{'id': cal['provider_id'], 'name': 'ignored', 'color': '#123ABC'}, {'id': 'unknown', 'color': '#abcdef'}],
                   'hidden': [cal['provider_id']], 'account': 'ignored', 'accounts': ['ignored']}
        with m.LOCK: result = m.import_preferences(payload)
        self.assertEqual(result['matched'], 2); self.assertEqual(result['unmatched'], ['unknown'])
        after = m.read()
        self.assertEqual(after['events'], before['events']); self.assertEqual(after['syncedAt'], before['syncedAt'])
        self.assertEqual(after['hidden'], sorted(c['id'] for c in before['calendars'])); self.assertTrue(all(c['color'] == '#123ABC' for c in after['calendars']))
        self.assertNotIn('accounts', after)
        self.sync('recolor'); self.assertEqual(m.read()['hidden'], after['hidden'])
        self.assertEqual(m.read()['calendars'][0]['color'], '#123ABC')
        with m.LOCK: m.import_preferences(payload)
        self.assertEqual(m.read()['events'], before['events'])

    def test_legacy_preferences_fail_atomically_and_preserve_unmatched(self):
        self.grant(); self.sync(); before = (m.DATA / 'snapshot.json').read_bytes()
        cal = m.read()['calendars'][0]
        for body in ({'calendars': [{'id': cal['provider_id'], 'color': '#123456'}, {'id': 'bad', 'color': 'red'}], 'hidden': []},
                     {'calendars': [], 'hidden': [cal['provider_id']]},
                     {'calendars': [{'id': 'a'}, {'id': 'a'}], 'hidden': []}):
            with self.assertRaises(ValueError), m.LOCK: m.import_preferences(body)
            self.assertEqual((m.DATA / 'snapshot.json').read_bytes(), before)
        with m.LOCK: result = m.import_preferences({'calendars': [{'id': 'unmatched'}], 'hidden': []})
        self.assertEqual(result['matched'], 0); self.assertEqual(result['unmatched'], ['unmatched'])
        self.assertEqual((m.DATA / 'snapshot.json').read_bytes(), before)

    def test_preferences_exact_local_id_and_other_hidden_preserved(self):
        self.grant(); self.sync(); doc = m.read(); a,b = doc['calendars']
        doc['hidden'] = [a['id'], b['id']]
        with m.LOCK:
            m.save(doc)
            m.import_preferences({'calendars': [{'id': a['id'], 'color': '#111111'}], 'hidden': []})
        self.assertEqual(m.read()['hidden'], [b['id']])
        self.assertEqual(m.read()['calendars'][0]['color'], '#111111')

    def test_wrong_key(self):
        self.grant('wrong'); self.assertEqual(self.sync()['state'], 'needs_permission')
        self.assertFalse(fake.CALLS[0]['grant_valid'])
        self.assertEqual(m.read()['events'], [])

    def test_setup_states(self):
        self.grant()
        for mode, state in [('no_client', 'needs_google_app'), ('configuration_error', 'needs_google_app'), ('no_accounts', 'needs_account'), ('denied', 'needs_permission')]:
            self.assertEqual(self.sync(mode)['state'], state)

    def test_happy_multi_account_dedupe_and_header(self):
        self.grant(slot=True); status = self.sync()
        self.assertEqual(status['state'], 'ok'); self.assertEqual(len(status['accounts']), 2)
        self.assertEqual(len(m.read()['calendars']), 2); self.assertEqual(len(m.read()['events']), 3)
        self.assertTrue(all(c['grant_valid'] for c in fake.CALLS))
        self.assertEqual(len(fake.CALLS), 4)
        self.assertEqual(m.read()['source'], 'connected_accounts')
        self.assertIsNotNone(status['last_success'])

    def test_prefs_preserved_and_digest_idempotent(self):
        self.grant(); self.sync(); first = m.read()
        with m.LOCK:
            first['hidden'] = [first['calendars'][0]['id']]; m.save(first)
        self.sync('recolor'); after = m.read()
        self.assertEqual(first['hidden'], after['hidden'])
        self.assertEqual(first['calendars'], after['calendars'])
        self.assertEqual(first['contentSha256'], after['contentSha256'])
        self.assertEqual(first['syncedAt'], after['syncedAt'])

    def test_partial_retains_last_good(self):
        self.grant(); self.sync(); before = m.read()
        status = self.sync('partial'); after = m.read()
        self.assertEqual(status['state'], 'error'); self.assertEqual(len(status['calendar_errors']), 1)
        beta = next(c['id'] for c in before['calendars'] if c['account'] == 'beta')
        self.assertEqual(before['calendarEvents'][beta], after['calendarEvents'][beta])
        self.assertTrue(any(e['title'] == 'alpha refreshed' for e in after['events']))
        self.assertEqual(before['syncLastSuccess'], after['syncLastSuccess'])

    def test_invalid_rejected_without_corruption(self):
        self.grant(); self.sync(); before = (m.DATA / 'snapshot.json').read_bytes()
        for mode in ('invalid', 'unsafe'):
            self.assertEqual(self.sync(mode)['state'], 'error')
            self.assertEqual(before, (m.DATA / 'snapshot.json').read_bytes())

    def test_truncated_retains_good(self):
        self.grant(); self.sync(); before = m.read()
        self.assertEqual(self.sync('truncated')['state'], 'error')
        self.assertEqual(before['events'], m.read()['events'])

    def test_hidden_duplicate_uses_visible_copy(self):
        self.grant(); self.sync(); doc = m.read()
        shared = next(e for e in doc['events'] if e['title'] == 'Shared meeting')
        doc['hidden'] = [shared['cal']]
        with m.LOCK: m.save(doc)
        visible = m.view()['events']
        self.assertTrue(any(e['title'] == 'Shared meeting' for e in visible))
        self.assertTrue(all(e['cal'] not in doc['hidden'] for e in visible))

    def test_grant_rotation_and_revocation(self):
        self.grant(); self.assertEqual(self.sync()['state'], 'ok')
        self.grant('rotated-wrong'); self.assertEqual(self.sync()['state'], 'needs_permission')
        Path(os.environ['WIZARD_GRANTS_FILE']).unlink()
        calls = len(fake.CALLS)
        self.assertEqual(self.sync()['state'], 'not_linked')
        self.assertEqual(len(fake.CALLS), calls)
        self.assertEqual(len(m.read()['events']), 3)

    def test_offset_dedupe(self):
        row = {'id': 'a', 'cal': 'a', 'title': ' Meeting ', 'start': '2026-10-15T10:00:00Z', 'end': '2026-10-15T11:00:00Z', 'allDay': False}
        other = dict(row, id='b', cal='b', title='meeting', start='2026-10-15T12:00:00+02:00', end='2026-10-15T13:00:00+02:00')
        self.assertEqual(len(m.dedupe([row, other])), 1)
        self.assertEqual(len(m.dedupe([row, dict(other, end='2026-10-15T14:00:00+02:00')])), 2)


if __name__ == '__main__': unittest.main(verbosity=2)
