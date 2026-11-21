"""Run the real qualified activation + measured shell with exactly one stale queued Company retry."""
from contextlib import closing
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
from tempfile import mkdtemp
from unittest.mock import patch


CONTROLLER = Path('/tmp/jsh-s5-release-controller-join.20261121')
BOOT = CONTROLLER / 'release_admission_bootstrap.py'
OWNER_PIN = '607a08c3d3e4728e411b95cfa9e4bd54a8dbcb767560ff077351e7bc268ebec9'
BOOT_PIN = 'c8a915a8311d74454d292a7f89a0f583b199a5a13832a89f00012cb99c0b500f'
CONTROLLER_PIN = '2cd45aff4d52d3808c41b1bbd36e0c1a3a257634b2df79221185345742adff8c'
RUNNER_PIN = 'f1ade3af7fd4c50baf55078f8c158a8ecd66773f2d8c725ab9dfc4aaa65e26b3'
LAUNCHER_PIN = '2556de3371c32be1991273a1ee88d2baa25753dfcdc73a9656d34de6b91de78c'
COMPANY = 'COMP-0490'


def deny_network(event, _args):
    if event.startswith(('socket.connect', 'socket.getaddrinfo', 'socket.bind', 'socket.gethostbyname')):
        raise RuntimeError('Offline fixture refuses network')


def sha(path):
    return sha256(path.read_bytes()).hexdigest()


def snapshot(directory):
    result = {}
    for name in ('state.db', 'jobs.sqlite3', 'inventories.sqlite3'):
        with closing(sqlite3.connect((directory / name).as_uri() + '?mode=ro', uri=True)) as database:
            result[name] = tuple(database.iterdump())
    return result


