"""One fresh, owner-approved native-table Company append with read-only remote recovery."""

from contextlib import contextmanager
from datetime import date
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
from unicodedata import normalize

from job_search_helper.ats import resolve_board
from job_search_helper.cli import writer_lock
from job_search_helper.company_events import canonical_company_fact, source_revision
from job_search_helper.repository import (
    MAX_ROWS, PROTECTED_BACKUP_ID, RepositoryError, _Sheet, _column_name, _effective,
)
from job_search_helper.sheet_profile import COMPACT_PROFILE, COMPACT_SCHEMAS


_TAB = 'Companies'
_IDENTITY = ('Company', 'Company ID', 'Official Careers URL')
_SCHEMA = 'scoped-manual-pilot-company-scope-v2'
_CLAIM = 'append-claim.json'
_MARKER_KEY = 'job-search-helper.scoped-company-append-v2'
_SHA = re.compile(r'[0-9a-f]{64}')
_BOARD = re.compile(r'https://job-boards\.greenhouse\.io/([a-z0-9][a-z0-9_-]{0,98})')


def _require(condition, reason):
    if not condition:
        raise RepositoryError(reason)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


def _digest(data):
    return sha256(data).hexdigest()


def _legacy_token(value):
    return ''.join(character for character in normalize('NFKC', value).casefold() if character.isalnum())


def _selection(approval, approved_sha256):
    _require(type(approval) is bytes and len(approval) <= 8192 and type(approved_sha256) is str
             and _SHA.fullmatch(approved_sha256) and _digest(approval) == approved_sha256,
             'An independent exact v2 intake scope is required.')
    try:
        scope = json.loads(approval)
        _require(type(scope) is dict and set(scope) == {
            'schema', 'company_name', 'company_id', 'board_url', 'added_on', 'workbook_sha256',
            'sheet_id', 'table_id', 'headers', 'metadata_id', 'pristine_custody',
        } and scope['schema'] == _SCHEMA and _canonical(scope) == approval,
                 'The v2 intake scope is outside the approved schema.')
        name, url = scope['company_name'], scope['board_url']
        board = _BOARD.fullmatch(url)
        _require(type(name) is str and name == name.strip() and 0 < len(name) <= 160
                 and name.isprintable() and re.fullmatch(r'COMP-[A-F0-9]{12}', scope['company_id'])
                 and board and resolve_board('Greenhouse', url)[:2] == ('Greenhouse', board[1])
                 and date.fromisoformat(scope['added_on']).isoformat() == scope['added_on'],
                 'The Company identity or Greenhouse URL is outside the exact enrollment.')
        _require(_legacy_token(name) != 'atomicmachines' and _legacy_token(board[1]) != 'atomicmachines',
                 'The unresolved legacy Atomic Machines identity or board is excluded from v2 intake.')
        _require(type(scope['metadata_id']) is int and 0 < scope['metadata_id'] <= 2**31 - 1
                 and type(scope['sheet_id']) is int and 0 <= scope['sheet_id'] <= 2**31 - 1
                 and re.fullmatch(r'[A-Za-z0-9_-]{1,128}', scope['table_id'])
                 and _SHA.fullmatch(scope['workbook_sha256']) and type(scope['headers']) is list
                 and len(scope['headers']) == len(COMPACT_SCHEMAS[_TAB])
                 and set(scope['headers']) == set(COMPACT_SCHEMAS[_TAB]),
                 'The worksheet, native table, header order or metadata ID is outside enrollment.')
        custody = scope['pristine_custody']
        _require(type(custody) is list and len(custody) == 4
                 and all(type(part) is int and part > 0 for part in custody),
                 'The v2 intake requires a pinned pristine private custody directory.')
    except (TypeError, ValueError, RecursionError):
        raise RepositoryError('The v2 intake scope is malformed.') from None
    return scope


def _key(value):
    return str(value or '').strip().casefold()


