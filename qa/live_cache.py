#!/usr/bin/env python3
"""Synthetic, in-memory Live cache regressions and a non-owner GET boundary probe.

No sockets, server processes, grants files, provider calls or owner data. The existing
qa/live.py is HTTP integration QA and is deliberately not imported or run here.
"""
import ast
import copy
from email.message import Message
from http.server import BaseHTTPRequestHandler
from pathlib import Path
import sys
import unittest
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import live

START, END = '2026-11-01', '2026-12-01'


class MemorySource(live.Source):
    def __init__(self, sid):
        self.id = sid
        self.level: str | None = 'suggest_only'
        self.calls = []

    def call(self, method, path, body=None, caller=None):
        self.calls.append((path, caller))
        if path == '/v1/status':
            value: dict = {'accounts': [{'email': f'{self.id}@example.com',
                                   'services': ['calendar'], 'status': 'active'}]}
            if self.level is not None:
                value['calendar_access'] = {'level': self.level, 'label': self.level}
            return value
        if path == '/v1/calendar_list_events':
            if self.level == 'no_access' and caller != live.OWNER:
                raise live.LiveError(403, 'agent_access_denied', 'No access')
            return {'events': [{'id': 'synthetic-event', 'title': 'Synthetic live event',
                                'start': {'date_time': '2026-11-02T23:00:00Z'},
                                'end': {'date_time': '2026-11-03T00:00:00Z'}}]}
        raise AssertionError(f'Unexpected source call: {path}')

    def list_count(self):
        return sum(path == '/v1/calendar_list_events' for path, _ in self.calls)


class LiveCacheTests(unittest.TestCase):
    def make_live(self, sid='google'):
        source = MemorySource(sid)
        client = live.Live({sid: source}, clock=lambda: 1000)
        self.addCleanup(client.pool.shutdown, wait=True)
        return client, source

    def test_status_projects_existing_calendar_access_shape(self):
        client, _ = self.make_live()
        status = client.status('agent:helper')
        self.assertEqual(status['sources'][0]['agent_access'],
                         {'level': 'suggest_only', 'label': 'suggest_only'})
        self.assertNotIn('calendar_access', status['sources'][0])

    def test_same_caller_and_accounts_recheck_on_reduction_and_restoration(self):
        for sid in ('google', 'microsoft'):
            for caller in ('agent:helper', None):
                with self.subTest(source=sid, caller=caller):
                    client, source = self.make_live(sid)
                    allowed = client.window(START, END, caller)
                    self.assertEqual(len(allowed['events']), 1)
                    self.assertIs(client.window(START, END, caller), allowed)
                    self.assertEqual(source.list_count(), 1)
                    source.level = 'no_access'
                    denied = client.window(START, END, caller)
                    self.assertEqual(denied['events'], [], 'permission reduction must not return cached events')
                    self.assertEqual(denied['errors'][0]['code'], 'agent_access_denied')
                    self.assertEqual(denied['status']['sources'][0]['agent_access']['level'], 'no_access')
                    self.assertEqual(source.list_count(), 2)
                    self.assertEqual(denied['calendars'], allowed['calendars'])
                    self.assertIs(client.window(START, END, caller), denied)
                    source.level = 'suggest_only'
                    restored = client.window(START, END, caller)
                    self.assertEqual(len(restored['events']), 1)
                    self.assertEqual(restored['status']['sources'][0]['agent_access']['level'], 'suggest_only')

    def test_owner_and_agents_stay_separate_when_access_changes(self):
        client, source = self.make_live()
        owner = client.window(START, END, live.OWNER)
        helper = client.window(START, END, 'agent:helper')
        other = client.window(START, END, 'agent:other')
        self.assertIsNot(owner, helper)
        self.assertIsNot(helper, other)
        self.assertEqual(source.list_count(), 3)
        source.level = 'no_access'
        current_owner = client.window(START, END, live.OWNER)
        self.assertIsNot(current_owner, owner)
        self.assertEqual(len(current_owner['events']), 1, 'agent reduction must not strip owner reads')
        self.assertEqual(current_owner['status']['sources'][0]['agent_access']['level'], 'no_access')
        self.assertEqual(client.window(START, END, 'agent:helper')['events'], [])
        self.assertEqual(client.window(START, END, 'agent:other')['events'], [])
        self.assertEqual(source.list_count(), 6)

    def test_missing_access_metadata_does_not_reuse_known_level_cache(self):
        client, source = self.make_live()
        before = client.window(START, END, 'agent:helper')
        source.level = None
        after = client.window(START, END, 'agent:helper')
        self.assertIsNot(after, before)
        self.assertIsNone(after['status']['sources'][0]['agent_access'])
        self.assertEqual(source.list_count(), 2)


