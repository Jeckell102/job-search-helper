"""Read the exact bridge from an enrolled recipe build to independent release authority."""

from contextlib import closing, nullcontext
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

from acquiretm_membership_recipe import TARGET_PATH, build_current_owned
from amphenol_retry_completion import RetryReleaseApproval
import coding_tools
from coordinator import AMPHENOL_RECIPE_WORK_ORDER
from coordinator_inference import digest, valid_inference_binding
from coordinator_store import Store
from coordinator_workspace import workspace
from job_search_helper.integration_release import (
    canonical_manifest, config_tree_digest, metadata, source_tree_digest,
)


_CHOICE = {'summary': 'W1', 'next_action': 'listing_membership_change', 'outcome': 'phase_done'}


def read_owned_candidate_release(enrollment, coordinator, root, *, outcome_id, candidate_root, manifest):
    """Return the exact installer inputs or hold, under the existing owner leases."""
    approval = getattr(enrollment, 'retry_approval', None)
    if not isinstance(approval, RetryReleaseApproval):
        return None
    try:
        manifest = canonical_manifest(manifest)
        if (manifest['release_id'] != approval.release_id
                or manifest['company_id'] != 'COMP-0490'
                or manifest['failed_request_id'] != enrollment.request_id
                or manifest['source_revision'] != enrollment.source_revision
                or set(manifest['files']) != {TARGET_PATH}):
            return None

        store = coordinator.store
        task, receipt = _read_completed_build(store, outcome_id)
        prepared = enrollment._read(root, coordinator, outcome_id, task_id=task['id'])
        if (not prepared or prepared['binding']['outcome_id'] != outcome_id
                or receipt['prompt_digest'] != digest(prepared['messages'])
                or receipt['tools_digest'] != digest(prepared['tools'])):
            return None
        _require_generated_wrapper(store, task, prepared, receipt, manifest['files'][TARGET_PATH])

        candidate_root = Path(candidate_root)
        if candidate_root.is_symlink():
            return None
        candidate_root = candidate_root.resolve(strict=True)
        if (metadata(candidate_root / TARGET_PATH) != manifest['files'][TARGET_PATH]['after']
                or source_tree_digest(candidate_root) != manifest['source_manifest_sha256']
                or config_tree_digest(candidate_root) != manifest['config_sha256']):
            return None
        with approval.open() as owner:
            owner.require(manifest)
        return {'candidate_root': candidate_root, 'manifest': manifest, 'approval': approval,
                'task_id': task['id']}
    except (AttributeError, KeyError, OSError, RuntimeError, TypeError, ValueError, sqlite3.Error):
        return None


def _read_completed_build(store, outcome_id):
    uri = Path(store.path).resolve(strict=True).as_uri() + '?mode=ro'
    with closing(sqlite3.connect(uri, uri=True)) as db:
        db.execute('BEGIN')
        view = SimpleNamespace(connect=lambda: nullcontext(db))
        [held] = [item for item in Store.held_repair_intake(view) if item['outcome_id'] == outcome_id]
        task = Store.get(view, held['task_id'])
        [receipt] = Store.inference_receipts(view, task['id'])
    if (held['status'] != 'PROMOTED_PAUSED'
            or task['status'] != 'REVIEW_COMPLETE_LIVE_NOT_VALIDATED'
            or task.get('stop_requested') is not False
            or (task.get('mode'), task.get('phase')) != ('review', 'inspect')
            or task.get('isolated_workspace') is not True
            or task.get('baseline_passed') is not True
            or task['integration']['work_order'] != AMPHENOL_RECIPE_WORK_ORDER
            or (receipt['task'], receipt['phase'], receipt['status']) != (task['id'], 'inspect', 'COMPLETED')
            or receipt.get('accepted_recipe_choice') != _CHOICE
            or not valid_inference_binding(receipt['control_binding'], receipt['request_id'])):
        raise ValueError('The exact enrolled recipe has no completed owned build.')
    return task, receipt


def _require_generated_wrapper(store, task, prepared, receipt, file_binding):
    binding = prepared['binding']
    evidence = json.loads(prepared['messages'][1]['content'])['W1']
    selection = {'strategy': _CHOICE['next_action'], 'evidence': _CHOICE['summary']}
    with workspace(store, task):
        source = (coding_tools.root() / TARGET_PATH).read_bytes()
    built = build_current_owned(source, selection, binding['board'], evidence, binding)
    record = {
        **built['receipt'],
        'request_id': receipt['request_id'], 'response_digest': receipt['response_digest'],
        'outcome_id': binding['outcome_id'], 'company_id': binding['company_id'],
        'source_revision': binding['source_revision'],
    }
    target = Path(store.base).resolve(strict=True) / task['id'] / 'recipe-candidate'
    candidate = built['source'].encode()
    for name, expected in (
        (TARGET_PATH, candidate), ('reviewed.patch', built['diff'].encode()),
        ('build-receipt.json', (json.dumps(record, indent=2, sort_keys=True) + '\n').encode()),
    ):
        path = target / name
        if path.resolve(strict=True) != path or not _matches_bytes(metadata(path), expected):
            raise ValueError('The isolated recipe build changed after its owned choice.')
    if (not _matches_bytes(file_binding['before'], source)
            or not _matches_bytes(file_binding['after'], candidate)):
        raise ValueError('The approved release does not install this exact generated wrapper.')


def _matches_bytes(file_binding, raw):
    return (file_binding is not None and file_binding['size'] == len(raw)
            and file_binding['sha256'] == sha256(raw).hexdigest())
