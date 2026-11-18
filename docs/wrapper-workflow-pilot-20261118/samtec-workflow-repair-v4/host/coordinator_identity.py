"""Host-owned company identity and immutable worker assignment bindings."""
import hashlib
import json
import re
from pathlib import PurePosixPath
from urllib.parse import urlsplit

REQUIRED = frozenset({'company_id', 'company', 'configured_url', 'tests', 'source_targets'})
OPTIONAL = frozenset({'work_order', 'ats', 'repaired_url'})
BINDING_FIELDS = ('objective', 'tests', 'integration')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def canonical_identity(integration):
    if not isinstance(integration, dict) or REQUIRED - integration.keys() or integration.keys() - REQUIRED - OPTIONAL:
        raise ValueError('Integration identity needs all five canonical fields and only supported metadata.')
    result = {key: integration[key] for key in REQUIRED}
    if not isinstance(result['company_id'], str) or not re.fullmatch(r'COMP-\d{4,}', result['company_id']):
        raise ValueError('Invalid integration company ID.')
    company = result['company']
    if not isinstance(company, str) or not 1 <= len(company.strip()) <= 200 or any(ord(c) < 32 for c in company):
        raise ValueError('Invalid integration company name.')
    result['company'] = company.strip()
    for key in ('configured_url', 'repaired_url'):
        value = integration.get(key)
        if key == 'repaired_url' and value is None:
            continue
        if not isinstance(value, str) or len(value) > 2048 or any(c.isspace() for c in value):
            raise ValueError('Integration URLs must be bounded HTTPS URLs.')
        try:
            parsed = urlsplit(value)
            if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
                raise ValueError('Integration URLs must be public HTTPS URLs without credentials or fragments.')
            parsed.port
        except ValueError as exc:
            raise ValueError('Invalid integration HTTPS URL.') from exc
    for key in ('work_order', 'ats'):
        if key in integration and (not isinstance(integration[key], str) or len(integration[key]) > 200):
            raise ValueError('Invalid integration metadata: ' + key)
    for key, area, limit in (('tests', 'tests', 8), ('source_targets', 'src', 24)):
        paths = result[key]
        if not isinstance(paths, list) or not 1 <= len(paths) <= limit:
            raise ValueError('Integration file scope must be a nonempty bounded list.')
        for name in paths:
            if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_./-]+\.py', name):
                raise ValueError('Invalid integration file path.')
            path = PurePosixPath(name)
            if path.parts[0] != area or any(part in ('.', '..') or part.startswith('.') for part in path.parts) or str(path) != name:
                raise ValueError('Integration file path escapes its assigned area.')
            if key == 'tests' and not path.name.startswith('test_'):
                raise ValueError('Integration tests must name test files.')
        if len(set(paths)) != len(paths):
            raise ValueError('Duplicate integration file path.')
        result[key] = list(paths)
    return result


def identity_digest(integration):
    return digest(canonical_identity(integration))


def worker_assignment(integration):
    identity = canonical_identity(integration)
    return (f"Develop the bounded integration for {identity['company_id']} {identity['company']}. "
            f"Read docs/backlog/{identity['company_id']}.md when present. "
            + 'Inspect ' + ' '.join(identity['source_targets']) + '. '
            + 'Run ' + ' '.join(identity['tests']) + '. '
            + 'Retrieve current employer evidence from ' + identity['configured_url'] + '. '
            + 'Preserve exact employer scope, full descriptions, pagination and stable reread checks. '
            + 'Save a tested development draft and an evidence-based handoff for live validation.')


def canonical_requirements(integration, requirements):
    """Keep observed URL aliases, but bind source identity cues to this company."""
    identity = canonical_identity(integration)
    result = json.loads(json.dumps(requirements))
    assigned = identity['tests'] + identity['source_targets']
    if any(path not in result.get('required_files', []) for path in assigned):
        raise ValueError('Evidence requirements omit assigned integration files.')
    targets = result.get('source_targets', [])
    if not targets or any(target.get('url') != identity['configured_url'] for target in targets):
        raise ValueError('Evidence requirements must target the canonical company URL.')
    for target in targets:
        target['identity_terms'] = [identity['company']]
    return result


def bind_identity(state):
    result = json.loads(json.dumps(state))
    if not result.get('integration'):
        return result
    identity = canonical_identity(result['integration'])
    if result.get('tests') != identity['tests']:
        raise ValueError('Task tests disagree with canonical integration identity.')
    assignment = worker_assignment(result['integration'])
    result.update(integration_identity=identity, integration_identity_digest=digest(identity),
                  worker_assignment=assignment, worker_assignment_digest=digest(assignment),
                  identity_binding_digest=digest({key: result.get(key) for key in BINDING_FIELDS}),
                  evidence_requirements_digest=digest(result.get('evidence_requirements', {})))
    return result


def validate_bound_identity(state):
    if not state.get('integration'):
        if state.get('campaign_id') or state.get('integration_identity_digest'):
            raise ValueError('Campaign task is missing canonical integration identity.')
        return
    expected = bind_identity(state)
    for key in ('integration_identity', 'integration_identity_digest', 'worker_assignment',
                'worker_assignment_digest', 'identity_binding_digest', 'evidence_requirements_digest'):
        if state.get(key) != expected[key]:
            raise ValueError('Immutable integration identity or worker assignment changed: ' + key)
    if state.get('campaign_id') and state.get('campaign_company_id') != expected['integration_identity']['company_id']:
        raise ValueError('Campaign company ID conflicts with canonical identity.')
    requirements = state.get('evidence_requirements')
    if requirements:
        canonical = canonical_requirements(state['integration'], requirements)
        if canonical != requirements:
            raise ValueError('Evidence identity cues disagree with canonical company identity.')
