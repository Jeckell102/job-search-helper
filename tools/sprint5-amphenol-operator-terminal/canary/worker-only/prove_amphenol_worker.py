"""Actual qualified owner/launcher/worker with fresh synthetic operator origin."""
from contextlib import closing,redirect_stdout
from hashlib import sha256
from io import StringIO
import json,os,shutil,sqlite3,subprocess,sys,traceback
from pathlib import Path
from tempfile import mkdtemp
HERE=Path(__file__).resolve().parent
SOURCE=Path('/home/chris/job-search-helper_old')
STAGED=Path('/tmp/jsh-operator-owned-bridge.xu59ooer')
TARGET='src/job_search_helper/acquiretm.py'
PINS={'src/job_search_helper/qualified_release_owner.py':'5cf4e70829ad40d797dde4779cb6a1f0a75953f303ed330c0610ee7f0e5b23e6','src/job_search_helper/runner.py':'de3c0f5045e1ad07d0b1e2e8b1da8b8dbce2acd3767182ddf9d1c7dbbaefb87b','job-search-scraper':'8fb9939560f004a213ca94724cdada7734996072c31194679017fea492841f72','release_admission_bootstrap.py':'1258ac47b647d61361fa84ccdda14816a184e6c15cd4c6e7c78e6b27cd228d45'}
def sha(path):return sha256(path.read_bytes()).hexdigest()
def write(path,value):path.write_text(json.dumps(value,sort_keys=True,indent=2)+'\n')
def snapshot(directory):
    result={}
    for name in ('state.db','jobs.sqlite3','inventories.sqlite3'):
        with closing(sqlite3.connect((directory/name).as_uri()+'?mode=ro',uri=True)) as db:result[name]=list(db.iterdump())
    return result

