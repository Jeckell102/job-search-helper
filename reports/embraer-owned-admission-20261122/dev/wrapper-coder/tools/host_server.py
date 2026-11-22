"""Authenticated loopback bridge for source-only wrapper development."""
from contextlib import closing, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from hashlib import sha256
import hmac
import json
import os
from pathlib import Path
import re
import signal
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import sqlite3
import time
import coding_tools
import public_tools
from coordinator import AMPHENOL_RECIPE_WORK_ORDER, Coordinator
from coordinator_supervision import (CoordinatorSupervision,
                                     external_retention_snapshot as retention_counts,
                                     watchdog)

BASE = Path(__file__).resolve().parent.parent
JOB_SEARCH_ROOT = BASE.parent.parent
if str(JOB_SEARCH_ROOT / 'src') not in sys.path:
    sys.path.insert(0, str(JOB_SEARCH_ROOT / 'src'))
TOKEN = (BASE / 'bridge-token').read_text().strip()
SLOTS = threading.BoundedSemaphore(4)
COORDINATOR = None
SUPERVISION = None
RECIPE_ENROLLMENT = None
SCRAPE_OUTCOME_CONSUMER = 'repair-coordinator'
_RECIPE_COMPANY = 'COMP-0490'
_RECIPE_PREPARATION = ContextVar('amphenol_recipe_preparation', default=None)
_RECIPE_TASK_CONTROLS = frozenset({
    'start', 'batch', 'prepare-held-repair', 'promote-repair', 'pilot-start',
    'pilot-stop', 'pause', 'resume', 'exclude', 'include', 'retry', 'scope-expand',
})


def host_external_retention_snapshot():
    """Count scraper/release evidence that supervision must never discard."""
    from job_search_helper.cli import job_database_path, load_environment, storage_backend
    from job_search_helper.company_events import BRIDGE_CONSUMER
    load_environment(JOB_SEARCH_ROOT / '.env')
    if storage_backend() != 'sqlite':
        raise ValueError('External retention snapshot requires local SQLite storage.')
    return retention_counts(
        job_database_path(), company_consumer=BRIDGE_CONSUMER,
        outcome_consumer=SCRAPE_OUTCOME_CONSUMER)


def supervision_thresholds(environ=None):
    """Read bounded operator-test thresholds; defaults remain production-safe."""
    environ = os.environ if environ is None else environ
    try:
        minimum_bytes = int(environ.get(
            'WRAPPER_SUPERVISION_MIN_FREE_BYTES', str(2 * 1024**3)))
        minimum_ratio = float(environ.get(
            'WRAPPER_SUPERVISION_MIN_FREE_RATIO', '0.05'))
    except (TypeError, ValueError):
        raise ValueError('Invalid coordinator supervision disk threshold') from None
    if not 0 <= minimum_bytes <= 2**63 - 1 or not 0 <= minimum_ratio <= 1:
        raise ValueError('Coordinator supervision disk threshold is out of range')
    return minimum_bytes, minimum_ratio


def build_supervision(coordinator, catch_up=None, *, recipe=None):
    """Wire the real host's zero-argument probes into maintenance supervision."""
    if catch_up is None:
        catch_up = (lambda: recipe.catch_up(coordinator)) if recipe is not None else (
            lambda: drain_scrape_outcomes(limit=20))
    minimum_bytes, minimum_ratio = supervision_thresholds()
    return CoordinatorSupervision(
        coordinator, catch_up,
        min_free_bytes=minimum_bytes, min_free_ratio=minimum_ratio,
        retention_probe=host_external_retention_snapshot)


def supervise(coordinator, supervision=None, exit_process=os._exit, interval=1):
    """Compatibility entry point for the existing host health contract."""
    if supervision is not None:
        return watchdog(coordinator, supervision, exit_process=exit_process,
                        interval=interval)
    while True:
        if not coordinator.thread.is_alive():
            exit_process(75)
            return
        time.sleep(interval)


def current_company_revision(company_id):
    """Read one local, eligible Company revision without contacting Google.

    The coordinator uses this only to reject stale promoted repairs.  Any
    missing configuration, non-local storage, or database error is a safe
    ``None`` result, which keeps the repair paused.
    """
    try:
        from job_search_helper.cli import (job_database_path, load_environment,
                                           storage_backend)
        from job_search_helper.company_events import current_company_source_revision
        from job_search_helper.sqlite_repository import SQLiteRepository
        load_environment(JOB_SEARCH_ROOT / '.env')
        if storage_backend() != 'sqlite':
            return None
        spreadsheet_id = os.environ.get('SPREADSHEET_ID', '').strip()
        if not spreadsheet_id:
            return None
        repository = SQLiteRepository(job_database_path(), spreadsheet_id, readonly=True)
        try:
            return current_company_source_revision(repository, company_id)
        finally:
            repository.close()
    except (ImportError, OSError, ValueError, sqlite3.Error):
        return None


