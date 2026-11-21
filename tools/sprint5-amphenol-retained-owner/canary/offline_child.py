"""Disposable dependency substitutions only; never used outside this fixture."""
import atexit, json, os, sys
from pathlib import Path

def audit(event, args):
    if event.startswith('socket.') or event in {'subprocess.Popen', 'os.exec', 'os.posix_spawn', 'os.system'}:
        raise AssertionError('Offline worker forbids network and subprocesses')
sys.addaudithook(audit)

def setup():
    root=Path.cwd().resolve()
    assert root.name=='project' and root.parent.parent==Path('/tmp/jsh-amphenol-recovery-canary.etk8w2mu')
    state=root/'.state'
    runtime=json.loads(os.environ['JSH_SCRAPER_RUNTIME_BINDING'])
    sys.path[:0]=[str(root/'src'),str(root/'tests')]
    def trace(frame,event,arg):
        if event=='return' and frame.f_code.co_name in {'freeze_exact_cycle_plans','_recover_exact_cycle_locked'} and isinstance(arg,dict):
            with (state/'publication-trace.jsonl').open('a') as stream:stream.write(json.dumps({'function':frame.f_code.co_name,'result':arg},sort_keys=True)+'\n')
    sys.setprofile(trace)
    from job_search_helper import ats
    def fetch(provider,url,cid,name):
        expected=json.loads((root/'provider-fixture.json').read_bytes())['company']
        assert (provider,url,cid,name)==(expected['ATS / Source'],expected['Official Careers URL'],expected['Company ID'],expected['Company'])
        with (state/'fetch-once').open('x') as stream: stream.write(runtime['release_id'])
        payload=json.loads((root/'provider-fixture.json').read_bytes())
        return ats.Inventory('complete',payload['jobs'],'frozen offline fixture',url,provider)
    assert 'job_search_helper.engine' not in sys.modules
    ats.fetch_inventory=fetch
    from job_search_helper import cli
    from job_search_helper.repository import GoogleRepository
    from job_search_helper.sheet_profile import COMPACT_SCHEMAS
    from sheets_fixture import RangeSheets
    def workbook(**kwargs):
        assert kwargs=={'write':True,'schemas':COMPACT_SCHEMAS,'evidence_archives':False}
        with (state/'workbook-once').open('x') as stream: stream.write(runtime['release_id'])
        service=RangeSheets(json.loads((root/'workbook-before.json').read_bytes()),schemas=COMPACT_SCHEMAS)
        remote=GoogleRepository(service,'fixture-sheet',schemas=COMPACT_SCHEMAS,min_request_interval=0)
        @atexit.register
        def save():
            (state/'workbook-after.json').write_text(json.dumps({'jobs':remote.read('Job History'),'companies':remote.read('Companies'),'batches':len(service.batches)},sort_keys=True))
        return remote
    cli.get_remote_repository=workbook
    with (state/'workers.jsonl').open('a') as stream:
        stream.write(json.dumps({'pid':os.getpid(),'runtime':runtime},sort_keys=True)+'\n')
if 'JSH_SCRAPER_RUNTIME_BINDING' in os.environ: setup()
