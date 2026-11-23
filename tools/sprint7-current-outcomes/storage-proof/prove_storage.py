"""Compose the installed outcome producer and receiver around an actual compact-v2 lost acknowledgement."""
from contextlib import ExitStack, closing
from hashlib import sha256
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

PROJECT = Path('/home/chris/job-search-helper_old')
HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(PROJECT/'src'), str(PROJECT/'tests'), str(PROJECT/'dev/wrapper-coder/tools')]
from coordinator import Coordinator
from job_search_helper import ats
from job_search_helper.engine import Engine, State
from job_search_helper.exact_cycle_recovery import recover_exact_cycle
from job_search_helper.inbox import InventoryInbox
from job_search_helper.repository import SCHEMAS, UncertainWriteError
from job_search_helper.scrape_outcome_delivery import OutcomeDelivery
from job_search_helper.scrape_outcome_producer import record_cycle_outcomes
from job_search_helper.sheet_profile import COMPACT_PROFILE, COMPACT_SCHEMAS
from job_search_helper.sqlite_repository import SQLiteRepository
from test_exact_cycle_recovery import RecordingRemote, company, inventory
from test_two_sided_outcome_delivery import ReceiverSink

CYCLE = 'CYC-S7-STORAGE'
COMPANY = 'COMP-1'


def check(ok, message):
    if not ok:
        raise AssertionError(message)


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class LostReplyWorkbook(RecordingRemote):
    def commit(self, operations):
        check(not self.commits, 'A second workbook write was attempted.')
        super().commit(operations)
        raise UncertainWriteError('Fixture workbook lost its reply after applying the batch.')


