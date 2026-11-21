"""Read one genuine published pilot outcome for separate delivery authorization."""

from hashlib import sha256

from job_search_helper.outcomes import COMPLETE, classify_outcome
from job_search_helper.retained_event_outcome import retained_event_outcome_facts
from job_search_helper.retained_operator_journal import SETTLED, RetainedOperatorJournal, _expected_consumption
from job_search_helper.retained_session_store import SYNC_CONFIRMED
from job_search_helper.retained_work_orchestrator import _cycle_id
from job_search_helper.scrape_outcome_delivery import CONSUMER, OutcomeDelivery
from job_search_helper.sheet_profile import COMPACT_PROFILE
from job_search_helper.sqlite_repository import SQLiteRepository


def read_pilot_outcome(local, *, request_sha256, reservation_digest, company_event_id, company_id,
                       source_revision, blocking_cycle_id, runtime_binding):
    """Require held application leases and return the digest-pinned sender row."""
    if (not isinstance(local, SQLiteRepository) or not local.readonly or local.path.name != 'jobs.sqlite3'
            or local.get_meta('sheets_profile') != COMPACT_PROFILE or local.get_meta('ready') != 'yes'):
        raise ValueError('Expected the approved read-only compact Jobs authority.')
    root = local.path.parent
    journal = RetainedOperatorJournal(root)
    queue = root / 'next-scan.json'
    if journal.inspect() is not None or queue.is_symlink() or queue.exists():
        raise ValueError('Selected pilot request ownership is still pending.')
    archived = journal.read_archived_event(request_sha256, reservation_digest)
    if archived is None or archived['state'] != SETTLED:
        raise ValueError('No exact consumed pilot settlement exists.')
    binding = archived['binding']
    claims = binding['claims']
    request_id = 'company-event:' + company_event_id
    if (binding['runtime'] != runtime_binding
            or (claims['request_id'], claims['company_id'], claims['source_revision'], claims['cycle_id'])
            != (request_id, company_id, source_revision, blocking_cycle_id)):
        raise ValueError('The consumed pilot scope differs from its approved owner.')
    publication = archived['settlement_evidence']
    if (publication['state'] != SYNC_CONFIRMED
            or archived['consumption'] != _expected_consumption(binding, publication)):
        raise ValueError('Expected the consumed confirmed publication of this pilot.')

    facts, outcome = retained_event_outcome_facts(local, request_sha256, reservation_digest)
    expected = {'company_event_id': company_event_id, 'request_id': request_id, 'company_id': company_id,
                'source_revision': source_revision, 'cycle_id': _cycle_id(reservation_digest),
                'retained_reservation_sha256': reservation_digest}
    if (outcome is None or facts['source_current'] is not True or facts['inventory_status'] != 'complete'
            or facts['storage_status'] != 'confirmed' or outcome['outcome'] != COMPLETE
            or outcome['action'] != 'save_without_repair' or outcome != classify_outcome(facts)
            or any(outcome['identity'].get(name) != value for name, value in expected.items())):
        raise ValueError('Expected the current exact successful outcome from the selected publication.')

    rows = local._outcome_delivery_rows(CONSUMER, outcome_id=outcome['outcome_id'])
    if len(rows) != 1:
        raise ValueError('Expected one exact outcome in the selected sender ledger.')
    saved, record_sha, stale, terminal, attempt = OutcomeDelivery(local, None)._preflight(rows[0])
    if saved != outcome or stale:
        raise ValueError('The selected immutable sender evidence changed or is stale.')
    sender_state = 'ATTEMPT_PRESENT' if attempt[0] is not None else 'READY'
    if terminal:
        sender_state = 'ALREADY_TERMINAL'
    return {'schema': 'selected-retained-pilot-delivery-candidate-v1', 'consumer': CONSUMER,
            'outcome_id': outcome['outcome_id'], 'record_sha256': record_sha, 'request_sha256': request_sha256,
            'source_revision': source_revision, 'reservation_digest': reservation_digest,
            'settlement_evidence_sha256': archived['settlement_evidence_sha256'],
            'workbook_id_sha256': sha256(local.spreadsheet_id.encode()).hexdigest(),
            'sender_state': sender_state}
