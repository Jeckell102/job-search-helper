from contextlib import closing
import fcntl
import json
import sqlite3

import pytest

import amphenol_candidate_release as reader
import amphenol_operator_one_shot as one_shot
import amphenol_operator_retained_release as retained
from job_search_helper import cli, qualified_release_owner
from test_one_shot_independent import prepared


def request(prepared_case):
    args, events, store, tasks = prepared_case
    fresh = {key: value for key, value in args.items() if key != 'historical_task_id'}
    fresh['completed_task_id'] = args['historical_task_id']
    store.set_queue_enabled(False)
    for name in ('state.db', 'jobs.sqlite3', 'inventories.sqlite3'):
        (cli.state_path().parent / name).touch()

    def prove_owned():
        assert events == ['enter']
        for name in ('scheduler.lock', 'supervision.lock'):
            with (tasks / name).open('rb') as competing:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(competing, fcntl.LOCK_EX | fcntl.LOCK_NB)

    return fresh, prove_owned


@pytest.mark.parametrize('wrong_outcome', (False, True))
def test_fresh_success_path_owns_cut_and_compares_exact_terminal(prepared, monkeypatch, wrong_outcome):
    fresh, prove_owned = request(prepared)
    attempt, outcome = 'RTRY-' + 'a' * 24, 'OUT-' + 'b' * 24
    calls = []

    def read(enrollment, coordinator, root, **selected):
        prove_owned()
        calls.append('fresh-build')
        assert selected['completed_task_id'] == fresh['completed_task_id']
        assert selected['approval'] == fresh['approval']
        assert enrollment.request_sha256 == fresh['request_sha256']
        assert selected['canonical_baseline'] == root
        return {key: selected[key] for key in ('candidate_root', 'manifest')}

    def install(project, candidate, db, records, manifest, **selected):
        prove_owned()
        calls.append('qualified-release')
        assert db == project / 'state.db'
        assert records == project / 'integration-releases'
        return {'release': {'attempt_id': attempt}, 'retry': {'state': 'COMPLETE', 'outcome': {'outcome_id': outcome}}}

    def deliver(enrollment, coordinator, **selected):
        prove_owned()
        calls.append('terminal-delivery')
        assert selected == {'original_outcome': fresh['original_outcome'], 'approval': fresh['approval']}
        return {'state': 'RECIPE_RETRY_CONFIRMED', 'attempt_id': attempt,
                'outcome_id': 'OUT-' + 'c' * 24 if wrong_outcome else outcome}

    monkeypatch.setattr(reader, 'read_operator_generated_candidate_release', read)
    monkeypatch.setattr(qualified_release_owner, 'release_and_continue_qualified', install)
    monkeypatch.setattr(one_shot, 'deliver_qualified_operator_retry', deliver)
    result = one_shot.run_fresh_operator_release(execute=True, **fresh)
    assert result['state'] == ('HELD_OPERATOR_TERMINAL' if wrong_outcome else 'OPERATOR_RELEASE_CONFIRMED')
    assert calls == ['fresh-build', 'qualified-release', 'terminal-delivery']
    assert prepared[1] == ['enter', 'exit']


@pytest.mark.parametrize('status', ('PAUSED_ERROR', 'REVIEW_COMPLETE_LIVE_NOT_VALIDATED'))
def test_fresh_recovery_only_checks_active_release_for_completed_task(prepared, monkeypatch, status):
    fresh, prove_owned = request(prepared)
    state = {'id': fresh['completed_task_id'], 'status': status,
             'repair_provenance': {'outcome_id': fresh['original_outcome']}}
    with closing(sqlite3.connect(prepared[2].path)) as db, db:
        db.execute('INSERT INTO tasks VALUES (?,?)', (state['id'], json.dumps(state)))
    monkeypatch.setattr(reader, 'read_operator_generated_candidate_release', lambda *a, **ka: None)
    monkeypatch.setattr(qualified_release_owner, 'release_and_continue_qualified',
                        lambda *a, **ka: pytest.fail('released without an eligible fresh candidate'))

    def recover(**selected):
        prove_owned()
        assert status == 'REVIEW_COMPLETE_LIVE_NOT_VALIDATED'
        assert selected['outcome_id'] == fresh['original_outcome']
        return {'state': 'HELD_OPERATOR_RETAINED_QUALIFICATION'}

    monkeypatch.setattr(retained, '_resume_operator_retained_release', recover)
    result = one_shot.run_fresh_operator_release(execute=True, **fresh)
    assert result == {'state': 'HELD_OPERATOR_FRESH_BUILD_PREFLIGHT' if status == 'PAUSED_ERROR'
                      else 'HELD_OPERATOR_RETAINED_QUALIFICATION'}
