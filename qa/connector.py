#!/usr/bin/env python3
"""Unit fixture for the adapter boundary, not proof of live Google connectivity."""
import importlib.util
import json
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('adapter',root/'tools/gog_import.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
cfg={'account':'fixture@example.invalid','calendars':[{'id':'primary','name':'Synthetic'}],'timezone':'UTC'}
event={'id':'one','summary':'Synthetic provider event','start':{'dateTime':'2026-10-15T10:00:00Z'},'end':{'dateTime':'2026-10-15T11:00:00Z'}}
commands=[]
def run(args, **kwargs):
    commands.append(args)
    return SimpleNamespace(returncode=0,stdout=json.dumps({'events':[event,event,dict(event,id='declined',attendees=[{'self':True,'responseStatus':'declined'}])]}))
with patch.object(m.subprocess,'run',run):
    doc=m.export(cfg,'gog-fixture')
assert len(doc['events'])==1 and doc['events'][0]['id']=='primary::one'
assert '--readonly' in commands[0] and '--all-pages' in commands[0] and '--no-input' in commands[0]
for result in [SimpleNamespace(returncode=1,stdout=''),SimpleNamespace(returncode=0,stdout=json.dumps({'events':[event],'nextPageToken':'incomplete'}))]:
    with patch.object(m.subprocess,'run',return_value=result):
        try: m.export(cfg,'gog-fixture')
        except (ValueError,RuntimeError): pass
        else: raise AssertionError('Failure did not abort')
print(json.dumps({'ok':True,'checks':['normalization','duplicate suppression','declined exclusion','read-only all-pages flags','provider failure abort','partial-page abort'],'liveProvider':False}))
