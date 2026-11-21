"""Flow one rejected verification through the real qualified rollback boundary."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile


def offline(event, _):
    if event.startswith('socket.') or event in {'subprocess.Popen', 'os.system', 'os.exec'}:
        raise RuntimeError('Fixture denied network and external processes')


sys.addaudithook(offline)
work = Path(__file__).resolve().parent
source = Path('/tmp/jsh-s5-enrolled-retry-receipt.20261121')
recipe = Path('/tmp/jsh-s5-joined-amphenol-release-candidate.20261121')
changed = 'src/job_search_helper/acquiretm.py'
root = Path(tempfile.mkdtemp(dir=work, prefix='run-'))
project = root / 'installed'
candidate = root / 'candidate'
for entry in ('src', 'title-blacklist.txt', 'title-review-list.txt', 'job-search-scraper',
              'release_admission_bootstrap.py'):
    path = source / entry
    project.mkdir(exist_ok=True)
    if path.is_dir():
        shutil.copytree(path, project / entry)
    else:
        shutil.copy2(path, project / entry)
(project / 'requirements.txt').write_text('# Fixed disposable dependency policy.\n')
shutil.copytree(project, candidate)
shutil.copy2(recipe / changed, candidate / changed)
os.environ.update(JOB_STORAGE_BACKEND='sqlite', SPREADSHEET_ID='fixture',
                  STATE_DB_FILE='.state/state.db', JOB_DB_FILE='.state/jobs.sqlite3')
sys.path[:0] = [str(project / 'src'), str(project)]
from release_admission_bootstrap import _validate_runtime
from job_search_helper.company_events import current_company_source_revision
from job_search_helper.engine import State
from job_search_helper.inbox import InventoryInbox
from job_search_helper.integration_release import (
    MANIFEST_SCHEMA, config_tree_digest, dependency_manifest_digest, digest,
    manifest_release_id, metadata, rollback_release, source_tree_digest,
)
from job_search_helper.qualified_release_owner import release_and_continue_qualified
from job_search_helper.sqlite_repository import SQLiteRepository

state_root = project / '.state'
state_file = state_root / 'state.db'
jobs_file = state_root / 'jobs.sqlite3'
inbox_file = state_root / 'inventories.sqlite3'
company = 'COMP-0490'
with (closing(State(state_file)),
      closing(InventoryInbox(inbox_file, 'fixture')),
      closing(SQLiteRepository(jobs_file, 'fixture', initialize=True)) as owned_jobs):
    owned_jobs.set_meta('ready', 'yes')
    owned_jobs.import_rows('Companies', [(2, {'Company ID': company, 'Company': 'Fixture Company',
        'Company Status': 'Active', 'ATS / Source': 'AcquireTM',
        'Official Careers URL': 'https://fixture.invalid/careers'})])


def revision(identity):
    with closing(SQLiteRepository(jobs_file, 'fixture', readonly=True)) as repository:
        return current_company_source_revision(repository, identity)


def stores():
    result = []
    for path in (state_file, jobs_file, inbox_file):
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
            result.append(tuple(db.iterdump()))
    return result


before = stores()
validation = {'result': 'PASS', 'scope': 'disposable verification fault case'}
manifest = dict(schema=MANIFEST_SCHEMA, company_id=company, failed_request_id='fixture-failure',
    source_revision=revision(company), files={changed:{'before':metadata(project / changed),
                                                       'after':metadata(candidate / changed)}},
    before_source_manifest_sha256=source_tree_digest(project),
    source_manifest_sha256=source_tree_digest(candidate),
    dependency_manifest_sha256=dependency_manifest_digest(project),
    before_config_sha256=config_tree_digest(project), config_sha256=config_tree_digest(candidate),
    validation_receipt_sha256=digest(validation))
manifest['release_id'] = manifest_release_id(manifest)
approval = root / 'fixture-approval'
approval.mkdir(mode=0o700)
receipt = {'schema':'integration-live-release-qualification-v1', 'result':'PASS',
    'evidence_class':'live_normal_dispatch', 'release_qualification':True,
    'manifest_sha256':digest(manifest), 'capture_manifest_sha256':digest({'fixture':True}),
    'candidate_validation_sha256':digest(validation),'reviewed_tools_sha256':digest({'fixture':True})}
receipt_file = approval / (manifest['release_id']+'.json')
receipt_file.write_text(json.dumps(receipt, sort_keys=True, separators=(',', ':')))
receipt_file.chmod(0o600)
seen = []


def broken_verifier(installed, expected):
    assert installed == project and expected == manifest
    assert source_tree_digest(installed) == manifest['source_manifest_sha256']
    seen.append(1)
    return {'result':'FAIL','scope':'injected disposable post-install verification'}


journal = state_root / 'integration-release-journal.json'
records = root / 'release-records'
info = approval.stat()
descriptor = os.open(approval, os.O_RDONLY | os.O_DIRECTORY)
try:
    try:
        release_and_continue_qualified(
            project, candidate, state_file, records, manifest, approval_path=approval,
            approval_fd=descriptor, owner_identity=(info.st_dev, info.st_ino),
            approval_sha256=hashlib.sha256(receipt_file.read_bytes()).hexdigest(),
            current_source_revision=revision, dependency_digest=lambda: dependency_manifest_digest(project),
            verify=broken_verifier,
        )
    except RuntimeError as exc:
        assert str(exc) == 'Installed release verification did not pass'
    else:
        raise AssertionError('Rejected installed verification did not hold the release')
finally:
    os.close(descriptor)
assert seen == [1]
assert json.loads(journal.read_text())['state'] == 'INSTALLED'
assert not (state_root / 'next-scan.json').exists()
assert not (state_root / 'repair-retry').exists()
try:
    _validate_runtime(project, state_root)
except RuntimeError as exc:
    assert 'Interrupted integration release blocks' in str(exc)
else:
    raise AssertionError('Pre-import admission accepted the unverified installed candidate')
release = manifest['release_id']
receipt = rollback_release(project, state_file, records, release)
assert rollback_release(project, state_file, records, release) == receipt
assert _validate_runtime(project, state_root)['state'] == 'ROLLED_BACK'
assert source_tree_digest(project) == manifest['before_source_manifest_sha256']
assert stores() == before and not (state_root / 'next-scan.json').exists()
assert not (records / release / 'receipt.json').exists()
assert not (state_root / 'repair-retry').exists()
result = {
    'disposition': 'DISPOSABLE_INSTALLED_VERIFICATION_FAILURE_ROLLED_BACK',
    'release_id': release, 'complete_release_receipt_written': False,
    'installed_failure_blocked_worker_admission': True, 'runtime_restored': True,
    'application_stores_unchanged': True, 'retry_written': False, 'idempotent_rollback': True,
    'isolated_verifier_calls': len(seen), 'rollback_receipt': receipt,
    'restored_source_sha256': source_tree_digest(project),
}
output = json.dumps(result, indent=2, sort_keys=True) + '\n'
(work / 'RESULT.json').write_text(output)
print(output, end='')
