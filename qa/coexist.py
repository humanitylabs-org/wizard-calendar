#!/usr/bin/env python3
"""Regression: private Google iCal subscriptions and Connected accounts sync coexist.

Both write the same snapshot. Each must leave the other's calendars, events, errors and
bookkeeping alone, through the module API and through the real HTTP handler. Synthetic
provider and feeds only; never contacts Google.
"""
import datetime as dt
import http.client
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch

import fake_connectors as fake

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
os.environ.setdefault('ICAL_SYNC_INTERVAL', '0')
spec = importlib.util.spec_from_file_location('calendar_server_coexist', ROOT / 'app/server.py')
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)

URL = 'https://calendar.google.com/calendar/ical/synthetic%40group.calendar.google.com/opaque-private-value/basic.ics'
TOMORROW = dt.datetime.now(dt.timezone.utc).date() + dt.timedelta(days=1)


def feed(title, uid='coexist-one'):
    return (f'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Wizard QA//EN\r\nBEGIN:VEVENT\r\nUID:{uid}\r\n'
            f'DTSTART;VALUE=DATE:{TOMORROW:%Y%m%d}\r\nDTEND;VALUE=DATE:{TOMORROW + dt.timedelta(days=1):%Y%m%d}\r\n'
            f'SUMMARY:{title}\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n').encode()


class CoexistTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.provider = ThreadingHTTPServer(('127.0.0.1', 0), fake.Handler)
        threading.Thread(target=cls.provider.serve_forever, daemon=True).start()
        cls.base = 'http://127.0.0.1:' + str(cls.provider.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.provider.shutdown(); cls.provider.server_close()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, {'WIZARD_GRANTS_FILE': self.temp.name + '/grants.json', 'CONNECTORS_URL': 'http://invalid.invalid'})
        env.start(); self.addCleanup(env.stop)
        data = patch.object(m, 'DATA', Path(self.temp.name) / 'data'); data.start(); self.addCleanup(data.stop)
        m.STATE.update(state='not_linked', last_success=None, last_error=None, accounts=[], calendar_errors={}, syncing=False)
        fake.MODE = 'ok'; fake.CALLS.clear()

    def grant(self):
        Path(os.environ['WIZARD_GRANTS_FILE']).write_text(json.dumps({'outgoing': {'connected-accounts': fake.KEY},
            'provider_endpoints': {'connected-accounts': self.base}, 'incoming': [], 'enforce': True}))

    def connected_sync(self, mode='ok'):
        fake.MODE = mode; m.sync_once(); return m.sync_status()

    def add_ical(self, title='Private event'):
        return m.add_ical_source('Personal iCal', URL, fetcher=lambda _u: feed(title), now='2026-11-07T10:00:00+00:00')

    def titles(self):
        return sorted(e['title'] for e in m.view()['events'])

    def test_connected_sync_keeps_ical_calendar_and_events(self):
        source = self.add_ical()
        self.grant(); self.assertEqual(self.connected_sync()['state'], 'ok')
        doc = m.read(); ids = {c['id'] for c in doc['calendars']}
        self.assertIn(source['id'], ids)
        self.assertEqual(len(ids), 3)  # two Connected accounts calendars + the iCal calendar
        self.assertIn('Private event', self.titles())
        self.assertEqual(sum(t == 'Shared meeting' for t in self.titles()), 1)  # Connected dedupe still applies
        view = m.view()
        self.assertEqual(view['mode'], 'connected_accounts')
        self.assertEqual([s['id'] for s in view['connected']], [source['id']])
        self.assertEqual(doc['source'], 'connected_accounts')
        self.assertNotIn('opaque-private-value', json.dumps(view))
        before = m.read()['events']
        self.connected_sync()  # a second Connected sync must not duplicate or drop the iCal rows
        self.assertEqual(sorted(e['id'] for e in m.read()['events']), sorted(e['id'] for e in before))

    def test_ical_refresh_keeps_connected_data_and_bookkeeping(self):
        self.add_ical('Private event'); self.grant(); self.connected_sync()
        before = m.read()
        self.assertEqual(m.sync_ical_sources(fetcher=lambda _u: feed('Renamed event'))['synced'], 1)
        after = m.read()
        self.assertIn('Renamed event', self.titles()); self.assertNotIn('Private event', self.titles())
        for key in ('source', 'calendarEvents', 'calendarErrors', 'syncLastSuccess'):
            self.assertEqual(before[key], after[key], key)
        self.assertEqual(sum(t == 'Shared meeting' for t in self.titles()), 1)
        self.assertEqual(m.view()['mode'], 'connected_accounts')

    def test_add_and_remove_ical_after_connected_sync(self):
        self.grant(); self.connected_sync()
        connected = sorted(e['id'] for e in m.read()['events'])
        source = self.add_ical()
        self.assertTrue(set(connected) < {e['id'] for e in m.read()['events']})
        self.assertEqual(m.read()['source'], 'connected_accounts')
        m.remove_ical_source(source['id'])
        self.assertEqual(sorted(e['id'] for e in m.read()['events']), connected)
        self.assertEqual(m.read()['source'], 'connected_accounts')
        self.assertEqual(m.view()['connected'], [])

    def test_failed_connected_sync_keeps_ical_events_visible(self):
        self.add_ical(); self.grant(); self.connected_sync()
        status = self.connected_sync('partial')  # beta fails; alpha refreshes; last-good retained
        self.assertEqual(status['state'], 'error')
        self.assertIn('Private event', self.titles())
        self.assertTrue(m.view()['errors'])

    def test_hidden_state_and_failed_ical_error_are_independent(self):
        source = self.add_ical(); self.grant(); self.connected_sync()
        doc = m.read(); doc['hidden'] = [source['id']]
        with m.LOCK: m.save(doc)
        self.assertNotIn('Private event', self.titles())
        self.assertEqual(m.read()['source'], 'connected_accounts')
        self.assertEqual(len(m.read()['calendars']), 3)
        m.sync_ical_sources(fetcher=lambda _u: (_ for _ in ()).throw(ValueError('synthetic feed failure')))
        view = m.view()
        self.assertIn('synthetic feed failure', view['errors'])
        self.assertEqual(view['connected'][0]['error'], 'synthetic feed failure')
        self.assertEqual(view['sync']['state'], 'ok')  # an iCal failure is not a Connected accounts failure
        self.assertEqual(sum(t == 'Shared meeting' for t in self.titles()), 1)

    def test_http_sync_refreshes_ical_and_queues_connected(self):
        self.add_ical(); self.grant()
        # Fresh feed via the real HTTP route; the fetcher is replaced for this test only.
        with patch.object(m.ical_feed, 'fetch_google_ical', lambda _u: feed('HTTP refreshed')), \
                patch.object(m, 'request_sync', lambda: (m.set_state(syncing=False), m.sync_status())[1]):
            httpd = ThreadingHTTPServer(('127.0.0.1', 0), m.Handler)
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            self.addCleanup(httpd.server_close); self.addCleanup(httpd.shutdown)
            port = httpd.server_address[1]; host = f'127.0.0.1:{port}'
            with patch.object(m, 'HOSTS', {host}), patch.object(m, 'ORIGINS', {f'http://{host}'}):
                def call(method, path, body=None):
                    c = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
                    raw = json.dumps(body).encode() if body is not None else None
                    c.request(method, path, body=raw, headers={'Host': host, **({'Content-Type': 'application/json'} if raw else {})})
                    r = c.getresponse(); out = json.loads(r.read()); c.close(); return r.status, out
                status, result = call('POST', '/api/sync', {})
                self.assertEqual(status, 202)  # Connected accounts is linked, so its refresh is asynchronous
                self.assertEqual(result['synced'], 1)
                self.assertIn('state', result)
                status, events = call('GET', '/api/events')
                self.assertEqual(status, 200)
                self.assertIn('HTTP refreshed', [e['title'] for e in events['events']])
                self.assertIn('sync', events)
                # Only iCal links, no grant: the refresh is complete when the reply returns.
                Path(os.environ['WIZARD_GRANTS_FILE']).unlink()
                status, result = call('POST', '/api/sync', {})
                self.assertEqual((status, result['synced'], result['syncing']), (200, 1, False))


if __name__ == '__main__':
    unittest.main(verbosity=2)
