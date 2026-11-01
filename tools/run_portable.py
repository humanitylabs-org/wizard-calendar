#!/usr/bin/env python3
"""Run a preloaded Alpha image locally; never build, pull or deploy a store app."""
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time
import urllib.request

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('action', choices=['start', 'stop', 'status'])
parser.add_argument('--project', default='calendar-test')
parser.add_argument('--port', type=int, default=18787)
parser.add_argument('--platform', choices=['linux/arm64', 'linux/amd64'])
args = parser.parse_args()
if not re.fullmatch(r'calendar-[a-z0-9-]{1,40}', args.project):
    parser.error('Project must begin calendar- followed by 1–40 lowercase letters, digits or hyphens')
if not 1024 <= args.port <= 65535:
    parser.error('Port must be 1024–65535')
root = Path(__file__).resolve().parents[1]
state = root / '.runtime'
state.mkdir(exist_ok=True)
docker = shlex.split(os.environ.get('DOCKER_CMD', 'docker'))
config = json.loads((root / 'runtipi/docker-compose.yml').read_text())
image = config['services']['wizard-calendar']['image']
volume, core = args.project + '_data', args.project + '_core'
origin = f'http://127.0.0.1:{args.port}'
data_mount = {'type': 'volume', 'source': 'calendar-data', 'target': '/data'}
override = {'services': {
    'calendar-data-init': {'volumes': [data_mount]},
    'wizard-calendar': {'ports': [f'127.0.0.1:{args.port}:8799'],
        'environment': {'WIZARD_CORE_DIR': '/core', 'WIZARD_TRUSTED_HOSTS': f'127.0.0.1:{args.port},localhost:{args.port}',
                        'WIZARD_TRUSTED_ORIGINS': origin + f',http://localhost:{args.port}'},
        'volumes': [data_mount, {'type': 'volume', 'source': 'calendar-core', 'target': '/core', 'read_only': True}]},
}, 'volumes': {'calendar-data': {'name': volume, 'external': True}, 'calendar-core': {'name': core, 'external': True}}}
if args.platform:
    for service in override['services'].values():
        service['platform'] = args.platform
path = state / (args.project + '.json')
path.write_text(json.dumps(override, indent=2) + '\n')
env = dict(os.environ, APP_DATA_DIR=str(state / 'unused-bind-target'), APP_PORT=str(args.port))
cmd = [*docker, 'compose', '-p', args.project, '-f', str(root / 'runtipi/docker-compose.yml'), '-f', str(path)]
if args.action == 'start':
    subprocess.run([*docker, 'image', 'inspect', image], check=True, stdout=subprocess.DEVNULL)
    subprocess.run([sys.executable, str(root / 'tools/fetch_core.py')], check=True)
    for name in (volume, core):
        subprocess.run([*docker, 'volume', 'create', name], check=True)
    helper = [*docker, 'run', '--rm', '-i', '--user', '0:0', '--network', 'none',
              '--read-only', '--cap-drop=ALL', '--security-opt=no-new-privileges:true']
    if args.platform:
        helper += ['--platform', args.platform]
    subprocess.run([*helper, '-v', core + ':/core', image, 'python', '-c',
                    "import sys; from pathlib import Path; p=Path('/core/app-client.tmp'); p.write_bytes(sys.stdin.buffer.read()); p.replace('/core/app-client.js')"],
                   input=(state / 'core/app-client.js').read_bytes(), check=True)
    subprocess.run(cmd + ['up', '-d', '--no-build', '--force-recreate'], env=env, check=True)
    for _ in range(45):
        try:
            with urllib.request.urlopen(origin + '/healthz', timeout=2) as response:
                health = json.load(response)
            if health.get('ok') and health.get('app') == 'wizard-calendar':
                break
        except (OSError, ValueError):
            pass
        time.sleep(1)
    else:
        raise SystemExit('Calendar did not become healthy; inspect Compose logs. Data volume retained.')
    print(f'Calendar healthy: {origin}/wizard-calendar/. Data retained in {volume}.')
elif args.action == 'stop':
    subprocess.run(cmd + ['down'], env=env, check=True)
    print(f'Stopped. Data volume {volume} retained. No data deletion was requested.')
else:
    subprocess.run(cmd + ['ps'], env=env, check=True)
