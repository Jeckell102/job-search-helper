"""Read the selected owner evidence and project the closed Amphenol choice prompt."""
from contextlib import closing, nullcontext
import json
import re
from pathlib import Path
import sqlite3
from types import SimpleNamespace

from coding_tools import spec
from coordinator_store import Store
from coordinator_identity import canonical_identity, validate_bound_identity
from job_search_helper.acquiretm import SOURCE
from job_search_helper.ats import ACQUIRETM_PAGINATION_CODE
from job_search_helper.company_events import current_company_repair_snapshot
from job_search_helper.engine import State
from job_search_helper.inbox import InventoryInbox
from job_search_helper.ordinary_company_event_fetch import load_ordinary_event_observation
from job_search_helper.ordinary_event_settlement import (
    _read_settlement, ordinary_event_outcome_settled, ordinary_no_publication_result,
)
from job_search_helper.scrape_outcome_delivery import CONSUMER, OutcomeDelivery, _OUTCOME_ID, _valid_receipt
from job_search_helper.sqlite_repository import SQLiteRepository
from job_search_helper.temporary_retry import _selected_sha


COMPANY_ID = 'COMP-0490'
COMPANY = 'Amphenol Aerospace'
HELD = 'HELD_FOR_REPAIR_TRIAGE'
IDENTITY = ('cycle_id', 'request_id', 'company_event_id', 'source_revision')


def _verified_readbacks(root, store, outcome_id, *, expected_task_id=None):
    root = Path(root)
    destination = InventoryInbox.destination_id(root / 'inventories.sqlite3')
    with (closing(State(str(root / 'state.db'), readonly=True)) as state,
          closing(SQLiteRepository(root / 'jobs.sqlite3', destination, readonly=True)) as jobs):
        [row] = jobs._outcome_delivery_rows(CONSUMER, outcome_id=outcome_id)
        record, digest, stale, acknowledged, _ = OutcomeDelivery(jobs, None)._preflight(row)
        if stale or not acknowledged or not ordinary_event_outcome_settled(jobs, record):
            return None
        identity = record['identity']
        cycle_id, request_id = identity['cycle_id'], identity['request_id']
        cycle = state.cycle(cycle_id)
        settlement = _read_settlement(jobs, cycle_id, request_id)
        request_sha256 = settlement['binding']['request_sha256']
        frozen = load_ordinary_event_observation(
            jobs, state, cycle['runtime_binding'], cycle_id=cycle_id, request_sha256=request_sha256,
        )
        company = current_company_repair_snapshot(jobs, COMPANY_ID)
    receiver = Path(store.path).resolve().as_uri() + '?mode=ro'
    with closing(sqlite3.connect(receiver, uri=True)) as db:
        db.execute('BEGIN')
        receipt_row = db.execute(
            'SELECT record_sha256,receipt_id,receipt,receipt_sha256,sink_status '
            'FROM scrape_outcome_delivery_receipts WHERE consumer=? AND outcome_id=?',
            (CONSUMER, outcome_id),
        ).fetchone()
        intake_row = db.execute(
            'SELECT company_id,source_revision,outcome,payload FROM scrape_outcome_intake WHERE outcome_id=?',
            (outcome_id,),
        ).fetchone()
        if receipt_row is None or intake_row is None:
            return None
        Store._validate_delivery_intake(
            intake_row, canonical=record, record_sha256=digest,
            legacy_text=json.dumps(record, sort_keys=True, separators=(',', ':')),
        )
        receipt = Store._validate_delivery_receipt(receipt_row, consumer=CONSUMER, canonical=record, record_sha256=digest)
        if receipt != json.loads(row[6]):
            return None
        # The existing held-intake view can use the same read-only snapshot.
        view = SimpleNamespace(connect=lambda: nullcontext(db))
        [held] = [item for item in Store.held_repair_intake(view) if item['outcome_id'] == outcome_id]
        continuation = {}
        if expected_task_id is not None:
            task_row = db.execute('SELECT state FROM tasks WHERE id=?', (expected_task_id,)).fetchone()
            if task_row is None:
                return None
            continuation = dict(expected_task_id=expected_task_id, promoted_task=json.loads(task_row[0]))
    selection = {key: identity[key] for key in IDENTITY}
    selection.update(outcome_id=outcome_id, request_sha256=request_sha256)
    return dict(selection=selection, company=company, record=record, receipt=receipt,
                held=held, settlement=settlement, frozen=frozen, **continuation)


def read_owned_choice_input(root, store, *, outcome_id, enabled=False, expected_task_id=None):
    """Read one outcome from the caller's trusted owner paths and receiver store.

    The caller owns the normal application leases. Missing, stale, or
    inconsistent evidence leaves the choice held. The result is input for one
    review call and confers no launch authority. An optional expected_task_id
    continues the same immutable input only for its exact promoted owner.
    """
    if (enabled is not True or not isinstance(outcome_id, str) or not _OUTCOME_ID.fullmatch(outcome_id)
            or (expected_task_id is not None and (not isinstance(expected_task_id, str)
                or not re.fullmatch(r'WRAP-[0-9a-f]{10}', expected_task_id)))):
        return None
    try:
        verified = _verified_readbacks(root, store, outcome_id, expected_task_id=expected_task_id)
        return prepare_choice_input(**verified, enabled=True) if verified is not None else None
    except (AttributeError, KeyError, OSError, RuntimeError, TypeError, ValueError, sqlite3.Error):
        return None


