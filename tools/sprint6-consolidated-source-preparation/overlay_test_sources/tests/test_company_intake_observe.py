import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from job_search_helper.company_events import BRIDGE_CONSUMER
from job_search_helper.repository import SCHEMAS
from job_search_helper.sqlite_repository import SQLiteRepository


def _jobs(path, names):
    jobs = SQLiteRepository(path, 'observe-test', initialize=True)
    for tab in SCHEMAS:
        rows = enumerate(({
            'Company': name, 'Company ID': name, 'Company Status': 'Active',
            'Official Careers URL': f'https://jobs.example.test/{name}',
            'ATS / Source': 'Greenhouse',
        } for name in names), 2) if tab == 'Companies' else ()
        jobs.import_rows(tab, rows)
    jobs.set_meta('ready', 'yes')
    return jobs


def _change(jobs, company, **values):
    return jobs.mutate_company_with_event({
        'tab': 'Companies', 'identity': {'Company ID': company}, 'values': values,
    })['company_event']


def _invoke(root, database):
    guard = root / 'guard'
    guard.mkdir()
    (guard / 'sitecustomize.py').write_text(
        'import os, sys\n'
        'def no_effects(event, args):\n'
        '    if event.startswith(("socket.", "subprocess.")) or event in {\n'
        '        "os.mkdir", "os.rename", "os.remove", "os.chmod", "os.system", "os.exec"\n'
        '    } or (event == "open" and args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT)):\n'
        '        raise RuntimeError("Unexpected CLI side effect: " + event)\n'
        'sys.addaudithook(no_effects)\n',
        encoding='utf-8',
    )
    project = Path(__file__).resolve().parents[1]
    environment = {
        **os.environ, 'PYTHON': sys.executable, 'PYTHONDONTWRITEBYTECODE': '1',
        'PYTHONPATH': str(guard), 'JOB_STORAGE_BACKEND': 'sqlite', 'SPREADSHEET_ID': 'observe-test',
        'JOB_DB_FILE': str(database), 'STATE_DB_FILE': str(root / 'app-state' / 'state.db'),
    }

    def files():
        return {str(path.relative_to(root)): (
            path.stat().st_mode, path.stat().st_mtime_ns,
            hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None,
        ) for path in root.rglob('*')}

    before = files()
    result = subprocess.run([str(project / 'job-search-scraper'), 'storage', 'intake-observe'],
                            cwd=root, env=environment, capture_output=True, text=True, timeout=15)
    assert result.stderr == ''
    assert files() == before
    return result.returncode, json.loads(result.stdout)


def test_observe_real_cli_previews_latest_pending_sources_without_side_effects(tmp_path):
    path = tmp_path / 'jobs.sqlite3'
    jobs = _jobs(path, ['active', 'paused', 'withdrawn', 'stale', 'delivered'])
    try:
        _change(jobs, 'active', **{'ATS / Source': 'Lever'})
        current = _change(jobs, 'active', **{'ATS / Source': 'Workable'})
        _change(jobs, 'paused', **{'ATS / Source': 'Lever'})
        _change(jobs, 'paused', **{'Company Status': 'Paused'})
        _change(jobs, 'withdrawn', **{'ATS / Source': 'Lever'})
        _change(jobs, 'withdrawn', **{'Official Careers URL': ''})
        _change(jobs, 'stale', **{'ATS / Source': 'Lever'})
        [(row_id, row)] = jobs.matches('Companies', {'Company ID': 'stale'})
        jobs.db.execute('DELETE FROM dirty WHERE tab=? AND row_id=?', ('Companies', row_id))
        jobs.import_rows('Companies', [(row_id, {**row, 'ATS / Source': 'Workable'})])
        delivered = _change(jobs, 'delivered', **{'ATS / Source': 'Lever'})
        jobs.acknowledge_company_event(delivered['event_id'], BRIDGE_CONSUMER,
                                       source_revision=delivered['source_revision'])
    finally:
        jobs.close()

    code, report = _invoke(tmp_path, path)
    assert code == 0
    assert report['scope'] == 'LOCAL_LATEST_PENDING_EVENTS_PER_COMPANY'
    assert report['more_events'] is False
    events = {event['company_id']: event for event in report['events']}
    assert events['active']['event_id'] == current['event_id']
    assert {company: event['state'] for company, event in events.items()} == {
        'active': 'PROPOSED_COMPANY_ONLY_SCRAPE', 'paused': 'HELD_INELIGIBLE',
        'withdrawn': 'HELD_WITHDRAWN', 'stale': 'HELD_STALE_SOURCE',
    }


def test_observe_real_cli_holds_committed_wal_without_creating_support_files(tmp_path):
    path = tmp_path / 'jobs.sqlite3'
    jobs = _jobs(path, ['active'])
    try:
        jobs.db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        _change(jobs, 'active', **{'ATS / Source': 'Lever'})
        assert path.with_name('jobs.sqlite3-wal').stat().st_size > 0
        code, report = _invoke(tmp_path, path)
        assert code == 1
        assert report['state'] == 'STATUS_SNAPSHOT_BUSY'
        assert 'events' not in report
    finally:
        jobs.close()


def test_observe_real_cli_caps_the_page_and_reports_additional_pending_events(tmp_path):
    path = tmp_path / 'jobs.sqlite3'
    names = [f'company-{index}' for index in range(101)]
    jobs = _jobs(path, names)
    try:
        for name in names:
            _change(jobs, name, **{'ATS / Source': 'Lever'})
    finally:
        jobs.close()

    code, report = _invoke(tmp_path, path)
    assert code == 0
    assert report['more_events'] is True
    assert len(report['events']) == 100