def current_company_repair_snapshot(company_id):
    """Read one local Company profile-binding snapshot without Google access."""
    try:
        from job_search_helper.cli import (job_database_path, load_environment,
                                           storage_backend)
        from job_search_helper.company_events import current_company_repair_snapshot as snapshot
        from job_search_helper.sqlite_repository import SQLiteRepository
        load_environment(JOB_SEARCH_ROOT / '.env')
        if storage_backend() != 'sqlite':
            return None
        spreadsheet_id = os.environ.get('SPREADSHEET_ID', '').strip()
        if not spreadsheet_id:
            return None
        repository = SQLiteRepository(job_database_path(), spreadsheet_id, readonly=True)
        try:
            return snapshot(repository, company_id)
        finally:
            repository.close()
    except (ImportError, OSError, ValueError, sqlite3.Error):
        return None


def select_repair_profile(held_repair):
    """Build a task only from a reviewed profile and fresh local Company fact."""
    try:
        from coordinator_repair_profiles import select_profile
        identity = held_repair.get('outcome', {}).get('identity', {})
        company_id = identity.get('company_id')
        return select_profile(held_repair, current_company_repair_snapshot(company_id))
    except (AttributeError, ImportError, TypeError, ValueError):
        return None


@dataclass(frozen=True)
class AmphenolRecipeEnrollment:
    """Opt in one genuine Company-event request before its outcome exists."""

    request_id: str
    source_revision: str
    company_event_id: str = ''
    retry_approval = None
    activate_approved_release = False

    @classmethod
    def from_process_environment(cls, environ=None):
        environ = os.environ if environ is None else environ
        raw = environ.get('WRAPPER_AMPHENOL_RECIPE_ENROLLMENT')
        approval = environ.get('WRAPPER_AMPHENOL_RETRY_APPROVAL')
        activate = environ.get('WRAPPER_AMPHENOL_ACTIVATE_APPROVED_RELEASE')
        if activate is not None and (activate != '1' or raw is None or approval is None):
            raise ValueError('Amphenol release activation requires exact recipe enrollment and approval.')
        if raw is None:
            if approval is not None:
                raise ValueError('Amphenol retry approval requires exact recipe enrollment.')
            return None
        try:
            pairs = json.loads(raw, object_pairs_hook=tuple) if isinstance(raw, str) and len(raw) <= 400 else None
            value = dict(pairs) if isinstance(pairs, tuple) and len(pairs) == 3 else None
            if (isinstance(value, dict) and set(value) == {'company_event_id', 'request_id', 'source_revision'}
                    and all(isinstance(item, str) for item in value.values())
                    and re.fullmatch(r'CEV-[0-9a-f]{32}', value['company_event_id'])
                    and value['request_id'] == 'company-event:' + value['company_event_id']
                    and re.fullmatch(r'[0-9a-f]{64}', value['source_revision'])):
                if approval is not None:
                    from amphenol_retry_completion import RetryReleaseApproval
                    return AmphenolRetryEnrollment(
                        **value, retry_approval=RetryReleaseApproval.from_json(approval),
                        activate_approved_release=activate == '1',
                    )
                return cls(**value)
        except (ValueError, TypeError):
            pass
        raise ValueError('Invalid exact Amphenol recipe process enrollment.')

    def matches(self, identity):
        return isinstance(identity, dict) and all(identity.get(key) == value for key, value in (
            ('company_id', _RECIPE_COMPANY), ('company_event_id', self.company_event_id),
            ('request_id', self.request_id), ('source_revision', self.source_revision),
        ))

    def qualified(self, record):
        identity = record.get('identity', {})
        return (self.matches(identity)
                and set(identity) == {'company_id', 'company_event_id', 'request_id', 'source_revision',
                                      'cycle_id', 'provider', 'adapter_version'}
                and (identity['provider'], identity['adapter_version']) == ('AcquireTM', 'normal-scraper-v1')
                and (record.get('outcome'), record.get('action'), record.get('repair_category')) == (
                    'QUALIFIED_INTEGRATION_REPAIR', 'upsert_qualified_repair', 'pagination_regression'))

    @contextmanager
    def owner_scope(self):
        from job_search_helper.cli import (job_database_path, load_environment, scraper_lock_name, state_path,
                                           storage_backend, writer_lock)
        from job_search_helper.inbox import InventoryInbox
        from job_search_helper.retained_work_runner import assert_normal_lifecycle_not_held

        load_environment(JOB_SEARCH_ROOT / '.env')
        jobs, state = job_database_path(), state_path()
        root = state.parent
        if (storage_backend() != 'sqlite' or jobs != root / 'jobs.sqlite3' or state != root / 'state.db'
                or any(path.is_symlink() or not path.is_file() for path in (jobs, state, root / 'inventories.sqlite3'))):
            raise ValueError('Amphenol recipe requires the co-located application stores.')
        with writer_lock(root / scraper_lock_name()), writer_lock(root / 'writer.lock'):
            assert_normal_lifecycle_not_held(root, jobs)
            destination = InventoryInbox.destination_id(root / 'inventories.sqlite3')
            yield root, jobs, destination

    def profile(self, held):
        from acquiretm_membership_recipe import TARGET_PATH
        from job_search_helper.acquiretm import SOURCE
        from coordinator_repair_profiles import select_profile

        if (_RECIPE_PREPARATION.get() != (self, held.get('repair_key'), held.get('outcome_id'))
                or not self.qualified(held.get('outcome', {}))):
            return select_repair_profile(held)
        profile = select_profile(held, current_company_repair_snapshot(_RECIPE_COMPANY), profiles=({
            'profile_id': AMPHENOL_RECIPE_WORK_ORDER, 'company_id': _RECIPE_COMPANY,
            'provider': 'AcquireTM', 'adapter_version': 'normal-scraper-v1',
            'failure_category': 'pagination_regression', 'configured_url': SOURCE,
            'tests': ['tests/test_acquiretm.py'], 'source_targets': [TARGET_PATH], 'max_sessions': 1,
        },))
        if profile is not None:
            profile.update(mode='review', objective=f'Review the selected AcquireTM pagination witness in '
                           f'{TARGET_PATH} and run tests/test_acquiretm.py.')
        return profile

    def _read(self, root, coordinator, outcome_id, *, task_id=None):
        from amphenol_recipe_choice_input import read_owned_choice_input

        prepared = read_owned_choice_input(root, coordinator.store, outcome_id=outcome_id,
                                           enabled=True, expected_task_id=task_id)
        return prepared if prepared and self.matches(prepared['binding']) else None

    def settled(self, repository, record):
        from job_search_helper.ordinary_event_settlement import ordinary_event_outcome_settled
        return ordinary_event_outcome_settled(repository, record)

    def read_promoted(self, coordinator, state):
        from job_search_helper.repository import RepositoryError

        outcome_id = (state.get('repair_provenance') or {}).get('outcome_id')
        try:
            with self.owner_scope() as (root, _, _):
                return self._read(root, coordinator, outcome_id, task_id=state['id'])
        except (OSError, ValueError, RuntimeError, sqlite3.Error, RepositoryError):
            return None

    def build_candidate(self, coordinator, state, prepared, receipt):
        from amphenol_recipe_candidate import save_candidate

        outcome_id = prepared['binding']['outcome_id']
        with self.owner_scope() as (root, _, _):
            if (self._read(root, coordinator, outcome_id, task_id=state['id']) != prepared
                    or coordinator.store.inference_receipt(receipt['request_id']) != receipt
                    or coordinator.store.pilot_task() != state['id'] or coordinator.paused(state['id'])):
                raise ValueError('The enrolled Amphenol recipe owner changed before saving the candidate.')
            coordinator.check_deadline(state['id'])
            return save_candidate(coordinator.store.base / state['id'], coding_tools.root(), prepared, receipt)

    def catch_up(self, coordinator):
        from coordinator_receipt_host_bridge import ManualReceiptV1HostBridge
        from job_search_helper.repository import RepositoryError
        from job_search_helper.scrape_outcome_delivery import CONSUMER, OutcomeDelivery
        from job_search_helper.sqlite_repository import SQLiteRepository

        if coordinator.stop.is_set():
            return {'state': 'HELD_RECIPE_CONTROLS'}
        if not coordinator.workspace_lock.acquire(blocking=False):
            return {'state': 'HELD_WORKSPACE_BUSY'}
        try:
            with self.owner_scope() as (root, jobs, destination):
                with closing(SQLiteRepository(jobs, destination, readonly=True)) as repository:
                    selected = repository.db.execute(
                        'SELECT outcome_id,company_id,source_revision FROM scrape_outcomes WHERE request_id=? LIMIT 2',
                        (self.request_id,),
                    ).fetchall()
                    if len(selected) != 1 or selected[0][1:] != (_RECIPE_COMPANY, self.source_revision):
                        return {'state': 'HELD_EXACT_TERMINAL_OUTCOME'}
                    outcome_id = selected[0][0]
                    [row] = repository._outcome_delivery_rows(CONSUMER, outcome_id=outcome_id)
                    record, _, stale, acknowledged, _ = OutcomeDelivery(repository, None)._preflight(row)
                    if (stale or record['outcome_id'] != outcome_id or not self.qualified(record)
                            or not self.settled(repository, record)):
                        return {'state': 'HELD_EXACT_TERMINAL_OUTCOME'}
                if not acknowledged:
                    with closing(SQLiteRepository(jobs, destination)) as repository:
                        delivered = ManualReceiptV1HostBridge(
                            coordinator, lambda: repository, enabled=True).manual_drain(outcome_id=outcome_id)
                    if delivered.get('results') != [{'outcome_id': outcome_id, 'disposition': 'ACCEPTED'}]:
                        return {'state': 'HELD_EXACT_OUTCOME_DELIVERY'}
                with coordinator.control_lock:
                    if self.retry_approval is not None:
                        if coordinator.stop.is_set():
                            return {'state': 'HELD_RECIPE_CONTROLS'}
                        from amphenol_retry_completion import deliver_qualified_retry
                        terminal = deliver_qualified_retry(
                            self, coordinator, root, jobs, destination, original_outcome=outcome_id,
                        )
                        if terminal['state'] == 'RECIPE_RETRY_CONFIRMED' or not self.activate_approved_release:
                            return terminal
                        from job_search_helper.integration_release import assert_release_settled
                        active = assert_release_settled(root)
                        if (active and active['state'] == 'COMPLETE'
                                and active['release_id'] == self.retry_approval.release_id):
                            return {'state': 'HELD_RECIPE_RETRY_CONTINUATION',
                                    'release_id': self.retry_approval.release_id}
                        from amphenol_candidate_release import read_owned_candidate_release
                        candidate, manifest = self.retry_approval.read_install_inputs()
                        release = read_owned_candidate_release(
                            self, coordinator, root, outcome_id=outcome_id, candidate_root=candidate,
                            manifest=manifest,
                        )
                        if release is None:
                            return {'state': 'HELD_EXACT_APPROVED_RELEASE'}
                        generation = coordinator.store.control_generation()
                    else:
                        return self._launch(root, coordinator, outcome_id)
            # The installer takes its own scraper and writer leases in the
            # established order. Leave the application read scope before it runs.
            return self._continue_release(coordinator, root, release, generation)
        except (KeyError, OSError, TypeError, ValueError, RuntimeError, sqlite3.Error, RepositoryError):
            return {'state': 'HELD_RECIPE_BOUNDARY'}
        finally:
            coordinator.workspace_lock.release()

    def _continue_release(self, coordinator, root, release, generation):
        from amphenol_installed_verification import verify_installed_amphenol_recipe
        from job_search_helper.integration_release import dependency_manifest_digest
        from job_search_helper.qualified_release_owner import UnfinishedScrapeWork, release_and_continue_qualified

        store = coordinator.store

        def revision_if_owned(company_id):
            if coordinator.stop.is_set() or store.control_generation() != generation:
                return None
            return current_company_revision(company_id)

        with coordinator.control_lock:
            manifest = release['manifest']
            if (store.queue_enabled() or store.campaign_enabled() or store.autopilot_enabled()
                    or store.pilot_task() != release['task_id'] or store.unresolved_inferences()
                    or any(task['status'] in ('RUNNING', 'QUEUED', 'PAUSING') for task in store.all())
                    or revision_if_owned(manifest['company_id']) != manifest['source_revision']):
                return {'state': 'HELD_RECIPE_CONTROLS'}
            approval = release['approval']
            try:
                with approval.descriptor() as descriptor:
                    result = release_and_continue_qualified(
                        JOB_SEARCH_ROOT, release['candidate_root'], root / 'state.db',
                        root / 'integration-releases', manifest,
                        approval_path=approval.directory, approval_fd=descriptor,
                        owner_identity=(approval.device, approval.inode), approval_sha256=approval.receipt_sha256,
                        current_source_revision=revision_if_owned,
                        dependency_digest=lambda: dependency_manifest_digest(JOB_SEARCH_ROOT),
                        verify=verify_installed_amphenol_recipe,
                    )
            except UnfinishedScrapeWork:
                return {
                    'state': 'HELD_UNFINISHED_SCRAPE', 'release_id': manifest['release_id'],
                    'detail': 'A saved unfinished scrape blocks installation into the shared runtime.',
                }
        return {'state': 'RECIPE_RELEASE_RETRY_CHECKED', 'release': result['release'],
                'retry_state': result['retry']['state'] if result['retry'] else None}

    def _launch(self, root, coordinator, outcome_id):
        store = coordinator.store
        if (coordinator.stop.is_set() or store.queue_enabled() or store.campaign_enabled()
                or store.pilot_task() is not None or store.unresolved_inferences()
                or any(task['status'] in ('RUNNING', 'QUEUED', 'PAUSING') for task in store.all())):
            return {'state': 'HELD_RECIPE_CONTROLS'}
        prepared = self._read(root, coordinator, outcome_id)
        held = [item for item in store.held_repair_intake() if item['outcome_id'] == outcome_id]
        if (prepared is None or len(held) != 1 or held[0]['task_id'] is not None
                or held[0]['status'] != 'HELD_FOR_REPAIR_TRIAGE'):
            return {'state': 'HELD_RECIPE_OWNER'}
        repair_key = held[0]['repair_key']
        selection_token = _RECIPE_PREPARATION.set((self, repair_key, outcome_id))
        try:
            new = coordinator.command({'action': 'prepare-held-repair', 'repair_key': repair_key})
        finally:
            _RECIPE_PREPARATION.reset(selection_token)
        task_id, state = new.get('id'), new.get('state') or {}
        if (new.get('ok') is not True or new.get('profile_id') != AMPHENOL_RECIPE_WORK_ORDER
                or not task_id or state.get('status') != 'PAUSED' or state.get('phase') != 'baseline'
                or state.get('mode') != 'review' or state.get('isolated_workspace') is not True
                or state.get('max_sessions') != 1 or coordinator.stop.is_set()
                or self._read(root, coordinator, outcome_id, task_id=task_id) != prepared):
            return {'state': 'HELD_RECIPE_PREPARATION'}
        started = coordinator.command({'action': 'pilot-start', 'id': task_id})
        if started.get('ok') is not True or store.pilot_task() != task_id:
            return {'state': 'HELD_RECIPE_ACTIVATION'}
        return {'state': 'RECIPE_PILOT_QUEUED', 'outcome_id': outcome_id, 'task_id': task_id}


