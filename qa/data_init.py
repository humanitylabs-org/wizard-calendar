#!/usr/bin/env python3
"""Mocked permission-init boundary; never open or mutate a host /data."""
import os
from pathlib import Path
import runpy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'app/prepare_data.py'


class DataInitTests(unittest.TestCase):
    def invoke(self, uid=0, gid=0, mode=0o40755, open_error=None):
        with patch('os.open', return_value=71, side_effect=open_error) as opened, \
             patch('os.fstat', return_value=SimpleNamespace(st_uid=uid, st_gid=gid, st_mode=mode)), \
             patch('os.fchown') as chown, patch('os.close') as close:
            try:
                runpy.run_path(str(SCRIPT), run_name='__main__')
            finally:
                self.opened, self.chown, self.closed = opened, chown, close

    def test_fresh_directory_chowned_once_without_traversal(self):
        self.invoke()
        self.opened.assert_called_once_with('/data', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        self.chown.assert_called_once_with(71, 1000, 1000)
        self.closed.assert_called_once_with(71)

    def test_existing_correct_owner_untouched(self):
        self.invoke(uid=1000, gid=1000)
        self.chown.assert_not_called()
        self.closed.assert_called_once_with(71)

    def test_unwritable_root_fails_and_closes(self):
        with self.assertRaisesRegex(RuntimeError, 'writable'):
            self.invoke(uid=1000, gid=1000, mode=0o40555)
        self.closed.assert_called_once_with(71)

    def test_symlink_open_failure_never_chowns(self):
        with self.assertRaises(OSError):
            self.invoke(open_error=OSError('no symlink following'))
        self.chown.assert_not_called()
        self.closed.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
