"""One default-off, receipt-owned Embraer development pilot; never a release."""
from contextlib import closing, contextmanager, nullcontext
from contextvars import ContextVar
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sqlite3
from types import SimpleNamespace

import coding_tools
from coordinator_identity import validate_bound_identity
from coordinator_repair_profiles import select_profile
from coordinator_store import Store
from coordinator_baseline import binding, files
from coordinator_workspace import BATCH_SOURCE_OVERRIDE
from job_search_helper.scrape_outcome_delivery import CONSUMER, OutcomeDelivery
from job_search_helper.sqlite_repository import SQLiteRepository


ENV = 'WRAPPER_EMBRAER_OPERATOR_PILOT_ENROLLMENT'
COMPANY_ID = 'COMP-0634'
SOURCE = 'https://www.embraer.com/careers/'
CODE = 'breezy_embraer_brand_heading'
PROFILE = 'breezy-embraer-brand-heading-v1'
TARGET = 'src/job_search_helper/shared_boards.py'
DISPATCHER = 'src/job_search_helper/ats.py'
_PREPARATION = ContextVar('embraer_pilot_preparation', default=None)
_FIELDS = {'request_id', 'source_revision', 'request_sha256', 'shared_boards_sha256', 'ats_sha256', 'baseline_sha256'}
_SUCCESSOR_FIELDS = {'outcome_id', 'predecessor_outcome_id', 'predecessor_repair_key',
                     'predecessor_task_id', 'predecessor_task_state_sha256', 'failure_fingerprint'}


@dataclass(frozen=True)
class EmbraerSuccessorAuthorization:
    """Opt-in pins for one fresh acknowledged operator outcome."""
    outcome_id: str
    predecessor_outcome_id: str
    predecessor_repair_key: str
    predecessor_task_id: str
    predecessor_task_state_sha256: str
    failure_fingerprint: str

    def valid(self):
        return (isinstance(self.outcome_id, str) and re.fullmatch(r'OUT-[0-9a-f]{24}', self.outcome_id)
                and all(isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value)
                    for value in (self.predecessor_repair_key, self.predecessor_task_state_sha256,
                                  self.failure_fingerprint))
                and isinstance(self.predecessor_outcome_id, str)
                and re.fullmatch(r'OUT-[0-9a-f]{24}', self.predecessor_outcome_id)
                and isinstance(self.predecessor_task_id, str)
                and re.fullmatch(r'WRAP-[0-9a-f]{10}', self.predecessor_task_id))


