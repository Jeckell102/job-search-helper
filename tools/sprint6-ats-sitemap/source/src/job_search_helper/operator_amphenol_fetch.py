"""Capture a normally dispatched partial for an exact reviewed operator request."""

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from .ats import validate_outcome_failure
from .cli import PROJECT_ROOT
from .company_events import canonical_company_fact
from .integration_release import assert_release_settled
from .ordinary_company_event_fetch import _scope_has_storage, _verify_workbook, capture_scoped_provider
from .ordinary_event_settlement import ordinary_no_publication_result
from .operator_partial_scope import AMPHENOL, ATS_CORPORATION, CROWN, EMBRAER, require_operator_partial_scope
from .retained_work_runner import assert_normal_lifecycle_not_held
from .runner import _canonical_runtime_binding
from .scan_request import _cycle_views, _unfinished_from_views
from .scoped_provider_observation import provider_identity, read_observation
from .temporary_retry import _selected_sha, _sync_directory


def _operator_source_files(scope):
    adapter = 'successfactors.py' if scope is CROWN or scope is ATS_CORPORATION else 'shared_boards.py'
    paths = (f'src/job_search_helper/{adapter}', 'src/job_search_helper/ats.py')
    if scope is ATS_CORPORATION:
        paths += ('src/job_search_helper/successfactors_sitemap.py', 'src/job_search_helper/ats_sitemap_parser.py')
    return {name: sha256((PROJECT_ROOT / name).read_bytes()).hexdigest() for name in paths}


def _observation_location(owner, state, runtime, scope=AMPHENOL):
    require_operator_partial_scope(scope)
    company = owner['company']
    fact = canonical_company_fact(company)
    if (owner['company_id'] != scope.company_id or company['Company'] != scope.company_name
            or fact['official_careers_url'] != scope.careers_url or fact['ats_source'] != scope.provider.casefold()):
        raise ValueError('Operator partial observation requires the reviewed Company source.')
    path = Path(state.path).parent / f'operator-{scope.slug}-observations' / (owner['request_sha256'] + '.json')
    binding = {
        'schema': f'operator-{scope.slug}-observation-v1', 'source_revision': owner['source_revision'],
        'company_id': owner['company_id'], 'company_name': company['Company'], 'source_fact': fact,
        'request_sha256': owner['request_sha256'], 'request_fingerprint': owner['request_fingerprint'],
        'request_receipt_sha256': _selected_sha(owner['receipt']), 'runtime': _canonical_runtime_binding(runtime),
    }
    if scope is EMBRAER or scope is CROWN or scope is ATS_CORPORATION:
        binding['source_files'] = _operator_source_files(scope)
    return path, binding


def _qualified_partial(observation, scope):
    if observation['state'] != 'FROZEN':
        return False
    if scope is AMPHENOL:
        return ordinary_no_publication_result(observation) == ('partial', 'Partial', scope.failure_code)
    inventory = observation['inventory']
    failure = validate_outcome_failure(inventory.get('outcome_failure'))
    if (failure is None or failure['category'] != scope.failure_category
            or failure['evidence_code'] != scope.failure_code
            or inventory['status'] != 'partial' or inventory['ats'] != scope.provider
            or inventory['requested_url'] != scope.careers_url or inventory['source_url'] != scope.board_url
            or inventory['browser_pending_urls'] != [] or inventory['browser_discovery_incomplete'] is not False
            or inventory.get('verified_zero') is not None):
        return False
    evidence = failure['evidence']
    if scope is CROWN or scope is ATS_CORPORATION:
        return (not inventory['jobs'] and evidence['company_id'] == scope.company_id
                and evidence['board'] == scope.board_url)
    return (evidence['company_id'] == scope.company_id and evidence['company'] == scope.company_name
            and evidence['board'] == scope.board_url
            and evidence['advertised_total'] == len(inventory['jobs']) + evidence['detail_failure_count'])


def load_operator_amphenol_partial(owner, state, runtime):
    return load_operator_partial(owner, state, runtime, scope=AMPHENOL)


def load_operator_partial(owner, state, runtime, *, scope):
    """Reopen the exact typed provider observation for an already verified owner."""
    path, binding = _observation_location(owner, state, runtime, scope)
    observation = read_observation(path, binding)
    if observation is None or not _qualified_partial(observation, scope):
        raise ValueError('Operator request has no exact qualified frozen partial.')
    _sync_directory(path.parent)
    return observation


def observe_operator_amphenol_partial(reader, state, runtime, *, request_sha256, fetcher,
                                     remote_reader, clock=None):
    return observe_operator_partial(reader, state, runtime, request_sha256=request_sha256,
                                    fetcher=fetcher, remote_reader=remote_reader, scope=AMPHENOL, clock=clock)


def observe_operator_partial(reader, state, runtime, *, request_sha256, fetcher, remote_reader, scope, clock=None):
    """Observe one exact operator request under the normal scraper and writer leases."""
    from .operator_selected_observation import read_operator_selected_observation

    runtime = _canonical_runtime_binding(runtime)

    def ownership():
        return read_operator_selected_observation(reader, state, runtime, request_sha256=request_sha256, scope=scope)

    owner = ownership()
    company, cycle = owner['company'], owner.get('cycle')
    root = Path(state.path).parent
    path, binding = _observation_location(owner, state, runtime, scope)
    observation = read_observation(path, binding)
    result = {'company_id': owner['company_id'], 'request_sha256': request_sha256}
    if observation is not None and observation['state'] == 'CLAIMED':
        return {'state': 'HELD_FETCH_UNCERTAIN', **result}

    def require_current_owner():
        assert_release_settled(root)
        assert_normal_lifecycle_not_held(root, reader.path)
        if (ownership() != owner or _observation_location(owner, state, runtime, scope)[1] != binding
                or (cycle and _scope_has_storage(reader, root, cycle['id']))):
            raise ValueError('Operator request, source or existing storage changed during observation.')

    require_current_owner()
    if observation is None:
        local, mirrors = _cycle_views(reader, state)
        if owner['state'] != 'QUEUED' or _unfinished_from_views(local, mirrors):
            raise ValueError('An operator partial observation cannot start after admission or alongside unfinished work.')
        _verify_workbook(reader, remote_reader, company)
        require_current_owner()
        now = clock or (lambda: datetime.now(timezone.utc))
        observation = capture_scoped_provider(path, binding, company, provider_identity(scope.provider, scope.board_url),
                                              fetcher, now)
        require_current_owner()
    else:
        _sync_directory(path.parent)

    if not _qualified_partial(observation, scope):
        return {'state': 'HELD_NO_QUALIFIED_PARTIAL', **result}
    return {'state': 'QUALIFIED_PARTIAL_FROZEN', 'observation_sha256': observation['sha256'], **result}
