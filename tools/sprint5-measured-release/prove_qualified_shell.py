"""Run the real qualified activation + measured shell with a foreign fixture queue."""
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


CONTROLLER = Path('/tmp/jsh-s5-release-controller-join.20261121')
BOOT = Path('/home/chris/job-search-helper_old/release_admission_bootstrap.py')
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
    root = Path(mkdtemp(prefix='actual-', dir=Path(__file__).resolve().parent))
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
    from job_search_helper.sheet_profile import COMPACT_PROFILE
    from job_search_helper.sqlite_repository import SQLiteRepository

    directory = project / '.state'
    directory.mkdir(mode=0o700)
    database = directory / 'state.db'
    jobs_file = directory / 'jobs.sqlite3'
    queue = directory / 'next-scan.json'
    foreign = b'{"mode":"fresh-full-scan","request_id":"foreign-fixture-full-scan","start_last":[]}\n'
    queue.write_bytes(foreign)
    queue_stat = queue.stat()
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
    before = snapshot(directory)

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

    try:
        cycle = {'id': 'CYC-CCCCCCCCCCCC', 'status': 'In Progress', 'all': False, 'companies': {}}
        with closing(State(database)) as state:
            state.save_cycle(cycle)
        protected = snapshot(directory)
        try:
            invoke()
        except ValueError as exc:
            assert 'Unfinished scrape work' in str(exc), str(exc)
        else:
            raise AssertionError('Fixture installation accepted an unfinished cycle')
        assert snapshot(directory) == protected and queue.read_bytes() == foreign
        assert (project / target).read_bytes() == old_bytes
        assert not (directory / 'integration-release-journal.json').exists()
        assert not (directory / 'offline-child.json').exists() and not (root / 'records').exists()
        with closing(State(database)) as state, state.connection:
            state.connection.execute('DELETE FROM cycles WHERE id=?', (cycle['id'],))
        assert snapshot(directory) == before
        try:
            result = invoke()
        except subprocess.CalledProcessError as exc:
            print(f'Disposable child failed with {exc.returncode}: {exc.stderr}', file=sys.stderr)
            raise
    finally:
        os.close(descriptor)
    journal = json.loads((directory / 'integration-release-journal.json').read_bytes())
    child = json.loads((directory / 'offline-child.json').read_bytes())
    attempt = result['release']['attempt_id']
    intent = json.loads((directory / 'repair-retry/intents' / (attempt + '.json')).read_bytes())
    assert result['release']['state'] == 'WAITING_SAFE_REQUEST_BOUNDARY'
    assert result['retry'] == {'state': 'WAITING_FOR_EXACT_RETRY', 'attempt_id': attempt}
    assert journal['state'] == 'COMPLETE' and journal['release_id'] == manifest['release_id']
    assert intent['attempt_id'] == attempt and intent['release'] == journal['release']
    assert child['pid'] != os.getpid() and child['runtime'] == {'state': 'COMPLETE', **{
        key: value for key, value in journal['release'].items() if key != 'schema'}}
    assert queue.read_bytes() == foreign and queue.stat().st_ino == queue_stat.st_ino
    assert not (directory / 'last-scan-request.json').exists()
    assert snapshot(directory) == before
    assert (project / target).read_bytes() != old_bytes
    observed = {'result': 'DISPOSABLE_ACTUAL_MEASURED_FOREIGN_QUEUE_WAIT',
                'retry_state': result['retry']['state'], 'release_state': journal['state'],
                'unfinished_cycle_refused_before_installation_or_child': True,
                'same_foreign_queue_inode_and_bytes': True, 'same_three_logical_sqlite_dumps': True,
                'measured_child_pid': child['pid'], 'source_digest': child['runtime']['source_manifest_sha256'],
                'bootstrap_pin': sha(project / BOOT.name), 'runner_pin': sha(project / 'src/job_search_helper/runner.py'),
                'controller_pin': sha(project / 'src/job_search_helper/release_controller.py'),
                'launcher_pin': sha(project / 'job-search-scraper'), 'parent_pin': OWNER_PIN}
    (root / 'RESULT.json').write_text(json.dumps(observed, indent=2, sort_keys=True) + '\n')
    print(root)
    print(json.dumps(observed, sort_keys=True))


if __name__ == '__main__':
    main()
