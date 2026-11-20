import json
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pytest

from job_search_helper.cli import writer_lock
from job_search_helper.engine import Engine, State
from job_search_helper.outcomes import classify_outcome
from job_search_helper.scrape_outcome_delivery import OutcomeDelivery
from job_search_helper.scan_request import requested_scan
from job_search_helper.temporary_retry import (
    CONSUMER, SELECTED_COOLDOWN_SECONDS, SelectedTemporaryRetrySink, TemporaryRetrySink,
    is_temporary_retry_request,
)
from job_search_helper.company_intake_dispatcher import CompanyIntakeDispatcher


class Repo:
    def __init__(self, company): self.company = company; self.rows = []
    def matches(self, tab, identity):
        return [(1, self.company)] if tab == 'Companies' and identity == {'Company ID': self.company['Company ID']} else []
    def _outcome_delivery_rows(self, consumer): return self.rows


def record(**extra):
    facts = {'request_id':'REQ-1','company_id':'COMP-1','source_revision':'x','cycle_id':'CYC-1',
             'provider':'test','adapter_version':'v1','source_current':True,'company_status':'Active',
             'storage_status':'confirmed','inventory_status':'partial','capability':'unknown',
             'failure':{'category':'timeout'}}
    facts.update(extra); return classify_outcome(facts)


class TemporaryRetryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.company = {'Company ID':'COMP-1','Company':'Acme','Company Status':'Active',
                        'Official Careers URL':'https://example.test/jobs','ATS / Source':'test'}
        from job_search_helper.company_events import source_revision
        self.revision = source_revision(self.company)

    def test_creates_exact_one_company_request_and_duplicate_is_idempotent(self):
        value = record(source_revision=self.revision)
        stamps = iter(('2026-01-01T00:00:00+00:00', '2026-01-01T00:05:00+00:00'))
        sink = TemporaryRetrySink(Repo(self.company), self.root, stamp=lambda:next(stamps))
        self.assertEqual(sink.ingest_immutable(value)['sink_status'], 'VALIDATED_COMPLETE')
        request = json.loads((self.root/'next-scan.json').read_text())
        self.assertTrue(is_temporary_retry_request(request)); self.assertEqual(request['company_ids'], ['COMP-1'])
        self.assertEqual(sink.ingest_immutable(value)['sink_status'], 'VALIDATED_COMPLETE')
        self.assertEqual(json.loads((self.root/'next-scan.json').read_text()), request)

    def test_request_grammar_rejects_extra_fields_and_malformed_lineage(self):
        value = record(source_revision=self.revision)
        sink = TemporaryRetrySink(Repo(self.company), self.root, stamp=lambda:'2026-01-01T00:00:00+00:00')
        sink.ingest_immutable(value)
        request = json.loads((self.root/'next-scan.json').read_text())
        self.assertFalse(is_temporary_retry_request(dict(request, extra=True)))
        self.assertFalse(is_temporary_retry_request(dict(request, request_fingerprint='a' * 64)))
        self.assertFalse(is_temporary_retry_request({**request, 'temporary_retry': {
            **request['temporary_retry'], 'retry_index': True}}))
        request['temporary_retry']['outcome_id'] = 'not-an-outcome'
        self.assertFalse(is_temporary_retry_request(request))

    def test_classifier_rejects_forged_or_mixed_temporary_retry_lineage(self):
        outcome_id = 'OUT-' + 'a' * 24
        with self.assertRaisesRegex(ValueError, 'temporary retry outcome identity'):
            record(temporary_retry_outcome_id=outcome_id)
        with self.assertRaisesRegex(ValueError, 'temporary retry outcome identity'):
            record(request_id='temporary-retry:' + outcome_id,
                   temporary_retry_outcome_id=outcome_id, attempt_id='RTRY-forged')

    def test_busy_slot_preserves_existing_request_and_is_retryable(self):
        (self.root/'next-scan.json').write_text(json.dumps({'occupied': True}))
        with self.assertRaisesRegex(RuntimeError, 'occupied'):
            TemporaryRetrySink(Repo(self.company), self.root).ingest_immutable(record(source_revision=self.revision))
        self.assertEqual(json.loads((self.root/'next-scan.json').read_text()), {'occupied': True})

    def test_directory_fsync_failure_is_unacknowledged_and_restart_converges(self):
        value = record(source_revision=self.revision)
        sink = TemporaryRetrySink(Repo(self.company), self.root,
                                  stamp=lambda:'2026-01-01T00:00:00+00:00')
        import os
        real_fsync, calls = os.fsync, []
        def fail_directory(fd):
            calls.append(fd)
            if len(calls) == 2:
                raise OSError('synthetic directory fsync failure')
            return real_fsync(fd)
        with patch('job_search_helper.temporary_retry.os.fsync', side_effect=fail_directory):
            with self.assertRaisesRegex(OSError, 'directory fsync'):
                sink.ingest_immutable(value)
        self.assertTrue((self.root/'next-scan.json').exists())
        restarted = TemporaryRetrySink(Repo(self.company), self.root,
                                       stamp=lambda:'2026-01-01T00:05:00+00:00')
        self.assertEqual(restarted.ingest_immutable(value)['sink_status'], 'VALIDATED_COMPLETE')

    def test_dispatcher_requires_separate_temporary_retry_gate(self):
        value = record(source_revision=self.revision)
        TemporaryRetrySink(Repo(self.company), self.root,
                           stamp=lambda:'2026-01-01T00:00:00+00:00').ingest_immutable(value)
        children = []
        dispatcher = CompanyIntakeDispatcher(
            Repo(self.company), self.root,
            child_runner=lambda command: children.append(command) or 0,
            queue_status=lambda: {'state': 'READY_FOR_START'})
        dispatcher.set_enabled(True)
        self.assertEqual(dispatcher.run_once()['state'], 'HELD_TEMPORARY_RETRY_DISABLED')
        self.assertEqual(children, [])
        dispatcher.set_temporary_retry_enabled(True)
        self.assertEqual(dispatcher.run_once()['state'], 'CHILD_LAUNCHED')
        self.assertEqual(len(children), 1)

    def test_source_drift_paused_and_claimed_hold_without_request(self):
        for change in ({'Company Status':'Paused'}, {'Claimed By':'other'}, {'Official Careers URL':'https://changed.test'}):
            company = dict(self.company); company.update(change)
            receipt = TemporaryRetrySink(Repo(company), self.root).ingest_immutable(record(source_revision=self.revision))
            self.assertEqual(receipt['sink_status'], 'OBSERVED_HELD')
            self.assertFalse((self.root/'next-scan.json').exists())

    def test_second_temporary_is_terminal_cap_and_never_writes_request(self):
        prior = 'OUT-' + 'a' * 24
        value = record(request_id='temporary-retry:' + prior, source_revision=self.revision,
                       temporary_retry_outcome_id=prior)
        receipt = TemporaryRetrySink(Repo(self.company), self.root).ingest_immutable(value)
        self.assertEqual(receipt['sink_status'], 'HELD_TEMPORARY_RETRY_CAP')
        self.assertFalse((self.root/'next-scan.json').exists())

    def test_non_temporary_never_creates_work(self):
        value = record(source_revision=self.revision, failure={'category':'unknown'})
        self.assertEqual(TemporaryRetrySink(Repo(self.company), self.root).ingest_immutable(value)['sink_status'], 'RECORDED_NO_REPAIR')
        self.assertFalse((self.root/'next-scan.json').exists())


@pytest.fixture
def selected(tmp_path, monkeypatch):
    candidate = pytest.importorskip('test_retained_operator_run', reason='requires combined retained event fixtures')
    from job_search_helper import ats
    fixture = candidate.OperatorFixture(tmp_path, monkeypatch, company_event=True)
    fixture.sign()
    fixture.fetch.return_value = ats.Inventory(
        'failed', source_url=candidate.BOARD, ats='Jobvite', browser_fallback_allowed=False,
        outcome_failure=ats.outcome_failure('temporary_transport', 'retryable_http_status'))
    terminal = fixture.command('execute')
    assert terminal['state'] == 'FETCH_OUTCOME'
    assert terminal['consumption']['state'] == 'FETCH_OUTCOME_CONSUMED'
    assert terminal['outcome']['identity']['retained_reservation_sha256'] == terminal['reservation_digest']
    fixture.fetch.assert_called_once()
    fixture.open_remote.reset_mock()
    current = [datetime(2026, 11, 20, 18, tzinfo=timezone.utc)]

    with closing(fixture.local()) as reader:
        def make_sink(**changes):
            return SelectedTemporaryRetrySink(reader, fixture.root, **{
                'outcome_id': terminal['outcome_id'], 'request_sha256': fixture.request_sha,
                'reservation_digest': terminal['reservation_digest'], 'clock': lambda: current[0], **changes,
            })
        yield fixture, terminal['outcome'], current, make_sink
    fixture.fetch.assert_called_once()
    fixture.open_remote.assert_not_called()


