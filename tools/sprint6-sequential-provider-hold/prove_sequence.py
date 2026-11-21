"""One disposable external-hold -> unrelated exact-publication sequence."""
from contextlib import closing
from hashlib import sha256
import copy,json,os,sys
from pathlib import Path
from tempfile import mkdtemp
from unittest.mock import Mock,patch
ROOT=Path(__file__).resolve().parent
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests'),str(ROOT/'dev/wrapper-coder/tools'),'/tmp/jsh-s5-review-pytest-dependencies','/usr/lib/python3/dist-packages']
def deny_network(event,args):
    if event in ('socket.connect','socket.bind','socket.getaddrinfo','socket.gethostbyname'):
        raise RuntimeError('S6 disposable proof forbids network')
sys.addaudithook(deny_network)
from job_search_helper import ats,cli
from job_search_helper.acquiretm import SOURCE
from job_search_helper.company_events import BRIDGE_CONSUMER,CompanyEventBridge,_json_digest
from job_search_helper.engine import State
from job_search_helper.inbox import InventoryInbox
from job_search_helper.ordinary_company_event_command import execute_ordinary_event
from job_search_helper.ordinary_event_settlement import ordinary_event_outcome_settled
from job_search_helper.repository import GoogleRepository
from job_search_helper.scrape_outcome_delivery import CONSUMER,OutcomeDelivery
from job_search_helper.sheet_profile import COMPACT_PROFILE,COMPACT_SCHEMAS
from job_search_helper.sqlite_repository import SQLiteRepository
from coordinator import Coordinator
from coordinator_receipt_host_bridge import ManualReceiptV1HostBridge
from sheets_fixture import RangeSheets
RUNTIME={'state':'NO_RELEASE','source_manifest_sha256':'a'*64,'config_sha256':'b'*64,'dependency_manifest_sha256':'c'*64}
work=Path(mkdtemp(prefix='runtime-',dir=ROOT))
state_path=work/'state.db';jobs_path=work/'jobs.sqlite3'
os.environ.update(JOB_STORAGE_BACKEND='sqlite',SPREADSHEET_ID='sheet',STATE_DB_FILE=str(state_path),JOB_DB_FILE=str(jobs_path))
archive=Path('/tmp/jsh-s5-amphenol-release-rehearsal/captured-retry-inventory.private.json')
archive_sha='94250320f27fbf987f417405599f609de6ea965feb41f1b6297cfee57dba5fa8'
assert sha256(archive.read_bytes()).hexdigest()==archive_sha
captured=json.loads(archive.read_bytes());assert captured['inventory_status']=='complete' and len(captured['jobs'])==39
BLOCKED='COMP-7001';SUCCESS='COMP-0490'
board='https://jobs.eu.lever.co/acme?location=Berlin';observed='https://api.eu.lever.co/v0/postings/acme?location=Berlin'
blocked={'Company ID':BLOCKED,'Company':'Fixture external hold','Company Status':'Active','ATS / Source':'Lever','Official Careers URL':'https://jobs.eu.lever.co/acme'}
success={'Company ID':SUCCESS,'Company':'Amphenol Aerospace','Company Status':'Active','ATS / Source':'AcquireTM','Official Careers URL':SOURCE.replace('home.aspx','old.aspx')}
unrelated={'Company ID':'COMP-9999','Company':'Unrelated fixture','Company Status':'Paused','ATS / Source':'Greenhouse','Official Careers URL':'https://job-boards.greenhouse.io/untouched'}
estimate = 'Estimated $120000-$150000'
keep_job = {
    'Job Key': 'comp-9999:manual:preserve',
    'Company': 'Unrelated fixture',
    'Job Title': 'Preserved manual role',
    'Requisition ID': 'preserve',
    'Official Job URL': 'https://example.test/preserve',
    'Job Status': 'Open and verified',
    'Salary / Range': estimate,
}
keep_opp={'Opportunity ID':'OPP-keep'}
with (closing(State(str(state_path))),closing(InventoryInbox(work/'inventories.sqlite3','sheet')),
      closing(SQLiteRepository(jobs_path,'sheet',initialize=True)) as repo):
    repo.set_meta('ready','yes');repo.set_meta('sheets_profile',COMPACT_PROFILE)
    repo.ensure_columns('Opportunities',['Opportunity ID'])
    repo.import_rows('Companies',[(2,blocked),(3,success),(4,unrelated)])
    repo.import_rows('Job History',[(2,keep_job)]);repo.import_rows('Opportunities',[(2,keep_opp)])
