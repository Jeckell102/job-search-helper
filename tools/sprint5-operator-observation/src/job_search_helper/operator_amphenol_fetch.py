"""Capture one normally dispatched AcquireTM observation for the operator's exact request."""

from datetime import datetime, timezone
from pathlib import Path

from .acquiretm import SOURCE
from .company_events import canonical_company_fact
from .integration_release import assert_release_settled
from .ordinary_company_event_fetch import _scope_has_storage, _verify_workbook, capture_scoped_provider
from .ordinary_event_settlement import ACQUIRETM_PAGINATION_CODE, ordinary_no_publication_result
from .retained_work_runner import assert_normal_lifecycle_not_held
from .runner import _canonical_runtime_binding
from .scan_request import _cycle_views, _unfinished_from_views
from .scoped_provider_observation import provider_identity, read_observation
from .temporary_retry import _selected_sha, _sync_directory


def _observation_location(owner, state, runtime):
    company = owner['company']
    fact = canonical_company_fact(company)
    if (company['Company'] != 'Amphenol Aerospace'
            or fact['official_careers_url'] != SOURCE or fact['ats_source'] != 'acquiretm'):
        raise ValueError('Amphenol observation requires its reviewed AcquireTM board.')
    path = Path(state.path).parent / 'operator-amphenol-observations' / (owner['request_sha256'] + '.json')
    binding = {
        'schema': 'operator-amphenol-observation-v1', 'source_revision': owner['source_revision'],
        'company_id': owner['company_id'], 'company_name': company['Company'], 'source_fact': fact,
        'request_sha256': owner['request_sha256'], 'request_fingerprint': owner['request_fingerprint'],
        'request_receipt_sha256': _selected_sha(owner['receipt']), 'runtime': _canonical_runtime_binding(runtime),
    }
    return path, binding


def load_operator_amphenol_partial(owner, state, runtime):
    """Reopen the exact typed provider observation for an already verified owner."""
    path, binding = _observation_location(owner, state, runtime)
    observation = read_observation(path, binding)
    if (observation is None or observation['state'] != 'FROZEN'
            or ordinary_no_publication_result(observation) != ('partial', 'Partial', ACQUIRETM_PAGINATION_CODE)):
        raise ValueError('Amphenol has no exact qualified frozen partial.')
    _sync_directory(path.parent)
    return observation


def observe_operator_amphenol_partial(reader, state, runtime, *, request_sha256, fetcher,
                                     remote_reader, clock=None):
    """Observe one exact operator request under the normal scraper and writer leases."""
    from .operator_selected_observation import read_operator_selected_observation

    runtime = _canonical_runtime_binding(runtime)

    def ownership():
        return read_operator_selected_observation(reader, state, runtime, request_sha256=request_sha256)

    owner = ownership()
    company, cycle = owner['company'], owner.get('cycle')
    root = Path(state.path).parent
    path, binding = _observation_location(owner, state, runtime)
    observation = read_observation(path, binding)
    result = {'company_id': owner['company_id'], 'request_sha256': request_sha256}
    if observation is not None and observation['state'] == 'CLAIMED':
        return {'state': 'HELD_FETCH_UNCERTAIN', **result}

    def require_current_owner():
        assert_release_settled(root)
        assert_normal_lifecycle_not_held(root, reader.path)
        if ownership() != owner or (cycle and _scope_has_storage(reader, root, cycle['id'])):
            raise ValueError('Amphenol request, source or existing storage changed during observation.')

    require_current_owner()
    if observation is None:
        local, mirrors = _cycle_views(reader, state)
        if owner['state'] != 'QUEUED' or _unfinished_from_views(local, mirrors):
            raise ValueError('An Amphenol observation cannot start after admission or alongside unfinished work.')
        _verify_workbook(reader, remote_reader, company)
        require_current_owner()
        now = clock or (lambda: datetime.now(timezone.utc))
        observation = capture_scoped_provider(path, binding, company, provider_identity('AcquireTM', SOURCE),
                                              fetcher, now)
        require_current_owner()
    else:
        _sync_directory(path.parent)

    if ordinary_no_publication_result(observation) != ('partial', 'Partial', ACQUIRETM_PAGINATION_CODE):
        return {'state': 'HELD_NO_QUALIFIED_PARTIAL', **result}
    return {'state': 'QUALIFIED_PARTIAL_FROZEN', 'observation_sha256': observation['sha256'], **result}
