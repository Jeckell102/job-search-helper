"""Default-hold release preflight for one retained operator Amphenol repair.

This module deliberately owns no scheduler, queue, or source transformation.
It only reconnects a still-current operator settlement, its preserved completed
choice, exact recovered candidate, and an independently pinned qualification
owner to the existing guarded release primitive.
"""
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3

from acquiretm_membership_recipe import TARGET_PATH, build_current_owned
from coordinator import AMPHENOL_RECIPE_WORK_ORDER
from coordinator_inference import digest, valid_inference_binding
from job_search_helper.integration_release import (
    assert_active_release_binding, canonical_manifest, digest as release_digest, metadata, release_binding,
)
from job_search_helper.qualified_release_owner import release_and_continue_qualified
from job_search_helper.release_qualification import open_release_qualification_owner


_CHOICE = {'summary': 'W1', 'next_action': 'listing_membership_change', 'outcome': 'phase_done'}
_COMPANY = 'COMP-0490'


def _physical_directory(value):
    """Accept an existing absolute directory only through ordinary ancestors."""
    try:
        path = Path(value)
        if not path.is_absolute():
            return None
        current = Path(path.anchor)
        for name in path.parts[1:]:
            current /= name
            if current.is_symlink() or not current.is_dir():
                return None
        return path if path.resolve(strict=True) == path else None
    except (OSError, RuntimeError, TypeError, ValueError):
        return None


def _physical_file(value):
    """Reject an ordinary file reached through even one symlinked ancestor."""
    try:
        path = Path(value)
        if (not path.is_absolute() or path.is_symlink() or not path.is_file()
                or _physical_directory(path.parent) is None):
            return None
        return path if path.resolve(strict=True) == path else None
    except (OSError, RuntimeError, TypeError, ValueError):
        return None


def _historical_snapshot(store, task_id):
    """Read preserved task/receipt bytes through an existing SQLite file only."""
    path = _physical_file(getattr(store, 'path', None))
    if path is None:
        return None
    uri = path.as_uri() + '?mode=ro'
    with sqlite3.connect(uri, uri=True) as db:
        db.execute('BEGIN')
        row = db.execute('SELECT state FROM tasks WHERE id=?', (task_id,)).fetchone()
        receipts = db.execute(
            'SELECT data FROM inference_receipts WHERE task=? ORDER BY rowid', (task_id,)).fetchall()
    if row is None:
        return None
    return json.loads(row[0]), [json.loads(item[0]) for item in receipts]


def _same(path, expected):
    try:
        return metadata(path) == expected
    except (OSError, ValueError):
        return False


def _candidate_matches(project_root, candidate_root, prepared, receipt, manifest):
    """Rebuild the sole deterministic wrapper from the measured installed source."""
    try:
        project_root = _physical_directory(project_root)
        candidate_root = _physical_directory(candidate_root)
        if project_root is None or candidate_root is None:
            return False
        source_path = _physical_file(project_root / TARGET_PATH)
        if source_path is None:
            return False
        source = source_path.read_bytes()
        binding = prepared['binding']
        evidence = json.loads(prepared['messages'][1]['content'])['W1']
        built = build_current_owned(
            source, {'strategy': _CHOICE['next_action'], 'evidence': _CHOICE['summary']},
            binding['board'], evidence, binding)
        record = {**built['receipt'], 'request_id': receipt['request_id'],
                  'response_digest': receipt['response_digest'],
                  'outcome_id': binding['outcome_id'], 'company_id': binding['company_id'],
                  'source_revision': binding['source_revision']}
        files = {
            TARGET_PATH: built['source'].encode(),
            'reviewed.patch': built['diff'].encode(),
            'build-receipt.json': (json.dumps(record, indent=2, sort_keys=True) + '\n').encode(),
        }
        for name, raw in files.items():
            path = _physical_file(candidate_root / name)
            if path is None or path.read_bytes() != raw:
                return False
        listed = manifest['files'].get(TARGET_PATH)
        return (listed is not None and _same(candidate_root / TARGET_PATH, listed['after'])
                and sha256(source).hexdigest() == listed['before']['sha256'])
    except (KeyError, OSError, TypeError, ValueError):
        return False