@dataclass(frozen=True)
class EmbraerOperatorEnrollment:
    request_id: str
    source_revision: str
    request_sha256: str
    shared_boards_sha256: str
    ats_sha256: str
    baseline_sha256: str
    successor: EmbraerSuccessorAuthorization | None = None
    uses_generic_develop = True

    @classmethod
    def from_process_environment(cls, environ=None):
        raw = (os.environ if environ is None else environ).get(ENV)
        if raw is None:
            return None
        try:
            pairs = json.loads(raw, object_pairs_hook=tuple) if isinstance(raw, str) and len(raw) <= 1600 else None
            value = (dict(pairs) if isinstance(pairs, tuple) and len(pairs) == len(dict(pairs))
                     and set(dict(pairs)) in (_FIELDS, _FIELDS | {'successor'}) else None)
            successor = None
            if isinstance(value, dict) and 'successor' in value:
                successor_pairs = value.pop('successor')
                successor_value = (dict(successor_pairs) if isinstance(successor_pairs, tuple)
                                   and len(successor_pairs) == len(dict(successor_pairs)) else None)
                if not isinstance(successor_value, dict) or set(successor_value) != _SUCCESSOR_FIELDS:
                    raise ValueError('Invalid exact Embraer successor owner.')
                successor = EmbraerSuccessorAuthorization(**successor_value)
                if not successor.valid():
                    raise ValueError('Invalid exact Embraer successor owner.')
            if (isinstance(value, dict) and set(value) == _FIELDS
                    and all(isinstance(v, str) for v in value.values())
                    and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{2,127}', value['request_id'])
                    and not value['request_id'].startswith(('company-event:', 'temporary-retry:', 'repair-retry:'))
                    and all(re.fullmatch(r'[0-9a-f]{64}', value[k]) for k in _FIELDS - {'request_id'})):
                return cls(**value, successor=successor)
        except (TypeError, ValueError):
            pass
        raise ValueError('Invalid exact Embraer operator pilot enrollment.')

    @property
    def source_files(self):
        return {TARGET: self.shared_boards_sha256, DISPATCHER: self.ats_sha256}

    def qualified(self, record):
        identity = record.get('identity', {})
        return (set(identity) == {'company_id', 'request_id', 'source_revision', 'cycle_id', 'provider', 'adapter_version'}
                and identity == {**identity, 'company_id': COMPANY_ID, 'request_id': self.request_id,
                                 'source_revision': self.source_revision, 'provider': 'Breezy HR',
                                 'adapter_version': 'normal-scraper-v1'}
                and (record.get('outcome'), record.get('action'), record.get('repair_category')) == (
                    'QUALIFIED_INTEGRATION_REPAIR', 'upsert_qualified_repair', 'full_description_regression'))

    @contextmanager
    def owner_scope(self):
        from job_search_helper.cli import (job_database_path, load_environment, scraper_lock_name,
                                          state_path, storage_backend, writer_lock)
        from job_search_helper.inbox import InventoryInbox
        from job_search_helper.retained_work_runner import assert_normal_lifecycle_not_held

        project = Path(__file__).resolve().parents[3]
        load_environment(project / '.env')
        jobs, state = job_database_path(), state_path()
        root = state.parent
        if (storage_backend() != 'sqlite' or jobs != root / 'jobs.sqlite3' or state != root / 'state.db'
                or any(p.is_symlink() or not p.is_file() for p in (jobs, state, root / 'inventories.sqlite3'))):
            raise ValueError('Embraer pilot requires canonical local application stores.')
        with writer_lock(root / scraper_lock_name()), writer_lock(root / 'writer.lock'):
            assert_normal_lifecycle_not_held(root, jobs)
            yield project, jobs, InventoryInbox.destination_id(root / 'inventories.sqlite3')

    def _sources_match(self, project):
        from job_search_helper.integration_release import source_tree_digest

        baseline = self.baseline_path
        if (baseline.resolve() != baseline.absolute() or not baseline.is_dir()
                or binding(files(baseline))['digest'] != self.baseline_sha256
                or source_tree_digest(project) != source_tree_digest(baseline)):
            return False
        for base in (Path(project), baseline):
            for name, expected in self.source_files.items():
                path = base / name
                if (path.resolve() != path.absolute() or not path.is_file()
                        or sha256(path.read_bytes()).hexdigest() != expected):
                    return False
        return True

    @property
    def baseline_path(self):
        return coding_tools.BASE / 'pilot-bases' / ('embraer-' + self.baseline_sha256)

    @contextmanager
    def _pilot_source(self, project):
        if not self._sources_match(project):
            raise ValueError('Embraer pilot baseline changed.')
        source_token = BATCH_SOURCE_OVERRIDE.set(self.baseline_path)
        workspace_token = coding_tools.WORKSPACE.set(self.baseline_path)
        try:
            yield
        finally:
            coding_tools.WORKSPACE.reset(workspace_token)
            BATCH_SOURCE_OVERRIDE.reset(source_token)

    def _source(self, jobs, destination):
        from job_search_helper.company_events import current_company_repair_snapshot
        from job_search_helper.operator_embraer_settlement import read_operator_embraer_source

        with closing(SQLiteRepository(jobs, destination, readonly=True)) as repository:
            selected = repository.db.execute(
                'SELECT outcome_id FROM scrape_outcomes WHERE request_id=? LIMIT 2', (self.request_id,)).fetchall()
            if len(selected) != 1:
                return None
            [row] = repository._outcome_delivery_rows(CONSUMER, outcome_id=selected[0][0])
            record, digest, stale, acknowledged, _ = OutcomeDelivery(repository, None)._preflight(row)
            if stale or not self.qualified(record):
                return None
            proof = read_operator_embraer_source(repository, record, self.request_sha256)
            company = current_company_repair_snapshot(repository, COMPANY_ID)
            if (not isinstance(proof, dict) or proof.get('source_files') != self.source_files
                    or proof.get('evidence_code') != CODE
                    or company != {'company_id': COMPANY_ID, 'source_revision': self.source_revision,
                                   'company': 'Embraer', 'official_careers_url': SOURCE, 'ats_source': 'breezy hr'}):
                return None
            return dict(row=row, record=record, digest=digest, acknowledged=acknowledged,
                        proof=proof, company=company)

    def _paired(self, store, source, *, exact_repair_key=None):
        """Read receiver receipt, exact intake, and promoted task in one snapshot."""
        record, digest = source['record'], source['digest']
        if not source['acknowledged'] or Path(store.path).is_symlink() or not Path(store.path).is_file():
            return None
        with closing(sqlite3.connect(Path(store.path).resolve().as_uri() + '?mode=ro', uri=True)) as db:
            db.execute('BEGIN')
            receipt_row = db.execute('SELECT record_sha256,receipt_id,receipt,receipt_sha256,sink_status '
                                    'FROM scrape_outcome_delivery_receipts WHERE consumer=? AND outcome_id=?',
                                    (CONSUMER, record['outcome_id'])).fetchone()
            intake = db.execute('SELECT company_id,source_revision,outcome,payload FROM scrape_outcome_intake '
                                'WHERE outcome_id=?', (record['outcome_id'],)).fetchone()
            if receipt_row is None or intake is None:
                return None
            Store._validate_delivery_intake(intake, canonical=record, record_sha256=digest,
                legacy_text=json.dumps(record, sort_keys=True, separators=(',', ':')))
            receipt = Store._validate_delivery_receipt(receipt_row, consumer=CONSUMER,
                                                       canonical=record, record_sha256=digest)
            if receipt != json.loads(source['row'][6]) or receipt['sink_status'] != 'HELD_FOR_REPAIR_TRIAGE':
                return None
            view = SimpleNamespace(connect=lambda: nullcontext(db))
            held = [v for v in Store.held_repair_intake(view)
                    if v['outcome_id'] == record['outcome_id']
                    and (exact_repair_key is None or v['repair_key'] == exact_repair_key)]
            if len(held) != 1 or held[0]['evidence_outcome_ids'] != [record['outcome_id']]:
                return None
            held = held[0]
            task = None
            if held['task_id'] is not None:
                row = db.execute('SELECT state FROM tasks WHERE id=?', (held['task_id'],)).fetchone()
                if row is None:
                    return None
                task = json.loads(row[0])
            return held, task

    def _successor_pair(self, store, source):
        """Find or reserve the one receipt-owned successor while the control lock is held."""
        authorization = self.successor
        if authorization is None:
            return self._paired(store, source), None
        record = source['record']
        if (source.get('acknowledged') is not True
                or record.get('outcome_id') != authorization.outcome_id
                or record.get('outcome_id') == authorization.predecessor_outcome_id
                or record.get('failure_fingerprint') != authorization.failure_fingerprint):
            return None, 'HELD_EMBRAER_SUCCESSOR_OWNER'
        repair_key = store._operator_successor_repair_key(authorization.predecessor_repair_key)
        paired = self._paired(store, source, exact_repair_key=repair_key)
        if paired is not None:
            return paired, None
        try:
            store.reserve_operator_repair_successor(
                predecessor_outcome_id=authorization.predecessor_outcome_id,
                outcome_id=record['outcome_id'], source_revision=self.source_revision,
                predecessor_repair_key=authorization.predecessor_repair_key,
                predecessor_task_id=authorization.predecessor_task_id,
                predecessor_task_state_sha256=authorization.predecessor_task_state_sha256,
                company_id=COMPANY_ID, failure_fingerprint=authorization.failure_fingerprint)
        except (KeyError, TypeError, ValueError):
            return None, 'HELD_EMBRAER_SUCCESSOR_OWNER'
        paired = self._paired(store, source, exact_repair_key=repair_key)
        return (paired, None) if paired is not None else (None, 'HELD_EMBRAER_RECEIPTS')

    def _proposal(self, held, company):
        proposal = select_profile(held, company, profiles=({
            'profile_id': PROFILE, 'company_id': COMPANY_ID, 'provider': 'Breezy HR',
            'adapter_version': 'normal-scraper-v1', 'failure_category': 'full_description_regression',
            'configured_url': SOURCE, 'tests': ['tests/test_shared_boards.py', 'tests/test_embraer_typed_defect.py'],
            'source_targets': [TARGET], 'max_sessions': 8,
        },))
        if proposal is not None:
            proposal['objective'] += (
                ' For this exact Embraer Breezy board, inspect the typed brand-heading defect fixture. '
                'Distinguish the employer brand heading from the job banner title while preserving '
                'canonical posting URL, exact listing identity, and full description checks. '
                'Verify the focused regression and shared-board compatibility tests.')
        return proposal

    def profile(self, held):
        selected = _PREPARATION.get()
        if selected is None or selected[:3] != (self, held.get('repair_key'), held.get('outcome_id')):
            return None
        return selected[3]

    def _task_matches(self, held, task, proposal):
        if (not isinstance(task, dict) or not task.get('integration_identity_digest')
                or task.get('integration') != proposal['integration']):
            return False
        validate_bound_identity(task)
        return (held['status'] == 'PROMOTED_PAUSED' and held['task_id'] == task.get('id')
                and task.get('isolated_workspace') is True and task.get('mode') == 'develop'
                and task.get('max_sessions') == 8 and task.get('held_repair_key') == held['repair_key']
                and task.get('assignment_baseline') == binding(files(self.baseline_path))
                and task['assignment_baseline']['digest'] == self.baseline_sha256
                and task.get('repair_provenance') == {'repair_key': held['repair_key'],
                    'outcome_id': held['outcome_id'], 'company_id': COMPANY_ID,
                    'source_revision': self.source_revision})

    def _never_activated(self, store, task):
        """Only the original durable promotion can recover its first launch."""
        if (task.get('status') != 'PAUSED' or task.get('phase') != 'baseline'
                or task.get('reason') != 'Promoted from held repair; explicit resume and review are required.'
                or task.get('stop_requested') is not True or task.get('activated_at') is not None
                or task.get('workflow_version') != 2 or task.get('authorization_version') != 1
                or task.get('manifest') != {} or task.get('checkpoint') != {}
                or any(task.get(key) != 0 for key in ('sessions', 'calls', 'tokens', 'errors', 'no_progress', 'phase_start'))):
            return False
        with closing(sqlite3.connect(Path(store.path).resolve().as_uri() + '?mode=ro', uri=True)) as db:
            db.execute('BEGIN')
            row = db.execute('SELECT state FROM tasks WHERE id=?', (task['id'],)).fetchone()
            return (row is not None and json.loads(row[0]) == task
                    and not db.execute('SELECT 1 FROM receipts WHERE task=? LIMIT 1', (task['id'],)).fetchone()
                    and not db.execute('SELECT 1 FROM inference_receipts WHERE task=? LIMIT 1', (task['id'],)).fetchone())

    def catch_up(self, coordinator):
        from coordinator_receipt_host_bridge import ManualReceiptV1HostBridge
        from job_search_helper.repository import RepositoryError

        if coordinator.stop.is_set():
            return {'state': 'HELD_EMBRAER_CONTROLS'}
        if not coordinator.workspace_lock.acquire(blocking=False):
            return {'state': 'HELD_WORKSPACE_BUSY'}
        try:
            with self.owner_scope() as (project, jobs, destination):
                if not self._sources_match(project):
                    return {'state': 'HELD_EMBRAER_SOURCE_BASELINE'}
                source = self._source(jobs, destination)
                if source is None:
                    return {'state': 'HELD_EMBRAER_OWNER'}
                outcome_id = source['record']['outcome_id']
                if not source['acknowledged']:
                    with closing(SQLiteRepository(jobs, destination)) as repository:
                        result = ManualReceiptV1HostBridge(coordinator, lambda: repository,
                                                         enabled=True).manual_drain(outcome_id=outcome_id)
                    if result.get('results') != [{'outcome_id': outcome_id, 'disposition': 'ACCEPTED'}]:
                        return {'state': 'HELD_EMBRAER_DELIVERY'}
                with coordinator.control_lock:
                    fresh = self._source(jobs, destination)
                    if (fresh is None or fresh['record'] != source['record'] or fresh['proof'] != source['proof']
                            or not self._sources_match(project)):
                        return {'state': 'HELD_EMBRAER_OWNER'}
                    paired, successor_hold = self._successor_pair(coordinator.store, fresh)
                    if successor_hold is not None:
                        return {'state': successor_hold}
                    if paired is None:
                        return {'state': 'HELD_EMBRAER_RECEIPTS'}
                    held, task = paired
                    proposal = self._proposal(held, fresh['company'])
                    if proposal is None:
                        return {'state': 'HELD_EMBRAER_PROFILE'}
                    if task is not None:
                        if not self._task_matches(held, task, proposal):
                            return {'state': 'HELD_EMBRAER_TASK'}
                        if not self._never_activated(coordinator.store, task):
                            return {'state': 'EMBRAER_PILOT_ALREADY_PREPARED', 'outcome_id': outcome_id, 'task_id': task['id']}
                    store = coordinator.store
                    if (held['status'] != ('PROMOTED_PAUSED' if task is not None else 'HELD_FOR_REPAIR_TRIAGE')
                            or coordinator.stop.is_set()
                            or store.queue_enabled() or store.campaign_enabled() or store.autopilot_enabled()
                            or store.pilot_task() is not None or store.unresolved_inferences()
                            or any(t['status'] in ('RUNNING', 'QUEUED', 'PAUSING') for t in store.all())):
                        return {'state': 'HELD_EMBRAER_CONTROLS'}
                    generation = store.control_generation()
                    if task is None:
                        token = _PREPARATION.set((self, held['repair_key'], outcome_id, proposal))
                        try:
                            with self._pilot_source(project):
                                prepared = coordinator.command({'action': 'prepare-held-repair', 'repair_key': held['repair_key']})
                        finally:
                            _PREPARATION.reset(token)
                    else:
                        prepared = {'ok': True, 'profile_id': PROFILE}
                    fresh = self._source(jobs, destination)
                    successor_key = (store._operator_successor_repair_key(self.successor.predecessor_repair_key)
                                     if self.successor is not None else None)
                    paired = (self._paired(store, fresh, exact_repair_key=successor_key)
                              if fresh else None)
                    if (not paired or prepared.get('ok') is not True or prepared.get('profile_id') != PROFILE
                            or fresh['proof'] != source['proof'] or not self._sources_match(project)
                            or coordinator.stop.is_set() or store.control_generation() != generation
                            or not self._task_matches(*paired, proposal)
                            or not self._never_activated(store, paired[1])):
                        return {'state': 'HELD_EMBRAER_PREPARATION'}
                    task_id = paired[1]['id']
                    with self._pilot_source(project):
                        started = coordinator.command({'action': 'pilot-start', 'id': task_id})
                    if started.get('ok') is not True or store.pilot_task() != task_id:
                        return {'state': 'HELD_EMBRAER_ACTIVATION'}
                    return {'state': 'EMBRAER_PILOT_QUEUED', 'outcome_id': outcome_id, 'task_id': task_id}
        except (AttributeError, ImportError, KeyError, OSError, TypeError, ValueError, RuntimeError,
                sqlite3.Error, RepositoryError):
            return {'state': 'HELD_EMBRAER_BOUNDARY'}
        finally:
            coordinator.workspace_lock.release()
