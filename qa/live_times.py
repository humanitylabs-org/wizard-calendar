#!/usr/bin/env python3
"""Bounded timestamp regressions; synthetic source, no sockets or provider calls."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import live


class CaptureSource(live.Source):
    def __init__(self, sid):
        self.id, self.calls = sid, []

    def call(self, method, path, body=None, caller=None):
        self.calls.append((method, path, body, caller))
        return {'event': {'id': 'synthetic'}}


class LiveTimesTests(unittest.TestCase):
    def test_minute_precision_gains_seconds_without_changing_zone(self):
        for suffix in ('', 'Z', '+07:00', '-05:30'):
            with self.subTest(suffix=suffix):
                self.assertEqual(live._when('2026-11-05T10:00' + suffix, 'Start'),
                                 '2026-11-05T10:00:00' + suffix)

    def test_existing_seconds_fraction_and_dates_stay_exact(self):
        for value in ('2026-11-05', '2026-11-05T10:00:27',
                      '2026-11-05T10:00:27Z', '2026-11-05T10:00:27.125+07:00'):
            with self.subTest(value=value):
                self.assertEqual(live._when(value, 'Start'), value)

    def test_optional_missing_time_remains_none(self):
        for value in (None, ''):
            self.assertIsNone(live._when(value, 'Start', required=False))

    def test_unsupported_formats_remain_rejected(self):
        for value in (None, '', 123, {}, 'tomorrow', '2026-11-05T10:00+0700'):
            with self.subTest(value=value):
                with self.assertRaises(live.LiveError) as caught:
                    live._when(value, 'Start')
                self.assertEqual(caught.exception.code, 'invalid_time')

    def test_create_forwards_normalized_times_to_both_sources_as_owner(self):
        for sid in ('google', 'microsoft'):
            with self.subTest(source=sid):
                source = CaptureSource(sid)
                client = live.Live({sid: source})
                self.addCleanup(client.pool.shutdown, wait=True)
                result = client.create({'account': f'live:{sid}:person@example.com',
                                        'title': 'Synthetic event', 'start': '2026-11-05T10:00',
                                        'end': '2026-11-05T11:00', 'time_zone': 'Asia/Bangkok'})
                self.assertTrue(result['created'])
                method, path, sent, caller = source.calls[-1]
                self.assertEqual((method, path, caller), ('POST', '/v1/calendar_create_event', live.OWNER))
                self.assertEqual(sent['start'], '2026-11-05T10:00:00')
                self.assertEqual(sent['end'], '2026-11-05T11:00:00')
                self.assertEqual(sent['time_zone'], 'Asia/Bangkok')

    def test_partial_update_preserves_omitted_fields_and_zone(self):
        source = CaptureSource('google')
        client = live.Live({'google': source})
        self.addCleanup(client.pool.shutdown, wait=True)
        client.update({'account': 'live:google:person@example.com', 'id': 'synthetic',
                       'start': '2026-11-05T10:00+07:00'})
        method, path, sent, caller = source.calls[-1]
        self.assertEqual((method, path, caller), ('POST', '/v1/calendar_update_event', live.OWNER))
        self.assertEqual(sent['start'], '2026-11-05T10:00:00+07:00')
        self.assertNotIn('end', sent)
        self.assertNotIn('title', sent)

    def test_all_day_create_remains_date_only(self):
        source = CaptureSource('google')
        client = live.Live({'google': source})
        self.addCleanup(client.pool.shutdown, wait=True)
        client.create({'account': 'live:google:person@example.com', 'title': 'Synthetic all day',
                       'start': '2026-11-05', 'end': '2026-11-06'})
        sent = source.calls[-1][2]
        self.assertEqual((sent['start'], sent['end']), ('2026-11-05', '2026-11-06'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
