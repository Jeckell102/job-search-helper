"""The measured launcher enters only the one-retry worker."""
import importlib.util
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

import pytest

from job_search_helper import release_controller, runner
from job_search_helper.cli import WriterLockBusy, writer_lock
from job_search_helper.integration_release import (
    JOURNAL_SCHEMA, MANIFEST_SCHEMA, digest, manifest_release_id, metadata, release_binding,
)
from job_search_helper.sheet_profile import COMPACT_PROFILE, COMPACT_SCHEMAS
from test_repair_retry_admission_replay import retry


PROJECT = Path(__file__).resolve().parents[1]


def test_direct_worker_rejects_missing_inherited_admission(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(runner, '_load_environment', lambda: None)
    monkeypatch.setattr(runner, 'state_path', lambda: tmp_path / 'state.db')
    for name in ('JSH_SCRAPER_ADMISSION_FD', 'JSH_SCRAPER_ADMISSION_PATH', 'JSH_SCRAPER_RUNTIME_BINDING'):
        monkeypatch.delenv(name, raising=False)
    assert runner.main(arguments(tmp_path, 3, 'a' * 64, 'RTRY-' + 'b' * 24)) == 1
    assert 'requires the pre-import scraper lease' in capsys.readouterr().err
    assert not list(tmp_path.iterdir())
    assert runner.main(arguments(tmp_path, 3, 'a' * 64, '../foreign')) == 1
    assert 'exact repair retry ID' in capsys.readouterr().err


def arguments(directory, fd, pin, attempt):
    info = directory.stat()
    return ['continue-qualified-repair', '--attempt-id', attempt,
            '--qualification-owner-path', str(directory), '--qualification-owner-fd', str(fd),
            '--qualification-owner-device', str(info.st_dev), '--qualification-owner-inode', str(info.st_ino),
            '--qualification-receipt-sha256', pin]


@pytest.fixture
def measured(retry, monkeypatch, tmp_path):
    bridge, original, engine, state = retry
    project = tmp_path / 'measured-project'
    target = 'src/job_search_helper/one_fixture.py'
    installed = project / target
    installed.parent.mkdir(parents=True)
    installed.write_text('# baseline disposable measured source\n')
    (project / 'requirements.txt').write_text('# disposable measurement record\n')
    spec = importlib.util.spec_from_file_location('release_admission_bootstrap', PROJECT / 'release_admission_bootstrap.py')
    bootstrap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bootstrap)
    monkeypatch.setitem(sys.modules, spec.name, bootstrap)
    monkeypatch.setattr(runner, 'PROJECT_ROOT', project)
    monkeypatch.setattr(runner, 'state_path', lambda: Path(state.path))
    monkeypatch.setenv('STATE_DB_FILE', state.path)
    monkeypatch.setenv('JOB_DB_FILE', str(engine.repo.path))
    monkeypatch.setenv('SPREADSHEET_ID', engine.repo.spreadsheet_id)
    for name in ('GOOGLE_CREDENTIALS_FILE', 'GOOGLE_TOKEN_READ_FILE', 'GOOGLE_TOKEN_WRITE_FILE'):
        monkeypatch.setenv(name, str(project / name.lower()))
    runner._load_environment()
    before_source = bootstrap.source_tree_digest(project)
    before_file = metadata(installed)
    installed.write_text('# fixed disposable measured source\n')
    verification = {'result': 'PASS'}
    manifest = {
        'schema': MANIFEST_SCHEMA, 'company_id': original['company_id'], 'source_revision': original['source_revision'],
        'failed_request_id': original['failed_request_id'], 'files': {target: {'before': before_file, 'after': metadata(installed)}},
        'before_source_manifest_sha256': before_source,
        'source_manifest_sha256': bootstrap.source_tree_digest(project),
        'before_config_sha256': bootstrap.config_tree_digest(project), 'config_sha256': bootstrap.config_tree_digest(project),
        'dependency_manifest_sha256': bootstrap.dependency_manifest_digest(project),
        'validation_receipt_sha256': digest(verification),
    }
    manifest['release_id'] = manifest_release_id(manifest)
    receipt = {'state': 'COMPLETE', 'release_id': manifest['release_id'], 'failed_request_id': manifest['failed_request_id'],
               'company_id': manifest['company_id'], 'source_revision': manifest['source_revision'],
               'activated_at': original['activated_at'], 'manifest_sha256': digest(manifest),
               'release': release_binding(manifest), 'verification': verification}
    record = tmp_path / 'record'
    record.mkdir()
    (record / 'manifest.json').write_text(json.dumps(manifest))
    (record / 'receipt.json').write_text(json.dumps(receipt))
    (tmp_path / 'integration-release-journal.json').write_text(json.dumps(
        {'schema': JOURNAL_SCHEMA, 'state': 'COMPLETE', 'release_id': receipt['release_id'], 'release': receipt['release'],
         'record': str(record), 'manifest_sha256': digest(manifest), 'receipt_sha256': digest(receipt)}))
    binding = release_controller._retry_binding(receipt)
    assert bridge.deliver(binding)['state'] == 'REQUEST_WRITTEN'
    engine.repo.set_meta('sheets_profile', COMPACT_PROFILE)
    owner = tmp_path / 'qualification'
    owner.mkdir(mode=0o700)
    qualification = {'schema': 'integration-live-release-qualification-v1', 'result': 'PASS',
                     'evidence_class': 'live_normal_dispatch', 'release_qualification': True,
                     'manifest_sha256': digest(manifest), 'candidate_validation_sha256': digest(verification),
                     'capture_manifest_sha256': '1' * 64, 'reviewed_tools_sha256': '2' * 64}
    file = owner / (manifest['release_id'] + '.json')
    file.write_text(json.dumps(qualification, sort_keys=True, separators=(',', ':')))
    file.chmod(0o600)
    yield bootstrap, project, bridge, binding, owner, digest(qualification)


