from contextlib import closing
from hashlib import sha256
import socket

import pytest

from job_search_helper import ats, cli
from job_search_helper.scrape_outcome_delivery import CONSUMER, OutcomeDelivery
from pilot_outcome_readback import read_pilot_outcome
from test_retained_operator_run import BOARD, CYCLE_ID, OperatorFixture


def pilot(tmp_path, monkeypatch, *, zero=False):
    def forbid(*args, **kwargs):
        pytest.fail('Readback must not start a network call.')

    monkeypatch.setattr(socket, 'getaddrinfo', forbid)
    monkeypatch.setattr(socket.socket, 'connect', forbid)
    fixture = OperatorFixture(tmp_path, monkeypatch, company_event=True)
    fixture.runtime = {**fixture.runtime, 'state': 'COMPLETE', 'release_id': 'REL-readback-fixture'}
    if zero:
        fixture.fetch.return_value = ats.Inventory('complete', source_url=BOARD, ats='Jobvite',
            browser_fallback_allowed=False, verified_zero='samtec_jobvite_explicit_zero')
    claims = fixture.sign()
    finished = fixture.command('execute')
    assert finished['state'] == ('VERIFIED_ZERO' if zero else 'SYNC_CONFIRMED')
    fixture.fetch.reset_mock()
    fixture.open_remote.reset_mock()
    monkeypatch.setattr(OutcomeDelivery, 'drain', forbid)
    return fixture, finished, {'request_sha256': claims['request_sha256'],
        'reservation_digest': finished['reservation_digest'], 'company_event_id': fixture.request['company_event']['event_id'],
        'company_id': claims['company_id'], 'source_revision': claims['source_revision'],
        'blocking_cycle_id': CYCLE_ID, 'runtime_binding': fixture.runtime}


def evidence(fixture, selected):
    with (cli.writer_lock(fixture.root / 'scraper.lock'), cli.writer_lock(fixture.root / 'writer.lock'),
          closing(fixture.local()) as local):
        return read_pilot_outcome(local, **selected)


def test_verified_nonempty_publication_provides_one_current_sender_identity(tmp_path, monkeypatch):
    fixture, result, selected = pilot(tmp_path, monkeypatch)
    protected = ('state.db', 'inventories.sqlite3', 'jobs.sqlite3', 'retained-sessions.sqlite3')
    before = {name: (fixture.root / name).read_bytes() for name in protected}
    observed = evidence(fixture, selected)
    assert observed == evidence(fixture, selected)
    assert observed['outcome_id'] == result['outcome_id'] and observed['sender_state'] == 'READY'
    with closing(fixture.local()) as local:
        row, = local._outcome_delivery_rows(CONSUMER, outcome_id=observed['outcome_id'])
        assert observed['record_sha256'] == sha256(row[1].encode()).hexdigest()
    fixture.fetch.assert_not_called()
    fixture.open_remote.assert_not_called()
    assert {name: (fixture.root / name).read_bytes() for name in protected} == before


def test_verified_zero_cannot_authorize_the_confirmed_publication_delivery(tmp_path, monkeypatch):
    fixture, _, selected = pilot(tmp_path, monkeypatch, zero=True)
    with pytest.raises(ValueError, match='consumed confirmed publication'):
        evidence(fixture, selected)


def test_current_scope_and_inactive_queue_are_required(tmp_path, monkeypatch):
    fixture, _, selected = pilot(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match='approved owner'):
        evidence(fixture, {**selected, 'source_revision': 'f' * 64})
    (fixture.root / 'next-scan.json').write_text('{}')
    with pytest.raises(ValueError, match='ownership is still pending'):
        evidence(fixture, selected)
