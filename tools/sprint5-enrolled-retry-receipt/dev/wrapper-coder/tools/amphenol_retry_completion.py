"""Deliver only the enrolled Amphenol release retry's verified completion."""

from contextlib import closing, contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import sqlite3

from coordinator_receipt_host_bridge import ManualReceiptV1HostBridge
from coordinator_store import Store
from job_search_helper.engine import State
from job_search_helper.exact_cycle_receipt import (
    repair_retry_has_confirmed_publication, require_current_repair_retry,
)
from job_search_helper.inbox import InventoryInbox
from job_search_helper.integration_release import _read_json, assert_release_settled
from job_search_helper.release_controller import _require_qualified_retry, _retry_binding
from job_search_helper.release_qualification import open_release_qualification_owner
from job_search_helper.repair_retry import canonical_retry_binding, release_binding_sha256
from job_search_helper.scan_request import superseded_cycle_ids
from job_search_helper.scrape_outcome_delivery import CONSUMER, OutcomeDelivery
from job_search_helper.scrape_outcome_producer import _successful_inventory
from job_search_helper.sqlite_repository import SQLiteRepository


_HELD = 'HELD_EXACT_RETRY_TERMINAL'


@dataclass(frozen=True)
class RetryReleaseApproval:
    release_id: str
    directory: str
    device: int
    inode: int
    receipt_sha256: str

    @classmethod
    def from_json(cls, raw):
        if not isinstance(raw, str) or len(raw) > 4096:
            raise ValueError('Invalid exact Amphenol retry approval.')
        pairs = json.loads(raw, object_pairs_hook=tuple)
        value = dict(pairs) if isinstance(pairs, tuple) and len(pairs) == 5 else {}
        if (set(value) != {'release_id', 'directory', 'device', 'inode', 'receipt_sha256'}
                or not all(isinstance(value[key], str) for key in ('release_id', 'directory', 'receipt_sha256'))
                or not re.fullmatch(r'REL-[0-9a-f]{24}', value['release_id'])
                or not re.fullmatch(r'[0-9a-f]{64}', value['receipt_sha256'])
                or not Path(value['directory']).is_absolute() or '..' in Path(value['directory']).parts
                or Path(value['directory']) == Path('/')
                or any(type(value[key]) is not int or value[key] <= 0 for key in ('device', 'inode'))):
            raise ValueError('Invalid exact Amphenol retry approval.')
        return cls(**value)

    @contextmanager
    def open(self):
        descriptor = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            with open_release_qualification_owner(
                self.directory, descriptor, expected_owner_identity=(self.device, self.inode),
                approved_receipt_sha256=self.receipt_sha256,
            ) as owner:
                yield owner
        finally:
            os.close(descriptor)


def _delivery_pair(store, readback, sender_row):
    record, digest, stale, acknowledged, _ = readback
    if stale or not acknowledged:
        return None
    receiver = Path(store.path).resolve().as_uri() + '?mode=ro'
    with closing(sqlite3.connect(receiver, uri=True)) as db:
        db.execute('BEGIN')
        receipt_row = db.execute(
            'SELECT record_sha256,receipt_id,receipt,receipt_sha256,sink_status '
            'FROM scrape_outcome_delivery_receipts WHERE consumer=? AND outcome_id=?',
            (CONSUMER, record['outcome_id']),
        ).fetchone()
        intake_row = db.execute(
            'SELECT company_id,source_revision,outcome,payload FROM scrape_outcome_intake WHERE outcome_id=?',
            (record['outcome_id'],),
        ).fetchone()
        if receipt_row is None or intake_row is None:
            return None
        Store._validate_delivery_intake(
            intake_row, canonical=record, record_sha256=digest,
            legacy_text=json.dumps(record, sort_keys=True, separators=(',', ':')),
        )
        receipt = Store._validate_delivery_receipt(
            receipt_row, consumer=CONSUMER, canonical=record, record_sha256=digest,
        )
    return receipt if receipt == json.loads(sender_row[6]) else None


def _same_completion(lifecycle, record, expected):
    if lifecycle is None or lifecycle['state'] != 'VALIDATED_COMPLETE':
        return False
    outcome_id = record['outcome_id']
    return (all(lifecycle[key] == expected[key] for key in (
                'attempt_id', 'failed_request_id', 'release_version', 'release_binding_sha256',
            ))
            and lifecycle['first_outcome_id'] == lifecycle['latest_outcome_id'] == outcome_id
            and len(lifecycle['events']) == 1
            and lifecycle['events'][0]['record'] == record)


