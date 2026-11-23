"""One genuine normal SQLite scan and storage-only outcome, with offline provider/Sheets transports."""
from contextlib import ExitStack, closing, redirect_stdout
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

BASE = Path('/home/chris/job-search-helper_old')
HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(BASE/'src'),str(BASE/'tests'),str(BASE/'dev/wrapper-coder/tools')]
from coordinator import Coordinator
from job_search_helper.engine import Engine, State
from job_search_helper.inbox import InventoryInbox
from job_search_helper.repository import GoogleRepository, SCHEMAS
from job_search_helper.run_sync import publish_pending
from job_search_helper.runner import _run_scan_with_retries
from job_search_helper.scrape_outcome_delivery import OutcomeDelivery
from job_search_helper.scrape_outcome_producer import record_cycle_outcomes
from job_search_helper.sheet_profile import COMPACT_PROFILE, COMPACT_SCHEMAS
from job_search_helper.sheets_sync import SheetsSynchronizer
from job_search_helper.sqlite_repository import SQLiteRepository
from sheets_fixture import RangeSheets
from test_fetch_pool import company, inventory
from test_two_sided_outcome_delivery import ReceiverSink


def require(ok,reason):
    if not ok:
        raise ValueError(reason)


def digest(obj):
    return sha256(json.dumps(obj,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def prove(folder):
    cid = 'COMP-0001'
    row = {**company(1,source='Greenhouse'),'Company ID':cid}
    observed = []
    def fetch(source,url,company_id,name):
        require(not observed and company_id == cid,'Unexpected fixture provider fetch.')
        observed.append(company_id)
        return inventory(company_id,name,url)
    with ExitStack() as held:
        local = held.enter_context(closing(SQLiteRepository(folder/'jobs.sqlite3','fixture',initialize=True)))
        local.ensure_columns('Opportunities',['Opportunity ID'])
        for tab in SCHEMAS:
            local.import_rows(tab,enumerate([row] if tab=='Companies' else [],2))
        with local.transaction():
            local.set_meta('ready','yes')
            local.set_meta('sheets_profile',COMPACT_PROFILE)
        state = held.enter_context(closing(State(folder/'state.db')))
        inbox = held.enter_context(closing(InventoryInbox(folder/'inbox.db','fixture')))
        engine = Engine(local,state,fetcher=fetch,inbox=inbox,error_log_path=folder/'errors.jsonl')
        real_cycle = engine.start_cycle([cid])
        scan = _run_scan_with_retries(engine,real_cycle,partial_retries=0,fetch_workers=1,assignment_window=1)
        cycle = state.cycle(real_cycle)
        counters = scan['run_counts']
        require(cycle['status'] == 'Complete' and cycle['companies'][cid]['stage'] == 'complete'
                and observed == [cid] and counters['successful'] == 1,'Ordinary SQLite scan did not finish.')
        before = local.status()['pending_cells']
        require(before > 0 and not inbox.pending(real_cycle,include_blocked=True),'Expected remotely pending local work.')
        records = record_cycle_outcomes(local,cycle,engine._company_rows(),storage_confirmed=before==0,state=state,inbox=inbox)
        [original] = records
        outcome = original['outcome']
        require(outcome['outcome']=='STORAGE_OR_SYNC_FAILURE' and outcome['action']=='reconcile_storage_only'
                and outcome['identity']['cycle_id']==real_cycle and outcome['identity']['company_id']==cid,
                'Missing exact ordinary storage-only failure.')
        oid = outcome['outcome_id']
        receiver = Coordinator(base=folder/'receiver')
        sink = ReceiverSink(receiver)
        delivery = OutcomeDelivery(local,sink)
        require(delivery.drain(outcome_id=oid)==[{'outcome_id':oid,'disposition':'ACCEPTED'}],
                'Missing receiver acknowledgement.')
        def receipts():
            rows = local.db.execute('SELECT receipt FROM scrape_outcome_delivery_receipts WHERE outcome_id=?',(oid,)).fetchall()
            with receiver.store.connect() as db:
                remote = db.execute('SELECT receipt FROM scrape_outcome_delivery_receipts WHERE outcome_id=?',(oid,)).fetchall()
                require(all(db.execute(f'SELECT count(*) FROM {t}').fetchone()[0]==0 for t in
                            ('repair_intake','tasks','inference_receipts')),'Unexpected coordinator work.')
            require(len(rows)==1 and remote==rows and json.loads(rows[0][0])['sink_status']=='RECORDED_NO_REPAIR',
                    'Two-sided storage-only outcome receipt differs.')
            return sha256(rows[0][0].encode()).hexdigest()
        receipt_sha = receipts()
        raw = local.db.execute('SELECT payload FROM scrape_outcomes WHERE outcome_id=?',(oid,)).fetchone()[0]
        history = local.read('Job History')
        evidence = local.read('Job Evidence')
        require(len(history)==len(evidence)==1 and history[0]['Job Key']==evidence[0]['Job Key'],'Missing local posting.')
        # Create the offline workbook only after the genuine local scan and receiver acknowledgement.
        service = RangeSheets({'Companies':[row]},schemas=COMPACT_SCHEMAS)
        def workbook():
            return GoogleRepository(service,'fixture',schemas=COMPACT_SCHEMAS,min_request_interval=0)
        sync = SheetsSynchronizer(local,workbook())
        publication = publish_pending(sync,max_batches=5,max_seconds=15)
        batch_count = len(service.batches)
        # Global drain is safe in this disposable database, populated with precisely one company.
        repeated = publish_pending(sync,max_batches=1,max_seconds=15)
        reader = workbook()
        remote_history = reader.read('Job History')
        remote_company = reader.read('Companies')
        require(publication['stop_reason']=='drained' and publication['pending_cells']==0 and batch_count>0
                and repeated['published_rows']==0 and repeated['pending_cells']==0
                and len(service.batches)==batch_count,'Ordinary publication failed to drain idempotently.')
        require(len(remote_history)==len(remote_company)==1 and remote_company[0]['Company ID']==cid
                and all(remote_history[0][k]==history[0][k] for k in ('Job Key','Job Title','Official Job URL')),
                'Fresh workbook readback does not match local posting.')
        require(local.read('Job History')==history and local.read('Job Evidence')==evidence and state.cycle(real_cycle)==cycle
                and local.db.execute('SELECT payload FROM scrape_outcomes').fetchall()==[(raw,)]
                and not delivery.drain(outcome_id=oid) and receipts()==receipt_sha and sink.calls==1
                and observed==[cid],'Storage reconciliation changed source history or duplicated work.')
        return {'state':'ACCEPT_DISPOSABLE_NORMAL_STORAGE_ONLY_RECOVERY','company_id':cid,'cycle_id':real_cycle,
                'provider_fixture_fetches':len(observed),'refetches':0,'source_state_at_cut':cycle['companies'][cid]['stage'],
                'pending_cells_at_cut':before,'outcome_id':oid,'original_outcome':outcome['outcome'],
                'action':outcome['action'],'receiver':'RECORDED_NO_REPAIR','receiver_calls':sink.calls,
                'matching_receipt_sha256':receipt_sha,'original_outcome_bytes_sha256':sha256(raw.encode()).hexdigest(),
                'unchanged_cycle_sha256':digest(cycle),'saved_jobs':len(history),'saved_job_evidence_rows':len(evidence),
                'fresh_workbook_postings':len(remote_history),'publication_rows':publication['published_rows'],
                'workbook_write_batches':batch_count,'pending_cells_after':publication['pending_cells'],
                'writes_on_second_drain':0,'new_repairs':0,'new_tasks':0,'new_inference':0,
                'scope':'Installed ordinary scan, producer, coordinator, SQLite publisher and GoogleRepository; synthetic provider and in-memory Sheets transport.'}


def main():
    require(sys.flags.isolated and sys.flags.dont_write_bytecode,'Use isolated Python without bytecode.')
    def guard(event,args):
        if event.startswith('socket.') or event in ('os.system','subprocess.Popen'):
            raise AssertionError('Unexpected external transport.')
    sys.addaudithook(guard)
    with TemporaryDirectory(dir=HERE) as folder, redirect_stdout(StringIO()):
        result=prove(Path(folder))
    with (HERE/'RESULT.json').open('x') as out:
        json.dump(result,out,indent=2,sort_keys=True)
        out.write('\n')
    print(result['state'])


if __name__=='__main__':
    main()
