"""Compose the one saved, already locally applied retry through exact publication."""

from pathlib import Path

from job_search_helper.cli import writer_lock
from job_search_helper.exact_cycle_receipt import (
    repair_retry_has_confirmed_publication,
    require_current_repair_retry,
)
from job_search_helper.exact_cycle_sync import _company_guard, _validate_controls, publish_exact_cycle
from job_search_helper.release_controller import _require_qualified_retry
from job_search_helper.repair_retry import retry_request
from job_search_helper.retained_work_runner import assert_normal_lifecycle_not_held
from job_search_helper.scan_request import request_fingerprint, superseded_cycle_ids

from verified_note_guards import adopt_note_guards


def resume_notes_admitted(engine, binding, approval, *, qualification_owner, remote_factory,
                          synchronizer_type, timestamp):
    """Caller already holds measured scraper admission for this exact release."""
    database = Path(engine.state.path).resolve(strict=True)
    company = binding['company_id']
    cycle_id = approval['cycle_id']
    key = (cycle_id, company)
    with writer_lock(database.parent / 'writer.lock'):
        assert_normal_lifecycle_not_held(database.parent, engine.repo.path)
        _require_qualified_retry(database, binding, qualification_owner)
        cycle = engine.state.cycle(cycle_id)
        request = retry_request(binding, enqueued_at=binding['activated_at'])
        if (not cycle or cycle.get('id') != cycle_id or cycle.get('repair_retry') != binding
                or cycle.get('status') not in {'In Progress', 'Complete'}
                or cycle.get('request_fingerprint') != request_fingerprint(request, [company])
                or cycle_id in superseded_cycle_ids(engine.state.cycles())):
            raise ValueError('The exact previously applied note retry is no longer current.')
        require_current_repair_retry(cycle, company, engine.repo, database.parent)
        engine.assert_runtime_binding(cycle_id, sync_only=True)
        saved, active = engine.inbox.get(*key), engine.inbox.plan(*key)
        if saved is None and active is None:
            archived = engine.repo.db.execute(
                'SELECT scope.apply_id,parent.plan_digest FROM exact_retry_note_guard_archive AS scope '
                'JOIN exact_local_applications AS parent ON parent.apply_id=scope.apply_id '
                'WHERE parent.cycle=? AND parent.company=?', key,
            ).fetchone()
            if (archived != (approval['verified_scope']['apply_id'], approval['plan_digest'])
                    or not repair_retry_has_confirmed_publication(
                        engine.inbox, engine.repo, cycle, company, require_complete=False)):
                raise ValueError('A cleaned-up note publication must have its original terminal receipt.')
            return {'state': 'READY_FOR_CLOSEOUT', 'cycle_id': cycle_id}
        if (cycle['status'] != 'In Progress' or saved is None or saved[1] or active is None
                or active[0]['plan_digest'] != approval['plan_digest']):
            raise ValueError('The approved locally applied note plan or inventory is unavailable.')
        rows = engine.repo.matches('Companies', {'Company ID': company})
        local_company = rows[0][1] if len(rows) == 1 else {}
        if (local_company.get('Active Cycle ID') != cycle_id or local_company.get('Claimed By')
                or local_company.get('Claim Token')):
            raise ValueError('The selected Company is no longer owned by the note retry.')

        with remote_factory() as remote:
            if remote.spreadsheet_id != engine.repo.spreadsheet_id:
                raise ValueError('The workbook differs from the approved note publication destination.')

            def guard(selected, url):
                if selected != company:
                    raise ValueError('The note retry is restricted to the approved Company.')
                return _company_guard(engine.repo, remote, selected, url)

            _validate_controls(active[0], guard(company, saved[0]['requested_url']))
            adopt_note_guards(engine.inbox, engine.repo, cycle, company, approval, timestamp=timestamp)
            result = publish_exact_cycle(
                engine.inbox, cycle_id, remote, company_ids=[company], state=engine.state, local=engine.repo,
                company_guard=guard, synchronizer=synchronizer_type(engine.repo, remote),
            )
        if result['held'] or result['confirmed'] != [company]:
            return {'state': 'RETRY_PUBLICATION_HELD', **result}
    return {'state': 'READY_FOR_CLOSEOUT', 'cycle_id': cycle_id}
