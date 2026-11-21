"""Exercise the exact shell control and the dispatcher claims against private stores."""
from contextlib import closing
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess

from job_search_helper.company_intake_dispatcher import CompanyIntakeDispatcher
from job_search_helper.sqlite_repository import SQLiteRepository
from test_ordinary_company_event_command import execute, queued

STAGE = Path('/tmp/jsh-s6-intake-launch-control.20261121')
JOURNAL = 'company-intake-dispatch.sqlite3'
GUARD = '''import os, sys
from pathlib import Path


def restrict(event, args):
    if event.startswith('socket.'):
        raise AssertionError('Launch-control CLI attempted network')
    if event == 'sqlite3.connect':
        database = Path(args[0]).resolve()
        if database != Path(os.environ['FIXTURE_ONLY_DISPATCH_DB']):
            raise AssertionError('Launch-control CLI attempted another SQLite store')


def prohibit_remote_factory(frame, event, _value):
    if event == 'call' and frame.f_code.co_name == 'get_remote_repository':
        raise AssertionError('Launch-control CLI attempted the workbook factory')


sys.addaudithook(restrict)
sys.setprofile(prohibit_remote_factory)
with Path(os.environ['FIXTURE_GUARD_LOG']).open('a') as log:
    log.write(str(os.getpid()) + chr(10))
'''


def sha(path):
    return sha256(path.read_bytes()).hexdigest()


def app_files(root):
    found = {}
    for path in root.rglob('*'):
        if path.is_file() and not path.name.startswith(JOURNAL):
            info = path.stat()
            found[str(path.relative_to(root))] = (info.st_dev, info.st_ino, info.st_mode,
                info.st_size, info.st_mtime_ns, info.st_ctime_ns, sha(path))
    return found


