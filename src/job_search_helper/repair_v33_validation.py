"""Remove inherited validation only from v3.3's four free-text fields."""
from __future__ import annotations
import copy
import json
import os
import tempfile
from .cli import get_repository, state_path, writer_lock
from .repository import PROTECTED_BACKUP_ID
from .runner import _load_environment

FIELDS = ('Source Hash', 'Salary / Range', 'Work Arrangement', 'Job Description')


def repair_requests(sheet):
    headers = sheet.headers
    if any(headers.count(name) != 1 for name in FIELDS):
        raise ValueError('Expected exactly one of each v3.3 text header; no repair attempted.')
    columns = {headers.index(name) for name in FIELDS}
    requests = []
    for table in sheet.tables:
        bounds = table['range']
        start = bounds.get('startColumnIndex', 0)
        end = bounds['endColumnIndex']
        properties = copy.deepcopy(table.get('columnProperties', []))
        changed = False
        for col in sorted(columns):
            if start <= col < end:
                matches = [p for p in properties if p.get('columnIndex') == col-start]
                if len(matches) != 1:
                    raise ValueError('Incomplete table column metadata; no repair attempted.')
                prop = matches[0]
                if prop.get('columnType') != 'TEXT' or prop.get('dataValidationRule'):
                    prop['columnType'] = 'TEXT'
                    prop.pop('dataValidationRule', None)
                    changed = True
        if changed:
            requests.append({'updateTable': {'table': {
                'tableId': table['tableId'], 'columnProperties': properties,
            }, 'fields': 'columnProperties'}})
    for col in sorted(columns):
        requests.append({'setDataValidation': {'range': {
            'sheetId': sheet.sheet_id, 'startRowIndex': 1,
            'endRowIndex': sheet.row_count, 'startColumnIndex': col,
            'endColumnIndex': col+1,
        }}})
    return requests


def repair(repo, backup_dir):
    if repo.spreadsheet_id == PROTECTED_BACKUP_ID:
        raise ValueError('Refusing to modify the protected backup spreadsheet.')
    sheet = repo._load(['Job History'])['Job History']
    requests = repair_requests(sheet)
    columns = {sheet.headers.index(name) for name in FIELDS}
    backup = {'sheet_id': sheet.sheet_id, 'spreadsheet_id': repo.spreadsheet_id,
              'headers': sheet.headers, 'tables': sheet.tables,
              'validation': [{'row': row, 'column': col, 'rule': cell['dataValidation']}
                  for (row, col), cell in sheet.cells.items()
                  if col in columns and row >= 1 and cell.get('dataValidation')]}
    backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, path = tempfile.mkstemp(prefix='v33-validation-backup-', suffix='.json', dir=backup_dir)
    with os.fdopen(fd, 'w') as out:
        json.dump(backup, out, ensure_ascii=False, indent=2)
    print(f'Validation backup: {path}', flush=True)
    repo._execute(repo.service.spreadsheets().batchUpdate(
        spreadsheetId=repo.spreadsheet_id, body={'requests': requests}), 'write')
    repo._metadata_cache = None
    after = repo._load(['Job History'])['Job History']
    if any(cell.get('dataValidation') for (row, col), cell in after.cells.items()
           if row >= 1 and col in columns):
        raise RuntimeError('Validation remains on a target text column; repair not verified.')
    if any('updateTable' in req for req in repair_requests(after)):
        raise RuntimeError('Table column repair not verified.')
    print('Repaired and verified the four v3.3 text columns. Job values and scan progress preserved.', flush=True)


def main():
    _load_environment()
    database = state_path()
    database.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with writer_lock(database.parent / 'writer.lock'):
        repo = get_repository(write=True, interactive=False)
        repair(repo, database.parent)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
