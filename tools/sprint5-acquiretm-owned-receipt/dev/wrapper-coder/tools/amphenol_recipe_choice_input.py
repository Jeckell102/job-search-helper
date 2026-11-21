"""Project validated application readbacks to the closed Amphenol choice prompt."""
import json

from coding_tools import spec
from job_search_helper.acquiretm import SOURCE
from job_search_helper.ats import ACQUIRETM_PAGINATION_CODE
from job_search_helper.ordinary_event_settlement import ordinary_no_publication_result
from job_search_helper.scrape_outcome_delivery import CONSUMER, _valid_receipt
from job_search_helper.temporary_retry import _selected_sha


COMPANY_ID = 'COMP-0490'
COMPANY = 'Amphenol Aerospace'
HELD = 'HELD_FOR_REPAIR_TRIAGE'
IDENTITY = ('cycle_id', 'request_id', 'company_event_id', 'source_revision')


def prepare_choice_input(*, selection, company, record, receipt, held, settlement, frozen, enabled=False):
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
        if (selection != {**identity, 'request_sha256': binding['request_sha256'],
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
                or (held['company_id'], held['source_revision'], held['status'], held['task_id'],
                    held['outcome_id'], held['outcome']) != (
                    COMPANY_ID, identity['source_revision'], HELD, None, record['outcome_id'], record)
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
