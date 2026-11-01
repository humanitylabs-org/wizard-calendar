#!/usr/bin/env python3
"""Disposable Thales acceptance runner. Real recipe + synthetic provider, no owner data.
Run in the durable light lane; Docker context must name an already-running daemon.
"""
import io
import json
import os
import platform
from pathlib import Path
import socket
import signal
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
if platform.system() == 'Darwin': ENV.setdefault('DOCKER_CONTEXT', 'colima')
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
                if ENV.get('LEGACY_WEB_DIR'):
                    run(['node', 'qa/legacy-compare.cjs'])
            finally:
                proc.terminate(); proc.wait(timeout=10)


def fake_provider_service(image, published_port):
    # The reused production image defaults to PORT=8799. Provider traffic and
    # the grant endpoint use 8800; never let the image ENV choose this test port.
    return {'image': image, 'read_only': True, 'user': '1000:1000', 'healthcheck': {'disable': True},
            'environment': {'PYTHONDONTWRITEBYTECODE': '1', 'PORT': '8800'},
            'command': ['python', '/app/qa/fake_connectors.py'],
            'volumes': ['source:/app:ro'], 'ports': ['127.0.0.1:' + str(published_port) + ':8800']}


def inspect_container(cid):
    # Parse privately: never print Config.Env, health output or credentials.
    return json.loads(subprocess.check_output(['docker', 'inspect', cid], env=ENV, text=True, timeout=15))[0]


def compose_diagnostics(cmd, base, fake):
    """Bounded synthetic-only diagnostics before teardown, including failures."""
    result = {'api': {}, 'containers': []}
    states = {'ok', 'error', 'needs_permission', 'not_configured', 'needs_setup', 'syncing', 'idle', 'unavailable'}
    for label, url, path in [('calendar', base, '/api/sync'), ('provider', fake, '/__qa/calls')]:
        try:
            status, body = request(url, path)
            result['api'][label] = {'http_status': status}
            if label == 'calendar':
                result['api'][label].update(state=body.get('state') if body.get('state') in states else 'other', syncing=body.get('syncing') is True)
            else: result['api'][label]['call_count'] = len(body)
        except Exception as exc: result['api'][label] = {'error_class': type(exc).__name__}
    try:
        ids = subprocess.check_output(cmd + ['ps', '-aq'], env=ENV, text=True, timeout=15).split()
        for cid in ids:
            info = inspect_container(cid); state = info['State']
            result['containers'].append({'service': info['Config']['Labels'].get('com.docker.compose.service'),
                'status': state.get('Status'), 'running': state.get('Running'), 'exit_code': state.get('ExitCode'), 'oom_killed': state.get('OOMKilled'),
                'mounts': [{'target': m['Destination'], 'read_only': not m['RW']} for m in info['Mounts']]})
        # Only these public, synthetic test services; bounded stderr/stdout, no
        # owner endpoints, environment dump, grant file or personal pages.
        logs = subprocess.run(cmd + ['logs', '--no-color', '--tail', '40'], env=ENV, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=15)
        (OUT / 'compose-public-test.log').write_text(logs.stdout[-8192:])
        result['log_truncated'] = len(logs.stdout) > 8192
    except Exception as exc: result['diagnostic_error_class'] = type(exc).__name__
    (OUT / 'compose-diagnostics.json').write_text(json.dumps(result, indent=2))


