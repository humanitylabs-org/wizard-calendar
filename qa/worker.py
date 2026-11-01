#!/usr/bin/env python3
"""Worker admission guard tests. No Docker/build/browser execution."""
import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('calendar_alpha_runner',ROOT/'tools/alpha_runner.py')
runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)


class WorkerAdmissionTests(unittest.TestCase):
    def test_host_arch_mismatch_refused_before_external_command(self):
        with patch.dict(os.environ,{'ARCH':'amd64'}),patch.object(runner.platform,'machine',return_value='arm64'),patch.object(runner.subprocess,'check_output') as command:
            with self.assertRaisesRegex(SystemExit,'Worker architecture'):runner.main()
            command.assert_not_called()

    def test_source_drift_refused_before_tests_or_build(self):
        with patch.dict(os.environ,{'ARCH':'amd64','SOURCE_REVISION':'a'*40}),patch.object(runner.platform,'machine',return_value='x86_64'),patch.object(runner.subprocess,'check_output',return_value='b'*40),patch.object(runner.subprocess,'run') as command:
            with self.assertRaisesRegex(SystemExit,'source revision'):runner.main()
            command.assert_not_called()


if __name__=='__main__':unittest.main(verbosity=2)