def claim(fixture, sink):
    with (writer_lock(fixture.root / 'scraper.lock'), writer_lock(fixture.root / 'writer.lock'),
          closing(State(str(fixture.state_path), readonly=True)) as state):
        return sink.claim_dispatch_locked(state)


def close_fixture_blocker(fixture, *, mirror=True):
    with closing(State(str(fixture.state_path))) as state:
        cycle = state.cycle(fixture.manifest['cycle_id'])
        state.save_cycle({**cycle, 'status': 'Complete'})
    if mirror:
        with closing(fixture.local(write=True)) as writer:
            writer.commit([{'tab': 'Scan Cycles', 'identity': {'Cycle ID': cycle['id']},
                            'values': {'Cycle Status': 'Complete'}}])


def test_selected_outcome_waits_for_cooldown_and_real_historical_hold(selected):
    fixture, outcome, current, make_sink = selected
    sink = make_sink()
    assert claim(fixture, sink)['state'] == 'HELD_NOT_SCHEDULED'
    accepted = sink.ingest_immutable(outcome)
    assert accepted['outcome_id'] == outcome['outcome_id']
    assert not fixture.queue_path.exists()
    assert claim(fixture, sink)['blocking_cycle_ids'] == [fixture.manifest['cycle_id']]

    current[0] += timedelta(seconds=SELECTED_COOLDOWN_SECONDS - 1)
    close_fixture_blocker(fixture, mirror=False)
    assert claim(fixture, sink)['blocking_cycle_ids'] == [fixture.manifest['cycle_id']]
    close_fixture_blocker(fixture)
    hold = claim(fixture, sink)
    assert hold['state'] == 'HELD_COOLDOWN'
    assert hold['not_before'] == (current[0] + timedelta(seconds=1)).isoformat()

    current[0] += timedelta(seconds=1)
    fixture.queue_path.write_text('{"unrelated":true}')
    assert claim(fixture, sink)['state'] == 'HELD_REQUEST_SLOT'
    assert fixture.queue_path.read_text() == '{"unrelated":true}'
    fixture.queue_path.unlink()
    with (writer_lock(fixture.root / 'scraper.lock'), writer_lock(fixture.root / 'writer.lock'),
          closing(State(str(fixture.state_path), readonly=True)) as read_state,
          closing(State(str(fixture.state_path))) as writable_state,
          closing(fixture.local(write=True)) as writer):
        dispatched = sink.claim_dispatch_locked(read_state)
        assert dispatched['state'] == 'SUCCESSOR_CLAIMED'
        assert is_temporary_retry_request(dispatched['request'])
        assert dispatched['request']['temporary_retry']['outcome_id'] == outcome['outcome_id']
        assert dispatched['request']['company_ids'] == [outcome['identity']['company_id']]
        # Exercise ordinary consumption in-process under the uninterrupted
        # admission boundary, using only the disposable SQLite fixture.
        fixture.queue_path.write_text(json.dumps(dispatched['request']))
        engine = Engine(writer, writable_state, runtime_binding=fixture.runtime)
        successor = requested_scan(engine, writable_state, fixture.state_path)
        cycle = writable_state.cycle(successor)
        assert list(cycle['companies']) == [outcome['identity']['company_id']]
        assert cycle['temporary_retry'] == dispatched['request']['temporary_retry']
    assert not fixture.queue_path.exists()
    assert make_sink().ingest_immutable(outcome) == accepted
    assert claim(fixture, make_sink()) == {
        'state': 'HELD_SUCCESSOR_ALREADY_CLAIMED', 'request_id': dispatched['request_id']}


