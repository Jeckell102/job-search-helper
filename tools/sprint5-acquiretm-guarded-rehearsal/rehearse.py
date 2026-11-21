"""Exercise guarded activation and retry scheduling in a disposable workspace."""
from contextlib import closing
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

root = Path(__file__).resolve().parent
application = Path('/tmp/jsh-s5-amphenol-receipt-choice.aH9Skdfa')
owned = Path('/tmp/jsh-s5-amphenol-owned-replay')
known_candidate = Path('/tmp/jsh-s5-amphenol-recipe-live-candidate')
release_source = Path('/tmp/jsh-m1-scope-backup/tools/sprint5-automated-release-preflight/src/job_search_helper')
custody_source = Path('/tmp/jsh-s5-release-qualification-custody.20261121/src/job_search_helper')
native = Path('/home/chris/job-search-helper_old')
app_package = Path('src/job_search_helper')
source_name = app_package / 'acquiretm.py'
public_capture_sha = '4a112649009f43322722be73cee16b52a53224d96b8142b65f7d8c0d53f2bc85'
qa_report_sha = '73f7b817a5689d7c24b3684b2f9013005693303ba05973a470b12b211a316cc8'
recipe_output_sha = '895ec36e443eea5a1c49c622d99b505d5ed49d5ff6c22d37e71eb5a610bb3c9d'


def file_digest(path):
    return sha256(path.read_bytes()).hexdigest()


if len(sys.argv) != 2:
    raise SystemExit('Pass the independently checked owned-replay build proof')
proof_path = Path(sys.argv[1]).resolve(strict=True)
if not proof_path.is_relative_to(owned) or proof_path.is_relative_to(owned/'stores'):
    raise ValueError('Expected scoped owned-replay proof in private stage')
