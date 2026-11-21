"""Turn completed ordinary normal-cycle facts into bounded M3 outcomes.

This is deliberately a recorder, not a repair dispatcher.  It accepts only
the ordinary cycle checkpoint and current Company row, so it cannot invent
private diagnostics or turn an ambiguous failure into a code-change request.
"""
from .ats import validate_outcome_failure
from .company_events import source_revision
from .exact_cycle_receipt import has_repair_retry_scope
from .repository import RepositoryError


def record_cycle_outcomes(repository, cycle, companies, *, storage_confirmed,
                          state=None, inbox=None):
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
    released_retry = has_repair_retry_scope(cycle)
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
            if released_retry and _successful_inventory(item):
                # The exact retry may have saved inventory while publication
                # is still pending. Leave the terminal outcome slot open.
                if state is not None and inbox is not None:
                    outcome = repository.record_repair_retry_success(
                        cycle['id'], str(company_id), state=state, inbox=inbox)
                    if outcome is not None:
                        results.append(outcome)
                continue
            facts = normal_cycle_outcome_facts(
                cycle, company, item, storage_confirmed=storage_confirmed)
            # Closed mapping evidence is an engineering explanation only for
            # an otherwise unknown, incomplete observation.  It never
            # overwrites complete/zero, access, or temporary evidence.
            sealed = None
            if (facts['inventory_status'] not in {'complete', 'zero'}
                    and facts['failure'].get('category') == 'unknown'):
                sealed = _sealed_mapping_evidence(repository, cycle, company, item)
            if sealed is not None:
                facts.update(sealed)
        except (RepositoryError, TypeError, ValueError):
            # Follow-up evidence must never destabilize a completed scrape.
            # Leave malformed or overlong checkpoint values out for operator
            # inspection rather than coercing them into a false repair signal.
            continue
        # Stale/paused evidence is durable audit evidence too.  The repository
        # withholds it from the reserved repair-coordinator consumer while
        # retaining it for audit and restart-safe review.
        if sealed is not None:
            # The repository rebuilds the facts and revalidates the sealed
            # group; this probe only chooses the closed writer boundary.
            results.append(repository.record_sealed_source_configuration_outcome(
                cycle['id'], str(company_id), storage_confirmed=storage_confirmed))
        else:
            results.append(repository.record_scrape_outcome(facts))
    return results


def _successful_inventory(item):
    if item.get('stage') != 'complete':
        return False
    status = _inventory_status(item, 'complete')
    return status == 'complete' or status == 'zero' and item.get('zero_openings_verified') is True


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
    temporary = cycle.get('temporary_retry')
    retry_identity = None
    if has_repair_retry_scope(cycle):
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
    if retry_identity is not None and stage != 'complete' and inventory_status in {'complete', 'zero'}:
        inventory_status = 'partial'
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
        'failure': _outcome_failure(item, inventory_status),
    }
    if item.get('zero_openings_verified') is True:
        facts['zero_openings_verified'] = True
    if retry_identity is not None:
        facts.update(retry_identity)
    if temporary is not None:
        if (not isinstance(temporary, dict) or temporary.get('retry_index') != 1
                or temporary.get('retry_cap') != 1 or temporary.get('company_id') != company_id):
            raise ValueError('Temporary retry outcome identity is invalid.')
        facts['temporary_retry_outcome_id'] = temporary['outcome_id']
    return facts


def _sealed_mapping_evidence(repository, cycle, company, item):
    """Return sealed mapping identity only from a complete durable group.

    This deliberately re-reads both installed bytes and the held qualification
    file.  It does not manufacture a group from a reason, a fetch result, or a
    current Company row.
    """
    from .source_configuration_snapshot import (
        _resolve_authoritative_installed_source_configuration,
        qualification_for_snapshot, validate_installed_source_configuration,
        validate_mapping_divergence_fact, validate_source_configuration_defect,
        validate_source_configuration_qualification_evidence)
    snapshot = validate_installed_source_configuration(item.get('installed_source_configuration'))
    sidecar = validate_source_configuration_defect(item.get('source_configuration_defect'), snapshot=snapshot)
    fact = validate_mapping_divergence_fact(item.get('source_configuration_mapping_fact'),
                                            cycle_id=cycle.get('id'), snapshot=snapshot)
    evidence = validate_source_configuration_qualification_evidence(
        item.get('source_configuration_qualification_evidence'), snapshot=snapshot)
    if snapshot is None or sidecar is None or fact is None or evidence is None:
        return None
    if (item.get('outcome_source_revision') != snapshot['source_revision']
            or item.get('outcome_source_fact', {}).get('company_id') != snapshot['company_id']
            or str(company.get('Company ID', '')).strip() != snapshot['company_id']):
        return None
    current = validate_installed_source_configuration(
        _resolve_authoritative_installed_source_configuration(repository, snapshot['company_id']))
    qualification = qualification_for_snapshot(snapshot)
    if (current != snapshot or qualification is None
            or evidence.get('matrix_digest') != qualification['matrix_digest']
            or evidence.get('qualification') != qualification['qualification']):
        return None
    return {
        'capability': 'sealed',
        'failure': {'category': 'same_provider_source_mapping',
                    'provider_code': sidecar['evidence_code']},
        'capability_id': sidecar['capability_id'],
        'capability_digest': sidecar['capability_digest'],
        'mapping_digest': sidecar['mapping_digest'],
        'configuration_digest': sidecar['configuration_digest'],
    }


def _outcome_failure(item, inventory_status):
    """Use only an exact allowlisted companion envelope, never its reason."""
    if inventory_status in {'complete', 'zero'}:
        return {'category': 'none'}
    envelope = validate_outcome_failure(item.get('outcome_failure'))
    if envelope is None:
        return {'category': 'unknown'}
    category = {
        'access_denied': 'access_denied',
        'temporary_transport': 'temporary_transport',
    }.get(envelope['category'])
    if category is None:
        return {'category': 'unknown'}
    return {'category': category, 'provider_code': envelope['evidence_code']}


def _ordinary_normal_cycle(cycle):
    """Exclude unsupported admission paths, but retain exact released retries.

    A retry is an ordinary scraper/storage attempt with additional immutable
    identity. Its outcome must be available for stale-result precedence and
    audit. Event/operator/recovery paths still need their separate contracts.
    """
    return not any(cycle.get(key) is not None for key in (
        'company_event', 'operator_request', 'recovery_pause', 'selected_retry_reservation_sha256'))


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
