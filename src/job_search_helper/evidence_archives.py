"""Google Drive evidence volumes with evidence-first, replay-safe commits.

The main workbook commit remains atomic. Evidence is committed first: an
interruption may leave unreferenced evidence, never a history record referring
to evidence whose write failed. Callers must hold the existing writer.lock.
"""
from __future__ import annotations

import copy
import json
import os
import re
import tempfile
from pathlib import Path

from .repository import GoogleRepository, RepositoryError, SCHEMAS, _tab

TAB = 'Job Evidence'
ROW_STRIDE = 100_000
VOLUME_LIMIT = 30_000_000


class ArchiveRepository(GoogleRepository):
    def _load_commit(self, operations):
        if all(not op.get('append_if_missing') for op in operations):
            return self._load_existing_commit(operations)
        return super()._load_commit(operations)


def save_registry(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.evidence-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as handle:
            os.fchmod(handle.fileno(), 0o600)
            json.dump(data, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class EvidenceArchives:
    def __init__(self, main, registry_path, factory=None):
        self.main = main
        self.registry_path = Path(registry_path)
        self.schemas = copy.deepcopy(SCHEMAS)
        self._repos = {}
        self._factory = factory
        self._committed_rows = {}
        self._committed_partial = True
        self._reload()
        # The former evidence tab is now a human-readable archive directory.
        self.main.schemas = {k: v for k, v in main.schemas.items() if k != TAB}

    def __getattr__(self, name):
        return getattr(self.main, name)

    def _reload(self):
        try:
            registry = json.loads(self.registry_path.read_text())
        except (OSError, ValueError) as exc:
            raise RepositoryError('Evidence archive registry is unavailable; refusing to fall back to the full workbook.') from exc
        if registry.get('version') != 1 or registry.get('spreadsheet_id') != self.main.spreadsheet_id:
            raise RepositoryError('Evidence archive registry belongs to a different workbook or version.')
        archives = registry.get('archives')
        if not isinstance(archives, list) or not archives:
            raise RepositoryError('Evidence archive registry has no volumes.')
        ids = []
        for item in archives:
            ident = item.get('spreadsheet_id', '')
            if not re.fullmatch(r'[A-Za-z0-9_-]+', ident) or ident == self.main.spreadsheet_id or ident in ids:
                raise RepositoryError('Invalid or duplicate evidence archive ID.')
            if not isinstance(item.get('reserved_bytes'), int) or item['reserved_bytes'] < 0:
                raise RepositoryError('Invalid evidence archive size accounting.')
            ids.append(ident)
        self.registry = registry

    def _repo(self, item):
        ident = item['spreadsheet_id']
        if ident not in self._repos:
            if self._factory:
                repo = self._factory(ident)
            else:
                repo = ArchiveRepository(self.main.service, ident, schemas={TAB: SCHEMAS[TAB]},
                                        min_request_interval=self.main.min_request_interval)
                # All volumes share the same Google-user quota and metrics.
                repo.metrics = self.main.metrics
                repo._pace_request = self.main._pace_request
            self._repos[ident] = repo
        return self._repos[ident]

    def read_columns(self, tab, headers):
        if tab != TAB:
            return self.main.read_columns(tab, headers)
        self._reload()
        result = []
        for index, item in enumerate(self.registry['archives']):
            for rownum, values in self._repo(item).read_columns(TAB, headers):
                if not 2 <= rownum <= ROW_STRIDE:
                    raise RepositoryError('Evidence row is outside supported volume bounds.')
                result.append((index * ROW_STRIDE + rownum, values))
        return result

    def read_cached_columns(self, tab, headers):
        return self.read_columns(tab, headers) if tab == TAB else self.main.read_cached_columns(tab, headers)

    def read_row(self, tab, row_number):
        if tab != TAB:
            return self.main.read_row(tab, row_number)
        self._reload()
        if not isinstance(row_number, int) or row_number < 2:
            raise RepositoryError('Invalid evidence row locator.')
        index, offset = divmod(row_number - 1, ROW_STRIDE)
        if index >= len(self.registry['archives']) or offset < 1:
            raise RepositoryError('Unknown evidence volume or header row locator.')
        return self._repo(self.registry['archives'][index]).read_row(TAB, offset + 1)

    def read(self, tab):
        if tab != TAB:
            return self.main.read(tab)
        return [row for _, row in self.read_columns(TAB, SCHEMAS[TAB])]

    def read_many(self, tabs):
        tabs = list(tabs)
        rows = self.main.read_many([t for t in tabs if t != TAB])
        if TAB in tabs:
            rows[TAB] = self.read(TAB)
        return rows

    def validate_schema(self):
        self._reload()
        self.main.validate_schema()
        for item in self.registry['archives']:
            self._repo(item).validate_schema()
        return True

    def ensure_tab(self, tab):
        if tab == TAB:
            self.validate_schema()
            return {'created': False, 'added_headers': [], 'archived': True}
        return self.main.ensure_tab(tab)

    def ensure_columns(self, tab, headers):
        if tab == TAB:
            if set(headers) - set(SCHEMAS[TAB]):
                raise RepositoryError('Unsupported archive schema change.')
            self.validate_schema()
            return []
        return self.main.ensure_columns(tab, headers)

    def _new_volume(self):
        number = len(self.registry['archives']) + 1
        title = f'Job Search Evidence - Volume {number:03d}'
        created = self.main._execute(self.main.service.spreadsheets().create(body={
            'properties': {'title': title},
            'sheets': [{'properties': {'title': TAB, 'gridProperties': {
                'rowCount': 1000, 'columnCount': len(SCHEMAS[TAB]), 'frozenRowCount': 1}},
                'data': [{'rowData': [{'values': [{'userEnteredValue': {'stringValue': h},
                    'userEnteredFormat': {'textFormat': {'bold': True}}} for h in SCHEMAS[TAB]]}]}]}]
        }, fields='spreadsheetId,spreadsheetUrl'), 'write')
        item = {'spreadsheet_id': created['spreadsheetId'], 'url': created['spreadsheetUrl'],
                'title': title, 'reserved_bytes': 0}
        self.registry['archives'].append(item)
        self.registry['directory_pending'] = True
        save_registry(self.registry_path, self.registry)
        # Persist the volume ID before any evidence writes. An uncertain create
        # may leave an empty unused file; it cannot lose or duplicate evidence.
        self.update_directory()
        return item

    def update_directory(self):
        self.main._metadata_cache = None
        sheet = next((s['properties'] for s in self.main._metadata()['sheets']
                      if s['properties']['title'] == TAB), None)
        if sheet is None:
            raise RepositoryError('The archive directory tab is missing.')
        rows = [['Evidence archive', 'Open in Google Drive', 'Description'],
                ['Storage', 'Full descriptions are preserved in the linked volumes.',
                 'The scraper and managed reviewers search all volumes automatically.']]
        rows += [[a.get('title', f'Volume {i+1}'), a['url'], 'Match Job Key + Source Hash']
                 for i, a in enumerate(self.registry['archives'])]
        requests = []
        if len(rows) > sheet['gridProperties']['rowCount']:
            requests.append({'appendDimension': {'sheetId': sheet['sheetId'], 'dimension': 'ROWS',
                            'length': len(rows)-sheet['gridProperties']['rowCount']}})
        requests.append({'updateCells': {'start': {'sheetId': sheet['sheetId'], 'rowIndex': 0, 'columnIndex': 0},
            'rows': [{'values': [dict({'userEnteredValue': {'stringValue': str(v)}},
                **({'userEnteredFormat': {'textFormat': {'link': {'uri': str(v)}}}}
                   if ri >= 2 and ci == 1 else {})) for ci, v in enumerate(row)]}
                for ri, row in enumerate(rows)],
            'fields': 'userEnteredValue,userEnteredFormat.textFormat.link'}})
        self.main._execute(self.main.service.spreadsheets().batchUpdate(
            spreadsheetId=self.main.spreadsheet_id, body={'requests': requests}), 'write')
        self.registry['directory_pending'] = False
        save_registry(self.registry_path, self.registry)

    def commit(self, operations):
        operations = list(operations)
        for op in operations:
            if not isinstance(op, dict):
                raise RepositoryError('Each operation must be a mapping.')
            _tab(op.get('tab'))
        evidence = [op for op in operations if op['tab'] == TAB]
        others = [op for op in operations if op['tab'] != TAB]
        self._committed_rows = {}
        results = []
        evidence_rows = []
        try:
            if evidence:
                self._reload()
                if self.registry.get('directory_pending'):
                    self.update_directory()
                locations = {}
                tails = []
                for index, item in enumerate(self.registry['archives']):
                    tail = 1
                    for rownum, row in self._repo(item).read_columns(TAB, ['Job Key', 'Source Hash']):
                        tail = max(tail, rownum)
                        key = (row.get('Job Key'), row.get('Source Hash'))
                        if key in locations:
                            raise RepositoryError('Duplicate evidence identity across archive volumes.')
                        locations[key] = index
                    tails.append(tail)
                groups = {}
                new_keys = set()
                for op in evidence:
                    identity = op.get('identity', {})
                    if set(identity) != {'Job Key', 'Source Hash'} or not all(identity.values()):
                        raise RepositoryError('Evidence requires exact Job Key and Source Hash.')
                    key = (identity['Job Key'], identity['Source Hash'])
                    size = len(json.dumps(op, ensure_ascii=True).encode())
                    if size > VOLUME_LIMIT:
                        raise RepositoryError('A single evidence record exceeds the volume limit.')
                    if key in locations:
                        index = locations[key]
                        # Resolve known records using fresh, targeted cell reads,
                        # not a full download of an old volume's descriptions.
                        if key not in new_keys:
                            op = {**op, 'append_if_missing': False}
                    else:
                        index = len(self.registry['archives']) - 1
                        if (self.registry['archives'][index]['reserved_bytes'] + size > VOLUME_LIMIT
                                or tails[index] >= ROW_STRIDE - 1000):
                            self._new_volume()
                            index += 1
                            tails.append(1)
                        locations[key] = index
                        new_keys.add(key)
                        tails[index] += 1
                    item = self.registry['archives'][index]
                    # Reserve before sending: even an ambiguous write/replay
                    # cannot undercount a volume. Overcounts only roll earlier.
                    item['reserved_bytes'] += size
                    groups.setdefault(index, []).append(op)
                save_registry(self.registry_path, self.registry)
                for index, ops in groups.items():
                    repo = self._repo(self.registry['archives'][index])
                    result = repo.commit(ops)
                    results.append(result)
                    evidence_rows.extend(repo._committed_rows.get(TAB, []))
            if others:
                results.append(self.main.commit(others))
                self._committed_rows.update(self.main._committed_rows)
            if evidence:
                self._committed_rows[TAB] = evidence_rows
            return {**{key: sum(r.get(key, 0) for r in results)
                       for key in ('inserted', 'updated', 'requests')},
                    'new_jobs': [job for result in results for job in result.get('new_jobs', [])]}
        except Exception:
            self._committed_rows = {}
            self._repos.clear()
            raise
