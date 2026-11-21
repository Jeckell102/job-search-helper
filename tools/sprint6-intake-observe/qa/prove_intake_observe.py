"""Run the actual storage intake-observe shell on an isolated SQLite fixture."""
from contextlib import closing
from hashlib import sha256
from pathlib import Path
from tempfile import mkdtemp
import json
import os
import shutil
import subprocess
import sys


STAGE = Path('/tmp/jsh-s6-intake-observe.20261121')
GUARD = '''from pathlib import Path
import os
import sys

WATCHED = {
    'writer_lock', 'requested_scan', 'acknowledge_company_event',
    'process_pending', '_deliver', '_deliver_eligible', '_deliver_cancellation',
    'get_remote_repository', 'fetch_inventory', 'resume_parallel', 'publish_batch',
}


def reject_effect(frame, event, _value):
    if event == 'call' and '/src/job_search_helper/' in frame.f_code.co_filename:
        if frame.f_code.co_name in WATCHED:
            raise AssertionError('Observe-only command invoked ' + frame.f_code.co_name)


def reject_transport(event, _args):
    if event.startswith(('socket.connect', 'socket.getaddrinfo', 'socket.gethostbyname', 'socket.bind', 'socket.sendto')):
        raise AssertionError('Observe-only command invoked network')


sys.addaudithook(reject_transport)
sys.setprofile(reject_effect)
with Path(os.environ['INTAKE_FIXTURE_GUARD_LOG']).open('a') as observed:
    observed.write(str(os.getpid()) + chr(10))
'''


def sha(path):
    return sha256(path.read_bytes()).hexdigest()