@pytest.mark.parametrize('case', ['waiting', 'complete', 'wrong_pin', 'missing_intent', 'wrong_destination'])
def test_measured_worker_routes_exact_scope_with_lazy_remote(measured, monkeypatch, capsys, case):
    bootstrap, project, bridge, binding, owner, pin = measured
    observations = []
    remote = object()

    def assemble_remote(**kwargs):
        observations.append('remote')
        assert kwargs == {'write': True, 'schemas': COMPACT_SCHEMAS, 'evidence_archives': False}
        return remote

    def continue_admitted(engine, database, exact, *, qualification_owner, remote_factory):
        observations.append('admitted')
        assert database == bridge.database and exact == binding
        assert engine.runtime_binding == bootstrap._validate_runtime(project, database.parent)
        assert engine.repo.spreadsheet_id == 'sheet' and qualification_owner._receipt_sha256 == pin
        with pytest.raises(WriterLockBusy), writer_lock(database.parent / 'scraper.lock'):
            pytest.fail('The measured scraper lock was released early.')
        if case == 'waiting':
            return {'state': 'WAITING_FOR_EXACT_RETRY', 'attempt_id': binding['attempt_id']}
        if case == 'wrong_destination':
            monkeypatch.setenv('SPREADSHEET_ID', 'another-workbook')
        with remote_factory() as selected:
            assert selected is remote
        return {'state': 'READY_FOR_CLOSEOUT', 'cycle_id': 'CYC-EXACT'}

    def finish(engine, exact, result, *, qualification_owner):
        observations.append('finish')
        assert exact == binding
        with writer_lock(bridge.database.parent / 'scraper.lock'):
            assert engine.repo.get_meta('ready') == 'yes'
            qualification_owner._check_root()
        return {'state': 'COMPLETE', 'cycle_id': result['cycle_id']} if case == 'complete' else result

    monkeypatch.setattr(runner.helper_cli, 'get_remote_repository', assemble_remote)
    monkeypatch.setattr(release_controller, '_continue_qualified_release_retry_admitted', continue_admitted)
    monkeypatch.setattr(release_controller, '_finish_qualified_release_retry', finish)
    descriptor = os.open(owner, os.O_RDONLY | os.O_DIRECTORY)
    os.set_inheritable(descriptor, True)
    args = arguments(owner, descriptor, 'f' * 64 if case == 'wrong_pin' else pin, binding['attempt_id'])
    if case == 'missing_intent':
        (bridge.intent_directory / (binding['attempt_id'] + '.json')).unlink()

    def capture_exec(executable, argv, environment):
        assert argv[-len(args)-2:] == ['-m', 'job_search_helper.runner', *args]
        assert argv[1:5] == ['-P', '-B', '-X', 'pycache_prefix=/dev/null']
        # Model exec's transfer of the sole descriptor. A harmless descriptor
        # in the original slot lets the simulated launcher's finally run.
        original_fd = int(environment['JSH_SCRAPER_ADMISSION_FD'])
        environment['JSH_SCRAPER_ADMISSION_FD'] = str(os.dup(original_fd))
        os.close(original_fd)
        try:
            observations.append(runner.main(args))
        finally:
            placeholder = os.open(os.devnull, os.O_RDONLY)
            if placeholder != original_fd:
                os.dup2(placeholder, original_fd)
                os.close(placeholder)

    monkeypatch.setattr(bootstrap.os, 'execve', capture_exec)
    queued = bridge.request_path.read_bytes()
    try:
        with patch.dict(os.environ):
            bootstrap.admit_and_exec(project, args)
    finally:
        os.close(descriptor)
    captured = capsys.readouterr()
    assert bridge.request_path.read_bytes() == queued
    if case in {'wrong_pin', 'missing_intent', 'wrong_destination'}:
        expected_observations, message = {
            'wrong_pin': ([1], 'receipt changed'),
            'missing_intent': ([1], 'no durable schedule intent'),
            'wrong_destination': (['admitted', 1], 'differs from the saved inventory destination'),
        }[case]
        assert observations == expected_observations and message in captured.err
        assert 'Qualified repair retry: ' not in captured.out
    elif case == 'waiting':
        assert observations == ['admitted', 'finish', 0]
        assert 'Qualified repair retry: ' in captured.out and 'WAITING_FOR_EXACT_RETRY' in captured.out
    else:
        assert observations == ['admitted', 'remote', 'finish', 0]
        assert 'Qualified repair retry: {"cycle_id": "CYC-EXACT", "state": "COMPLETE"}' in captured.out
