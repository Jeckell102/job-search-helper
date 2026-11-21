"""Compose the exact held owner, settled choice, recipe build and qualification reader."""

from dataclasses import asdict
from hashlib import sha256
import json
from shutil import copyfile
from types import SimpleNamespace
from unittest.mock import Mock

from acquiretm_membership_recipe import TARGET_PATH
from amphenol_candidate_release import read_owned_candidate_release
from amphenol_installed_verification import verify_installed_amphenol_recipe
from amphenol_retry_completion import RetryReleaseApproval
import coding_tools
from job_search_helper.cli import writer_lock
from job_search_helper.integration_release import (
    JOURNAL_SCHEMA, MANIFEST_SCHEMA, config_tree_digest, digest, manifest_release_id, metadata, source_tree_digest,
)
from job_search_helper.private_file_custody import encode
from test_amphenol_host_enrollment import enrolled, host
from test_coordinator import response
from test_owned_recipe_scheduler import CHOICE, claim_step


def test_exact_owned_build_must_match_the_independent_full_release(enrolled, host, tmp_path, monkeypatch):
    enrollment, coordinator, supervision, root, selected, _ = enrolled
    started = supervision.catch_up()
    assert started['state'] == 'RECIPE_PILOT_QUEUED'
    task = started['task_id']
    monkeypatch.setattr(coding_tools, 'run_tests', lambda *_: {'exit_code': 0, 'timed_out': False, 'output': 'fixture'})
    coordinator.budget = lambda *_: SimpleNamespace(available_generation_tokens=1200, prompt_tokens=500)
    coordinator.model = Mock(return_value=response('worker_checkpoint', CHOICE))
    claim_step(coordinator, task)
    claim_step(coordinator, task)
    coordinator.model.assert_called_once()
    assert coordinator.store.get(task)['status'] == 'REVIEW_COMPLETE_LIVE_NOT_VALIDATED'

    project = coding_tools.root()
    sparse = coordinator.store.base / task / 'recipe-candidate'
    candidate = tmp_path / 'full-candidate'
    (candidate / TARGET_PATH).parent.mkdir(parents=True)
    copyfile(sparse / TARGET_PATH, candidate / TARGET_PATH)
    manifest = {
        'schema': MANIFEST_SCHEMA,
        'failed_request_id': enrollment.request_id,
        'company_id': 'COMP-0490',
        'source_revision': enrollment.source_revision,
        'files': {TARGET_PATH: {'before': metadata(project / TARGET_PATH), 'after': metadata(candidate / TARGET_PATH)}},
        'before_source_manifest_sha256': source_tree_digest(project),
        'source_manifest_sha256': source_tree_digest(candidate),
        'before_config_sha256': config_tree_digest(project),
        'config_sha256': config_tree_digest(candidate),
        'dependency_manifest_sha256': 'a' * 64,
        'validation_receipt_sha256': 'b' * 64,
    }
    manifest['release_id'] = manifest_release_id(manifest)
    directory = tmp_path / 'test-qualification-authority'
    directory.mkdir(mode=0o700)
    candidate = candidate.rename(directory / (manifest['release_id'] + '.candidate'))
    manifest_file = directory / (manifest['release_id'] + '.manifest.json')
    manifest_file.write_bytes(encode(manifest))
    manifest_file.chmod(0o600)
    qualified = directory / (manifest['release_id'] + '.json')
    context = directory.stat()

    def approve(*, release_qualification):
        raw = encode({
            'schema': 'integration-live-release-qualification-v1', 'result': 'PASS',
            'evidence_class': 'live_normal_dispatch', 'release_qualification': release_qualification,
            'manifest_sha256': digest(manifest), 'candidate_validation_sha256': manifest['validation_receipt_sha256'],
            'capture_manifest_sha256': 'c' * 64, 'reviewed_tools_sha256': 'd' * 64,
        })
        qualified.write_bytes(raw)
        qualified.chmod(0o600)
        return host.AmphenolRetryEnrollment(**asdict(enrollment), retry_approval=RetryReleaseApproval(
            manifest['release_id'], str(directory), context.st_dev, context.st_ino, sha256(raw).hexdigest(),
        ))

    def read(owner, supplied_manifest=manifest):
        with coordinator.workspace_lock, coordinator.control_lock, enrollment.owner_scope():
            return read_owned_candidate_release(
                owner, coordinator, root, outcome_id=selected['outcome_id'],
                candidate_root=candidate, manifest=supplied_manifest,
            )

    assert read(enrollment) is None
    assert read(approve(release_qualification=False)) is None
    owner = approve(release_qualification=True)
    expected = {'candidate_root': candidate, 'manifest': manifest, 'approval': owner.retry_approval,
                'task_id': task}
    assert read(owner) == read(owner) == expected
    foreign_manifest = {**manifest, 'failed_request_id': 'foreign-request'}
    foreign_manifest['release_id'] = manifest_release_id(foreign_manifest)
    assert read(owner, foreign_manifest) is None

    extra = (candidate / TARGET_PATH).with_name('foreign.py')
    extra.write_text('value = 1\n')
    assert read(owner) is None
    extra.unlink()
    receipt_path = sparse / 'build-receipt.json'
    original_receipt = receipt_path.read_bytes()
    receipt = json.loads(original_receipt)
    receipt['response_digest'] = 'e' * 64
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    assert read(owner) is None
    receipt_path.write_bytes(original_receipt)

    calls = []
    terminal = {'state': 'HELD_EXACT_RETRY_TERMINAL'}

    def install(project_root, candidate_root, database, record_root, supplied_manifest, **options):
        assert (project_root, candidate_root, database, record_root, supplied_manifest) == (
            tmp_path, candidate, root / 'state.db', root / 'integration-releases', manifest,
        )
        # The installer owns its normal application leases, never nested
        # inside the earlier read scope in the supervision callback.
        with writer_lock(root / 'scraper.lock'), writer_lock(root / 'writer.lock'):
            assert options['current_source_revision']('COMP-0490') == enrollment.source_revision
        assert options['verify'] is verify_installed_amphenol_recipe
        calls.append(supplied_manifest['release_id'])
        terminal['state'] = 'RECIPE_RETRY_CONFIRMED'
        return {'release': {'state': 'REQUEST_WRITTEN'}, 'retry': {'state': 'COMPLETE'}}

    monkeypatch.setattr('amphenol_retry_completion.deliver_qualified_retry', lambda *_args, **_kwargs: terminal)
    monkeypatch.setattr('job_search_helper.qualified_release_owner.release_and_continue_qualified', install)
    assert owner.catch_up(coordinator) == terminal and calls == []
    process_enrollment = {
        'WRAPPER_AMPHENOL_RECIPE_ENROLLMENT': json.dumps(asdict(enrollment)),
        'WRAPPER_AMPHENOL_RETRY_APPROVAL': json.dumps(asdict(owner.retry_approval)),
        'WRAPPER_AMPHENOL_ACTIVATE_APPROVED_RELEASE': '1',
    }
    enabled = host.AmphenolRecipeEnrollment.from_process_environment(process_enrollment)
    assert enabled.catch_up(coordinator) == {
        'state': 'RECIPE_RELEASE_RETRY_CHECKED', 'release': {'state': 'REQUEST_WRITTEN'},
        'retry_state': 'COMPLETE',
    }
    assert enabled.catch_up(coordinator) == terminal
    assert calls == [manifest['release_id']]

    terminal['state'] = 'HELD_EXACT_RETRY_TERMINAL'
    active_journal = root / 'integration-release-journal.json'
    active_journal.write_bytes(encode({
        'schema': JOURNAL_SCHEMA, 'state': 'COMPLETE', 'release_id': manifest['release_id'],
    }))
    expected_hold = {'state': 'HELD_RECIPE_RETRY_CONTINUATION', 'release_id': manifest['release_id']}
    assert enabled.catch_up(coordinator) == expected_hold
    restarted = host.build_coordinator(enabled)
    assert enabled.catch_up(restarted) == expected_hold
    assert calls == [manifest['release_id']]
    assert coordinator.model.call_count == 1