def _board_key(value):
    url = str(value or '').strip()
    if url.lower().startswith('http://'):
        url = 'https://' + url[7:]
    try:
        provider, board, _ = resolve_board('', url)
    except ValueError:
        return None
    return board.casefold() if provider == 'Greenhouse' else None


def _match(records, row):
    board = _board_key(row['Official Careers URL'])
    matches = [(number, found) for number, found in records
               if _key(found['Company']) == _key(row['Company'])
               or _key(found['Company ID']) == _key(row['Company ID'])
               or _board_key(found['Official Careers URL']) == board]
    if not matches:
        return None
    _require(len(matches) == 1, 'Multiple rows match the enrolled Company identity or board.')
    number, found = matches[0]
    _require(all(found[key] == row[key] for key in _IDENTITY),
             'An existing Company row collides with the enrolled identity or board.')
    return number


def _row(scope):
    return {'Company': scope['company_name'], 'Company ID': scope['company_id'], 'Company Status': 'Active',
            'Official Careers URL': scope['board_url'], 'ATS / Source': 'Greenhouse', 'Date Added': scope['added_on']}


def _remote_row(remote, workbook, scope, row):
    headers = scope['headers']
    width = len(headers)
    snapshot = remote._execute(remote.service.spreadsheets().get(
        spreadsheetId=workbook, ranges=[f"'Companies'!A1:{_column_name(width)}"],
        includeGridData=True,
        fields=('sheets(properties(sheetId,title,gridProperties(rowCount)),'
                'tables(tableId,range,rowsProperties(footerColorStyle)),'
                'data(startRow,startColumn,rowData(values(userEnteredValue,effectiveValue,'
                'formattedValue,hyperlink,textFormatRuns))))'),
    ), 'read')
    sheets = snapshot.get('sheets', [])
    _require(len(sheets) == 1, 'The enrolled Companies worksheet was not uniquely returned.')
    raw = sheets[0]
    properties = raw.get('properties', {})
    tables = raw.get('tables', [])
    _require(properties.get('title') == _TAB and properties.get('sheetId') == scope['sheet_id']
             and len(tables) == 1 and tables[0].get('tableId') == scope['table_id'],
             'The Companies worksheet or native table identity differs from enrollment.')
    bounds = tables[0].get('range', {})
    grid_rows = properties.get('gridProperties', {}).get('rowCount')
    table_end = bounds.get('endRowIndex')
    _require(bounds.get('sheetId') == scope['sheet_id'] and bounds.get('startRowIndex', 0) == 0
             and bounds.get('startColumnIndex', 0) == 0 and bounds.get('endColumnIndex') == width
             and type(table_end) is int and type(grid_rows) is int and 2 <= table_end <= grid_rows <= MAX_ROWS,
             'The Companies table no longer spans the enrolled compact columns.')
    blocks = raw.get('data', [])
    _require(len(blocks) == 1 and blocks[0].get('startRow', 0) == blocks[0].get('startColumn', 0) == 0,
             'The Companies grid did not begin with the enrolled headers.')
    rows = blocks[0].get('rowData', [])
    _require(rows and len(rows) <= grid_rows, 'The Companies grid did not return its bounded rows.')
    header_cells = rows[0].get('values', [])
    _require([_effective(cell) for cell in header_cells] == headers
             and all(cell.get('userEnteredValue') == {'stringValue': header}
                     for cell, header in zip(header_cells, headers, strict=True)),
             'The Companies literal header order differs from enrollment.')
    sheet = _Sheet(headers)
    for index, entry in enumerate(rows[1:], start=1):
        values = entry.get('values', [])
        _require(len(values) <= width, 'The Companies grid returned columns outside the enrolled width.')
        sheet.cells.update({(index, col): cell for col, cell in enumerate(values) if cell})
    number = _match(((number + 1, found) for number, found in sheet.records()), row)
    if number is None:
        return None
    footer = 'footerColorStyle' in tables[0].get('rowsProperties', {})
    _require(number < table_end or number == table_end and not footer,
             'The selected Company is outside the native table body.')
    for column, header in enumerate(headers):
        cell = sheet.cells.get((number - 1, column), {})
        value, entered = _effective(cell), cell.get('userEnteredValue', {})
        if header in row:
            _require(value == row[header] and entered == {'stringValue': row[header]},
                     'The current Company row differs from the enrolled literal input.')
        else:
            _require(value in ('', None) and not entered,
                     'The current Company row contains an unenrolled value.')
    return number


