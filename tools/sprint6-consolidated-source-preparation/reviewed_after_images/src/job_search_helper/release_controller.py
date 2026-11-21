"""Guarded release-to-retry orchestration for one reviewed integration."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile

from .integration_release import (
    _completed_receipt,
    _read_json,
    _verify_projected_release,
    activate_release,
    assert_active_release_binding,
    canonical_manifest,
    config_tree_digest,
    digest,
    source_tree_digest,
)
from .repair_retry import (
    REPAIR_RETRY_SCHEMA,
    RepairRetryBridge,
    canonical_retry_binding,
    retry_attempt_id,
    retry_request,
)


def release_and_schedule(project_root, candidate_root, database, record_root, manifest,
                         *, current_source_revision, dependency_digest, verify, fault=None):
    """Activate one exact release and durably schedule its fresh Company retry."""
    return _release_and_schedule(
        project_root, candidate_root, database, record_root, manifest,
        current_source_revision=current_source_revision, dependency_digest=dependency_digest,
        verify=verify, fault=fault,
    )


def release_and_schedule_qualified(project_root, candidate_root, database, record_root, manifest,
                                   *, qualification_owner, current_source_revision, dependency_digest,
                                   verify, fault=None, preinstall_guard=None):
    """Enter automatic installation only with an independently qualified candidate."""
    from .release_qualification import _QualificationOwner

    if not isinstance(qualification_owner, _QualificationOwner):
        raise ValueError('An independently configured release qualification owner is required')
    if not callable(verify):
        raise ValueError('Automated release still requires installed candidate verification')
    manifest = canonical_manifest(manifest)

    def preinstall(exact_manifest):
        if (source_tree_digest(candidate_root) != exact_manifest['source_manifest_sha256']
                or config_tree_digest(candidate_root) != exact_manifest['config_sha256']):
            raise ValueError('The complete candidate differs from the qualified source or configuration')
        _verify_projected_release(project_root, exact_manifest)
        qualification_owner.require(exact_manifest)
        if preinstall_guard is not None:
            preinstall_guard(exact_manifest)

    qualification_owner.require(manifest)
    return _release_and_schedule(
        project_root, candidate_root, database, record_root, manifest,
        current_source_revision=current_source_revision, dependency_digest=dependency_digest,
        verify=verify, fault=fault, preinstall=preinstall,
    )


def _release_and_schedule(project_root, candidate_root, database, record_root, manifest,
                          *, current_source_revision, dependency_digest, verify, fault, preinstall=None):
    receipt = activate_release(
        project_root, candidate_root, database, record_root, manifest,
        current_source_revision=current_source_revision,
        dependency_digest=dependency_digest, verify=verify, preinstall=preinstall,
    )
    _fault(fault, "after_activation")
    binding = _retry_binding(receipt)
    bridge = RepairRetryBridge(
        database, current_source_revision=current_source_revision,
    )
    scheduled = bridge.deliver(binding)
    result = {
        "state": scheduled["state"],
        "release_id": receipt["release_id"],
        "attempt_id": binding["attempt_id"],
        "failed_request_id": binding["failed_request_id"],
        "company_id": binding["company_id"],
        "source_revision": binding["source_revision"],
    }
    record = Path(record_root) / receipt["release_id"] / "release-to-retry.json"
    _write_json(record, result)
    return result


def _retry_binding(receipt):
    binding = {
        "schema": REPAIR_RETRY_SCHEMA,
        **{key: receipt[key] for key in (
            "failed_request_id", "company_id", "source_revision", "release", "activated_at",
        )},
    }
    return {**binding, "attempt_id": retry_attempt_id(binding)}


def _require_qualified_retry(database, binding, qualification_owner):
    from .release_qualification import _QualificationOwner

    if not isinstance(qualification_owner, _QualificationOwner):
        raise ValueError('An independently configured release qualification owner is required')
    journal = assert_active_release_binding(database.parent, binding['release'])
    record = Path(journal['record'])
    manifest = canonical_manifest(_read_json(record / 'manifest.json'))
    if journal.get('manifest_sha256') != digest(manifest):
        raise ValueError('Active repair release manifest differs from the durable journal')
    receipt = _completed_receipt(record / 'receipt.json', journal, manifest, require_digest=True)
    if _retry_binding(receipt) != binding:
        raise ValueError('Retry does not match the active release receipt')
    qualification_owner.require(manifest)
    if _read_qualified_retry_intent(database, binding['attempt_id']) != binding:
        raise ValueError('Retry differs from its durable schedule intent')


def _read_qualified_retry_intent(database, attempt_id):
    if not isinstance(attempt_id, str) or not re.fullmatch(r'RTRY-[0-9a-f]{24}', attempt_id):
        raise ValueError('A canonical released retry attempt ID is required')
    path = Path(database).parent / 'repair-retry' / 'intents' / (attempt_id + '.json')
    if path.is_symlink() or not path.is_file():
        raise ValueError('Qualified retry has no durable schedule intent')
    saved = _read_json(path)
    binding = canonical_retry_binding(saved)
    if saved != binding or binding['attempt_id'] != attempt_id:
        raise ValueError('Qualified retry schedule intent conflicts with its attempt ID')
    return binding


def continue_qualified_release_retry(engine, database, binding, *, qualification_owner, remote_factory):
    """Continue one already activated qualified release under its own scope.

    The caller supplies the Engine of the admitted installed worker. The
    remote factory is used only for a saved eligible inventory that still
    requires publication, while both scraper and writer leases are held.
    """
    from .cli import scraper_lock_name, writer_lock

    database = Path(database).resolve(strict=True)
    with writer_lock(database.parent / scraper_lock_name()):
        result = _continue_qualified_release_retry_admitted(
            engine, database, binding, qualification_owner=qualification_owner,
            remote_factory=remote_factory,
        )
    return _finish_qualified_release_retry(engine, binding, result, qualification_owner=qualification_owner)


def _continue_qualified_release_retry_admitted(engine, database, binding, *, qualification_owner, remote_factory):
    """Run one retry while the caller continuously owns measured scraper admission."""
    from .cli import job_database_path, state_path, storage_backend, writer_lock
    from .company_events import current_company_source_revision
    from .engine import Engine, State
    from .exact_cycle_recovery import _recover_exact_cycle_locked
    from .exact_cycle_receipt import repair_retry_has_confirmed_publication, require_current_repair_retry
    from .inbox import InventoryInbox
    from .retained_work_runner import assert_normal_lifecycle_not_held
    from .scan_request import _read_request, requested_scan, superseded_cycle_ids
    from .sqlite_repository import SQLiteRepository

    binding = canonical_retry_binding(binding)
    database = Path(database).resolve(strict=True)
    root = database.parent
    if (not isinstance(engine, Engine) or not isinstance(engine.repo, SQLiteRepository)
            or not isinstance(engine.inbox, InventoryInbox) or not isinstance(engine.state, State)
            or engine.repo.readonly or engine.state.readonly or storage_backend() != 'sqlite'
            or not callable(remote_factory)
            or Path(engine.state.path).resolve() != database
            or Path(engine.inbox.path).resolve() != root / 'inventories.sqlite3'
            or (database, engine.repo.path) not in (
                (state_path().resolve(), job_database_path().resolve()),
                (root / 'state.db', root / 'jobs.sqlite3'))
            or InventoryInbox.destination_id(root / 'inventories.sqlite3') != engine.repo.spreadsheet_id):
        raise ValueError('Qualified retry requires its admitted SQLite application stores')

    release = binding['release']
    if engine.runtime_binding != {'state': 'COMPLETE', **{
            key: value for key, value in release.items() if key != 'schema'}}:
        raise ValueError('Qualified retry requires the exact installed worker runtime')
    company_id = binding['company_id']
    request = retry_request(binding, enqueued_at=binding['activated_at'])
    with writer_lock(root / 'writer.lock'):
        assert_normal_lifecycle_not_held(root, engine.repo.path)
        _require_qualified_retry(database, binding, qualification_owner)
        if current_company_source_revision(engine.repo, company_id) != binding['source_revision']:
            raise ValueError('Qualified retry Company source is no longer current')
        queue = root / 'next-scan.json'
        if queue.is_file() and _read_request(queue) == (request, [company_id]):
            cycle_id = requested_scan(engine, engine.state, database, expected_repair_retry=binding)
        else:
            bridge = RepairRetryBridge(database, current_source_revision=None)
            if not bridge._already_admitted(request):
                return {'state': 'WAITING_FOR_EXACT_RETRY', 'attempt_id': binding['attempt_id']}
            [cycle_id] = [cycle['id'] for cycle in engine.state.cycles()
                          if cycle.get('start_request_id') == request['request_id']]
        cycle = engine.state.cycle(cycle_id)
        if (cycle is None or cycle.get('status') not in {'In Progress', 'Complete'}
                or cycle_id in superseded_cycle_ids(engine.state.cycles())):
            raise ValueError('Qualified retry cycle is no longer current')
        require_current_repair_retry(cycle, company_id, engine.repo, root)
        engine.assert_runtime_binding(cycle_id, sync_only=True)
        if not repair_retry_has_confirmed_publication(
                engine.inbox, engine.repo, cycle, company_id, require_complete=False):
            company_rows = engine.repo.matches('Companies', {'Company ID': company_id})
            company = company_rows[0][1] if len(company_rows) == 1 else {}
            if (company.get('Active Cycle ID') != cycle_id
                    or company.get('Claimed By') or company.get('Claim Token')):
                raise ValueError('Qualified retry no longer owns the active Company')
            saved = engine.inbox.get(cycle_id, company_id)
            if (saved is None and cycle['status'] == 'In Progress'
                    and cycle['companies'][company_id]['stage'] == 'queued'
                    and engine.inbox.plan(cycle_id, company_id) is None
                    and engine.inbox.exact_remote_state(cycle_id, company_id) is None):
                engine.resume_local(cycle_id, defer_sync=True, fetch_workers=1, assignment_window=1)
                saved = engine.inbox.get(cycle_id, company_id)
            if (saved is None or saved[1] or saved[0].get('inventory_status') != 'complete'
                    or not saved[0].get('jobs') or saved[0].get('browser_pending_urls')
                    or saved[0].get('browser_discovery_incomplete')):
                return {'state': 'RETRY_INVENTORY_HELD', 'cycle_id': cycle_id}
            with remote_factory() as remote:
                if getattr(remote, 'spreadsheet_id', None) != engine.repo.spreadsheet_id:
                    raise ValueError('Qualified retry publication destination differs from Jobs')
                publication = _recover_exact_cycle_locked(engine, remote, cycle_id, [company_id])
            if publication['held'] or len(publication['confirmed']) != 1:
                return {'state': 'RETRY_PUBLICATION_HELD', 'cycle_id': cycle_id}

    return {'state': 'READY_FOR_CLOSEOUT', 'cycle_id': cycle_id}


def _finish_qualified_release_retry(engine, binding, result, *, qualification_owner):
    """Close the same proven retry after the earlier scraper admission has ended."""
    if result['state'] != 'READY_FOR_CLOSEOUT':
        return result
    from .exact_cycle_recovery import close_published_repair_retry

    binding = canonical_retry_binding(binding)
    _require_qualified_retry(Path(engine.state.path), binding, qualification_owner)
    cycle_id = result['cycle_id']
    outcome = close_published_repair_retry(
        engine, cycle_id, binding['company_id'], attempt_id=binding['attempt_id'],
        release_id=binding['release']['release_id'],
    )
    return {'state': 'COMPLETE', 'cycle_id': cycle_id, 'outcome': outcome}


def _write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write((json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode())
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _fault(callback, stage):
    if callable(callback):
        callback(stage)
