"""Checkpoint the exact immutable outcome after ordinary verified publication."""

import json

from . import ordinary_verification_pending as pending
from .ordinary_verification_outcome import existing_outcome
from .repository import RepositoryError


TERMINAL = 'ordinary_verification_terminal'


def _published_marker(stores, cycle_id, company_id):
    from .ordinary_verification_publication import read_publication_proof

    proof = read_publication_proof(stores, cycle_id, company_id)
    if proof is None:
        raise RepositoryError('Ordinary verification has no exact archived publication.')
    cycle, original = pending._read_cycle(stores.state, cycle_id)
    marker = pending.read_marker(cycle, company_id)
    if marker is None or pending.digest(marker) != proof['owner']['prepared_sha256']:
        raise RepositoryError('The published ordinary verification dispatch changed.')
    return cycle, original, marker, proof


def _terminal_record(stores, marker, proof):
    current = existing_outcome(stores.jobs, marker['owner'])
    if current is None:
        return None
    return {
        'schema': 'ordinary-verification-terminal-v1',
        'dispatch_sha256': marker['dispatch_sha256'],
        'publication_sha256': pending.digest(proof),
        'outcome_id': current['outcome_id'],
        'outcome_payload_sha256': current['payload_sha256'],
    }


def read_terminal_checkpoint(stores, cycle_id, company_id):
    """Verify both historical receipts before trusting the recorded terminal state."""
    cycle, original, marker, proof = _published_marker(stores, cycle_id, company_id)
    item = cycle['companies'][company_id]
    if TERMINAL not in item:
        return None
    expected = _terminal_record(stores, marker, proof)
    if expected is None or item[TERMINAL] != expected:
        raise RepositoryError('Ordinary verification terminal evidence changed or is missing.')
    refreshed, refreshed_raw = pending._read_cycle(stores.state, cycle_id)
    if refreshed_raw != original or refreshed['companies'][company_id][TERMINAL] != expected:
        raise RepositoryError('Ordinary verification terminal checkpoint changed during readback.')
    pending._check_stores(stores, marker['owner'])
    return expected


def checkpoint_existing_outcome(stores, cycle_id, company_id):
    """Reconcile a completed Jobs write into State without producing an outcome."""
    from .ordinary_verification_publication import _require_owned_leases

    _require_owned_leases(stores)
    state = stores.state
    if state.readonly or state.connection.in_transaction:
        raise RepositoryError('Ordinary verification requires an idle writable State checkpoint.')
    cycle, original, marker, proof = _published_marker(stores, cycle_id, company_id)
    expected = _terminal_record(stores, marker, proof)
    if expected is None:
        raise RepositoryError('The exact ordinary verification outcome is not durable.')
    item = cycle['companies'][company_id]
    if TERMINAL not in item:
        item[TERMINAL] = expected
        encoded = json.dumps(cycle, ensure_ascii=False, allow_nan=False)
        with state.connection:
            updated = state.connection.execute(
                'UPDATE main.cycles SET data=? WHERE id=? AND data=?',
                (encoded, cycle_id, original),
            )
            if updated.rowcount != 1:
                raise RepositoryError('The owning cycle changed before its terminal checkpoint.')
    if read_terminal_checkpoint(stores, cycle_id, company_id) != expected:
        raise RepositoryError('Ordinary verification terminal checkpoint did not read back exactly.')
    return expected
