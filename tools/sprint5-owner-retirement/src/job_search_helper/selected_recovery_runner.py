"""Explicit local-only commands for signed selected legacy recovery.

Neither command initializes Google clients, invokes the normal scraper, opens
the review queue, creates a publication receipt, or progresses remote work.
Preview opens both databases read-only.  Apply validates signed scope before a
writable SQLite connection is opened, then holds the normal local writer lock
while it journals/reconciles this one selected successor.
"""
from __future__ import annotations

import argparse
import base64
import json
from contextlib import nullcontext
from pathlib import Path

from .exact_legacy_migration_runner import _controls, _read_retained, _required
from .inbox import InventoryInbox
from .exact_local_plan import adopt_verified_legacy_prefix, commit_exact_local_plan
from .exact_selected_legacy_recovery import (build_selected_legacy_v2_plan,
                                             preview_selected_legacy_binding)
from .selected_recovery_authorization import (Ed25519AuthorizationVerifier,
                                              required_claims,
                                              required_cancellation_claims,
                                              verify_authorization,
                                              verify_cancellation_authorization)
from .sqlite_repository import SQLiteRepository, timestamp


def _build_readonly(inventory_path, local_path, cycle_id, company_id):
    """Build frozen candidate evidence without opening either DB for writes."""
    cycle_id = _required(cycle_id, "cycle ID")
    company_id = _required(company_id, "Company ID")
    destination, payload, legacy, cursor, legacy_state = _read_retained(
        inventory_path, cycle_id, company_id)
    local = SQLiteRepository(local_path, destination, readonly=True)
    try:
        controls = _controls(local, company_id, legacy.get("requested_url"))
        binding = preview_selected_legacy_binding(
            local, cycle_id=cycle_id, company_id=company_id, payload=payload,
            legacy_plan=legacy, cursor=cursor, controls=controls)
        plan, report = build_selected_legacy_v2_plan(
            local, cycle_id=cycle_id, company_id=company_id, payload=payload,
            legacy_plan=legacy, cursor=cursor, controls=controls,
            binding=binding)
    finally:
        local.close()
    return destination, payload, legacy, cursor, legacy_state, binding, plan, report


def preview_selected_recovery(inventory_path, local_path, cycle_id, company_id,
                              *, expires_at):
    """Return sanitized exact-scope pins; strictly no database mutation."""
    (_destination, _payload, _legacy, _cursor, legacy_state, binding, plan,
     report) = _build_readonly(inventory_path, local_path, cycle_id, company_id)
    claims = required_claims(cycle_id=cycle_id, company_id=company_id,
                             plan=plan, recovery=plan["selected_legacy_recovery"],
                             expires_at=expires_at)
    return {"cycle_id": cycle_id, "company_id": company_id,
            "legacy_state": legacy_state, "binding": binding,
            "authorization_claims": claims, "plan_digest": plan["plan_digest"],
            "remote_projection_digest": plan["remote_projection_digest"],
            "verified_prefix_cursor": report["verified_prefix_cursor"],
            "remaining_operation_count": report["remaining_operation_count"],
            "mutation_performed": False, "remote_write_performed": False,
            "receipt_created": False}


