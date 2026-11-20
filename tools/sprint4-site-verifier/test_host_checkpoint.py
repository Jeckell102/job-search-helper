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
        systemctl=Path('/usr/bin/systemctl'), maintenance_bundle=tmp_path / 'bundle',
        maintenance_exe=Path('/usr/bin/python3'), launch_uid=uid, wrapper_active=True,
        wrapper_enabled='enabled', wrapper_unit_file=tmp_path / 'wrapper.service',
        sync_unit_file=tmp_path / 'sync.service', wrapper_args=('/python', str(wrapper / 'host_server.py')),
        wrapper_cwd=wrapper, wrapper_exe=Path('/python'), wrapper_port=18789,
        wrapper_cgroup=Path('/fixture/users/wrapper.service'), network_namespace=(1, 20),
        before_host=checker.SourceFile(sha256(old).hexdigest(), 0o600, uid),
        after_host=checker.SourceFile(sha256(new).hexdigest(), 0o600, uid),
        alternate_roots=(alt,), covers=(CoverPin(alt, (1, 20), 42, (1, 40), uid, ('job-search-scraper',)),),
        source_paths=frozenset({'src/job_search_helper/runner.py'}),
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
    monkeypatch.setattr(checker, 'authenticated_maintenance', lambda *args: {999: ('start', 'controller.py')})
    monkeypatch.setattr(checker, 'verify_route_drain', processes)
    monkeypatch.setattr(checker, 'verify_listener', sockets)
    monkeypatch.setattr(checker, 'unit_status', lambda executable, name: fake_service(policy, name))
    assert checker.attest(request, policy, protected) == {**request, 'verified': True}
    assert covers.call_count == 2
    protected.assert_called_once_with('host-fenced', 'INSTALLED')
    assert sockets.call_count == 2 and processes.call_count == 2
    sockets.assert_called_with(policy, 0, Path('/proc'))
    processes.assert_called_with(policy, 0, Path('/proc'), {999: ('start', 'controller.py')})
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
    monkeypatch.setattr(checker, 'authenticated_maintenance', lambda *args: {})
    monkeypatch.setattr(checker, 'verify_listener', Mock())
    monkeypatch.setattr(checker, 'unit_status',
                        lambda exe, name: fake_service(policy, name, active=name == checker.WRAPPER_UNIT))
    process = Mock(side_effect=['initial-identity', 'replacement-identity'])
    monkeypatch.setattr(checker, 'verify_wrapper_process', process)
    with pytest.raises(ValueError, match='changed during site attestation'):
        checker.attest(request, policy, Mock())
    assert process.call_count == 2


def test_refuses_unrelated_live_listener_for_held_site(site, tmp_path, monkeypatch):
    policy, _, _, _ = site
    proc = tmp_path / 'proc'
    socktable = proc / 'net'
    socktable.mkdir(parents=True)
    (socktable / 'tcp6').write_text('header\n')
    (socktable / 'tcp').write_text('header\n0: 0100007F:4965 00000000:0000 0A 0 0 0 0 0 83\n')
    monkeypatch.setattr(checker, 'namespace_pin', lambda path: policy.network_namespace)
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


def fake_process(proc, pid, parent, args, exe, directory):
    process = proc / str(pid)
    (process / 'fd').mkdir(parents=True)
    info = ['S', str(parent), *(['0'] * 17), str(pid + 5)]
    (process / 'stat').write_text(f'{pid} (fixture) ' + ' '.join(info))
    (process / 'cmdline').write_bytes(b'\0'.join(str(arg).encode() for arg in args) + b'\0')
    (process / 'cwd').symlink_to(directory)
    (process / 'exe').symlink_to(exe)
    return process


