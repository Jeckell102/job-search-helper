from pathlib import Path

import pytest

from job_search_helper import ats, cli, ordinary_verification_pending as pending, runner
from job_search_helper.engine import Engine
from job_search_helper.ordinary_verification_finisher import finish_published_ordinary
from job_search_helper.repository import RepositoryError
from test_s5_ordinary_publication_continuation import (
    COMPANY, COMPANY_ID, COMPACT_SCHEMAS, CYCLE_ID, RecordingRemote, WORKBOOK, measured_scope,
)
from test_s5_ordinary_worker_handoff import RUNTIME, attempt, local_worker, mismatch


def test_unarmed_reservation_stops_generic_launcher_and_engine(local_worker, monkeypatch):
    stores, handoff, _ = local_worker
    def cut(*args, **kwargs):
        raise RuntimeError('after Jobs commit')
    with monkeypatch.context() as interrupted:
        interrupted.setattr(pending, 'arm', cut)
        with pytest.raises(RuntimeError, match='after Jobs commit'):
            handoff.assignment()
    expected = ('generic runner held', 'generic Engine held')
    observed = []
    try:
        runner._assert_no_pending_ordinary_verification(Path(stores.state.path), jobs_path=stores.jobs.path)
    except (ValueError, RepositoryError):
        observed.append('generic runner held')

    class ProviderReached(BaseException):
        pass

    def provider(*args):
        raise ProviderReached()
    engine = Engine(stores.jobs, stores.state, inbox=stores.inbox, fetcher=provider, runtime_binding=RUNTIME)
    try:
        engine.resume_local(CYCLE_ID)
    except (ValueError, RepositoryError):
        observed.append('generic Engine held')
    except ProviderReached:
        observed.append('generic Engine reached provider')
    assert tuple(observed) == expected


def test_typed_mismatch_does_not_turn_complete_from_different_state_status(measured_scope, monkeypatch):
    launch, state, jobs, inbox = measured_scope
    monkeypatch.setattr(ats, 'fetch_inventory', lambda *args: mismatch())
    remote = RecordingRemote([COMPANY], schemas=COMPACT_SCHEMAS)
    remote.spreadsheet_id = WORKBOOK
    monkeypatch.setattr(cli, 'get_remote_repository', lambda **kwargs: remote)
    assert launch(resume=True, resume_cycle_id=CYCLE_ID, capture_ordinary_verification=True,
                  fetch_workers=1, browser_fallback=False) == 0
    assert launch(sync_only=True, sync_cycle_id=CYCLE_ID, sync_company_ids=[COMPANY_ID],
                  publish_ordinary_verification=True) == 0
    with cli.writer_lock(state.parent / 'writer.lock'), pending.open_verification_stores(
        state, jobs, inbox, WORKBOOK, writable_jobs=True,
    ) as stores:
        cycle = stores.state.cycle(CYCLE_ID)
        saved_stage = cycle['companies'][COMPANY_ID]['stage']
        assert saved_stage == 'partial'
        cycle['companies'][COMPANY_ID]['inventory_status'] = 'complete'
        stores.state.save_cycle(cycle)
        try:
            result = finish_published_ordinary(stores, cycle['runtime_binding'], CYCLE_ID, COMPANY_ID)
        except RepositoryError:
            result = {'state': 'REFUSED'}
        assert result['state'] in {'REFUSED', 'VERIFICATION_PENDING'}
        assert stores.jobs.scrape_outcomes() == []


def test_private_plain_argument_cannot_write_before_publication(local_worker):
    stores, handoff, _ = local_worker
    handoff.assignment()
    cycle = stores.state.cycle(CYCLE_ID)
    owner = pending.read_marker(cycle, COMPANY_ID)['owner']
    facts = {key: owner[key] for key in ('cycle_id', 'request_id', 'company_id', 'source_revision')}
    facts.update(source_current=True, company_status='Active', storage_status='confirmed', inventory_status='complete')
    with pytest.raises(RepositoryError, match='exact verification finisher'):
        with stores.jobs.transaction():
            stores.jobs._record_scrape_outcome_in_transaction(facts)


@pytest.mark.parametrize('endpoint', ['assess', 'pause'])
def test_direct_interrupted_recovery_holds_unarmed_reservation(local_worker, monkeypatch, endpoint):
    stores, handoff, _ = local_worker

    def cut(*args, **kwargs):
        raise RuntimeError('after Jobs commit')

    with monkeypatch.context() as interrupted:
        interrupted.setattr(pending, 'arm', cut)
        with pytest.raises(RuntimeError, match='after Jobs commit'):
            handoff.assignment()
    cycle = stores.state.cycle(CYCLE_ID)
    assert pending.read_marker(cycle, COMPANY_ID) is None
    assert stores.inbox.get(CYCLE_ID, COMPANY_ID) is None

    class ReachedCycleMirror(RuntimeError):
        pass

    def should_not_read(*args):
        raise ReachedCycleMirror()

    monkeypatch.setattr(stores.jobs, 'read', should_not_read)
    engine = Engine(stores.jobs, stores.state, inbox=stores.inbox, runtime_binding=RUNTIME)
    with pytest.raises(ValueError, match='exact owned continuation'):
        if endpoint == 'assess':
            engine.assess_interrupted_cycle_recovery(CYCLE_ID)
        else:
            engine.pause_interrupted_cycle(CYCLE_ID, reason='fixture interrupted recovery')
    assert stores.state.cycle(CYCLE_ID) == cycle
    assert stores.inbox.get(CYCLE_ID, COMPANY_ID) is None
    assert stores.jobs.scrape_outcomes() == []