def apply_selected_recovery(inventory_path, local_path, cycle_id, company_id,
                            authorization, verifier, *, lock_factory=None,
                            allow_test_verifier=False):
    """Adopt one signed selected successor into the ordinary v2 local path.

    The command stops at ``V2_PLAN_FROZEN``.  It never declares a remote plan,
    creates a receipt, or calls Sheets; a later explicit exact-v2 publication
    must pass the inbox authorization/expiry gate.
    """
    frozen = InventoryInbox.sealed_selected_legacy_recovery(
        inventory_path, cycle_id, company_id)
    report = None
    if frozen is not None:
        plan = frozen.get('candidate')
        recovery = (frozen.get('evidence') or {}).get('recovery')
        if not isinstance(plan, dict) or not isinstance(recovery, dict):
            raise ValueError('selected_recovery_current_journal_evidence_invalid')
        claims = required_claims(
            cycle_id=cycle_id, company_id=company_id, plan=plan,
            recovery=recovery, expires_at=frozen.get('authorization_expires_at'))
        authorization_evidence = verify_authorization(
            authorization, claims, verifier, allow_test_verifier=allow_test_verifier)
        if (authorization_evidence['authorization_digest'] != frozen.get('authorization_digest')
                or authorization_evidence['claims_digest'] != frozen.get('claims_digest')
                or authorization_evidence['key_id'] != frozen.get('key_id')):
            raise ValueError('selected_recovery_current_journal_authorization_mismatch')
        from .exact_local_plan import _validate_plan
        _validate_plan(plan, cycle_id, company_id)
        destination = InventoryInbox.destination_id(inventory_path)
    else:
        (destination, _payload, _legacy, _cursor, _legacy_state, _binding, plan,
         report) = _build_readonly(inventory_path, local_path, cycle_id, company_id)
        payload = authorization.get('payload') if isinstance(authorization, dict) else None
        expires_at = payload.get('expires_at') if isinstance(payload, dict) else None
        claims = required_claims(
            cycle_id=cycle_id, company_id=company_id, plan=plan,
            recovery=plan['selected_legacy_recovery'], expires_at=expires_at)
        authorization_evidence = verify_authorization(
            authorization, claims, verifier, allow_test_verifier=allow_test_verifier)

    context = lock_factory() if lock_factory is not None else _default_lock(local_path)
    with context:
        from .retained_cycle_retirement_control import assert_cycle_path_not_retired
        assert_cycle_path_not_retired(Path(inventory_path).parent / "state.db", cycle_id)
        if frozen is None:
            # Re-read immutable candidate inputs while the writer boundary is
            # held, but do so before either SQLite database is opened writable.
            (fresh_destination, _payload, _legacy, _cursor, _legacy_state,
             _binding, fresh_plan, _fresh_report) = _build_readonly(
                 inventory_path, local_path, cycle_id, company_id)
            if fresh_destination != destination or fresh_plan != plan:
                raise ValueError('selected_recovery_candidate_changed_before_apply')
        inbox = InventoryInbox(inventory_path, destination)
        local = SQLiteRepository(local_path, destination, readonly=False)
        try:
            if frozen is None:
                inbox.begin_selected_legacy_recovery(
                    cycle_id, company_id, plan, authorization_evidence,
                    timestamp=timestamp())
            current = inbox.selected_legacy_recovery_state(cycle_id, company_id)
            if current is None:
                raise ValueError('selected_recovery_current_journal_missing')
            if current['state'] == 'FROZEN':
                adopt_verified_legacy_prefix(
                    local, cycle_id, company_id, plan, timestamp_value=timestamp())
                inbox.mark_selected_legacy_prefix_verified(
                    cycle_id, company_id, plan, local, timestamp=timestamp())
            current = inbox.selected_legacy_recovery_state(cycle_id, company_id)
            if current['state'] == 'PREFIX_VERIFIED':
                commit_exact_local_plan(local, cycle_id, company_id, plan)
                inbox.mark_selected_legacy_local_verified(
                    cycle_id, company_id, plan, local, timestamp=timestamp())
            current = inbox.selected_legacy_recovery_state(cycle_id, company_id)
            if current['state'] == 'SELECTED_LOCAL_VERIFIED':
                inbox.freeze_selected_legacy_successor(
                    cycle_id, company_id, plan, local, timestamp=timestamp())
            final = inbox.selected_legacy_recovery_state(cycle_id, company_id)
        finally:
            local.close(); inbox.close()
    if final is None or final['state'] not in {'V2_PLAN_FROZEN', 'REMOTE_PLAN_FROZEN'}:
        raise ValueError('selected_recovery_current_journal_not_terminal')
    return {'cycle_id': cycle_id, 'company_id': company_id,
            'plan_digest': plan['plan_digest'],
            'remote_projection_digest': plan['remote_projection_digest'],
            'state': final['state'],
            'authorization_digest': authorization_evidence['authorization_digest'],
            'verified_prefix_cursor': claims['verified_prefix_cursor'],
            'receipt_created': False, 'remote_write_performed': False,
            'recovered': frozen is not None or report is None}


