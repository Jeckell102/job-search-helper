"""Explicit offline integration check using the separately approved saved corpus."""

import fcntl
from contextlib import ExitStack
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from job_search_helper import cli, ordinary_raw_capture as raw, ordinary_verification_pending as pending
from job_search_helper import ordinary_verifier_handoff as handoff
from job_search_helper.company_events import source_revision
from job_search_helper.runtime_mapping_facts import _fd_identities
from test_ordinary_verification_pending import CYCLE_ID, attempt
from test_s5_ordinary_publication_continuation import WORKBOOK, measured_scope
from test_s5_ordinary_verifier_handoff import COMPANY_ID, digest, pack, use_forterra_source
from test_s5_ordinary_worker_handoff import local_worker


APPROVED = Path('/tmp/jsh-m5-live-authority-repair.jMbESo7E')
CORPUS = APPROVED / 'checkpoints/pytest-final-repair/test_full_original_employer_an0'
VERIFIER = Path(__file__).resolve().parents[1] / 'dev/ordinary_rippling_verifier.py'
PREVIOUS_VERIFIER = Path('/tmp/jsh-s5-ordinary-verifier-bound-launch.c33tr0iC/dev/ordinary_rippling_verifier.py')
REVIEWED_TOOLS = VERIFIER.parent / 'pre_release_validation'
CURRENT_CONTROL = 'Performance Drone Works (PDW)'
SAVED_MISMATCH = Path('/tmp/jsh-s5-ordinary-sealed-evidence-red.PBkhfctW/fixture_data/public-rippling.json')


def _pin_file(path, expected):
    value = path.read_bytes()
    assert digest(value) == expected
    return value


