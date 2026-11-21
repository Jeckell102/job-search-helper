"""Run one already-qualified Amphenol operator repair during admitted maintenance."""

from contextlib import ExitStack, closing, contextmanager
import fcntl
import os
import re
import sqlite3
import stat
from types import SimpleNamespace

from amphenol_operator_retained_release import (
    _physical_directory, _physical_file, continue_operator_retained_release,
)
from amphenol_retry_completion import RetryReleaseApproval, deliver_qualified_operator_retry


class CoordinatorBusy(RuntimeError):
    """The existing coordinator's cross-process ownership is unavailable."""


@contextmanager
def _coordinator_lease(base):
    """Borrow the two existing host locks in the same order as service startup."""
    with ExitStack() as cleanup:
        for name in ('scheduler.lock', 'supervision.lock'):
            path = base / name
            try:
                descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
                cleanup.callback(os.close, descriptor)
                opened, named = os.fstat(descriptor), path.lstat()
                if (not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1
                        or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)):
                    raise CoordinatorBusy('Coordinator lease identity changed')
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise CoordinatorBusy('Coordinator lease is unavailable') from exc
        yield


def _coordinator_is_idle(path):
    """Read the explicit controls and current work without initializing the Store."""
    try:
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as reader:
            reader.execute('BEGIN')
            controls = dict(reader.execute(
                'SELECT key,value FROM settings WHERE key IN '
                "('queue_enabled','campaign_enabled','autopilot_enabled','pilot_task','disk_pressure_hold')"
            ))
            task = reader.execute(
                "SELECT 1 FROM tasks WHERE json_type(state,'$.status') IS NOT 'text' "
                "OR json_extract(state,'$.status') IN ('RUNNING','QUEUED','PAUSING') LIMIT 1"
            ).fetchone()
            inference = reader.execute(
                "SELECT 1 FROM inference_receipts WHERE status IN ('DISPATCHING','UNCERTAIN') LIMIT 1"
            ).fetchone()
    except sqlite3.Error:
        return False
    return (controls.get('queue_enabled') == 'false'
            and all(controls.get(name, 'false') == 'false' for name in (
                'campaign_enabled', 'autopilot_enabled', 'disk_pressure_hold',
            ))
            and controls.get('pilot_task', 'null') == 'null' and task is None and inference is None)


def run_operator_release(*, approval, original_outcome, request_sha256, historical_task_id,
                         maintenance_scope=None, execute=False):
    """Under a caller's guarded host exclusion, run the selected release through receipt."""
    return _run_operator_release(approval=approval, original_outcome=original_outcome,
        request_sha256=request_sha256, task_id=historical_task_id, maintenance_scope=maintenance_scope,
        execute=execute, fresh=False)


def run_fresh_operator_release(*, approval, original_outcome, request_sha256, completed_task_id,
                               maintenance_scope=None, execute=False, resume_complete=False):
    """Release the exact output of a successfully completed automatic build."""
    return _run_operator_release(approval=approval, original_outcome=original_outcome,
        request_sha256=request_sha256, task_id=completed_task_id, maintenance_scope=maintenance_scope,
        execute=execute, fresh=True, resume_complete=resume_complete)


def _continue_fresh_release(approval, enrollment, coordinator, task_id, release, *, resume_complete):
    from amphenol_candidate_release import read_operator_generated_candidate_release
    from amphenol_operator_retained_release import _resume_operator_retained_release
    from job_search_helper.qualified_release_owner import release_and_continue_qualified

    root = release['root']
    if (_physical_directory(root) is None or any(_physical_file(root / name) is None for name in (
            'state.db', 'jobs.sqlite3', 'inventories.sqlite3'))):
        return {'state': 'HELD_OPERATOR_APPLICATION_STORE'}
    candidate = None
    if not resume_complete:
        candidate = read_operator_generated_candidate_release(
            enrollment, coordinator, root, outcome_id=release['outcome_id'],
            candidate_root=release['candidate_root'], manifest=release['manifest'], completed_task_id=task_id,
            canonical_baseline=release['project_root'], approval=approval,
        )
    if candidate is None:
        # The input owner can move to the retry after activation. Only the
        # same completed build can attempt recovery. The existing recovery
        # verifier refuses before install unless the exact release is active.
        try:
            task = coordinator.store.get(task_id)
        except (KeyError, ValueError):
            task = {}
        if (task.get('status') != 'REVIEW_COMPLETE_LIVE_NOT_VALIDATED'
                or task.get('repair_provenance', {}).get('outcome_id') != release['outcome_id']):
            return {'state': 'HELD_OPERATOR_FRESH_BUILD_PREFLIGHT'}
        return _resume_operator_retained_release(execute=True, **release)
    return release_and_continue_qualified(
        release['project_root'], candidate['candidate_root'], root / 'state.db', root / 'integration-releases',
        candidate['manifest'], approval_path=release['approval_path'], approval_fd=release['approval_fd'],
        owner_identity=release['owner_identity'], approval_sha256=release['approval_sha256'],
        current_source_revision=release['current_source_revision'], dependency_digest=release['dependency_digest'],
        verify=release['verify'],
    )