proof = json.loads(proof_path.read_text())
prepared_path = owned / 'prepared-choice.json'
prepared = json.loads(prepared_path.read_text())
binding = prepared['binding']
assert proof['disposition'] == 'OWNED_REPLAY_CHOICE_ACCEPTED'
assert proof['prepared_sha256'] == file_digest(prepared_path)
assert proof['outcome_id'] == binding['outcome_id']
assert proof['candidate_source_sha256'] == recipe_output_sha == file_digest(known_candidate/source_name)
assert proof['test_provenance'] == prepared['test_provenance']
assert isinstance(proof['model_response_sha256'], str) and len(proof['model_response_sha256']) == 64
generated_source = Path(proof['generated_source_path']).resolve(strict=True)
assert generated_source == (proof_path.parent/'candidate'/source_name).resolve(strict=True)
assert file_digest(generated_source) == recipe_output_sha
os.umask(0o077)
project = root/'test-project'
candidate = root/'test-candidate'
project.mkdir(mode=0o700)
assert project.is_relative_to(Path('/tmp'))
shutil.copytree(application/'src', project/'src', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
for source, file, pin in (
    (release_source, 'integration_release.py', '69a4261f117a61d41a3a3cb023ca7c73098b1c0ee0a6c98b2fefb525d7ab21df'),
    (release_source, 'release_controller.py', 'a867ec859a1177711e6647e1ced164dcaff61553277c703a032b1cc3d5354dd0'),
    (custody_source, 'release_qualification.py', 'e91a7015f457b4acfb514ec3952f4173699962e7a2712cf43e088cd1a2005613'),
    (custody_source, 'private_file_custody.py', 'e57484449665ebd14c00fe1e4a9ec3f6bf4bc9907126fe608a9f690937e5142d'),
):
    assert file_digest(source/file) == pin
    shutil.copy2(source/file, project/app_package/file)
for file in ('pyproject.toml', 'title-blacklist.txt', 'title-review-list.txt'):
    shutil.copy2(known_candidate/file, project/file)
(project/'.storage-backend').write_text('sqlite\n')
shutil.copytree(known_candidate/'tests', project/'tests')
shutil.copytree(project, candidate)
(candidate/source_name).write_bytes(generated_source.read_bytes())

# These stores came from real application transactions with a fixture workbook.
state = project/'.state'
databases = ('state.db', 'jobs.sqlite3', 'inventories.sqlite3')
shutil.copytree(owned/'stores', state, ignore=shutil.ignore_patterns(
    'coordinator', '*.lock', '*-shm', '*-wal', *databases))
for name in databases:
    source = owned/'stores'/name
    with (closing(sqlite3.connect(source.as_uri()+'?mode=ro', uri=True)) as reader,
          closing(sqlite3.connect(state/name)) as target):
        reader.backup(target)
assert not (state/'next-scan.json').exists()
os.environ['JOB_STORAGE_BACKEND'] = 'sqlite'
os.environ['SPREADSHEET_ID'] = 'sheet'
sys.path.insert(0, str(project/'src'))
from job_search_helper.company_events import current_company_source_revision
from job_search_helper.integration_release import (
    MANIFEST_SCHEMA, config_tree_digest, dependency_manifest_digest, digest, manifest_release_id, metadata, source_tree_digest,
)
from job_search_helper.release_controller import release_and_schedule_qualified
from job_search_helper.release_qualification import open_release_qualification_owner
from job_search_helper.ordinary_event_settlement import ordinary_event_outcome_settled
from job_search_helper.sqlite_repository import SQLiteRepository


def revision(company_id):
    with closing(SQLiteRepository(state/'jobs.sqlite3', 'sheet', readonly=True)) as repo:
        return current_company_source_revision(repo, company_id)


with closing(SQLiteRepository(state/'jobs.sqlite3', 'sheet', readonly=True)) as repo:
    [failed] = repo.scrape_outcomes()
    assert failed['outcome_id'] == binding['outcome_id'] and failed['identity']['request_id'] == binding['request_id']
    assert ordinary_event_outcome_settled(repo, failed)
    assert not repo.read('Job History') and not repo.read('Job Evidence')
assert revision(binding['company_id']) == binding['source_revision']

# The owner receipt below exists only in the test workspace and binds its
# measured policy. The fixture's shared test venv is driven by the test runner.
dependency = dependency_manifest_digest(project)
assert dependency_manifest_digest(candidate) == dependency
validation = {'result': 'PASS', 'scope': 'disposable-release-rehearsal',
              'source': source_tree_digest(candidate), 'offline_tests': 16}
manifest = {
    'schema': MANIFEST_SCHEMA, 'company_id': binding['company_id'], 'source_revision': binding['source_revision'],
    'failed_request_id': binding['request_id'],
    'files': {str(source_name): {'before': metadata(project/source_name), 'after': metadata(candidate/source_name)}},
    'before_source_manifest_sha256': source_tree_digest(project), 'source_manifest_sha256': source_tree_digest(candidate),
    'dependency_manifest_sha256': dependency, 'before_config_sha256': config_tree_digest(project),
    'config_sha256': config_tree_digest(candidate), 'validation_receipt_sha256': digest(validation),
}
manifest['release_id'] = manifest_release_id(manifest)
owner_dir = root/'fixture-qualification-owner'
owner_dir.mkdir(mode=0o700)
qualification = {
    'schema': 'integration-live-release-qualification-v1', 'result': 'PASS', 'evidence_class': 'live_normal_dispatch',
    'release_qualification': True, 'manifest_sha256': digest(manifest), 'capture_manifest_sha256': public_capture_sha,
    'candidate_validation_sha256': manifest['validation_receipt_sha256'], 'reviewed_tools_sha256': qa_report_sha,
}
qpath = owner_dir/(manifest['release_id'] + '.json')
qpath.write_text(json.dumps(qualification, sort_keys=True, separators=(',', ':')))
qpin = file_digest(qpath)
verification_runs = []


def verify(installed, expected):
    assert source_tree_digest(installed) == expected['source_manifest_sha256']
    assert file_digest(installed/source_name) == recipe_output_sha
    assert not (state/'next-scan.json').exists()
    scratch = root/'test-output'
    scratch.mkdir(mode=0o700)
    args = ['/usr/bin/python3', '-I', str(native/'dev/wrapper-coder/tools/coding_sandbox.py'),
            str(installed), str(native/'.venv'), str(scratch), 'tests/test_acquiretm.py',
            'tests/test_company_sources.py', 'tests/test_inventory_source_validation.py']
    execution = subprocess.run(args, capture_output=True, timeout=70, text=True, check=True)
    (root/'installed-tests.log').write_text(execution.stdout)
    assert '16 passed' in execution.stdout
    verification_runs.append(expected['release_id'])
    return dict(validation)


st = owner_dir.stat()
fd = os.open(owner_dir, os.O_RDONLY | os.O_DIRECTORY)
try:
    with open_release_qualification_owner(owner_dir, fd, expected_owner_identity=(st.st_dev,st.st_ino),
                                          approved_receipt_sha256=qpin) as authority:
        def run():
            return release_and_schedule_qualified(project, candidate, state/'state.db', root/'records', manifest,
                qualification_owner=authority, current_source_revision=revision,
                dependency_digest=lambda: dependency_manifest_digest(project), verify=verify)
        result = run()
        assert result['state'] == 'REQUEST_WRITTEN'
        first_request = (state/'next-scan.json').read_bytes()
        repeated = run()
        assert repeated['state'] == 'REQUEST_ALREADY_DURABLE'
        assert repeated['attempt_id'] == result['attempt_id']
        assert (state/'next-scan.json').read_bytes() == first_request
finally:
    os.close(fd)
request = json.loads(first_request)
assert request['company_ids'] == [manifest['company_id']]
assert request['repair_retry']['failed_request_id'] == binding['request_id']
assert len(verification_runs) == 1
result['disposition'] = 'DISPOSABLE_RELEASE_AND_SCOPED_RETRY_QUEUE_REHEARSAL'
result['candidate_source_sha256'] = recipe_output_sha
result['rehearsal_source_digest'] = manifest['source_manifest_sha256']
result['queued_request_sha256'] = sha256(first_request).hexdigest()
encoded = json.dumps(result, indent=2, sort_keys=True) + '\n'
(root/'rehearsal-result.json').write_text(encoded)
print(encoded, end='')