def _marker_present(remote, workbook, expected):
    result = remote._execute(remote.service.spreadsheets().developerMetadata().search(
        spreadsheetId=workbook,
        body={'dataFilters': [{'developerMetadataLookup': {'metadataId': expected['metadataId']}}]},
        fields='matchedDeveloperMetadata(developerMetadata(metadataId,metadataKey,metadataValue,location,visibility))',
    ), 'read')
    matches = result.get('matchedDeveloperMetadata', [])
    if matches == []:
        return False
    _require(type(matches) is list and len(matches) == 1 and type(matches[0]) is dict
             and type(matches[0].get('developerMetadata')) is dict,
             'The exact developer metadata ID has ambiguous evidence.')
    marker = dict(matches[0]['developerMetadata'])
    location = marker.get('location')
    _require(type(location) is dict and location.get('spreadsheet') is True,
             'The existing developer metadata marker is not spreadsheet-scoped.')
    if location == {'spreadsheet': True, 'locationType': 'SPREADSHEET'}:
        marker['location'] = {'spreadsheet': True}
    _require(type(marker.get('metadataId')) is int and marker == expected,
             'The existing developer metadata marker differs from the append claim.')
    return True


def _remote_evidence(remote, workbook, scope, row, marker, *, committed):
    _require(_marker_present(remote, workbook, marker) == committed,
             'The exact append marker is missing or already present; dispatch and replay are held.')
    number = _remote_row(remote, workbook, scope, row)
    _require((number is not None) == committed,
             'The exact Company row is missing or already present; dispatch and replay are held.')
    _require(_marker_present(remote, workbook, marker) == committed,
             'The exact append marker changed during Company readback.')
    return number


def _claim(scope, scope_sha256, database, row):
    intent = {'schema': 'scoped-manual-pilot-append-claim-v2', 'scope_sha256': scope_sha256,
              'database': database, 'row': row, 'workbook_sha256': scope['workbook_sha256'],
              'sheet_id': scope['sheet_id'], 'table_id': scope['table_id'], 'headers': scope['headers'],
              'metadata_id': scope['metadata_id']}
    marker = {'metadataId': scope['metadata_id'], 'metadataKey': _MARKER_KEY,
              'metadataValue': _digest(_canonical(intent)), 'location': {'spreadsheet': True},
              'visibility': 'DOCUMENT'}
    cells = [{'userEnteredValue': {'stringValue': row[header]}} if header in row else {}
             for header in scope['headers']]
    body = _canonical({'requests': [
        {'createDeveloperMetadata': {'developerMetadata': marker}},
        {'appendCells': {'sheetId': scope['sheet_id'], 'tableId': scope['table_id'],
                         'fields': 'userEnteredValue', 'rows': [{'values': cells}]}},
    ]})
    payload = _canonical({'intent': intent, 'body_sha256': _digest(body), 'body': json.loads(body)}) + b'\n'
    return payload, body, marker


def _stamp(info):
    return [info.st_dev, info.st_ino, info.st_ctime_ns, info.st_mtime_ns]


def _check_custody(path, fd, pin, *, pristine=False):
    info = os.fstat(fd)
    expected = pin if pristine else pin[:2]
    _require(path.resolve(strict=True) == path and _stamp(path.lstat()) == _stamp(info)
             and _stamp(info)[:len(expected)] == expected and info.st_uid == os.geteuid()
             and stat.S_IMODE(info.st_mode) == 0o700
             and (not pristine or not os.listdir(fd)),
             'The independently pinned fresh custody is unavailable or already spent.')