def main():
    sys.addaudithook(deny_network)
    assert sys.version_info >= (3, 11)
    root = Path(mkdtemp(prefix='actual-queued-company-', dir=Path(__file__).resolve().parent))
    project, candidate, approval = (root / name for name in ('project', 'candidate', 'approval'))
    project.mkdir(mode=0o700)
    approval.mkdir(mode=0o700)
    selected = (
        'JOB_STORAGE_BACKEND', 'STATE_DB_FILE', 'JOB_DB_FILE', 'SPREADSHEET_ID', 'EVIDENCE_ARCHIVES_FILE',
        'JOB_SCRAPER_CHROMIUM_EXECUTABLE', 'COMPANY_RETAINED_KEY_ID', 'COMPANY_RETAINED_ED25519_PUBLIC_KEY_BASE64',
        'JOB_SEARCH_ORDINARY_CAPTURE_ROOT', 'GOOGLE_CREDENTIALS_FILE', 'GOOGLE_TOKEN_READ_FILE', 'GOOGLE_TOKEN_WRITE_FILE',
    )
    for key in selected:
        os.environ.pop(key, None)
    os.environ.update(JOB_STORAGE_BACKEND='sqlite', STATE_DB_FILE='.state/state.db',
                      JOB_DB_FILE='.state/jobs.sqlite3', SPREADSHEET_ID='fixture-sheet')

    shutil.copytree(CONTROLLER / 'src', project / 'src', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copy2(CONTROLLER / 'job-search-scraper', project / 'job-search-scraper')
    assert sha(BOOT) == BOOT_PIN
    shutil.copy2(BOOT, project / BOOT.name)
    assert sha(project / 'src/job_search_helper/qualified_release_owner.py') == OWNER_PIN
    assert sha(project / 'src/job_search_helper/release_controller.py') == CONTROLLER_PIN
    assert sha(project / 'src/job_search_helper/runner.py') == RUNNER_PIN
    assert sha(project / 'job-search-scraper') == LAUNCHER_PIN
    (project / '.storage-backend').write_text('sqlite\n')
    for name in ('title-blacklist.txt', 'title-review-list.txt'):
        shutil.copy2(CONTROLLER / name, project / name)
    subprocess.run([sys.executable, '-m', 'venv', '--without-pip', str(project / '.venv')], check=True)
    site = next((project / '.venv/lib').glob('python*/site-packages'))
    # This hook is part of the measured dependency tree. It cannot run in the
    # stable bootstrap's -I -S invocation. Only its admitted exec loads it.
    (site / 'fixture_offline_guard.pth').write_text('import fixture_offline_guard\n')
    (site / 'fixture_offline_guard.py').write_text(
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "def offline(event, _args):\n"
        "    if event.startswith(('socket.connect','socket.getaddrinfo','socket.bind','socket.gethostbyname')):\n"
        "        raise RuntimeError('Offline fixture refuses network')\n"
        "sys.addaudithook(offline)\n"
        "if 'JSH_SCRAPER_RUNTIME_BINDING' in os.environ:\n"
        "    def watch_effect(frame, event, _value):\n"
        "        if event != 'call': return\n"
        "        source = frame.f_code.co_filename\n"
        "        effects = {'requested_scan', 'resume_parallel', 'fetch_inventory', 'get_remote_repository', '_recover_exact_cycle_locked'}\n"
        "        if '/src/job_search_helper/' in source and frame.f_code.co_name in effects:\n"
        "            with Path('.state/unexpected-effect.txt').open('a') as log: log.write(frame.f_code.co_name + chr(10))\n"
        "            raise AssertionError('Stale queued Company reached an effect boundary')\n"
        "    sys.setprofile(watch_effect)\n"
        "    with Path('.state/offline-child.json').open('x') as output:\n"
        "        json.dump({'pid': os.getpid(), 'runtime': json.loads(os.environ['JSH_SCRAPER_RUNTIME_BINDING'])}, output)\n"
    )
    shutil.copytree(project / 'src', candidate / 'src')
    for name in ('.storage-backend', 'title-blacklist.txt', 'title-review-list.txt'):
        shutil.copy2(project / name, candidate / name)
    target = 'src/job_search_helper/__init__.py'
    old_bytes = (project / target).read_bytes()
    (candidate / target).write_bytes(old_bytes + b'\n# Exact fixture-only installed revision.\n')

    sys.path.insert(0, str(project / 'src'))
    from job_search_helper.company_events import current_company_source_revision
    from job_search_helper.engine import State
    from job_search_helper.inbox import InventoryInbox
    from job_search_helper.integration_release import (
        MANIFEST_SCHEMA, config_tree_digest, dependency_manifest_digest, digest,
        manifest_release_id, metadata, source_tree_digest,
    )
    from job_search_helper.qualified_release_owner import release_and_continue_qualified
    from job_search_helper.repair_retry import retry_request
    from job_search_helper.scan_request import _read_request
    from job_search_helper.sheet_profile import COMPACT_PROFILE
    from job_search_helper.sqlite_repository import SQLiteRepository

    directory = project / '.state'
    directory.mkdir(mode=0o700)
    database = directory / 'state.db'
    jobs_file = directory / 'jobs.sqlite3'
    queue = directory / 'next-scan.json'
    with (closing(State(database)), closing(InventoryInbox(directory / 'inventories.sqlite3', 'fixture-sheet')),
          closing(SQLiteRepository(jobs_file, 'fixture-sheet', initialize=True)) as jobs):
        jobs.set_meta('ready', 'yes')
        jobs.set_meta('sheets_profile', COMPACT_PROFILE)
        jobs.import_rows('Companies', [(2, {
            'Company ID': COMPANY, 'Company': 'Fixture board', 'Company Status': 'Active',
            'ATS / Source': 'AcquireTM', 'Official Careers URL': 'https://fixture.invalid/board',
        })])

    def revision(company_id):
        with closing(SQLiteRepository(jobs_file, 'fixture-sheet', readonly=True)) as jobs:
            return current_company_source_revision(jobs, company_id)

    verification = {'result': 'PASS', 'scope': 'disposable measured launcher fixture'}
    manifest = {
        'schema': MANIFEST_SCHEMA, 'company_id': COMPANY, 'source_revision': revision(COMPANY),
        'failed_request_id': 'fixture-predecessor',
        'files': {target: {'before': metadata(project / target), 'after': metadata(candidate / target)}},
        'before_source_manifest_sha256': source_tree_digest(project),
        'source_manifest_sha256': source_tree_digest(candidate),
        'dependency_manifest_sha256': dependency_manifest_digest(project),
        'before_config_sha256': config_tree_digest(project), 'config_sha256': config_tree_digest(candidate),
        'validation_receipt_sha256': digest(verification),
    }
    manifest['release_id'] = manifest_release_id(manifest)
    receipt = approval / (manifest['release_id'] + '.json')
    receipt.write_text(json.dumps({
        'schema': 'integration-live-release-qualification-v1', 'result': 'PASS',
        'evidence_class': 'live_normal_dispatch', 'release_qualification': True,
        'manifest_sha256': digest(manifest), 'capture_manifest_sha256': 'c' * 64,
        'candidate_validation_sha256': manifest['validation_receipt_sha256'], 'reviewed_tools_sha256': 'a' * 64,
    }, sort_keys=True, separators=(',', ':')))
    receipt.chmod(0o600)
    identity = approval.stat()
    descriptor = os.open(approval, os.O_RDONLY | os.O_DIRECTORY)
    assert not queue.exists()
    active_revision = revision(COMPANY)
    assert active_revision == manifest['source_revision']

    def verify(installed, expected):
        assert expected == manifest and (installed / target).read_bytes() == (candidate / target).read_bytes()
        compile((installed / target).read_bytes(), str(installed / target), 'exec')
        return verification

    def invoke():
        return release_and_continue_qualified(project, candidate, database, root / 'records', manifest,
            approval_path=approval, approval_fd=descriptor,
            owner_identity=(identity.st_dev, identity.st_ino), approval_sha256=sha(receipt),
            current_source_revision=revision, dependency_digest=lambda: dependency_manifest_digest(project),
            verify=verify)

    real_run = subprocess.run
    launches = []
    evidence = {}

    def fingerprint(path):
        current = path.stat()
        return (current.st_dev, current.st_ino, current.st_mode,
                current.st_size, current.st_mtime_ns, sha(path))

    def effect_boundary(argv, **kwargs):
        assert not launches and argv[0:2] == [str(project / 'job-search-scraper'), 'continue-qualified-repair']
        launches.append(argv)
        assert kwargs['cwd'] == project and kwargs['pass_fds'] == (descriptor,)
        attempt = argv[argv.index('--attempt-id') + 1]
        journal_path = directory / 'integration-release-journal.json'
        intent_path = directory / 'repair-retry/intents' / (attempt + '.json')
        controller_record = root / 'records' / manifest['release_id'] / 'release-to-retry.json'
        journal = json.loads(journal_path.read_bytes())
        intent = json.loads(intent_path.read_bytes())
        assert journal['state'] == 'COMPLETE' and journal['release_id'] == manifest['release_id']
        assert intent['attempt_id'] == attempt and intent['release'] == journal['release']
        assert intent['source_revision'] == active_revision == revision(COMPANY)
        assert _read_request(queue) == (retry_request(intent, enqueued_at=intent['activated_at']), [COMPANY])
        assert json.loads(controller_record.read_bytes())['state'] == 'REQUEST_WRITTEN'
        assert (project / target).read_bytes() == (candidate / target).read_bytes() != old_bytes
        assert not (directory / 'offline-child.json').exists()
        source_before = source_tree_digest(project)
        assert source_before == manifest['source_manifest_sha256']
        private_paths = [queue, journal_path, intent_path, controller_record,
                         Path(journal['record']) / 'manifest.json', Path(journal['record']) / 'receipt.json']
        before = {path: fingerprint(path) for path in private_paths}

        with closing(SQLiteRepository(jobs_file, 'fixture-sheet')) as jobs:
            [(row_id, company)] = jobs.matches('Companies', {'Company ID': COMPANY})
            assert row_id > 0 and company['Company Status'] == 'Active'
            company['Official Careers URL'] = 'https://fixture.invalid/replacement-board'
            jobs.import_companies_with_events([(2, company)], origin='sheets-reconciliation')
        changed_revision = revision(COMPANY)
        assert changed_revision and changed_revision != active_revision
        store_before_worker = snapshot(directory)
        assert before == {path: fingerprint(path) for path in private_paths}

        try:
            real_run(argv, **kwargs, timeout=15)
        except subprocess.CalledProcessError as exc:
            assert exc.returncode == 1, (exc.returncode, exc.stdout, exc.stderr)
            assert 'Qualified retry Company source is no longer current' in exc.stderr, (exc.stdout, exc.stderr)
            assert 'Qualified repair retry:' not in exc.stdout
            evidence['worker_exit'] = exc.returncode
            (root / 'WORKER_STDOUT.txt').write_text(exc.stdout)
            (root / 'WORKER_STDERR.txt').write_text(exc.stderr)
        else:
            raise AssertionError('Measured worker admitted the stale queued retry')

        child = json.loads((directory / 'offline-child.json').read_bytes())
        assert child['pid'] != os.getpid() and child['runtime'] == {'state': 'COMPLETE', **{
            key: value for key, value in journal['release'].items() if key != 'schema'}}
        assert before == {path: fingerprint(path) for path in private_paths}
        assert source_tree_digest(project) == source_before
        assert snapshot(directory) == store_before_worker and revision(COMPANY) == changed_revision
        assert not (directory / 'last-scan-request.json').exists()
        assert not (directory / 'unexpected-effect.txt').exists()
        evidence.update({'attempt_id': attempt, 'queue_sha256': before[queue][-1],
                         'measured_worker_pid': child['pid'], 'source_digest': source_before,
                         'original_company_revision': active_revision, 'changed_company_revision': changed_revision,
                         'unchanged_store_logical_dumps': True, 'unchanged_queue_identity_bytes': True,
                         'unchanged_release_journal_intent_records': True, 'admitted_cycle': False,
                         'request_admission_provider_publication_effects': 0})
        # Preserve the actual parent's propagation of the child hold.
        raise subprocess.CalledProcessError(1, argv)

    try:
        with patch('job_search_helper.qualified_release_owner.subprocess.run', side_effect=effect_boundary):
            try:
                invoke()
            except subprocess.CalledProcessError as exc:
                assert exc.returncode == 1 and len(launches) == 1 and evidence['worker_exit'] == 1
            else:
                raise AssertionError('Qualified owner accepted a stale worker')
    finally:
        os.close(descriptor)
    evidence.update({'result': 'DISPOSABLE_MEASURED_STALE_QUEUED_COMPANY_HELD', 'launch_count': len(launches),
                     'bootstrap_pin': BOOT_PIN, 'runner_pin': RUNNER_PIN, 'controller_pin': CONTROLLER_PIN,
                     'launcher_pin': LAUNCHER_PIN, 'parent_pin': OWNER_PIN})
    (root / 'RESULT.json').write_text(json.dumps(evidence, indent=2, sort_keys=True) + '\n')
    print(root)
    print(json.dumps(evidence, sort_keys=True))


if __name__ == '__main__':
    main()
