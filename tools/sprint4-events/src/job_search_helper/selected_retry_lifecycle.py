"""Protect active selected retries from normal scraper and sync entry."""
from contextlib import closing
import json
from pathlib import Path


def assert_no_selected_retry_cycle(state_directory, *, permitted_cycle_id=None):
    from .engine import State

    path = Path(state_directory).resolve() / 'state.db'
    if not path.exists():
        return
    with closing(State(str(path), readonly=True)) as state:
        if not state.connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='cycles'",
        ).fetchone():
            return
        for cycle in state.cycles():
            if ('selected_retry_reservation_sha256' in cycle
                    and cycle.get('status') not in {'Complete', 'Complete with exceptions'}
                    and cycle.get('id') != permitted_cycle_id):
                raise ValueError('Selected retry owns this cycle; use its dedicated execution and publication path.')


def assert_generic_outcome_not_selected(repository, identity):
    """Reserve the selected parent request and cycle for the sealed writer."""
    from .engine import State
    from .repository import RepositoryError
    from .scan_request import cycle_metadata

    parent_id = identity.get('temporary_retry_outcome_id')
    if parent_id is not None:
        row = repository.db.execute(
            'SELECT payload FROM scrape_outcomes WHERE outcome_id=?', (parent_id,),
        ).fetchone()
        if row and 'retained_reservation_sha256' in json.loads(row[0])['identity']:
            raise RepositoryError('Selected retry outcomes require the sealed terminal writer.')

    cycle_id = identity.get('cycle_id')
    if not cycle_id:
        return
    mirrors = repository.matches('Scan Cycles', {'Cycle ID': cycle_id})
    if any('selected_retry_reservation_sha256' in cycle_metadata(row) for _, row in mirrors):
        raise RepositoryError('Selected retry outcomes require the sealed terminal writer.')
    path = repository.path.parent / 'state.db'
    if path.is_file() and not path.is_symlink():
        with closing(State(str(path), readonly=True)) as state:
            if state.connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='cycles'").fetchone():
                cycle = state.cycle(cycle_id)
                if cycle is not None and 'selected_retry_reservation_sha256' in cycle:
                    raise RepositoryError('Selected retry outcomes require the sealed terminal writer.')