def test_exact_maintenance_ancestry_excludes_only_proven_checkout_lock_references(site, tmp_path, monkeypatch):
    policy, request, _, _ = site
    proc = tmp_path / 'proc'
    init = proc / '1'
    init.mkdir(parents=True)
    (init / 'comm').write_text('systemd\n')
    (init / 'cmdline').write_bytes(b'')
    bundle, python = policy.maintenance_bundle, policy.maintenance_exe
    control = fake_process(proc, 101, 1, [python, '-I', bundle / 'controller.py', 'rollback'],
                           python, tmp_path)
    policy.lock_paths[0].touch()
    (control / 'fd/3').symlink_to(policy.lock_paths[0])
    for fd, relative in enumerate(('.', 'dev', 'dev/wrapper-coder', 'dev/wrapper-coder/tools'), start=4):
        (control / f'fd/{fd}').symlink_to(policy.project / relative)
    locks = Mock()
    monkeypatch.setattr(checker, 'verify_flocks', locks)
    request['checkpoint'] = 'preflight'
    pinned = checker.authenticated_maintenance(policy, request, 'preflight', proc, 101)
    assert pinned == {101: ('106', 'controller.py')}
    checker.verify_route_drain(policy, 0, proc, pinned)
    locks.assert_called_once_with(proc, 101, (*policy.lock_paths, bundle / 'controller.lock'))

    options = [
        '--project', policy.project, '--marker', policy.marker, '--gate', bundle / 'installer.lock',
        '--state', bundle / 'transaction', '--verifier', bundle / 'verify_hold',
        '--manifest', bundle / 'manifest.json', '--manifest-sha256', policy.manifest_sha256,
        '--hold-id', policy.maintenance_id, '--fenced-host', '--parked-package',
    ]
    install = fake_process(proc, 102, 101,
                           [python, '-I', '-B', bundle / 'installer.py', 'rollback', *options], python, tmp_path)
    (policy.project / 'src/.s4-maintenance-package').mkdir(parents=True)
    (policy.project / 'src/job_search_helper').mkdir()
    for fd, relative in enumerate(('.', 'src', 'src/job_search_helper', 'src/.s4-maintenance-package',
                                   'dev', 'dev/wrapper-coder', 'dev/wrapper-coder/tools'), start=7):
        (install / f'fd/{fd}').symlink_to(policy.project / relative)
    fake_process(proc, 103, 102, [python, '-I', bundle / 'verify_hold'], python, tmp_path)
    request['checkpoint'] = 'held:entry'
    pinned = checker.authenticated_maintenance(policy, request, 'held', proc, 103)
    assert pinned == {
        103: ('108', 'verify_hold'), 102: ('107', 'installer.py'), 101: ('106', 'controller.py'),
    }
    checker.verify_route_drain(policy, 0, proc, pinned)
    unapproved = policy.project / 'private-writer.py'
    unapproved.touch()
    (install / 'fd/15').symlink_to(unapproved)
    with pytest.raises(ValueError, match='descriptor remains open'):
        checker.verify_route_drain(policy, 0, proc, pinned)
    (install / 'fd/15').unlink()
    fake_process(proc, 104, 1, [python, '-I', '-B', bundle / 'installer.py', 'rollback', *options],
                 python, tmp_path)
    with pytest.raises(ValueError, match='Checkout process remains live'):
        checker.verify_route_drain(policy, 0, proc, pinned)


def test_late_listener_or_process_replacement_refuses_ack(site, monkeypatch):
    policy, request, _, _ = site
    monkeypatch.setattr(checker, 'verify_cover', Mock())
    monkeypatch.setattr(checker, 'authenticated_maintenance', lambda *args: {999: ('start', 'controller.py')})
    monkeypatch.setattr(checker, 'unit_status', lambda executable, name: fake_service(policy, name))
    monkeypatch.setattr(checker, 'verify_route_drain', Mock())
    listener = Mock(side_effect=[set(), ValueError('late listener')])
    monkeypatch.setattr(checker, 'verify_listener', listener)
    with pytest.raises(ValueError, match='late listener'):
        checker.attest(request, policy, Mock())
    assert listener.call_count == 2
    monkeypatch.setattr(checker, 'verify_listener', Mock(return_value=set()))
    monkeypatch.setattr(checker, 'verify_route_drain', Mock(side_effect=[None, ValueError('late process')]))
    with pytest.raises(ValueError, match='late process'):
        checker.attest(request, policy, Mock())


def test_noncanonical_request_or_undefined_hold_checkpoint_refuses(site):
    policy, request, _, _ = site
    with pytest.raises(ValueError, match='Unexpected package route'):
        checker.stage_of({**request, 'package': request['package'] + '/'}, policy)
    held = {**request, 'package': str(policy.project / 'src/.s4-maintenance-package')}
    with pytest.raises(ValueError, match='Unknown site release checkpoint'):
        checker.stage_of({**held, 'checkpoint': 'held:INSTALLING:unapproved.py'}, policy)
    assert checker.stage_of({**held, 'checkpoint': 'held:INSTALLING:src/job_search_helper/runner.py'}, policy) == 'held'


def test_closed_expected_descriptor_does_not_hide_next_open_file(site, tmp_path, monkeypatch):
    policy, _, _, _ = site
    proc = tmp_path / 'proc'
    init = proc / '1'
    init.mkdir(parents=True)
    (init / 'comm').write_text('systemd\n')
    (init / 'cmdline').write_bytes(b'')
    process = fake_process(proc, 202, 1, ['/python', '/bundle/controller.py'], '/python', tmp_path)
    disappearing = process / 'fd/4'
    disappearing.symlink_to(policy.wrapper_cwd)
    unapproved = policy.project / 'unapproved-open-script'
    unapproved.touch()
    (process / 'fd/5').symlink_to(unapproved)
    filesystem_stat = Path.stat

    def stat_with_closed_fd(path, *args, **kwargs):
        if path == disappearing:
            raise FileNotFoundError
        return filesystem_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'stat', stat_with_closed_fd)
    with pytest.raises(ValueError, match='Checkout descriptor remains open'):
        checker.verify_route_drain(policy, 0, proc, {202: ('207', 'controller.py')})

    filesystem_lstat = Path.lstat
    monkeypatch.setattr(Path, 'stat', filesystem_stat)

    def lstat_with_displaced_name(path):
        if path == policy.wrapper_cwd:
            raise FileNotFoundError
        return filesystem_lstat(path)

    monkeypatch.setattr(Path, 'lstat', lstat_with_displaced_name)
    with pytest.raises(ValueError, match='lost its named endpoint'):
        checker.maintenance_descriptor(policy, disappearing, str(policy.wrapper_cwd), 'controller.py')
