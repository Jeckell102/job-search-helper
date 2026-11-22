"""Complete one locally observed operator partial before exposing repair authority."""

from contextlib import ExitStack, closing
import json
from pathlib import Path

from . import cli
from .engine import State, now
from .integration_release import assert_release_settled
from .ordinary_company_event_command import _open_engine, _open_readers
from .ordinary_event_settlement import _mirror_values, _outcome_rows, _require_no_publication, _terminal
from .operator_amphenol_fetch import load_operator_partial, observe_operator_partial
from .operator_partial_scope import AMPHENOL, require_operator_partial_scope
from .operator_selected_observation import _same_json_file, read_operator_selected_observation
from .outcomes import classify_outcome
from .retained_work_runner import assert_normal_lifecycle_not_held
from .scan_request import _cycle_views, _unfinished_from_views, requested_scan
from .sqlite_repository import SQLiteRepository
from .temporary_retry import _canonical, _selected_sha, _sync_directory


SCHEMA = AMPHENOL.settlement_schema
COMPANY_ID = AMPHENOL.company_id


def execute_operator_amphenol(admission, *, request_sha256, fetcher, remote_reader):
    return execute_operator_partial(admission, request_sha256=request_sha256, fetcher=fetcher,
                                    remote_reader=remote_reader, scope=AMPHENOL)


def execute_operator_partial(admission, *, request_sha256, fetcher, remote_reader, scope):
    """Observe and settle one exact operator request under inherited scraper admission."""
    require_operator_partial_scope(scope)
    database, jobs, runtime = admission
    root = database.parent
    with cli.writer_lock(root / 'writer.lock'), ExitStack() as readers:
        assert_release_settled(root)
        assert_normal_lifecycle_not_held(root, jobs)
        reader, state = _open_readers(readers, database, jobs, root / 'inventories.sqlite3')
        owner = read_operator_selected_observation(reader, state, runtime,
                                                  request_sha256=request_sha256, settlement_recovery=True, scope=scope)
        pending = _same_json_file(root / 'next-scan.json', owner['request'])
        if owner['state'] == 'QUEUED':
            observed = observe_operator_partial(reader, state, runtime, request_sha256=request_sha256,
                                                fetcher=fetcher, remote_reader=remote_reader, scope=scope)
            if observed['state'] != 'QUALIFIED_PARTIAL_FROZEN':
                return observed
        elif _unfinished_from_views(*_cycle_views(reader, state)) - {owner['cycle']['id']}:
            raise ValueError('Operator partial settlement is blocked by another unfinished cycle.')
        elif pending:
            if owner['cycle']['status'] != 'In Progress' or owner['mirror']['Cycle Status'] != 'In Progress':
                raise ValueError('The pending operator acknowledgement conflicts with terminal work.')
            load_operator_partial(owner, state, runtime, scope=scope)
        with ExitStack() as writers:
            engine = _open_engine(writers, database, jobs, reader.spreadsheet_id, runtime, publication=True)
            if pending:
                cycle_id = requested_scan(engine, engine.state, database)
                cycle = engine.state.cycle(cycle_id) if cycle_id else None
                if (not cycle or cycle.get('request_fingerprint') != owner['request_fingerprint']
                        or ('cycle' in owner and owner['cycle']['id'] != cycle_id)):
                    raise ValueError('Normal admission did not create the exact operator cycle.')
            return settle_operator_partial(engine, request_sha256=request_sha256, scope=scope)


def read_operator_amphenol_settlement(repository, cycle_id, request_id):
    return read_operator_partial_settlement(repository, cycle_id, request_id, scope=AMPHENOL)


def read_operator_partial_settlement(repository, cycle_id, request_id, *, scope):
    require_operator_partial_scope(scope)
    table = scope.settlement_table
    if repository.db.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone() is None:
        return None
    rows = repository.db.execute(
        f'SELECT cycle,request_id,sha256,payload FROM {table} WHERE cycle=? OR request_id=?',
        (cycle_id, request_id),
    ).fetchall()
    if not rows:
        return None
    record = json.loads(rows[0][3])
    if (not isinstance(record, dict) or set(record) != {
            'schema', 'binding', 'outcome', 'recorded_at', 'before_state_sha256',
            'terminal_state_sha256', 'terminal_mirror_sha256',
        } or record['schema'] != scope.settlement_schema
            or rows != [(cycle_id, request_id, _selected_sha(record), _canonical(record))]):
        raise ValueError('Operator partial settlement has conflicting durable records.')
    return record


def operator_partial_facts(scope, binding, observation):
    facts = {key: binding[key] for key in ('request_id', 'company_id', 'source_revision', 'cycle_id')}
    facts.update({'source_current': True, 'company_status': 'Active', 'provider': scope.provider,
                  'adapter_version': 'normal-scraper-v1', 'storage_status': 'not_attempted',
                  'inventory_status': 'partial', 'zero_openings_verified': False, 'capability': 'qualified',
                  'failure': {'category': scope.failure_category,
                              'provider_code': observation['inventory']['outcome_failure']['evidence_code']}})
    return facts


def settle_operator_amphenol(engine, *, request_sha256):
    return settle_operator_partial(engine, request_sha256=request_sha256, scope=AMPHENOL)


