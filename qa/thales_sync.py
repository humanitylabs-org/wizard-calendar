#!/usr/bin/env python3
"""Disposable Thales acceptance runner. Real recipe + synthetic provider, no owner data.
Run in the durable light lane; Docker context must name an already-running daemon.
"""
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '.runtime/sync-evidence'
OUT.mkdir(parents=True, exist_ok=True)
ENV = dict(os.environ)
ENV['PATH'] = '/opt/homebrew/bin:/usr/local/bin:' + ENV.get('PATH', '')
ENV.setdefault('DOCKER_CONTEXT', 'colima')
ENV['QA_OUT'] = str(OUT)
LOG = []


def run(argv, **kwargs):
    result = subprocess.run(argv, cwd=ROOT, env=ENV, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kwargs)
    print(result.stdout, flush=True)
    LOG.append({'argv': argv, 'returncode': result.returncode, 'output': result.stdout})
    (OUT / 'commands.json').write_text(json.dumps(LOG, indent=2))
    result.check_returncode()
    return result.stdout


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); return sock.getsockname()[1]


def request(base, path, body=None):
    req = urllib.request.Request(base + path, data=None if body is None else json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=5) as response: return response.status, json.load(response)


def until(fn, seconds=90):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            value = fn()
            if value: return value
        except (OSError, ValueError): pass
        time.sleep(.2)
    raise AssertionError('Timed out waiting for disposable QA service')


