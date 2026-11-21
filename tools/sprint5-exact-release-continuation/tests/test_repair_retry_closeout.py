"""Close one normally admitted retry with an existing exact publication."""
from copy import deepcopy
from unittest.mock import Mock

import pytest

from job_search_helper.ats import Inventory
from job_search_helper.cli import WriterLockBusy, writer_lock
from job_search_helper.exact_cycle_receipt import repair_retry_has_confirmed_publication
from job_search_helper.exact_cycle_recovery import close_published_repair_retry, recover_exact_cycle
from job_search_helper.sheet_profile import COMPACT_PROFILE, COMPACT_SCHEMAS
from test_exact_cycle_recovery import RecordingRemote
from test_repair_retry_admission_replay import admit, retry


@pytest.fixture
def published(retry):
    bridge, binding, engine, state = retry
    repo = engine.repo
    repo.ensure_columns('Opportunities', ['Opportunity ID'])
    repo.set_meta('sheets_profile', COMPACT_PROFILE)
    company_id = binding['company_id']
    url = repo.read('Companies')[0]['Official Careers URL']
    posting = {'posting_id': 'fixture-1', 'title': 'Implementation Manager', 'url': url + '/jobs/1',
               'location': 'Remote', 'description': 'Customer-facing implementation.', 'ats': 'AcquireTM'}
    fetch = Mock(spec=lambda *_: None, return_value=Inventory(
        'complete', [posting], source_url=url, ats='AcquireTM'))
    engine.fetcher = fetch
    assert bridge.deliver(binding)['state'] == 'REQUEST_WRITTEN'
    cycle_id = admit(bridge, engine, state)
    with writer_lock(bridge.database.parent / 'scraper.lock'):
        assert engine.resume_local(cycle_id, fetch_workers=1, assignment_window=1, defer_sync=True)[
            'attempted_company_ids'] == [company_id]
    fetch.assert_called_once()
    fetch.side_effect = AssertionError('Closeout must not fetch.')
    remote = RecordingRemote(repo.read('Companies'), schemas=COMPACT_SCHEMAS)
    remote.spreadsheet_id = repo.spreadsheet_id
    report = recover_exact_cycle(engine, remote, cycle_id, [company_id])
    assert report['confirmed'] == [company_id], report
    assert len(remote.commits) == 1
    cycle = state.cycle(cycle_id)
    assert cycle['status'] == 'In Progress' and cycle['companies'][company_id]['stage'] == 'complete'
    assert repair_retry_has_confirmed_publication(engine.inbox, repo, cycle, company_id, require_complete=False)
    assert not repair_retry_has_confirmed_publication(engine.inbox, repo, cycle, company_id)
    assert not repo.scrape_outcomes()
    yield engine, cycle_id, company_id, binding
    assert fetch.call_count == 1 and len(remote.commits) == 1


def close(published, **changes):
    engine, cycle_id, company_id, binding = published
    values = {'engine': engine, 'cycle_id': cycle_id, 'company_id': company_id,
              'attempt_id': binding['attempt_id'], 'release_id': binding['release']['release_id']}
    return close_published_repair_retry(**(values | changes))


def mirror(engine, cycle_id):
    [(_, row)] = engine.repo.matches('Scan Cycles', {'Cycle ID': cycle_id})
    return row


@pytest.mark.parametrize('cut', [None, 'mirror-before-state', 'state-before-outcome'])
def test_closeout_is_scoped_and_replays_without_rewriting(published, monkeypatch, cut):
    engine, cycle_id, company_id, binding = published
    root = engine.repo.path.parent
    prior = deepcopy(engine.state.cycle(cycle_id))
    unrelated = {'id': 'CYC-UNRELATED', 'status': 'Complete', 'companies': {}}
    engine.state.save_cycle(unrelated)
    snapshot = {tab: engine.repo.read(tab) for tab in ('Companies', 'Job History', 'Job Evidence', 'Opportunities')}
    inbox = tuple(engine.inbox.connection.iterdump())
    archived = (root / 'last-scan-request.json').read_bytes()
    pending = root / 'next-scan.json'
    journal = (root / 'integration-release-journal.json').read_bytes()

    if cut:
        def interrupt(*args, **kwargs):
            raise OSError('simulated closeout interruption')
        with monkeypatch.context() as crash:
            if cut == 'mirror-before-state':
                crash.setattr(engine.state, 'save_cycle', interrupt)
            else:
                crash.setattr(engine.repo, 'record_repair_retry_success', interrupt)
            with pytest.raises(OSError, match='interruption'):
                close(published)
        assert not engine.repo.scrape_outcomes()
        assert (engine.state.cycle(cycle_id) == prior) is (cut == 'mirror-before-state')
        settled_mirror = mirror(engine, cycle_id)
        assert settled_mirror['Cycle Status'] == 'Complete'
    else:
        settled_mirror = None

    outcome = close(published)
    after = engine.state.cycle(cycle_id)
    row = mirror(engine, cycle_id)
    assert after['status'] == row['Cycle Status'] == 'Complete'
    assert after['completed_at'] == row['Completed At']
    assert settled_mirror is None or row == settled_mirror
    assert outcome['outcome'] == 'COMPLETE'
    assert outcome['identity']['attempt_id'] == binding['attempt_id']
    assert repair_retry_has_confirmed_publication(engine.inbox, engine.repo, after, company_id)
    jobs = tuple(engine.repo.db.iterdump())
    assert close(published) == outcome
    assert tuple(engine.repo.db.iterdump()) == jobs
    assert engine.repo.scrape_outcomes() == [outcome]
    assert engine.state.cycle(cycle_id) == after and mirror(engine, cycle_id) == row
    assert engine.state.cycle(unrelated['id']) == unrelated
    assert {tab: engine.repo.read(tab) for tab in snapshot} == snapshot
    assert tuple(engine.inbox.connection.iterdump()) == inbox
    assert (root / 'last-scan-request.json').read_bytes() == archived and not pending.exists()
    assert (root / 'integration-release-journal.json').read_bytes() == journal


@pytest.mark.parametrize('defect', ['attempt', 'release', 'company', 'missing_ack', 'pending_receipt'])
def test_closeout_holds_without_changing_application_state(published, defect):
    engine, _, _, _ = published
    changes = {}
    if defect == 'missing_ack':
        engine.repo.db.execute('DELETE FROM exact_local_acknowledgements')
    elif defect == 'pending_receipt':
        with engine.inbox.connection:
            engine.inbox.connection.execute('UPDATE publication_receipts SET state=?', ('SYNC_PENDING',))
    else:
        changes[{'attempt': 'attempt_id', 'release': 'release_id', 'company': 'company_id'}[defect]] = 'wrong'
    before = (tuple(engine.repo.db.iterdump()), tuple(engine.inbox.connection.iterdump()), engine.state.cycles())
    with pytest.raises(ValueError):
        close(published, **changes)
    assert before == (tuple(engine.repo.db.iterdump()), tuple(engine.inbox.connection.iterdump()), engine.state.cycles())


def test_closeout_joins_both_existing_admission_locks(published):
    engine, cycle_id, _, _ = published
    for lock in ('scraper.lock', 'writer.lock'):
        with writer_lock(engine.repo.path.parent / lock):
            with pytest.raises(WriterLockBusy):
                close(published)
        assert engine.state.cycle(cycle_id)['status'] == 'In Progress'
        assert mirror(engine, cycle_id)['Cycle Status'] == 'In Progress'
        assert not engine.repo.scrape_outcomes()
    assert close(published)['outcome'] == 'COMPLETE'
