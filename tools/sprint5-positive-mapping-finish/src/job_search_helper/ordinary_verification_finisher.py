"""Close an exact published ordinary attempt when its existing facts settle it."""

from contextvars import ContextVar
from dataclasses import dataclass
import json

from . import ordinary_verification_pending as pending
from .engine import Engine
from .ordinary_verification_outcome import existing_outcome
from .ordinary_verification_outcome_owner import (
    _binding, _read_reservation, require_reserved_outcome_owner,
)
from .ordinary_verification_publication import _require_owned_leases, _row as archived_publication, read_publication_proof
from .ordinary_verification_terminal import _published_marker, checkpoint_existing_outcome
from .repository import RepositoryError
from .scrape_outcome_producer import _sealed_mapping_evidence, normal_cycle_outcome_facts
from .sqlite_repository import _identity_key
from . import runtime_mapping_facts as mapping_facts


_ACTIVE_WRITE = ContextVar('active_published_ordinary_outcome', default=None)


@dataclass(frozen=True)
class _PreparedRepair:
    authority: object
    marker: dict
    publication: dict
    capture_manifest_sha256: str
    machine_evidence: dict
    verification_binding: dict
    fact_row: tuple


def permits_published_outcome_write(db, identity, facts, classification, reservation):
    """Recognize only the lexical write inside the exact published finisher."""
    permit = _ACTIVE_WRITE.get()
    if permit is None or not isinstance(reservation, dict):
        return False
    stores, owner, expected, state_bytes, publication, facts_sha, repair = permit
    if (db is not stores.jobs.db or not db.in_transaction or reservation != expected
            or any(owner[key] != identity.get(key) for key in ('cycle_id', 'request_id', 'company_id', 'source_revision'))
            or not isinstance(facts, dict) or pending.digest(facts) != facts_sha
            or not isinstance(classification, dict)):
        return False
    qualified = classification.get('outcome') == 'QUALIFIED_INTEGRATION_REPAIR'
    category = classification.get('repair_category')
    if ((repair is None and (qualified or category is not None))
            or (repair is not None and (not qualified or category != 'same_provider_source_mapping'))):
        return False
    _require_owned_leases(stores)
    cycle_id, company_id = owner['cycle_id'], owner['company_id']
    live_cycle, live_state = pending._read_cycle(stores.state, cycle_id)
    if (live_state != state_bytes
            or archived_publication(stores.inbox.connection, cycle_id, company_id) != publication):
        return False
    if repair is None:
        return True
    company = _current_company(stores.jobs, company_id)
    pending._check_company(stores, live_cycle, owner)
    sealed = _sealed_mapping_evidence(stores.jobs, live_cycle, company, live_cycle['companies'][company_id])
    return (mapping_facts._row(stores.state.connection, cycle_id, company_id) == repair.fact_row
            and sealed is not None and all(facts.get(key) == value for key, value in sealed.items())
            and repair.authority.require(repair.marker, repair.publication, repair.capture_manifest_sha256)
            == (repair.machine_evidence, repair.verification_binding))


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