def deliver_qualified_retry(enrollment, coordinator, root, jobs, destination, *, original_outcome):
    """Read and deliver one already-published retry under the host owner's leases."""
    approval = enrollment.retry_approval
    journal = assert_release_settled(root)
    if not journal or journal['state'] != 'COMPLETE' or journal['release_id'] != approval.release_id:
        return {'state': _HELD}
    database = root / 'state.db'
    binding = canonical_retry_binding(_retry_binding(_read_json(Path(journal['record']) / 'receipt.json')))
    if (binding['failed_request_id'] != enrollment.request_id
            or binding['source_revision'] != enrollment.source_revision or binding['company_id'] != 'COMP-0490'):
        return {'state': _HELD}
    with approval.open() as owner:
        _require_qualified_retry(database, binding, owner)

    company_id = binding['company_id']
    attempt_id = binding['attempt_id']
    expected = {
        'request_id': 'company-retry:' + attempt_id, 'attempt_id': attempt_id, 'company_id': company_id,
        'failed_request_id': binding['failed_request_id'], 'source_revision': binding['source_revision'],
        'release_version': binding['release']['release_id'],
        'release_binding_sha256': release_binding_sha256(binding['release']),
    }
    with (closing(SQLiteRepository(jobs, destination, readonly=True)) as repository,
          closing(State(database, readonly=True)) as state,
          closing(InventoryInbox(root / 'inventories.sqlite3', destination, readonly=True)) as inbox):
        [row] = repository._outcome_delivery_rows(CONSUMER, outcome_id=original_outcome)
        origin = OutcomeDelivery(repository, None)._preflight(row)
        if not enrollment.qualified(origin[0]) or _delivery_pair(coordinator.store, origin, row) is None:
            return {'state': _HELD}
        outcomes = repository.db.execute(
            'SELECT outcome_id FROM scrape_outcomes WHERE request_id=? LIMIT 2', (expected['request_id'],),
        ).fetchall()
        if len(outcomes) != 1:
            return {'state': _HELD}
        [outcome_id] = outcomes[0]
        [row] = repository._outcome_delivery_rows(CONSUMER, outcome_id=outcome_id)
        readback = OutcomeDelivery(repository, None)._preflight(row)
        record, _, stale, acknowledged, _ = readback
        identity = record['identity']
        if (stale or record['outcome'] != 'COMPLETE'
                or any(identity.get(key) != value for key, value in expected.items())):
            return {'state': _HELD}
        cycle_id = identity['cycle_id']
        cycle = state.cycle(cycle_id)
        cycles = state.cycles()
        if (cycle is None or cycle_id in superseded_cycle_ids(cycles)
                or cycle.get('repair_retry') != binding):
            return {'state': _HELD}
        owners = [
            item for item in cycles
            if (item.get('start_request_id') == expected['request_id']
                or item.get('request_fingerprint') == cycle.get('request_fingerprint')
                or isinstance(item.get('repair_retry'), dict)
                and item['repair_retry'].get('attempt_id') == attempt_id)
        ]
        if owners != [cycle]:
            return {'state': _HELD}
        require_current_repair_retry(cycle, company_id, repository, root)
        if (not _successful_inventory(cycle['companies'][company_id])
                or not repair_retry_has_confirmed_publication(inbox, repository, cycle, company_id)):
            return {'state': _HELD}

    lifecycle = coordinator.store.retry_lifecycle(attempt_id)
    if lifecycle is not None and not _same_completion(lifecycle, record, expected):
        return {'state': _HELD}
    if not acknowledged:
        with closing(SQLiteRepository(jobs, destination)) as repository:
            bridge = ManualReceiptV1HostBridge(coordinator, lambda: repository, enabled=True)
            bridge.manual_drain(outcome_id=outcome_id)
            [row] = repository._outcome_delivery_rows(CONSUMER, outcome_id=outcome_id)
            readback = OutcomeDelivery(repository, None)._preflight(row)
    paired = _delivery_pair(coordinator.store, readback, row)
    if (paired is None or paired['sink_status'] != 'VALIDATED_COMPLETE'
            or not _same_completion(coordinator.store.retry_lifecycle(attempt_id), record, expected)):
        return {'state': _HELD}
    return {'state': 'RECIPE_RETRY_CONFIRMED', 'attempt_id': attempt_id, 'outcome_id': outcome_id}
