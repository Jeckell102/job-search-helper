import json

from job_search_helper import repair_retry_status, runner
from job_search_helper.repair_retry_status import read_repair_retry_status
from test_repair_retry_admission_replay import admit, retry


def checkpoint(state, engine):
    for db in (state.connection, engine.repo.db, engine.inbox.connection):
        assert db.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0] == 0


def test_readonly_status_follows_exact_queue_admission_and_held_inventory(retry, monkeypatch, capsys):
    bridge, binding, engine, state = retry
    attempt = binding['attempt_id']
    company = binding['company_id']
    assert bridge.deliver(binding)['state'] == 'REQUEST_WRITTEN'
    checkpoint(state, engine)
    old_queue = bridge.request_path.read_bytes()
    snapshots = [tuple(handle.iterdump()) for handle in
                 (state.connection, engine.repo.db, engine.inbox.connection)]
    assert read_repair_retry_status(bridge.database, engine.repo.path, attempt)['status'] == 'WAITING_TO_SCRAPE'
    assert bridge.request_path.read_bytes() == old_queue
    assert snapshots == [tuple(handle.iterdump()) for handle in
                         (state.connection, engine.repo.db, engine.inbox.connection)]
    cycle_id = admit(bridge, engine, state)
    checkpoint(state, engine)
    assert read_repair_retry_status(bridge.database, engine.repo.path, attempt)['status'] == 'AWAITING_INVENTORY'
    engine.inbox.save(cycle_id, company, {'inventory_status': 'partial', 'jobs': []})
    checkpoint(state, engine)
    monkeypatch.setattr(runner, '_load_environment', lambda: None)
    monkeypatch.setattr(runner, 'state_path', lambda: bridge.database)
    monkeypatch.setattr(runner.helper_cli, 'job_database_path', lambda: engine.repo.path)
    capsys.readouterr()
    assert runner.scrape_main(['company-queue-status', '--attempt-id', attempt]) == 0
    readback = json.loads(capsys.readouterr().out)
    assert readback['status'] == 'HELD_INVENTORY' and readback['cycle_id'] == cycle_id
    assert engine.inbox.get(cycle_id, company) == ({'inventory_status': 'partial', 'jobs': []}, False)


def test_status_holds_stale_source_and_preserves_an_exact_queue(retry):
    bridge, binding, engine, state = retry
    assert bridge.deliver(binding)['state'] == 'REQUEST_WRITTEN'
    old_queue = bridge.request_path.read_bytes()
    [(row_id, row)] = engine.repo.matches('Companies', {'Company ID': binding['company_id']})
    engine.repo.import_rows('Companies', [(row_id, {
        **row, 'Official Careers URL': 'https://example.test/revised',
    })])
    assert read_repair_retry_status(bridge.database, engine.repo.path, binding['attempt_id'])[
        'status'] == 'STATUS_SNAPSHOT_BUSY'
    checkpoint(state, engine)
    result = read_repair_retry_status(bridge.database, engine.repo.path, binding['attempt_id'])
    assert result['status'] == 'HELD_SOURCE'
    assert bridge.request_path.read_bytes() == old_queue


def test_status_holds_duplicate_durable_owners(retry):
    bridge, binding, engine, state = retry
    assert bridge.deliver(binding)['state'] == 'REQUEST_WRITTEN'
    first = state.cycle(admit(bridge, engine, state))
    state.save_cycle({**first, 'id': 'CYC-111111111111'})
    checkpoint(state, engine)
    result = read_repair_retry_status(bridge.database, engine.repo.path, binding['attempt_id'])
    assert result['status'] == 'HELD_OWNERSHIP'
    assert result['cycle_id'] is None


def test_status_rejects_a_snapshot_changed_during_the_read(retry, monkeypatch):
    bridge, binding, engine, state = retry
    assert bridge.deliver(binding)['state'] == 'REQUEST_WRITTEN'
    checkpoint(state, engine)
    read = repair_retry_status._read_checkpointed_retry_status

    def read_and_change(*args, **kwargs):
        report = read(*args, **kwargs)
        [(row_id, row)] = engine.repo.matches('Companies', {'Company ID': binding['company_id']})
        engine.repo.import_rows('Companies', [(row_id, {
            **row, 'Official Careers URL': 'https://example.test/revised-while-reading',
        })])
        checkpoint(state, engine)
        return report

    monkeypatch.setattr(repair_retry_status, '_read_checkpointed_retry_status', read_and_change)
    assert read_repair_retry_status(bridge.database, engine.repo.path, binding['attempt_id'])[
        'status'] == 'STATUS_SNAPSHOT_BUSY'
