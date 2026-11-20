"""Owned admission and result handoff for one ordinary company-only fetch."""

from . import ordinary_verification_pending as pending
from .ordinary_verification_outcome import existing_outcome
from .repository import RepositoryError
from .source_configuration_snapshot import (
    _resolve_authoritative_installed_source_configuration, qualification_for_snapshot,
    validate_installed_source_configuration,
)


class OrdinaryVerificationHandoff:
    """Use short local custody windows around the ordinary provider call."""

    def __init__(self, cycle_id, open_stores):
        self.cycle_id = cycle_id
        self._open_stores = open_stores

    def _cycle(self, stores):
        cycle = stores.state.cycle(self.cycle_id)
        members = cycle.get('companies') if isinstance(cycle, dict) else None
        if not isinstance(members, dict) or len(members) != 1:
            raise RepositoryError('Ordinary verification requires one saved Company.')
        company_id, item = next(iter(members.items()))
        if not isinstance(item, dict):
            raise RepositoryError('Ordinary verification Company checkpoint is unavailable.')
        return cycle, company_id, item

    def _enrollment(self, stores, cycle, company_id, item):
        snapshot = validate_installed_source_configuration(item.get('installed_source_configuration'))
        qualification = qualification_for_snapshot(snapshot)
        if (snapshot is None or qualification is None
                or _resolve_authoritative_installed_source_configuration(stores.jobs, company_id) != snapshot):
            raise RepositoryError('Ordinary verification requires a reviewed source qualification.')
        owner = {
            'cycle_id': self.cycle_id,
            'cycle_started_at': cycle.get('started_at'),
            'request_id': cycle.get('start_request_id'),
            'request_fingerprint': cycle.get('request_fingerprint'),
            'company_id': company_id,
            'source_revision': item.get('outcome_source_revision'),
            'company_source_sha256': pending.company_source_sha256(stores, company_id),
            'store_binding_sha256': pending.store_binding(stores),
            'observation_generation': 1,
        }
        admission = {key: snapshot[key] for key in (
            'configured_url', 'capability_id', 'capability_digest', 'mapping_digest', 'configuration_digest',
        )}
        admission.update(authority_url=snapshot['official_careers_url'],
                         matrix_digest=qualification['matrix_digest'],
                         runtime_binding_sha256=pending.digest(cycle.get('runtime_binding')))
        return owner, admission

    @staticmethod
    def _current_company(stores, company_id):
        # Enrollment has already proved that the main Company relations are
        # unshadowed. Claim/hold fields are separate from the frozen projection.
        found = stores.jobs.matches('Companies', {'Company ID': company_id})
        if len(found) != 1:
            raise RepositoryError('Ordinary verification lost its unique Company.')
        company = found[0][1]
        if (company.get('Claimed By') or company.get('Claim Token')
                or (company.get('Scan State') == 'Blocked / Manual Review'
                    and str(company.get('Automatic Retry?', '')).casefold() == 'no')):
            raise RepositoryError('Ordinary verification Company is held or has a foreign claim.')
        return company

    @staticmethod
    def _no_outcome(stores, owner):
        if existing_outcome(stores.jobs, owner) is not None:
            raise RepositoryError('The exact ordinary attempt already has an immutable outcome.')

    def assignment(self):
        """Return the one allowed fetch, or a saved handoff without another fetch."""
        with self._open_stores() as stores:
            cycle, company_id, item = self._cycle(stores)
            owner, admission = self._enrollment(stores, cycle, company_id, item)
            self._no_outcome(stores, owner)
            company = self._current_company(stores, company_id)
            marker = pending.read_marker(cycle, company_id)
            if marker is not None:
                if marker['owner'] != owner or marker['admission'] != admission:
                    raise RepositoryError('The saved ordinary verification admission changed.')
                if marker['state'] == 'PREPARED':
                    _, (_, blocked) = pending.read_prepared_inventory(stores, self.cycle_id, company_id)
                    if blocked:
                        raise RepositoryError('The saved ordinary verification inventory is blocked.')
                    return company_id, None, None
            armed = pending.arm(stores, owner, admission)
            return company_id, company, pending.dispatch_sha256(armed, company_id)

    def save(self, company_id, dispatch, payload, *, observation, failure):
        """Record only the returned inventory from this exact dispatch."""
        with self._open_stores() as stores:
            cycle, current, item = self._cycle(stores)
            if current != company_id:
                raise RepositoryError('The ordinary verification Company changed during the fetch.')
            owner, admission = self._enrollment(stores, cycle, company_id, item)
            marker = pending.read_marker(cycle, company_id)
            if marker is None or marker['owner'] != owner or marker['admission'] != admission:
                raise RepositoryError('The ordinary verification admission changed during the fetch.')
            self._no_outcome(stores, owner)
            self._current_company(stores, company_id)
            return pending.prepare_inventory(
                stores, self.cycle_id, company_id, payload, dispatch_digest=dispatch,
                observation=observation, failure=failure,
            )
