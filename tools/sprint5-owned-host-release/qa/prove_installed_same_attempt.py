"""Owned build and host-driven guarded canary install, measured child and exact receipt."""
from contextlib import closing
from functools import partial
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
from tempfile import mkdtemp
from types import SimpleNamespace
from unittest.mock import Mock, patch


HERE = Path(__file__).resolve().parent
SOURCE = Path('/tmp/jsh-s5-owned-host-trigger-held-guard.20261121')
RECIPE = Path('/tmp/jsh-s5-joined-amphenol-release-candidate.20261121/src/job_search_helper/acquiretm.py')
ARCHIVE = Path('/tmp/jsh-s5-amphenol-owned-replay')
CAPTURE = Path('/tmp/jsh-s5-continuation-composed.05f7tgrs/captured-retry-inventory.private.json')
VERIFIER_STAGE = Path('/tmp/jsh-s5-installed-recipe-verification.20261121/dev/wrapper-coder/tools')
VERIFIER_PIN = 'aeea069ce3ea41d721f19eba73b21ac351ac820d991e3da9f85e546c33d58b8d'
RECIPE_TOOL_PIN = 'e753da1c44d2bafe8b1d1ce8a5954fd23c113c3eeeced11fa5a2592d8854479a'
COMPANY = 'COMP-0490'
TARGET = 'src/job_search_helper/acquiretm.py'
ORIGINAL = 'OUT-cffecec610203a71e5c23b82'
ADAPTER_PIN = '895ec36e443eea5a1c49c622d99b505d5ed49d5ff6c22d37e71eb5a610bb3c9d'
CAPTURE_PIN = '94250320f27fbf987f417405599f609de6ea965feb41f1b6297cfee57dba5fa8'
SOURCE_PINS = {
    TARGET: 'a95953afe2bc10138714f6b11af22572b17ab344bf61d78b834647895025aa61',
    'src/job_search_helper/qualified_release_owner.py': '607a08c3d3e4728e411b95cfa9e4bd54a8dbcb767560ff077351e7bc268ebec9',
    'src/job_search_helper/runner.py': '0b4e80b429b242a1eec02eadb5b89ac501b8d13f7dc0c3122015e01eece91003',
    'src/job_search_helper/release_controller.py': '2cd45aff4d52d3808c41b1bbd36e0c1a3a257634b2df79221185345742adff8c',
    'src/job_search_helper/inbox.py': 'dc6f207088e755ac98bd6541ed1ec1b608dc81b2359b7c908883eeb81e43dee1',
    'dev/wrapper-coder/tools/host_server.py': '30854d51eaaf0bc2dcd4f833d192acf28572b8c0ec63ba0ac2a25c1f4e6dc586',
    'dev/wrapper-coder/tools/amphenol_retry_completion.py': 'c7ca5f021989a5f552482be2f3eb3d40a3da428c733f49b6f8a601c05945f6ef',
    'dev/wrapper-coder/tools/amphenol_candidate_release.py': '7cf2c0795925f077b5cda4a67ce6418adf6fbafae2a955732f60765951ab087f',
    'dev/wrapper-coder/tools/amphenol_installed_verification.py': VERIFIER_PIN,
    'job-search-scraper': '2556de3371c32be1991273a1ee88d2baa25753dfcdc73a9656d34de6b91de78c',
    'release_admission_bootstrap.py': 'c8a915a8311d74454d292a7f89a0f583b199a5a13832a89f00012cb99c0b500f',
}


def sha(path):
    return sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n')


def read_dump(path):
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as database:
        return tuple(database.iterdump())


def snapshot(directory):
    return {name: read_dump(directory / name) for name in ('state.db', 'jobs.sqlite3', 'inventories.sqlite3')}


def deny_network(event, args):
    if event.startswith('socket.'):
        raise AssertionError('Parent canary forbids DNS and network.')


def copy_archived_stores(root, directory):
    original = ARCHIVE / 'stores'
    receiver = root / 'coordinator'
    receiver.mkdir(mode=0o700)
    for name in ('jobs.sqlite3', 'inventories.sqlite3', 'state.db', 'coordinator/tasks.sqlite3'):
        source = original / name
        target = (root if '/' in name else directory) / name
        shutil.copy2(source, target)
        wal = source.with_name(source.name + '-wal')
        if wal.exists() and wal.stat().st_size:
            shutil.copy2(wal, target.with_name(target.name + '-wal'))
    for name in ('company-event-bridge', 'ordinary-event-inventory'):
        shutil.copytree(original / name, directory / name)
    shutil.copy2(original / 'last-scan-request.json', directory / 'last-scan-request.json')


