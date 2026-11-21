"""Signed, durable local-only hold for late-Company selected recovery.

This command intentionally stops after recording signed evidence.  It does
not modify the local job store, run a scraper, create a receipt, or touch a
remote service.  There is no generic apply/release fallback for this variant.
"""
from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
import stat

from .control_before_prefix_authorization import (
    required_control_before_prefix_claims,
    verify_control_before_prefix_authorization,
)
from .exact_legacy_migration_runner import _controls, _read_retained, _required
from .exact_control_before_prefix_recovery import (
    build_control_before_prefix_v2_plan, preview_control_before_prefix_binding,
)
from .inbox import InventoryInbox
from .sqlite_repository import SQLiteRepository, timestamp


def _build_readonly(inventory_path, local_path, cycle_id, company_id):
    """Build the candidate with read-only connections only."""
    cycle_id, company_id = _required(cycle_id, 'cycle ID'), _required(company_id, 'Company ID')
    destination, payload, legacy, cursor, legacy_state = _read_retained(
        inventory_path, cycle_id, company_id)
    local = SQLiteRepository(local_path, destination, readonly=True)
    try:
        controls = _controls(local, company_id, legacy.get('requested_url'))
        binding = preview_control_before_prefix_binding(
            local, cycle_id=cycle_id, company_id=company_id, payload=payload,
            legacy_plan=legacy, cursor=cursor, controls=controls)
        plan, report = build_control_before_prefix_v2_plan(
            local, cycle_id=cycle_id, company_id=company_id, payload=payload,
            legacy_plan=legacy, cursor=cursor, controls=controls, binding=binding)
    finally:
        local.close()
    return destination, payload, legacy, cursor, legacy_state, binding, plan, report


def preview_control_before_prefix_recovery(inventory_path, local_path, cycle_id,
                                           company_id, *, expires_at):
    (_destination, _payload, _legacy, _cursor, legacy_state, binding, plan,
     report) = _build_readonly(inventory_path, local_path, cycle_id, company_id)
    recovery = plan['selected_legacy_control_before_prefix_recovery']
    claims = required_control_before_prefix_claims(
        cycle_id=cycle_id, company_id=company_id, plan=plan, recovery=recovery,
        expires_at=expires_at)
    return {'cycle_id': cycle_id, 'company_id': company_id, 'legacy_state': legacy_state,
            'binding': binding, 'authorization_claims': claims,
            'plan_digest': plan['plan_digest'],
            'remote_projection_digest': plan['remote_projection_digest'],
            'mutation_performed': False, 'local_write_performed': False,
            'remote_write_performed': False, 'receipt_created': False}


def preview_control_before_prefix_source_transition(inventory_path, local_path, cycle_id,
                                                    company_id):
    """Build a guarded proposal from saved rows without granting apply authority."""
    from .exact_control_before_prefix_recovery import (
        preview_control_before_prefix_source_transition as preview_transition,
    )

    cycle_id = _required(cycle_id, 'cycle ID')
    company_id = _required(company_id, 'Company ID')
    inventory_path, local_path = (
        Path(path).resolve(strict=True) for path in (inventory_path, local_path)
    )
    before = _checkpointed_inputs(inventory_path, local_path)
    destination, payload, legacy, cursor, _state = _read_retained(
        inventory_path, cycle_id, company_id, immutable=True)
    local = SQLiteRepository(local_path, destination, readonly=True, immutable=True)
    try:
        local.db.execute('PRAGMA query_only=ON')
        local.db.execute('BEGIN')
        controls = _controls(local, company_id, legacy.get('requested_url'))
        proposal = preview_transition(
            local, cycle_id=cycle_id, company_id=company_id, payload=payload,
            legacy_plan=legacy, cursor=cursor, controls=controls)
    finally:
        local.close()
    if _checkpointed_inputs(inventory_path, local_path) != before:
        raise ValueError('Source transition preview inputs changed during the read.')
    return {**proposal['report'], 'mutation_performed': False,
            'local_write_performed': False, 'remote_write_performed': False,
            'receipt_created': False}


def _checkpointed_inputs(*databases):
    """Reject pending SQLite changes before using immutable mode."""
    identities = {}
    for database in databases:
        for suffix in ('', '-wal', '-journal'):
            path = database.with_name(database.name + suffix)
            try:
                info = path.lstat()
            except FileNotFoundError:
                if not suffix:
                    raise
                identities[path] = None
                continue
            if not stat.S_ISREG(info.st_mode) or (suffix and info.st_size):
                raise ValueError('Source transition preview requires checkpointed databases.')
            identities[path] = (info.st_dev, info.st_ino, info.st_size,
                                info.st_mtime_ns, info.st_ctime_ns)
    return identities


def apply_control_before_prefix_recovery(inventory_path, local_path, cycle_id,
                                         company_id, authorization, verifier, *,
                                         lock_factory=None, allow_test_verifier=False):
    """Verify authorization before durable write, then create only a local hold."""
    (destination, _payload, _legacy, _cursor, _legacy_state, _binding, plan,
     _report) = _build_readonly(inventory_path, local_path, cycle_id, company_id)
    payload = authorization.get('payload') if isinstance(authorization, dict) else None
    expires_at = payload.get('expires_at') if isinstance(payload, dict) else None
    claims = required_control_before_prefix_claims(
        cycle_id=cycle_id, company_id=company_id, plan=plan,
        recovery=plan['selected_legacy_control_before_prefix_recovery'],
        expires_at=expires_at)
    # Authentication happens before a writable inbox or local repository is opened.
    verified = verify_control_before_prefix_authorization(
        authorization, claims, verifier, allow_test_verifier=allow_test_verifier)
    context = lock_factory() if lock_factory is not None else nullcontext()
    with context:
        # Rebuild before opening the durable writer so a signed preview cannot
        # race a changed retained plan or local control snapshot.
        (fresh_destination, _payload, _legacy, _cursor, _legacy_state, _binding,
         fresh_plan, _report) = _build_readonly(
             inventory_path, local_path, cycle_id, company_id)
        if fresh_destination != destination or fresh_plan != plan:
            raise ValueError('control_before_prefix_candidate_changed_before_apply')
        inbox = InventoryInbox(inventory_path, destination)
        try:
            held = inbox.begin_control_before_prefix_recovery(
                cycle_id, company_id, plan, authorization, verifier,
                timestamp=timestamp(), allow_test_verifier=allow_test_verifier)
        finally:
            inbox.close()
    return {'cycle_id': cycle_id, 'company_id': company_id, 'state': held['state'],
            'plan_digest': plan['plan_digest'],
            'authorization_digest': verified['authorization_digest'],
            'local_write_performed': False, 'remote_write_performed': False,
            'receipt_created': False, 'recovered': held['recovered']}
