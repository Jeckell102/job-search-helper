from contextlib import closing
import sqlite3

import pytest

from job_search_helper.inbox import InventoryInbox


def test_readonly_inbox_reads_existing_inventory_without_mutating(tmp_path):
    path = tmp_path / 'inventories.sqlite3'
    payload = {'inventory_status': 'complete', 'jobs': []}
    with closing(InventoryInbox(path, 'working-sheet')) as inbox:
        inbox.save('CYC-1', 'COMP-1', payload)
    saved = path.read_bytes()

    with closing(InventoryInbox(path, 'working-sheet', readonly=True)) as inbox:
        assert inbox.get('CYC-1', 'COMP-1') == (payload, False)
        with pytest.raises(sqlite3.OperationalError, match='readonly'):
            inbox.save('CYC-2', 'COMP-1', payload)
    assert path.read_bytes() == saved
    with pytest.raises(ValueError, match='different spreadsheet'):
        InventoryInbox(path, 'another-sheet', readonly=True)
    missing = tmp_path / 'missing.sqlite3'
    with pytest.raises(sqlite3.OperationalError):
        InventoryInbox(missing, 'working-sheet', readonly=True)
    assert not missing.exists()
