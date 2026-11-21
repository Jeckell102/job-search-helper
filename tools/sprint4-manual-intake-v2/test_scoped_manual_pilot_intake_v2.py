"""Disposable SQLite and synthetic Sheets only."""

from copy import deepcopy
from hashlib import sha256
import json

import pytest

import scoped_manual_pilot_intake_v2 as intake
from job_search_helper.repository import GoogleRepository, RepositoryError, UncertainWriteError
from job_search_helper.sheet_profile import COMPACT_PROFILE, COMPACT_SCHEMAS
from job_search_helper.sqlite_repository import SQLiteRepository
from sheets_fixture import RangeSheets


TAB = 'Companies'
WORKBOOK = 'test-only-manual-intake-v2'
SHEET_ID = 19
TABLE_ID = 'native-company-table'
METADATA_ID = 1_961_188_331
HEADERS = COMPACT_SCHEMAS[TAB]
EXISTING = {'Company': 'Existing Fixture', 'Company ID': 'COMP-4DA6D3EB2936', 'Notes': 'keep exactly'}
TAIL = {'Company': 'Fixture outside table', 'Company ID': 'COMP-FBB34792912E', 'Notes': 'outside tail survives'}


class Reply:
    def __init__(self, function):
        self.function = function

    def execute(self, num_retries=0):
        return self.function()


class FixtureSheets(RangeSheets):
    """Apply or reject both requests as one synthetic Sheets mutation."""

    def __init__(self):
        super().__init__({TAB: [EXISTING, TAIL]}, schemas=COMPACT_SCHEMAS)
        self.markers = {}
        self.metadata_searches = []
        self.before_search = None
        self.sheet(TAB)['properties']['sheetId'] = SHEET_ID
        self.sheet(TAB)['tables'] = [{'tableId': TABLE_ID, 'range': {
            'sheetId': SHEET_ID, 'endRowIndex': 2, 'endColumnIndex': len(HEADERS),
        }}]

    def developerMetadata(self):
        return self

    def search(self, *, spreadsheetId, body, fields):
        assert spreadsheetId == WORKBOOK
        assert 'developerMetadata' in fields
        assert body == {'dataFilters': [{'developerMetadataLookup': {'metadataId': METADATA_ID}}]}
        self.metadata_searches.append(body)

        def read():
            if self.before_search is not None:
                self.before_search()
            marker = self.markers.get(METADATA_ID)
            return {'matchedDeveloperMetadata': [{'developerMetadata': deepcopy(marker)}]} if marker else {}

        return Reply(read)

    def batchUpdate(self, *, spreadsheetId, body):
        self.batches.append({'spreadsheetId': spreadsheetId, 'body': deepcopy(body)})

        def write():
            if self.before_write is not None:
                self.before_write()
            assert spreadsheetId == WORKBOOK
            metadata, append = body['requests']
            marker = deepcopy(metadata['createDeveloperMetadata']['developerMetadata'])
            row = append['appendCells']
            assert set(row) == {'tableId', 'sheetId', 'fields', 'rows'}
            assert (row['tableId'], row['sheetId'], row['fields']) == (TABLE_ID, SHEET_ID, 'userEnteredValue')
            assert marker['location'] == {'spreadsheet': True} and marker['visibility'] == 'DOCUMENT'
            if marker['metadataId'] in self.markers:
                raise ValueError('synthetic duplicate-ID batch rejection')
            values, = row['rows']
            inserted = deepcopy(values)
            for cell in inserted['values']:
                if cell:
                    cell['effectiveValue'] = deepcopy(cell['userEnteredValue'])
            sheet = self.sheet(TAB)
            bounds = sheet['tables'][0]['range']
            sheet['data'][0]['rowData'].insert(bounds['endRowIndex'], inserted)
            bounds['endRowIndex'] += 1
            self.markers[marker['metadataId']] = {**marker, 'location': {'spreadsheet': True,
                                                                         'locationType': 'SPREADSHEET'}}
            if self.lose_response:
                raise TimeoutError('synthetic response lost after commit')
            return {'replies': [{}, {}]}

        return Reply(write)


@pytest.fixture
def enrolled(tmp_path):
    custody = tmp_path / 'fresh-custody'
    custody.mkdir(mode=0o700)
    local = SQLiteRepository(tmp_path / 'jobs.sqlite3', WORKBOOK, initialize=True)
    local.set_meta('ready', 'yes')
    local.set_meta('sheets_profile', COMPACT_PROFILE)
    local.import_rows(TAB, [(2, EXISTING)])
    local.bootstrap_company_event_reconciliation()
    service = FixtureSheets()
    remote = GoogleRepository(service, WORKBOOK, schemas=COMPACT_SCHEMAS, min_request_interval=0)
    info = custody.stat()
    scope = {
        'schema': 'scoped-manual-pilot-company-scope-v2', 'company_name': 'Field Fixture Company',
        'company_id': 'COMP-D6223D861357', 'board_url': 'https://job-boards.greenhouse.io/fieldfixture',
        'added_on': '2026-11-20', 'workbook_sha256': sha256(WORKBOOK.encode()).hexdigest(),
        'sheet_id': SHEET_ID, 'table_id': TABLE_ID, 'headers': HEADERS[:], 'metadata_id': METADATA_ID,
        'pristine_custody': [info.st_dev, info.st_ino, info.st_ctime_ns, info.st_mtime_ns],
    }
    yield local, remote, service, custody, scope
    local.close()


