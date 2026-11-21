import importlib.util
import json
import os
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

from test_s5_ordinary_verifier_handoff import attempt, enrolled, local_worker, measured_scope, stage


@pytest.fixture
def verifier(monkeypatch):
    spec = importlib.util.spec_from_file_location('qa_bound_verifier', Path.cwd() / 'dev/ordinary_rippling_verifier.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name in module.LEASE_ENV:
        monkeypatch.delenv(name, raising=False)
    def forbidden(*args, **kwargs):
        pytest.fail('a rejected attempt must not launch a child or replay evidence')
    monkeypatch.setattr(module, 'run_child', forbidden)
    monkeypatch.setattr(module, 'replay_public', forbidden)
    return module


def args_for(work, *, proof=True, empty_slot=None):
    slot = work.slot if empty_slot is None else empty_slot
    return SimpleNamespace(slot=slot, evidence=slot, candidate=slot, reviewed_tools=slot,
                           pending_sha256=work.pending_sha256, job_sha256=work.job_sha256,
                           owner_slot=work.owner_slot if proof else None)


def assert_never_reserved(slot):
    for name in ('verifier.lock', 'reservation.json', 'receipt.json'):
        assert not (slot / name).exists()


@pytest.mark.parametrize('measured_scope', [True], indirect=True)
@pytest.mark.parametrize('fault,reason', [
    ('directory-copy', 'assigned_offline_slot_changed'),
    ('missing-anchor', 'assigned_offline_owner_changed'),
    ('omitted-token', 'assigned_offline_slot_requires_owner_proof'),
    ('omitted-token-no-manifest', 'assigned_offline_slot_requires_owner_proof'),
])
def test_supervisor_refuses_assignment_fault_before_reservation(enrolled, verifier, fault, reason):
    _, root, _, _, _, _ = enrolled
    work = stage(enrolled)
    if fault == 'directory-copy':
        moved = root / 'moved-original'
        work.slot.rename(moved)
        shutil.copytree(moved, work.slot)
    elif fault == 'missing-anchor':
        (root / (work.slot.name + '.json')).unlink()
    elif fault == 'omitted-token-no-manifest':
        (work.slot / 'owner.json').unlink()
    with pytest.raises(verifier.Stop, match=reason):
        verifier.supervise(args_for(work, proof=not fault.startswith('omitted-token')))
    assert_never_reserved(work.slot)


@pytest.mark.parametrize('measured_scope', [True], indirect=True)
def test_legacy_fixture_without_owner_keeps_separate_offline_route(enrolled, verifier, monkeypatch, tmp_path):
    work = stage(enrolled)
    slot = tmp_path / 'isolated-legacy'
    slot.mkdir(mode=0o700)
    shutil.copy2(work.slot / 'pending.json', slot / 'pending.json')
    job = json.loads((work.slot / 'job.json').read_bytes())
    job['schema'] = verifier.JOB
    old_job = verifier.canonical(job)
    (slot / 'job.json').write_bytes(old_job)
    (slot / 'job.json').chmod(0o600)
    calls = []

    def fake_offline_child(*args):
        calls.append(args)
        return {'result': 'HOLD', 'reason': 'fixture_offline_held', 'evidence': None, 'requests_used': 0}

    monkeypatch.setattr(verifier, 'run_child', fake_offline_child)
    args = args_for(work, proof=False, empty_slot=slot)
    args.job_sha256 = verifier.digest(old_job)
    assert verifier.supervise(args)['delivery'] == 'NEW'
    assert verifier.supervise(args)['delivery'] == 'REUSED'
    assert len(calls) == 1


@pytest.mark.parametrize('measured_scope', [True], indirect=True)
def test_child_rechecks_assigned_owner_before_budget(enrolled, verifier):
    _, root, _, _, _, _ = enrolled
    work = stage(enrolled)
    args = args_for(work)
    metadata = verifier.verification_identity(args)
    (root / (work.slot.name + '.json')).unlink()
    reader, writer = os.pipe()
    with os.fdopen(writer, 'wb') as gate:
        gate.write(verifier.canonical({
            'owner_pid': os.getppid(), 'identity': metadata,
            'slot_identity': verifier.physical_identity(work.slot.stat()),
        }))
    args.worker = reader
    result = verifier.worker(args)
    assert result == {'result': 'CHANGED_INPUT', 'reason': 'assigned_offline_owner_changed',
                      'evidence': None, 'requests_used': 0}
    assert_never_reserved(work.slot)


@pytest.mark.parametrize('measured_scope', [True], indirect=True)
def test_supervisor_rechecks_sibling_record_before_reserving(enrolled, verifier, monkeypatch):
    _, root, _, _, _, _ = enrolled
    work = stage(enrolled)
    anchor = root / (work.slot.name + '.json')
    original_read = verifier.read_pin

    def read_with_interruption(directory, name, expected):
        value = original_read(directory, name, expected)
        if name == 'pending.json' and anchor.exists():
            anchor.unlink()
        return value

    monkeypatch.setattr(verifier, 'read_pin', read_with_interruption)
    with pytest.raises(verifier.Stop, match='assigned_offline_owner_changed'):
        verifier.supervise(args_for(work))
    assert not (work.slot / 'reservation.json').exists()


@pytest.mark.parametrize('measured_scope', [True], indirect=True)
def test_assigned_job_does_not_become_legacy_after_detached_copy(enrolled, verifier, tmp_path):
    work = stage(enrolled)
    slot = tmp_path / 'isolated-detached-assignment'
    slot.mkdir(mode=0o700)
    for name in ('pending.json', 'job.json'):
        shutil.copy2(work.slot / name, slot / name)
    args = args_for(work, proof=False, empty_slot=slot)
    with pytest.raises(verifier.Stop, match='assigned_offline_slot_requires_owner_proof'):
        verifier.supervise(args)
    assert_never_reserved(slot)
