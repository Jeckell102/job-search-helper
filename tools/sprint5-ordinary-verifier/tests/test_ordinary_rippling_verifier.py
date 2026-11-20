"""Exercise private bounded verifier custody without a scraper, database or network."""

import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

import ordinary_rippling_verifier as v


SCRIPT = Path(v.__file__).resolve()
AUTHORITY = Path('/tmp/jsh-m5-live-authority-repair.jMbESo7E')
PUBLIC = AUTHORITY / 'checkpoints/pytest-final-repair/test_full_original_employer_an0'
RED = Path('/tmp/jsh-s5-ordinary-sealed-evidence-red.PBkhfctW/fixture_data/public-rippling.json')
PUBLIC_SHA = '75feafd84ced0cbeb8ce855eedbcb02ce8fe3582faeb034c10a924d34e992480'
RED_SHA = 'a69b02cd011f98d5dddde1c6faa10a621b87894829421a24aa60ce8fefcbed0b'


def private(path, raw):
    path.write_bytes(raw)
    path.chmod(0o600)
    return path


def saved_fixture(directory):
    folder = directory / 'evidence'
    folder.mkdir(mode=0o700)
    capture = PUBLIC / 'capture.json'
    pin = json.loads((PUBLIC / 'pin.json').read_text())
    assert v.digest(capture.read_bytes()) == pin['capture_sha256'] == PUBLIC_SHA
    shutil.copyfile(capture, folder / 'public-capture.json')
    (folder / 'public-capture.json').chmod(0o600)
    replay_pin = private(folder / 'replay-pin.json', v.canonical(pin))
    red_raw = RED.read_bytes()
    assert v.digest(red_raw) == RED_SHA
    red = json.loads(red_raw)
    stale = red['expected']['stale_board']
    observed = red['expected']['foreign_board_slug']
    mismatch = private(folder / 'configured-response.html', red['responses'][stale].encode())
    return folder, pin, v.digest(replay_pin.read_bytes()), stale, observed, mismatch


@pytest.fixture(scope='session')
def saved(tmp_path_factory):
    return saved_fixture(tmp_path_factory.mktemp('private-corpus'))


def make_job(tmp_path, saved, *, limit=128, duration=30, edit_pending=None, edit_job=None):
    evidence, pin, pin_sha, stale, foreign, mismatch = saved
    slot = tmp_path / 'slot'
    slot.mkdir(mode=0o700)
    config = 'c' * 64
    observation_sha = v.digest(mismatch.read_bytes())
    pending = {'schema': v.PENDING, 'owner': {'cycle_id': 'CYC-000000000001', 'cycle_started_at': '2026-11-20T18:13:00+00:00',
               'request_id': 'SCAN-001', 'request_fingerprint': 'd' * 64, 'company_id': 'COMP-0066',
               'source_revision': pin['scope'][0]['source_revision'], 'company_source_sha256': pin['scope'][0]['company_row_sha256'],
               'store_binding_sha256': 'e' * 64, 'observation_generation': 1},
               'admission': {'authority_url': v.FORTERRA_URL, 'configured_url': stale, 'capability_id': 'rippling-shared-v1',
                             'capability_digest': 'a' * 64, 'mapping_digest': 'b' * 64, 'configuration_digest': config,
                             'matrix_digest': 'f' * 64, 'runtime_binding_sha256': '1' * 64},
               'observation': {'schema': v.OBSERVATION, 'configured_url': stale, 'expected_slug': v.slug_for_url(stale),
                               'observed_slug': foreign, 'response_sha256': observation_sha}}
    if edit_pending:
        edit_pending(pending)
    pending_sha = v.digest(v.canonical(pending))
    job = {'schema': v.JOB, 'pending_sha256': pending_sha, 'candidate_replay_pin_sha256': pin_sha,
           'mismatch_response_sha256': observation_sha, 'deadline_unix_ms': time.time_ns() // 1_000_000 + int(duration * 1000),
           'request_limit': limit}
    if edit_job:
        edit_job(job)
    job_sha = v.digest(v.canonical(job))
    private(slot / 'pending.json', v.canonical(pending))
    private(slot / 'job.json', v.canonical(job))
    args = SimpleNamespace(slot=slot, evidence=evidence, candidate=AUTHORITY,
                           reviewed_tools=AUTHORITY / 'dev/pre_release_validation', pending_sha256=pending_sha,
                           job_sha256=job_sha)
    return args, pending, job


