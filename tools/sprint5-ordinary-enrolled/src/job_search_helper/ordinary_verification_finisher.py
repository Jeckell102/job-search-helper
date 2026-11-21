"""Close an exact published ordinary attempt when its existing facts settle it."""

from contextvars import ContextVar
import json

from . import ordinary_verification_pending as pending
from .engine import Engine
from .ordinary_verification_outcome import existing_outcome
from .ordinary_verification_outcome_owner import (
    _binding, _read_reservation, require_reserved_outcome_owner,
)
from .ordinary_verification_publication import _require_owned_leases, _row as archived_publication
from .ordinary_verification_terminal import _published_marker, checkpoint_existing_outcome
from .repository import RepositoryError
from .scrape_outcome_producer import normal_cycle_outcome_facts
from .sqlite_repository import _identity_key


_ACTIVE_WRITE = ContextVar('active_published_ordinary_outcome', default=None)


def permits_published_outcome_write(db, identity, facts, classification, reservation):
    """Recognize only the lexical write inside the exact published finisher."""
    permit = _ACTIVE_WRITE.get()
    if permit is None or not isinstance(reservation, dict):
        return False
    stores, owner, expected, state_bytes, publication, facts_sha = permit
    if (db is not stores.jobs.db or not db.in_transaction or reservation != expected
            or any(owner[key] != identity.get(key) for key in ('cycle_id', 'request_id', 'company_id', 'source_revision'))
            or not isinstance(facts, dict) or pending.digest(facts) != facts_sha
            or not isinstance(classification, dict) or classification.get('repair_category') is not None
            or classification.get('outcome') == 'QUALIFIED_INTEGRATION_REPAIR'):
        return False
    _require_owned_leases(stores)
    cycle_id, company_id = owner['cycle_id'], owner['company_id']
    return (pending._read_cycle(stores.state, cycle_id)[1] == state_bytes
            and archived_publication(stores.inbox.connection, cycle_id, company_id) == publication)


def _current_company(repository, company_id):
    rows = repository.db.execute(
        "SELECT records.data FROM main.lookups AS lookups "
        "JOIN main.records AS records ON records.tab=lookups.tab AND records.row_id=lookups.row_id "
        "WHERE lookups.tab='Companies' AND lookups.header='Company ID' AND lookups.value=?",
        (_identity_key('Company ID', company_id),),
    ).fetchall()
    if len(rows) != 1:
        raise RepositoryError('The ordinary outcome has no unique current Company.')
    row = json.loads(rows[0][0])
    if (row.get('Company ID') != company_id or row.get('Claimed By') or row.get('Claim Token')
            or (row.get('Scan State') == 'Blocked / Manual Review'
                and str(row.get('Automatic Retry?', '')).casefold() == 'no')):
        raise RepositoryError('The ordinary outcome Company is held or changed.')
    return row


def finish_published_ordinary(stores, runtime, cycle_id, company_id):
    """Finish a published no-repair disposition with the exact private Jobs writer.

    A current incomplete typed mismatch remains reserved for the independently
    verified repair path. No verifier receipt or outcome facts are accepted here.
    """
    _require_owned_leases(stores)
    cycle, original, marker, proof = _published_marker(stores, cycle_id, company_id)
    Engine.validate_cycle_runtime_binding(cycle, runtime, sync_only=True)
    owner = marker['owner']
    reservation = require_reserved_outcome_owner(stores, owner, marker['dispatch_sha256'])
    archived_before = archived_publication(stores.inbox.connection, cycle_id, company_id)
    if archived_before is None or archived_before[3] != pending.digest(proof):
        raise RepositoryError('The archived ordinary publication proof changed.')

    jobs = stores.jobs
    with jobs.transaction():
        _require_owned_leases(stores)
        _, live_state = pending._read_cycle(stores.state, cycle_id)
        if (live_state != original
                or archived_publication(stores.inbox.connection, cycle_id, company_id) != archived_before
                or _binding(stores, tuple(owner[key] for key in ('cycle_id', 'request_id', 'company_id', 'source_revision')),
                            marker['dispatch_sha256']) != reservation
                or _read_reservation(jobs.db, cycle_id, company_id) != reservation):
            raise RepositoryError('The verified ordinary outcome authority changed.')
        prior = existing_outcome(jobs, owner)
        if prior is None:
            company = _current_company(jobs, company_id)
            item = dict(cycle['companies'][company_id])
            # Use the archived stage rather than a later editable status.
            item['inventory_status'] = proof['final_stage']
            item.pop('zero_openings_verified', None)
            item.pop('outcome_failure', None)
            if marker['failure'] is not None:
                item['outcome_failure'] = marker['failure']
            facts = normal_cycle_outcome_facts(cycle, company, item, storage_confirmed=True)
            if facts['source_current'] is True and marker['observation'] is not None:
                return {'state': 'VERIFICATION_PENDING'}
            token = _ACTIVE_WRITE.set((stores, owner, reservation, original, archived_before, pending.digest(facts)))
            try:
                result = jobs._record_scrape_outcome_in_transaction(facts)
            finally:
                _ACTIVE_WRITE.reset(token)
            outcome_id = result['outcome_id']
        else:
            outcome_id = prior['outcome_id']

    finished = checkpoint_existing_outcome(stores, cycle_id, company_id)
    if finished['outcome_id'] != outcome_id:
        raise RepositoryError('The ordinary outcome changed before terminal checkpointing.')
    return {'state': 'ALREADY_STORED' if prior is not None else 'OUTCOME_STORED',
            'terminal': finished}