class EventsBoundaryTests(unittest.TestCase):
    def test_non_owner_get_returns_snapshot_while_mcp_refuses_no_access(self):
        # Characterize a remaining hold, not a claim that this is a safe policy.
        # Compile the real handler/view without importing server module globals:
        # no environment-derived paths, source clients or storage are initialized.
        tree = ast.parse((ROOT / 'app/server.py').read_text())
        selected = [node for node in tree.body
                    if isinstance(node, (ast.FunctionDef, ast.ClassDef))
                    and node.name in ('view', 'Handler')]
        self.assertEqual(len(selected), 2)
        source = MemorySource('google')
        source.level = 'no_access'
        client = live.Live({'google': source}, clock=lambda: 1000)
        self.addCleanup(client.pool.shutdown, wait=True)
        snapshot = {'schemaVersion': 1, 'timezone': 'UTC',
                    'calendars': [{'id': 'synthetic-snapshot', 'name': 'Synthetic snapshot'}],
                    'events': [{'id': 'synthetic-private-event', 'cal': 'synthetic-snapshot',
                                'title': 'Synthetic snapshot event'}]}
        namespace = {'BaseHTTPRequestHandler': BaseHTTPRequestHandler, 'urlsplit': urlsplit,
                     'live': live, 'LIVE': client, 'TZ': 'UTC',
                     'read': lambda: copy.deepcopy(snapshot), 'ical_sources_public': lambda: [],
                     '_live_range': lambda *args: (START, END),
                     'SYNC_STATE': {'syncing': False, 'lastError': ''},
                     'HOSTS': {'127.0.0.1:8799'}, 'LOCAL_HOSTS': {'127.0.0.1:8799'},
                     'ORIGINS': {'http://127.0.0.1:8799'}, 'DEV_MODE': False,
                     'SHELL_AUTH': 'tailscale-serve', 'OWNER_LOGINS': set()}
        import json
        namespace['json'] = json
        exec(compile(ast.Module(body=selected, type_ignores=[]), str(ROOT / 'app/server.py'), 'exec'), namespace)
        handler = object.__new__(namespace['Handler'])
        handler.headers = Message()
        handler.headers['Host'] = '127.0.0.1:8799'
        handler.headers['X-Wizard-Agent'] = 'helper'
        handler.path = f'/api/events?from={START}&to={END}'
        replies = []
        handler.respond = lambda value, status=200, **kwargs: replies.append((status, value))
        self.assertTrue(handler.trusted())
        self.assertFalse(handler.owner())
        handler.do_GET()
        status, value = replies.pop()
        self.assertEqual(status, 200)
        self.assertEqual(value['agentAccess'][0]['level'], 'no_access')
        self.assertEqual([event['id'] for event in value['events']], ['synthetic-private-event'])
        self.assertEqual(value['suggestions'], [])
        self.assertTrue(all(caller != live.OWNER for _, caller in source.calls))
        handler.mcp({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                     'params': {'name': 'calendar_events'}})
        _, response = replies.pop()
        self.assertTrue(response['result']['isError'])
        self.assertEqual(json.loads(response['result']['content'][0]['text'])['error']['code'],
                         'agent_access_denied')


if __name__ == '__main__':
    unittest.main(verbosity=2)
