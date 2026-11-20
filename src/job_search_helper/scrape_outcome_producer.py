"""Turn completed ordinary normal-cycle facts into bounded M3 outcomes.

This is deliberately a recorder, not a repair dispatcher.  It accepts only
the ordinary cycle checkpoint and current Company row, so it cannot invent
private diagnostics or turn an ambiguous failure into a code-change request.
"""
from .company_events import source_revision
from .repository import RepositoryError


def record_cycle_outcomes(repository, cycle, companies, *, storage_confirmed):
    """Persist bounded outcomes for the ordinary normal-cycle path only.

    This is deliberately post-storage.  A fresh Company read can suppress a
    stale repair/retry/coordinator handoff, but cannot claim to have prevented
    an earlier job write.  Pre-persistence source fencing remains Engine and
    admission work, outside this M3 adapter.
    """
    if not isinstance(cycle, dict) or not isinstance(companies, list):
        raise ValueError('Cycle outcome recording requires saved cycle and Company facts.')
    if not isinstance(storage_confirmed, bool):
        raise ValueError('Storage confirmation must be explicit.')
    if not _ordinary_normal_cycle(cycle):
        return []
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
            facts = normal_cycle_outcome_facts(
                cycle, company, item, storage_confirmed=storage_confirmed)
        except (RepositoryError, TypeError, ValueError):
            # Follow-up evidence must never destabilize a completed scrape.
            # Leave malformed or overlong checkpoint values out for operator
            # inspection rather than coercing them into a false repair signal.
            continue
        # Stale/paused evidence is durable audit evidence too.  The repository
        # withholds it from the reserved repair-coordinator consumer while
        # retaining it for audit and restart-safe review.
        results.append(repository.record_scrape_outcome(facts))
    return results


def normal_cycle_outcome_facts(cycle, company, item, *, storage_confirmed):
    """Build conservative M3 facts from one saved ordinary-cycle item.

    Only values already saved in the cycle item or authoritative Company row
    are used.  Missing completion evidence becomes a partial/unknown hold;
    the adapter never infers a qualified integration defect.
    """
    company_id = _required_text(company.get('Company ID'), 'company ID')
    current_revision = source_revision(company)
    frozen_revision = _optional_text(item.get('outcome_source_revision'))
    retry = cycle.get('repair_retry')
    retry_identity = None
    if retry is not None:
        # A released retry has a stronger, admission-time identity than a
        # normal checkpoint.  Carry all of it into the outcome so a later
        # repair consumer cannot mistake this for the failed attempt or a
        # different installed version.  Invalid lineage is held by skipping
        # this record in the caller, never by manufacturing a normal outcome.
        from .repair_retry import release_binding_sha256, validate_retry_request
        # Do not infer retry admission from a cycle ID.  The stored cycle must
        # still carry the exact successor request identity and its one-company
        # scope, otherwise an outcome could be attached to the failed request
        # or an unrelated normal cycle.
        retry = validate_retry_request(
            {
                'repair_retry': retry,
                'request_id': cycle.get('start_request_id'),
                'source_revision': retry.get('source_revision') if isinstance(retry, dict) else None,
            },
            list((cycle.get('companies') or {}).keys()),
        )
        if retry['company_id'] != company_id:
            raise ValueError('Repair retry outcome Company identity does not match the cycle.')
        if frozen_revision and frozen_revision != retry['source_revision']:
            raise ValueError('Repair retry outcome source revision conflicts with its admission binding.')
        frozen_revision = retry['source_revision']
        retry_identity = {
            'attempt_id': retry['attempt_id'],
            'failed_request_id': retry['failed_request_id'],
            'release_version': retry['release']['release_id'],
            'release_binding_sha256': release_binding_sha256(retry['release']),
        }
    # A post-run reread only proves freshness when the saved item recorded the
    # source fact it began from.  Missing provenance is an unclassified hold,
    # not permission to call the current row "fresh."
    current = frozen_revision == current_revision if frozen_revision else None
    stage = item['stage']
    inventory_status = _inventory_status(item, stage)
    # Scraper stages do not carry a trustworthy adapter fault category. Hold
    # non-complete work for evidence rather than guessing it merits a repair.
    category = 'none' if inventory_status == 'complete' else 'unknown'
    facts = {
        'request_id': _required_text(cycle.get('start_request_id') or cycle.get('id'), 'request ID'),
        'company_id': company_id,
        # The frozen assignment fact, not a post-run reread, is immutable
        # outcome identity. The reread remains bounded comparison evidence.
        # Legacy checkpoints cannot assert freshness, but still need a bounded
        # durable hold identity rather than an unrecordable empty fact.
        'source_revision': frozen_revision or current_revision,
        'current_source_revision': current_revision,
        'cycle_id': _required_text(cycle.get('id'), 'cycle ID'),
        'provider': _optional_text(item.get('ats')) or _optional_text(company.get('ATS / Source')) or 'unknown',
        'adapter_version': 'normal-scraper-v1',
        'source_current': current,
        'company_status': _optional_text(company.get('Company Status')) or 'Active',
        'storage_status': 'confirmed' if storage_confirmed else 'sync_pending',
        'inventory_status': inventory_status,
        'capability': 'unknown',
        'failure': {'category': category},
    }
    if item.get('zero_openings_verified') is True:
        facts['zero_openings_verified'] = True
    if retry_identity is not None:
        facts.update(retry_identity)
    return facts


def _ordinary_normal_cycle(cycle):
    """Exclude unsupported admission paths, but retain exact released retries.

    A retry is an ordinary scraper/storage attempt with additional immutable
    identity. Its outcome must be available for stale-result precedence and
    audit. Event/operator/recovery paths still need their separate contracts.
    """
    return not any(cycle.get(key) is not None for key in (
        'company_event', 'operator_request', 'recovery_pause'))


def _inventory_status(item, stage):
    """Require saved completion proof and downgrade unknown facts to a hold."""
    status = _optional_text(item.get('inventory_status')).casefold()
    if status not in {'complete', 'partial', 'blocked', 'failed', 'unsupported', 'zero'}:
        status = 'partial'
    if item.get('browser_pending_urls') or item.get('browser_discovery_incomplete'):
        return 'partial'
    # A stage alone is not completion evidence: normal Engine output preserves
    # the fetched inventory status, and anything else must remain incomplete.
    if stage == 'complete' and status not in {'complete', 'zero'}:
        return 'partial'
    return status


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
