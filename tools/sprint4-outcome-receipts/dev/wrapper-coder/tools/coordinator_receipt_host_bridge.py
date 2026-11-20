"""Manual, default-off host bridge for the isolated receipt-v1 proof.

This module deliberately has no runner, service, socket, path, or scheduler
configuration.  An explicit in-process coordinator and sender repository
factory are required by the caller; the fixed transport grammar is the only
thing this bridge owns.
"""
from job_search_helper.scrape_outcome_delivery import CONSUMER, OutcomeDelivery
from job_search_helper.repository import RepositoryError


_ACTION = 'ingest-scrape-outcome-delivery-v1'


class _ReceiptV1Sink:
    """Adapt the fixed receiver command to the sender-owned delivery sink."""
    def __init__(self, coordinator):
        self._coordinator = coordinator

    def ingest_immutable(self, record):
        response = self._coordinator.command({
            'action': _ACTION, 'consumer': CONSUMER, 'record': record,
        })
        if not isinstance(response, dict) or response.get('ok') is not True:
            raise RuntimeError('Receipt-v1 coordinator did not accept the immutable record.')
        receipt = response.get('receipt')
        if not isinstance(receipt, dict):
            raise RuntimeError('Receipt-v1 coordinator did not return its exact receipt.')
        return receipt


class ManualReceiptV1HostBridge:
    """One explicit, disabled-by-default drain; it never starts work itself."""
    def __init__(self, coordinator, repository_factory, *, enabled=False):
        if type(enabled) is not bool:
            raise ValueError('Receipt-v1 bridge enabled must be a boolean.')
        if not callable(repository_factory):
            raise ValueError('Receipt-v1 bridge requires a repository factory.')
        self._coordinator = coordinator
        self._repository_factory = repository_factory
        self._enabled = enabled

    def status(self):
        return {'state': 'MANUAL_ENABLED' if self._enabled else 'DISABLED',
                'consumer': CONSUMER, 'action': _ACTION}

    def manual_drain(self, *, outcome_id=None):
        """Drain once only when explicitly enabled, optionally for one stored record."""
        if not self._enabled:
            return {**self.status(), 'results': []}
        try:
            repository = self._repository_factory()
        except (OSError, RepositoryError):
            # Opening, schema validation, or reading the local ledger is a
            # held host boundary.  Do not expose a path/driver message and do
            # not contact the receiver when source evidence is unavailable.
            return {**self.status(), 'state': 'HELD_SOURCE_STORAGE_UNAVAILABLE', 'results': []}
        # OutcomeDelivery owns receipt validation, leases, cap/backoff, stale
        # suppression, and atomic local acknowledgement.  The coordinator sees
        # only the fixed v1 action and immutable record.
        try:
            results = OutcomeDelivery(repository, _ReceiptV1Sink(self._coordinator),
                                      consumer=CONSUMER).drain(outcome_id=outcome_id)
        except (OSError, RepositoryError):
            return {**self.status(), 'state': 'HELD_SOURCE_STORAGE_UNAVAILABLE', 'results': []}
        return {**self.status(), 'results': results}


def legacy_production_drain(*_args, **_kwargs):
    """There is no compatibility fallback from receipt-v1 to direct drain."""
    raise RuntimeError('Legacy production-shaped outcome drain is forbidden; use receipt-v1.')
