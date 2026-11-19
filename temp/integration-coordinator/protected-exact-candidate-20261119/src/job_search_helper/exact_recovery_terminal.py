"""Read-only qualification of retained terminal recovery holds."""
from __future__ import annotations

import hashlib
import json

from .publication_receipts import SYNC_CONFIRMED, record_fingerprints

MANIFEST_VERSION = 'exact-recovery-terminal-hold-v1'


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def _plan_digest(plan):
    return _digest(plan)


def _expected_receipt(cycle, company_id, payload, plan):
    from .exact_cycle_receipt import derive_receipt
    return derive_receipt(cycle, company_id, payload, plan, 'terminal-hold-proof')


def _confirmed_receipt(inbox, expected):
    # This detects ambiguity only; it is never proof for a different binding.
    company_id = expected['binding']['company_id']
    inbox.find_receipt(company_id, expected['records'])
    receipt = inbox.receipt(expected)
    if receipt is None:
        # A different binding for the same Company is still remote evidence,
        # not an excuse to use a legacy proof.
        return ('INVALID' if _company_receipts(inbox, company_id) else 'ABSENT', None)
    if receipt['state'] != SYNC_CONFIRMED:
        return 'INVALID', None
    if (receipt['binding'] != expected['binding'] or receipt['records'] != expected['records']
            or receipt['schedule'] != expected['schedule']):
        return 'INVALID', None
    return 'CONFIRMED', receipt


def _company_receipts(inbox, company_id):
    """Read-only receipt inventory for a no-plan terminal hold."""
    with inbox.lock:
        rows = inbox.connection.execute('SELECT binding,state FROM publication_receipts').fetchall()
    result = []
    for binding, state in rows:
        decoded = json.loads(binding)
        if str(decoded.get('company_id', '')).strip() == company_id:
            result.append({'binding': decoded, 'state': state})
    return result


def _legacy_proof(value, cycle_id, company_id, payload, plan, cursor, records, expected):
    if not isinstance(value, dict):
        raise ValueError('legacy_readback_proof_missing')
    required = {'version', 'read_only', 'cycle_id', 'company_id', 'inventory_digest',
                'plan_digest', 'cursor', 'count', 'records', 'selected_row_readback_digest',
                'proposed_receipt'}
    if set(value) != required or value.get('version') != 'legacy-selected-row-readback-v1':
        raise ValueError('legacy_readback_proof_schema_invalid')
    if (value['read_only'] is not True or value['cycle_id'] != cycle_id or value['company_id'] != company_id
            or value['inventory_digest'] != _digest(payload) or value['plan_digest'] != _plan_digest(plan)
            or value['cursor'] != cursor or value['count'] != len(plan['operations'])
            or value['records'] != records or not isinstance(value['selected_row_readback_digest'], str)
            or not value['selected_row_readback_digest']):
        raise ValueError('legacy_readback_proof_mismatch')
    proposed = value['proposed_receipt']
    if (not isinstance(proposed, dict) or set(proposed) != {'state', 'binding', 'records', 'schedule'}
            or proposed['state'] != 'PROPOSED' or proposed['binding'] != expected['binding']
            or proposed['records'] != expected['records'] or proposed['schedule'] != expected['schedule']):
        raise ValueError('legacy_readback_proof_receipt_invalid')
    return value