def settle_operator_partial(engine, *, request_sha256, scope):
    """Settle under the same scraper and writer leases as the scoped observation."""
    require_operator_partial_scope(scope)
    repo, state = engine.repo, engine.state
    company_id = scope.company_id

    def read_owner():
        with (closing(SQLiteRepository(repo.path, repo.spreadsheet_id, readonly=True)) as reader,
              closing(State(state.path, readonly=True)) as checkpoint):
            return read_operator_selected_observation(reader, checkpoint, engine.runtime_binding,
                                                      request_sha256=request_sha256, settlement_recovery=True, scope=scope)

    owner = read_owner()
    if owner['state'] != 'ADMITTED':
        raise ValueError('Operator partial settlement needs its exact admitted cycle.')
    cycle, company, request = owner['cycle'], owner['company'], owner['request']
    root = Path(state.path).parent
    if _same_json_file(root / 'next-scan.json', request):
        raise ValueError('Operator partial settlement requires a durable normal queue acknowledgement.')
    _sync_directory(root)
    cycle_id, request_id = cycle['id'], request['request_id']
    observation = load_operator_partial(owner, state, engine.runtime_binding, scope=scope)
    binding = {'cycle_id': cycle_id, 'request_id': request_id, 'company_id': company_id,
               'source_revision': owner['source_revision'], 'request_sha256': request_sha256,
               'request_fingerprint': owner['request_fingerprint'], 'observation_sha256': observation['sha256'],
               'provider_inventory_sha256': observation['inventory_sha256']}
    facts = operator_partial_facts(scope, binding, observation)
    outcome = classify_outcome(facts)
    if (outcome['outcome'], outcome['action'], outcome.get('repair_category')) != (
            'QUALIFIED_INTEGRATION_REPAIR', 'upsert_qualified_repair', scope.failure_category):
        raise ValueError('Operator partial does not classify as the reviewed repair.')

    _require_no_publication(engine, cycle_id, request_id)
    if company.get('Active Cycle ID') != cycle_id:
        raise ValueError('The Company no longer belongs to the operator partial cycle.')
    saved = read_operator_partial_settlement(repo, cycle_id, request_id, scope=scope)
    if saved is None:
        if (cycle['status'] != 'In Progress' or cycle['companies'][company_id]['stage'] != 'queued'
                or owner['mirror']['Cycle Status'] != 'In Progress' or company.get('Scan State') != 'Queued'
                or _outcome_rows(repo, binding)):
            raise ValueError('Operator partial cannot settle existing or mismatched work.')
        stamp = now()
        terminal = _terminal(cycle, company_id, 'partial', stamp)
        terminal[scope.observation_field] = observation['sha256']
        with repo.transaction():
            repo._commit_in_transaction([
                {'tab': 'Scan Cycles', 'identity': {'Cycle ID': cycle_id},
                 'values': _mirror_values('partial', stamp), 'expected': {'Cycle Status': 'In Progress'}},
                {'tab': 'Companies', 'identity': {'Company ID': company_id}, 'values': {'Scan State': 'Partial'},
                 'expected': {'Active Cycle ID': cycle_id, 'Scan State': 'Queued'}},
            ])
            [mirror] = repo.matches('Scan Cycles', {'Cycle ID': cycle_id})
            saved = {'schema': scope.settlement_schema, 'binding': binding, 'outcome': outcome, 'recorded_at': stamp,
                     'before_state_sha256': _selected_sha(cycle), 'terminal_state_sha256': _selected_sha(terminal),
                     'terminal_mirror_sha256': _selected_sha(mirror[1])}
            repo.db.execute(
                f'CREATE TABLE IF NOT EXISTS {scope.settlement_table} ('
                'cycle TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE, sha256 TEXT NOT NULL, payload TEXT NOT NULL)'
            )
            repo.db.execute(f'INSERT INTO {scope.settlement_table} VALUES (?,?,?,?)',
                            (cycle_id, request_id, _selected_sha(saved), _canonical(saved)))

    current = read_owner()
    if (saved['binding'] != binding or saved['outcome'] != outcome
            or current['company'].get('Scan State') != 'Partial'
            or current['company'].get('Active Cycle ID') != cycle_id
            or _selected_sha(current['mirror']) != saved['terminal_mirror_sha256']):
        raise ValueError('Operator partial terminal evidence changed before completion.')
    current_cycle = current['cycle']
    if _selected_sha(current_cycle) == saved['before_state_sha256']:
        terminal = _terminal(current_cycle, company_id, 'partial', saved['recorded_at'])
        terminal[scope.observation_field] = observation['sha256']
        if _selected_sha(terminal) != saved['terminal_state_sha256']:
            raise ValueError('Operator partial terminal State binding changed.')
        state.save_cycle(terminal)
    if _selected_sha(state.cycle(cycle_id)) != saved['terminal_state_sha256']:
        raise ValueError('Operator partial State did not complete its exact cycle.')

    expected = (outcome['outcome_id'], request_id, company_id, binding['source_revision'], outcome['outcome'],
                outcome['action'], _canonical(outcome), saved['recorded_at'])
    with repo.transaction():
        rows = _outcome_rows(repo, binding)
        if rows and rows != [expected]:
            raise ValueError('Operator partial has a conflicting outcome.')
        public = repo._record_scrape_outcome_in_transaction(facts, recorded_at=saved['recorded_at'])['outcome']
        if public != outcome or _outcome_rows(repo, binding) != [expected]:
            raise ValueError('Operator partial outcome differs from its verified receipt.')
    return {'state': 'FETCH_REPAIR_QUALIFIED', 'cycle_id': cycle_id,
            'settlement_sha256': _selected_sha(saved), 'outcome': public}
