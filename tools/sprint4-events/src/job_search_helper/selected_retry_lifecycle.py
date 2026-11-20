"""Protect active selected retries from normal scraper and sync entry."""
from contextlib import closing
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
