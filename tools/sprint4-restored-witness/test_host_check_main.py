from dataclasses import asdict, replace
import fcntl
import io
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

import host_check_main
import host_checkpoint as checker
from protected_state import WitnessHold
from launcher_witness import LauncherPolicy, LAUNCH_FILES
from site_bundle import build_host_checker
from site_policy import load_policy
from test_host_checkpoint import fake_service, site
import test_protected_state as state_fixtures


def json_default(value):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, frozenset):
        return sorted(value)
    raise TypeError(type(value))


def build_fixture_archive(policy, protected_pin, digest, launcher):
    source = Path(host_check_main.__file__).parent
    destination = policy.maintenance_bundle / 'host-check'
    destination.parent.mkdir()
    data = {
        '__main__.py': (source / 'host_check_main.py').read_bytes(),
        **{name: (source / name).read_bytes() for name in (
            'host_checkpoint.py', 'alternate_writer_witness.py', 'protected_state.py', 'site_policy.py', 'launcher_witness.py',
            'physical_protected_witness.py', 'protected_continuity.py', 'alternate_exchange_witness.py', 'host_exchange.py',
            'ancillary_process_witness.py',
        )},
        'approved_site_policy.json': json.dumps({
            'schema': 'sprint-4-site-policy-v1', 'site': asdict(policy),
            'protected_pin_file': str(protected_pin), 'protected_pin_sha256': digest, 'launchers': asdict(launcher),
        }, default=json_default).encode(),
    }
    build_host_checker(destination, data)
    return destination


def test_archive_loads_private_policy_but_refuses_unobserved_actual_host(site, tmp_path):
    policy, _, _, _ = site
    policy = replace(policy, launch_uid=max(os.geteuid(), 1),
                     marker=policy.project / '.state/integration-release-journal.json',
                     lock_paths=(policy.project / '.integration-install.lock', policy.project / '.state/scraper.lock'))
    pin = tmp_path / 'no-production-protected-pin'
    pins = {name: 'a' * 64 for name in LAUNCH_FILES}
    launcher = LauncherPolicy(policy.project / '.venv/bin/python', Path('/usr/bin/python3'),
                              Path('/usr/bin/bash'), (), pins, pins)
    bundle = build_fixture_archive(policy, pin, 'b' * 64, launcher)
    assert load_policy(bundle) == (policy, pin, 'b' * 64, launcher)
    result = subprocess.run([bundle], input=b'{"unexpected":"fixture-not-real"}',
                            capture_output=True, timeout=3)
    assert result.returncode != 0 and not result.stdout
    assert b'Approved policy or host evidence' in result.stderr
    assert b'fixture-not-real' not in result.stderr


@pytest.mark.parametrize(('reason', 'category'), (
    ('database changed during read', 'SQLITE_CONTINUITY'),
    ('nonempty WAL needs read-only view', 'SQLITE_WAL'),
    ('rollback journal needs reconciliation', 'SQLITE_ROLLBACK_JOURNAL'),
    ('protected state differs from private pin', 'PROTECTED_BASELINE'),
    ('Protected files or writer ownership changed during the checkpoint', 'PROTECTED_CONTINUITY'),
    ('release lease not owned by controller', 'WRITER_LEASE'),
    ('secret path or application data', 'UNCLASSIFIED'),
    ({'unexpected': 'private'}, 'UNCLASSIFIED'),
))
def test_public_protected_refusal_exposes_only_allowlisted_category(reason, category):
    assert host_check_main.protected_refusal(WitnessHold(reason)) == (
        f'Site checkpoint held. Protected release evidence could not be verified. [{category}]'
    )


@pytest.fixture
def restored_clock(monkeypatch):
    elapsed = [0.0]
    monkeypatch.setattr(host_check_main.time, 'monotonic', lambda: elapsed[0])
    monkeypatch.setattr(host_check_main.time, 'sleep', lambda delay: elapsed.__setitem__(0, elapsed[0] + delay))
    return elapsed


def test_restored_stability_rechecks_original_owner_and_all_checks_after_churn(restored_clock, tmp_path, monkeypatch):
    sample = iter(['changing', 'settled', 'settled', 'settled', 'settled', 'settled', 'settled'])
    monkeypatch.setattr(host_check_main, 'physical_snapshot', lambda project: next(sample))
    attempts = []

    def verify():
        attempts.append('complete')
        if len(attempts) == 1:
            raise WitnessHold('database changed during read')
        return {'verified': True}

    result = host_check_main.wait_for_restored_stability(tmp_path, lambda: ('boot', 18, 92), verify)
    assert result == {'verified': True} and attempts == ['complete', 'complete']
    assert restored_clock[0] == 6