def _default_lock(local_path):
    from .cli import scraper_lock_name, writer_lock
    return writer_lock(
        Path(local_path).resolve().parent / scraper_lock_name())


def cancel_selected_recovery(inventory_path, local_path, cycle_id, company_id,
                             authorization, verifier, *, lock_factory=None,
                             allow_test_verifier=False):
    """Archive one untouched FROZEN candidate for full-legacy observation."""
    frozen = InventoryInbox.sealed_selected_legacy_recovery(
        inventory_path, cycle_id, company_id)
    if frozen is None:
        archived = InventoryInbox.archived_selected_legacy_cancellation(
            inventory_path, cycle_id, company_id)
        if archived is not None:
            frozen = archived['selected_recovery']
    if frozen is None or frozen.get('state') != 'FROZEN':
        raise ValueError('selected_recovery_cancellation_requires_frozen_candidate')
    plan = frozen.get('candidate')
    recovery = (frozen.get('evidence') or {}).get('recovery')
    if not isinstance(plan, dict) or not isinstance(recovery, dict):
        raise ValueError('selected_recovery_cancellation_evidence_invalid')
    payload = authorization.get('payload') if isinstance(authorization, dict) else None
    expires_at = payload.get('expires_at') if isinstance(payload, dict) else None
    claims = required_cancellation_claims(
        cycle_id=cycle_id, company_id=company_id, plan=plan,
        recovery=recovery, frozen=frozen, expires_at=expires_at)
    verified = verify_cancellation_authorization(
        authorization, claims, verifier, allow_test_verifier=allow_test_verifier)
    context = lock_factory() if lock_factory is not None else _default_lock(local_path)
    with context:
        from .retained_cycle_retirement_control import assert_cycle_path_not_retired
        assert_cycle_path_not_retired(Path(inventory_path).parent / "state.db", cycle_id)
        destination = InventoryInbox.destination_id(inventory_path)
        inbox = InventoryInbox(inventory_path, destination)
        local = SQLiteRepository(local_path, destination, readonly=False)
        try:
            return inbox.cancel_frozen_selected_legacy_recovery(
                cycle_id, company_id, local,
                cancellation_authorization=verified,
                frozen_authorization_digest=frozen['authorization_digest'],
                frozen_claims_digest=frozen['claims_digest'],
                frozen_key_id=frozen['key_id'],
                successor_plan_digest=plan['plan_digest'],
                reason='full_legacy_observation_handoff', timestamp=timestamp())
        finally:
            local.close(); inbox.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preview", "apply", "cancel"))
    parser.add_argument("--inventory", required=True)
    parser.add_argument("--local-db", required=True)
    parser.add_argument("--cycle", required=True)
    parser.add_argument("--company", required=True)
    parser.add_argument("--expires-at", help="Required for preview")
    parser.add_argument("--authorization", help="Signed JSON envelope; required for apply")
    parser.add_argument("--key-id", help="External public-key identifier; required for apply")
    parser.add_argument("--ed25519-public-key-base64", help="External public key; required for apply")
    args = parser.parse_args(argv)
    if args.command == "preview":
        if not args.expires_at:
            parser.error("preview requires --expires-at")
        result = preview_selected_recovery(args.inventory, args.local_db, args.cycle,
                                           args.company, expires_at=args.expires_at)
    else:
        if not (args.authorization and args.key_id and args.ed25519_public_key_base64):
            parser.error("apply/cancel requires --authorization, --key-id, and --ed25519-public-key-base64")
        try:
            envelope = json.loads(Path(args.authorization).read_text(encoding="utf-8"))
            public_key = base64.b64decode(args.ed25519_public_key_base64, validate=True)
        except Exception as error:
            parser.error("apply authorization/public key input is invalid: %s" % error)
        verifier = Ed25519AuthorizationVerifier({args.key_id: public_key})
        if args.command == "apply":
            result = apply_selected_recovery(
                args.inventory, args.local_db, args.cycle, args.company,
                envelope, verifier)
        else:
            result = cancel_selected_recovery(
                args.inventory, args.local_db, args.cycle, args.company,
                envelope, verifier)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