def invoke(enrolled, *, recover=False, changes=None, approved_sha256=None):
    local, remote, _, custody, scope = enrolled
    raw = json.dumps({**scope, **(changes or {})}, sort_keys=True, ensure_ascii=False,
                     separators=(',', ':')).encode()
    routine = intake.recover_intake if recover else intake.start_new_intake
    return routine(local, remote, raw, approved_sha256=approved_sha256 or sha256(raw).hexdigest(),
                   custody_directory=custody)


def never_local(enrolled):
    local, _, _, _, _ = enrolled
    assert len(local.read(TAB)) == 1
    assert not local.pending_company_events('bridge')


def test_one_atomic_append_shape_and_same_confirmed_readback(enrolled):
    local, remote, service, custody, scope = enrolled
    old = deepcopy(local.read(TAB))
    result = invoke(enrolled)
    assert result == invoke(enrolled, recover=True)
    assert result['state'] == 'COMPANY_INTAKE_CONFIRMED'
    assert len(service.batches) == 1 and len(service.markers) == 1
    assert local.read(TAB)[:1] == old
    assert local.pending_company_events('bridge')[0]['event_id'] == result['event_id']
    assert local.db.execute('SELECT count(*) FROM main.dirty').fetchone() == (0,)
    assert [row['Notes'] for row in remote.read(TAB)] == ['keep exactly', '', 'outside tail survives']
    claim_path = custody / 'append-claim.json'
    claim = json.loads(claim_path.read_bytes())
    request = service.batches[0]
    assert claim['body'] == request['body'] and request['spreadsheetId'] == WORKBOOK
    assert claim['body_sha256'] == sha256(intake._canonical(claim['body'])).hexdigest()
    assert claim['intent']['row']['Company'] == scope['company_name']
    marker, append = claim['body']['requests']
    assert marker['createDeveloperMetadata']['developerMetadata']['metadataValue'] == sha256(
        intake._canonical(claim['intent'])).hexdigest()
    assert len(append['appendCells']['rows']) == 1 and append['appendCells']['sheetId'] == SHEET_ID
    assert claim_path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(RepositoryError, match='already spent'):
        invoke(enrolled)
    assert len(service.batches) == 1


def test_timeout_before_commit_is_spent_and_never_replayed(enrolled):
    _, remote, service, custody, _ = enrolled

    def timeout():
        raise TimeoutError('unknown server response before fixture commit')

    service.before_write = timeout
    with pytest.raises(UncertainWriteError):
        invoke(enrolled)
    claim_path = custody / 'append-claim.json'
    claim = claim_path.read_bytes()
    for _ in range(2):
        with pytest.raises(RepositoryError, match='marker is missing'):
            invoke(enrolled, recover=True)
    assert claim_path.read_bytes() == claim
    claim_path.unlink()
    with pytest.raises(RepositoryError, match='retained v2 append claim is missing'):
        invoke(enrolled, recover=True)
    with pytest.raises(RepositoryError, match='already spent'):
        invoke(enrolled)
    never_local(enrolled)
    assert len(remote.read(TAB)) == 2 and len(service.batches) == 1 and not service.markers


def test_timeout_after_commit_reconciles_one_event_without_resending(enrolled):
    _, _, service, custody, _ = enrolled
    service.lose_response = True
    with pytest.raises(UncertainWriteError):
        invoke(enrolled)
    never_local(enrolled)
    claim = (custody / 'append-claim.json').read_bytes()
    result = invoke(enrolled, recover=True)
    assert result == invoke(enrolled, recover=True)
    assert (custody / 'append-claim.json').read_bytes() == claim
    assert len(service.batches) == 1


