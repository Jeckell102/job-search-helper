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


def qualify_terminal_holds(state, inbox, cycle_id, company_ids):
    """Return immutable manifests or fail-closed refusals without mutations.

    A completed frozen plan requires its own durable ``SYNC_CONFIRMED`` receipt.
    There is deliberately no legacy callback or caller-supplied readback
    metadata escape hatch: only the narrow Sheets confirmation path may create
    that receipt after selected-row readback. This function never writes,
    replays a plan, acknowledges an inventory, or saves State.
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
                if receipt_state == 'INVALID':
                    raise ValueError('receipt_evidence_not_confirmed_or_mismatched')
                if receipt_state == 'ABSENT':
                    raise ValueError('confirmed_receipt_missing')
                manifest['plan'] = {'digest': _plan_digest(plan), 'cursor': cursor,
                                    'count': len(plan['operations']), 'records': records}
                if receipt:
                    manifest['receipt'] = {'binding': receipt['binding'], 'records': receipt['records'],
                                           'schedule': receipt['schedule'], 'state': receipt['state']}
            elif _company_receipts(inbox, company_id):
                # A receipt without a frozen plan is ambiguous remote work.
                raise ValueError('receipt_exists_without_frozen_plan')
            manifest['manifest_digest'] = _digest({key: value for key, value in manifest.items()
                                                    if key != 'manifest_digest'})
            report['qualified'].append(manifest)
        except Exception as exc:
            report['held'].append({'company_id': company_id, 'reason': str(exc) or type(exc).__name__})
    return report


def revalidate_terminal_manifest(state, inbox, manifest):
    """Compare a pause consumer's manifest to fresh qualification (CAS gate).

    A completed frozen plan is valid only while its durable confirmed receipt
    remains exactly bound to the frozen plan.
    """
    if not isinstance(manifest, dict) or manifest.get('version') != MANIFEST_VERSION:
        raise ValueError('terminal_manifest_invalid')
    report = qualify_terminal_holds(state, inbox, manifest.get('cycle_id'), [manifest.get('company_id')])
    if len(report['qualified']) != 1 or report['qualified'][0].get('manifest_digest') != manifest.get('manifest_digest'):
        raise ValueError('terminal_manifest_changed_before_pause')
    return report['qualified'][0]