def test_selected_delivery_lost_ack_reuses_one_durable_schedule(selected):
    fixture, outcome, current, make_sink = selected
    key = outcome['outcome_id']
    sink = make_sink()
    with closing(fixture.local(write=True)) as sender:
        delivery = OutcomeDelivery(sender, sink, consumer=CONSUMER, clock=lambda: current[0].timestamp(),
                                   stamp=lambda: current[0].isoformat())
        with (patch.object(sender, '_complete_outcome_delivery', side_effect=OSError('returned ACK lost')),
              pytest.raises(OSError, match='returned ACK lost')):
            delivery.drain(limit=1, outcome_id=key)
        path, = sink.directory.glob('*.json')
        scheduled = path.read_bytes()
        current[0] += timedelta(seconds=301)
        restarted = OutcomeDelivery(sender, make_sink(), consumer=CONSUMER, clock=lambda: current[0].timestamp(),
                                    stamp=lambda: current[0].isoformat())
        assert restarted.drain(limit=1, outcome_id=key) == [{'outcome_id': key, 'disposition': 'ACCEPTED'}]
        assert restarted.drain(limit=1, outcome_id=key) == []
        assert path.read_bytes() == scheduled
        assert sender.db.execute('SELECT count(*) FROM scrape_outcome_delivery_receipts WHERE consumer=?',
                                 (CONSUMER,)).fetchone() == (1,)
    assert not fixture.queue_path.exists()


def test_aba_source_change_cannot_claim_scheduled_retry(selected):
    fixture, outcome, current, make_sink = selected
    sink = make_sink()
    sink.ingest_immutable(outcome)
    close_fixture_blocker(fixture)
    current[0] += timedelta(seconds=301)
    identity = {'Company ID': outcome['identity']['company_id']}
    with closing(fixture.local(write=True)) as writer:
        original = writer.matches('Companies', identity)[0][1]['Official Careers URL']
        for url in ('https://jobs.jobvite.com/another/search', original):
            writer.mutate_company_with_event({'tab': 'Companies', 'identity': identity,
                                              'values': {'Official Careers URL': url}})
    assert claim(fixture, sink)['state'] == 'HELD_SOURCE_CHANGED'
    assert not fixture.queue_path.exists()


def test_unrelated_outcome_or_unconsumed_locator_cannot_schedule(selected):
    fixture, outcome, _current, make_sink = selected
    with pytest.raises(ValueError, match='does not match'):
        make_sink().ingest_immutable({**outcome, 'outcome_id': 'OUT-' + 'b' * 24})
    with pytest.raises(ValueError, match='exact durable temporary outcome'):
        make_sink(outcome_id='OUT-' + 'b' * 24).ingest_immutable(outcome)
    with pytest.raises(ValueError, match='consumed retained fetch outcome'):
        make_sink(request_sha256='b' * 64).ingest_immutable(outcome)
    with closing(fixture.local()) as reader, pytest.raises(ValueError, match='explicit selected scheduling'):
        TemporaryRetrySink(reader, fixture.root).ingest_immutable(outcome)
    assert not (fixture.root / 'selected-temporary-retries').exists()
    assert not fixture.queue_path.exists()


def test_uncertain_claim_write_preserves_budget_without_second_dispatch(selected):
    fixture, outcome, current, make_sink = selected
    sink = make_sink()
    sink.ingest_immutable(outcome)
    close_fixture_blocker(fixture)
    current[0] += timedelta(seconds=301)
    from job_search_helper.temporary_retry import _sync_directory

    def lose_durability_result(path):
        _sync_directory(path)
        if path == sink.directory:
            raise OSError('lost claim acknowledgement')

    with (patch('job_search_helper.temporary_retry._sync_directory', side_effect=lose_durability_result),
          pytest.raises(OSError, match='lost claim acknowledgement')):
        claim(fixture, sink)
    assert claim(fixture, make_sink())['state'] == 'HELD_SUCCESSOR_ALREADY_CLAIMED'
    assert not fixture.queue_path.exists()
