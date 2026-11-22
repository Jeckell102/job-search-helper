"""Continue one released retry from its approved, already-saved inventory."""

from pathlib import Path

from job_search_helper.cli import writer_lock
from job_search_helper.exact_cycle_planner import _validate_existing_exact_plan_v2
from job_search_helper.exact_cycle_receipt import require_current_repair_retry
from job_search_helper.exact_cycle_recovery import _recover_exact_cycle_locked
from job_search_helper.exact_cycle_sync import _company_guard, _validate_controls
from job_search_helper.release_controller import _require_qualified_retry
from job_search_helper.repair_retry import retry_request
from job_search_helper.retained_work_runner import assert_normal_lifecycle_not_held
from job_search_helper.scan_request import request_fingerprint, superseded_cycle_ids

from rejected_retry_plan import select_successor


def recover_saved_retry_admitted(engine, binding, candidate, approval, *,
                                  qualification_owner, remote_factory, timestamp):
    """Caller must own measured scraper admission and the exact tool approval."""
    database = Path(engine.state.path).resolve(strict=True)
    root = database.parent
    cycle_id = approval['cycle_id']
    company = binding['company_id']
    with writer_lock(root / 'writer.lock'):
        assert_normal_lifecycle_not_held(root, engine.repo.path)
        _require_qualified_retry(database, binding, qualification_owner)
        cycle = engine.state.cycle(cycle_id)
        request = retry_request(binding, enqueued_at=binding['activated_at'])
        if (not cycle or cycle['id'] != cycle_id or cycle.get('repair_retry') != binding
                or cycle.get('status') not in {'In Progress', 'Complete'}
                or cycle.get('request_fingerprint') != request_fingerprint(request, [company])
                or cycle_id in superseded_cycle_ids(engine.state.cycles())):
            raise ValueError('The approved Company-only retry is no longer current.')
        require_current_repair_retry(cycle, company, engine.repo, root)
        engine.assert_runtime_binding(cycle_id, sync_only=True)
        saved = engine.inbox.get(cycle_id, company)
        if saved is None:
            selected = select_successor(engine.inbox, engine.repo, cycle, company, candidate, approval,
                                        timestamp=timestamp)
            if selected != 'SUCCESSOR_ALREADY_CONFIRMED':
                raise ValueError('The approved retry inventory is missing.')
            return {'state': 'READY_FOR_CLOSEOUT', 'cycle_id': cycle_id}
        if cycle['status'] != 'In Progress' or saved[1]:
            raise ValueError('The approved inventory is blocked or its cycle is finished.')
        rows = engine.repo.matches('Companies', {'Company ID': company})
        row = rows[0][1] if len(rows) == 1 else {}
        if row.get('Active Cycle ID') != cycle_id or row.get('Claimed By') or row.get('Claim Token'):
            raise ValueError('The retry no longer owns the selected Company.')
        payload = saved[0]
        _validate_existing_exact_plan_v2(candidate, payload, engine.repo, cycle_id, company,
                                         candidate['control_evidence_digest'])
        with remote_factory() as remote:
            if remote.spreadsheet_id != engine.repo.spreadsheet_id:
                raise ValueError('The workbook is not the approved retry destination.')
            controls = _company_guard(engine.repo, remote, company, payload['requested_url'])
            _validate_controls(candidate, controls)
            select_successor(engine.inbox, engine.repo, cycle, company, candidate, approval,
                             timestamp=timestamp)
            report = _recover_exact_cycle_locked(engine, remote, cycle_id, [company],
                                                 require_frozen_plans=True)
        if report['held'] or report['confirmed'] != [company]:
            return {'state': 'RETRY_PUBLICATION_HELD', **report}
    return {'state': 'READY_FOR_CLOSEOUT', 'cycle_id': cycle_id}
