"""Exercise the read-only observer with real disposable retained and sender stores."""

from contextlib import closing
from hashlib import sha256
import json
import socket
import sqlite3

import pytest

from job_search_helper import ats, cli
from job_search_helper.retained_operator_journal import RetainedOperatorJournal, _inventory_digest, _write_record
from job_search_helper.retained_pilot_terminal import RetainedPilotHold, verify_retained_pilot_terminal
from job_search_helper.retained_work_exception import digest
from job_search_helper.scrape_outcome_delivery import CONSUMER, SCHEMA, OutcomeDelivery
from test_retained_operator_run import BOARD, CYCLE_ID, OperatorFixture


class ReceiptSink:
    """Fixture sink for the persisted sender receipt. No receiver or transport."""

    status = 'RECORDED_NO_REPAIR'
    calls = 0

    def ingest_immutable(self, record):
        self.calls += 1
        receipt = {
            'schema': SCHEMA,
            'consumer': CONSUMER,
            'outcome_id': record['outcome_id'],
            'record_sha256': digest(record),
        }
        return {
            **receipt,
            'disposition': 'ACCEPTED',
            'sink_receipt_id': 'ODR-' + digest(receipt)[:24],
            'sink_status': self.status,
        }


@pytest.fixture
def pilot(tmp_path, monkeypatch, request):
    def deny_network(*args, **kwargs):
        pytest.fail('The retained pilot evidence test attempted a real network call.')

    monkeypatch.setattr(socket, 'getaddrinfo', deny_network)
    monkeypatch.setattr(socket.socket, 'connect', deny_network)
    monkeypatch.setattr(socket.socket, 'connect_ex', deny_network)
    fixture = OperatorFixture(tmp_path, monkeypatch, company_event=True)
    fixture.runtime = {**fixture.runtime, 'state': 'COMPLETE', 'release_id': 'REL-retained-pilot-fixture'}
    claims = fixture.sign()
    verified_zero = getattr(request, 'param', False)
    if verified_zero:
        fixture.fetch.return_value = ats.Inventory(
            'complete', source_url=BOARD, ats='Jobvite', browser_fallback_allowed=False,
            verified_zero='samtec_jobvite_explicit_zero',
        )
    result = fixture.command('execute')
    assert result['state'] == ('VERIFIED_ZERO' if verified_zero else 'SYNC_CONFIRMED')
    selected = {
        'request_sha256': claims['request_sha256'],
        'reservation_digest': result['reservation_digest'],
        'company_event_id': fixture.request['company_event']['event_id'],
        'company_id': claims['company_id'],
        'source_revision': claims['source_revision'],
        'blocking_cycle_id': CYCLE_ID,
        'runtime_binding': fixture.runtime,
    }
    return fixture, result, selected


def observe(fixture, selected):
    with (cli.writer_lock(fixture.root / 'scraper.lock'),
          cli.writer_lock(fixture.root / 'writer.lock'),
          closing(fixture.local()) as local):
        return verify_retained_pilot_terminal(local, **selected)


def deliver(fixture, outcome_id, *, status='RECORDED_NO_REPAIR'):
    sink = ReceiptSink()
    sink.status = status
    with closing(fixture.local(write=True)) as local:
        delivery = OutcomeDelivery(local, sink)
        assert delivery.drain(outcome_id=outcome_id) == [{'outcome_id': outcome_id, 'disposition': 'ACCEPTED'}]
        (_row,) = local._outcome_delivery_rows(CONSUMER, outcome_id=outcome_id)
        assert sink.calls == 1
        return _row[1], _row[6]


def test_selected_pilot_reopens_exact_terminal_evidence_twice_without_side_effects(pilot, monkeypatch):
    fixture, result, selected = pilot
    outcome_text, receipt_text = deliver(fixture, result['outcome_id'])
    fixture.fetch.reset_mock()
    fixture.open_remote.reset_mock()
    sheets_batches = fixture.service.batches[:]

    def forbid_drain(*args, **kwargs):
        pytest.fail('Verification must never run an outcome delivery.')

    monkeypatch.setattr(OutcomeDelivery, 'drain', forbid_drain)
    protected = ('state.db', 'inventories.sqlite3', 'jobs.sqlite3', 'retained-sessions.sqlite3')
    before = {name: (fixture.root / name).read_bytes() for name in protected}
    evidence = observe(fixture, selected)
    assert observe(fixture, selected) == evidence
    assert evidence['identity']['company_event_id'] == selected['company_event_id']
    assert evidence['identity']['retained_reservation_sha256'] == selected['reservation_digest']
    assert evidence['blocking_cycle_id'] == CYCLE_ID
    assert evidence['publication']['acknowledgement_id'] == result['acknowledgement_id']
    assert evidence['record'] == json.loads(outcome_text)
    assert evidence['record_sha256'] == sha256(outcome_text.encode()).hexdigest()
    assert evidence['sender_receipt_sha256'] == sha256(receipt_text.encode()).hexdigest()
    assert evidence['sink_receipt_id'] == json.loads(receipt_text)['sink_receipt_id']
    assert evidence['sink_status'] == 'RECORDED_NO_REPAIR'
    assert evidence['outcome_id'] == result['outcome_id']
    assert 'description' not in json.dumps(evidence).casefold()
    assert {name: (fixture.root / name).read_bytes() for name in protected} == before
    assert fixture.service.batches == sheets_batches
    fixture.fetch.assert_not_called()
    fixture.open_remote.assert_not_called()
    fixture.assert_historical_records_unchanged()