def main():
    sys.addaudithook(lambda event,args: (_ for _ in ()).throw(AssertionError('No network')) if event.startswith('socket.') else None)
    root=Path(mkdtemp(prefix='run-',dir=HERE));print(root,flush=True)
    write(HERE/'LATEST.json',{'root':str(root)})
    project=root/'project';candidate=root/'candidate';approval=root/'approval'
    project.mkdir(mode=0o700);approval.mkdir(mode=0o700)
    for name,pin in PINS.items():assert sha(SOURCE/name)==pin,(name,sha(SOURCE/name))
    # Only Python application sources; no native data, configuration or credentials.
    for path in (SOURCE/'src/job_search_helper').rglob('*.py'):
        rel=path.relative_to(SOURCE);target=project/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
    for name in ('job-search-scraper','release_admission_bootstrap.py'):shutil.copy2(SOURCE/name,project/name)
    shutil.copytree(STAGED/'tests',project/'tests',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    for name,body in (('.storage-backend','sqlite\n'),('requirements.txt','# Offline standard library fixture\n'),('title-blacklist.txt',''),('title-review-list.txt','')):(project/name).write_text(body)
    subprocess.run([sys.executable,'-m','venv','--without-pip',str(project/'.venv')],check=True)
    site=next((project/'.venv/lib').glob('python*/site-packages'))
    shutil.copy2(HERE/'offline_child.py',site/'offline_child.py');(site/'offline_child.pth').write_text('import offline_child\n')
    shutil.copytree(project/'src',candidate/'src')
    for name in ('.storage-backend','requirements.txt','title-blacklist.txt','title-review-list.txt'):shutil.copy2(project/name,candidate/name)
    with (candidate/TARGET).open('a') as stream:stream.write('\n# Disposable qualified-owner worker contract fixture.\n')
    directory=project/'.state';directory.mkdir(mode=0o700)
    for key in list(os.environ):
        if key.startswith(('JOB_','JSH_','WRAPPER_','COMPANY_RETAINED_','GOOGLE_')) or key in {'SPREADSHEET_ID','STATE_DB_FILE','EVIDENCE_ARCHIVES_FILE'}:os.environ.pop(key)
    os.environ.update(JOB_STORAGE_BACKEND='sqlite',STATE_DB_FILE='.state/state.db',JOB_DB_FILE='.state/jobs.sqlite3',SPREADSHEET_ID='fixture-sheet',PYTHONDONTWRITEBYTECODE='1')
    sys.path[:0]=[str(project/'src'),str(project/'tests')]
    from job_search_helper.ats import Inventory
    from job_search_helper.company_events import current_company_source_revision
    from job_search_helper.engine import Engine,State
    from job_search_helper.inbox import InventoryInbox
    from job_search_helper.integration_release import MANIFEST_SCHEMA,config_tree_digest,dependency_manifest_digest,digest,manifest_release_id,metadata,source_tree_digest
    from job_search_helper.operator_company_request import queue_operator_company_request
    from job_search_helper.qualified_release_owner import release_and_continue_qualified
    from job_search_helper.repository import SCHEMAS
    from job_search_helper.scan_request import requested_scan
    from job_search_helper.sheet_profile import COMPACT_PROFILE
    from job_search_helper.sqlite_repository import SQLiteRepository
    from job_search_helper.exact_cycle_receipt import repair_retry_has_confirmed_publication
    company={'Company ID':'COMP-0490','Company':'Amphenol Aerospace','Company Status':'Active','ATS / Source':'AcquireTM','Official Careers URL':'https://amphenol-aerospace.acquiretm.com/home.aspx'}
    other={'Company ID':'COMP-OTHER','Company':'Other Fixture','Company Status':'Active','ATS / Source':'Greenhouse','Official Careers URL':'https://boards.greenhouse.io/fixture-other'}
    other_job={'Job Key':'other-existing','Company':'Other Fixture','Job Title':'Untouched fixture job','Job URL':'https://example.invalid/other'}
    request_id='operator-amphenol-disposable-qualification-proof'
    db=directory/'state.db';jobs_path=directory/'jobs.sqlite3'
    try:
        with closing(State(db)) as state,closing(SQLiteRepository(jobs_path,'fixture-sheet',initialize=True)) as jobs,closing(InventoryInbox(directory/'inventories.sqlite3','fixture-sheet')) as inbox:
            for tab in SCHEMAS:jobs.import_rows(tab,enumerate([company,other] if tab=='Companies' else [other_job] if tab=='Job History' else [],2))
            jobs.set_meta('ready','yes');jobs.set_meta('sheets_profile',COMPACT_PROFILE);jobs.ensure_columns('Opportunities',['Opportunity ID'])
            write(project/'workbook-before.json',{'Companies':jobs.read('Companies'),'Job History':jobs.read('Job History')})
            assert queue_operator_company_request(jobs,directory,company['Company ID'],request_id)['state']=='REQUEST_WRITTEN'
            from unittest.mock import patch
            from job_search_helper.cli import writer_lock
            from job_search_helper.operator_amphenol_settlement import settle_operator_amphenol
            from job_search_helper.operator_company_request import _digest
            from job_search_helper.ordinary_event_settlement import ACQUIRETM_PAGINATION_CODE
            request=json.loads((directory/'next-scan.json').read_bytes())
            engine=Engine(jobs,state,inbox=inbox,runtime_binding={'state':'NO_RELEASE','source_manifest_sha256':source_tree_digest(project)})
            with writer_lock(directory/'scraper.lock'),writer_lock(directory/'writer.lock'):
                original=requested_scan(engine,state,db)
                observation={'sha256':'b'*64,'inventory_sha256':'c'*64,'inventory':{'outcome_failure':{'evidence_code':ACQUIRETM_PAGINATION_CODE}}}
                with patch('job_search_helper.operator_amphenol_settlement.load_operator_amphenol_partial',return_value=observation):
                    settled=settle_operator_amphenol(engine,request_sha256=_digest(request))
                assert settled['state']=='FETCH_REPAIR_QUALIFIED' and settled['cycle_id']==original
            prior=state.cycle(original)
            assert prior['status']=='Complete with exceptions',prior
            assert prior['operator_request']['request_id']==request_id and not prior.get('company_event')
            mirror=jobs.matches('Scan Cycles',{'Cycle ID':original})[0][1]
            saved_other=jobs.matches('Companies',{'Company ID':'COMP-OTHER'})[0][1];saved_job=jobs.matches('Job History',{'Job Key':'other-existing'})[0][1]
            revision_value=current_company_source_revision(jobs,company['Company ID'])
        assert not (directory/'company-event-bridge').exists()
        request_archive=(directory/'last-scan-request.json').read_bytes()
        posting={'company_id':company['Company ID'],'company':company['Company'],'ats':'AcquireTM','posting_id':'fixture-1','url':company['Official Careers URL']+'/jobs/fixture-1','title':'Field Applications Engineer','description':'Integrate products and support technical customers. '*80,'location':'Ohio','work_arrangement':'Hybrid','compensation':'$140k-$180k annual base','is_listed':True}
        write(project/'provider-fixture.json',{'jobs':[posting],'company':company})
        def revision(cid):
            with closing(SQLiteRepository(jobs_path,'fixture-sheet',readonly=True)) as jobs:return current_company_source_revision(jobs,cid)
        verification={'result':'PASS','fixture_only':True,'source_manifest_sha256':source_tree_digest(candidate),'config_sha256':config_tree_digest(candidate)}
        manifest={'schema':MANIFEST_SCHEMA,'company_id':company['Company ID'],'source_revision':revision_value,'failed_request_id':request_id,'files':{TARGET:{'before':metadata(project/TARGET),'after':metadata(candidate/TARGET)}},'before_source_manifest_sha256':source_tree_digest(project),'source_manifest_sha256':source_tree_digest(candidate),'dependency_manifest_sha256':dependency_manifest_digest(project),'before_config_sha256':config_tree_digest(project),'config_sha256':config_tree_digest(candidate),'validation_receipt_sha256':digest(verification)}
        manifest['release_id']=manifest_release_id(manifest);write(root/'manifest.json',manifest)
        ticket=approval/(manifest['release_id']+'.json')
        # Exact authority-shape fixture only. This is NOT live qualification.
        write(ticket,{'schema':'integration-live-release-qualification-v1','result':'PASS','evidence_class':'live_normal_dispatch','release_qualification':True,'manifest_sha256':digest(manifest),'capture_manifest_sha256':sha(project/'provider-fixture.json'),'candidate_validation_sha256':digest(verification),'reviewed_tools_sha256':sha(HERE/'offline_child.py')});ticket.write_text(json.dumps(json.loads(ticket.read_text()),sort_keys=True,separators=(',',':')));ticket.chmod(0o600)
        info=approval.stat();checks=[]
        def verify(installed,expected):
            assert installed==project and expected==manifest
            assert source_tree_digest(project)==manifest['source_manifest_sha256'] and config_tree_digest(project)==manifest['config_sha256']
            checks.append(True);return verification
        def invoke():
            descriptor=os.open(approval,os.O_RDONLY|os.O_DIRECTORY)
            try:return release_and_continue_qualified(project,candidate,db,root/'records',manifest,approval_path=approval,approval_fd=descriptor,owner_identity=(info.st_dev,info.st_ino),approval_sha256=sha(ticket),current_source_revision=revision,dependency_digest=lambda:dependency_manifest_digest(project),verify=verify)
            except subprocess.CalledProcessError as exc:
                (root/'worker.stdout').write_text(exc.stdout);(root/'worker.stderr').write_text(exc.stderr);raise
            finally:os.close(descriptor)
        first=invoke();write(root/'FIRST.json',first)
        assert first['retry']['state']=='COMPLETE',first
        cycle_id=first['retry']['cycle_id'];outcome=first['retry']['outcome']
        assert outcome['identity']['failed_request_id']==request_id
        with closing(State(db,readonly=True)) as state,closing(SQLiteRepository(jobs_path,'fixture-sheet',readonly=True)) as jobs,closing(InventoryInbox(directory/'inventories.sqlite3','fixture-sheet',readonly=True)) as inbox:
            cycle=state.cycle(cycle_id);assert cycle['status']=='Complete' and set(cycle['companies'])=={company['Company ID']}
            assert repair_retry_has_confirmed_publication(inbox,jobs,cycle,company['Company ID'])
            assert state.cycle(original)==prior and jobs.matches('Scan Cycles',{'Cycle ID':original})[0][1]==mirror
            assert jobs.matches('Companies',{'Company ID':'COMP-OTHER'})[0][1]==saved_other and jobs.matches('Job History',{'Job Key':'other-existing'})[0][1]==saved_job
            local=[r['Job Key'] for r in jobs.read('Job History') if r['Company']==company['Company']]
        workbook=json.loads((directory/'workbook-after.json').read_bytes());remote=[r['Job Key'] for r in workbook['jobs'] if r['Company']==company['Company']]
        assert local==remote and len(local)==1 and workbook['batches']==1,(local,remote,workbook['batches'])
        before=snapshot(directory);second=invoke();assert second['retry']==first['retry'] and snapshot(directory)==before and len(checks)==1
        workers=[json.loads(s) for s in (directory/'workers.jsonl').read_text().splitlines()];assert len(workers)==2 and len({r['pid'] for r in workers})==2
        assert all(r['runtime']['release_id']==manifest['release_id'] for r in workers)
        assert not (directory/'company-event-bridge').exists()
        assert (directory/'operator-company-requests/receipts').is_dir()
        result={'result':'PASS_WORKER_ONLY','origin':'real_synthetic_operator_request','failed_request_id':request_id,'release_id':manifest['release_id'],'attempt_id':first['release']['attempt_id'],'cycle_id':cycle_id,'outcome_id':outcome['outcome_id'],'jobs':len(local),'fixture_batches':workbook['batches'],'provider_fixture_calls':1,'workbook_fixture_calls':1,'measured_workers':len(workers),'original_cycle_unchanged':True,'unrelated_rows_unchanged':True,'native_qualification':False,'host_completion_exercised':False,'company_event_route_used':False,'source_pins':PINS}
        write(root/'RESULT.json',result);print(json.dumps(result,sort_keys=True),flush=True)
    except Exception as exc:
        write(root/'FAILURE.json',{'type':type(exc).__name__,'error':str(exc),'traceback':traceback.format_exc(),'native_qualification':False})
        raise
if __name__=='__main__':main()
