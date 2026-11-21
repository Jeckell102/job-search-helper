from contextlib import closing
from pathlib import Path
import inspect
import sqlite3
import sys
import tempfile


def deny_network(event, _args):
    if event.startswith(('socket.connect', 'socket.getaddrinfo')):
        raise RuntimeError('This is an offline receipt test')


sys.addaudithook(deny_network)
source = Path(sys.argv[1])
sys.path[:0] = [str(source / 'src'), str(source / 'dev/wrapper-coder/tools')]
from coordinator import Coordinator
from coordinator_store import OUTCOME_DELIVERY_CONSUMER
from job_search_helper.engine import State
from job_search_helper.inbox import InventoryInbox
from job_search_helper.repository import RepositoryError
from job_search_helper.scrape_outcome_delivery import OutcomeDelivery
from job_search_helper.scrape_outcome_producer import normal_cycle_outcome_facts, record_cycle_outcomes
from job_search_helper.sqlite_repository import SQLiteRepository

archived = Path('/tmp/jsh-s5-closeout-check.yynrvfx6')
cycle_id = 'CYC-8F35E1D030EF'
company_id = 'COMP-0490'
with tempfile.TemporaryDirectory(prefix='jsh-exact-retry-proof-') as folder:
    root = Path(folder)
    for name in ('state.db', 'jobs.sqlite3', 'inventories.sqlite3'):
        with (closing(sqlite3.connect((archived / name).as_uri() + '?mode=ro', uri=True)) as source,
              closing(sqlite3.connect(root / name)) as destination):
            source.backup(destination)
    with (closing(State(root / 'state.db')) as state,
          closing(InventoryInbox(root / 'inventories.sqlite3', 'sheet')) as inbox,
          closing(SQLiteRepository(root / 'jobs.sqlite3', 'sheet')) as jobs):
        cycle = state.cycle(cycle_id)
        companies = [row for _, row in jobs.matches('Companies', {'Company ID': company_id})]
        ack = jobs.db.execute('SELECT * FROM exact_local_acknowledgements').fetchone()
        with jobs.db:
            jobs.db.execute('DELETE FROM exact_local_acknowledgements')
        options = {'storage_confirmed': True}
        if 'state' in inspect.signature(record_cycle_outcomes).parameters:
            options.update(state=state, inbox=inbox)
        assert record_cycle_outcomes(jobs, cycle, companies, **options) == [], 'Missing Jobs acknowledgement produced a positive retry outcome'
        facts = normal_cycle_outcome_facts(
            cycle, companies[0], cycle['companies'][company_id], storage_confirmed=True)
        try:
            jobs.record_scrape_outcome(facts)
        except RepositoryError:
            pass
        else:
            raise AssertionError('The generic writer accepted caller-asserted retry success')
        with jobs.db:
            jobs.db.execute('INSERT INTO exact_local_acknowledgements VALUES (?,?,?,?,?)', ack)

        with inbox.connection:
            inbox.connection.execute("UPDATE publication_receipts SET state='SYNC_PENDING'")
        assert record_cycle_outcomes(jobs, cycle, companies, **options) == []
        with inbox.connection:
            inbox.connection.execute("UPDATE publication_receipts SET state='SYNC_CONFIRMED'")
        state.save_cycle({**cycle, 'request_fingerprint': '0' * 64})
        assert record_cycle_outcomes(jobs, cycle, companies, **options) == []
        state.save_cycle(cycle)
        options['storage_confirmed'] = False

        [first] = record_cycle_outcomes(jobs, cycle, companies, **options)
        [replay] = record_cycle_outcomes(jobs, cycle, companies, **options)
        assert first['recorded'] is True and replay['recorded'] is False
        assert first['outcome'] == replay['outcome']
        assert first['outcome']['outcome'] == 'COMPLETE'
        receiver = Coordinator(base=root / 'coordinator')

        class LocalSink:
            def ingest_immutable(self, record):
                return receiver.command({
                    'action': 'ingest-scrape-outcome-delivery-v1',
                    'consumer': OUTCOME_DELIVERY_CONSUMER,
                    'record': record,
                })['receipt']

        delivery = OutcomeDelivery(jobs, LocalSink())
        assert delivery.drain(outcome_id=first['outcome_id']) == [
            {'outcome_id': first['outcome_id'], 'disposition': 'ACCEPTED'}]
        assert delivery.drain(outcome_id=first['outcome_id']) == []
        lineage = receiver.store.retry_lifecycle(cycle['repair_retry']['attempt_id'])
        assert lineage['state'] == 'VALIDATED_COMPLETE'
        assert [event['outcome_id'] for event in lineage['events']] == [first['outcome_id']]
        print('Exact completion and delivery replay preserved one COMPLETE and one VALIDATED_COMPLETE.')