fixture=RangeSheets({'Companies':[{**blocked,'Official Careers URL':board},{**success,'Official Careers URL':SOURCE},unrelated],
                     'Job History':[keep_job],'Opportunities':[keep_opp]},schemas=COMPACT_SCHEMAS)
remote=GoogleRepository(fixture,'sheet',schemas=COMPACT_SCHEMAS,min_request_interval=0)
with closing(SQLiteRepository(jobs_path, 'sheet', readonly=True)) as seed_repo:
    [seed_local_job] = seed_repo.matches('Job History', {'Job Key': keep_job['Job Key']})
    assert seed_local_job[1]['Salary / Range'] == estimate
[seed_sheet_job] = [row for row in remote.read('Job History') if row['Job Key'] == keep_job['Job Key']]
assert seed_sheet_job['Salary / Range'] == estimate
coordinator=Coordinator(base=work/'coordinator',model=Mock(side_effect=AssertionError('No inference for block or complete')))
coordinator.command({'action':'queue-pause'})
factory_calls=[];provider_calls=[];ownership_checks=[]
def check_owner(company_id):
    for name in ('scraper.lock','writer.lock'):
        try:
            with cli.writer_lock(work/name):raise AssertionError('Missing application lease '+name)
        except cli.WriterLockBusy:pass
    with closing(State(str(state_path),readonly=True)) as state:
        active=[c for c in state.cycles() if c['status'] not in {'Complete','Complete with exceptions'}]
        assert len(active)==1 and set(active[0]['companies'])=={company_id}
        ownership_checks.append(active[0]['id'])
def provider(provider,url,cid,name):
    check_owner(cid);provider_calls.append(cid)
    if cid==BLOCKED:
        assert (provider,url,name)==('Lever',board,blocked['Company'])
        return ats.Inventory('blocked',source_url=observed,ats='Lever',outcome_failure=ats.outcome_failure('access_denied','public_access_denied'))
    assert (provider,url,cid,name)==('AcquireTM',SOURCE,SUCCESS,success['Company'])
    return ats.Inventory('complete',captured['jobs'],captured['reason'],SOURCE,'AcquireTM')
def workbook(*,write,interactive,schemas,evidence_archives):
    assert interactive is False and schemas==COMPACT_SCHEMAS and not evidence_archives
    factory_calls.append(write);return remote
def create_event(cid,url):
    with closing(SQLiteRepository(jobs_path,'sheet')) as repo:
        event=repo.mutate_company_with_event({'tab':'Companies','identity':{'Company ID':cid},'values':{'Official Careers URL':url}})['company_event']
        CompanyEventBridge(repo,work).process_pending()
    return event
def queued_request(cid,event):
    request=json.loads((work/'next-scan.json').read_bytes())
    assert request['company_ids']==[cid] and request['company_event']['event_id']==event['event_id']
    return request,_json_digest(request)
def execute(action,digest,cycle=None):
    with cli.writer_lock(work/'scraper.lock'):
        return execute_ordinary_event(action,(state_path,jobs_path,RUNTIME),request_sha256=digest,cycle_id=cycle)