def preflight_operator_retained_release(*, project_root, root, store, outcome_id, request_sha256,
                                        source_revision, historical_task_id, candidate_root, manifest,
                                        approval_path, approval_fd, owner_identity, approval_sha256):
    """Return existing primitive inputs only for the one complete retained proof."""
    try:
        from amphenol_recipe_choice_input import read_operator_owned_choice_input, read_operator_owned_source

        project_root = _physical_directory(project_root)
        root = _physical_directory(root)
        candidate_root = _physical_directory(candidate_root)
        if project_root is None or root is None or candidate_root is None:
            return None
        # The operator source reader opens these three current application
        # stores.  Bind their concrete paths before handing it a root, so an
        # alias cannot redirect State/Jobs/Inbox through a symlinked child.
        state_db = _physical_file(root / 'state.db')
        if (state_db is None or _physical_file(root / 'jobs.sqlite3') is None
                or _physical_file(root / 'inventories.sqlite3') is None):
            return None
        manifest = canonical_manifest(manifest)
        source = read_operator_owned_source(
            root, outcome_id=outcome_id, request_sha256=request_sha256,
            source_revision=source_revision)
        if source is None or source['stale'] or not source['acknowledged']:
            return None
        record = source['record']
        identity = record['identity']
        if (manifest['company_id'] != _COMPANY or manifest['failed_request_id'] != identity['request_id']
                or manifest['source_revision'] != source_revision
                or set(manifest['files']) != {TARGET_PATH}):
            return None
        snapshot = _historical_snapshot(store, historical_task_id)
        if snapshot is None:
            return None
        task, receipts = snapshot
        if (not isinstance(task, dict) or task.get('id') != historical_task_id
                or task.get('status') != 'PAUSED_ERROR' or task.get('isolated_workspace') is not True
                or task.get('repair_provenance') != {
                    'repair_key': task.get('held_repair_key'), 'outcome_id': outcome_id,
                    'company_id': _COMPANY, 'source_revision': source_revision}
                or task.get('integration', {}).get('work_order') != AMPHENOL_RECIPE_WORK_ORDER
                or len(receipts) != 1):
            return None
        [receipt] = receipts
        if ((receipt.get('task'), receipt.get('phase'), receipt.get('status')) !=
                (historical_task_id, 'inspect', 'COMPLETED')
                or receipt.get('accepted_recipe_choice') != _CHOICE
                or not valid_inference_binding(receipt.get('control_binding'), receipt.get('request_id'))):
            return None
        prepared = read_operator_owned_choice_input(
            root, store, outcome_id=outcome_id, request_sha256=request_sha256,
            enabled=True, expected_task_id=historical_task_id)
        if (not prepared or prepared['binding'].get('outcome_id') != outcome_id
                or prepared['binding'].get('request_id') != identity['request_id']
                or receipt.get('prompt_digest') != digest(prepared['messages'])
                or receipt.get('tools_digest') != digest(prepared['tools'])
                or not _candidate_matches(project_root, candidate_root, prepared, receipt, manifest)):
            return None
        # This opens a caller-supplied independent owner and verifies its exact
        # on-disk PASS receipt; a response field cannot label itself qualified.
        with open_release_qualification_owner(
                approval_path, approval_fd, expected_owner_identity=owner_identity,
                approved_receipt_sha256=approval_sha256) as owner:
            owner.require(manifest)
        return {'project_root': project_root, 'candidate_root': candidate_root,
                'manifest': manifest, 'database': state_db, 'record_root': root / 'integration-releases',
                'approval_path': approval_path, 'approval_fd': approval_fd,
                'owner_identity': owner_identity, 'approval_sha256': approval_sha256,
                'source_revision': source_revision}
    except (AttributeError, KeyError, OSError, RuntimeError, TypeError, ValueError, sqlite3.Error):
        return None


def continue_operator_retained_release(*, execute=False, current_source_revision, dependency_digest, verify,
                                       historical_task_id, **kwargs):
    """Preflight by default; explicit execution delegates to the existing primitive."""
    prepared = preflight_operator_retained_release(historical_task_id=historical_task_id, **kwargs)
    if prepared is None:
        return _resume_operator_retained_release(
            execute=execute, current_source_revision=current_source_revision,
            dependency_digest=dependency_digest, verify=verify, **kwargs,
        )
    if execute is not True:
        return {'state': 'HELD_OPERATOR_RETAINED_RELEASE_PREFLIGHT', 'release_id': prepared['manifest']['release_id']}
    return release_and_continue_qualified(
        prepared['project_root'], prepared['candidate_root'], prepared['database'],
        prepared['record_root'], prepared['manifest'], approval_path=prepared['approval_path'],
        approval_fd=prepared['approval_fd'], owner_identity=prepared['owner_identity'],
        approval_sha256=prepared['approval_sha256'], current_source_revision=current_source_revision,
        dependency_digest=dependency_digest, verify=verify)