@pytest.mark.parametrize(('change', 'reason'), [
    ('marker_gone', 'marker is missing'),
    ('marker_wrong_value', 'marker differs'),
    ('marker_wrong_visibility', 'marker differs'),
    ('marker_wrong_location', 'not spreadsheet-scoped'),
    ('row_gone', 'row is missing'),
    ('row_edited', 'enrolled literal input'),
    ('row_formula', 'enrolled literal input'),
    ('row_extra_cell', 'unenrolled value'),
    ('row_duplicate_alias', 'Multiple rows'),
    ('marker_changed_on_second_read', 'changed during Company readback'),
])
def test_lost_success_requires_current_exact_marker_and_literal_row(enrolled, change, reason):
    _, _, service, _, _ = enrolled
    service.lose_response = True
    with pytest.raises(UncertainWriteError):
        invoke(enrolled)
    if change == 'marker_gone':
        service.markers.clear()
    elif change == 'marker_wrong_value':
        service.markers[METADATA_ID]['metadataValue'] = '0' * 64
    elif change == 'marker_wrong_visibility':
        service.markers[METADATA_ID]['visibility'] = 'PROJECT'
    elif change == 'marker_wrong_location':
        service.markers[METADATA_ID]['location'] = {'sheetId': SHEET_ID, 'locationType': 'SHEET'}
    elif change == 'row_gone':
        service.sheet(TAB)['data'][0]['rowData'].pop(2)
        service.sheet(TAB)['tables'][0]['range']['endRowIndex'] -= 1
    elif change == 'row_edited':
        service.set_cell(TAB, 2, 'Company Status', 'Inactive')
    elif change == 'row_formula':
        service.set_cell(TAB, 2, 'Company Status', cell={'userEnteredValue': {'formulaValue': '="Active"'},
                                                         'effectiveValue': {'stringValue': 'Active'}})
    elif change == 'row_extra_cell':
        service.set_cell(TAB, 2, 'Notes', 'unexpected manual cell')
    elif change == 'row_duplicate_alias':
        service.set_cell(TAB, 3, 'Official Careers URL', 'https://boards.greenhouse.io/fieldfixture/')
    else:
        initial_reads = len(service.metadata_searches)
        service.before_search = lambda: service.markers.clear() if len(service.metadata_searches) == initial_reads + 2 else None
    with pytest.raises(RepositoryError, match=reason):
        invoke(enrolled, recover=True)
    assert len(service.batches) == 1
    never_local(enrolled)


def test_collision_racing_batch_does_not_append_or_allocate_another_id(enrolled):
    _, remote, service, _, _ = enrolled

    def collide():
        service.markers[METADATA_ID] = {'metadataId': METADATA_ID, 'metadataKey': 'foreign',
                                       'metadataValue': 'foreign', 'location': {'spreadsheet': True},
                                       'visibility': 'DOCUMENT'}

    service.before_write = collide
    with pytest.raises(UncertainWriteError):
        invoke(enrolled)
    with pytest.raises(RepositoryError, match='marker differs'):
        invoke(enrolled, recover=True)
    never_local(enrolled)
    assert len(service.batches) == 1 and len(remote.read(TAB)) == 2


@pytest.mark.parametrize(('changes', 'reason'), [
    ({'company_name': '  Atomic Machines'}, 'outside the exact enrollment'),
    ({'company_name': 'Atomic-Machines'}, 'legacy Atomic Machines'),
    ({'board_url': 'https://job-boards.greenhouse.io/atomicmachines'}, 'legacy Atomic Machines'),
    ({'board_url': 'https://boards.greenhouse.io/atomicmachines/'}, 'outside the exact enrollment'),
    ({'metadata_id': True}, 'outside enrollment'),
    ({'metadata_id': 2**31}, 'outside enrollment'),
    ({'table_id': 'wrong-table'}, 'table identity'),
    ({'sheet_id': 0}, 'table identity'),
])
def test_legacy_or_malformed_scope_never_creates_claim(enrolled, changes, reason):
    _, _, service, custody, _ = enrolled
    with pytest.raises(RepositoryError, match=reason):
        invoke(enrolled, changes=changes)
    assert not list(custody.iterdir()) and not service.batches
    never_local(enrolled)


def test_denies_claim_from_v1_even_with_current_exact_remote_row_and_marker(enrolled):
    _, _, service, custody, _ = enrolled
    service.lose_response = True
    with pytest.raises(UncertainWriteError):
        invoke(enrolled)
    path = custody / 'append-claim.json'
    path.write_text('{"version":1}\n')
    with pytest.raises(RepositoryError, match='claim differs'):
        invoke(enrolled, recover=True)
    assert len(service.batches) == 1
    never_local(enrolled)


def test_wrong_approval_pin_and_changed_headers_stop_before_claim_or_append(enrolled):
    _, _, service, custody, _ = enrolled
    with pytest.raises(RepositoryError, match='independent exact'):
        invoke(enrolled, approved_sha256='0' * 64)
    assert not service.get_calls and not service.metadata_searches
    header = service.sheet(TAB)['data'][0]['rowData'][0]['values']
    header[0], header[1] = header[1], header[0]
    with pytest.raises(RepositoryError, match='literal header order'):
        invoke(enrolled)
    assert not list(custody.iterdir()) and not service.batches
    never_local(enrolled)
