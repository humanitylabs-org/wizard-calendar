#!/usr/bin/env python3
"""Release-worker runner: stage a clean checkout as cwd; set ARCH and DOCKER_CMD.
Does not push images, create releases/tags, deploy, or contact owner services.
"""
import hashlib
import json
import os
import platform
from pathlib import Path
import re
import shlex
import signal
import subprocess
import sys
import time
import urllib.request
import uuid


def main():
    root = Path.cwd()
    arch = os.environ.get('ARCH', '')
    if arch not in ('amd64', 'arm64'):
        raise SystemExit('Set ARCH=amd64 or ARCH=arm64')
    if {'x86_64': 'amd64', 'aarch64': 'arm64', 'arm64': 'arm64'}.get(platform.machine()) != arch:
        raise SystemExit('Worker architecture must match requested architecture; never emulate')
    docker = shlex.split(os.environ.get('DOCKER_CMD', 'docker'))
    if not docker:
        raise SystemExit('DOCKER_CMD cannot be empty')
    def run(*args, **kw):
        return subprocess.run(list(args), cwd=root, check=True, **kw)
    def output(*args):
        return subprocess.check_output(list(args), cwd=root, text=True).strip()
    sha = output('git', 'rev-parse', 'HEAD')
    if os.environ.get('SOURCE_REVISION', sha) != sha:
        raise SystemExit('Staged source revision differs from admitted source')
    if output('git', 'status', '--porcelain', '--untracked-files=no'):
        raise SystemExit('Refusing a dirty tracked source checkout')
    match = re.search(r'^version: (\S+)$', (root / 'wizard.md').read_text(), re.M)
    if not match:
        raise SystemExit('wizard.md has no version')
    version = match[1]
    tag = f'wizard-calendar:{version}'
    evidence = root / 'evidence'
    evidence.mkdir(exist_ok=True)
    receipt = evidence / f'release-{arch}.json'
    # Never leave an earlier PASS receipt if this attempt fails.
    receipt.unlink(missing_ok=True)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
    with (evidence / f'headless-{arch}.log').open('w') as log:
        run(sys.executable, 'qa/headless.py', stdout=log, stderr=subprocess.STDOUT, env=env)
    print(f'PASS headless QA ({arch})', flush=True)
    daemon_arch = output(*docker, 'info', '--format', '{{.Architecture}}')
    native = {'x86_64': 'amd64', 'aarch64': 'arm64', 'amd64': 'amd64', 'arm64': 'arm64'}.get(daemon_arch)
    if native != arch:
        raise SystemExit(f'Native builds only: Docker is {daemon_arch}, requested {arch}')
    run(*docker, 'build', '--platform', f'linux/{arch}', '-f', 'app/Dockerfile',
        '-t', tag, '--label', f'org.opencontainers.image.revision={sha}', '.')
    info = json.loads(output(*docker, 'image', 'inspect', tag))[0]
    assert info['Architecture'] == arch and info['Os'] == 'linux'
    assert info['Config']['User'] == '1000:1000'
    assert info['Config']['Labels']['org.opencontainers.image.revision'] == sha
    assert info['Config'].get('Healthcheck')
    name = 'calendar-alpha-smoke-' + uuid.uuid4().hex[:12]
    volume = name + '-data'
    hardening = ['--read-only', '--cap-drop=ALL', '--security-opt=no-new-privileges:true',
                 '--tmpfs', '/tmp:rw,noexec,nosuid,size=16m', '--memory=256m']
    mount = ['--mount', f'type=volume,source={volume},target=/data,volume-nocopy']
    def get(path):
        req = urllib.request.Request(base + path, headers={'Host': '127.0.0.1:8799'})
        with urllib.request.urlopen(req, timeout=3) as response:
            assert response.status == 200
            return json.load(response)
    def ready():
        for _ in range(120):
            try:
                health = get('/wizard-calendar/healthz')
                if health.get('ok') and health.get('version') == version:
                    return health
            except (OSError, ValueError):
                pass
            time.sleep(.25)
        raise RuntimeError('Image smoke failed health readiness')
    run(*docker, 'volume', 'create', volume)
    try:
        # Exercise the root-owned, no-copy data root used by a fresh WAM bind.
        # This isolated helper has no network and only CHOWN, just like Compose.
        run(*docker, 'run', '--rm', '--platform', f'linux/{arch}', '--user', '0:0',
            '--network', 'none', *hardening, '--cap-add=CHOWN', *mount,
            '--health-cmd', 'true', tag, 'python', 'app/prepare_data.py')
        run(*docker, 'run', '-d', '--name', name, '--platform', f'linux/{arch}',
            '--user', '1000:1000', *hardening, *mount,
            '-p', '127.0.0.1::8799', tag)
        inspected = json.loads(output(*docker, 'inspect', name))[0]
        port = inspected['NetworkSettings']['Ports']['8799/tcp'][0]['HostPort']
        base = f'http://127.0.0.1:{port}'
        # Use the internal loopback Host; the smoke publishes a random port.
        ready()
        status = output(*docker, 'exec', name, 'python', '-c',
                        "from pathlib import Path; print(Path('/proc/1/status').read_text())")
        uid = re.search(r'^Uid:\s+(.+)$', status, re.M)
        gid = re.search(r'^Gid:\s+(.+)$', status, re.M)
        assert uid and set(uid[1].split()) == {'1000'}, status
        assert gid and set(gid[1].split()) == {'1000'}, status
        assert get('/api/events')['events'] == []
        run(*docker, 'exec', name, 'python', '-c',
            "from pathlib import Path; p=Path('/data/smoke'); p.write_text('retained'); assert p.read_text() == 'retained'")
        host = inspected['HostConfig']
        assert host['ReadonlyRootfs'] and host['CapDrop'] == ['ALL']
        assert not host.get('CapAdd') and 'no-new-privileges:true' in host['SecurityOpt']
        for _ in range(120):
            state = json.loads(output(*docker, 'inspect', name))[0]['State']
            if state['Health']['Status'] == 'healthy':
                break
            if state['Status'] != 'running' or state['Health']['Status'] == 'unhealthy':
                raise RuntimeError('Docker healthcheck failed: ' + json.dumps(state))
            time.sleep(.25)
        else:
            raise RuntimeError('Docker healthcheck did not become healthy')
        print(f'PASS hardened image smoke ({arch}): HTTP 200, Uid/Gid 1000, writable /data, Docker healthy', flush=True)
    finally:
        # Best effort logs on failure; never target containers outside this run.
        subprocess.run([*docker, 'logs', name], cwd=root, check=False)
        subprocess.run([*docker, 'rm', '-f', name], cwd=root, check=False)
        run(*docker, 'volume', 'rm', volume)
    archive = root / f'wizard-calendar-{arch}.tar.gz'
    temporary = archive.with_suffix(archive.suffix + '.partial')
    try:
        with temporary.open('wb') as dest:
            save = subprocess.Popen([*docker, 'save', tag], cwd=root, stdout=subprocess.PIPE)
            try:
                assert save.stdout is not None
                compressed = subprocess.run(['gzip', '-n'], stdin=save.stdout, stdout=dest)
                save.stdout.close()
                saved_code = save.wait()
                compressed.check_returncode()
                if saved_code:
                    raise subprocess.CalledProcessError(saved_code, save.args)
            finally:
                if save.poll() is None:
                    save.kill()
                    save.wait()
        temporary.replace(archive)
    finally:
        temporary.unlink(missing_ok=True)
    digest = hashlib.sha256()
    with archive.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    result = {'ok': True, 'commit': sha, 'version': version, 'architecture': arch,
              'image_tag': tag, 'image_id': info['Id'], 'artifact': archive.name,
              'sha256': digest.hexdigest(), 'bytes': archive.stat().st_size,
              'health_status': 200, 'uid': 1000, 'gid': 1000, 'live_provider': False}
    receipt.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    main()
