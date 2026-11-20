"""Verify and classify the exact settlement of one signed Company event."""
import json
from pathlib import Path
import re

from .ats import validate_outcome_failure
from .company_events import BRIDGE_CONSUMER, canonical_company_fact, current_company_source_revision
from .company_sources import repair_source
from .outcomes import classify_outcome
from .repository import _url
from .retained_dirty_provenance import retained_publication
from .retained_operator_journal import (
    FETCH_OUTCOME, SETTLED, VERIFIED_ZERO, RetainedOperatorJournal, _expected_consumption, _inventory_digest,
)
from .retained_operator_run import _stored_session, _terminal_evidence
from .retained_work_exception import _provider_identity, _request_provenance, digest
from .retained_work_orchestrator import _cycle_id
from .retained_work_runner import _read_json
from .scan_request import _timestamp


def retained_event_outcome_facts(local, request_sha256, reservation_digest):
    """Read exact active or archived settlement under scraper and writer locks."""
    jobs = Path(local.path)
    root = jobs.parent
    if (not local.readonly or not local.is_local or jobs.name != 'jobs.sqlite3' or jobs.is_symlink()):
        raise ValueError('Retained event outcome requires the canonical read-only Jobs repository.')
    record = RetainedOperatorJournal(root).read_settled_event(request_sha256, reservation_digest)
    if record is None or record['state'] != SETTLED:
        raise ValueError('Retained event outcome has no exact settlement.')
    binding = record['binding']
    claims = binding['claims']
    request = settled_event_request(root, binding, record)
    event_id, frozen_fact, current = sealed_event_source(root, local, claims, request)
    if record['settlement_evidence'].get('state') == FETCH_OUTCOME:
        evidence, current_facts, stale_facts = returned_failure_evidence(local, binding, record, event_id, frozen_fact)
        if evidence != record['settlement_evidence']:
            raise ValueError('Retained event failure settlement receipt changed.')
        chosen = stale_facts if evidence['source_current'] is False else current_facts
        return chosen, _existing_outcome(local, chosen)
    inventory = record['inventory']
    cycle_id = _cycle_id(reservation_digest)
    zero = record['settlement_evidence'].get('state') == VERIFIED_ZERO
    if zero:
        terminal = verified_zero_evidence(local, binding, record, frozen_fact)
    else:
        _verified_inventory(root, local, record, event_id, cycle_id, frozen_fact['official_careers_url'])
        terminal = _terminal_evidence(root, local, binding, record['inventory_sha256'])
    if terminal != record['settlement_evidence']:
        raise ValueError('Retained event outcome settlement receipt changed.')

    complete_facts = {
        'request_id': claims['request_id'], 'company_id': claims['company_id'],
        'source_revision': claims['source_revision'], 'company_event_id': event_id,
        'cycle_id': cycle_id, 'retained_reservation_sha256': reservation_digest,
        'provider': inventory['ats'], 'adapter_version': 'normal-scraper-v1',
        'source_current': True, 'company_status': 'Active', 'storage_status': 'confirmed',
        'inventory_status': inventory['status'], 'capability': 'unknown', 'failure': {'category': 'none'},
    }
    if zero:
        complete_facts.update(inventory_status='zero', zero_openings_verified=True, storage_status='not_required')
    # A newer source can suppress delivery, but it cannot change the result
    # already committed for the original attempt.
    stale_facts = dict(complete_facts, source_current=False)
    existing = _existing_outcome(local, complete_facts, stale_facts)
    return (complete_facts if current else stale_facts), existing


def settled_event_request(root, binding, record):
    """Read the exact original pending or consumed bytes with receipt validation."""
    request_sha = binding['claims']['request_sha256']
    expected = _expected_consumption(binding, record['settlement_evidence'])
    base = root / 'company-event-bridge'
    archive = base / 'consumed-requests' / f'{request_sha}.json'
    receipt = base / 'consumption-receipts' / f'{request_sha}.json'
    if receipt.exists() or record['consumption'] is not None:
        if _read_archived_json(receipt) != expected or record['consumption'] not in (None, expected):
            raise ValueError('Retained event outcome request consumption changed.')
        return _read_archived_json(archive)
    return _read_archived_json(archive if archive.exists() else root / 'next-scan.json')


