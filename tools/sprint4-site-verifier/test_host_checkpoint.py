from dataclasses import replace
from hashlib import sha256
import json
import os
from pathlib import Path
from unittest.mock import Mock

import pytest

import host_checkpoint as checker
from alternate_writer_witness import CoverPin


@pytest.fixture
def site(tmp_path):
    root = tmp_path / 'primary'
    wrapper = root / 'dev/wrapper-coder/tools'
    wrapper.mkdir(parents=True)
    old, new = b'synthetic old host', b'synthetic new host'
    uid = os.geteuid()
    alt = tmp_path / 'alternate checkout'
    policy = checker.SitePolicy(
        project=root, marker=root / '.state/release.json',
        lock_paths=(root / 'scraper.lock', root / 'writer.lock'),
        cache_prefixes=(), maintenance_id='fixture-held', manifest_sha256='a' * 64,
        systemctl=Path('/usr/bin/systemctl'), launch_uid=uid, wrapper_active=True,
        wrapper_enabled='enabled', wrapper_unit_file=tmp_path / 'wrapper.service',
        sync_unit_file=tmp_path / 'sync.service', wrapper_args=('/python', str(wrapper / 'host_server.py')),
        wrapper_cwd=wrapper, wrapper_exe=Path('/python'), wrapper_port=18789,
        wrapper_cgroup=Path('/fixture/users/wrapper.service'),
        before_host=checker.SourceFile(sha256(old).hexdigest(), 0o600, uid),
        after_host=checker.SourceFile(sha256(new).hexdigest(), 0o600, uid),
        alternate_roots=(alt,), covers=(CoverPin(alt, (1, 20), 42, (1, 40), uid, ('job-search-scraper',)),),
    )
    request = {
        'schema': 'sprint-4-host-check-v1', 'nonce': 'f' * 32,
        'checkpoint': 'host-fenced', 'project': str(root), 'package': str(root / 'src/job_search_helper'),
        'marker': str(policy.marker), 'backend': 'sqlite', 'target': 'INSTALLED',
        'maintenance_id': policy.maintenance_id, 'locks': list(map(str, policy.lock_paths)),
        'pycache_prefixes': [], 'source_manifest_sha256': policy.manifest_sha256,
    }
    policy.marker.parent.mkdir()
    policy.marker.write_text(json.dumps({
        'schema': 'integration-release-journal-v1', 'state': 'FOUNDATION_MAINTENANCE',
        'maintenance_id': policy.maintenance_id,
    }))
    policy.marker.chmod(0o600)
    return policy, request, old, new


def fake_service(policy, name, active=False):
    is_wrapper = name == checker.WRAPPER_UNIT
    return {
        'ActiveState': 'active' if active else 'inactive', 'MainPID': '21' if active else '0',
        'UnitFileState': 'enabled' if is_wrapper else 'disabled',
        'FragmentPath': str(policy.wrapper_unit_file if is_wrapper else policy.sync_unit_file),
        'ControlGroup': str(policy.wrapper_cgroup) if active else '',
    }


def test_held_checkpoint_requires_evidence_and_echoes_exact_request(site, monkeypatch):
    policy, request, _, _ = site
    covers, protected, processes, sockets = Mock(), Mock(), Mock(), Mock()
    monkeypatch.setattr(checker, 'verify_cover', covers)
    monkeypatch.setattr(checker, 'verify_route_drain', processes)
    monkeypatch.setattr(checker, 'verify_listener', sockets)
    monkeypatch.setattr(checker, 'unit_status', lambda executable, name: fake_service(policy, name))
    assert checker.attest(request, policy, protected) == {**request, 'verified': True}
    assert covers.call_count == 2
    protected.assert_called_once_with('host-fenced', 'INSTALLED')
    sockets.assert_called_once_with(policy, 0, Path('/proc'))
    processes.assert_called_once_with(policy, 0, Path('/proc'))
    with pytest.raises(ValueError, match='lacks a separate cover'):
        checker.attest(request, replace(policy, covers=()), protected)


def test_refuses_a_foreign_marker_or_present_fenced_host(site, monkeypatch):
    policy, request, _, new = site
    monkeypatch.setattr(checker, 'verify_cover', Mock())
    services = Mock()
    monkeypatch.setattr(checker, 'unit_status', services)
    host = policy.wrapper_cwd / 'host_server.py'
    host.write_bytes(new)
    with pytest.raises(ValueError, match='entry must be absent'):
        checker.attest(request, policy, Mock())
    host.unlink()
    policy.marker.write_text('{}')
    with pytest.raises(ValueError, match='does not prove this release hold'):
        checker.attest(request, policy, Mock())
    services.assert_not_called()


def test_restored_checkpoint_checks_target_and_running_process_twice(site, monkeypatch):
    policy, request, old, new = site
    policy.marker.unlink()
    request['checkpoint'] = 'restored'
    host = policy.wrapper_cwd / 'host_server.py'
    host.write_bytes(old)
    host.chmod(0o600)
    monkeypatch.setattr(checker, 'verify_cover', Mock())
    with pytest.raises(ValueError, match='differs from the approved endpoint'):
        checker.attest(request, policy, Mock())
    host.write_bytes(new)
    monkeypatch.setattr(checker, 'verify_route_drain', Mock())
    monkeypatch.setattr(checker, 'verify_listener', Mock())
    monkeypatch.setattr(checker, 'unit_status',
                        lambda exe, name: fake_service(policy, name, active=name == checker.WRAPPER_UNIT))
    process = Mock(side_effect=['initial-identity', 'replacement-identity'])
    monkeypatch.setattr(checker, 'verify_wrapper_process', process)
    with pytest.raises(ValueError, match='changed during site attestation'):
        checker.attest(request, policy, Mock())
    assert process.call_count == 2


def test_refuses_unrelated_live_listener_for_held_site(site, tmp_path):
    policy, _, _, _ = site
    proc = tmp_path / 'proc'
    socktable = proc / 'net'
    socktable.mkdir(parents=True)
    (socktable / 'tcp6').write_text('header\n')
    (socktable / 'tcp').write_text('header\n0: 0100007F:4965 00000000:0000 0A 0 0 0 0 0 83\n')
    with pytest.raises(ValueError, match='survived the hold'):
        checker.verify_listener(policy, 0, proc)


def test_rejects_checkout_process_with_open_old_host_source(site, tmp_path):
    policy, _, _, _ = site
    proc = tmp_path / 'proc'
    init = proc / '1'
    init.mkdir(parents=True)
    (init / 'comm').write_text('systemd\n')
    (init / 'cmdline').write_bytes(b'')
    worker = proc / '8888'
    (worker / 'fd').mkdir(parents=True)
    (worker / 'cmdline').write_bytes(b'python\0')
    (worker / 'cwd').symlink_to(tmp_path)
    (worker / 'fd/5').symlink_to(str(policy.wrapper_cwd / 'host_server.py') + ' (deleted)')
    with pytest.raises(ValueError, match='descriptor remains open'):
        checker.verify_route_drain(policy, 0, proc)
