#!/usr/bin/env python3
"""Generate the portable source-package recipe (no embedded app payload or build)."""
import json
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]

# Radicale's start step (issue 74). Calendar writes Radicale's password file (DATA/radicale/users, 0600) as whatever
# user its own service runs as: root by default, but a box may run it as 1000:1000. Radicale must read that file, and
# root with every capability dropped cannot read another user's 0600 file. So the DAV service becomes the file's owner
# before Radicale starts: it waits for the file (opening a folder Docker made as root so Calendar can write it, instead
# of crash-looping), gives the radicale folder tree to that owner, drops every capability (bounding set included, so
# not even a root Radicale gets one back) and starts the stock Radicale as that user. CHOWN/SETUID/SETGID/SETPCAP are
# only used here, before Radicale runs. Python is the stock image's own; no custom image.
DAV_START = r"""
import ctypes, os, sys, time
d = '/var/lib/radicale'
f = d + '/users'
first = os.stat(d)
opened = False
while not os.path.isfile(f):
    if not opened:
        print('wizard-calendar-dav: waiting for Calendar to write its password file', file=sys.stderr, flush=True)
        if first.st_uid == os.getuid() and first.st_mode & 0o777 != 0o777:
            os.chmod(d, 0o777)
        opened = True
    time.sleep(1)
st = os.stat(f)
uid, gid = st.st_uid, st.st_gid
if opened and first.st_uid == os.getuid() and first.st_mode & 0o777 != 0o777:
    os.chmod(d, first.st_mode & 0o7777)
for top, dirs, files in os.walk(d, onerror=lambda e: print('wizard-calendar-dav:', e, file=sys.stderr)):
    for p in [top] + [os.path.join(top, n) for n in dirs + files]:
        try:
            s = os.lstat(p)
            if (s.st_uid, s.st_gid) != (uid, gid):
                os.lchown(p, uid, gid)
        except OSError as e:
            print('wizard-calendar-dav:', e, file=sys.stderr)
libc = ctypes.CDLL(None, use_errno=True)
for cap in range(64):
    libc.prctl(24, cap, 0, 0, 0)  # PR_CAPBSET_DROP
os.setgroups([])
os.setgid(gid)
os.setuid(uid)
print(f'wizard-calendar-dav: Radicale runs as {uid}:{gid}, the owner of Calendar\'s password file', file=sys.stderr, flush=True)
os.execv('/app/bin/python', ['/app/bin/python', '/app/bin/radicale', *sys.argv[1:]])
""".strip() + '\n'
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
    # Starts as root (root-owned binds), then DAV_START turns it into the user Calendar runs as, with no capabilities.
    'image': 'ghcr.io/kozea/radicale:3.9.2@sha256:c74545ef669a3166646ec13438a31b5d0bfff198d8ba7ecd214c0a5f40f03fb4',
    'user': '0:0', 'cap_drop': ['ALL'], 'cap_add': ['CHOWN', 'SETUID', 'SETGID', 'SETPCAP'],
    'security_opt': ['no-new-privileges:true'],
    'entrypoint': ['/app/bin/python', '-c', DAV_START],
    'mem_limit': '128m', 'tmpfs': ['/tmp'], 'read_only': True,
    'volumes': ['${APP_DATA_DIR}/data/radicale:/var/lib/radicale'],
    'command': ['--hosts', '0.0.0.0:5232', '--auth-type', 'htpasswd', '--auth-htpasswd-filename', '/var/lib/radicale/users',
                '--auth-htpasswd-encryption', 'sha512', '--rights-type', 'owner_only',
                '--storage-filesystem-folder', '/var/lib/radicale/collections'],
}}, 'x-runtipi': {'schema_version': 2, 'overrides': []}}
text = json.dumps(compose, indent=2) + '\n'
if '--check' in sys.argv:
    assert (root / 'runtipi/docker-compose.yml').read_text() == text, 'Regenerate runtime recipe'
    print('Source-package recipe matches')
else:
    (root / 'runtipi/docker-compose.yml').write_text(text)
    print('Source-package recipe generated')