@dataclass(frozen=True)
class AmphenolRetryEnrollment(AmphenolRecipeEnrollment):
    retry_approval: object
    activate_approved_release: bool = False


@dataclass(frozen=True)
class OperatorAmphenolRecipeEnrollment(AmphenolRecipeEnrollment):
    """Default-off owner for one exact operator request; never releases code."""

    request_sha256: str = ''
    predecessor_outcome_id: str = ''
    predecessor_repair_key: str = ''
    predecessor_task_id: str = ''
    predecessor_task_state_sha256: str = ''
    failure_fingerprint: str = ''

    @classmethod
    def from_process_environment(cls, environ):
        raw = environ.get('WRAPPER_AMPHENOL_OPERATOR_RECIPE_ENROLLMENT')
        if raw is None:
            return None
        try:
            base = {
                'request_id': r'[A-Za-z0-9][A-Za-z0-9._:-]{2,127}',
                'request_sha256': r'[0-9a-f]{64}',
                'source_revision': r'[0-9a-f]{64}',
            }
            predecessor = {
                'predecessor_outcome_id': r'OUT-[0-9a-f]{24}',
                'predecessor_repair_key': r'[0-9a-f]{64}',
                'predecessor_task_id': r'WRAP-[0-9a-f]{10}',
                'predecessor_task_state_sha256': r'[0-9a-f]{64}',
                'failure_fingerprint': r'[0-9a-f]{64}',
            }
            pairs = json.loads(raw, object_pairs_hook=tuple) if isinstance(raw, str) and len(raw) <= 1024 else None
            if isinstance(pairs, tuple):
                value = dict(pairs)
                if len(pairs) == len(value):
                    for allowed in (base, {**base, **predecessor}):
                        if (set(value) == set(allowed)
                                and all(isinstance(value[key], str) and re.fullmatch(pattern, value[key])
                                        for key, pattern in allowed.items())):
                            return cls(**value)
        except (TypeError, ValueError):
            pass
        raise ValueError('Invalid exact operator Amphenol recipe enrollment.')

    def matches(self, identity):
        return isinstance(identity, dict) and all(identity.get(key) == value for key, value in (
            ('company_id', _RECIPE_COMPANY), ('request_id', self.request_id),
            ('source_revision', self.source_revision),
        )) and 'company_event_id' not in identity

    def qualified(self, record):
        identity = record.get('identity', {})
        return (self.matches(identity)
                and set(identity) == {'company_id', 'request_id', 'source_revision',
                                      'cycle_id', 'provider', 'adapter_version'}
                and (identity['provider'], identity['adapter_version']) == ('AcquireTM', 'normal-scraper-v1')
                and (record.get('outcome'), record.get('action'), record.get('repair_category')) == (
                    'QUALIFIED_INTEGRATION_REPAIR', 'upsert_qualified_repair', 'pagination_regression'))

    def _canonical_recipe_workspace(self):
        """Return the installed pinned recipe source, never a task checkout.

        The isolated coordinator workspace is intentionally allowed to lag the
        installed source.  This operator-only recipe may proceed only from the
        independently approved installed baseline that the compiler itself
        consumes.  Callers hold ``owner_scope`` while using this value.
        """
        from acquiretm_membership_recipe import SOURCE_SHA256, TARGET_PATH

        source = JOB_SEARCH_ROOT / TARGET_PATH
        try:
            if source.is_symlink() or not source.is_file():
                return None
            with source.open('rb') as stream:
                digest = sha256(stream.read()).hexdigest()
        except OSError:
            return None
        return JOB_SEARCH_ROOT if hmac.compare_digest(digest, SOURCE_SHA256) else None

    def _read(self, root, coordinator, outcome_id, *, task_id=None):
        from amphenol_recipe_choice_input import read_operator_owned_choice_input

        # This is reached before choice prompt preparation and pilot admission.
        # Do not let a stale isolated task checkout expose a review route.
        if self._canonical_recipe_workspace() is None:
            return None
        prepared = read_operator_owned_choice_input(
            root, coordinator.store, outcome_id=outcome_id, request_sha256=self.request_sha256,
            enabled=True, expected_task_id=task_id)
        return prepared if prepared and self.matches(prepared['binding']) else None

    def build_candidate(self, coordinator, state, prepared, receipt):
        """Compile the operator recipe from the same measured source we gated."""
        from amphenol_recipe_candidate import save_candidate

        outcome_id = prepared['binding']['outcome_id']
        with self.owner_scope() as (root, _, _):
            canonical_workspace = self._canonical_recipe_workspace()
            if (canonical_workspace is None
                    or self._read(root, coordinator, outcome_id, task_id=state['id']) != prepared
                    or coordinator.store.inference_receipt(receipt['request_id']) != receipt
                    or coordinator.store.pilot_task() != state['id'] or coordinator.paused(state['id'])):
                raise ValueError('The enrolled operator Amphenol recipe owner changed before saving the candidate.')
            coordinator.check_deadline(state['id'])
            return save_candidate(coordinator.store.base / state['id'], canonical_workspace, prepared, receipt)

    def settled(self, repository, record):
        try:
            from amphenol_recipe_choice_input import read_operator_owned_source
            source = read_operator_owned_source(
                Path(repository.path).parent, outcome_id=record['outcome_id'],
                request_sha256=self.request_sha256, source_revision=self.source_revision)
            return source is not None and source['record'] == record
        except (KeyError, OSError, TypeError, ValueError, sqlite3.Error):
            return False

    def _launch(self, root, coordinator, outcome_id):
        if self.predecessor_outcome_id:
            # catch_up has already checked the frozen operator settlement and
            # acknowledged this exact outcome within its application owner scope.
            if coordinator.stop.is_set() or self._canonical_recipe_workspace() is None:
                return {'state': 'HELD_RECIPE_CONTROLS'}
            coordinator.store.reserve_operator_repair_successor(
                predecessor_outcome_id=self.predecessor_outcome_id,
                outcome_id=outcome_id, company_id=_RECIPE_COMPANY, source_revision=self.source_revision,
                predecessor_repair_key=self.predecessor_repair_key, predecessor_task_id=self.predecessor_task_id,
                predecessor_task_state_sha256=self.predecessor_task_state_sha256,
                failure_fingerprint=self.failure_fingerprint,
            )
        return super()._launch(root, coordinator, outcome_id)


