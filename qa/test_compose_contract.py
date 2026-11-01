"""Offline regressions for the real Compose provider definition, no Docker."""
import ast
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
TREE = ast.parse((ROOT / 'qa/thales_sync.py').read_text())


def load(*names, **namespace):
    nodes = [n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert len(nodes) == len(names)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(ROOT / 'qa/thales_sync.py'), 'exec'), namespace)
    return namespace


class ComposeContract(unittest.TestCase):
    def test_explicit_provider_port_beats_actual_image_default(self):
        # Read the real Dockerfile and execute the exact Compose-definition helper.
        default = re.search(r'\bPORT=(\d+)', (ROOT / 'app/Dockerfile').read_text()).group(1)
        self.assertEqual(default, '8799')
        service = load('fake_provider_service')['fake_provider_service']('exact-image', 32123)
        merged = {'PORT': default, **service['environment']}
        self.assertEqual(merged['PORT'], '8800')
        self.assertEqual(service['ports'], ['127.0.0.1:32123:8800'])
        self.assertEqual(service['volumes'], ['source:/app:ro'])
        self.assertTrue(service['read_only'])
        self.assertEqual(service['healthcheck'], {'disable': True})
        self.assertEqual(service['user'], '1000:1000')
        # Ensure compose_tests actually consumes this definition, not a dead helper.
        calls = [n for n in ast.walk(TREE) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'fake_provider_service']
        self.assertEqual(len(calls), 1)

    def test_diagnostic_projection_never_copies_environment_or_api_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            process = Mock()
            process.check_output.return_value = 'owned-cid\n'
            process.run.return_value = Mock(stdout='public synthetic test stderr')
            info = {'Config': {'Env': ['SECRET_SENTINEL'], 'Labels': {'com.docker.compose.service': 'fake-connectors'}},
                    'State': {'Status': 'running', 'Running': True, 'ExitCode': 0, 'OOMKilled': False, 'Health': {'Log': 'SECRET_SENTINEL'}},
                    'Mounts': [{'Destination': '/app', 'RW': False}]}
            ns = load('compose_diagnostics', json=json, subprocess=process, ENV={}, OUT=Path(tmp),
                      request=lambda *args: (200, {'state': 'ok', 'syncing': False, 'private': 'SECRET_SENTINEL'} if args[1] == '/api/sync' else []),
                      inspect_container=lambda cid: info)
            ns['compose_diagnostics'](['docker', 'compose'], 'synthetic-base', 'synthetic-provider')
            result = (Path(tmp) / 'compose-diagnostics.json').read_text()
            self.assertNotIn('SECRET_SENTINEL', result)
            self.assertNotIn('Env', result)
            self.assertEqual(json.loads(result)['api']['calendar']['state'], 'ok')
            self.assertEqual(json.loads(result)['containers'][0]['mounts'], [{'target': '/app', 'read_only': True}])

    def test_runtime_port_and_source_modes_are_asserted_without_env_dump(self):
        source = ast.get_source_segment((ROOT / 'qa/thales_sync.py').read_text(), next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == 'compose_tests'))
        for assertion in ("os.environ['PORT']=='8800'", "os.environ['PORT']=='8799'", 'info.mode = 0o644', "grant('synthetic-wrong-grant')", "['state'] == 'needs_permission'"):
            self.assertIn(assertion, source)
        self.assertNotIn("run(['docker', 'inspect', cid])", source)


if __name__ == '__main__': unittest.main(verbosity=2)