def verify(root):
    row = company(COMPANY)
    payload = inventory(COMPANY)
    payload['jobs'] = [{
        'title':'Customer Implementation Engineer', 'posting_id':'1001',
        'url':'https://boards.example.test/comp-1/jobs/1001', 'location':'Remote',
        'description':'Customer-facing implementation and deployment work.', 'ats':'Greenhouse',
    }]
    remote = LostReplyWorkbook([row], schemas=COMPACT_SCHEMAS)
    with ExitStack() as ctx:
        jobs = ctx.enter_context(closing(SQLiteRepository(root/'jobs.db','fixture',initialize=True)))
        jobs.ensure_columns('Opportunities',['Opportunity ID'])
        for tab in SCHEMAS:
            jobs.import_rows(tab, enumerate([row] if tab == 'Companies' else [], 2))
        with jobs.transaction():
            jobs.set_meta('ready','yes')
            jobs.set_meta('sheets_profile',COMPACT_PROFILE)
        state = ctx.enter_context(closing(State(root/'state.db')))
        inbox = ctx.enter_context(closing(InventoryInbox(root/'inbox.db','fixture')))
        engine = Engine(jobs,state,inbox=inbox,error_log_path=root/'errors.jsonl')
        item = {'stage':'queued'}
        engine._admit_source_fact(item,row)
        state.save_cycle({'id':CYCLE,'status':'In Progress','started_at':'2026-11-19T00:00:00Z',
                          'companies':{COMPANY:item}})
        inbox.save(CYCLE,COMPANY,payload)
        coordinator = Coordinator(base=root/'receiver')
        sink = ReceiverSink(coordinator)
        delivery = OutcomeDelivery(jobs,sink)
        first = recover_exact_cycle(engine,remote,CYCLE,[COMPANY])
        check(first['held'] == [{'company_id':COMPANY,'reason':'uncertain_write'}] and not first['confirmed'],
              'The lost response did not produce a held publication.')
        plan = inbox.plan(CYCLE,COMPANY)[0]
        frozen_payload = inbox.get(CYCLE,COMPANY)[0]
        journal = inbox.exact_remote_state(CYCLE,COMPANY)
        check(frozen_payload == payload and plan['exact_plan_version'] == 2 and journal['state'] == 'SYNC_PENDING'
              and journal['first_attempt_claimed'] and journal['local_plan_digest'] == plan['plan_digest']
              and inbox.exact_local_state(CYCLE,COMPANY)['state'] == 'LOCAL_VERIFIED',
              'The selected inventory, immutable plan or pending publication lost its binding.')
        cut = state.cycle(CYCLE)
        produced = record_cycle_outcomes(jobs,cut,engine._company_rows(),storage_confirmed=False,
                                         state=state,inbox=inbox)
        cut_dispositions = [result['outcome']['outcome'] for result in produced]
        check(cut['companies'][COMPANY]['stage'] == 'inventory' and not produced and not delivery.drain(),
              'Installed pending-inventory seam differs; inspect before reporting.')
        check(not jobs.scrape_outcomes(company_id=COMPANY) and sink.calls == 0,
              'A storage-failure outcome or receiver call exists at the cut.')
        before = {tab:digest(jobs.read(tab)) for tab in ('Job History','Job Evidence','Opportunities','Companies')}
        remote_before = {tab:digest(remote.snapshot(tab)) for tab in ('Job History','Opportunities','Companies')}
        local_rows = {tab:len(jobs.read(tab)) for tab in before}
        check(local_rows['Job History'] == local_rows['Job Evidence'] == 1,
              'The positive fixture did not retain the selected local posting.')
        second = recover_exact_cycle(engine,remote,CYCLE,[COMPANY])
        check(second['confirmed'] == [COMPANY] and not second['held'] and not second['planned']
              and len(remote.commits) == 1, 'Scoped readback failed or repeated dispatch.')
        receipt = inbox.connection.execute('SELECT state,acknowledgement_id FROM publication_receipts WHERE receipt_id=?',
                                          (journal['receipt_id'],)).fetchone()
        confirmed = inbox._require_exact_local_acknowledgement(jobs,CYCLE,COMPANY,plan['plan_digest'],
                                                               journal['receipt_id'],receipt[1])
        check(receipt[0] == 'SYNC_CONFIRMED' and confirmed['selected_fields_digest']
              and state.cycle(CYCLE)['companies'][COMPANY]['stage'] == 'complete'
              and all(digest(jobs.read(tab)) == hashed for tab,hashed in before.items())
              and all(digest(remote.snapshot(tab)) == hashed for tab,hashed in remote_before.items()),
              'Saved publication and logical row continuity differ.')
        final = record_cycle_outcomes(jobs,state.cycle(CYCLE),engine._company_rows(),storage_confirmed=True,
                                      state=state,inbox=inbox)
        check(len(final) == 1 and final[0]['outcome']['outcome'] == 'COMPLETE','Expected one confirmed ordinary outcome.')
        outcome = final[0]['outcome']
        check(delivery.drain(outcome_id=outcome['outcome_id']) == [{'outcome_id':outcome['outcome_id'],'disposition':'ACCEPTED'}]
              and not delivery.drain() and sink.calls == 1, 'Final ordinary outcome receipt missing or repeated.')
        sender = jobs.db.execute('SELECT receipt FROM scrape_outcome_delivery_receipts').fetchall()
        with coordinator.store.connect() as db:
            receiver = db.execute('SELECT receipt FROM scrape_outcome_delivery_receipts').fetchall()
            for table in ('repair_intake','tasks','inference_receipts'):
                check(db.execute(f'SELECT count(*) FROM {table}').fetchone()[0] == 0,'Unexpected coordinator work.')
        check(len(sender) == 1 and sender == receiver and json.loads(receiver[0][0])['sink_status'] == 'RECORDED_NO_REPAIR',
              'Sender and receiver do not share one no-repair receipt.')
        return {'state':'HOLD_MISSING_PENDING_STORAGE_OUTCOME', 'fixture':'one ordinary non-event company, one saved posting',
                'pending':{'state_stage':cut['companies'][COMPANY]['stage'],'local_state':'LOCAL_VERIFIED',
                           'publication':'SYNC_PENDING','producer_outcomes':cut_dispositions,'receiver_calls':0},
                'recovery':{'state':'SYNC_CONFIRMED','remote_write_batches':len(remote.commits),'replanned':False,
                            'inventory_sha256':digest(frozen_payload),'plan_digest':plan['plan_digest'],
                            'receipt_id':journal['receipt_id'],'acknowledgement_id':receipt[1],
                            'verified_selected_fields_sha256':confirmed['selected_fields_digest'],
                            'unchanged_logical_rows':local_rows},
                'final_outcome':{'classification':outcome['outcome'],'receiver_disposition':'RECORDED_NO_REPAIR',
                                 'matching_sender_receiver_receipt_sha256':sha256(sender[0][0].encode()).hexdigest(),
                                 'duplicate_drained':0,'new_repairs':0,'new_tasks':0,'new_inference':0}}


def main():
    check(sys.flags.isolated and sys.flags.dont_write_bytecode,'Expected isolated Python without bytecode.')
    def guard(event,args):
        if event.startswith('socket.') or event in ('os.system','subprocess.Popen'):
            raise AssertionError('External transport is forbidden.')
    sys.addaudithook(guard)
    fetches = []
    def count_fetch(frame,event,arg):
        if event == 'call' and frame.f_code is ats.fetch_inventory.__code__:
            fetches.append(1)
    sys.setprofile(count_fetch)
    try:
        with TemporaryDirectory(dir=HERE) as temp:
            result = verify(Path(temp))
    finally:
        sys.setprofile(None)
    check(not fetches,'An inventory refetch occurred.')
    result['provider_dispatches'] = len(fetches)
    result['limits'] = 'Preseeded synthetic saved inventory and company; real installed SQLite producer, receiver and exact publisher; in-memory workbook.'
    with (HERE/'RESULT.json').open('x') as out:
        json.dump(result,out,sort_keys=True,indent=2)
        out.write('\n')
    print(result['state'])


if __name__ == '__main__':
    main()
