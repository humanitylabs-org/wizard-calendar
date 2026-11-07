#!/usr/bin/env python3
"""Offline recipe/version/security regression checks (stdlib only)."""
import ast
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
manifest = (ROOT / 'wizard.md').read_text()
match = re.search(r'^version: (\S+)$', manifest, re.M)
assert match, 'wizard.md version missing'
version = match[1]
config = json.loads((ROOT / 'runtipi/config.json').read_text())
recipe = json.loads((ROOT / 'runtipi/docker-compose.yml').read_text())
pin = re.compile(r'^ghcr\.io/humanitylabs-org/wizard-calendar:sha-[0-9a-f]{40}@sha256:[0-9a-f]{64}$')
assert config['version'] == version
images = {s['image'] for s in recipe['services'].values()}
assert len(images) == 1 and pin.match(images.copy().pop()), images
assert f'image: wizard-calendar:{version}\n' in (ROOT / 'compose.yml').read_text()  # developer build only
constants = {n.targets[0].id: ast.literal_eval(n.value) for n in ast.parse((ROOT / 'app/server.py').read_text()).body
             if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id == 'VERSION'}
assert constants['VERSION'] == version
assert json.loads((ROOT / 'openapi.json').read_text())['info']['version'] == version
assert f"version: '{version}'" in (ROOT / 'web/app.js').read_text()
assert 'package: image' in manifest and 'uses: [connected-accounts]' in manifest
css = (ROOT / 'web/app.css').read_text()
setup_heading = re.search(r'\.setup h1\s*\{([^}]+)\}', css)[1]
assert 'font-size: var(--wz-text-title, 1.5rem)' in setup_heading
assert not re.search(r'font-size:\s*[\d.]+px', setup_heading), 'New setup heading must follow the shared typography token'
assert '/wizard-calendar/' in manifest
assert all(f['required'] is False and 'default' in f for f in config['form_fields'])
print(f'PASS versions agree: wizard.md/config/compose/server/OpenAPI/client = {version}')
for name, service in recipe['services'].items():
    assert 'pull_policy' not in service
    assert service['cap_drop'] == ['ALL'] and service['read_only'] is True
    assert service['security_opt'] == ['no-new-privileges:true']
    assert service['tmpfs'] and service['volumes'] == ['${APP_DATA_DIR}/data:/data']
    assert 'build' not in service and 'APP_SOURCE_DIR' not in json.dumps(service)
main = recipe['services']['wizard-calendar']
assert main['user'] == '1000:1000' and not main.get('cap_add')
assert main['depends_on']['calendar-data-init']['condition'] == 'service_completed_successfully'
init = recipe['services']['calendar-data-init']
assert init['user'] == '0:0' and init['cap_add'] == ['CHOWN'] and init['network_mode'] == 'none'
assert init['command'] == ['python', 'app/prepare_data.py']
assert init['healthcheck']['disable'] is True
assert main['environment']['WIZARD_TRUSTED_ORIGINS'] == '${WIZARD_TRUSTED_ORIGINS:-}'
dockerfile = (ROOT / 'app/Dockerfile').read_text()
assert 'FROM python:3.12-slim-bookworm' in dockerfile
assert 'USER 1000:1000' in dockerfile and 'HEALTHCHECK ' in dockerfile
assert '!app/prepare_data.py' in (ROOT / '.dockerignore').read_text()
subprocess.run([sys.executable, 'tools/package_runtime.py', '--check'], cwd=ROOT, check=True)
print('PASS portable image, optional defaults, Connected accounts declaration and hardened recipe')
# Scan tracked source/doc/tests; .git and generated receipts are not app payload.
files = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
owner = re.compile('wizard[.]tailc0f369[.]ts[.]net|\\b[Jj]ames\\b|/home/' + 'telos')
for name in filter(None, files):
    path = ROOT / name
    if path.is_file():
        text = path.read_text(errors='replace')
        assert not owner.search(text), f'Owner-specific text in {name}'
        emails = re.findall(r'[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})', text)
        assert all(domain == 'example.com' or domain.endswith('.invalid') for domain in emails), f'Personal email in {name}'
print('PASS owner-specific text scan; only reserved synthetic example email domains allowed')