def recipe_enrollment_from_process_environment(environ=None):
    """Select exactly one default-off provenance; event and operator never mix."""
    environ = os.environ if environ is None else environ
    from embraer_operator_pilot import ENV, EmbraerOperatorEnrollment
    if environ.get(ENV) is not None:
        if any(environ.get(key) is not None for key in (
                'WRAPPER_AMPHENOL_RECIPE_ENROLLMENT', 'WRAPPER_AMPHENOL_OPERATOR_RECIPE_ENROLLMENT',
                'WRAPPER_AMPHENOL_RETRY_APPROVAL', 'WRAPPER_AMPHENOL_ACTIVATE_APPROVED_RELEASE')):
            raise ValueError('Embraer pilot enrollment cannot mix with Amphenol or release controls.')
        return EmbraerOperatorEnrollment.from_process_environment(environ)
    event = environ.get('WRAPPER_AMPHENOL_RECIPE_ENROLLMENT')
    operator = environ.get('WRAPPER_AMPHENOL_OPERATOR_RECIPE_ENROLLMENT')
    if event is not None and operator is not None:
        raise ValueError('Amphenol event and operator enrollments are mutually exclusive.')
    if operator is not None:
        if (environ.get('WRAPPER_AMPHENOL_RETRY_APPROVAL') is not None
                or environ.get('WRAPPER_AMPHENOL_ACTIVATE_APPROVED_RELEASE') is not None):
            raise ValueError('Operator Amphenol enrollment cannot authorize retry or release.')
        return OperatorAmphenolRecipeEnrollment.from_process_environment(environ)
    return AmphenolRecipeEnrollment.from_process_environment(environ)


