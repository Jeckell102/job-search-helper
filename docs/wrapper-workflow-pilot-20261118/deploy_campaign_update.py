"""Deploy the tested one-company campaign controls with rollback evidence."""
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import time

stage = Path(__file__).resolve().parent
base = Path('/home/chris/job-search-helper_old/dev/wrapper-coder')
tools = base/'tools'
tasks = base/'tasks'
archive = base/'repairs'/('campaign-coordinator-'+time.strftime('%Y%m%d-%H%M%S'))
names = ['backfill_campaign_metadata.py','coordinator.py','coordinator_store.py',
         'import_integration_backlog.py','test_backfill_campaign_metadata.py',
         'test_coordinator_queue.py','test_coordinator_workflow.py',
         'test_import_integration_backlog.py','test_wrapper_commands.py','wrapper_task.py']

def active():
    with sqlite3.connect('file:'+str(tasks/'tasks.sqlite3')+'?mode=ro', uri=True) as db:
        return [json.loads(row[0])['id'] for row in db.execute('select state from tasks')
                if json.loads(row[0])['status'] in ('RUNNING','QUEUED','PAUSING')]

if active():
    raise RuntimeError('Active coordinator tasks prevent deployment: '+', '.join(active()))
archive.mkdir(parents=True, mode=0o700)
(archive/'before').mkdir(); (archive/'after').mkdir()
for name in names:
    src=stage/'host'/name; dst=tools/name
    if dst.exists(): shutil.copy2(dst, archive/'before'/name)
    shutil.copy2(src, archive/'after'/name)
shutil.copy2(stage/'WORKFLOW.md', archive/'WORKFLOW.md')
subprocess.run(['systemctl','--user','stop','wrapper-development-host.service'],check=True)
try:
    if active(): raise RuntimeError('Task became active while stopping service.')
    with sqlite3.connect(tasks/'tasks.sqlite3') as db, sqlite3.connect(archive/'tasks-before.sqlite3') as out:
        db.backup(out)
        assert out.execute('pragma quick_check').fetchone()[0]=='ok'
    for name in names:
        src=stage/'host'/name; dst=tools/name; tmp=tools/(name+'.new')
        tmp.write_bytes(src.read_bytes()); os.chmod(tmp,0o600); tmp.replace(dst)
    campaign=base/'campaign-autopilot-20261118'
    if campaign.exists(): shutil.rmtree(campaign)
    campaign.mkdir()
    batches=[]
    for src in sorted((stage/'backlog').glob('batch-*.json')):
        dst=campaign/src.name; shutil.copy2(src,dst); batches.append(str(dst))
    subprocess.run(['/home/chris/job-search-helper_old/.venv/bin/python',str(tools/'backfill_campaign_metadata.py'),
                    str(tasks),*batches],check=True,cwd=tools,stdout=(archive/'metadata-migration.json').open('w'))
    with sqlite3.connect(tasks/'tasks.sqlite3') as db:
        for key in ('queue_enabled','autopilot_enabled'):
            db.execute('insert into settings values (?,?) on conflict(key) do update set value=excluded.value',(key,'false'))
    shutil.copy2(stage/'WORKFLOW.md',base/'PERSISTENT_WORKFLOW.md')
finally:
    subprocess.run(['systemctl','--user','start','wrapper-development-host.service'],check=True)
print(json.dumps({'archive':str(archive),'installed':names,'campaign':'paused'}))
