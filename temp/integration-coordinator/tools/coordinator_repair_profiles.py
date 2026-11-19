"""Deterministic, fail-closed selection of reviewed M4 repair profiles.

Profiles are deliberately data, not prompts or executable code.  An empty
registry is the safe default: a qualified M3 outcome then remains held for
engineering review.  A future qualified profile must bind one company,
provider, adapter version, failure category, source revision, URL, exact file
scope, and tests before it can create a paused coordinator task.
"""
import copy
import re


# No automatic profile is enabled until the F5 matrix has completed its
# independent preflight and qualification evidence.  Tests inject a profile
# through ``select_profile(..., profiles=...)``.
PROFILE_REGISTRY = ()


def select_profile(held_repair, current_company, *, profiles=PROFILE_REGISTRY):
    """Return one immutable task assignment or ``None`` without side effects.

    ``held_repair`` is the coordinator's immutable M3 record.  The caller
    obtains ``current_company`` from the local Job Search Helper authority;
    any absent, malformed, stale, or ambiguous input returns no profile.
    """
    if not isinstance(held_repair, dict) or not isinstance(current_company, dict):
        return None
    outcome = held_repair.get('outcome')
    if not isinstance(outcome, dict) or outcome.get('outcome') != 'QUALIFIED_INTEGRATION_REPAIR':
        return None
    identity = outcome.get('identity')
    if not isinstance(identity, dict):
        return None
    company_id = _text(identity.get('company_id'))
    source_revision = _text(identity.get('source_revision'))
    provider = _text(identity.get('provider')).casefold()
    adapter_version = _text(identity.get('adapter_version'))
    category = _text(outcome.get('repair_category')).casefold()
    if not all((company_id, source_revision, provider, adapter_version, category)):
        return None
    if (current_company.get('company_id') != company_id
            or current_company.get('source_revision') != source_revision):
        return None
    url = _https(current_company.get('official_careers_url'))
    name = _text(current_company.get('company'))
    if not url or not name:
        return None
    matches = []
    for raw in profiles:
        profile = _canonical_profile(raw)
        if profile is None:
            continue
        if (profile['company_id'] == company_id
                and profile['provider'] == provider
                and profile['adapter_version'] == adapter_version
                and profile['failure_category'] == category
                and profile['configured_url'] == url):
            matches.append(profile)
    if len(matches) != 1:
        return None
    profile = matches[0]
    integration = {
        'company_id': company_id, 'company': name, 'configured_url': url,
        'tests': list(profile['tests']), 'source_targets': list(profile['source_targets']),
        'ats': profile['provider'], 'work_order': profile['profile_id'],
    }
    paths = ' '.join(integration['source_targets'])
    tests = ' '.join(integration['tests'])
    return {
        'source_revision': source_revision,
        'profile_id': profile['profile_id'],
        'objective': (f"Develop the bounded {profile['profile_id']} repair for "
                      f"{company_id} {name}. Inspect {paths}; run {tests}. "
                      "Preserve employer scope, full descriptions, pagination, "
                      "and stable job identities. Save a tested candidate and "
                      "evidence handoff; do not release or retry the scraper."),
        'mode': 'develop', 'max_sessions': profile['max_sessions'],
        'integration': integration,
    }


def _canonical_profile(value):
    if not isinstance(value, dict) or set(value) != {
            'profile_id', 'company_id', 'provider', 'adapter_version',
            'failure_category', 'configured_url', 'tests', 'source_targets',
            'max_sessions'}:
        return None
    profile_id = _text(value.get('profile_id'))
    company_id = _text(value.get('company_id'))
    provider = _text(value.get('provider')).casefold()
    adapter_version = _text(value.get('adapter_version'))
    category = _text(value.get('failure_category')).casefold()
    url = _https(value.get('configured_url'))
    tests, targets = value.get('tests'), value.get('source_targets')
    sessions = value.get('max_sessions')
    if (not re.fullmatch(r'[a-z0-9][a-z0-9._-]{0,95}', profile_id)
            or not re.fullmatch(r'COMP-\d{4,}', company_id)
            or not provider or not adapter_version or not category or not url
            or not isinstance(sessions, int) or not 1 <= sessions <= 20
            or not _paths(tests, 'tests', 8, 'test_')
            or not _paths(targets, 'src', 12, None)):
        return None
    return {'profile_id': profile_id, 'company_id': company_id, 'provider': provider,
            'adapter_version': adapter_version, 'failure_category': category,
            'configured_url': url, 'tests': tuple(tests), 'source_targets': tuple(targets),
            'max_sessions': sessions}


def _paths(value, root, maximum, prefix):
    if not isinstance(value, list) or not 1 <= len(value) <= maximum or len(set(value)) != len(value):
        return False
    for item in value:
        if (not isinstance(item, str) or not re.fullmatch(r'[A-Za-z0-9_./-]+\.py', item)
                or not item.startswith(root + '/') or '/.' in item or '..' in item
                or prefix is not None and not item.rsplit('/', 1)[-1].startswith(prefix)):
            return False
    return True


def _text(value):
    return value.strip() if isinstance(value, str) and 0 < len(value.strip()) <= 256 else ''


def _https(value):
    value = _text(value)
    return value if value.startswith('https://') and not any(ch.isspace() for ch in value) else ''
