#!/usr/bin/env python3
"""Thales-only release runner; invoke under the shared heavy-job lock.
Builds pushed source, exercises empty installs + recreation, exports private test images.
"""
import argparse
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import time
import urllib.request
import uuid
from pathlib import Path

p=argparse.ArgumentParser(); p.add_argument('--out',required=True,type=Path); args=p.parse_args()
root=Path(__file__).resolve().parents[1]
out=args.out.resolve(); out.mkdir(parents=True,exist_ok=True)

def run(*cmd,**kw):
    return subprocess.run(cmd,check=True,cwd=root,**kw)

def output(*cmd):
    return subprocess.check_output(cmd,cwd=root,text=True).strip()

def get(url):
    with urllib.request.urlopen(url,timeout=5) as response:return json.load(response)

def ready(url):
    for _ in range(60):
        try:return get(url+'/healthz')
        except Exception:time.sleep(1)
    raise RuntimeError('Container did not become ready')

sha=output('git','rev-parse','HEAD')
assert not output('git','status','--porcelain','--untracked-files=no'),'Dirty tracked source'
remote=output('git','ls-remote','origin','refs/heads/feature/calendar-portable-test-20261015').split()[0]
assert remote==sha,'Must push before release build'
results={'commit':sha,'architectures':[],'liveProvider':False}
for arch,port in [('arm64',18787),('amd64',18788)]:
    tag=f'wizard-calendar-test:0.1.0-{arch}'
    run('docker','build','--platform',f'linux/{arch}','-f','app/Dockerfile','-t',tag,'--label',f'org.opencontainers.image.revision={sha}','.')
    info=json.loads(output('docker','image','inspect',tag))[0]
    assert info['Architecture']==arch
    name='calendar-qa-'+uuid.uuid4().hex[:10]
    volume=name+'-data'
    run('docker','volume','create',volume)
    url=f'http://127.0.0.1:{port}'
    def start():
        run('docker','run','-d','--name',name,'--platform',f'linux/{arch}','--read-only','--cap-drop=ALL','--security-opt=no-new-privileges','--tmpfs','/tmp','-p',f'127.0.0.1:{port}:8799','-e',f'WIZARD_TRUSTED_HOSTS=127.0.0.1:{port},localhost:{port}','-e',f'WIZARD_TRUSTED_ORIGINS={url},http://localhost:{port}','-e','WIZARD_CORE_DIR=/core','-v',f'{volume}:/data','-v',f'{root}/.runtime/core:/core:ro',tag)
        ready(url)
    try:
        start()
        with (out/f'api-{arch}.json').open('w') as f:run('python3','qa/api.py','--url',url,stdout=f)
        before=get(url+'/api/export')
        run('docker','restart',name);ready(url)
        assert get(url+'/api/export')==before,'Restart lost data'
        run('docker','rm','-f',name);start()
        assert get(url+'/api/export')==before,'Recreate/update lost data'
        browser_result=None
        if arch=='arm64':
            env=dict(os.environ,CALENDAR_URL=url,QA_OUT=str(out))
            run('node','qa/browser.cjs',env=env)
            run('node','qa/hosted.cjs',env=env)
            browser_result='browser.json + hosted.json'
        path=out/f'wizard-calendar-0.1.0-linux-{arch}.tar.gz'
        proc=subprocess.Popen(['docker','image','save',tag],stdout=subprocess.PIPE)
        with path.open('wb') as f, gzip.GzipFile(fileobj=f,mode='wb',mtime=0) as compressed:
            shutil.copyfileobj(proc.stdout,compressed)
        assert proc.wait()==0
        digest=hashlib.sha256()
        with path.open('rb') as f:
            for block in iter(lambda:f.read(1024*1024),b''):digest.update(block)
        results['architectures'].append({'architecture':arch,'image':tag,'imageId':info['Id'],'registryDigest':None,'artifact':path.name,'sha256':digest.hexdigest(),'bytes':path.stat().st_size,'emptyInstall':True,'apiReceipt':f'api-{arch}.json','restartPreserved':True,'recreatePreserved':True,'browser':browser_result})
        (out/'images.json').write_text(json.dumps(results,indent=2)+'\n')
    finally:
        subprocess.run(['docker','rm','-f',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        run('docker','volume','rm',volume)
print(json.dumps(results,indent=2))