def _read_claim(fd, payload):
    try:
        descriptor = os.open(_CLAIM, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    except FileNotFoundError:
        raise RepositoryError('The retained v2 append claim is missing; replay is held.') from None
    with os.fdopen(descriptor, 'rb') as stream:
        info = os.fstat(stream.fileno())
        _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == os.geteuid()
                 and stat.S_IMODE(info.st_mode) == 0o600 and stream.read(len(payload) + 1) == payload
                 and _stamp(os.stat(_CLAIM, dir_fd=fd, follow_symlinks=False)) == _stamp(info),
                 'The retained v2 append claim differs from the exact approved request.')


def _create_claim(fd, payload):
    descriptor = os.open(_CLAIM, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=fd)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    os.fsync(fd)
    _read_claim(fd, payload)


def _local_identity(local):
    path = Path(local.path).absolute()
    info = path.lstat()
    databases = local.db.execute('PRAGMA database_list').fetchall()
    _require(path.resolve(strict=True) == path and stat.S_ISREG(info.st_mode) and info.st_nlink == 1
             and [(schema, name) for _, schema, name in databases if schema != 'temp'] == [('main', str(path))]
             and not local.db.execute('SELECT 1 FROM temp.sqlite_master LIMIT 1').fetchone(),
             'Expected the exact local Jobs file without attached or shadowed relations.')
    return [info.st_dev, info.st_ino]


def _local_number(local, row):
    return _match(local.read_columns(_TAB, _IDENTITY), row)


def _has_history(local, row):
    return local.db.execute('SELECT 1 FROM main.company_revisions WHERE lower(company_id)=lower(?)',
                            (row['Company ID'],)).fetchone() is not None


def _required_event(local, row):
    company = row['Company ID']
    event_rows = local.db.execute(
        'SELECT event_id,revision,source_revision,kind,payload FROM main.company_event_outbox WHERE company_id=?',
        (company,),
    ).fetchall()
    revisions = local.db.execute(
        'SELECT revision,source_revision,eligible,fact FROM main.company_revisions WHERE company_id=?',
        (company,),
    ).fetchall()
    fact, revision = canonical_company_fact(row), source_revision(row)
    _require(len(event_rows) == len(revisions) == 1 and revisions[0][:3] == (1, revision, 1)
             and json.loads(revisions[0][3]) == fact,
             'The selected Company lacks one exact intake revision and event.')
    event_id, number, source, kind, payload = event_rows[0]
    event = {'event_id': event_id, 'revision': 1, 'source_revision': revision, 'kind': 'company.eligible',
             'fact': fact, 'origin': 'sheets-reconciliation', 'company_id': company, 'company': row['Company']}
    _require(re.fullmatch(r'CEV-[a-f0-9]{32}', event_id) and (number, source, kind) == (1, revision, 'company.eligible')
             and json.loads(payload) == event, 'The selected local event differs from the v2 append claim.')
    return event