def compose_tests():
    project = 'calendar-sync-qa-' + str(os.getpid())
    p, fp = port(), port()
    base, fake = 'http://127.0.0.1:' + str(p), 'http://127.0.0.1:' + str(fp)
    recipe = json.loads((ROOT / 'runtipi/docker-compose.yml').read_text())
    assert all('/wizard' not in v for v in recipe['services']['wizard-calendar']['volumes']), 'Grants mount belongs to WAM'
    image = recipe['services']['wizard-calendar']['image']
    # Verify existence without logging the image's complete Config.Env.
    run(['docker', 'image', 'inspect', '--format', '{{.Id}}', image])
    names = {key: project + '_' + key for key in ('data', 'source', 'core', 'grants')}
    volumes = [{'type': 'volume', 'source': key, 'target': target, 'read_only': key != 'data'} for key, target in [('data', '/data'), ('core', '/core'), ('grants', '/wizard')]]
    override = {'services': {
        'calendar-data-init': {'volumes': [{'type': 'volume', 'source': 'data', 'target': '/data'}]},
        'wizard-calendar': {'environment': {'WIZARD_CORE_DIR': '/core', 'WIZARD_TRUSTED_HOSTS': '127.0.0.1:' + str(p), 'WIZARD_TRUSTED_ORIGINS': base, 'CALENDAR_SYNC_MINUTES': '0.01', 'WIZARD_GRANTS_FILE': '/wizard/grants.json'}, 'ports': ['127.0.0.1:' + str(p) + ':8799'], 'volumes': volumes},
        'fake-connectors': fake_provider_service(image, fp)},
        'volumes': {key: {'name': name, 'external': True} for key, name in names.items()}}
    path = OUT / 'compose.override.json'; path.write_text(json.dumps(override, indent=2))
    ENV.update(APP_DATA_DIR=str(OUT / 'unused'), APP_PORT=str(p))
    cmd = ['docker', 'compose', '-p', project, '-f', str(ROOT / 'runtipi/docker-compose.yml'), '-f', str(path)]
    helper = ['docker', 'run', '--rm', '-i', '--network', 'none', '--user', '0:0']
    for key, name in names.items():
        run(['docker', 'volume', 'create', name])
        helper += ['-v', name + ':/' + key]
    helper += [image, 'python', '-c']
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode='w') as bundle:
        directory = tarfile.TarInfo('qa'); directory.type = tarfile.DIRTYPE; directory.mode = 0o755
        bundle.addfile(directory)
        info = bundle.gettarinfo(ROOT / 'qa/fake_connectors.py', arcname='qa/fake_connectors.py')
        info.mode = 0o644
        with (ROOT / 'qa/fake_connectors.py').open('rb') as file: bundle.addfile(info, file)
    # Pipe bytes directly: no host checkout bind is required inside the Colima VM.
    subprocess.run(helper + ["import sys,tarfile,os; tarfile.open(fileobj=sys.stdin.buffer,mode='r|').extractall('/source',filter='data'); os.chown('/data',0,0)"], input=archive.getvalue(), env=ENV, check=True)
    subprocess.run(helper + ["import sys; from pathlib import Path; Path('/core/app-client.js').write_bytes(sys.stdin.buffer.read())"], input=(ROOT / '.runtime/core/app-client.js').read_bytes(), env=ENV, check=True)
    def grant(key):
        body = {'outgoing': {'connected-accounts': key}, 'provider_endpoints': {'connected-accounts': 'http://fake-connectors:8800'}, 'incoming': [], 'enforce': True}
        subprocess.run(helper + ["import sys; from pathlib import Path; p=Path('/grants/grants.tmp'); p.write_bytes(sys.stdin.buffer.read()); p.chmod(0o644); p.replace('/grants/grants.json')"], input=json.dumps(body).encode(), env=ENV, check=True)
    checks = []
    try:
        grant('synthetic-calendar-grant')
        run(cmd + ['config'])
        run(cmd + ['up', '-d', '--no-build'])
        # Real image ENV regression: verify inside each running service, without
        # printing the environment or grant contents. Also check source modes.
        run(cmd + ['exec', '-T', 'fake-connectors', 'python', '-c', "import os,stat; from pathlib import Path; assert os.environ['PORT']=='8800'; p=Path('/app/qa/fake_connectors.py'); assert stat.S_IMODE(p.stat().st_mode)==0o644; assert os.access(p,os.R_OK); print('FAKE_PROVIDER_PORT_8800_SOURCE_0644')"])
        run(cmd + ['exec', '-T', 'wizard-calendar', 'python', '-c', "import os; assert os.environ['PORT']=='8799'; from pathlib import Path; assert Path('/wizard/grants.json').stat().st_mode & 0o444 == 0o444; assert Path('/core/app-client.js').is_file(); print('CALENDAR_PORT_8799_GRANTS_CORE_READABLE')"])
        run(cmd + ['exec', '-T', 'wizard-calendar', 'python', '-c', "import urllib.request,json; r=urllib.request.urlopen('http://fake-connectors:8800/__qa/calls',timeout=3); assert r.status==200; assert isinstance(json.load(r),list); print('PROVIDER_LISTENER_8800_REACHABLE')"])
        checks.append('real production image port 8799 overridden to 8800 only for fake provider; mounted source/core/grants readable')
        until(lambda: request(base, '/api/sync')[1]['state'] == 'ok')
        status = request(base, '/api/sync')[1]
        doc = request(base, '/api/export')[1]
        assert len(doc['events']) == 3 and len(doc['calendars']) == 2 and len(status['accounts']) == 2
        checks.append('actual Runtipi Alpha image recipe + fake provider on same Compose network; multi-account sync and dedupe')
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
        inspect = inspect_container(cid)
        assert inspect['HostConfig']['ReadonlyRootfs']
        assert inspect['Config']['User'] == recipe['services']['wizard-calendar']['user'] == '1000:1000'
        assert inspect['HostConfig']['CapDrop'] == ['ALL']
        assert any(m['Destination'] == '/wizard' and not m['RW'] for m in inspect['Mounts'])
        assert any(m['Destination'] == '/data' and m['RW'] for m in inspect['Mounts'])
        run(['docker', 'exec', cid, 'python', '-c', 'import sys; print(sys.version)'])
        checks.append('non-root 1000:1000 with ALL caps dropped, read-only root and grant mount, writable /data verified by Docker inspect')
        result = {'ok': True, 'image': image, 'project': project, 'count': len(checks), 'checks': checks, 'initial_sync': status, 'grant_checks': calls}
        (OUT / 'compose.json').write_text(json.dumps(result, indent=2)); print(json.dumps(result, indent=2), flush=True)
    finally:
        try: compose_diagnostics(cmd, base, fake)
        finally:
            try: run(cmd + ['down', '--remove-orphans'])
            finally:
                for name in names.values(): run(['docker', 'volume', 'rm', name])


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    server_tests()
    compose_tests()
    (OUT / 'PASS').write_text('Calendar API, sync, browser, hosted harness and actual Compose passed.\n')
    print('CALENDAR_SYNC_ACCEPTANCE_PASS ' + str(OUT), flush=True)