def _resume_operator_retained_release(*, execute=False, current_source_revision, dependency_digest, verify,
                                      project_root, root, store, outcome_id, request_sha256, source_revision,
                                      candidate_root, manifest, approval_path, approval_fd,
                                      owner_identity, approval_sha256):
    """Resume only the same qualified completed activation and its durable retry."""
    from amphenol_retry_completion import _delivery_pair, _historical_operator_origin_matches
    from job_search_helper.engine import State
    from job_search_helper.inbox import InventoryInbox
    from job_search_helper.repository import RepositoryError
    from job_search_helper.scrape_outcome_delivery import CONSUMER, OutcomeDelivery
    from job_search_helper.sqlite_repository import SQLiteRepository

    held = {'state': 'HELD_OPERATOR_RETAINED_QUALIFICATION'}
    if (not isinstance(outcome_id, str) or not re.fullmatch(r'OUT-[0-9a-f]{24}', outcome_id)
            or not isinstance(request_sha256, str) or not re.fullmatch(r'[0-9a-f]{64}', request_sha256)):
        return held
    try:
        project_root = _physical_directory(project_root)
        candidate_root = _physical_directory(candidate_root)
        root = _physical_directory(root)
        if project_root is None or candidate_root is None or root is None:
            return held
        database, jobs, inbox = (_physical_file(root / name) for name in (
            'state.db', 'jobs.sqlite3', 'inventories.sqlite3',
        ))
        if None in (database, jobs, inbox) or _physical_file(getattr(store, 'path', None)) is None:
            return held
        manifest = canonical_manifest(manifest)
        if (manifest['company_id'] != _COMPANY or manifest['source_revision'] != source_revision
                or set(manifest['files']) != {TARGET_PATH}):
            return held
        released = release_binding(manifest)
        manifest_sha256 = release_digest(manifest)
        record_root = root / 'integration-releases'
        record = record_root / manifest['release_id']

        def active_source_revision(company_id):
            # The release primitive repeats this under its scraper lease. If
            # rollback wins first, recovery must never turn into installation.
            if _physical_file(root / 'integration-release-journal.json') is None:
                return None
            journal = assert_active_release_binding(root, released)
            if (journal['manifest_sha256'] != manifest_sha256 or journal['record'] != str(record)
                    or _physical_file(record / 'receipt.json') is None):
                return None
            return current_source_revision(company_id)

        if active_source_revision(_COMPANY) != source_revision:
            return held
        destination = InventoryInbox.destination_id(inbox)
        with (closing(SQLiteRepository(jobs, destination, readonly=True)) as repository,
              closing(State(database, readonly=True)) as state):
            [row] = repository._outcome_delivery_rows(CONSUMER, outcome_id=outcome_id)
            origin = OutcomeDelivery(repository, None)._preflight(row)
            receipt = _delivery_pair(store, origin, row)
            identity = origin[0]['identity']
            if (receipt is None or receipt['sink_status'] != 'HELD_FOR_REPAIR_TRIAGE'
                    or identity.get('company_id') != _COMPANY or identity.get('source_revision') != source_revision
                    or identity.get('request_id') != manifest['failed_request_id']
                    or not _historical_operator_origin_matches(repository, state, origin[0], request_sha256)):
                return held
        with open_release_qualification_owner(
            approval_path, approval_fd, expected_owner_identity=owner_identity,
            approved_receipt_sha256=approval_sha256,
        ) as owner:
            owner.require(manifest)
    except (AttributeError, KeyError, OSError, RepositoryError, RuntimeError, TypeError, ValueError, sqlite3.Error):
        return held

    if execute is not True:
        return {'state': 'HELD_OPERATOR_RETAINED_RECOVERY_PREFLIGHT', 'release_id': manifest['release_id']}
    return release_and_continue_qualified(
        project_root, candidate_root, database, record_root, manifest,
        approval_path=approval_path, approval_fd=approval_fd, owner_identity=owner_identity,
        approval_sha256=approval_sha256, current_source_revision=active_source_revision,
        dependency_digest=dependency_digest, verify=verify,
    )