def test_real_shell_control_before_and_after_exact_ordinary_admission(queued, tmp_path):
    paths, request, digest, provider, remote, _, _ = queued
    root = paths[0].parent
    queue = root / 'next-scan.json'
    original = app_files(root)['next-scan.json']
    project = tmp_path.parent / 'launch-control-shell'
    shutil.copytree(STAGE / 'src', project / 'src', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copy2(STAGE / 'job-search-scraper', project / 'job-search-scraper')
    subprocess.run(['/usr/bin/python3.11', '-m', 'venv', '--without-pip', str(project / '.venv')],
                   check=True, timeout=10)
    lib = next((project / '.venv/lib').glob('python*/site-packages'))
    (lib / 'fixture_launch_guard.pth').write_text('import fixture_launch_guard\n')
    (lib / 'fixture_launch_guard.py').write_text(GUARD)
    log = project / 'guard-pids.txt'
    env = {**os.environ, 'PYTHONPATH': '', 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONNOUSERSITE': '1',
           'FIXTURE_ONLY_DISPATCH_DB': str(root / JOURNAL), 'FIXTURE_GUARD_LOG': str(log),
           # Intentionally unusable Jobs/Google configuration in the shell.
           'JOB_DB_FILE': str(root / 'cannot-open-jobs.sqlite3'), 'SPREADSHEET_ID': ''}
    launches = []
    control_calls = []

    def control(action, enabled):
        before = app_files(root)
        completed = subprocess.run(['./job-search-scraper', 'storage', 'intake-scrape-' + action],
                                   cwd=project, env=env, check=True, timeout=10, text=True, capture_output=True)
        assert not completed.stderr, completed.stderr
        assert len(log.read_text().splitlines()) == len(control_calls) + 1
        result = json.loads(completed.stdout)
        assert result['state'] == 'COMPANY_INTAKE_CONTROL' and result['enabled']
        assert result['scrape_enabled'] is enabled
        assert app_files(root) == before
        control_calls.append(result)
        return result

    def child(arguments):
        launches.append(arguments)
        assert arguments[1:] == ('ordinary-company-event', 'admit-fetch', '--request-sha256', digest)
        assert execute(queued)['state'] == 'INVENTORY_FROZEN'
        return 0

    with closing(SQLiteRepository(paths[1], 'sheet')) as jobs:
        legacy = CompanyIntakeDispatcher(jobs, root, child_runner=child)
        assert not legacy.status()['scrape_enabled']
        legacy.set_enabled(True)
        assert legacy.status()['enabled'] and legacy.status()['scrape_enabled']
        assert control('disable', False)['ownership'] == {}
        rebuilt = CompanyIntakeDispatcher(jobs, root, child_runner=child)
        disabled = rebuilt.run_once()
        assert disabled['state'] == 'HELD_SCRAPE_DISABLED' and disabled['request_id'] == request['request_id']
        assert app_files(root)['next-scan.json'] == original
        assert rebuilt.status()['ownership'] == {} and rebuilt.status()['dispatches'] == {}
        assert not launches and provider.call_count == remote.call_count == 0

        assert control('enable', True)['ownership'] == {}
        assert rebuilt.run_once()['state'] == 'ORDINARY_CHILD_RETURNED'
        assert not queue.exists() and len(launches) == 1
        held = rebuilt.run_once()
        assert held['state'] == 'HELD_ORDINARY_PUBLICATION' and held['request_sha256'] == digest
        # An admitted exact continuation remains visible when future starts are paused.
        control('disable', False)
        reopened = CompanyIntakeDispatcher(jobs, root, child_runner=child)
        assert reopened.run_once() == reopened.reconcile_ordinary() == held
        assert len(launches) == provider.call_count == remote.call_count == 1
    result = {'result': 'PASS', 'real_shell_calls': len(control_calls), 'only_dispatch_db_open_allowed': True,
              'workbook_factory_calls_during_control': 0,
              'legacy_missing_key_respects_intake': True, 'disabled': disabled['state'],
              'exact_queue_identity_unchanged_disabled': True, 'disabled_claim_count': 0,
              'enabled_launch_count': len(launches), 'continued_existing_readback': held['state'],
              'request_digest': digest}
    (project / 'RESULT.json').write_text(json.dumps(result, sort_keys=True, indent=2) + '\n')
    print(json.dumps(result, sort_keys=True))


def test_existing_claim_methods_gate_temporary_and_retained_recovery_without_rewriting_prior_rows(tmp_path):
    dispatcher = CompanyIntakeDispatcher(None, tmp_path)
    dispatcher.set_enabled(True)
    normal_id, retained_id = 'temporary-retry:fixture-existing', 'company-event:retained-fixture'
    digest = 'f' * 64
    eligibility = {'exception_cycle': 'CYC-0123456789AB', 'manifest_digest': 'a' * 64}
    cfg = {'key_id': 'fixture-public-key', 'fingerprint': 'b' * 64}
    assert dispatcher._reserve(normal_id, digest) == 'RESERVED'
    dispatcher._finish(normal_id, 'CHILD_LAUNCHED')
    assert dispatcher._claim_retained(retained_id, digest, eligibility, cfg) == 'RESERVED'

    def owned_rows():
        with dispatcher._journal() as db:
            return (db.execute('SELECT * FROM dispatches ORDER BY request_id').fetchall(),
                    db.execute('SELECT * FROM request_ownership ORDER BY request_id').fetchall())

    before = owned_rows()
    dispatcher.set_scrape_enabled(False)
    reopened = CompanyIntakeDispatcher(None, tmp_path)
    assert reopened._reserve('temporary-retry:fixture-new', digest) == 'HELD_SCRAPE_DISABLED'
    assert reopened._resume_reservation(normal_id, digest) == 'HELD_SCRAPE_DISABLED'
    assert reopened._claim_retained('company-event:retained-new', digest, eligibility, cfg) == 'HELD_SCRAPE_DISABLED'
    assert not reopened._record_retained_recoverable(retained_id, 'before denied launch', for_launch=True)
    assert owned_rows() == before
    reopened._record_retained_terminal(retained_id, digest)
    assert reopened._retained_owner(retained_id)['state'] == 'RETAINED_CONSUMED'
    assert reopened.status()['scrape_enabled'] is False