def _promoted_owner_matches(held, record, promoted_task, expected_task_id):
    if (not isinstance(promoted_task, dict)
            or not isinstance(promoted_task.get('integration'), dict)
            or not isinstance(promoted_task.get('integration_identity_digest'), str)
            or not re.fullmatch(r'[0-9a-f]{64}', promoted_task['integration_identity_digest'])):
        return False
    identity = canonical_identity(promoted_task['integration'])
    validate_bound_identity(promoted_task)
    return (held['status'] == 'PROMOTED_PAUSED' and held['task_id'] == expected_task_id
            and promoted_task.get('id') == expected_task_id
            and promoted_task.get('isolated_workspace') is True
            and promoted_task.get('held_repair_key') == held['repair_key']
            and promoted_task.get('repair_provenance') == {
                'repair_key': held['repair_key'], 'outcome_id': record['outcome_id'],
                'company_id': COMPANY_ID, 'source_revision': record['identity']['source_revision'],
            }
            and identity.get('company_id') == COMPANY_ID and identity.get('company') == COMPANY
            and identity.get('configured_url') == SOURCE)


def prepare_choice_input(*, selection, company, record, receipt, held, settlement, frozen,
                         enabled=False, expected_task_id=None, promoted_task=None):
    """Accept only the readbacks of the trusted owner for the selected request.

    The caller must verify current settlement, frozen observation, and both
    delivery ledgers through their existing authorities before invoking this
    pure projection. Its result can describe one review call. It confers no
    authority to run it, prepare a task, or resume a worker.
    """
    if enabled is not True:
        return None
    try:
        binding = settlement['binding']
        identity = {key: selection[key] for key in IDENTITY}
        expected_scope = {**identity, 'company_id': COMPANY_ID}
        digest = _selected_sha(record)
        owns_repair = (held['status'] == HELD and held['task_id'] is None and promoted_task is None
                       if expected_task_id is None else
                       _promoted_owner_matches(held, record, promoted_task, expected_task_id))
        if (not owns_repair or selection != {**identity, 'request_sha256': binding['request_sha256'],
                          'outcome_id': record['outcome_id']}
                or company != {'company_id': COMPANY_ID, 'source_revision': identity['source_revision'],
                               'company': COMPANY, 'official_careers_url': SOURCE, 'ats_source': 'acquiretm'}
                or record['identity'] != {**expected_scope, 'provider': 'AcquireTM',
                                         'adapter_version': 'normal-scraper-v1'}
                or {key: binding[key] for key in expected_scope} != expected_scope
                or (record['outcome'], record['action'], record['repair_category']) != (
                    'QUALIFIED_INTEGRATION_REPAIR', 'upsert_qualified_repair', 'pagination_regression')
                or settlement['schema'] != 'ordinary-company-event-settlement-v1'
                or binding['authority'] != 'ordinary-company-event-no-publication-v1'
                or settlement['outcome'] != record or settlement['stage'] != 'partial'
                or settlement['publication_sha256'] is not None
                or settlement['no_publication'] != {'scan_state': 'Partial', 'evidence_code': ACQUIRETM_PAGINATION_CODE}
                or _valid_receipt(receipt, CONSUMER, record['outcome_id'], digest) is None
                or receipt['sink_status'] != HELD
                or (held['company_id'], held['source_revision'], held['outcome_id'], held['outcome']) != (
                    COMPANY_ID, identity['source_revision'], record['outcome_id'], record)
                or record['outcome_id'] not in held['evidence_outcome_ids']
                or frozen['sha256'] != binding['observation_sha256']
                or _selected_sha({key: value for key, value in frozen.items() if key != 'sha256'}) != frozen['sha256']
                or frozen['inventory_sha256'] != binding['provider_inventory_sha256']
                or ordinary_no_publication_result(frozen) != ('partial', 'Partial', ACQUIRETM_PAGINATION_CODE)):
            return None
        witness = frozen['inventory']['outcome_failure']['evidence']
    except (AttributeError, KeyError, TypeError, ValueError):
        return None

    choices = {
        'listing_membership_change': 'Wait for fresh posting identifiers on the verified board after the same page click, then run the existing scope, completeness and full-detail checks.',
        'fixed_delay': 'Use the example observed elapsed time as a fixed sleeping interval on every page, with no listing state as readiness evidence.',
        'hold': 'Current observations cannot support one bounded repair.',
    }
    system = ('Choose one strategy as a strictly bounded evidence decision. '
              'Respond using worker_checkpoint, one call. Never propose source code. '
              'Use evidence ID W1 in summary. Put the exact chosen strategy ID in next_action, '
              'with phase_done in outcome. If observations are insufficient, use hold '
              'in next_action and blocked in outcome. Use only the values in the tool schema.')
    checkpoint = spec('worker_checkpoint',
                      'Record the evidence ID and one bounded next-action strategy. These are exact identifiers.', {
                          'summary': {'type': 'string', 'enum': ['W1']},
                          'next_action': {'type': 'string', 'enum': list(choices)},
                          'outcome': {'type': 'string', 'enum': ['phase_done', 'blocked']},
                      }, ['summary', 'next_action', 'outcome'])
    return {
        'mode': 'review', 'phase': 'inspect', 'max_calls': 1, 'tools': [checkpoint],
        'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': json.dumps({
            'task': 'Select how to recognize a completed pagination transition without weakening any existing validation.',
            'candidates': choices, 'W1': witness,
            'scope': 'Amphenol Aerospace COMP-0490 on its verified AcquireTM employer board',
        }, sort_keys=True)}],
        'binding': {**selection, 'company_id': COMPANY_ID, 'board': SOURCE, 'record_sha256': digest,
                    'sink_receipt_id': receipt['sink_receipt_id'], 'observation_sha256': frozen['sha256'],
                    'witness_sha256': _selected_sha(witness)},
    }
