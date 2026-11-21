from contextlib import closing
import json
import os
from subprocess import CompletedProcess

import pytest

from job_search_helper import qualified_release_owner as owner
from job_search_helper.cli import writer_lock
from job_search_helper.engine import State
from job_search_helper.inbox import InventoryInbox
from job_search_helper.sqlite_repository import SQLiteRepository


@pytest.mark.parametrize('case', ['exact', 'stale_company', 'foreign_attempt'])
def test_qualified_owner_dispatches_only_the_measured_attempt(tmp_path, monkeypatch, case):
    project = tmp_path / 'project'
    project.mkdir()
    launcher = project / 'job-search-scraper'
    launcher.write_text('#!/bin/sh\nexit 99\n')
    launcher.chmod(0o700)
    approval = tmp_path / 'approval'
    approval.mkdir(mode=0o700)
    identity = (approval.stat().st_dev, approval.stat().st_ino)
    pin = 'a' * 64
    release = {
        'state': 'STALE_COMPANY_REVISION' if case == 'stale_company' else 'REQUEST_ALREADY_ADMITTED',
        'attempt_id': 'RTRY-' + 'b' * 24, 'release_id': 'REL-fixture',
        'company_id': 'COMP-0490', 'failed_request_id': 'prior-request', 'source_revision': 'd' * 64,
    }
    calls = []

    def install(*args, **kwargs):
        calls.append('qualified install')
        kwargs['qualification_owner']._check_root()
        return release

    def run(args, **kwargs):
        assert calls == ['qualified install']
        calls.append('admitted worker')
        assert args == [
            str(launcher), 'continue-qualified-repair', '--attempt-id', release['attempt_id'],
            '--qualification-owner-path', str(approval), '--qualification-owner-fd', str(descriptor),
            '--qualification-owner-device', str(identity[0]), '--qualification-owner-inode',
            str(identity[1]), '--qualification-receipt-sha256', pin,
        ]
        assert kwargs['pass_fds'] == (descriptor,) and kwargs['cwd'] == project
        assert kwargs['check'] and kwargs['capture_output']
        scoped = {key: release[key] for key in (
            'attempt_id', 'failed_request_id', 'company_id', 'source_revision',
        )}
        if case == 'foreign_attempt':
            scoped['attempt_id'] = 'RTRY-' + 'c' * 24
        scope = {**scoped, 'release_version': release['release_id']}
        result = {'state': 'COMPLETE', 'outcome': {'outcome': 'COMPLETE', 'identity': scope}}
        return CompletedProcess(args, 0, 'Company-only scan.\n' + owner._WORKER_REPORT + json.dumps(result) + '\n')

    monkeypatch.setattr(owner, 'release_and_schedule_qualified', install)
    monkeypatch.setattr(owner.subprocess, 'run', run)
    descriptor = os.open(approval, os.O_RDONLY | os.O_DIRECTORY)
    try:
        def invoke():
            return owner.release_and_continue_qualified(
                project, tmp_path / 'candidate', tmp_path / 'state.db', tmp_path / 'records', {},
                approval_path=approval, approval_fd=descriptor, owner_identity=identity, approval_sha256=pin,
                current_source_revision=None, dependency_digest=None, verify=None,
            )

        if case == 'foreign_attempt':
            with pytest.raises(RuntimeError, match='different release or attempt'):
                invoke()
        else:
            result = invoke()
            assert result['release'] == release
            assert (result['retry'] is None) == (case == 'stale_company')
    finally:
        os.close(descriptor)
    assert calls == (['qualified install'] if case == 'stale_company'
                     else ['qualified install', 'admitted worker'])


@pytest.mark.parametrize('surface', ['state', 'mirror', 'idle'])
def test_new_qualified_install_respects_unfinished_normal_cycles(tmp_path, surface):
    database = tmp_path / 'state.db'
    with (closing(State(database)) as state,
          closing(SQLiteRepository(tmp_path / 'jobs.sqlite3', 'sheet', initialize=True)) as jobs,
          closing(InventoryInbox(tmp_path / 'inventories.sqlite3', 'sheet'))):
        jobs.set_meta('ready', 'yes')
        if surface == 'state':
            state.save_cycle({'id': 'CYC-protected', 'status': 'In Progress', 'companies': {}})
        elif surface == 'mirror':
            jobs.import_rows('Scan Cycles', [(2, {
                'Cycle ID': 'CYC-protected', 'Cycle Status': 'In Progress',
            })])
        expected_state = state.cycles()
        expected_mirror = jobs.read('Scan Cycles')
        with writer_lock(tmp_path / 'scraper.lock'):
            if surface == 'idle':
                owner._require_idle_installation(database, {'release_id': 'REL-new'})
            else:
                with pytest.raises(ValueError, match='Unfinished scrape work'):
                    owner._require_idle_installation(database, {'release_id': 'REL-new'})
        assert state.cycles() == expected_state and jobs.read('Scan Cycles') == expected_mirror
