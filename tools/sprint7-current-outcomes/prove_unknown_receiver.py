"""Carry a previously captured default-off fixture through the real receiver once."""
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory

from coordinator import Coordinator
from coordinator_receipt_host_bridge import ManualReceiptV1HostBridge
from job_search_helper.sqlite_repository import SQLiteRepository


FIXTURE = Path('/tmp/jsh-s5-ordinary-sealed-evidence-red.PBkhfctW/test-work/third/'
               'test_default_off_normal_scrape0/installed-default-off')


def no_network(event, _args):
    if event in {'socket.connect','socket.bind','socket.getaddrinfo','socket.gethostbyname'}:
        raise AssertionError('The receiver proof must stay offline.')


def main():
    sys.addaudithook(no_network)
    evidence = json.loads((FIXTURE/'probe-evidence.json').read_bytes())
    old = FIXTURE/'.state/jobs.sqlite3'
    before = sha256(old.read_bytes()).hexdigest()
    expected, = evidence['outcomes']
    assert expected['outcome'] == 'UNKNOWN_CAPABILITY_HOLD' and expected['action'] == 'hold_for_engineering'
    assert evidence['qualification'] is None and evidence['mapping_fact_count'] == 0
    with TemporaryDirectory(prefix='unknown-held-receiver-') as name:
        root = Path(name)
        copy = root/'jobs.sqlite3'
        with (closing(sqlite3.connect(old.as_uri()+'?mode=ro',uri=True)) as sender_snapshot,
              closing(sqlite3.connect(copy)) as workspace):
            sender_snapshot.backup(workspace)
        coordinator = Coordinator(base=root/'receiver')
        coordinator.store.set_queue_enabled(False)
        with closing(SQLiteRepository(copy,'S5_offline_fixture_only')) as sender:
            original, = sender.scrape_outcomes()
            assert original == expected
            bridge = ManualReceiptV1HostBridge(coordinator,lambda:sender,enabled=True)
            result = bridge.manual_drain(outcome_id=expected['outcome_id'])
            assert result['results'] == [{'outcome_id':expected['outcome_id'],'disposition':'ACCEPTED'}]
            assert bridge.manual_drain(outcome_id=expected['outcome_id'])['results'] == []
            sent, = sender.db.execute(
                'SELECT receipt FROM scrape_outcome_delivery_receipts WHERE outcome_id=?',
                (expected['outcome_id'],)).fetchone()
        with coordinator.store.connect() as db:
            received, = db.execute(
                'SELECT receipt FROM scrape_outcome_delivery_receipts WHERE outcome_id=?',
                (expected['outcome_id'],)).fetchone()
        assert sent == received
        receipt = json.loads(received)
        assert receipt['sink_status'] == 'RECORDED_NO_REPAIR'
        assert coordinator.store.all() == [] and coordinator.store.held_repair_intake() == []
    assert sha256(old.read_bytes()).hexdigest() == before
    print(json.dumps({'application_outcome':expected['outcome'],'action':expected['action'],
                      'origin':'previously captured offline normal-worker fixture',
                      'outcome_id':expected['outcome_id'],'receiver_status':receipt['sink_status'],
                      'receipt_sha256':sha256(received.encode()).hexdigest(),
                      'same_sender_receiver_receipt':True,'new_repair_tasks':0,'provider_calls':0},sort_keys=True))


if __name__ == '__main__':
    main()