def _prepare_live_repair(stores, runtime, cycle, original, company, marker, proof, authority, capture):
    """Commit the qualified fact and its checked seal as one State transaction."""
    from .ordinary_live_mapping_verdict import _LiveVerdictOwner
    from .ordinary_verification_publisher import read_captured_ordinary_response

    if type(authority) is not _LiveVerdictOwner or capture is None:
        raise RepositoryError('The positive mapping route requires the configured live verdict and raw capture owners.')
    owner = marker['owner']
    cycle_id, company_id = owner['cycle_id'], owner['company_id']
    item = cycle['companies'][company_id]
    if (proof['final_stage'] != 'partial' or marker['observation'] is None or marker['failure'] is not None
            or item.get('stage') != 'partial' or item.get('inventory_status') != 'partial'
            or item.get('zero_openings_verified') is True or not item.get('fetched_at')):
        raise RepositoryError('The saved inventory is unavailable for a qualified mapping result.')
    pending._check_company(stores, cycle, owner)
    captured = read_captured_ordinary_response(stores, cycle_id, company_id, capture)
    if captured.dispatch_sha256 != marker['dispatch_sha256']:
        raise RepositoryError('The raw response belongs to a different dispatch.')
    evidence, verification = authority.require(marker, proof, captured.manifest_sha256)
    fact = {
        'schema': 'rippling-mapping-divergence-fact-v1', 'cycle_id': cycle_id, 'company_id': company_id,
        'source_revision': owner['source_revision'], 'evidence_code': 'rippling_verified_mapping_divergence',
        **{key: marker['admission'][key] for key in (
            'capability_id', 'capability_digest', 'mapping_digest', 'configuration_digest',
        )},
        **evidence,
    }
    checkpoint = Engine(stores.jobs, stores.state, runtime_binding=runtime)._source_configuration_defect_checkpoint(
        cycle, item, fact, company=company,
    )
    seal = None if checkpoint == cycle else (original, checkpoint)
    _require_owned_leases(stores)
    if (pending._read_cycle(stores.state, cycle_id)[1] != original
            or read_publication_proof(stores, cycle_id, company_id) != proof
            or authority.require(marker, proof, captured.manifest_sha256) != (evidence, verification)):
        raise RepositoryError('The exact qualified mapping inputs changed before the State write.')
    _current_company(stores.jobs, company_id)
    pending._check_company(stores, cycle, owner)
    fact_id = mapping_facts._persist_runtime_mapping_fact(
        stores.state, stores.jobs, runtime, cycle_id=cycle_id, company_id=company_id,
        fact=fact, verification=verification, seal=seal,
    )
    readback = mapping_facts._read_owned_runtime_fact(
        stores.state, stores.jobs, runtime, cycle_id=cycle_id, company_id=company_id, verification=verification,
    )
    fact_row = mapping_facts._row(stores.state.connection, cycle_id, company_id)
    if (readback != {'fact_id': fact_id, 'fact': fact} or fact_row is None
            or stores.state.cycle(cycle_id) != checkpoint):
        raise RepositoryError('The exact qualified mapping fact and seal did not read back.')
    return _PreparedRepair(authority, marker, proof, captured.manifest_sha256, evidence, verification, fact_row)


def finish_published_ordinary(stores, runtime, cycle_id, company_id, *, qualified_owner=None, capture=None):
    """Finish a published no-repair disposition with the exact private Jobs writer.

    A typed mismatch stays pending unless the configured live authority owns
    its exact verdict. A prior immutable Jobs outcome always wins.
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
    repair = None
    if (qualified_owner is not None and marker['observation'] is not None
            and existing_outcome(jobs, owner) is None):
        company = _current_company(jobs, company_id)
        item = cycle['companies'][company_id]
        initial = normal_cycle_outcome_facts(cycle, company, item, storage_confirmed=True)
        if initial['source_current'] is True:
            repair = _prepare_live_repair(stores, runtime, cycle, original, company, marker, proof,
                                          qualified_owner, capture)
            cycle, original, next_marker, next_proof = _published_marker(stores, cycle_id, company_id)
            if next_marker != marker or next_proof != proof:
                raise RepositoryError('The qualified outcome publication changed after the State seal.')
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
                if repair is None:
                    return {'state': 'VERIFICATION_PENDING'}
                pending._check_company(stores, cycle, owner)
                sealed = _sealed_mapping_evidence(jobs, cycle, company, item)
                if sealed is None:
                    raise RepositoryError('The qualified mapping seal is no longer current.')
                facts.update(sealed)
            else:
                repair = None
            token = _ACTIVE_WRITE.set((stores, owner, reservation, original, archived_before,
                                       pending.digest(facts), repair))
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