def deliver(outcome):
    with closing(SQLiteRepository(jobs_path,'sheet')) as repo:
        assert ordinary_event_outcome_settled(repo,outcome)
        result=ManualReceiptV1HostBridge(coordinator,lambda:repo,enabled=True).manual_drain(outcome_id=outcome['outcome_id'])
        assert result['results']==[{'outcome_id':outcome['outcome_id'],'disposition':'ACCEPTED'}]
        [row]=repo._outcome_delivery_rows(CONSUMER,outcome_id=outcome['outcome_id'])
        record,_,stale,ack,_=OutcomeDelivery(repo,None)._preflight(row)
        assert record==outcome and ack and not stale
        sender=json.loads(row[6])
    with coordinator.store.connect() as db:
        receiver=json.loads(db.execute('SELECT receipt FROM scrape_outcome_delivery_receipts WHERE consumer=? AND outcome_id=?',(CONSUMER,outcome['outcome_id'])).fetchone()[0])
    assert sender==receiver
    return sender
with patch.object(ats,'fetch_inventory',side_effect=provider),patch.object(cli,'get_remote_repository',side_effect=workbook):
    req_a,sha_a=queued_request(BLOCKED,create_event(BLOCKED,board))
    admitted_a=execute('admit-fetch',sha_a);cycle_a=admitted_a['cycle_id']
    assert admitted_a['state']=='INVENTORY_FROZEN'
    event_b=create_event(SUCCESS,SOURCE)
    assert not (work/'next-scan.json').exists()
    with closing(SQLiteRepository(jobs_path,'sheet',readonly=True)) as repo:
        assert repo.pending_company_events(BRIDGE_CONSUMER)==[event_b]
    assert provider_calls==[BLOCKED]
    blocked_result=execute('publish',sha_a,cycle_a)
    assert blocked_result['state']=='FETCH_BLOCKED' and blocked_result['outcome']['outcome']=='BLOCKED'
    assert fixture.batches==[] and not any(factory_calls)
    receipt_a=deliver(blocked_result['outcome'])
    assert receipt_a['sink_status']=='RECORDED_NO_REPAIR' and not coordinator.store.held_repair_intake() and not coordinator.store.all()
    with (closing(State(str(state_path),readonly=True)) as state,closing(SQLiteRepository(jobs_path,'sheet',readonly=True)) as repo):
        saved_a=state.cycle(cycle_a);assert saved_a['status']=='Complete with exceptions'
        protected_a=repo.matches('Companies',{'Company ID':BLOCKED})
        protected_company=repo.matches('Companies',{'Company ID':'COMP-9999'})
        protected_job=repo.matches('Job History',{'Job Key':keep_job['Job Key']})
        protected_opp=repo.read('Opportunities')
        assert protected_job == [seed_local_job]
        [protected_sheet_job] = [
            row for row in remote.read('Job History') if row['Job Key'] == keep_job['Job Key']
        ]
        assert protected_sheet_job == seed_sheet_job
    # New objects reopen the same durable coordinator owner after the first hold.
    coordinator=Coordinator(base=work/'coordinator',model=Mock(side_effect=AssertionError('No inference')))
    assert not coordinator.store.queue_enabled() and not coordinator.store.campaign_enabled()
    with closing(SQLiteRepository(jobs_path,'sheet')) as repo:
        CompanyEventBridge(repo,work).process_pending()
    req_b,sha_b=queued_request(SUCCESS,event_b)
    admitted_b=execute('admit-fetch',sha_b);cycle_b=admitted_b['cycle_id'];assert cycle_b!=cycle_a
    assert admitted_b['state']=='INVENTORY_FROZEN' and admitted_b['job_count']==39
    success_result=execute('publish',sha_b,cycle_b)
    assert success_result['state']=='SYNC_CONFIRMED',success_result.get('state')
    with closing(SQLiteRepository(jobs_path,'sheet',readonly=True)) as repo:
        found=[r for r in repo.scrape_outcomes() if r['identity']['request_id']==req_b['request_id']]
    assert len(found)==1 and found[0]['outcome']=='COMPLETE'
    receipt_b=deliver(found[0])
    saved_batches=copy.deepcopy(fixture.batches)
    with patch.object(ats,'fetch_inventory',side_effect=AssertionError('Terminal replay refetched')),patch.object(cli,'get_remote_repository',side_effect=AssertionError('Terminal replay opened workbook')):
        assert execute('publish',sha_a,cycle_a)==blocked_result
        assert execute('publish',sha_b,cycle_b)==success_result
    assert fixture.batches==saved_batches
