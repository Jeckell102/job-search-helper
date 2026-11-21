"""Only a synthetic owner can insert a fixture row. The helper sees a read-only service."""

from contextlib import closing
from copy import deepcopy
from hashlib import sha256
import json
from shutil import copyfile

import pytest

import owner_external_company_intake as intake
from job_search_helper.cli import WriterLockBusy, writer_lock
from job_search_helper.repository import GoogleRepository, RepositoryError
from job_search_helper.sheet_profile import COMPACT_PROFILE, COMPACT_SCHEMAS
from job_search_helper.sqlite_repository import SQLiteRepository
from sheets_fixture import RangeSheets


TAB = 'Companies'
WORKBOOK = 'test-only-owner-external-company'
SHEET_ID = 79
TABLE_ID = 'fixture-company-table'
HEADERS = COMPACT_SCHEMAS[TAB]
EXISTING = {'Company': 'Existing Company', 'Company ID': 'COMP-4DA6D3EB2936', 'Notes': 'Keep manual note'}
TAIL = {'Company': 'Outside native table', 'Company ID': 'COMP-FBB34792912E', 'Notes': 'Keep outside values'}


class OwnerFixtureSheets(RangeSheets):
    def __init__(self):
        super().__init__({TAB: [EXISTING, TAIL]}, schemas=COMPACT_SCHEMAS)
        self.sheet(TAB)['properties']['sheetId'] = SHEET_ID
        self.sheet(TAB)['tables'] = [{'tableId': TABLE_ID, 'range': {
            'sheetId': SHEET_ID, 'endRowIndex': 2, 'endColumnIndex': len(HEADERS),
        }}]
        self.external_owner_edits = []

    def batchUpdate(self, **kwargs):
        raise AssertionError('The intake helper must never issue a Sheets write')

    def developerMetadata(self):
        raise AssertionError('The intake helper must never call developer metadata')

    def owner_edit(self, row):
        sheet = self.sheet(TAB)
        bounds = sheet['tables'][0]['range']
        values = [{'userEnteredValue': {'stringValue': row[header]},
                   'effectiveValue': {'stringValue': row[header]}} if header in row else {}
                  for header in HEADERS]
        sheet['data'][0]['rowData'].insert(bounds['endRowIndex'], {'values': values})
        bounds['endRowIndex'] += 1
        self.external_owner_edits.append(deepcopy(row))
        return bounds['endRowIndex']


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()


def digest(data):
    return sha256(data).hexdigest()


@pytest.fixture
def available(tmp_path):
    custody = tmp_path / 'external-owner-proof'
    custody.mkdir(mode=0o700)
    jobs = tmp_path / 'jobs.sqlite3'
    with closing(SQLiteRepository(jobs, WORKBOOK, initialize=True)) as setup:
        setup.set_meta('ready', 'yes')
        setup.set_meta('sheets_profile', COMPACT_PROFILE)
        setup.import_rows(TAB, [(2, EXISTING)])
        setup.bootstrap_company_event_reconciliation()
    service = OwnerFixtureSheets()
    remote = GoogleRepository(service, WORKBOOK, schemas=COMPACT_SCHEMAS, min_request_interval=0)

    info, db = custody.stat(), jobs.stat()
    scope = {
        'schema': 'scoped-owner-external-company-v1', 'owner_sha256': '9' * 64,
        'company_name': 'Freeform', 'company_id': 'COMP-D6223D861357',
        'board_url': 'https://job-boards.greenhouse.io/freeformfixture', 'added_on': '2026-11-20',
        'workbook_sha256': digest(WORKBOOK.encode()), 'sheet_id': SHEET_ID, 'table_id': TABLE_ID,
        'headers': HEADERS[:], 'database': [db.st_dev, db.st_ino],
        'pristine_custody': [info.st_dev, info.st_ino, info.st_ctime_ns, info.st_mtime_ns],
    }
    with intake.open_jobs_for_external_intake(jobs, WORKBOOK) as local:
        yield local, remote, service, custody, scope


def prepare(available, *, scope_changes=None, selection_pin=None):
    local, remote, _, custody, scope = available
    raw = canonical({**scope, **(scope_changes or {})})
    return intake.prepare_absence(local, remote, raw, approved_scope_sha256=selection_pin or digest(raw),
                                  custody_directory=custody)


def confirm(available, observed, *, owner_pin=None, scope_changes=None):
    local, remote, _, custody, scope = available
    selection = canonical({**scope, **(scope_changes or {})})
    raw = canonical(observed)
    return intake.confirm_owner_edit(local, remote, selection, raw, approved_scope_sha256=digest(selection),
                                     approved_owner_edit_sha256=owner_pin or digest(raw), custody_directory=custody)