def server_tests():
    run([sys.executable, 'tools/fetch_core.py'])
    run([sys.executable, 'tools/package_runtime.py', '--check'])
    run([sys.executable, 'tools/check_view.py'])
    run([sys.executable, 'qa/sync.py'])
    run([sys.executable, 'qa/connector.py'])
    run(['npm', 'install', '--prefix', 'qa', '--no-package-lock', '--ignore-scripts', '--no-audit', '--no-fund'])
    with tempfile.TemporaryDirectory(prefix='calendar-qa-', dir=ROOT / '.runtime') as tmp:
        p = port(); base = 'http://127.0.0.1:' + str(p)
        env = dict(ENV, PORT=str(p), DATA_DIR=tmp, WIZARD_CORE_DIR=str(ROOT / '.runtime/core'), WIZARD_GRANTS_FILE=tmp + '/no-grant.json', CALENDAR_TIMEZONE='', CALENDAR_SYNC_MINUTES='10')
        with (OUT / 'server.log').open('w') as log:
            proc = subprocess.Popen([sys.executable, 'app/server.py'], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                until(lambda: request(base, '/healthz')[1]['ok'])
                run([sys.executable, 'qa/api.py', '--url', base])
                ENV['CALENDAR_URL'] = base
                run(['node', 'qa/browser.cjs'])
                run(['node', 'qa/hosted.cjs'])
                ENV['QA_MOBILE'] = '1'
                run(['node', 'qa/hosted.cjs'])
                ENV.pop('QA_MOBILE')
                run(['node', 'qa/setup-card.cjs'])
                # The legacy suites own their synthetic data and select Bangkok in UI.
                run(['node', 'qa.cjs'])
                run(['node', 'qa_geometry.cjs'])
                run(['node', 'qa_views.cjs'])
            finally:
                proc.terminate(); proc.wait(timeout=10)


def compose_tests():
    project = 'calendar-sync-qa-' + str(os.getpid())
    p, fp = port(), port()
    base, fake = 'http://127.0.0.1:' + str(p), 'http://127.0.0.1:' + str(fp)
    recipe = json.loads((ROOT / 'runtipi/docker-compose.yml').read_text())
    assert all('/wizard' not in v for v in recipe['services']['wizard-calendar']['volumes']), 'Grants mount belongs to WAM'
    image = recipe['services']['wizard-calendar']['image']
    names = {key: project + '_' + key for key in ('data', 'source', 'core', 'grants')}
    volumes = [{'type': 'volume', 'source': key, 'target': target, 'read_only': key != 'data'} for key, target in [('data', '/data'), ('source', '/app'), ('core', '/core'), ('grants', '/wizard')]]
    override = {'services': {
        'wizard-calendar': {'environment': {'WIZARD_CORE_DIR': '/core', 'WIZARD_TRUSTED_HOSTS': '127.0.0.1:' + str(p), 'WIZARD_TRUSTED_ORIGINS': base, 'CALENDAR_SYNC_MINUTES': '0.01', 'WIZARD_GRANTS_FILE': '/wizard/grants.json'}, 'ports': ['127.0.0.1:' + str(p) + ':8799'], 'volumes': volumes},
        'fake-connectors': {'image': image, 'read_only': True, 'user': '1000:1000', 'environment': {'PYTHONDONTWRITEBYTECODE': '1'}, 'command': ['python', '/app/qa/fake_connectors.py'], 'volumes': ['source:/app:ro'], 'ports': ['127.0.0.1:' + str(fp) + ':8800']}},
        'volumes': {key: {'name': name, 'external': True} for key, name in names.items()}}
    path = OUT / 'compose.override.json'; path.write_text(json.dumps(override, indent=2))
    ENV.update(APP_DATA_DIR=str(OUT / 'unused'), APP_SOURCE_DIR=str(ROOT), APP_PORT=str(p))
    cmd = ['docker', 'compose', '-p', project, '-f', str(ROOT / 'runtipi/docker-compose.yml'), '-f', str(path)]
    helper = ['docker', 'run', '--rm', '-i', '--network', 'none', '--user', '0:0']
    for key, name in names.items():
        run(['docker', 'volume', 'create', name])
        helper += ['-v', name + ':/' + key]
    helper += [image, 'python', '-c']
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode='w') as bundle:
        for name in ['app/server.py', 'openapi.json', 'qa/fake_connectors.py'] + sorted('web/' + x.name for x in (ROOT / 'web').iterdir() if x.is_file()): bundle.add(ROOT / name, arcname=name)
    # Pipe bytes directly: no host checkout bind is required inside the Colima VM.
    subprocess.run(helper + ["import sys,tarfile,os; tarfile.open(fileobj=sys.stdin.buffer,mode='r|').extractall('/source',filter='data'); os.chown('/data',0,0)"], input=archive.getvalue(), env=ENV, check=True)
    subprocess.run(helper + ["import sys; from pathlib import Path; Path('/core/app-client.js').write_bytes(sys.stdin.buffer.read())"], input=(ROOT / '.runtime/core/app-client.js').read_bytes(), env=ENV, check=True)
    def grant(key):
        body = {'outgoing': {'wizard-connectors': key}, 'provider_endpoints': {'wizard-connectors': 'http://fake-connectors:8800'}, 'incoming': [], 'enforce': True}
        subprocess.run(helper + ["import sys; from pathlib import Path; p=Path('/grants/grants.tmp'); p.write_bytes(sys.stdin.buffer.read()); p.chmod(0o644); p.replace('/grants/grants.json')"], input=json.dumps(body).encode(), env=ENV, check=True)
    checks = []
    try:
        grant('synthetic-calendar-grant')
        run(cmd + ['config'])
        run(cmd + ['up', '-d', '--no-build'])
        until(lambda: request(base, '/api/sync')[1]['state'] == 'ok')
        status = request(base, '/api/sync')[1]
        doc = request(base, '/api/export')[1]
        assert len(doc['events']) == 3 and len(doc['calendars']) == 2 and len(status['accounts']) == 2
        checks.append('actual Runtipi python:3.12-alpine recipe + fake provider on same Compose network; multi-account sync and dedupe')
        calls = request(fake, '/__qa/calls')[1]
        assert calls and all(c['grant_valid'] for c in calls)
        assert any(c['path'].endswith('/events') for c in calls)
        checks.append('X-Wizard-Grant verified by provider on status, calendars and events calls')
        until(lambda: len(request(fake, '/__qa/calls')[1]) >= len(calls) + 4)
        checks.append('periodic in-app worker repeats without any external import process')
        ENV['CALENDAR_URL'] = base
        run(['node', 'qa/connected.cjs'])
        first = doc['contentSha256']
        cid = doc['calendars'][0]['id']
        request(base, '/api/calendars/visibility', {'id': cid, 'visible': False})
        code, queued = request(base, '/api/sync', {})
        assert code == 202
        until(lambda: not request(base, '/api/sync')[1]['syncing'])
        after = request(base, '/api/export')[1]
        assert after['hidden'] == [cid] and after['contentSha256'] == first
        checks.append('owner Sync now returns 202; visibility retained and repeat digest stable')
        grant('synthetic-wrong-grant')
        until(lambda: request(base, '/api/sync')[1]['state'] == 'needs_permission')
        assert request(base, '/api/export')[1]['contentSha256'] == first
        grant('synthetic-calendar-grant')
        until(lambda: request(base, '/api/sync')[1]['state'] == 'ok')
        checks.append('read-only grants directory observes atomic rotation; 403 preserves data and restored key recovers')
        request(fake, '/__qa/mode', {'mode': 'invalid'})
        until(lambda: request(base, '/api/sync')[1]['state'] == 'error')
        assert request(base, '/api/export')[1]['contentSha256'] == first
        checks.append('invalid provider response leaves last-good atomic snapshot unchanged')
        request(fake, '/__qa/mode', {'mode': 'partial'})
        until(lambda: bool(request(base, '/api/sync')[1]['calendar_errors']))
        partial = request(base, '/api/export')[1]
        assert any(e['title'] == 'beta meeting' for e in partial['events'])
        assert any(e['title'] == 'alpha refreshed' for e in partial['events'])
        checks.append('failed calendar retains its last good data while successful calendar refreshes')
        cid = run(cmd + ['ps', '-q', 'wizard-calendar']).strip()
        inspect = json.loads(run(['docker', 'inspect', cid]))[0]
        assert inspect['HostConfig']['ReadonlyRootfs']
        assert inspect['Config']['User'] == recipe['services']['wizard-calendar']['user'] == '0:0'
        assert inspect['HostConfig']['CapDrop'] == ['ALL']
        assert any(m['Destination'] == '/wizard' and not m['RW'] for m in inspect['Mounts'])
        assert any(m['Destination'] == '/data' and m['RW'] for m in inspect['Mounts'])
        run(['docker', 'exec', cid, 'python', '-c', 'import sys; print(sys.version)'])
        checks.append('unchanged recipe root user with ALL caps dropped, read-only root and grant mount, writable /data verified by Docker inspect')
        result = {'ok': True, 'image': image, 'project': project, 'count': len(checks), 'checks': checks, 'initial_sync': status, 'grant_checks': calls}
        (OUT / 'compose.json').write_text(json.dumps(result, indent=2)); print(json.dumps(result, indent=2), flush=True)
    finally:
        run(cmd + ['logs', '--no-color'])
        run(cmd + ['down', '--remove-orphans'])
        for name in names.values(): run(['docker', 'volume', 'rm', name])


if __name__ == '__main__':
    server_tests()
    compose_tests()
    (OUT / 'PASS').write_text('Calendar API, sync, browser, hosted harness and actual Compose passed.\n')
    print('CALENDAR_SYNC_ACCEPTANCE_PASS ' + str(OUT), flush=True)
