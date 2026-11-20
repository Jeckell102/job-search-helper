"""Offline, source-neutral delivery of immutable M3 outcome records."""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone

from .repository import RepositoryError
from .outcomes import validate_public_outcome_record

CONSUMER = 'repair-coordinator'
SCHEMA = 'outcome-delivery-receipt-v1'
_OUTCOME_ID = re.compile(r'^OUT-[0-9a-f]{24}$')
_CONSUMER = re.compile(r'^[a-z0-9][a-z0-9._-]{0,63}$')
_SINK_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$')
_STATUSES = frozenset({
    'RECORDED_NO_REPAIR', 'SUPERSEDED_BY_REPAIRED_RETRY', 'HELD_FOR_REPAIR_TRIAGE',
    'HELD_MISSING_REPAIR_CAPABILITY', 'VALIDATED_COMPLETE', 'OBSERVED_HELD',
    'ROLLBACK_REQUIRED', 'RECONCILIATION_REQUIRED', 'HELD_TEMPORARY_RETRY_CAP',
})


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _digest(raw):
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def _stamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _valid_receipt(value, consumer, outcome_id, digest, *, stale=False):
    keys = {'schema', 'consumer', 'outcome_id', 'record_sha256', 'disposition'}
    if not stale:
        keys |= {'sink_receipt_id', 'sink_status'}
    if not isinstance(value, dict) or set(value) != keys:
        return None
    if (value.get('schema') != SCHEMA or value.get('consumer') != consumer
            or value.get('outcome_id') != outcome_id or value.get('record_sha256') != digest
            or not _OUTCOME_ID.fullmatch(outcome_id) or not _CONSUMER.fullmatch(consumer)
            or not re.fullmatch(r'[0-9a-f]{64}', digest)):
        return None
    if stale:
        return value if value.get('disposition') == 'STALE_SUPPRESSED' else None
    if (value.get('disposition') != 'ACCEPTED'
            or not isinstance(value.get('sink_receipt_id'), str)
            or not _SINK_ID.fullmatch(value['sink_receipt_id'])
            or value.get('sink_status') not in _STATUSES):
        return None
    return value


