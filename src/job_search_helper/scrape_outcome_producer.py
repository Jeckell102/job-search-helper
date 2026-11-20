"""Turn completed normal-scraper cycle facts into bounded M3 outcomes.

This is deliberately a recorder, not a repair dispatcher.  It accepts only
the ordinary cycle checkpoint and current Company row, so it cannot invent
private diagnostics or turn an ambiguous failure into a code-change request.
"""
from .company_events import source_revision
from .repository import RepositoryError


def record_cycle_outcomes(repository, cycle, companies, *, storage_confirmed):
    """Persist one idempotent outcome per completed Company in a cycle."""
    if not isinstance(cycle, dict) or not isinstance(companies, list):
        raise ValueError('Cycle outcome recording requires saved cycle and Company facts.')
    if not isinstance(storage_confirmed, bool):
        raise ValueError('Storage confirmation must be explicit.')
    by_id = {str(row.get('Company ID') or '').strip(): row for row in companies}
    results = []
    for company_id, item in (cycle.get('companies') or {}).items():
        if (not isinstance(item, dict) or not isinstance(item.get('stage'), str)
                or item.get('stage') not in {
                'complete', 'partial', 'blocked', 'failed', 'unsupported'}):
            continue
        company = by_id.get(str(company_id).strip())
        if not company:
            continue
        try:
            facts = _facts(cycle, company, item, storage_confirmed=storage_confirmed)
        except (RepositoryError, TypeError, ValueError):
            # Follow-up evidence must never destabilize a completed scrape.
            # Leave malformed or overlong checkpoint values out for operator
            # inspection rather than coercing them into a false repair signal.
            continue
        results.append(repository.record_scrape_outcome(facts))
    return results


def _facts(cycle, company, item, *, storage_confirmed):
    event = cycle.get('company_event') or {}
    if not isinstance(event, dict):
        raise ValueError('Company event must be structured when present.')
    company_id = _required_text(company.get('Company ID'), 'company ID')
    revision = source_revision(company)
    requested_revision = _optional_text(event.get('source_revision'))
    current = not requested_revision or requested_revision == revision
    stage = item['stage']
    # Scraper stages do not carry a trustworthy adapter fault category.  Hold
    # non-complete work for evidence rather than guessing it merits a repair.
    category = 'none' if stage == 'complete' else 'unknown'
    facts = {
        'request_id': _required_text(cycle.get('start_request_id') or cycle.get('id'), 'request ID'),
        'company_id': company_id,
        'source_revision': revision,
        'company_event_id': _optional_text(event.get('event_id')),
        'cycle_id': _required_text(cycle.get('id'), 'cycle ID'),
        'provider': _optional_text(item.get('ats')) or _optional_text(company.get('ATS / Source')) or 'unknown',
        'adapter_version': 'normal-scraper-v1',
        'source_current': current,
        'company_status': _optional_text(company.get('Company Status')) or 'Active',
        'storage_status': 'confirmed' if storage_confirmed else 'sync_pending',
        'inventory_status': 'complete' if stage == 'complete' else 'partial',
        'capability': 'unknown',
        'failure': {'category': category},
    }
    retry = cycle.get('repair_retry')
    if isinstance(retry, dict):
        # A retry outcome must never be attributed merely to a friendly
        # release ID.  Canonicalizing here keeps a malformed recovered cycle
        # from producing an apparently authoritative repair outcome.
        from .repair_retry import canonical_retry_binding, release_binding_sha256
        retry = canonical_retry_binding(retry)
        facts['attempt_id'] = retry['attempt_id']
        facts['failed_request_id'] = retry['failed_request_id']
        facts['release_version'] = retry['release']['release_id']
        facts['release_binding_sha256'] = release_binding_sha256(retry['release'])
    return facts


def _required_text(value, field):
    value = _optional_text(value)
    if not value:
        raise ValueError(f'{field} is required.')
    return value


def _optional_text(value):
    if value is None:
        return ''
    if not isinstance(value, str):
        raise ValueError('Outcome evidence text must be text.')
    value = value.strip()
    if len(value) > 256:
        raise ValueError('Outcome evidence text exceeds its safe bound.')
    return value
