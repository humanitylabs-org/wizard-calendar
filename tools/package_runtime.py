#!/usr/bin/env python3
"""Generate the portable source-package recipe (no embedded app payload or build)."""
import json
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]
compose = {'services': {'wizard-calendar': {
    'image': 'python:3.12-alpine@sha256:1b668429b3511ab407d8e00648891631b0b1a4d7e15e3ca70f38ab5b91ad4ab4',
    # App Manager creates root-owned binds. No ownership-preparing custom image.
    'user': '0:0', 'working_dir': '/app',
    'cap_drop': ['ALL'], 'security_opt': ['no-new-privileges:true'],
    'mem_limit': '256m', 'tmpfs': ['/tmp'], 'read_only': True,
    'environment': {'BIND': '0.0.0.0', 'PORT': '8799', 'DATA_DIR': '/data',
        'PYTHONDONTWRITEBYTECODE': '1', 'CALENDAR_TIMEZONE': '${CALENDAR_TIMEZONE:-}',
        'CALENDAR_SYNC_MINUTES': '${CALENDAR_SYNC_MINUTES:-10}',
        'CONNECTORS_URL': '${CONNECTORS_URL:-}',
        'WIZARD_GRANTS_FILE': '/wizard/grants.json',
        'WIZARD_TRUSTED_HOSTS': '${WIZARD_TRUSTED_HOSTS:-}',
        'WIZARD_TRUSTED_ORIGINS': '${WIZARD_TRUSTED_ORIGINS:-}',
        'WIZARD_LOCAL_HOSTS': '127.0.0.1:${APP_PORT},localhost:${APP_PORT},wizard-calendar:8799'},
    'volumes': ['${APP_SOURCE_DIR}:/app:ro', '${APP_DATA_DIR}/data:/data', '${APP_DATA_DIR}/wizard:/wizard:ro'],
    'command': ['python', 'app/server.py'],
    'x-runtipi': {'is_main': True, 'internal_port': 8799}
}}, 'x-runtipi': {'schema_version': 2, 'overrides': []}}
text = json.dumps(compose, indent=2) + '\n'
if '--check' in sys.argv:
    assert (root / 'runtipi/docker-compose.yml').read_text() == text, 'Regenerate runtime recipe'
    print('Source-package recipe matches')
else:
    (root / 'runtipi/docker-compose.yml').write_text(text)
    print('Source-package recipe generated')