def sealed_event_source(root, local, claims, request):
    """Verify immutable event scope and independently measure current eligibility."""
    from .company_events import MANUAL_RETAINED_SCHEMA
    from .scan_request import _company_event_timing, _enqueued_at

    base = root / 'company-event-bridge'
    if digest(request) != claims['request_sha256']:
        raise ValueError('Retained event outcome request hash changed.')
    if (set(request) != {'mode', 'request_id', 'company_ids', 'source_revision', 'enqueued_at',
                         'start_last', 'company_event', 'company_event_timing', 'manual_retained'}
            or request['request_id'] != claims['request_id'] or request['company_ids'] != [claims['company_id']]
            or request['source_revision'] != claims['source_revision'] or request['start_last'] != []
            or request['manual_retained'] != {'schema': MANUAL_RETAINED_SCHEMA,
                                             'blocking_cycle_id': claims['cycle_id']}):
        raise ValueError('Retained event outcome is outside the signed manual scope.')
    event = request['company_event']
    if (not isinstance(event, dict) or set(event) != {
            'schema', 'event_id', 'company_id', 'revision', 'source_revision'}
            or not isinstance(event['event_id'], str) or not re.fullmatch('CEV-[0-9a-f]{32}', event['event_id'])):
        raise ValueError('Retained event outcome has an invalid event identity.')
    event_id = event['event_id']
    receipt = _read_archived_json(base / 'receipts' / f'{event_id}.json')
    _request_provenance(request, receipt)
    _enqueued_at(request)
    _timestamp(receipt.get('recorded_at'), 'Company-event receipt time')
    timing = _company_event_timing(request)
    if (set(receipt) != set(event) | {'state', 'recorded_at', 'request_sha256'}
            or type(receipt['revision']) is not int or receipt['state'] != 'REQUEST_WRITTEN'
            or digest(receipt) != claims['receipt_sha256'] or timing is None
            or timing['condition'] != 'unverified' or timing['blocking_cycle_ids'] != [claims['cycle_id']]):
        raise ValueError('Retained event outcome staging receipt changed.')

    row = local.db.execute(
        'SELECT o.payload,r.fact,o.created_at,'
        '(SELECT MAX(newer.revision) FROM company_revisions newer WHERE newer.company_id=o.company_id) '
        'FROM company_event_outbox o '
        'JOIN company_revisions r ON r.company_id=o.company_id AND r.revision=o.revision '
        'AND r.source_revision=o.source_revision AND r.eligible=1 '
        'JOIN company_event_deliveries d ON d.event_id=o.event_id AND d.consumer=? '
        'JOIN company_event_watermarks w ON w.consumer=d.consumer AND w.company_id=o.company_id '
        'AND w.revision>=o.revision '
        'JOIN company_revisions wr ON wr.company_id=w.company_id AND wr.revision=w.revision '
        'AND wr.source_revision=w.source_revision '
        'WHERE o.event_id=? AND o.company_id=? AND o.revision=? AND o.source_revision=? '
        "AND o.kind='company.eligible'",
        (BRIDGE_CONSUMER, event_id, claims['company_id'], event['revision'], claims['source_revision']),
    ).fetchone()
    if row is None or row[2] != timing['observed_at']:
        raise ValueError('Retained event outcome lacks an acknowledged Company event.')
    outbox, frozen_fact = json.loads(row[0]), json.loads(row[1])
    if (not isinstance(outbox, dict) or outbox.get('origin') not in (
            'application', 'import', 'sheets-reconciliation')
            or outbox.get('kind') != 'company.eligible' or type(outbox.get('revision')) is not int
            or any(outbox.get(key) != event[key] for key in ('company_id', 'event_id', 'revision', 'source_revision'))
            or outbox.get('fact') != frozen_fact or digest(frozen_fact) != claims['source_revision']
            or frozen_fact.get('eligible') is not True or frozen_fact.get('company_status') != 'active'
            or frozen_fact.get('company_id') != claims['company_id']
            or not isinstance(outbox.get('company'), str) or not outbox['company'].strip()):
        raise ValueError('Retained event outcome frozen source or event origin changed.')
    matches = local.matches('Companies', {'Company ID': claims['company_id']})
    if len(matches) > 1:
        raise ValueError('Retained event outcome current Company is ambiguous.')
    company = matches[0][1] if matches else None
    current = (row[3] == event['revision'] and company is not None
               and canonical_company_fact(company) == frozen_fact)
    if current and any(str(company.get(key) or '').strip()
                       for key in ('Claimed By', 'Claim Token', 'Active Cycle ID')):
        raise ValueError('Retained event outcome Company has another owner.')
    return event_id, {**frozen_fact, 'company_name': outbox['company']}, current