def main():
    sys.addaudithook(deny_network)
    root = Path(mkdtemp(prefix='same-attempt-', dir=HERE))
    print(root, flush=True)
    project, candidate, approval = (root / name for name in ('project', 'candidate', 'approval'))
    project.mkdir(mode=0o700)
    approval.mkdir(mode=0o700)
    original = ARCHIVE / 'stores'
    original_files = [p for p in original.rglob('*') if p.is_file() and not p.name.endswith('-shm')]
    original_pins = {p: sha(p) for p in original_files}
    assert all(sha(SOURCE / name) == pin for name, pin in SOURCE_PINS.items())
    assert sha(RECIPE) == ADAPTER_PIN and sha(CAPTURE) == CAPTURE_PIN

    for name in ('src', 'tests', 'dev/wrapper-coder/tools'):
        shutil.copytree(SOURCE / name, project / name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for name in ('job-search-scraper', 'release_admission_bootstrap.py', 'title-blacklist.txt', 'title-review-list.txt'):
        shutil.copy2(SOURCE / name, project / name)
    assert all(sha(project / name) == pin for name, pin in SOURCE_PINS.items())
    tools = project / 'dev/wrapper-coder/tools'
    verifier = VERIFIER_STAGE / 'amphenol_installed_verification.py'
    assert sha(verifier) == VERIFIER_PIN
    shutil.copy2(verifier, tools / verifier.name)
    assert sha(tools / 'acquiretm_membership_recipe.py') == RECIPE_TOOL_PIN
    (project / 'docs').mkdir()
    (project / 'docs/wrapper-development-test-protocol.md').write_text('# Fixture protocol\nRun the exact local baseline tests.\n')
    (project / 'requirements.txt').write_text('# Standard-library-only disposable runtime fixture.\n')
    shutil.copy2(CAPTURE, project / 'public-inventory.private.json')
    token = project / 'dev/wrapper-coder/bridge-token'
    token.write_text('private-canary-fixture-token\n')
    token.chmod(0o600)
    (project / '.storage-backend').write_text('sqlite\n')
    subprocess.run([sys.executable, '-m', 'venv', '--without-pip', str(project / '.venv')], check=True)
    site = next((project / '.venv/lib').glob('python*/site-packages'))
    shutil.copy2(HERE / 'offline_child.py', site / 'isolated_offline_canary.py')
    (site / 'isolated_offline_canary.pth').write_text('import isolated_offline_canary\n')
    shutil.copytree(project / 'src', candidate / 'src')
    for name in ('.storage-backend', 'title-blacklist.txt', 'title-review-list.txt', 'requirements.txt'):
        shutil.copy2(project / name, candidate / name)
    directory = project / '.state'
    directory.mkdir(mode=0o700)
    copy_archived_stores(root, directory)
    os.environ.update(JOB_STORAGE_BACKEND='sqlite', STATE_DB_FILE='.state/state.db',
                      JOB_DB_FILE='.state/jobs.sqlite3', SPREADSHEET_ID='sheet')
    sys.path[:0] = [str(project / 'src'), str(tools)]
    import coding_tools
    import host_server as host
    from job_search_helper.company_events import current_company_source_revision
    from job_search_helper.engine import State
    from job_search_helper.exact_cycle_receipt import repair_retry_has_confirmed_publication
    from job_search_helper.inbox import InventoryInbox
    from job_search_helper.integration_release import (
        MANIFEST_SCHEMA, config_tree_digest, dependency_manifest_digest, digest,
        manifest_release_id, metadata, source_tree_digest,
    )
    from job_search_helper.ordinary_event_settlement import ordinary_event_outcome_settled
    from job_search_helper.private_file_custody import encode
    from job_search_helper.scrape_outcome_delivery import CONSUMER, OutcomeDelivery
    from job_search_helper.sqlite_repository import SQLiteRepository

    db = directory / 'state.db'
    jobs_path = directory / 'jobs.sqlite3'
    prepared = json.loads((ARCHIVE / 'prepared-choice.json').read_bytes())['binding']
    assert prepared['outcome_id'] == ORIGINAL
    with (closing(State(db, readonly=True)) as state,
          closing(SQLiteRepository(jobs_path, 'sheet')) as jobs):
        original_cycles = state.cycles()
        [prior] = original_cycles
        assert prior['status'] == 'Complete with exceptions' and prior['start_request_id'] == prepared['request_id']
        [row] = jobs._outcome_delivery_rows(CONSUMER, outcome_id=ORIGINAL)
        original_outcome, _, stale, acknowledged, _ = OutcomeDelivery(jobs, None)._preflight(row)
        assert acknowledged and not stale and ordinary_event_outcome_settled(jobs, original_outcome)
        [seed_company] = jobs.read('Companies')
        assert seed_company['Company ID'] == COMPANY
        unrelated_company = {'Company ID': 'COMP-CANARY-OTHER', 'Company': 'Unrelated canary',
                             'Company Status': 'Active', 'ATS / Source': 'Greenhouse',
                             'Official Careers URL': 'https://example.invalid/other'}
        unrelated_job = {'Job Key': 'canary-unrelated-key', 'Company': 'Unrelated canary',
                         'Job Title': 'Preserved fixture job', 'Job URL': 'https://example.invalid/1'}
        jobs.import_rows('Companies', [(3, unrelated_company)])
        jobs.import_rows('Job History', [(2, unrelated_job)])
        companies = jobs.read('Companies')
        history = jobs.read('Job History')
        write_json(project / 'workbook-before.private.json', {'Companies': companies, 'Job History': history})
        saved_company = jobs.matches('Companies', {'Company ID': 'COMP-CANARY-OTHER'})[0][1]
        saved_job = jobs.matches('Job History', {'Job Key': 'canary-unrelated-key'})[0][1]
        saved_prior_mirror = jobs.matches('Scan Cycles', {'Cycle ID': prior['id']})[0][1]

    def revision(company_id):
        with closing(SQLiteRepository(jobs_path, 'sheet', readonly=True)) as jobs:
            return current_company_source_revision(jobs, company_id)

    assert revision(COMPANY) == prepared['source_revision']
    scope = {key: prepared[key] for key in ('company_event_id', 'request_id', 'source_revision')}
    scope_env = {'WRAPPER_AMPHENOL_RECIPE_ENROLLMENT': json.dumps(scope)}
    assert host.AmphenolRecipeEnrollment.from_process_environment({}) is None
    recipe = host.AmphenolRecipeEnrollment.from_process_environment(scope_env)
    with patch.object(host, 'Coordinator', partial(host.Coordinator, base=root / 'coordinator')):
        coordinator = host.build_coordinator(recipe)
    coordinator.command({'action': 'queue-pause'})
    coding_tools.ROOT = project
    model_choice = {'summary': 'W1', 'next_action': 'listing_membership_change', 'outcome': 'phase_done'}
    reply = {'message': {'role': 'assistant', 'content': '', 'tool_calls': [{'type': 'function',
             'function': {'name': 'worker_checkpoint', 'arguments': model_choice}}]},
             'usage': {'done_reason': 'stop', 'prompt_eval_count': 500, 'eval_count': 60}}
    coordinator.model = Mock(return_value=reply)
    coordinator.budget = lambda *_: SimpleNamespace(available_generation_tokens=1200, prompt_tokens=500)
    started = host.build_supervision(coordinator, recipe=recipe).catch_up()
    assert started['state'] == 'RECIPE_PILOT_QUEUED' and started['outcome_id'] == ORIGINAL, started
    task = started['task_id']
    with patch.object(coding_tools, 'run_tests', return_value={'exit_code': 0, 'timed_out': False, 'output': 'fixture baseline'}):
        for _ in range(2):
            assert coordinator.store.claim_pilot(task), coordinator.store.get(task)
            coordinator.step(task)
    coordinator.model.assert_called_once()
    build_owner = coordinator.store.get(task)
    [choice] = coordinator.store.inference_receipts(task)
    assert (build_owner['status'], build_owner['baseline_passed'], build_owner['isolated_workspace']) == (
        'REVIEW_COMPLETE_LIVE_NOT_VALIDATED', True, True), build_owner
    assert choice['status'] == 'COMPLETED' and choice['accepted_recipe_choice'] == model_choice
    built = coordinator.store.base / task / 'recipe-candidate' / TARGET
    assert built.read_bytes() == RECIPE.read_bytes()
    shutil.copy2(built, candidate / TARGET)
    def observe_model(*_args):
        raise AssertionError('Activation cannot perform another inference')
    coordinator.model = Mock(side_effect=observe_model)

    verification = {
        'schema': 'amphenol-installed-recipe-verification-v1', 'result': 'PASS',
        'wrapper': metadata(candidate / TARGET),
        'source_manifest_sha256': source_tree_digest(candidate),
        'config_sha256': config_tree_digest(candidate),
        # The one-file release leaves requirements and the installed venv intact.
        'dependency_manifest_sha256': dependency_manifest_digest(project),
    }
    assert (project / 'requirements.txt').read_bytes() == (candidate / 'requirements.txt').read_bytes()
    write_json(root / 'expected-verification.json', verification)
    manifest = {
        'schema': MANIFEST_SCHEMA, 'company_id': COMPANY, 'source_revision': prepared['source_revision'],
        'failed_request_id': prepared['request_id'],
        'files': {TARGET: {'before': metadata(project / TARGET), 'after': metadata(candidate / TARGET)}},
        'before_source_manifest_sha256': source_tree_digest(project), 'source_manifest_sha256': source_tree_digest(candidate),
        'dependency_manifest_sha256': dependency_manifest_digest(project),
        'before_config_sha256': config_tree_digest(project), 'config_sha256': config_tree_digest(candidate),
        'validation_receipt_sha256': digest(verification),
    }
    manifest['release_id'] = manifest_release_id(manifest)
    candidate = candidate.rename(approval / (manifest['release_id'] + '.candidate'))
    manifest_file = approval / (manifest['release_id'] + '.manifest.json')
    manifest_file.write_bytes(encode(manifest))
    manifest_file.chmod(0o600)
    ticket = approval / (manifest['release_id'] + '.json')
    ticket.write_text(json.dumps({
        'schema': 'integration-live-release-qualification-v1', 'result': 'PASS', 'evidence_class': 'live_normal_dispatch',
        'release_qualification': True, 'manifest_sha256': digest(manifest), 'capture_manifest_sha256': CAPTURE_PIN,
        'candidate_validation_sha256': manifest['validation_receipt_sha256'], 'reviewed_tools_sha256': sha(HERE / 'offline_child.py'),
    }, sort_keys=True, separators=(',', ':')))
    ticket.chmod(0o600)
    info = approval.stat()
    approval_env = {**scope_env, 'WRAPPER_AMPHENOL_RETRY_APPROVAL': json.dumps({
        'release_id': manifest['release_id'], 'directory': str(approval),
        'device': info.st_dev, 'inode': info.st_ino, 'receipt_sha256': sha(ticket),
    })}
    default_off = host.AmphenolRecipeEnrollment.from_process_environment(approval_env)
    before = snapshot(directory)
    baseline = sha(project / TARGET)
    off = host.build_supervision(coordinator, recipe=default_off).catch_up()
    assert off == {'state': 'HELD_EXACT_RETRY_TERMINAL'}, off
    assert snapshot(directory) == before and sha(project / TARGET) == baseline
    assert not (directory / 'integration-release-journal.json').exists()
    assert not (directory / 'next-scan.json').exists() and not (directory / 'measured-child.jsonl').exists()

    enabled_env = {**approval_env, 'WRAPPER_AMPHENOL_ACTIVATE_APPROVED_RELEASE': '1'}
    enabled = host.AmphenolRecipeEnrollment.from_process_environment(enabled_env)
    supervisor = host.build_supervision(coordinator, recipe=enabled)
    first = supervisor.catch_up()
    assert first['state'] == 'RECIPE_RELEASE_RETRY_CHECKED' and first['retry_state'] == 'COMPLETE', first
    assert first['release']['state'] == 'REQUEST_WRITTEN'
    record = directory / 'integration-releases' / manifest['release_id'] / 'receipt.json'
    saved_receipt = json.loads(record.read_bytes())
    assert saved_receipt['verification'] == verification
    assert digest(saved_receipt['verification']) == manifest['validation_receipt_sha256']
    assert sha(project / TARGET) == ADAPTER_PIN and not (directory / 'next-scan.json').exists()
    assert coordinator.store.get(task) == build_owner and coordinator.store.inference_receipts(task) == [choice]
    coordinator.model.assert_not_called()
    with closing(SQLiteRepository(jobs_path, 'sheet', readonly=True)) as jobs:
        [success] = [item for item in jobs.scrape_outcomes() if item['outcome_id'] != ORIGINAL]
    cid = success['identity']['cycle_id']
    attempt = first['release']['attempt_id']
    assert success['identity']['attempt_id'] == attempt and success['identity']['failed_request_id'] == prepared['request_id']
    with (closing(State(db, readonly=True)) as state,
          closing(SQLiteRepository(jobs_path, 'sheet', readonly=True)) as jobs,
          closing(InventoryInbox(directory / 'inventories.sqlite3', 'sheet', readonly=True)) as inbox):
        cycle = state.cycle(cid)
        assert cycle['status'] == 'Complete' and set(cycle['companies']) == {COMPANY}
        assert repair_retry_has_confirmed_publication(inbox, jobs, cycle, COMPANY)
        assert state.cycle(prior['id']) == prior
        assert jobs.matches('Scan Cycles', {'Cycle ID': prior['id']})[0][1] == saved_prior_mirror
        assert jobs.matches('Companies', {'Company ID': 'COMP-CANARY-OTHER'})[0][1] == saved_company
        assert jobs.matches('Job History', {'Job Key': 'canary-unrelated-key'})[0][1] == saved_job
        local = sorted(row['Job Key'] for row in jobs.read('Job History') if row['Company'] == 'Amphenol Aerospace')
        workbook = json.loads((directory / 'workbook-after.private.json').read_text())
        mirrored = sorted(row['Job Key'] for row in workbook['jobs'] if row['Company'] == 'Amphenol Aerospace')
        assert local == mirrored and len(set(local)) == 18 and workbook['batches'] == 1
        assert jobs._outcome_delivery_rows(CONSUMER, outcome_id=ORIGINAL) == [row]
        assert [record for record in jobs.scrape_outcomes() if record['outcome_id'] != ORIGINAL] == [success]
    measured_path = directory / 'measured-child.jsonl'
    launch_log = measured_path.read_bytes()
    [measured] = [json.loads(line) for line in launch_log.splitlines()]
    assert measured['runtime']['release_id'] == manifest['release_id']
    assert measured['runtime']['source_manifest_sha256'] == manifest['source_manifest_sha256']
    write_json(root / 'host-settings.json', {
        'original_outcome_id': ORIGINAL, 'outcome': success, 'enrollment': enabled_env,
    })
    for phase in ('first', 'restart'):
        execution = subprocess.run([str(project / '.venv/bin/python'), '-I', '-B',
            str(HERE / 'host_readback.py'), str(root), phase], cwd=project, text=True, capture_output=True)
        (root / f'host-{phase}.log').write_text(execution.stdout + execution.stderr)
        assert execution.returncode == 0, execution.stderr
        if phase == 'first':
            after_host = snapshot(directory)
            receiver_dump = read_dump(root / 'coordinator/tasks.sqlite3')
    assert snapshot(directory) == after_host and read_dump(root / 'coordinator/tasks.sqlite3') == receiver_dump
    assert measured_path.read_bytes() == launch_log and sha(project / TARGET) == ADAPTER_PIN
    initial_host = json.loads((root / 'host-first.json').read_text())
    restarted_host = json.loads((root / 'host-restart.json').read_text())
    assert initial_host['pid'] != restarted_host['pid'] and initial_host['receipt_sha256'] == restarted_host['receipt_sha256']
    assert set(path for path in original.rglob('*') if path.is_file() and not path.name.endswith('-shm')) == set(original_pins)
    assert all(sha(path) == pin for path, pin in original_pins.items())
    result = {'result': 'DISPOSABLE_SAME_ATTEMPT_INSTALLED_AND_RECEIVED', 'release_id': manifest['release_id'],
              'attempt_id': attempt, 'cycle_id': cid, 'outcome_id': success['outcome_id'], 'original_outcome_id': ORIGINAL,
              'installed_source_sha256': manifest['source_manifest_sha256'], 'measured_dependency_sha256': manifest['dependency_manifest_sha256'],
              'saved_and_published_job_count': len(local), 'fixture_batches': workbook['batches'],
              'captured_fetch_calls': 1, 'workbook_factory_calls': 1, 'real_provider_or_workbook_calls': 0,
              'child_pids': [measured['pid']], 'host_pids': [initial_host['pid'], restarted_host['pid']],
              'host_receipt_sha256': initial_host['receipt_sha256'], 'receiver_events': 1, 'receiver_commands_on_restart': 0,
              'native_release_qualification': False, 'preserved_archived_inputs': True,
              'verified_release_receipt_sha256': sha(record), 'verification_digest': digest(verification),
              'actual_host_install_worker_launches': 1, 'installed_verifier_pin': VERIFIER_PIN,
              'genuine_build_task': task, 'build_choice_calls': 1, 'default_off_hold': off['state'],
              'resolved_inferences': True, 'host_launch_state': first['state']}
    write_json(root / 'RESULT.json', result)
    print(json.dumps(result, sort_keys=True), flush=True)


if __name__ == '__main__':
    main()
