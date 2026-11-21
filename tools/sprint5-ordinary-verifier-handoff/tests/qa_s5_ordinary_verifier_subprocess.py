"""Explicit offline integration check using the separately approved saved corpus."""

import fcntl
from contextlib import ExitStack
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from job_search_helper import cli, ordinary_raw_capture as raw, ordinary_verification_pending as pending
from job_search_helper import ordinary_verifier_handoff as handoff
from job_search_helper.runtime_mapping_facts import _fd_identities
from test_ordinary_verification_pending import CYCLE_ID, attempt
from test_s5_ordinary_publication_continuation import WORKBOOK, measured_scope
from test_s5_ordinary_verifier_handoff import COMPANY_ID, digest, pack, use_forterra_source
from test_s5_ordinary_worker_handoff import local_worker


APPROVED = Path('/tmp/jsh-m5-live-authority-repair.jMbESo7E')
CORPUS = APPROVED / 'checkpoints/pytest-final-repair/test_full_original_employer_an0'
VERIFIER = Path('/tmp/jsh-s5-ordinary-verifier.povmDDEm/dev/ordinary_rippling_verifier.py')
SAVED_MISMATCH = Path('/tmp/jsh-s5-ordinary-sealed-evidence-red.PBkhfctW/fixture_data/public-rippling.json')


def _pin_file(path, expected):
    value = path.read_bytes()
    assert digest(value) == expected
    return value


@pytest.mark.parametrize('measured_scope', [True], indirect=True)
def test_approved_offline_worker_consumes_owner_work_and_returns_exact_evidence(measured_scope, monkeypatch, tmp_path):
    public = _pin_file(CORPUS / 'capture.json', '75feafd84ced0cbeb8ce855eedbcb02ce8fe3582faeb034c10a924d34e992480')
    pin = pack(json.loads((CORPUS / 'pin.json').read_bytes()))
    _pin_file(VERIFIER, '2925328cfae39a390cbac072a0834d10a580b0174555c1ef00fa9e418f7564c6')
    fixture = json.loads(_pin_file(SAVED_MISMATCH,
                                  'a69b02cd011f98d5dddde1c6faa10a621b87894829421a24aa60ce8fefcbed0b'))
    board = fixture['expected']['stale_board']
    configured_response = fixture['responses'][board].encode()
    use_forterra_source(measured_scope, monkeypatch, board, configured_response)

    _, state, jobs, inbox = measured_scope
    root = tmp_path / 'verifier-owner'
    root.mkdir(mode=0o700)
    info = root.stat()
    with ExitStack() as stack:
        def directory(path):
            descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
            stack.callback(os.close, descriptor)
            return descriptor

        capture_root = tmp_path / 'private-capture'
        capture = stack.enter_context(raw.open_custody(capture_root, directory(capture_root)))
        channel = stack.enter_context(handoff.open_offline_channel(
            root, directory(root), expected_owner_identity=(info.st_dev, info.st_ino),
            approved_pin_sha256=digest(pin),
        ))
        with (cli.writer_lock(state.parent / 'writer.lock'),
              pending.open_verification_stores(state, jobs, inbox, WORKBOOK, readonly=True) as stores):
            runtime = stores.state.cycle(CYCLE_ID)['runtime_binding']
            work = channel.stage(stores, runtime, CYCLE_ID, COMPANY_ID, capture,
                                 replay_pin=pin, public_capture=public, duration_seconds=30, request_limit=114)
            before = tuple(db.serialize() for db in (stores.state.connection, stores.jobs.db, stores.inbox.connection))

        # The named fixture owns the one synthetic scraper lock. Release it
        # during the actual subprocess, as the production design will require.
        lock_path = state.parent / 'scraper.lock'
        lock = lock_path.stat()
        (scraper_fd,) = (
            fd for fd, identity in _fd_identities().items()
            if identity == (lock.st_dev, lock.st_ino)
        )
        fcntl.flock(scraper_fd, fcntl.LOCK_UN)
        try:
            for name in ('scraper.lock', 'writer.lock'):
                with (state.parent / name).open('rb') as lease:
                    fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            command = [
                sys.executable, '-I', '-S', '-B', str(VERIFIER), '--slot', str(work.slot),
                '--evidence', str(work.slot), '--candidate', str(APPROVED),
                '--reviewed-tools', str(APPROVED / 'dev/pre_release_validation'),
                '--pending-sha256', work.pending_sha256, '--job-sha256', work.job_sha256,
            ]
            first, second = (
                subprocess.run(command, capture_output=True, timeout=30, env={}, check=True)
                for _ in range(2)
            )
        finally:
            fcntl.flock(scraper_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        first, second = json.loads(first.stdout), json.loads(second.stdout)
        assert first['delivery'] == 'NEW' and second['delivery'] == 'REUSED'
        assert first['receipt'] == second['receipt']
        assert first['receipt']['requests_used'] == 114
        assert first['receipt']['result'] == 'VERIFIED_MISMATCH'
        with (cli.writer_lock(state.parent / 'writer.lock'),
              pending.open_verification_stores(state, jobs, inbox, WORKBOOK, readonly=True) as stores):
            result = channel.read_result(stores, runtime, CYCLE_ID, COMPANY_ID, capture)
            assert result['receipt'] == first['receipt']
            assert result['application_authority'] is False
            assert before == tuple(db.serialize() for db in (stores.state.connection, stores.jobs.db, stores.inbox.connection))
