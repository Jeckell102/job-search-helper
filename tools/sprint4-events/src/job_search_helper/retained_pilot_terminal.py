"""Read-only application evidence for a selected signed retained pilot."""

from hashlib import sha256
import json
import re
import sqlite3

from .outcomes import COMPLETE, classify_outcome
from .repository import RepositoryError
from .retained_event_outcome import retained_event_outcome_facts, retained_outcome_source_is_current
from .retained_operator_journal import SETTLED, RetainedOperatorJournal, _expected_consumption
from .retained_session_store import SYNC_CONFIRMED
from .retained_work_orchestrator import _cycle_id
from .scrape_outcome_delivery import CONSUMER, OutcomeDelivery
from .sheet_profile import COMPACT_PROFILE
from .sqlite_repository import SQLiteRepository


class RetainedPilotHold(ValueError):
    """The selected application evidence is missing, pending, or inconsistent."""


def verify_retained_pilot_terminal(
    local, *, request_sha256, reservation_digest, company_event_id, company_id,
    source_revision, blocking_cycle_id, runtime_binding,
):
    """Return the exact application evidence for receiver comparison.

    The caller supplies the canonical read-only Jobs repository, selected
    identity and independently verified runtime while holding the existing
    scraper and writer leases. No locks, stores or receipts are created here.
    """
    if not isinstance(local, SQLiteRepository) or not local.readonly or local.path.name != 'jobs.sqlite3':
        raise RetainedPilotHold('Selected retained pilot requires the canonical read-only Jobs store.')
    try:
        return _verify(
            local, request_sha256=request_sha256, reservation_digest=reservation_digest,
            company_event_id=company_event_id, company_id=company_id, source_revision=source_revision,
            blocking_cycle_id=blocking_cycle_id, runtime_binding=runtime_binding,
        )
    except RetainedPilotHold:
        raise
    except (ValueError, RepositoryError, OSError, sqlite3.Error, LookupError, TypeError, AttributeError) as exc:
        raise RetainedPilotHold('Selected retained pilot evidence is unreadable or inconsistent.') from exc


def _verify(
    local, *, request_sha256, reservation_digest, company_event_id, company_id,
    source_revision, blocking_cycle_id, runtime_binding,
):
    root = local.path.parent
    if local.get_meta('sheets_profile') != COMPACT_PROFILE or local.get_meta('ready') != 'yes':
        raise RetainedPilotHold('Selected retained pilot requires a ready compact Jobs store.')
    journal = RetainedOperatorJournal(root)
    queue = root / 'next-scan.json'
    if journal.inspect() is not None or queue.is_symlink() or queue.exists():
        raise RetainedPilotHold('Selected retained pilot has pending request or operator journal work.')
    archived = journal.read_archived_event(request_sha256, reservation_digest)
    if archived is None or archived['state'] != SETTLED:
        raise RetainedPilotHold('Selected retained pilot has no archived settlement.')
    binding = archived['binding']
    claims = binding['claims']
    request_id = 'company-event:' + company_event_id
    if (binding['runtime'] != runtime_binding
            or (claims['request_id'], claims['company_id'], claims['source_revision'], claims['cycle_id'])
            != (request_id, company_id, source_revision, blocking_cycle_id)):
        raise RetainedPilotHold('Selected retained pilot identity or runtime differs from its admission.')
    publication = archived['settlement_evidence']
    if (publication['state'] != SYNC_CONFIRMED
            or archived['consumption'] != _expected_consumption(binding, publication)):
        raise RetainedPilotHold('Selected retained pilot has no consumed confirmed publication.')
    sessions = root / 'retained-sessions.sqlite3'
    if sessions.is_symlink() or not sessions.is_file():
        raise RetainedPilotHold('Selected retained pilot requires the canonical retained session store.')

    facts, outcome = retained_event_outcome_facts(local, request_sha256, reservation_digest)
    expected_identity = {
        'company_event_id': company_event_id, 'request_id': request_id, 'company_id': company_id,
        'source_revision': source_revision, 'cycle_id': _cycle_id(reservation_digest),
        'retained_reservation_sha256': reservation_digest,
    }
    if (outcome is None or facts['source_current'] is not True or facts['inventory_status'] != 'complete'
            or facts['storage_status'] != 'confirmed' or outcome['outcome'] != COMPLETE
            or outcome['action'] != 'save_without_repair' or outcome != classify_outcome(facts)
            or any(outcome['identity'].get(key) != value for key, value in expected_identity.items())
            or not retained_outcome_source_is_current(local, outcome['identity'])):
        raise RetainedPilotHold('Selected retained pilot has no current complete canonical outcome.')

    outcome_id = outcome['outcome_id']
    rows = local._outcome_delivery_rows(CONSUMER, outcome_id=outcome_id)
    if len(rows) != 1:
        raise RetainedPilotHold('Selected retained pilot lacks one exact sender delivery record.')
    row = rows[0]
    delivered, record_sha256, stale, terminal, _attempt = OutcomeDelivery(local, None)._preflight(row)
    if delivered != outcome or stale or not terminal:
        raise RetainedPilotHold('Selected retained pilot outcome sender delivery is pending or inconsistent.')
    receipt = json.loads(row[6])
    if (receipt['disposition'] != 'ACCEPTED' or receipt['sink_status'] != 'RECORDED_NO_REPAIR'
            or re.fullmatch(r'ODR-[0-9a-f]{24}', receipt['sink_receipt_id']) is None):
        raise RetainedPilotHold('Selected retained pilot sender receipt lacks clean coordinator intake.')

    return {
        'schema': 'selected-retained-pilot-terminal-v1',
        'consumer': CONSUMER,
        'record': outcome,
        'identity': outcome['identity'],
        'outcome_id': outcome_id,
        'record_sha256': record_sha256,
        'sender_receipt_sha256': row[7],
        'sink_receipt_id': receipt['sink_receipt_id'],
        'sink_status': receipt['sink_status'],
        'blocking_cycle_id': blocking_cycle_id,
        'request_sha256': request_sha256,
        'workbook_id_sha256': sha256(local.spreadsheet_id.encode('utf-8')).hexdigest(),
        'operator_record_sha256': archived['record_sha256'],
        'settlement_evidence_sha256': archived['settlement_evidence_sha256'],
        'publication': publication,
    }
