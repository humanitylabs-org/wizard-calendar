#!/usr/bin/env python3
"""Generate the digest-pinned image recipe; the image is built by .github/workflows/app-image.yml."""
import json
from pathlib import Path
import re
import sys

root = Path(__file__).resolve().parents[1]
match = re.search(r'^version: (\S+)$', (root / 'wizard.md').read_text(), re.M)
assert match, 'wizard.md version missing'
version = match[1]
# Published by .github/workflows/app-image.yml (multi-arch index, public on GHCR); update both
# the commit tag and the digest together when the image is rebuilt.
IMAGE = ('ghcr.io/humanitylabs-org/wizard-calendar:sha-%s@%s'
         % ('06e2735926bef4811bb4865f27dc1924a0572a17', 'sha256:af46cdeed6423a9aae2ee221a63f5698df2c00d5626c6d3d97b9a5e981675be2'))
common = {
    'image': IMAGE,
    'cap_drop': ['ALL'], 'security_opt': ['no-new-privileges:true'],
    'mem_limit': '256m', 'tmpfs': ['/tmp:rw,noexec,nosuid,size=16m'], 'read_only': True,
    'volumes': ['${APP_DATA_DIR}/data:/data'],
}
compose = {'services': {
    # Docker creates fresh bind directories as root. Change only this app's data
    # root, without following symlinks or walking/chowning existing user files.
    'calendar-data-init': {
        **common, 'user': '0:0', 'cap_add': ['CHOWN'], 'network_mode': 'none',
        'command': ['python', 'app/prepare_data.py'], 'restart': 'no',
        'healthcheck': {'disable': True},
    },
    'wizard-calendar': {
        **common, 'user': '1000:1000',
        'depends_on': {'calendar-data-init': {'condition': 'service_completed_successfully'}},
        'environment': {'BIND': '0.0.0.0', 'PORT': '8799', 'DATA_DIR': '/data', 'PYTHONDONTWRITEBYTECODE': '1',
            'CALENDAR_TIMEZONE': '${CALENDAR_TIMEZONE:-}',
            'CALENDAR_SYNC_MINUTES': '${CALENDAR_SYNC_MINUTES:-10}',
            'ICAL_SYNC_INTERVAL': '${ICAL_SYNC_INTERVAL:-900}',
            'CONNECTORS_URL': '${CONNECTORS_URL:-}',
            'WIZARD_GRANTS_FILE': '/wizard/grants.json',
            'WIZARD_TRUSTED_HOSTS': '${WIZARD_TRUSTED_HOSTS:-}',
            'WIZARD_TRUSTED_ORIGINS': '${WIZARD_TRUSTED_ORIGINS:-}',
            'WIZARD_LOCAL_HOSTS': '127.0.0.1:${APP_PORT},localhost:${APP_PORT},wizard-calendar:8799'},
        # WAM injects its standard read-only /wizard grants directory.
        'x-runtipi': {'is_main': True, 'internal_port': 8799},
    },
}, 'x-runtipi': {'schema_version': 2, 'overrides': []}}
text = json.dumps(compose, indent=2) + '\n'
if '--check' in sys.argv:
    assert (root / 'runtipi/docker-compose.yml').read_text() == text, 'Regenerate runtime recipe'
    print('PASS image recipe matches generator')
else:
    (root / 'runtipi/docker-compose.yml').write_text(text)
    print('Image recipe generated')
