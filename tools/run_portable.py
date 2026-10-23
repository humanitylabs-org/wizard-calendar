#!/usr/bin/env python3
"""Run the portable source package without building an app image.
Named data/core volumes also work when a VM Docker daemon cannot bind the host checkout.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('action',choices=['start','stop','status'])
parser.add_argument('--project',default='calendar-test')
parser.add_argument('--port',type=int,default=18787)
parser.add_argument('--platform',choices=['linux/arm64','linux/amd64'],help='Optional runtime architecture')
args=parser.parse_args()
if not re.fullmatch(r'calendar-[a-z0-9-]{1,40}',args.project):parser.error('Project must begin calendar- followed by 1–40 lowercase letters, digits or hyphens')
if not 1024<=args.port<=65535:parser.error('Port must be 1024–65535')
root=Path(__file__).resolve().parents[1]
state=root/'.runtime';state.mkdir(exist_ok=True)
config=json.loads((root/'runtipi/docker-compose.yml').read_text())
image=config['services']['wizard-calendar']['image']
# Existing volume contents are retained; only the app-owned volume root gets its expected UID.
volume=args.project+'_data'; core=args.project+'_core'
origin=f'http://127.0.0.1:{args.port}'
override={'services':{'wizard-calendar':{'ports':[f'127.0.0.1:{args.port}:8799'],'environment':{'WIZARD_CORE_DIR':'/core','WIZARD_TRUSTED_HOSTS':f'127.0.0.1:{args.port},localhost:{args.port}','WIZARD_TRUSTED_ORIGINS':f'{origin},http://localhost:{args.port}'},'volumes':[{'type':'volume','source':'calendar-data','target':'/data'},{'type':'volume','source':'calendar-core','target':'/core','read_only':True}]}},'volumes':{'calendar-data':{'name':volume,'external':True},'calendar-core':{'name':core,'external':True}}}
if args.platform:override['services']['wizard-calendar']['platform']=args.platform
path=state/(args.project+'.json')
path.write_text(json.dumps(override,indent=2)+'\n')
env=dict(os.environ,APP_DATA_DIR=str(state/'unused-bind-target'))
cmd=['docker','compose','-p',args.project,'-f',str(root/'runtipi/docker-compose.yml'),'-f',str(path)]
if args.action=='start':
    subprocess.run([sys.executable,str(root/'tools/fetch_core.py')],check=True)
    helper=['docker','run','--rm','-i','--user','0:0','--network','none']
    if args.platform:helper+=['--platform',args.platform]
    helper+=['-v',volume+':/data','-v',core+':/core',image,'python','-c',"import os,sys; from pathlib import Path; os.chown('/data',1000,1000); os.chmod('/data',0o750); p=Path('/core/app-client.tmp'); p.write_bytes(sys.stdin.buffer.read()); p.replace('/core/app-client.js')"]
    subprocess.run(helper,input=(state/'core/app-client.js').read_bytes(),check=True)
    subprocess.run(cmd+['up','-d','--no-build','--force-recreate'],env=env,check=True)
    for attempt in range(45):
        try:
            with urllib.request.urlopen(origin+'/healthz',timeout=2) as response: health=json.load(response)
            if health.get('ok') and health.get('app')=='wizard-calendar': break
        except (OSError,ValueError): pass
        time.sleep(1)
    else: raise SystemExit('Calendar did not become healthy; inspect the Compose service logs. Data volume retained.')
    print(f'Calendar healthy: {origin}/. Data retained in {volume}.')
elif args.action=='stop':
    subprocess.run(cmd+['down'],env=env,check=True)
    print(f'Stopped. Data volume {volume} retained. No data deletion was requested.')
else:subprocess.run(cmd+['ps'],env=env,check=True)