def verified_zero_evidence(local, binding, record, frozen_fact):
    """Verify a supported explicit zero without creating a publication."""
    claims = binding['claims']
    inventory = record['inventory']
    code = inventory.get('verified_zero')
    facts_url = frozen_fact['official_careers_url']
    provider = _provider_identity(frozen_fact['ats_source'], facts_url)
    observed_provider = _provider_identity(inventory['ats'], inventory['source_url'])
    valid_greenhouse = code == 'greenhouse_explicit_total_zero' and provider.startswith('greenhouse:')
    valid_samtec = (code == 'samtec_jobvite_explicit_zero' and claims['company_id'] == 'COMP-0739'
                    and facts_url.rstrip('/') == 'https://jobs.jobvite.com/samtec/search')
    if (inventory['status'] != 'complete' or inventory['jobs'] != []
            or inventory.get('outcome_failure') is not None
            or inventory.get('browser_pending_urls') != [] or inventory.get('browser_discovery_incomplete') is not False
            or _url(inventory['requested_url']) != facts_url or not provider or observed_provider != provider
            or not (valid_greenhouse or valid_samtec)
            or _timestamp(inventory['fetch_started_at'], 'Zero inventory fetch start')
            > _timestamp(inventory['fetched_at'], 'Zero inventory fetch end')):
        raise ValueError('retained_event_zero_openings_not_verified')
    reservation = binding['reservation_digest']
    cycle = _cycle_id(reservation)
    _verify_no_publication(local, reservation, cycle)
    return {
        'state': VERIFIED_ZERO, 'request_id': claims['request_id'],
        'company_id': claims['company_id'], 'source_revision': claims['source_revision'],
        'reservation_digest': reservation, 'inventory_sha256': record['inventory_sha256'],
        'zero_evidence': code,
    }


def returned_failure_evidence(local, binding, record, event_id, frozen_fact, *, source_current=None):
    """Seal one returned failure and replay the original classification decision."""
    claims = binding['claims']
    inventory = record['inventory']
    reservation = binding['reservation_digest']
    cycle_id = _cycle_id(reservation)
    status = inventory['status']
    if (status not in {'partial', 'failed', 'blocked', 'unsupported'}
            or 'outcome_failure' not in inventory or inventory.get('verified_zero') is not None
            or _inventory_digest(inventory, binding) != record['inventory_sha256']
            or _timestamp(inventory['fetch_started_at'], 'Retained failure fetch start')
            > _timestamp(inventory['fetched_at'], 'Retained failure fetch end')):
        raise ValueError('Retained event failure requires an exact frozen incomplete response.')
    requested_url = inventory['requested_url']
    provider, board, _ = repair_source(frozen_fact['ats_source'], requested_url,
                                      claims['company_id'], frozen_fact['company_name'])
    expected_provider = _provider_identity(provider, board)
    if (_url(requested_url) != frozen_fact['official_careers_url'] or not expected_provider
            or _provider_identity(inventory['ats'], inventory['source_url']) != expected_provider):
        raise ValueError('Retained event failure provider source changed.')
    _verify_no_publication(local, reservation, cycle_id)

    envelope = validate_outcome_failure(inventory['outcome_failure'])
    failure = {'category': 'unknown'}
    if envelope is not None and status != 'unsupported':
        failure = {'category': envelope['category'], 'provider_code': envelope['evidence_code']}
    fresh = {
        'request_id': claims['request_id'], 'company_id': claims['company_id'],
        'source_revision': claims['source_revision'], 'company_event_id': event_id,
        'cycle_id': cycle_id, 'retained_reservation_sha256': reservation, 'provider': inventory['ats'],
        'adapter_version': 'normal-scraper-v1', 'source_current': True, 'company_status': 'Active',
        'storage_status': 'not_attempted', 'inventory_status': status, 'capability': 'unknown',
        'failure': failure,
    }
    stale = dict(fresh, source_current=False)
    if source_current is None:
        source_current = record['settlement_evidence'].get('source_current')
    if type(source_current) is not bool:
        raise ValueError('Retained event failure source decision is invalid.')
    outcome = classify_outcome(fresh if source_current else stale)
    evidence = {
        'state': FETCH_OUTCOME, 'request_id': claims['request_id'], 'company_id': claims['company_id'],
        'source_revision': claims['source_revision'], 'reservation_digest': reservation,
        'inventory_sha256': record['inventory_sha256'], 'source_current': source_current,
        'outcome': outcome,
    }
    return evidence, fresh, stale