def _confirm_local(local, workbook, remote_number, row, payload, database):
    receipt_key = 'scoped_manual_pilot_intake_v2:' + _digest(payload)
    with local.transaction():
        _require(_local_identity(local) == database and local.get_meta('spreadsheet_id') == workbook,
                 'The pinned Jobs file or workbook changed before intake.')
        local_number, receipt = _local_number(local, row), local.get_meta(receipt_key)
        if local_number is None:
            _require(receipt is None and not _has_history(local, row),
                     'The enrolled Company ID already has intake or revision history.')
            imported, events = local._import_rows_in_transaction(
                _TAB, [(remote_number, row)], event_origin='sheets-reconciliation',
            )
            _require(imported == len(events) == 1, 'Exact intake did not create one local event.')
            local_number, receipt = _local_number(local, row), events[0]['event_id']
            local.set_meta(receipt_key, receipt)
        _require(local_number is not None, 'The enrolled row could not be read back from local Jobs.')
        baseline = local.baseline(_TAB, local_number - 1)
        current = local.read_row(_TAB, local_number)
        _require(baseline is not None and all(baseline.get(key) == current.get(key) == value
                                              for key, value in row.items()),
                 'Local Company and baseline differ from the enrolled literal input.')
        event = _required_event(local, row)
        _require(receipt == event['event_id'] and _local_identity(local) == database,
                 'The selected local event is not bound to the durable v2 append claim.')
    return {'state': 'COMPANY_INTAKE_CONFIRMED', 'event_id': event['event_id'],
            'company_id': event['company_id'], 'source_revision': event['source_revision']}


@contextmanager
def _owned(local, remote, scope, custody):
    workbook = remote.spreadsheet_id
    _require(not local.readonly and not local.db.in_transaction
             and local.spreadsheet_id == workbook and workbook != PROTECTED_BACKUP_ID
             and _digest(workbook.encode()) == scope['workbook_sha256']
             and remote.schemas.get(_TAB) == COMPACT_SCHEMAS[_TAB],
             'The effective workbook or configured Companies schema is outside scope.')
    state = Path(local.path).absolute().parent
    custody = Path(custody)
    with writer_lock(state / 'scraper.lock'), writer_lock(state / 'writer.lock'):
        _require(local.get_meta('ready') == 'yes' and local.get_meta('sheets_profile') == COMPACT_PROFILE
                 and local.get_meta('company_event_external_baseline') == 'yes',
                 'Expected the existing completed local Companies baseline.')
        fd = os.open(custody, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            _check_custody(custody, fd, scope['pristine_custody'])
            yield fd, _local_identity(local), workbook
        finally:
            os.close(fd)


def start_new_intake(local, remote, approval, *, approved_sha256, custody_directory):
    """Spend one independently enrolled pristine custody and send one exact append batch."""
    scope = _selection(approval, approved_sha256)
    row = _row(scope)
    custody = Path(custody_directory)
    with _owned(local, remote, scope, custody) as (fd, database, workbook):
        _check_custody(custody, fd, scope['pristine_custody'], pristine=True)
        payload, body, marker = _claim(scope, approved_sha256, database, row)
        _remote_evidence(remote, workbook, scope, row, marker, committed=False)
        _require(_local_number(local, row) is None and not _has_history(local, row)
                 and _local_identity(local) == database,
                 'Company identity, revision or local Jobs changed before the fresh intake.')
        _check_custody(custody, fd, scope['pristine_custody'], pristine=True)
        _create_claim(fd, payload)
        _check_custody(custody, fd, scope['pristine_custody'])
        remote._execute(remote.service.spreadsheets().batchUpdate(
            spreadsheetId=workbook, body=json.loads(body),
        ), 'write')
        return _recover(local, remote, workbook, scope, row, custody, fd, database, payload, marker)


def _recover(local, remote, workbook, scope, row, custody, fd, database, payload, marker):
    _read_claim(fd, payload)
    number = _remote_evidence(remote, workbook, scope, row, marker, committed=True)
    _check_custody(custody, fd, scope['pristine_custody'])
    _read_claim(fd, payload)
    return _confirm_local(local, workbook, number, row, payload, database)


def recover_intake(local, remote, approval, *, approved_sha256, custody_directory):
    """Reconcile this retained claim with current remote evidence, with no Sheets writes."""
    scope = _selection(approval, approved_sha256)
    row = _row(scope)
    custody = Path(custody_directory)
    with _owned(local, remote, scope, custody) as (fd, database, workbook):
        payload, _, marker = _claim(scope, approved_sha256, database, row)
        return _recover(local, remote, workbook, scope, row, custody, fd, database, payload, marker)
