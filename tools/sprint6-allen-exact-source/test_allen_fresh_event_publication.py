"""Publish one verified fresh Allen result while keeping the real old-source fence."""

from contextlib import closing
from unittest.mock import Mock

import pytest

from job_search_helper import ats
from job_search_helper.allen_source_reconciliation import (
    AFTER, BEFORE, COMPANY_ID, COMPANY_NAME, continue_allen_source_reconciliation,
)
from job_search_helper.cli import writer_lock
from job_search_helper.company_events import CompanyEventBridge, read_verified_ordinary_event_admission, source_revision
from job_search_helper.engine import Engine, State
from job_search_helper.inbox import InventoryInbox
from job_search_helper.ordinary_company_event_fetch import freeze_ordinary_event_locked
from job_search_helper.ordinary_company_event_publication import publish_ordinary_event_locked
from job_search_helper.repository import GoogleRepository
from job_search_helper.scan_request import requested_scan
from job_search_helper.sheet_profile import COMPACT_PROFILE, COMPACT_SCHEMAS
from job_search_helper.sheets_sync import SheetsSynchronizer
from job_search_helper.sqlite_repository import SQLiteRepository
from sheets_fixture import RangeSheets


RUNTIME = {'state': 'NO_RELEASE', 'source_manifest_sha256': 'a' * 64,
           'config_sha256': 'b' * 64, 'dependency_manifest_sha256': 'c' * 64}
WORKBOOK = 'sheet'


def source_fences(local):
    return local.db.execute(
        "SELECT * FROM conflicts WHERE header='__company_source__' ORDER BY tab,row_id"
    ).fetchall()


def test_new_ordinary_receipt_keeps_old_source_fences(tmp_path):
    db, jobs, saved = (tmp_path / name for name in ('state.db', 'jobs.sqlite3', 'inventories.sqlite3'))
    company = {'Company ID': COMPANY_ID, 'Company': COMPANY_NAME, 'Company Status': 'Active', **BEFORE}
    other = {'Company ID': 'COMP-9999', 'Company': 'Unrelated', 'Company Status': 'Paused', **BEFORE}
    old_job = {'Job Key': 'old-allen', 'Company': COMPANY_NAME, 'Job Title': 'Old source role',
               'Official Job URL': BEFORE['Official Careers URL'] + '/jobs/123',
               'Job Status': 'Closed', 'Salary / Range': 'Estimated $120000-$150000'}
    sheets = RangeSheets({'Companies': [company, other], 'Job History': [old_job]}, schemas=COMPACT_SCHEMAS)
    remote = GoogleRepository(sheets, WORKBOOK, schemas=COMPACT_SCHEMAS, min_request_interval=0)
    intent = {'schema': 'allen-source-reconciliation-v1', 'spreadsheet_id': WORKBOOK,
              'company_id': COMPANY_ID, 'company': COMPANY_NAME, 'company_status': 'Active',
              'before': BEFORE, 'after': AFTER, 'expected_source_revision': source_revision(company)}

    with (closing(State(str(db))) as state, closing(InventoryInbox(saved, WORKBOOK)),
          closing(SQLiteRepository(jobs, WORKBOOK, initialize=True)) as local):
        local.set_meta('ready', 'yes')
        local.set_meta('sheets_profile', COMPACT_PROFILE)
        local.ensure_columns('Opportunities', ['Opportunity ID'])
        local.import_rows('Companies', [(2, company), (3, other)])
        local.import_rows('Job History', [(2, old_job)])
        local.bootstrap_company_event_reconciliation()
        local.commit([{'tab': 'Job History', 'identity': {'Job Key': 'old-allen'},
                       'values': {'Last Checked': 'keep old pending value'}}])
        kept_job = local.read_row('Job History', 2)
        assert continue_allen_source_reconciliation(local, remote, intent)['state'] == 'COMPLETE'
        CompanyEventBridge(local, tmp_path).process_pending()
        with writer_lock(tmp_path / 'scraper.lock'), writer_lock(tmp_path / 'writer.lock'):
            cid = requested_scan(Engine(local, state, runtime_binding=RUNTIME), state, db)
        request_sha = read_verified_ordinary_event_admission(local, state, cid)['request_sha256']
        assert source_revision(local.read_row('Companies', 2)) == source_revision({**company, **AFTER})
        fences = source_fences(local)
        assert {row[0] for row in fences} == {'Companies', 'Job History'}

    job = {'title': 'Implementation Manager', 'posting_id': 'fixture-42', 'location': 'Remote, United States',
           'url': AFTER['Official Careers URL'] + '/fixture-42', 'ats': 'Ashby',
           'description': ('Coordinate customer implementation, plan program delivery, and test rollout. ' * 110)}
    provider = Mock(return_value=ats.Inventory('complete', [job], source_url=AFTER['Official Careers URL'], ats='Ashby'))
    with (writer_lock(tmp_path / 'scraper.lock'), writer_lock(tmp_path / 'writer.lock'),
          closing(SQLiteRepository(jobs, WORKBOOK, readonly=True)) as reader,
          closing(State(str(db), readonly=True)) as state):
        assert freeze_ordinary_event_locked(reader, state, RUNTIME, cycle_id=cid,
                                            request_sha256=request_sha, fetcher=provider,
                                            remote_reader=lambda: remote)['state'] == 'INVENTORY_FROZEN'
    provider.assert_called_once()

    with (writer_lock(tmp_path / 'scraper.lock'), writer_lock(tmp_path / 'writer.lock'),
          closing(SQLiteRepository(jobs, WORKBOOK)) as local, closing(State(str(db))) as state,
          closing(InventoryInbox(saved, WORKBOOK)) as inbox):
        engine = Engine(local, state, inbox=inbox, runtime_binding=RUNTIME, error_log_path=tmp_path / 'errors.jsonl')
        receipt = publish_ordinary_event_locked(engine, lambda: remote, cycle_id=cid, request_sha256=request_sha)
        assert receipt['state'] == 'SYNC_CONFIRMED'
        assert local.read_row('Job History', 2) == kept_job
        assert source_fences(local) == fences
        assert remote.read_row('Companies', 3)['Company Status'] == 'Paused'
        assert remote.read_row('Job History', 2)['Salary / Range'] == old_job['Salary / Range']
        assert any(row.get('Official Job URL') == job['url'] for row in local.read('Job History'))

        rid, current = local.matches('Companies', {'Company ID': COMPANY_ID})[0]
        row_scope = {'tab': 'Companies', 'row_id': rid, 'identity': {'Company ID': COMPANY_ID},
                     'fields': ['Last Checked'], 'append_if_missing': False, 'guards': {}, 'expected': {}}
        with pytest.raises(ValueError, match='unresolved conflict'):
            SheetsSynchronizer(local, remote)._plan_exact_row(row_scope)
        with pytest.raises(TypeError, match='ordinary_company_binding'):
            SheetsSynchronizer(local, remote).plan_exact_scope(
                [row_scope], [], ordinary_company_binding=receipt['binding'])
        with pytest.raises(ValueError, match='unresolved conflict'):
            SheetsSynchronizer(local, remote)._plan_exact_row(
                row_scope, ordinary_company_binding={**receipt['binding'], 'source_revision': '0' * 64})
        assert source_revision(current) == source_revision({**company, **AFTER})
