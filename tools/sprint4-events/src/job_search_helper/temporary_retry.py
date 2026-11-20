"""Bounded, local-only delivery of one temporary scrape retry.

This adapter only writes the existing one-company request slot.  It never
starts a scraper, changes Company/Job History, or creates repair work.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from .cli import scraper_lock_name, writer_lock
from .company_events import current_company_source_revision
from .scrape_outcome_delivery import SCHEMA

CONSUMER = "temporary-scrape-retry"
MAX_RESCRAPES = 1
SELECTED_COOLDOWN_SECONDS = 300


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _stamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def is_temporary_retry_request(request):
    value = request.get("temporary_retry") if isinstance(request, dict) else None
    if not isinstance(value, dict) or request.get("mode") != "company-only":
        return False
    top = {"request_id", "mode", "company_ids", "source_revision", "start_last",
           "enqueued_at", "temporary_retry"}
    if set(request) not in (top, top | {"request_fingerprint"}) or request.get("start_last") != []:
        return False
    required = {"schema", "outcome_id", "company_id", "source_revision", "retry_index", "retry_cap"}
    if set(value) != required or value.get("schema") != "temporary-scrape-retry-v1":
        return False
    cid, revision, outcome_id = value.get("company_id"), value.get("source_revision"), value.get("outcome_id")
    valid = (isinstance(cid, str) and bool(cid) and cid == cid.strip()
            and isinstance(revision, str) and bool(revision) and revision == revision.strip()
            and isinstance(request.get("enqueued_at"), str) and bool(request["enqueued_at"].strip())
            and isinstance(outcome_id, str) and re.fullmatch(r"OUT-[0-9a-f]{24}", outcome_id) is not None
            and request.get("company_ids") == [cid]
            and request.get("source_revision") == revision
            and request.get("request_id") == "temporary-retry:" + outcome_id
            and type(value.get("retry_index")) is int and value["retry_index"] == 1
            and type(value.get("retry_cap")) is int and value["retry_cap"] == MAX_RESCRAPES)
    if valid and "request_fingerprint" in request:
        # Ordinary requested_scan adds this before Engine rechecks the same
        # request. Accept only the independently recomputed internal value.
        from .scan_request import request_fingerprint
        return request["request_fingerprint"] == request_fingerprint(request, [cid])
    return valid


class TemporaryRetrySink:
    """Idempotent sink used by ``OutcomeDelivery`` for M3 TEMPORARY only."""
    def __init__(self, repository, state_directory, *, stamp=None):
        self.repository = repository
        self.root = Path(state_directory).resolve()
        self.stamp = stamp or _stamp

    def _receipt(self, record, status):
        raw = _canonical(record)
        return {"schema": SCHEMA, "consumer": CONSUMER, "outcome_id": record["outcome_id"],
                "record_sha256": hashlib.sha256(raw.encode()).hexdigest(), "disposition": "ACCEPTED",
                "sink_receipt_id": "temporary-retry:" + record["outcome_id"], "sink_status": status}

    def ingest_immutable(self, record):
        if record.get("outcome") != "TEMPORARY":
            return self._receipt(record, "RECORDED_NO_REPAIR")
        identity = record.get("identity") or {}
        if ('retained_reservation_sha256' in identity
                or (identity.get('company_event_id') and str(identity.get('cycle_id', '')).startswith('CYC-R'))):
            raise ValueError('Retained temporary outcomes require explicit selected scheduling.')
        # A TEMPORARY result from the one allowed retry is a terminal hold,
        # not a second request and never a repair escalation.
        parent = identity.get("temporary_retry_outcome_id")
        request_id = identity.get("request_id")
        if "temporary_retry_outcome_id" in identity or (
                isinstance(request_id, str) and request_id.startswith("temporary-retry:")):
            if (not isinstance(parent, str) or re.fullmatch(r"OUT-[0-9a-f]{24}", parent) is None
                    or request_id != "temporary-retry:" + parent):
                raise ValueError("Temporary retry outcome requires exact parent lineage.")
            return self._receipt(record, "HELD_TEMPORARY_RETRY_CAP")
        cid, revision = identity.get("company_id"), identity.get("source_revision")
        if not isinstance(cid, str) or not isinstance(revision, str):
            return self._receipt(record, "OBSERVED_HELD")
        with writer_lock(self.root / scraper_lock_name()):
            if current_company_source_revision(self.repository, cid) != revision:
                return self._receipt(record, "OBSERVED_HELD")
            matches = self.repository.matches("Companies", {"Company ID": cid})
            if len(matches) != 1 or matches[0][1].get("Claimed By") or matches[0][1].get("Claim Token"):
                return self._receipt(record, "OBSERVED_HELD")
            request = {"request_id": "temporary-retry:" + record["outcome_id"], "mode": "company-only",
                       "company_ids": [cid], "source_revision": revision, "start_last": [], "enqueued_at": self.stamp(),
                       "temporary_retry": {"schema": "temporary-scrape-retry-v1", "outcome_id": record["outcome_id"],
                                           "company_id": cid, "source_revision": revision,
                                           "retry_index": 1, "retry_cap": MAX_RESCRAPES}}
            path = self.root / "next-scan.json"
            if path.exists():
                try:
                    existing = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError) as exc:
                    raise RuntimeError("request slot unreadable") from exc
                expected = dict(request, enqueued_at=existing.get("enqueued_at"))
                if not is_temporary_retry_request(existing) or existing != expected:
                    raise RuntimeError("request slot occupied")
                return self._receipt(record, "VALIDATED_COMPLETE")
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd, name = tempfile.mkstemp(prefix=".temporary-retry-", dir=self.root)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(_canonical(request)); handle.flush(); os.fsync(handle.fileno())
                os.chmod(name, 0o600); os.replace(name, path)
                directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            finally:
                if os.path.exists(name): os.unlink(name)
            if json.loads(path.read_text(encoding="utf-8")) != request:
                raise RuntimeError("request readback mismatch")
        return self._receipt(record, "VALIDATED_COMPLETE")


def _selected_sha(value):
    return hashlib.sha256(_canonical(value).encode('utf-8')).hexdigest()


def _sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class SelectedTemporaryRetrySink:
    """One explicitly selected settled retained outcome and one durable successor budget."""

    def __init__(self, reader, state_directory, *, outcome_id, request_sha256, reservation_digest, clock=None):
        self.root = Path(state_directory).resolve()
        jobs = self.root / 'jobs.sqlite3'
        if (getattr(reader, 'readonly', False) is not True or getattr(reader, 'is_local', False) is not True
                or Path(reader.path).resolve() != jobs or jobs.is_symlink() or scraper_lock_name() != 'scraper.lock'):
            raise ValueError('Selected retry requires the canonical read-only SQLite repository.')
        if (not isinstance(outcome_id, str) or not re.fullmatch(r'OUT-[0-9a-f]{24}', outcome_id)
                or any(not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value)
                       for value in (request_sha256, reservation_digest))):
            raise ValueError('Selected retry requires exact outcome and settled reservation IDs.')
        self.reader = reader
        self.outcome_id = outcome_id
        self.request_sha256 = request_sha256
        self.reservation_digest = reservation_digest
        self.directory = self.root / 'selected-temporary-retries'
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _selected(self):
        from .outcomes import validate_public_outcome_record
        from .retained_event_outcome import settled_event_request
        from .retained_operator_journal import FETCH_OUTCOME, RetainedOperatorJournal

        archived = RetainedOperatorJournal(self.root).read_archived_event(
            self.request_sha256, self.reservation_digest)
        if (archived is None or archived['settlement_evidence'].get('state') != FETCH_OUTCOME
                or archived['consumption'] != {
                    'request_sha256': self.request_sha256, 'state': 'FETCH_OUTCOME_CONSUMED'}):
            raise ValueError('Selected retry requires a consumed retained fetch outcome.')
        binding = archived['binding']
        claims = binding['claims']
        request = settled_event_request(self.root, binding, archived)
        outcome = validate_public_outcome_record(archived['settlement_evidence'].get('outcome'))
        if (outcome is None or _selected_sha(request) != self.request_sha256
                or (outcome['outcome_id'], outcome['outcome'], outcome['action']) != (
                    self.outcome_id, 'TEMPORARY', 'retry_with_bounded_backoff')):
            raise ValueError('Selected retry requires the exact durable temporary outcome.')
        identity = outcome['identity']
        event = identity.get('company_event_id')
        if (not isinstance(event, str) or not re.fullmatch(r'CEV-[0-9a-f]{32}', event)
                or claims['request_id'] != 'company-event:' + event
                or any(identity[key] != claims[key] for key in ('request_id', 'company_id', 'source_revision'))
                or request.get('company_event', {}).get('event_id') != event
                or identity.get('retained_reservation_sha256') != self.reservation_digest
                or 'temporary_retry_outcome_id' in identity):
            raise ValueError('Selected retry is outside original Company-event lineage.')
        rows = self.reader.db.execute(
            'SELECT outcome_id,request_id,company_id,source_revision,outcome,action,payload '
            'FROM scrape_outcomes WHERE request_id=? OR outcome_id=?',
            (claims['request_id'], self.outcome_id),
        ).fetchall()
        expected = (self.outcome_id, claims['request_id'], claims['company_id'], claims['source_revision'],
                    outcome['outcome'], outcome['action'], _canonical(outcome))
        if rows != [expected]:
            raise ValueError('Selected retry requires the exact durable temporary outcome.')
        key = {'outcome_id': self.outcome_id, 'outcome_sha256': _selected_sha(outcome),
               'request_sha256': self.request_sha256, 'reservation_digest': self.reservation_digest}
        return outcome, self.directory / (event + '.json'), key

    def _now(self):
        stamp = self.clock()
        if not isinstance(stamp, datetime) or stamp.utcoffset() is None:
            raise ValueError('Selected retry requires an aware clock.')
        return stamp.astimezone(timezone.utc)

    def _current(self, identity):
        from .retained_event_outcome import retained_outcome_source_is_current

        matches = self.reader.matches('Companies', {'Company ID': identity['company_id']})
        return (len(matches) == 1 and retained_outcome_source_is_current(self.reader, identity)
                and str(matches[0][1].get('Company Status') or '').strip().casefold() == 'active'
                and not any(str(matches[0][1].get(field) or '').strip() for field in (
                    'Claimed By', 'Claim Token', 'Active Cycle ID')))

    def _read(self, path, key):
        try:
            attrs = self.directory.lstat()
        except FileNotFoundError:
            return None
        if (not stat.S_ISDIR(attrs.st_mode) or stat.S_IMODE(attrs.st_mode) != 0o700
                or attrs.st_uid != os.geteuid()):
            raise ValueError('Selected retry ledger directory is unsafe.')
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            return None
        with os.fdopen(fd, 'r', encoding='utf-8') as stream:
            attrs = os.fstat(stream.fileno())
            if (not stat.S_ISREG(attrs.st_mode) or stat.S_IMODE(attrs.st_mode) != 0o600
                    or attrs.st_uid != os.geteuid() or attrs.st_nlink != 1):
                raise ValueError('Selected retry ledger record is unsafe.')
            raw = stream.read()
        record = json.loads(raw)
        if (not isinstance(record, dict) or set(record) != {'key', 'state', 'scheduled_at', 'sha256'}
                or record['key'] != key or record['state'] not in ('SCHEDULED', 'CLAIMED')
                or _canonical(record) + '\n' != raw
                or _selected_sha({field: value for field, value in record.items() if field != 'sha256'})
                != record['sha256']):
            raise ValueError('Selected retry already has conflicting durable budget evidence.')
        from .scan_request import _timestamp
        _timestamp(record['scheduled_at'], 'Selected retry scheduled time')
        return record

    def _write(self, path, key, stamp, state):
        self.directory.mkdir(mode=0o700, exist_ok=True)
        _sync_directory(self.root)
        record = {'key': key, 'state': state, 'scheduled_at': stamp}
        fd, temporary = tempfile.mkstemp(dir=self.directory, prefix='.selected-')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                stream.write(_canonical({**record, 'sha256': _selected_sha(record)}) + '\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            _sync_directory(self.directory)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def ingest_immutable(self, record):
        """Schedule the selected outcome only; a repeated transport ACK is identical."""
        with writer_lock(self.root / 'scraper.lock'), writer_lock(self.root / 'writer.lock'):
            return self._ingest_immutable_locked(record)

    def _ingest_immutable_locked(self, record):
        """Schedule under the inherited normal scraper and writer admission."""
        outcome, path, key = self._selected()
        if record != outcome:
            raise ValueError('Transport record does not match the selected durable outcome.')
        prior = self._read(path, key)
        if prior is None:
            from .retained_event_outcome import retained_event_outcome_facts
            _facts, verified = retained_event_outcome_facts(self.reader, self.request_sha256, self.reservation_digest)
            if verified != outcome:
                raise ValueError('Selected retry requires the exact durable temporary outcome.')
            if not self._current(outcome['identity']):
                raise ValueError('Selected retry Company source changed before scheduling.')
            self._write(path, key, self._now().isoformat(), 'SCHEDULED')
        # Retry a lost directory fsync before acknowledging either path.
        _sync_directory(self.root)
        _sync_directory(self.directory)
        return {'schema': SCHEMA, 'consumer': CONSUMER, 'outcome_id': self.outcome_id,
                'record_sha256': key['outcome_sha256'], 'disposition': 'ACCEPTED',
                'sink_receipt_id': 'temporary-retry:' + self.outcome_id, 'sink_status': 'OBSERVED_HELD'}


    def claim_dispatch_locked(self, state):
        """Claim one in-memory normal-start request under the caller's scraper and writer locks.

        The caller keeps ownership through ordinary admission and must not
        publish this request to an asynchronously consumed slot. A claimed
        attempt with an uncertain launch stays spent for reconciliation.
        """
        from .integration_release import assert_release_settled
        from .retained_work_runner import assert_normal_lifecycle_not_held
        from .scan_request import _timestamp, _unfinished_cycle_ids

        state_path = self.root / 'state.db'
        if (getattr(state, 'readonly', False) is not True or Path(state.path).resolve() != state_path
                or state_path.is_symlink()):
            raise ValueError('Selected retry dispatch requires the canonical read-only State database.')
        outcome, path, key = self._selected()
        entry = self._read(path, key)
        request_id = 'temporary-retry:' + self.outcome_id
        if entry is None:
            return {'state': 'HELD_NOT_SCHEDULED', 'request_id': request_id}
        if entry['state'] == 'CLAIMED':
            return {'state': 'HELD_SUCCESSOR_ALREADY_CLAIMED', 'request_id': request_id}
        blockers = sorted(_unfinished_cycle_ids(SimpleNamespace(repo=self.reader), state))
        if blockers:
            return {'state': 'HELD_UNFINISHED_CYCLE', 'request_id': request_id, 'blocking_cycle_ids': blockers}
        due = _timestamp(entry['scheduled_at'], 'Selected retry scheduled time') + timedelta(seconds=SELECTED_COOLDOWN_SECONDS)
        if self._now() < due:
            return {'state': 'HELD_COOLDOWN', 'request_id': request_id, 'not_before': due.isoformat()}
        if os.path.lexists(self.root / 'next-scan.json'):
            return {'state': 'HELD_REQUEST_SLOT', 'request_id': request_id}
        identity = outcome['identity']
        if not self._current(identity):
            return {'state': 'HELD_SOURCE_CHANGED', 'request_id': request_id}
        assert_normal_lifecycle_not_held(self.root, self.reader.path)
        assert_release_settled(self.root)
        cid, revision = identity['company_id'], identity['source_revision']
        request = {'request_id': request_id, 'mode': 'company-only', 'company_ids': [cid],
                   'source_revision': revision, 'start_last': [], 'enqueued_at': entry['scheduled_at'],
                   'temporary_retry': {'schema': 'temporary-scrape-retry-v1', 'outcome_id': self.outcome_id,
                                       'company_id': cid, 'source_revision': revision,
                                       'retry_index': 1, 'retry_cap': MAX_RESCRAPES}}
        self._write(path, key, entry['scheduled_at'], 'CLAIMED')
        return {'state': 'SUCCESSOR_CLAIMED', 'request_id': request_id, 'request': request}