def invoke(args, *, extra=(), environment=None):
    command = [sys.executable, '-I', '-S', '-B', str(SCRIPT), *extra]
    for key, value in vars(args).items():
        command.extend(('--' + key.replace('_', '-'), str(value)))
    result = subprocess.run(command, capture_output=True, text=True, timeout=40, check=False, env=environment)
    assert not result.stderr
    return result.returncode, json.loads(result.stdout)


def test_full_verified_mismatch_is_bounded_and_restart_reuses_receipt(tmp_path, saved):
    args, pending, job = make_job(tmp_path, saved, limit=114)
    code, result = invoke(args)
    assert code == 0 and result['result'] == 'VERIFIED_MISMATCH', result
    assert result['delivery'] == 'NEW'
    receipt = result['receipt']
    evidence = receipt['evidence']
    assert receipt['requests_used'] == receipt['request_limit'] == 114 and receipt['mode'] == 'offline_saved_captures'
    assert evidence['configured_observation_sha256'] == pending['observation']['response_sha256']
    assert evidence['candidate_inventory_digest'] == 'ce001b011f2dfaf778b4a6980845f8a9af274b8bf635aec3c492b533e32c76b6'
    assert evidence['regression_inventory_digest'] == 'de34debc1ddce8c16a9df083c7165af4c0b6c5d8fce69f346f1159e21975f4ce'
    assert (args.slot / 'receipt.json').stat().st_mode & 0o777 == 0o600
    assert {path.name for path in args.slot.iterdir()} == {
        'reservation.json', 'receipt.json', 'job.json', 'pending.json', 'verifier.lock',
    }
    args.evidence = tmp_path / 'missing-corpus-after-restart'
    code, restarted = invoke(args)
    assert code == 0 and restarted['delivery'] == 'REUSED'
    assert restarted['receipt'] == receipt and restarted['receipt_sha256'] == result['receipt_sha256']


@pytest.mark.parametrize('limit', [1, 113])
def test_request_exhaustion_never_degrades_to_generic_hold(tmp_path, saved, limit):
    args, _, _ = make_job(tmp_path, saved, limit=limit)
    code, result = invoke(args)
    assert code == 1 and result['result'] == 'BUDGET_EXHAUSTED', result
    assert result['receipt']['requests_used'] == limit and result['receipt']['evidence'] is None
    assert invoke(args)[1]['delivery'] == 'REUSED'


@pytest.mark.parametrize('duration', [-2, 0.30])
def test_expired_and_active_deadline_are_terminal(tmp_path, saved, duration):
    args, _, _ = make_job(tmp_path, saved, duration=duration)
    code, result = invoke(args)
    assert code == 1 and result['result'] == 'TIMEOUT', result
    assert result['receipt']['evidence'] is None
    code, reuse = invoke(args)
    assert code == 1 and reuse['delivery'] == 'REUSED' and reuse['receipt_sha256'] == result['receipt_sha256']


def test_independent_foreign_slug_drift_holds_even_with_exact_response_bytes(tmp_path, saved):
    def different_observation(pending):
        pending['observation']['observed_slug'] = 'another-foreign-tenant'

    args, _, _ = make_job(tmp_path, saved, edit_pending=different_observation)
    code, result = invoke(args)
    assert code == 1 and result['result'] == 'HOLD', result
    assert result['receipt']['requests_used'] == 1 and result['receipt']['evidence'] is None


@pytest.mark.parametrize('changed', ['generation', 'runtime', 'company', 'response', 'job'])
def test_changed_exact_pending_or_job_refuses_without_reservation(tmp_path, saved, changed):
    args, pending, job = make_job(tmp_path, saved)
    if changed == 'job':
        job['request_limit'] = 44
        private(args.slot / 'job.json', v.canonical(job))
    else:
        target, key, value = {
            'generation': ('owner', 'observation_generation', 2), 'runtime': ('admission', 'runtime_binding_sha256', '2' * 64),
            'company': ('owner', 'company_source_sha256', '3' * 64), 'response': ('observation', 'response_sha256', '4' * 64),
        }[changed]
        pending[target][key] = value
        private(args.slot / 'pending.json', v.canonical(pending))
    code, result = invoke(args)
    assert code == 1 and result['result'] == 'CHANGED_INPUT' and result['delivery'] == 'REJECTED'
    assert not (args.slot / 'reservation.json').exists() and not (args.slot / 'receipt.json').exists()