def qualify_terminal_holds(state, inbox, cycle_id, company_ids, *, readback_proof=None):
    """Return immutable manifests or fail-closed refusals without mutations.

    ``readback_proof`` is used only for legacy end-cursor plans with no receipt
    evidence. It must return the closed, versioned, read-only proof envelope
    validated by :func:`_legacy_proof`. The proposed receipt remains explicitly
    non-confirmed audit evidence in the manifest; this function never creates
    it, writes it, replays a plan, acknowledges an inventory, or saves State.
    """
    if not isinstance(cycle_id, str) or not cycle_id.strip():
        raise ValueError('exact_cycle_id_required')
    requested = [str(value).strip() for value in company_ids]
    if not requested or any(not value for value in requested) or len(set(requested)) != len(requested):
        raise ValueError('explicit_unique_company_ids_required')
    cycle = state.cycle(cycle_id)
    if not isinstance(cycle, dict) or cycle.get('id') != cycle_id:
        raise ValueError('exact_cycle_missing')
    report = {'version': MANIFEST_VERSION, 'cycle_id': cycle_id, 'qualified': [], 'held': []}
    for company_id in requested:
        try:
            item = cycle.get('companies', {}).get(company_id)
            if not isinstance(item, dict) or item.get('stage') not in {'blocked', 'unsupported'}:
                raise ValueError('checkpoint_not_terminal_hold')
            saved = inbox.get(cycle_id, company_id)
            if saved is None or not saved[1]:
                raise ValueError('inbox_not_blocked_hold')
            payload, _blocked = saved
            if not isinstance(payload, dict):
                raise ValueError('inventory_payload_invalid')
            manifest = {'version': MANIFEST_VERSION, 'cycle_id': cycle_id,
                        'company_id': company_id, 'stage': item['stage'],
                        'inventory_digest': _digest(payload), 'plan': None,
                        'receipt': None}
            planned = inbox.plan(cycle_id, company_id)
            if planned is not None:
                plan, cursor = planned
                if not isinstance(plan, dict) or not isinstance(plan.get('operations'), list):
                    raise ValueError('frozen_plan_invalid')
                if type(cursor) is not int or cursor < 0 or cursor != len(plan['operations']):
                    raise ValueError('frozen_plan_not_complete')
                records = record_fingerprints(plan['operations'])
                expected = _expected_receipt(cycle, company_id, payload, plan)
                receipt_state, receipt = _confirmed_receipt(inbox, expected)
                proof = None
                if receipt_state == 'INVALID':
                    raise ValueError('receipt_evidence_not_confirmed_or_mismatched')
                if receipt_state == 'ABSENT':
                    if not callable(readback_proof):
                        raise ValueError('confirmed_receipt_missing')
                    proof = _legacy_proof(readback_proof(cycle_id, company_id, plan, payload),
                                          cycle_id, company_id, payload, plan, cursor, records, expected)
                manifest['plan'] = {'digest': _plan_digest(plan), 'cursor': cursor,
                                    'count': len(plan['operations']), 'records': records}
                if receipt:
                    manifest['receipt'] = {'binding': receipt['binding'], 'records': receipt['records'],
                                           'schedule': receipt['schedule'], 'state': receipt['state']}
                elif proof is not None:
                    manifest['legacy_readback_proof'] = proof
            elif _company_receipts(inbox, company_id):
                # A receipt without a frozen plan is ambiguous remote work.
                raise ValueError('receipt_exists_without_frozen_plan')
            manifest['manifest_digest'] = _digest({key: value for key, value in manifest.items()
                                                    if key != 'manifest_digest'})
            report['qualified'].append(manifest)
        except Exception as exc:
            report['held'].append({'company_id': company_id, 'reason': str(exc) or type(exc).__name__})
    return report


def revalidate_terminal_manifest(state, inbox, manifest, *, readback_proof=None):
    """Compare a pause consumer's manifest to fresh qualification (CAS gate).

    A legacy manifest requires a new selected-row proof callable. Cached proof
    in the manifest is audit evidence, never current readback evidence.
    """
    if not isinstance(manifest, dict) or manifest.get('version') != MANIFEST_VERSION:
        raise ValueError('terminal_manifest_invalid')
    proof = readback_proof
    if manifest.get('legacy_readback_proof') is not None and not callable(proof):
        raise ValueError('fresh_legacy_readback_proof_required')
    report = qualify_terminal_holds(state, inbox, manifest.get('cycle_id'), [manifest.get('company_id')],
                                    readback_proof=proof)
    if len(report['qualified']) != 1 or report['qualified'][0].get('manifest_digest') != manifest.get('manifest_digest'):
        raise ValueError('terminal_manifest_changed_before_pause')
    return report['qualified'][0]