def _verify_no_publication(local, reservation, cycle_id):
    if (_stored_session(Path(local.path).parent, reservation) is not None
            or local.db.execute('SELECT 1 FROM exact_local_applications WHERE cycle=? LIMIT 1', (cycle_id,)).fetchone()):
        raise ValueError('Retained no-write outcome conflicts with publication.')


def _read_archived_json(path):
    if path.resolve() != path or not path.is_file():
        raise ValueError('Retained event outcome requires a regular archive file.')
    return _read_json(path)


def _verified_inventory(root, local, record, event_id, cycle_id, requested_url):
    binding = record['binding']
    reservation = binding['reservation_digest']
    claims = binding['claims']
    inventory = record['inventory']
    if (inventory['status'] != 'complete' or not inventory['jobs']
            or _url(inventory['requested_url']) != requested_url
            or inventory.get('browser_pending_urls') != []
            or inventory.get('browser_discovery_incomplete') is not False
            or _timestamp(inventory.get('fetch_started_at'), 'Retained event fetch start')
            > _timestamp(inventory.get('fetched_at'), 'Retained event fetch finish')):
        raise ValueError('Retained event outcome inventory is incomplete.')
    if (root / 'retained-sessions.sqlite3').is_symlink():
        raise ValueError('Retained event outcome requires the canonical Session store.')
    session = _stored_session(root, reservation)
    provenance = retained_publication(local, reservation)
    if (session is None or session['cycle_id'] != cycle_id
            or (provenance['event_id'], provenance['cycle'], provenance['request_id'])
            != (event_id, cycle_id, claims['request_id'])):
        raise ValueError('Retained event outcome publication identity changed.')
    plan = json.loads(session['plan'])
    payload = dict(inventory)
    payload['inventory_status'] = payload.pop('status')
    if plan.get('inventory_payload_digest') != digest(payload):
        raise ValueError('Retained event outcome inventory does not match the settled plan.')


def retained_outcome_source_is_current(local, identity):
    """Recheck the exact outbox revision before any retained result is sent."""
    row = local.db.execute(
        'SELECT 1 FROM company_event_outbox o '
        'JOIN company_revisions r ON r.company_id=o.company_id AND r.revision=o.revision '
        'AND r.source_revision=o.source_revision AND r.eligible=1 '
        'WHERE o.event_id=? AND o.company_id=? AND o.source_revision=? '
        "AND o.kind='company.eligible' AND NOT EXISTS (SELECT 1 FROM company_revisions newer "
        'WHERE newer.company_id=o.company_id AND newer.revision>o.revision)',
        (identity['company_event_id'], identity['company_id'], identity['source_revision']),
    ).fetchone()
    return (row is not None and current_company_source_revision(local, identity['company_id'])
            == identity['source_revision'])


def _existing_outcome(local, *allowed_facts):
    outcomes = [classify_outcome(facts) for facts in allowed_facts]
    request_id = outcomes[0]['identity']['request_id']
    rows = local.db.execute(
        'SELECT outcome_id,request_id,company_id,source_revision,outcome,action,payload '
        'FROM scrape_outcomes WHERE request_id=?',
        (request_id,),
    ).fetchall()
    if not rows:
        return None
    for outcome in outcomes:
        identity = outcome['identity']
        expected = (outcome['outcome_id'], request_id, identity['company_id'],
                    identity['source_revision'], outcome['outcome'], outcome['action'],
                    json.dumps(outcome, ensure_ascii=False, sort_keys=True, separators=(',', ':')))
        if rows == [expected]:
            return outcome
    raise ValueError('Retained event outcome conflicts with an existing immutable record.')
