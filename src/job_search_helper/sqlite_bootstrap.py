"""Bounded, read-only import of the master workbook and its evidence volumes.

A shadow import never becomes an operational database. An operational import
requires all old writers to be stopped; the CLI holds the existing writer lock.
No Google write is performed here, and a partial database remains unusable.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from .repository import (RepositoryError, SCHEMAS, _column_name, _identity_key,
                         _table_rule, _validate_headers)
from .sqlite_repository import SQLiteRepository, encode, identity_for, timestamp


def identity_label(tab, row):
    return encode({h: _identity_key(h, v) for h, v in identity_for(tab, row).items()})


def sources(remote):
    main = getattr(remote, 'main', remote)
    if hasattr(remote, 'registry'):
        remote._reload()
        result = [(main, tab) for tab in SCHEMAS if tab != 'Job Evidence']
        result.extend((remote._repo(item), 'Job Evidence') for item in remote.registry['archives'])
        return result
    return [(main, tab) for tab in SCHEMAS]


def chunks(repo, tab, size=500):
    """Yield numbered records and formula/dropdown policies, not whole sheets."""
    if not 1 <= size <= 2000:
        raise ValueError('Import chunk size must be between 1 and 2000 rows.')
    if not hasattr(repo, '_load'):
        # Offline test repositories only. Production uses cell-aware grid reads.
        rows = list(enumerate(repo.read(tab), 2))
        for start in range(0, len(rows), size):
            yield rows[start:start + size], {}, list(repo.schemas[tab])
        return
    repo._metadata_cache = None
    repo._header_cache.clear()
    metadata = repo._metadata()
    sheets = {item['properties']['title']: item for item in metadata.get('sheets', [])}
    if tab not in sheets:
        raise RepositoryError(f'Missing import tab: {tab}')
    count = sheets[tab]['properties']['gridProperties']['rowCount']
    headers, _ = repo._headers(tab)
    _validate_headers(tab, headers, SCHEMAS[tab])
    end = _column_name(len(headers))
    escaped = tab.replace("'", "''")
    for start in range(2, count + 1, size):
        stop = min(count, start + size - 1)
        ranges = [f"'{escaped}'!A1:{end}1", f"'{escaped}'!A{start}:{end}{stop}"]
        sheet = repo._load([tab], ranges_override=ranges)[tab]
        numbered = [(number + 1, row) for number, row in sheet.records()
                    if start <= number + 1 <= stop]
        policies = {}
        for number, row in numbered:
            row_policies = {}
            for col, header in enumerate(sheet.headers):
                cell = sheet.cells.get((number - 1, col), {})
                policy = {}
                entered = cell.get('userEnteredValue', {})
                if 'formulaValue' in entered:
                    policy['userEnteredValue'] = copy.deepcopy(entered)
                validation = cell.get('dataValidation') or _table_rule(sheet, number - 1, col)
                if validation:
                    policy['dataValidation'] = copy.deepcopy(validation)
                if policy:
                    row_policies[header] = policy
            policies[number] = row_policies
        yield numbered, policies, list(sheet.headers)


def control_signature(rows, tab):
    fields = {
        'Companies': ['Company', 'Company ID', 'Company Status', 'Official Careers URL', 'ATS / Source'],
        'Job History': ['Job Key', 'Added to Opportunities?', 'Review Status', 'Decision', 'Source Hash'],
        'Opportunities': ['Company', 'Job URL', 'Application Status', 'Date Applied', 'Date Found', 'Notes'],
        'Scan Cycles': ['Cycle ID', 'Cycle Status', 'Last Checkpoint At'],
    }[tab]
    selected = [{h: row.get(h, '') for h in fields} for row in rows]
    return hashlib.sha256(encode(sorted(selected, key=lambda r: identity_label(tab, r))).encode()).hexdigest()


def bootstrap(remote, destination, *, shadow=True, chunk_size=500, progress=None):
    destination = Path(destination).resolve()
    if destination.exists():
        raise RepositoryError('Import destination already exists; use a new filename. No database was replaced.')
    local = SQLiteRepository(destination, remote.spreadsheet_id, initialize=True)
    try:
        with local.transaction():
            local.set_meta('ready', 'no')
            local.set_meta('import_started', timestamp())
            local.set_meta('shadow', 'yes' if shadow else 'no')
            local.db.execute('CREATE TABLE import_identities (tab TEXT, identity TEXT, source TEXT, remote_row INTEGER, PRIMARY KEY(tab,identity))')
        reports = []
        for repo, tab in sources(remote):
            source_id = repo.spreadsheet_id
            digest = hashlib.sha256()
            count = 0
            for numbered, policies, headers in chunks(repo, tab, chunk_size):
                if headers != local.schemas[tab]:
                    if local.read_columns(tab, [local.schemas[tab][0]]):
                        raise RepositoryError(f'{tab}: incompatible headers between import sources.')
                    with local.transaction():
                        local.db.execute('UPDATE tabs SET headers=? WHERE tab=?', (encode(headers), tab))
                    local.schemas[tab] = headers
                # Reserve each identity before import. A repeated key in another
                # row or volume must never overwrite the earlier record silently.
                with local.transaction():
                    for number, row in numbered:
                        label = identity_label(tab, row)
                        previous = local.db.execute('SELECT source,remote_row FROM import_identities WHERE tab=? AND identity=?', (tab, label)).fetchone()
                        if previous:
                            raise RepositoryError(f'{tab}: duplicate identity at rows {previous[1]} and {number}; import stopped.')
                        local.db.execute('INSERT INTO import_identities VALUES (?,?,?,?)', (tab, label, source_id, number))
                local.import_rows(tab, numbered, policies=policies, protect_existing_choices=True)
                for number, row in numbered:
                    matches = local.matches(tab, identity_for(tab, row))
                    expected = {h: row.get(h, '') for h in headers}
                    if len(matches) != 1 or matches[0][1] != expected:
                        raise RepositoryError(f'{tab}: imported values failed exact verification at row {number}.')
                    digest.update((encode(expected) + '\n').encode())
                count += len(numbered)
                with local.transaction():
                    local.db.execute('INSERT INTO import_progress VALUES (?,?,?,0) ON CONFLICT(source,tab) DO UPDATE SET next_row=excluded.next_row',
                        (source_id, tab, (numbered[-1][0] + 1) if numbered else 2))
                if progress:
                    progress({'tab': tab, 'source': source_id, 'rows_verified': count})
            with local.transaction():
                local.db.execute('INSERT INTO import_progress VALUES (?,?,?,1) ON CONFLICT(source,tab) DO UPDATE SET complete=1', (source_id, tab, count + 2))
            reports.append({'tab': tab, 'source': source_id, 'rows': count, 'sha256': digest.hexdigest()})
        if local.db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise RepositoryError('Imported database integrity check failed.')
        # A shadow copy may have observed an active scraper. It is not eligible
        # for activation, even when every downloaded row was copied correctly.
        if not shadow:
            for tab in ('Companies', 'Job History', 'Opportunities', 'Scan Cycles'):
                local_rows = local.read(tab)
                if tab in ('Job History', 'Scan Cycles'):
                    fields = ['Job Key', 'Added to Opportunities?', 'Review Status', 'Decision', 'Source Hash'] if tab == 'Job History' else ['Cycle ID', 'Cycle Status', 'Last Checkpoint At']
                    remote_rows = [row for _, row in remote.read_columns(tab, fields)]
                else:
                    remote_rows = remote.read(tab)
                if control_signature(local_rows, tab) != control_signature(remote_rows, tab):
                    raise RepositoryError(f'{tab}: controls changed during import. Keep writers stopped and repeat into a new database.')
        with local.transaction():
            local.set_meta('import_report', encode(reports))
            local.set_meta('import_completed', timestamp())
            local.set_meta('ready', 'no' if shadow else 'yes')
        return {**local.status(), 'shadow': shadow, 'import_report': reports, 'path': str(destination)}
    finally:
        local.close()
