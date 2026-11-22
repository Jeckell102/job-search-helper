"""Read saved Embraer publication and receipt claims under the host owner's leases."""

from contextlib import closing
from pathlib import Path

from job_search_helper.engine import State
from job_search_helper.exact_cycle_receipt import (
    repair_retry_has_confirmed_publication, require_current_repair_retry,
)
from job_search_helper.inbox import InventoryInbox
from job_search_helper.integration_release import _read_json, assert_release_settled
from job_search_helper.release_controller import _require_qualified_retry, _retry_binding
from job_search_helper.repair_retry import canonical_retry_binding, release_binding_sha256
from job_search_helper.scan_request import superseded_cycle_ids
from job_search_helper.scrape_outcome_delivery import CONSUMER, OutcomeDelivery
from job_search_helper.scrape_outcome_producer import _successful_inventory
from job_search_helper.sqlite_repository import SQLiteRepository


COMPANY_ID = 'COMP-0634'


def read_embraer_retry_completion(enrollment, approval, *, root, jobs, destination, original_outcome):
    """Reopen the exact completed retry without opening a writable handle."""
    root = Path(root)
    journal = assert_release_settled(root)
    if not journal or journal['state'] != 'COMPLETE' or journal['release_id'] != approval.release_id:
        return None
    database = root / 'state.db'
    binding = canonical_retry_binding(_retry_binding(_read_json(Path(journal['record']) / 'receipt.json')))
    if (binding['company_id'] != COMPANY_ID or binding['failed_request_id'] != enrollment.request_id
            or binding['source_revision'] != enrollment.source_revision):
        return None
    with approval.open() as owner:
        _require_qualified_retry(database, binding, owner)

    attempt = binding['attempt_id']
    retry_request = 'company-retry:' + attempt
    release_digest = release_binding_sha256(binding['release'])
    with (closing(SQLiteRepository(jobs, destination, readonly=True)) as repository,
          closing(State(database, readonly=True)) as state,
          closing(InventoryInbox(root / 'inventories.sqlite3', destination, readonly=True)) as inbox):
        original_rows = repository._outcome_delivery_rows(CONSUMER, outcome_id=original_outcome)
        retries = repository.db.execute(
            'SELECT outcome_id FROM scrape_outcomes WHERE request_id=? LIMIT 2', (retry_request,),
        ).fetchall()
        if len(original_rows) != 1 or len(retries) != 1:
            return None
        origin = OutcomeDelivery(repository, None)._preflight(original_rows[0])
        if origin[2] or not origin[3] or not enrollment.qualified(origin[0]):
            return None
        rows = repository._outcome_delivery_rows(CONSUMER, outcome_id=retries[0][0])
        if len(rows) != 1:
            return None
        readback = OutcomeDelivery(repository, None)._preflight(rows[0])
        record, _, stale, _, _ = readback
        identity = record['identity']
        expected = {
            'company_id': COMPANY_ID, 'request_id': retry_request, 'attempt_id': attempt,
            'failed_request_id': enrollment.request_id, 'source_revision': enrollment.source_revision,
            'release_version': binding['release']['release_id'], 'release_binding_sha256': release_digest,
        }
        if stale or record['outcome'] != 'COMPLETE' or any(identity.get(key) != value for key, value in expected.items()):
            return None

        cycle_id = identity['cycle_id']
        cycle = state.cycle(cycle_id)
        cycles = state.cycles()
        if cycle is None or cycle_id in superseded_cycle_ids(cycles) or cycle.get('repair_retry') != binding:
            return None
        owners = [item for item in cycles if item.get('start_request_id') == retry_request
                  or item.get('request_fingerprint') == cycle.get('request_fingerprint')
                  or (isinstance(item.get('repair_retry'), dict) and item['repair_retry'].get('attempt_id') == attempt)]
        if owners != [cycle]:
            return None
        require_current_repair_retry(cycle, COMPANY_ID, repository, root)
        if (not _successful_inventory(cycle['companies'][COMPANY_ID])
                or not repair_retry_has_confirmed_publication(inbox, repository, cycle, COMPANY_ID)):
            return None
        return {
            'binding': binding, 'record': record, 'origin': origin,
            'origin_sender_row': original_rows[0], 'readback': readback, 'sender_row': rows[0],
            'release_binding_sha256': release_digest, 'approval_receipt_sha256': approval.receipt_sha256,
        }