def build_coordinator(recipe=None):
    if recipe is None:
        return Coordinator(company_revision_resolver=current_company_revision,
                           repair_profile_selector=select_repair_profile)
    if getattr(recipe, 'uses_generic_develop', False):
        return Coordinator(company_revision_resolver=current_company_revision,
                           repair_profile_selector=recipe.profile)
    coordinator = Coordinator(
        company_revision_resolver=current_company_revision, repair_profile_selector=recipe.profile,
        owned_recipe_reader=lambda state: recipe.read_promoted(coordinator, state),
        owned_recipe_builder=lambda state, prepared, receipt: recipe.build_candidate(coordinator, state, prepared, receipt),
    )
    return coordinator


def drain_scrape_outcomes(*, limit=20, outcome_id=None):
    """Deliver one preconfigured outcome through the receipt-v1 host boundary."""
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('Scrape outcome drain limit must be between 1 and 100.')
    if outcome_id is None:
        # Existing catch-up and legacy requests must never drain the backlog.
        return {'ok': True, 'state': 'HELD_EXACT_OPERATOR_SCOPE_REQUIRED', 'delivered': []}
    if not isinstance(outcome_id, str) or not re.fullmatch(r'OUT-[0-9a-f]{24}', outcome_id):
        raise ValueError('Selected outcome ID is invalid.')
    if os.environ.get('WRAPPER_SELECTED_OUTCOME_ID') != outcome_id:
        return {'ok': True, 'state': 'HELD_EXACT_OPERATOR_SCOPE_REQUIRED', 'delivered': []}
    from coordinator_receipt_host_bridge import ManualReceiptV1HostBridge
    from job_search_helper.cli import (job_database_path, load_environment, state_path,
                                       storage_backend, writer_lock)
    from job_search_helper.retained_work_runner import assert_normal_lifecycle_not_held
    from job_search_helper.sqlite_repository import SQLiteRepository
    load_environment(JOB_SEARCH_ROOT / '.env')
    if storage_backend() != 'sqlite':
        raise ValueError('Scrape outcome delivery requires local SQLite storage.')
    spreadsheet_id = os.environ.get('SPREADSHEET_ID', '').strip()
    if not spreadsheet_id:
        raise ValueError('Scrape outcome delivery requires a configured spreadsheet ID.')
    state = state_path().parent
    jobs = job_database_path()
    if jobs.parent != state:
        raise ValueError('Selected outcome delivery requires co-located SQLite state.')
    with writer_lock(state / 'writer.lock'):
        assert_normal_lifecycle_not_held(state, jobs)
        with closing(SQLiteRepository(jobs, spreadsheet_id)) as repository:
            bridge = ManualReceiptV1HostBridge(COORDINATOR, lambda: repository, enabled=True)
            return {'ok': True, **bridge.manual_drain(outcome_id=outcome_id)}