def _run_operator_release(*, approval, original_outcome, request_sha256, task_id, maintenance_scope,
                          execute, fresh, resume_complete=False):
    if execute is not True:
        return {'state': 'HELD_OPERATOR_EXECUTION_NOT_REQUESTED'}
    if (not isinstance(approval, RetryReleaseApproval) or not callable(maintenance_scope)
            or type(resume_complete) is not bool
            or not isinstance(original_outcome, str) or not re.fullmatch(r'OUT-[0-9a-f]{24}', original_outcome)
            or not isinstance(request_sha256, str) or not re.fullmatch(r'[0-9a-f]{64}', request_sha256)
            or not isinstance(task_id, str) or not re.fullmatch(r'WRAP-[0-9a-f]{10}', task_id)):
        return {'state': 'HELD_OPERATOR_ONE_SHOT_INPUTS'}
    candidate, manifest = approval.read_install_inputs()
    if manifest['company_id'] != 'COMP-0490':
        return {'state': 'HELD_OPERATOR_ONE_SHOT_INPUTS'}

    from amphenol_installed_verification import verify_installed_amphenol_recipe
    from coordinator import Coordinator
    from host_server import BASE, JOB_SEARCH_ROOT, OperatorAmphenolRecipeEnrollment, current_company_revision
    from job_search_helper.cli import job_database_path, load_environment, state_path, storage_backend
    from job_search_helper.integration_release import dependency_manifest_digest

    # Existing native maintenance must exclude host startup, shutdown and
    # other Store writers. The service's flocks alone do not cover those cuts.
    with maintenance_scope():
        base = _physical_directory(BASE / 'tasks')
        database = _physical_file(base / 'tasks.sqlite3') if base is not None else None
        if database is None:
            return {'state': 'HELD_OPERATOR_COORDINATOR_STORE'}
        try:
            with _coordinator_lease(base):
                load_environment(JOB_SEARCH_ROOT / '.env')
                root = state_path().parent
                if (storage_backend() != 'sqlite' or state_path() != root / 'state.db'
                        or job_database_path() != root / 'jobs.sqlite3'):
                    return {'state': 'HELD_OPERATOR_APPLICATION_STORE'}
                if not _coordinator_is_idle(database):
                    return {'state': 'HELD_OPERATOR_COORDINATOR_CONTROLS'}
                coordinator = None
                enrollment = OperatorAmphenolRecipeEnrollment(
                    manifest['failed_request_id'], manifest['source_revision'], request_sha256=request_sha256,
                )
                with approval.descriptor() as owner_fd:
                    release = dict(
                        project_root=JOB_SEARCH_ROOT, root=root, store=SimpleNamespace(path=database),
                        candidate_root=candidate, manifest=manifest, outcome_id=original_outcome,
                        request_sha256=request_sha256, source_revision=manifest['source_revision'],
                        approval_path=approval.directory,
                        approval_fd=owner_fd, owner_identity=(approval.device, approval.inode),
                        approval_sha256=approval.receipt_sha256,
                        current_source_revision=current_company_revision,
                        dependency_digest=lambda: dependency_manifest_digest(JOB_SEARCH_ROOT),
                        verify=verify_installed_amphenol_recipe,
                    )
                    if fresh:
                        coordinator = Coordinator(base=base, company_revision_resolver=current_company_revision,
                                                  existing_store_only=True)
                        result = _continue_fresh_release(
                            approval, enrollment, coordinator, task_id, release, resume_complete=resume_complete)
                    else:
                        result = continue_operator_retained_release(
                            execute=True, historical_task_id=task_id, **release,
                        )
                retry = result.get('retry') or {}
                if retry.get('state') != 'COMPLETE':
                    return result
                if coordinator is None:
                    coordinator = Coordinator(base=base, company_revision_resolver=current_company_revision,
                                              existing_store_only=True)
                terminal = deliver_qualified_operator_retry(
                    enrollment, coordinator, original_outcome=original_outcome, approval=approval,
                )
                expected = {
                    'state': 'RECIPE_RETRY_CONFIRMED',
                    'attempt_id': result['release']['attempt_id'],
                    'outcome_id': retry['outcome']['outcome_id'],
                }
                return {
                    **result,
                    'state': 'OPERATOR_RELEASE_CONFIRMED' if terminal == expected else 'HELD_OPERATOR_TERMINAL',
                    'coordinator': terminal,
                }
        except CoordinatorBusy:
            return {'state': 'HELD_OPERATOR_COORDINATOR_BUSY'}