class OutcomeDelivery:
    """A disabled-by-default adapter; caller supplies only an idempotent sink."""
    def __init__(self, repository, sink, *, consumer=CONSUMER, clock=None, stamp=None):
        if not _CONSUMER.fullmatch(consumer):
            raise ValueError('Outcome delivery consumer is invalid.')
        self.repository, self.sink, self.consumer = repository, sink, consumer
        self.clock = clock or (lambda: datetime.now(timezone.utc).timestamp())
        self.stamp = stamp or _stamp

    def _preflight(self, row):
        (outcome_id, raw, outcome, _recorded, acknowledged, receipt_digest, raw_receipt,
         receipt_sha, attempt_digest, count, state, due, error) = row
        try:
            record = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise RepositoryError('Immutable outcome payload is corrupt.') from exc
        if raw != _canonical(record):
            raise RepositoryError('Immutable outcome payload is not canonical.')
        if validate_public_outcome_record(record) is None:
            raise RepositoryError('Immutable outcome payload violates public outcome grammar.')
        digest = _digest(raw)
        stale = outcome == 'STALE_OR_PAUSED'
        receipt = None
        if raw_receipt is not None:
            try:
                receipt = json.loads(raw_receipt)
            except (TypeError, ValueError) as exc:
                raise RepositoryError('Outcome delivery receipt is corrupt.') from exc
            if (raw_receipt != _canonical(receipt) or receipt_digest != digest or receipt_sha != _digest(raw_receipt)
                    or _valid_receipt(receipt, self.consumer, outcome_id, digest, stale=stale) is None):
                raise RepositoryError('Outcome delivery receipt does not match immutable evidence.')
        if bool(acknowledged) != bool(receipt):
            raise RepositoryError('Outcome delivery acknowledgement and receipt disagree.')
        if attempt_digest is not None:
            if (attempt_digest != digest or type(count) is not int or not 1 <= count <= 16
                    or state not in {'IN_FLIGHT', 'WAITING', 'HELD_RETRY_CAP'}
                    or isinstance(due, bool)
                    or (state in {'IN_FLIGHT', 'WAITING'}
                        and (not isinstance(due, (int, float)) or due != due
                             or due in {float('inf'), float('-inf')}))
                    or (state == 'HELD_RETRY_CAP') != (due is None)
                    or (state == 'IN_FLIGHT' and error is not None)
                    or (state == 'WAITING'
                        and (count >= 16 or error not in {'sink_unavailable', 'invalid_receipt'}))
                    or (state == 'HELD_RETRY_CAP'
                        and (count != 16 or error not in {'sink_unavailable', 'invalid_receipt'}))):
                raise RepositoryError('Outcome delivery attempt is corrupt.')
        if receipt is not None and attempt_digest is not None:
            raise RepositoryError('Terminal outcome delivery has forbidden attempt state.')
        if stale and attempt_digest is not None:
            raise RepositoryError('Stale outcome has forbidden delivery attempt.')
        return record, digest, stale, receipt is not None, (count, state, due)

    def drain(self, *, limit=100, outcome_id=None):
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError('Outcome delivery limit must be between 1 and 1000.')
        if outcome_id is not None and (not isinstance(outcome_id, str) or not _OUTCOME_ID.fullmatch(outcome_id)):
            raise ValueError('Selected outcome ID is invalid.')
        now = float(self.clock())
        if not math.isfinite(now):
            raise ValueError('Outcome delivery clock must be finite.')
        results = []
        scope = {'outcome_id': outcome_id} if outcome_id is not None else {}
        for row in self.repository._outcome_delivery_rows(self.consumer, **scope):
            if len(results) >= limit:
                break
            record, digest, stale, terminal, attempt = self._preflight(row)
            outcome_id = row[0]
            if terminal:
                continue
            if stale:
                receipt = {'schema': SCHEMA, 'consumer': self.consumer, 'outcome_id': outcome_id,
                           'record_sha256': digest, 'disposition': 'STALE_SUPPRESSED'}
                raw = _canonical(receipt)
                self.repository._complete_outcome_delivery(
                    self.consumer, outcome_id, digest, raw, _digest(raw), self.stamp())
                results.append({'outcome_id': outcome_id, 'disposition': 'STALE_SUPPRESSED'})
                continue
            identity = record['identity']
            if identity.get('company_event_id') or identity['request_id'].startswith('company-event:'):
                from .company_events import acknowledged_company_event_source_is_current
                if not acknowledged_company_event_source_is_current(self.repository, identity):
                    disposition = ('HELD_STALE_RETAINED_SOURCE' if identity.get('retained_reservation_sha256')
                                   else 'HELD_STALE_COMPANY_EVENT_SOURCE')
                    results.append({'outcome_id': outcome_id, 'disposition': disposition})
                    continue
            count, state, due = attempt
            if state == 'HELD_RETRY_CAP' or (state == 'WAITING' and due > now) or (state == 'IN_FLIGHT' and due > now):
                continue
            reservation = self.repository._reserve_outcome_delivery(
                self.consumer, outcome_id, digest, now, self.stamp())
            if reservation is None:
                continue
            try:
                receipt = self.sink.ingest_immutable(record)
            except Exception:
                self.repository._settle_outcome_delivery_failure(
                    self.consumer, outcome_id, digest, now, self.stamp(), 'sink_unavailable')
                results.append({'outcome_id': outcome_id,
                                'disposition': 'HELD_RETRY_CAP' if reservation['attempt_count'] == 16 else 'WAITING'})
                continue
            receipt = _valid_receipt(receipt, self.consumer, outcome_id, digest)
            if receipt is None:
                self.repository._settle_outcome_delivery_failure(
                    self.consumer, outcome_id, digest, now, self.stamp(), 'invalid_receipt')
                results.append({'outcome_id': outcome_id,
                                'disposition': 'HELD_RETRY_CAP' if reservation['attempt_count'] == 16 else 'WAITING'})
                continue
            raw = _canonical(receipt)
            self.repository._complete_outcome_delivery(
                self.consumer, outcome_id, digest, raw, _digest(raw), self.stamp(),
                expected_attempt_count=reservation['attempt_count'])
            results.append({'outcome_id': outcome_id, 'disposition': 'ACCEPTED'})
        return results