@pytest.mark.parametrize('measured_scope', [True], indirect=True)
@pytest.mark.parametrize(('control_name', 'old_tools'), [
    ('PDW', False), (CURRENT_CONTROL, False), (CURRENT_CONTROL, True),
])
def test_approved_offline_worker_consumes_owner_work_and_returns_exact_evidence(
    measured_scope, monkeypatch, tmp_path, control_name, old_tools,
):
    public = _pin_file(CORPUS / 'capture.json', '75feafd84ced0cbeb8ce855eedbcb02ce8fe3582faeb034c10a924d34e992480')
    replay_pin = json.loads((CORPUS / 'pin.json').read_bytes())
    if control_name != 'PDW':
        corpus = json.loads(public)
        company = corpus['cases'][1]['company']
        assert company['Company ID'] == 'COMP-0178' and company['Company'] == 'PDW'
        company['Company'] = control_name
        public = pack(corpus)
        replay_pin['capture_sha256'] = digest(public)
        replay_pin['scope'][1].update(company=control_name, company_row_sha256=digest(pack(company)),
                                      source_revision=source_revision(company))
    pin = pack(replay_pin)
    _pin_file(VERIFIER, 'ae39cb34ab229eee22b66f34dbe2d1486d2f08f0e1de0acc43970a8d15bbff14')
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
                '--reviewed-tools', str(REVIEWED_TOOLS),
                '--pending-sha256', work.pending_sha256, '--job-sha256', work.job_sha256,
            ]
            missing_proof = subprocess.run(command, capture_output=True, timeout=30, env={}, check=False)
            assert missing_proof.returncode == 1
            assert json.loads(missing_proof.stdout)['reason'] == 'assigned_offline_slot_requires_owner_proof'
            manifest = work.slot / 'owner.json'
            retained_manifest = root / 'retained-slot-manifest.json'
            manifest.rename(retained_manifest)
            missing_proof = subprocess.run(command, capture_output=True, timeout=30, env={}, check=False)
            assert missing_proof.returncode == 1
            assert json.loads(missing_proof.stdout)['reason'] == 'assigned_offline_slot_requires_owner_proof'
            assert not (work.slot / 'verifier.lock').exists()
            retained_manifest.rename(manifest)
            command.extend(('--owner-slot', work.owner_slot))
            _pin_file(PREVIOUS_VERIFIER, 'f218ed98eb0991e72c78b7ddaaf67dcde41f48b6a3d472e171cc5e26b2de1164')
            previous_command = command.copy()
            previous_command[4] = str(PREVIOUS_VERIFIER)
            rejected = subprocess.run(previous_command, capture_output=True, timeout=30, env={}, check=False)
            assert rejected.returncode == 1
            assert json.loads(rejected.stdout)['reason'] == 'assigned_offline_slot_changed'
            assert not (work.slot / 'verifier.lock').exists()
            original_dir = root / 'retained-original-work'
            work.slot.rename(original_dir)
            shutil.copytree(original_dir, work.slot)
            rejected = subprocess.run(command, capture_output=True, timeout=30, env={}, check=False)
            assert rejected.returncode == 1
            assert json.loads(rejected.stdout)['reason'] == 'assigned_offline_slot_changed'
            assert not (work.slot / 'verifier.lock').exists()
            assert not (work.slot / 'reservation.json').exists()
            shutil.rmtree(work.slot)
            original_dir.rename(work.slot)

            anchor = root / (work.slot.name + '.json')
            retained_anchor = root / 'retained-owner-record.json'
            anchor.rename(retained_anchor)
            rejected = subprocess.run(command, capture_output=True, timeout=30, env={}, check=False)
            assert rejected.returncode == 1
            assert json.loads(rejected.stdout)['reason'] == 'assigned_offline_owner_changed'
            assert not (work.slot / 'verifier.lock').exists()
            retained_anchor.rename(anchor)
            if old_tools:
                downgraded = command.copy()
                downgraded[downgraded.index('--reviewed-tools') + 1] = str(APPROVED / 'dev/pre_release_validation')
                first = subprocess.run(downgraded, capture_output=True, timeout=30, env={}, check=False)
            else:
                first = subprocess.run(command, capture_output=True, timeout=30, env={}, check=True)
            second = subprocess.run(command, capture_output=True, timeout=30, env={}, check=not old_tools)
        finally:
            fcntl.flock(scraper_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert first.returncode == second.returncode == int(old_tools)
        first, second = json.loads(first.stdout), json.loads(second.stdout)
        assert first['delivery'] == 'NEW' and second['delivery'] == 'REUSED'
        assert first['receipt'] == second['receipt']
        assert first['receipt_sha256'] == second['receipt_sha256'] == digest(pack(first['receipt']))
        assert first['receipt']['identity']['reviewed_tools_sha256'] == '86723e7fdc0e4e8acdae2dbdc9516c93f0e4557c60ef3b75d17f20869bd3eac0'
        assert first['receipt']['identity']['verifier_sha256'] == 'ae39cb34ab229eee22b66f34dbe2d1486d2f08f0e1de0acc43970a8d15bbff14'
        if old_tools:
            assert first['receipt']['result'] == 'CHANGED_INPUT'
            assert first['receipt']['reason'] == 'reviewed_verifier_source_changed'
            assert first['receipt']['requests_used'] == 0
            assert first['receipt']['evidence'] is None
        else:
            assert first['receipt']['requests_used'] == 114
            assert first['receipt']['result'] == 'VERIFIED_MISMATCH'
            evidence = first['receipt']['evidence']
            assert evidence['candidate_vector'] == replay_pin['candidate']
            assert evidence['replay_capture_sha256'] == digest(public)
            assert evidence['regression_inventory_digest'] == 'de34debc1ddce8c16a9df083c7165af4c0b6c5d8fce69f346f1159e21975f4ce'
        with (cli.writer_lock(state.parent / 'writer.lock'),
              pending.open_verification_stores(state, jobs, inbox, WORKBOOK, readonly=True) as stores):
            result = channel.read_result(stores, runtime, CYCLE_ID, COMPANY_ID, capture)
            assert result['receipt'] == first['receipt']
            assert result['application_authority'] is False
            assert before == tuple(db.serialize() for db in (stores.state.connection, stores.jobs.db, stores.inbox.connection))