with (closing(State(str(state_path),readonly=True)) as state,closing(SQLiteRepository(jobs_path,'sheet',readonly=True)) as repo,
      closing(InventoryInbox(work/'inventories.sqlite3','sheet')) as inbox):
    final_a=state.cycle(cycle_a);final_b=state.cycle(cycle_b)
    assert final_a==saved_a and final_b['status']=='Complete'
    assert repo.matches('Companies',{'Company ID':BLOCKED})==protected_a
    assert repo.matches('Companies',{'Company ID':'COMP-9999'})==protected_company
    assert repo.matches('Job History',{'Job Key':keep_job['Job Key']})==protected_job and repo.read('Opportunities')==protected_opp
    [final_sheet_job] = [
        row for row in remote.read('Job History') if row['Job Key'] == keep_job['Job Key']
    ]
    assert final_sheet_job == protected_sheet_job and final_sheet_job['Salary / Range'] == estimate
    local=[r for r in repo.read('Job History') if r.get('Company')==success['Company']]
    sheet=[r for r in remote.read('Job History') if r.get('Company')==success['Company']]
    assert len(local)==len(sheet)==18 and len({r['Job Key'] for r in local})==18
    assert {r['Job Key'] for r in local}=={r['Job Key'] for r in sheet}
    pubs=inbox.connection.execute('SELECT state,binding FROM publication_receipts').fetchall()
    assert len(pubs)==1 and pubs[0][0]=='SYNC_CONFIRMED'
    pub_binding=json.loads(pubs[0][1]);assert pub_binding['company_id']==SUCCESS and pub_binding['request_id']==req_b['request_id']
    assert len(repo.scrape_outcomes())==2 and not repo.pending_scrape_outcomes(CONSUMER)
    assert len(repo.db.execute('SELECT * FROM scrape_outcome_delivery_receipts').fetchall())==2
    assert set(final_a['companies'])=={BLOCKED} and set(final_b['companies'])=={SUCCESS}
assert not coordinator.store.all() and not coordinator.store.held_repair_intake()
assert not coordinator.store.queue_enabled() and not coordinator.store.campaign_enabled() and coordinator.store.pilot_task() is None
assert coordinator.scheduler_thread is None;coordinator.model.assert_not_called()
assert provider_calls==[BLOCKED,SUCCESS] and len(fixture.batches)==1
(ROOT/'fixture-workbook.private.json').write_text(json.dumps({'sheets':fixture.sheets,'batches':fixture.batches},sort_keys=True)+'\n')
result={'disposition':'DISPOSABLE_EXTERNAL_HOLD_THEN_UNRELATED_PUBLICATION_PASS','blocked_company':BLOCKED,'blocked_cycle':cycle_a,'blocked_request_id':req_a['request_id'],'blocked_state':'Complete with exceptions','blocked_outcome':'BLOCKED','blocked_sender_receiver_status':receipt_a['sink_status'],'success_company':SUCCESS,'success_cycle':cycle_b,'success_request_id':req_b['request_id'],'success_state':'Complete','success_outcome':'COMPLETE','success_sender_receiver_status':receipt_b['sink_status'],'inventory_count':39,'unique_local_and_fixture_jobs':18,'fixture_write_batches':1,'publication_receipts':1,'matching_two_sided_outcome_receipts':2,'prior_busy_request_preserved':True,'one_active_application_owner_at_each_fetch':True,'coordinator_reopened_after_hold':True,'blocked_and_unrelated_rows_preserved':True,'terminal_replay_provider_calls':0,'terminal_replay_workbook_calls':0,'repair_tasks':0,'inference_calls':0,'provider_network_calls':0,'google_calls':0,'queue_and_campaign_enabled':False,'archive_sha256':archive_sha,'release':'NO_RELEASE_FIXTURE','native_effects':False}
result['manual_estimate_preserved_local_and_fixture_workbook'] = True
(ROOT/'RESULT.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
print(json.dumps(result,sort_keys=True))