def owner_edit(available):
    """Fixture operator consumes pre-receipt and provides the independently pinned post evidence."""
    _, _, service, custody, _ = available
    proof = (custody / 'owner-edit-absence.json').read_bytes()
    binding = json.loads(proof)['binding']
    number = service.owner_edit(binding['row'])
    return {'schema': 'scoped-owner-external-confirmed-edit-v1', 'binding': binding,
            'absence_sha256': digest(proof), 'sheet_row': number}


def untouched(available):
    local, _, _, _, scope = available
    assert len(local.read(TAB)) == 1
    assert not local.pending_company_events('bridge')
    assert local.db.execute('SELECT 1 FROM main.company_revisions WHERE company_id=?',
                            (scope['company_id'],)).fetchone() is None
    assert local.db.execute("SELECT 1 FROM main.meta WHERE key LIKE 'scoped_owner_external_intake:%'").fetchone() is None


def test_absence_then_owner_edit_creates_one_exact_external_receipt_and_event(available):
    local, remote, service, custody, scope = available
    original = deepcopy(local.read(TAB))
    pre = prepare(available)
    untouched(available)
    assert pre['state'] == 'OWNER_EDIT_ABSENCE_CONFIRMED'
    pre_path = custody / 'owner-edit-absence.json'
    assert (pre_path.stat().st_mode & 0o777) == 0o600
    assert pre['absence_sha256'] == digest(pre_path.read_bytes())
    assert not service.external_owner_edits

    observed = owner_edit(available)
    first = confirm(available, observed)
    assert first == confirm(available, observed)
    assert first['state'] == 'EXTERNAL_COMPANY_INTAKE_CONFIRMED'
    assert pre['absence_sha256'] == digest(pre_path.read_bytes())
    assert len(service.external_owner_edits) == 1
    assert local.read(TAB)[:1] == original
    event, = local.pending_company_events('bridge')
    assert event['event_id'] == first['event_id']
    assert event['origin'] == 'sheets-reconciliation'
    assert event['company_id'] == scope['company_id'] and event['revision'] == 1
    assert local.db.execute('SELECT count(*) FROM main.dirty').fetchone() == (0,)
    stored, = local.db.execute("SELECT value FROM main.meta WHERE key LIKE 'scoped_owner_external_intake:%'").fetchall()
    receipt = json.loads(stored[0])
    assert digest(stored[0].encode()) == first['receipt_sha256']
    assert receipt['binding'] == observed['binding'] and receipt['sheet_row'] == observed['sheet_row']
    assert receipt['schema'] == 'scoped-owner-external-observed-intake-v1'
    assert receipt['owner_edit_sha256'] == digest(canonical(observed))
    assert receipt['absence_sha256'] == pre['absence_sha256']
    assert [row['Notes'] for row in remote.read(TAB)] == ['Keep manual note', '', 'Keep outside values']


@pytest.mark.parametrize('source', ['remote', 'revision'])
def test_pre_edit_absence_holds_on_earlier_remote_or_local_identity(available, source):
    local, _, service, custody, scope = available
    row = intake._row(scope)
    if source == 'remote':
        service.owner_edit(row)
    else:
        with local.transaction():
            local.db.execute('INSERT INTO main.company_revisions VALUES (?,?,?,?,?,?)',
                             (scope['company_id'], 1, '0' * 64, 1, '{}', 'fixture-time'))
    with pytest.raises(RepositoryError, match='already exists in Sheets|already has a local row'):
        prepare(available)
    assert not list(custody.iterdir())
    assert not local.pending_company_events('bridge')


@pytest.mark.parametrize(('mode', 'reason'), [
    ('wrong_pin', 'independent exact owner-edit'),
    ('owner', 'differs from the exact literal'),
    ('provenance', 'earlier absence proof differs'),
    ('absent', 'absent or moved'),
    ('changed', 'enrolled literal input'),
    ('formula', 'enrolled literal input'),
    ('duplicate', 'Multiple rows'),
    ('foreign_alias', 'collides'),
    ('table', 'table identity'),
    ('headers', 'literal header order'),
])
def test_owner_readback_holds_without_new_local_revision(available, mode, reason):
    _, _, service, custody, _ = available
    prepare(available)
    observed = owner_edit(available)
    kwargs = {}
    if mode == 'wrong_pin':
        kwargs['owner_pin'] = '0' * 64
    elif mode == 'owner':
        observed['binding']['owner_sha256'] = '0' * 64
    elif mode == 'provenance':
        path = custody / 'owner-edit-absence.json'
        path.write_bytes(path.read_bytes().replace(b'exact_identity_absent', b'wrong_identity_absent'))
    elif mode == 'absent':
        service.sheet(TAB)['data'][0]['rowData'].pop(2)
    elif mode == 'changed':
        service.set_cell(TAB, 2, 'Date Added', '2026-11-21')
    elif mode == 'formula':
        service.set_cell(TAB, 2, 'Company Status', cell={'userEnteredValue': {'formulaValue': '="Active"'},
                                                         'effectiveValue': {'stringValue': 'Active'}})
    elif mode == 'duplicate':
        service.owner_edit({**observed['binding']['row'], 'Company ID': 'COMP-AAAAAAAAAAAA'})
    elif mode == 'foreign_alias':
        service.set_cell(TAB, 2, 'Official Careers URL', 'https://boards.greenhouse.io/freeformfixture/')
    elif mode == 'table':
        service.sheet(TAB)['tables'][0]['tableId'] = 'another-native-table'
    else:
        headers = service.sheet(TAB)['data'][0]['rowData'][0]['values']
        headers[0], headers[1] = headers[1], headers[0]
    with pytest.raises(RepositoryError, match=reason):
        confirm(available, observed, **kwargs)
    untouched(available)