def test_changed_private_configured_bytes_are_terminal_without_positive_evidence(tmp_path, saved):
    args, _, _ = make_job(tmp_path, saved)
    evidence = tmp_path / 'different-evidence'
    shutil.copytree(args.evidence, evidence)
    changed = evidence / 'configured-response.html'
    private(changed, changed.read_bytes() + b'changed')
    args.evidence = evidence
    code, result = invoke(args)
    assert code == 1 and result['result'] == 'CHANGED_INPUT', result
    assert result['receipt']['reason'] == 'configured_response_changed' and result['receipt']['evidence'] is None


@pytest.mark.parametrize('expired', [False, True])
def test_restart_after_durable_reservation_does_not_refetch(tmp_path, saved, expired):
    args, _, _ = make_job(tmp_path, saved, duration=-1 if expired else 30)
    private(args.slot / 'reservation.json', v.canonical(v.verification_identity(args)))
    args.evidence = tmp_path / 'missing-evidence-never-opened'
    code, result = invoke(args)
    assert code == 1 and result['delivery'] == 'INTERRUPTED'
    assert result['result'] == ('TIMEOUT' if expired else 'HOLD')
    assert result['receipt']['requests_used'] is None and result['receipt']['evidence'] is None
    assert invoke(args)[1]['delivery'] == 'REUSED'


def test_concurrent_attempt_and_application_lease_refuse_without_reservation(tmp_path, saved):
    args, _, _ = make_job(tmp_path, saved)
    mutex = private(args.slot / 'verifier.lock', b'')
    with mutex.open('rb') as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        assert invoke(args)[1]['delivery'] == 'BUSY'
    env = {**os.environ, 'JSH_SCRAPER_ADMISSION_FD': '8'}
    assert invoke(args, environment=env)[1]['reason'] == 'inherited_application_lease_present'
    assert not (args.slot / 'reservation.json').exists() and not (args.slot / 'receipt.json').exists()


def test_direct_worker_without_supervisor_gate_cannot_replay(tmp_path, saved):
    args, _, _ = make_job(tmp_path, saved)
    _, result = invoke(args, extra=('--worker', '0'))
    assert result['result'] == 'HOLD' and result['requests_used'] == 0
    assert not (args.slot / 'reservation.json').exists()


def test_pending_staleness_after_worker_discards_success(tmp_path, saved, monkeypatch):
    args, pending, _ = make_job(tmp_path, saved)

    def worker_returns_as_owner_advances(_args, _job, _slot_identity):
        pending['owner']['observation_generation'] += 1
        private(args.slot / 'pending.json', v.canonical(pending))
        return {'result': 'VERIFIED_MISMATCH', 'reason': 'would_not_be_used', 'evidence': {'unused': True}, 'requests_used': 5}

    monkeypatch.setattr(v, 'run_child', worker_returns_as_owner_advances)
    result = v.supervise(args)
    assert result['result'] == 'CHANGED_INPUT' and result['receipt']['evidence'] is None
    assert invoke(args)[1]['delivery'] == 'REJECTED'


def test_changed_checksum_or_missing_reservation_refuses_reuse(tmp_path, saved):
    args, _, _ = make_job(tmp_path, saved, duration=-3)
    assert invoke(args)[1]['result'] == 'TIMEOUT'
    receipt_path = args.slot / 'receipt.json'
    saved_receipt = receipt_path.read_bytes()
    corrupted = json.loads(saved_receipt)
    corrupted['receipt']['reason'] = 'changed'
    private(receipt_path, v.canonical(corrupted))
    assert invoke(args)[1]['reason'] == 'conflicting_private_receipt'
    private(receipt_path, saved_receipt)
    (args.slot / 'reservation.json').unlink()
    assert invoke(args)[1]['reason'] == 'conflicting_private_receipt'


def test_slot_replacement_during_worker_cannot_receive_old_result(tmp_path, saved, monkeypatch):
    args, _, _ = make_job(tmp_path, saved)
    replaced = tmp_path / 'formerly-owned-slot'

    def rename_slot(_args, _job, _slot_identity):
        args.slot.rename(replaced)
        args.slot.mkdir(mode=0o700)
        return {'result': 'HOLD', 'reason': 'unused', 'evidence': None, 'requests_used': 0}

    monkeypatch.setattr(v, 'run_child', rename_slot)
    with pytest.raises(v.Stop, match='private_slot_path_changed') as error:
        v.supervise(args)
    assert error.value.result == 'CHANGED_INPUT'
    assert not (args.slot / 'receipt.json').exists() and not (replaced / 'receipt.json').exists()
