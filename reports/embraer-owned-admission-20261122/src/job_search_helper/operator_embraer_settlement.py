"""Embraer operator partial admission and read-only proof for repair delivery."""

from contextlib import closing
import sqlite3

from .cli import PROJECT_ROOT
from .engine import State
from .integration_release import (
    RELEASE_BINDING_SCHEMA, assert_active_release_binding, assert_release_settled, source_tree_digest,
)
from .operator_amphenol_fetch import load_operator_partial
from .operator_amphenol_settlement import (
    execute_operator_partial, operator_partial_facts, read_operator_partial_settlement,
)
from .operator_partial_scope import EMBRAER
from .operator_selected_observation import _same_json_file, read_operator_selected_observation
from .ordinary_event_settlement import _has_publication_evidence
from .outcomes import classify_outcome, validate_public_outcome_record
from .repository import RepositoryError
from .scrape_outcome_delivery import OutcomeDelivery
from .sqlite_repository import SQLiteRepository
from .temporary_retry import _selected_sha


def execute_operator_embraer(admission, *, request_sha256, fetcher, remote_reader):
    return execute_operator_partial(admission, request_sha256=request_sha256, fetcher=fetcher,
                                    remote_reader=remote_reader, scope=EMBRAER)


def read_operator_embraer_source(repository, record, request_sha256):
    """Reopen the original terminal request and its exact installed defect evidence."""
    if validate_public_outcome_record(record) is None:
        return None
    identity = record['identity']
    if (set(identity) != {'company_id', 'source_revision', 'provider', 'adapter_version', 'request_id', 'cycle_id'}
            or identity['company_id'] != EMBRAER.company_id or identity['provider'] != EMBRAER.provider
            or identity['adapter_version'] != 'normal-scraper-v1'
            or record.get('outcome') != 'QUALIFIED_INTEGRATION_REPAIR'
            or record.get('repair_category') != EMBRAER.failure_category
            or not isinstance(repository, SQLiteRepository) or not repository.is_local):
        return None
    try:
        root = repository.path.parent
        if repository.path != root / 'jobs.sqlite3':
            return None
        with (closing(State(str(root / 'state.db'), readonly=True)) as state,
              closing(SQLiteRepository(repository.path, repository.spreadsheet_id, readonly=True)) as reader):
            return _read_source(reader, state, root, record, request_sha256)
    except (KeyError, OSError, TypeError, ValueError, sqlite3.Error, RepositoryError, RuntimeError):
        return None


def _read_source(repository, state, root, record, request_sha256):
    identity = record['identity']
    cycle = state.cycle(identity['cycle_id'])
    if cycle is None or cycle.get('status') != 'Complete with exceptions':
        return None
    runtime = cycle['runtime_binding']
    if runtime['source_manifest_sha256'] != source_tree_digest(PROJECT_ROOT):
        return None
    if runtime['state'] == 'COMPLETE':
        active = {key: value for key, value in runtime.items() if key != 'state'}
        assert_active_release_binding(root, {**active, 'schema': RELEASE_BINDING_SCHEMA})
    elif runtime['state'] != 'NO_RELEASE' or assert_release_settled(root) is not None:
        return None
    owner = read_operator_selected_observation(repository, state, runtime, request_sha256=request_sha256,
                                              scope=EMBRAER)
    archived = root / 'last-scan-request.json'
    company = owner['company']
    if (owner['state'] != 'ADMITTED' or owner['cycle'] != cycle or owner['source_revision'] != identity['source_revision']
            or owner['request']['request_id'] != identity['request_id']
            or archived.is_symlink() or not _same_json_file(archived, owner['request'])
            or company.get('Active Cycle ID') != identity['cycle_id'] or company.get('Scan State') != 'Partial'):
        return None

    rows = repository._outcome_delivery_rows('repair-coordinator', outcome_id=record['outcome_id'])
    if len(rows) != 1 or OutcomeDelivery(repository, None)._preflight(rows[0])[0] != record:
        return None
    settlement = read_operator_partial_settlement(repository, identity['cycle_id'], identity['request_id'], scope=EMBRAER)
    if settlement is None or settlement['outcome'] != record:
        return None
    inbox = root / 'inventories.sqlite3'
    if inbox.is_symlink() or not inbox.is_file():
        return None
    with closing(sqlite3.connect(inbox.as_uri() + '?mode=ro', uri=True)) as connection:
        if _has_publication_evidence(connection, repository, identity['cycle_id'], identity['request_id']):
            return None
    observation = load_operator_partial(owner, state, runtime, scope=EMBRAER)
    binding = {
        **{key: identity[key] for key in ('cycle_id', 'request_id', 'company_id', 'source_revision')},
        'request_sha256': request_sha256, 'request_fingerprint': owner['request_fingerprint'],
        'observation_sha256': observation['sha256'], 'provider_inventory_sha256': observation['inventory_sha256'],
    }
    if (settlement['binding'] != binding
            or record != classify_outcome(operator_partial_facts(EMBRAER, binding, observation))
            or cycle.get(EMBRAER.observation_field) != observation['sha256']
            or settlement['terminal_state_sha256'] != _selected_sha(cycle)
            or settlement['terminal_mirror_sha256'] != _selected_sha(owner['mirror'])):
        return None
    return {
        'request_id': identity['request_id'], 'outcome_id': record['outcome_id'],
        'source_revision': identity['source_revision'], 'request_sha256': request_sha256,
        'evidence_code': EMBRAER.failure_code, 'source_files': observation['binding']['source_files'],
        'observation_sha256': observation['sha256'], 'settlement_sha256': _selected_sha(settlement),
        'runtime': runtime,
    }