def test_restored_stability_holds_real_logical_change_without_retry(restored_clock, tmp_path, monkeypatch):
    monkeypatch.setattr(host_check_main, 'physical_snapshot', lambda project: 'stable')
    attempts = []

    def verify():
        attempts.append('complete')
        raise WitnessHold('protected state differs from private pin')

    with pytest.raises(WitnessHold, match='differs from private pin'):
        host_check_main.wait_for_restored_stability(tmp_path, lambda: 31, verify)
    assert attempts == ['complete'] and restored_clock[0] == 1.5


def test_restored_stability_refuses_unbounded_churn_and_owner_replacement(restored_clock, tmp_path, monkeypatch):
    never = lambda: pytest.fail('No quiet startup interval has been observed')
    monkeypatch.setattr(host_check_main, 'physical_snapshot', lambda project: restored_clock[0])
    with pytest.raises(WitnessHold, match='did not reach a stable'):
        host_check_main.wait_for_restored_stability(tmp_path, lambda: 31, never)
    assert 65 < restored_clock[0] < 70

    restored_clock[0] = 0
    with pytest.raises(WitnessHold, match='writer exclusion is unverified'):
        host_check_main.wait_for_restored_stability(tmp_path, lambda: int(restored_clock[0]), never)
    assert restored_clock[0] == 1.5


def test_restored_stability_rechecks_physical_proof_after_complete_attempt(restored_clock, tmp_path, monkeypatch):
    sample = iter(['quiet', 'quiet', 'changed', 'settled', 'settled', 'settled'])
    monkeypatch.setattr(host_check_main, 'physical_snapshot', lambda project: next(sample))
    results = iter(['first complete evidence', 'second complete evidence'])
    assert host_check_main.wait_for_restored_stability(tmp_path, lambda: 31, lambda: next(results)) == (
        'second complete evidence'
    )


def test_composed_checker_requires_owned_real_fixture_lease_and_unchanged_sqlite(site, monkeypatch, capsys):
    policy, request, old, _ = site
    state_fixture = state_fixtures.ProtectedWitnessTests()
    state_fixture.setUp()
    try:
        project = state_fixture.root
        wrapper = project / 'dev/wrapper-coder/tools'
        host = wrapper / 'host_server.py'
        host.write_bytes(old)
        host.chmod(0o600)
        marker = project / '.state/integration-release-journal.json'
        lock = project / '.state/scraper.lock'
        policy = replace(policy, project=project, marker=marker, wrapper_cwd=wrapper, lock_paths=(lock,))
        request.update(checkpoint='preflight', project=str(project), marker=str(marker),
                       locks=[str(lock)], package=str(project / 'src/job_search_helper'))
        monkeypatch.setattr(host_check_main, 'load_policy',
                            lambda _: (policy, state_fixture.pin, state_fixture.digest, object()))
        monkeypatch.setattr(host_check_main, 'probe_launchers', lambda *args: None)
        monkeypatch.setattr(checker, 'verify_cover', lambda _: None)
        monkeypatch.setattr(checker, 'verify_listener', lambda *args: {83})
        monkeypatch.setattr(checker, 'verify_route_drain', lambda *args: None)
        monkeypatch.setattr(checker, 'verify_wrapper_process', lambda *args: 'stable')
        monkeypatch.setattr(checker, 'unit_status', lambda binary, name:
                            fake_service(policy, name, active=name == checker.WRAPPER_UNIT))
        authenticate = lambda *args: {os.getpid(): ('stable', 'controller.py')}
        monkeypatch.setattr(checker, 'authenticated_maintenance', authenticate)
        monkeypatch.setattr(host_check_main, 'authenticated_maintenance', authenticate)
        executable = policy.maintenance_bundle / 'host-check'
        executable.parent.mkdir()
        executable.write_bytes(b'pinned fixture verifier bytes')
        monkeypatch.setattr(sys, 'argv', [str(executable)])

        def supplied_request():
            monkeypatch.setattr(sys, 'stdin', io.TextIOWrapper(io.BytesIO(json.dumps(request).encode())))

        with lock.open('wb') as lease:
            supplied_request()
            with pytest.raises(WitnessHold, match='release lease not owned'):
                host_check_main.main()
            assert not capsys.readouterr().out
            fcntl.flock(lease, fcntl.LOCK_EX)
            supplied_request()
            host_check_main.main()
            assert json.loads(capsys.readouterr().out) == {**request, 'verified': True}
            state_fixture.sql('inbox', 'UPDATE sync_plans SET cursor=cursor+1')
            supplied_request()
            with pytest.raises(WitnessHold, match='differs from private pin'):
                host_check_main.main()
            assert not capsys.readouterr().out
    finally:
        state_fixture.doCleanups()