def execute_manual(name, args, names):
    """Authenticated manual requests grant only their exact shared-checkout path.

    The caller retains the existing tool-name authorization and workspace lock.
    No task scope or isolated workspace can be inherited by this compatibility path.
    """
    if coding_tools.WORKSPACE.get() is not None:
        raise ValueError('Manual edits cannot inherit a task workspace.')
    paths = [args.get('path')] if isinstance(args, dict) and name in ('code_edit', 'code_create') else []
    token = coding_tools.EDIT_SCOPE.set(paths)
    try:
        return coding_tools.execute(name, args, names)
    finally:
        coding_tools.EDIT_SCOPE.reset(token)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # Never log submitted code, tokens, or conversation content.

    def reply(self, status, value):
        data = json.dumps(value).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        self.connection.settimeout(120)
        if not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + TOKEN):
            return self.reply(403, {'ok': False, 'error': 'Unauthorized'})
        if self.path not in ('/execute', '/coordinator'):
            return self.reply(404, {'ok': False, 'error': 'Unknown endpoint'})
        if not SLOTS.acquire(blocking=False):
            return self.reply(429, {'ok': False, 'error': 'Development tools are busy'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 400000:
                raise ValueError('Invalid request size')
            body = json.loads(self.rfile.read(length))
            if self.path == '/coordinator':
                if not isinstance(body, dict):
                    raise ValueError('Invalid coordinator request.')
                if body.get('action') in {
                        'ingest-scrape-outcome', 'ingest-scrape-outcome-record', 'ingest-scrape-outcome-delivery-v1'}:
                    return self.reply(403, {'ok': False, 'error': 'Scrape outcome intake requires the local receipt bridge.'})
                if body.get('action') == 'drain-scrape-outcomes':
                    if set(body) - {'action', 'limit'}:
                        raise ValueError('Scrape outcome drain has unsupported fields.')
                    return self.reply(200, drain_scrape_outcomes(limit=body.get('limit', 20)))
                if body.get('action') == 'drain-selected-scrape-outcome':
                    if set(body) != {'action', 'outcome_id'} or not isinstance(body['outcome_id'], str):
                        raise ValueError('Selected outcome drain requires exactly one outcome ID.')
                    return self.reply(200, drain_scrape_outcomes(outcome_id=body['outcome_id']))
                if body.get('action') == 'supervision-status':
                    if set(body) != {'action'}:
                        raise ValueError('Supervision status has unsupported fields.')
                    return self.reply(200, {'ok': True, 'supervision': SUPERVISION.status()})
                if RECIPE_ENROLLMENT is not None and body.get('action') in _RECIPE_TASK_CONTROLS:
                    with COORDINATOR.control_lock:
                        result = COORDINATOR.command(body)
                    return self.reply(200, result)
                return self.reply(200, COORDINATOR.command(body))
            if not isinstance(body, dict) or set(body) != {'name', 'args', 'names'}:
                raise ValueError('Invalid request')
            names = body['names']
            if not isinstance(names, list) or any(not isinstance(n, str) or n not in coding_tools.NAMES | public_tools.NAMES for n in names):
                raise ValueError('Invalid allowed tools')
            if not isinstance(body['name'], str):
                raise ValueError('Invalid tool name')
            executor = public_tools.execute if body['name'] in public_tools.NAMES else execute_manual
            mutation = body['name'] in ('code_edit', 'code_create', 'code_commit', 'code_test')
            acquired = not mutation or COORDINATOR.workspace_lock.acquire(blocking=False)
            if not acquired:
                return self.reply(200, {'ok': False, 'error': 'A coordinator worker owns the development workspace. Pause it and wait for PAUSED before manual edits or tests.'})
            try:
                result = executor(body['name'], body['args'], set(names))
            finally:
                if mutation:
                    COORDINATOR.workspace_lock.release()
            result['workspace_location'] = 'scraper computer: Job Search Helper dev/wrapper-coder/repo'
            self.reply(200, result)
        except sqlite3.Error:
            self.reply(503, {'ok': False, 'error': 'Task database unavailable. No action was replayed; check coordinator health.'})
        except (ValueError, TypeError, OSError) as exc:
            self.reply(200 if self.path == '/coordinator' else 400,
                       {'ok': False, 'error': str(exc)[:350]})
        finally:
            SLOTS.release()


if __name__ == '__main__':
    os.umask(0o077)
    RECIPE_ENROLLMENT = recipe_enrollment_from_process_environment()
    server = ThreadingHTTPServer(('127.0.0.1', 18789), Handler)
    COORDINATOR = build_coordinator(RECIPE_ENROLLMENT)
    COORDINATOR.start()
    SUPERVISION = build_supervision(COORDINATOR, recipe=RECIPE_ENROLLMENT)
    SUPERVISION.start()

    def shutdown(signum, frame):
        SUPERVISION.shutdown('Service signal ' + str(signum))
        # HTTPServer.shutdown must run outside the serve_forever thread.
        threading.Thread(target=server.shutdown, name='coordinator-http-shutdown', daemon=True).start()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    threading.Thread(target=watchdog, args=(COORDINATOR, SUPERVISION),
                     kwargs={'exit_process': os._exit},
                     name='coordinator-supervisor', daemon=True).start()
    try:
        server.serve_forever()
    finally:
        if SUPERVISION.status() is None or SUPERVISION.status().get('state') != 'SHUTDOWN_PAUSED':
            SUPERVISION.shutdown('HTTP service stopped')
        server.server_close()
