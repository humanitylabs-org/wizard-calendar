#!/usr/bin/env python3
"""Generate deterministic portable Runtipi source payload; no unpublished app image."""
import base64
import json
from pathlib import Path
root = Path(__file__).resolve().parents[1]
files = ['app/server.py', 'openapi.json'] + sorted('web/' + p.name for p in (root / 'web').iterdir() if p.is_file())
payload = {p: (root / p).read_text() for p in files}
blob = base64.b64encode(json.dumps(payload, sort_keys=True).encode()).decode()
code = ("import base64,json,pathlib,runpy\nroot=pathlib.Path('/tmp/wizard-app');root.mkdir(exist_ok=True)\n"
        + f"files=json.loads(base64.b64decode('{blob}'))\n"
        + "for name,text in files.items():\n p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)\n"
        + "runpy.run_path(str(root/'app/server.py'),run_name='__main__')\n")
image = (root / 'app/Dockerfile').read_text().splitlines()[0].split()[1]
compose = {'services': {'wizard-calendar': {'image': image, 'user': '1000:1000', 'cap_drop': ['ALL'], 'security_opt': ['no-new-privileges:true'], 'mem_limit':'256m', 'tmpfs':['/tmp'], 'read_only':True,
 'environment': {'BIND':'0.0.0.0','PORT':'8799','DATA_DIR':'/data','PYTHONDONTWRITEBYTECODE':'1','CALENDAR_TIMEZONE':'${CALENDAR_TIMEZONE:-UTC}','WIZARD_TRUSTED_HOSTS':'${WIZARD_TRUSTED_HOSTS:-}','WIZARD_TRUSTED_ORIGINS':'${WIZARD_TRUSTED_ORIGINS:-}','WIZARD_LOCAL_HOSTS':'127.0.0.1:${APP_PORT},localhost:${APP_PORT},wizard-calendar:8799'},
 'volumes':['${APP_DATA_DIR}/data:/data'], 'command':['python','-c',code], 'x-runtipi':{'is_main':True,'internal_port':8799}}}, 'x-runtipi':{'schema_version':2,'overrides':[]}}
(root / 'runtipi/docker-compose.yml').write_text(json.dumps(compose, indent=2) + '\n')
print('Portable runtime payload generated')
