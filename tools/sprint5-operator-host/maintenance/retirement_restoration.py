"""Exact installed-retirement restoration; no pilot or rollback is implied."""
from hashlib import sha256
import json
from pathlib import Path
import re

from host_exchange import Hold, encode, require


SCHEMA = 's5-owner-retirement-restoration-v1'
MANIFEST_SCHEMA = 'sprint-6-operator-selected-source-manifest-v1'
MANIFEST_SHA256 = '8c73be2432fdc49485f426f5be77d6588ea1e13f7b659595f6a4dad16710c57e'
MAINTENANCE_ID = 's5-operator-trigger-20261121-03'
PROJECT = '/home/chris/job-search-helper_old'
CYCLE_ID = 'CYC-B639C6D864EC'
HEX = re.compile('[0-9a-f]{64}')


def exchange_identity(witness):
    return {'generation': witness.generation, 'intent_sha256': witness.intent_sha256,
            'policy_sha256': witness.policy_sha256, 'mount_namespace': witness.mount_namespace,
            'control': str(witness.control),
            'routes': [[str(pair.canonical), str(pair.parked)] for pair in witness.pairs]}


def _terminal(controller, release):
    require(controller.manifest.schema == MANIFEST_SCHEMA
            and controller.manifest.sha256 == MANIFEST_SHA256
            and len(controller.manifest.paths) == 9
            and release.get('source') == 'INSTALLED'
            and release.get('maintenance_id') == MAINTENANCE_ID
            and release.get('project') == PROJECT
            and release.get('source_manifest_sha256') == MANIFEST_SHA256,
            'Exact installed retirement release is required')


def _proof(read_retirement, read_protected):
    retired, protected = read_retirement(), read_protected()
    require(isinstance(retired, dict) and set(retired) == {
        'cycle_id', 'state', 'published', 'archive_root', 'archive_scope_sha256',
        'retirement_record_sha256'} and retired['cycle_id'] == CYCLE_ID
        and retired['state'] == 'RETIRED_UNPUBLISHED' and retired['published'] is False
        and isinstance(retired['archive_root'], str) and Path(retired['archive_root']).is_absolute()
        and all(isinstance(retired[key], str) and HEX.fullmatch(retired[key])
                for key in ('archive_scope_sha256', 'retirement_record_sha256')),
        'Verified exact unpublished retirement proof is required')
    require(isinstance(protected, dict) and set(protected) == {'protected_pin_sha256', 'witness_sha256'}
            and all(isinstance(value, str) and HEX.fullmatch(value) for value in protected.values()),
            'Unchanged protected-state proof is required')
    return {'retirement': retired, 'protected': protected}


def read_verified_retirement(state, selection):
    """Read exact native State/archive proof; caller holds normal release leases."""
    from job_search_helper.retained_cycle_retirement_control import verified_retired_cycle_ids, _read
    from job_search_helper.retained_cycle_retirement import _digest
    require(isinstance(selection, dict) and set(selection) == {
        'cycle_id', 'archive_root', 'archive_scope_sha256', 'retirement_record_sha256'}
        and selection['cycle_id'] == CYCLE_ID and getattr(state, 'readonly', False) is True
        and Path(state.path).resolve(strict=True) == Path(PROJECT) / '.state/state.db',
        'Exact read-only retirement selection is required')
    require(verified_retired_cycle_ids(state) == {CYCLE_ID}, 'Exact verified retired cycle is unavailable')
    record = _read(state.connection, CYCLE_ID)
    require(record is not None and record.get('retired') is True
            and record.get('state') == 'RETIRED_UNPUBLISHED' and record.get('published') is False
            and record.get('archive_root') == selection['archive_root']
            and record.get('archive_scope_sha256') == selection['archive_scope_sha256']
            and _digest(record) == selection['retirement_record_sha256'],
            'Retirement record differs from its approved exact archive')
    return {**selection, 'state': record['state'], 'published': False}


def observe_after_retirement(controller, exchange, *, read_verified_retirement, read_protected_state):
    with controller.restoration_terminal() as release:
        _terminal(controller, release)
        closed = exchange.witness('closed')
        proof = _proof(read_verified_retirement, read_protected_state)
        require(exchange.witness('closed') == closed, 'Exchange changed during retirement observation')
        return {'schema': SCHEMA, 'release': release, 'exchange': exchange_identity(closed), **proof}


def restore_after_retirement(controller, exchange, approval, *, approved_sha256,
                             read_verified_retirement, read_protected_state):
    require(type(approval) is bytes and sha256(approval).hexdigest() == approved_sha256,
            'Retirement restoration approval differs from its trusted pin')
    try:
        plan = json.loads(approval)
    except (ValueError, UnicodeError) as error:
        raise Hold('Retirement restoration approval is unreadable') from error
    require(isinstance(plan, dict) and set(plan) == {'schema', 'release', 'exchange', 'retirement', 'protected'}
            and plan['schema'] == SCHEMA and approval == encode(plan)
            and all(isinstance(plan[key], dict) and plan[key]
                    for key in ('release', 'exchange', 'retirement', 'protected')),
            'Retirement restoration approval is incomplete or not canonical')
    with controller.restoration_terminal() as release:
        _terminal(controller, release)
        require(release == plan['release'], 'Retirement restoration release changed')
        def verified(witness, evidence):
            return (witness.phase == 'closed' and witness.terminal_proof_sha256 is None
                    and exchange_identity(witness) == plan['exchange'] and evidence == approval
                    and _proof(read_verified_retirement, read_protected_state)
                    == {key: plan[key] for key in ('retirement', 'protected')})
        return exchange.restore(approval, verify_terminal=verified)
