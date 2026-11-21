from contextlib import closing
import hashlib
import json
from pathlib import Path
from shutil import copy2

from job_search_helper.engine import Engine, State
from job_search_helper.exact_cycle_receipt import repair_retry_has_confirmed_publication
from job_search_helper.exact_cycle_recovery import close_published_repair_retry
from job_search_helper.inbox import InventoryInbox
from job_search_helper.sqlite_repository import SQLiteRepository


def test_saved_publication(tmp_path, monkeypatch):
    monkeypatch.setenv('JOB_STORAGE_BACKEND', 'sqlite')
    original = Path('/tmp/jsh-s5-amphenol-publication-rehearsal/test-project/.state')
    names = ('state.db', 'jobs.sqlite3', 'inventories.sqlite3', 'integration-release-journal.json',
             'last-scan-request.json')
    before = {name: hashlib.sha256((original / name).read_bytes()).hexdigest() for name in names}
    for name in names:
        if name.endswith(('.db', '.sqlite3')):
            wal = original / f'{name}-wal'
            assert not wal.exists() or wal.stat().st_size == 0
        copy2(original / name, tmp_path / name)
    assert before == {name: hashlib.sha256((tmp_path / name).read_bytes()).hexdigest() for name in names}

    def no_fetch(*args, **kwargs):
        raise AssertionError('Provider fetch is prohibited.')

    with (closing(State(tmp_path / 'state.db')) as state,
          closing(SQLiteRepository(tmp_path / 'jobs.sqlite3', 'sheet')) as repo,
          closing(InventoryInbox(tmp_path / 'inventories.sqlite3', 'sheet')) as inbox):
        cid = 'CYC-8F35E1D030EF'
        company = 'COMP-0490'
        original_cycle = state.cycle(cid)
        engine = Engine(repo, state, inbox=inbox, runtime_binding=original_cycle['runtime_binding'], fetcher=no_fetch)
        carry = {'attempt_id': 'RTRY-94818009148713cd8859150f', 'release_id': 'REL-76cc6f8179568b839386f429'}
        predecessors = [c for c in state.cycles() if c['id'] != cid]
        other = {tab: repo.read(tab) for tab in ('Companies', 'Job History', 'Job Evidence', 'Opportunities')}
        outcomes = repo.scrape_outcomes()
        receipt = tuple(inbox.connection.iterdump())
        assert len(other['Job History']) == len(other['Job Evidence']) == 18
        assert original_cycle['status'] == 'In Progress'
        assert repair_retry_has_confirmed_publication(inbox, repo, original_cycle, company, require_complete=False)
        outcome = close_published_repair_retry(engine, cid, company, **carry)
        same = close_published_repair_retry(engine, cid, company, **carry)
        final = state.cycle(cid)
        [(_, mirror)] = repo.matches('Scan Cycles', {'Cycle ID': cid})
        assert outcome == same and outcome['outcome'] == 'COMPLETE'
        assert outcome['identity']['attempt_id'] == carry['attempt_id']
        assert final['status'] == mirror['Cycle Status'] == 'Complete'
        assert len(repo.scrape_outcomes()) == len(outcomes) + 1
        assert all(previous in repo.scrape_outcomes() for previous in outcomes)
        assert [c for c in state.cycles() if c['id'] != cid] == predecessors
        assert {tab: repo.read(tab) for tab in other} == other
        assert tuple(inbox.connection.iterdump()) == receipt
        assert not (tmp_path / 'next-scan.json').exists()
        result = {'cycle_id': cid, 'outcome_id': outcome['outcome_id'], 'state': final['status'],
                  'unchanged_confirmed_receipt': True, 'job_rows_preserved': 18, 'written_outcomes': 1}
        (Path(__file__).parent / 'SAVED_AMPhenol_RESULT.json').write_text(json.dumps(result, indent=2) + '\n')
    assert before == {name: hashlib.sha256((original / name).read_bytes()).hexdigest() for name in names}
    for name in names[3:]:
        assert hashlib.sha256((tmp_path / name).read_bytes()).hexdigest() == before[name]