@pytest.mark.parametrize('field', [
    'request_sha256', 'reservation_digest', 'company_event_id', 'company_id', 'source_revision',
    'blocking_cycle_id', 'runtime_binding',
])
def test_selected_identity_and_runtime_must_match(pilot, field):
    fixture, result, selected = pilot
    deliver(fixture, result['outcome_id'])
    wrong_value = {
        'request_sha256': '2' * 64,
        'reservation_digest': '3' * 64,
        'company_event_id': 'CEV-' + '4' * 32,
        'company_id': 'COMP-DIFFERENT',
        'source_revision': '5' * 64,
        'blocking_cycle_id': 'CYC-000000000000',
        'runtime_binding': {**fixture.runtime, 'dependency_manifest_sha256': '6' * 64},
    }[field]
    with pytest.raises(RetainedPilotHold):
        observe(fixture, {**selected, field: wrong_value})


def test_selected_pilot_holds_without_accepted_sender_delivery(pilot):
    fixture, result, selected = pilot
    with pytest.raises(RetainedPilotHold, match='pending or inconsistent'):
        observe(fixture, selected)
    deliver(fixture, result['outcome_id'], status='RECONCILIATION_REQUIRED')
    with pytest.raises(RetainedPilotHold, match='clean coordinator intake'):
        observe(fixture, selected)


@pytest.mark.parametrize('boundary', [
    'archive', 'consumption', 'active', 'request', 'session', 'inventory', 'ack', 'outcome', 'receipt', 'attempt',
])
def test_incomplete_or_conflicting_authority_holds(pilot, boundary):
    fixture, result, selected = pilot
    deliver(fixture, result['outcome_id'])
    root = fixture.root
    journal = RetainedOperatorJournal(root)
    record = journal.read_archived_event(selected['request_sha256'], selected['reservation_digest'])
    archive = journal._archive_path(record['binding'])
    if boundary == 'archive':
        archive.unlink()
    elif boundary == 'consumption':
        path = root / 'company-event-bridge' / 'consumption-receipts' / (selected['request_sha256'] + '.json')
        path.unlink()
    elif boundary == 'active':
        journal.path.write_bytes(archive.read_bytes())
        journal.path.chmod(0o600)
    elif boundary == 'request':
        fixture.queue_path.write_text(json.dumps(fixture.request))
    elif boundary == 'inventory':
        record['inventory']['jobs'][0]['description'] = 'Substituted disposable description.'
        record['inventory_sha256'] = _inventory_digest(record['inventory'], record['binding'])
        record['settlement_evidence']['inventory_sha256'] = record['inventory_sha256']
        record['settlement_evidence_sha256'] = digest(record['settlement_evidence'])
        _write_record(archive, record)
    elif boundary == 'session':
        with closing(sqlite3.connect(root / 'retained-sessions.sqlite3')) as db, db:
            db.execute('UPDATE retained_sessions SET state=?', ('SYNC_PENDING',))
    else:
        with closing(fixture.local(write=True)) as local, local.transaction():
            if boundary == 'ack':
                local.db.execute('DELETE FROM exact_local_acknowledgements')
            elif boundary == 'outcome':
                local.db.execute("UPDATE scrape_outcomes SET action='reconcile_storage_only'")
            elif boundary == 'receipt':
                local.db.execute('UPDATE scrape_outcome_delivery_receipts SET receipt_sha256=?', ('0' * 64,))
            else:
                (record_sha,) = local.db.execute(
                    'SELECT record_sha256 FROM scrape_outcome_delivery_receipts'
                ).fetchone()
                local.db.execute(
                    'INSERT INTO scrape_outcome_delivery_attempts VALUES (?,?,?,?,?,?,?,?)',
                    (CONSUMER, result['outcome_id'], record_sha, 1, 'IN_FLIGHT', 1000, None, 'fixture'),
                )
    with pytest.raises(RetainedPilotHold):
        observe(fixture, selected)


def test_terminal_sender_receipt_does_not_authorize_superseded_company_source(pilot):
    fixture, result, selected = pilot
    deliver(fixture, result['outcome_id'])
    with closing(fixture.local(write=True)) as local:
        [(row_number, company)] = local.matches('Companies', {'Company ID': selected['company_id']})
        local.import_companies_with_events(
            [(row_number, {**company, 'Official Careers URL': 'https://jobs.jobvite.com/samtec/different'})],
            origin='sheets-reconciliation',
        )
        local.import_companies_with_events([(row_number, company)], origin='sheets-reconciliation')
    with pytest.raises(RetainedPilotHold, match='current complete canonical'):
        observe(fixture, selected)


@pytest.mark.parametrize('pilot', [True], indirect=True)
def test_verified_zero_cannot_stand_in_for_the_approved_publication_pilot(pilot):
    fixture, result, selected = pilot
    deliver(fixture, result['outcome_id'])
    with pytest.raises(RetainedPilotHold, match='no consumed confirmed publication'):
        observe(fixture, selected)