def test_owner_attestation_cannot_substitute_for_missing_durable_preproof(available):
    _, _, service, _, scope = available
    row = intake._row(scope)
    approval = {'schema': 'scoped-owner-external-confirmed-edit-v1',
                'binding': intake._binding(scope, digest(canonical(scope))), 'absence_sha256': '0' * 64,
                'sheet_row': service.owner_edit(row)}
    with pytest.raises(RepositoryError, match='pre-owner-edit absence proof is unavailable'):
        confirm(available, approval)
    untouched(available)


def test_preproof_deleted_cannot_be_regenerated_after_owner_edit(available):
    _, _, _, custody, _ = available
    prepare(available)
    approval = owner_edit(available)
    (custody / 'owner-edit-absence.json').unlink()
    with pytest.raises(RepositoryError, match='pristine|already spent'):
        prepare(available)
    with pytest.raises(RepositoryError, match='pre-owner-edit absence proof is unavailable'):
        confirm(available, approval)
    untouched(available)


@pytest.mark.parametrize('changes', [
    {'company_name': 'Atomic Machines'},
    {'company_name': 'Atomic‐Machines'},
    {'board_url': 'https://job-boards.greenhouse.io/atomicmachines'},
    {'board_url': 'https://boards.greenhouse.io/atomicmachines'},
])
def test_legacy_atomic_selection_never_observes_or_creates_custody(available, changes):
    _, _, service, custody, _ = available
    with pytest.raises(RepositoryError, match='legacy Atomic Machines|canonical Greenhouse'):
        prepare(available, scope_changes=changes)
    assert not service.get_calls and not list(custody.iterdir())
    untouched(available)


def test_wrong_scope_digest_and_local_scraper_contention_never_prepare(available):
    local, _, service, custody, _ = available
    with pytest.raises(RepositoryError, match='independent exact owner-external scope'):
        prepare(available, selection_pin='0' * 64)
    with writer_lock(local.path.parent / 'scraper.lock'):
        with pytest.raises(WriterLockBusy):
            prepare(available)
    assert not service.get_calls and not list(custody.iterdir())
    untouched(available)


def test_local_owner_collision_is_not_adopted_after_readback(available):
    local, _, _, _, _ = available
    prepare(available)
    observed = owner_edit(available)
    local.import_rows(TAB, [(observed['sheet_row'], observed['binding']['row'])])
    before = deepcopy(local.read(TAB))
    with pytest.raises(RepositoryError, match='was not imported by this owner-external intake'):
        confirm(available, observed)
    assert local.read(TAB) == before and not local.pending_company_events('bridge')


def test_same_physical_jobs_pin_is_required_before_sheet_read(available):
    _, _, service, custody, scope = available
    device, inode = scope['database']
    with pytest.raises(RepositoryError, match='opened Jobs file or workbook differs'):
        prepare(available, scope_changes={'database': [device, inode + 1]})
    assert not service.get_calls and not list(custody.iterdir())
    untouched(available)


def test_failure_inside_local_transaction_reverts_row_revision_event_and_receipt(available, monkeypatch):
    prepare(available)
    observed = owner_edit(available)

    def reject_readback(*args):
        raise RepositoryError('synthetic exact event readback refusal')

    monkeypatch.setattr(intake, '_required_event', reject_readback)
    with pytest.raises(RepositoryError, match='event readback refusal'):
        confirm(available, observed)
    untouched(available)


def test_replacing_named_jobs_cannot_relabel_the_open_sqlite_connection(available):
    local, _, service, custody, scope = available
    path = local.path
    moved = path.with_name('prior-jobs.sqlite3')
    path.rename(moved)
    copyfile(moved, path)
    replacement = path.stat()
    with pytest.raises(RepositoryError, match='opened Jobs connection lost'):
        prepare(available, scope_changes={'database': [replacement.st_dev, replacement.st_ino]})
    assert not service.get_calls and not list(custody.iterdir())
