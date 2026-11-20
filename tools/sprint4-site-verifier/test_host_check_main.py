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


def build_fixture_archive(policy, protected_pin, digest):
    source = Path(host_check_main.__file__).parent
    destination = policy.maintenance_bundle / 'host-check'
    destination.parent.mkdir()
    data = {
        '__main__.py': (source / 'host_check_main.py').read_bytes(),
        **{name: (source / name).read_bytes() for name in (
            'host_checkpoint.py', 'alternate_writer_witness.py', 'protected_state.py', 'site_policy.py',
        )},
        'approved_site_policy.json': json.dumps({
            'schema': 'sprint-4-site-policy-v1', 'site': asdict(policy),
            'protected_pin_file': str(protected_pin), 'protected_pin_sha256': digest,
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
    bundle = build_fixture_archive(policy, pin, 'b' * 64)
    assert load_policy(bundle) == (policy, pin, 'b' * 64)
    result = subprocess.run([bundle], input=b'{"unexpected":"fixture-not-real"}',
                            capture_output=True, timeout=3)
    assert result.returncode != 0 and not result.stdout
    assert b'Approved policy or host evidence' in result.stderr
    assert b'fixture-not-real' not in result.stderr


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
                            lambda _: (policy, state_fixture.pin, state_fixture.digest))
        monkeypatch.setattr(checker, 'verify_cover', lambda _: None)
        monkeypatch.setattr(checker, 'verify_listener', lambda *args: {83})
        monkeypatch.setattr(checker, 'verify_route_drain', lambda *args: None)
        monkeypatch.setattr(checker, 'verify_wrapper_process', lambda *args: 'stable')
        monkeypatch.setattr(checker, 'unit_status', lambda binary, name:
                            fake_service(policy, name, active=name == checker.WRAPPER_UNIT))
        authenticate = lambda *args: {os.getpid(): ('stable', 'controller.py')}
        monkeypatch.setattr(checker, 'authenticated_maintenance', authenticate)
        monkeypatch.setattr(host_check_main, 'authenticated_maintenance', authenticate)
        monkeypatch.setattr(sys, 'argv', ['/fixture/host-check'])

        def supplied_request():
            monkeypatch.setattr(sys, 'stdin', io.TextIOWrapper(io.BytesIO(json.dumps(request).encode())))

        with lock.open('wb') as lease:
            supplied_request()
            with pytest.raises(WitnessHold, match='closure unverified'):
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
