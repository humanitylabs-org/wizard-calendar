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
        'PYTHONDONTWRITEBYTECODE': '1', 'CALENDAR_TIMEZONE': '${CALENDAR_TIMEZONE:-UTC}',
        'ICAL_SYNC_INTERVAL': '${ICAL_SYNC_INTERVAL:-900}',
        'WIZARD_TRUSTED_HOSTS': '${WIZARD_TRUSTED_HOSTS:-}',
        'WIZARD_TRUSTED_ORIGINS': '${WIZARD_TRUSTED_ORIGINS:-}',
        'WIZARD_LOCAL_HOSTS': '127.0.0.1:${APP_PORT},localhost:${APP_PORT},wizard-calendar:8799',
        'WIZARD_SHELL_AUTH': '${WIZARD_SHELL_AUTH:-tailscale-serve}',
        'WIZARD_OWNER_LOGINS': '${WIZARD_OWNER_LOGINS:-}',
        'WIZARD_GRANTS_FILE': '/wizard/grants.json',
        'CALENDAR_RADICALE_URL': 'http://wizard-calendar-dav:5232'},
    'volumes': ['${APP_SOURCE_DIR}:/app:ro', '${APP_DATA_DIR}/data:/data'],
    'command': ['python', 'app/server.py'],
    'x-runtipi': {'is_main': True, 'internal_port': 8799}
}, 'wizard-calendar-dav': {
    # Calendar on Radicale (issue 61): the stock upstream image, unmodified. Not main, so it joins only this app's own
    # network (no port, not on the Wizard's main network): Calendar's server is the only thing that reaches it.
    # Root like Calendar (root-owned binds, every capability dropped); it waits for Calendar to write its password file.
    'image': 'ghcr.io/kozea/radicale:3.9.2@sha256:c74545ef669a3166646ec13438a31b5d0bfff198d8ba7ecd214c0a5f40f03fb4',
    'user': '0:0', 'cap_drop': ['ALL'], 'security_opt': ['no-new-privileges:true'],
    'mem_limit': '128m', 'tmpfs': ['/tmp'], 'read_only': True,
    'volumes': ['${APP_DATA_DIR}/data/radicale:/var/lib/radicale'],
    'command': ['--hosts', '0.0.0.0:5232', '--auth-type', 'htpasswd', '--auth-htpasswd-filename', '/var/lib/radicale/users',
                '--auth-htpasswd-encryption', 'plain', '--rights-type', 'owner_only',
                '--storage-filesystem-folder', '/var/lib/radicale/collections'],
}}, 'x-runtipi': {'schema_version': 2, 'overrides': []}}
text = json.dumps(compose, indent=2) + '\n'
if '--check' in sys.argv:
    assert (root / 'runtipi/docker-compose.yml').read_text() == text, 'Regenerate runtime recipe'
    print('Source-package recipe matches')
else:
    (root / 'runtipi/docker-compose.yml').write_text(text)
    print('Source-package recipe generated')