def snapshot(root):
    result = {}
    for path in (root, *sorted(root.rglob('*'))):
        info = path.stat()
        stamp = (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        result[str(path.relative_to(root))] = (stamp, sha(path) if path.is_file() else None)
    return result


def row(company, url, status='Active'):
    return {'Company ID': company, 'Company': f'Fixture {company}', 'Company Status': status,
            'Official Careers URL': f'https://observed.example.test/{url}' if url else '',
            'ATS / Source': 'Greenhouse'}


def record(repository, index, company, url, status='Active'):
    [event] = repository.import_companies_with_events(
        [(index, row(company, url, status))], origin='sheets-reconciliation')['company_events']
    return event


def active_ids(report):
    return [evt['event_id'] for evt in report['events'] if evt['state'] == 'PROPOSED_COMPANY_ONLY_SCRAPE']


def normal_report(value):
    assert value['state'] == 'COMPANY_INTAKE_OBSERVATION', value
    assert value['scope'] == 'LOCAL_LATEST_PENDING_EVENTS_PER_COMPANY' and value['more_events'] is False, value
    return {evt['event_id']: evt['state'] for evt in value['events']}


def setup(project):
    shutil.copytree(STAGE / 'src', project / 'src', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copy2(STAGE / 'job-search-scraper', project / 'job-search-scraper')
    shutil.copy2(STAGE / 'release_admission_bootstrap.py', project / 'release_admission_bootstrap.py')
    (project / '.storage-backend').write_text('sqlite\n')
    subprocess.run([sys.executable, '-m', 'venv', '--without-pip', str(project / '.venv')], check=True)
    site = next((project / '.venv/lib').glob('python*/site-packages'))
    (site / 'fixture_observer_guard.pth').write_text('import fixture_observer_guard\n')
    (site / 'fixture_observer_guard.py').write_text(GUARD)


def run(root):
    project = root / 'project'
    setup(project)
    sys.path.insert(0, str(project / 'src'))
    from job_search_helper.engine import State
    from job_search_helper.inbox import InventoryInbox
    from job_search_helper.sheet_profile import COMPACT_PROFILE
    from job_search_helper.sqlite_repository import SQLiteRepository

    state_dir = project / '.state'
    state_dir.mkdir(mode=0o700)
    jobs_file = state_dir / 'jobs.sqlite3'
    with (closing(State(state_dir / 'state.db')),
          closing(InventoryInbox(state_dir / 'inventories.sqlite3', 'observed-fixture-sheet')),
          closing(SQLiteRepository(jobs_file, 'observed-fixture-sheet', initialize=True)) as jobs):
        jobs.set_meta('ready', 'yes')
        jobs.set_meta('sheets_profile', COMPACT_PROFILE)
        first = record(jobs, 2, 'COMP-1001', 'earlier')
        latest = record(jobs, 2, 'COMP-1001', 'newest')
        stale = record(jobs, 3, 'COMP-1002', 'captured')
        jobs.import_rows('Companies', [(3, row('COMP-1002', 'changed-outside-outbox'))])
        before_withdrawal = record(jobs, 4, 'COMP-1003', 'withdrawal')
        withdrawal = record(jobs, 4, 'COMP-1003', None)
    assert latest['revision'] > first['revision'] and withdrawal['revision'] > before_withdrawal['revision']
    assert not any(state_dir.glob('*-wal')) and not any(state_dir.glob('*-shm'))

    scratch = root / 'child-tmp'
    scratch.mkdir(mode=0o700)
    guards = root / 'guard_pids.txt'
    environment = {**os.environ, 'JOB_STORAGE_BACKEND': 'sqlite', 'JOB_DB_FILE': '.state/jobs.sqlite3',
        'STATE_DB_FILE': '.state/state.db', 'SPREADSHEET_ID': 'observed-fixture-sheet',
        'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONNOUSERSITE': '1', 'TMPDIR': str(scratch),
        'INTAKE_FIXTURE_GUARD_LOG': str(guards)}
    for key in ('PYTHONPATH', 'GOOGLE_CREDENTIALS_FILE', 'GOOGLE_TOKEN_READ_FILE', 'GOOGLE_TOKEN_WRITE_FILE',
                'JSH_SCRAPER_ADMISSION_FD', 'JSH_SCRAPER_ADMISSION_PATH', 'JSH_SCRAPER_RUNTIME_BINDING'):
        environment.pop(key, None)

    def observe(label, exit_code):
        before = snapshot(state_dir)
        before_guards = guards.read_text().splitlines() if guards.exists() else []
        result = subprocess.run(['./job-search-scraper', 'storage', 'intake-observe'], cwd=project, env=environment,
                                capture_output=True, text=True, timeout=12)
        (root / f'{label}.stdout').write_text(result.stdout)
        (root / f'{label}.stderr').write_text(result.stderr)
        assert result.returncode == exit_code, (result.returncode, result.stdout, result.stderr)
        assert not result.stderr, result.stderr
        after_guards = guards.read_text().splitlines()
        assert after_guards[:-1] == before_guards and int(after_guards[-1]) != os.getpid()
        assert snapshot(state_dir) == before, 'Intake observation changed local paths or bytes'
        assert not (state_dir / 'next-scan.json').exists() and not (state_dir / 'scraper.lock').exists()
        return json.loads(result.stdout)

    checkpointed = observe('CHECKPOINTED', 0)
    decisions = normal_report(checkpointed)
    assert decisions == {latest['event_id']: 'PROPOSED_COMPANY_ONLY_SCRAPE',
        stale['event_id']: 'HELD_STALE_SOURCE', withdrawal['event_id']: 'HELD_WITHDRAWN'}, decisions
    assert first['event_id'] not in decisions and before_withdrawal['event_id'] not in decisions
    assert active_ids(checkpointed) == [latest['event_id']]

    with closing(SQLiteRepository(jobs_file, 'observed-fixture-sheet')) as jobs:
        jobs.db.execute('PRAGMA wal_autocheckpoint=0')
        digest_before = sha(jobs_file)
        wal_latest = record(jobs, 2, 'COMP-1001', 'newest-committed-to-wal')
        assert latest['revision'] < wal_latest['revision'] and sha(jobs_file) == digest_before
        wal = jobs_file.with_name(jobs_file.name + '-wal')
        assert (wal_bytes := wal.stat().st_size) > 0
        busy = observe('COMMITTED_WAL', 1)
        assert busy['state'] == 'STATUS_SNAPSHOT_BUSY' and not busy.get('events'), busy

    next_report = observe('AFTER_CHECKPOINT', 0)
    assert normal_report(next_report) == {wal_latest['event_id']: 'PROPOSED_COMPANY_ONLY_SCRAPE',
        stale['event_id']: 'HELD_STALE_SOURCE', withdrawal['event_id']: 'HELD_WITHDRAWN'}, next_report
    assert active_ids(next_report) == [wal_latest['event_id']]
    result = {'result': 'PASS', 'normal_shell_route': './job-search-scraper storage intake-observe',
              'checkpointed_events': checkpointed, 'committed_wal': busy, 'committed_wal_bytes': wal_bytes,
              'events_after_checkpoint': next_report, 'application_paths_inode_mode_mtime_ctime_and_bytes_unchanged': True,
              'guarded_subprocess_count': len(guards.read_text().splitlines()),
              'created_queue_or_lease': False, 'profile_watched_request_ack_provider_workbook_effects': 0}
    (root / 'RESULT.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(root)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    run(Path(mkdtemp(prefix='shell-observe-', dir=Path(__file__).resolve().parent)))
