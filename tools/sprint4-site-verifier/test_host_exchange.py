from dataclasses import asdict
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile

import pytest

import host_exchange as exchange


def path_pin(path):
    flags = exchange.DIRECTORY if path.is_dir() else os.O_RDONLY | exchange.FILE
    fd = os.open(path, flags)
    try:
        return asdict(exchange.pin(fd))
    finally:
        os.close(fd)


def seal(path, raw):
    path.touch(mode=0o600, exist_ok=True)
    data = exchange.encode(raw)
    path.write_bytes(data)
    return exchange.HostExchange(path, sha256(data).hexdigest())


@pytest.fixture
def fixture():
    exchange.FIXTURE_BASE.mkdir(mode=0o700, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=exchange.FIXTURE_BASE) as name:
        root = Path(name)
        control = root / 'private'
        control.mkdir(mode=0o700)
        lock = control / exchange.LOCK
        lock.touch(mode=0o600)
        first, second = root / 'routes 1', root / 'routes 2'
        first.mkdir(mode=0o700)
        second.mkdir(mode=0o700)
        pairs = []
        for parent, name in ((first, 'copy a'), (second, 'copy b'), (first, 'copy c')):
            canonical, parked = parent / name, parent / f'{exchange.PARK_PREFIX}{name}'
            canonical.mkdir(mode=0o700)
            (canonical / 'launcher').write_text(name)
            parked.mkdir(mode=0o500)
            pairs.append(dict(parent=str(parent), canonical=name, parked=parked.name,
                              parent_pin=path_pin(parent), original_pin=path_pin(canonical),
                              sentinel_pin=path_pin(parked)))
        raw = dict(schema=exchange.POLICY_SCHEMA, mode='fixture', generation='a'*32,
                   mount_namespace=os.readlink('/proc/self/ns/mnt'), control=str(control),
                   control_pin=path_pin(control), lock_pin=path_pin(lock), pairs=pairs)
        yield seal(control / exchange.POLICY, raw), raw


def loaded(controller):
    return exchange.load_policy(controller.policy_path, controller.approved_sha256)


def disk_journal(controller):
    return json.loads((controller.policy_path.parent / exchange.JOURNAL).read_bytes())


def states(controller):
    return [(pair.canonical / 'launcher').exists() for pair in loaded(controller).pairs]


def interrupt(monkeypatch, operation, name):
    original = getattr(exchange, name)

    def stop(*args, **kwargs):
        original(*args, **kwargs)
        os._exit(61)

    with monkeypatch.context() as patch:
        patch.setattr(exchange, name, stop)
        pid = os.fork()
        if pid == 0:
            try:
                operation()
            finally:
                os._exit(62)
        _, status = os.waitpid(pid, 0)
    assert os.WIFEXITED(status) and os.WEXITSTATUS(status) == 61


def test_prepare_pins_all_pairs_and_replay_closes_after_exact_next_swap(fixture, monkeypatch):
    controller, _ = fixture
    digest = controller.prepare()
    assert controller.prepare() == digest
    assert len(disk_journal(controller)['intent']['pairs']) == 3
    interrupt(monkeypatch, controller.close, '_exchange')
    assert states(controller) == [False, True, True]
    assert disk_journal(controller)['completed'] == 0
    with pytest.raises(exchange.Hold):
        controller.witness()
    reopened = exchange.HostExchange(controller.policy_path, controller.approved_sha256)
    closed = reopened.close()
    assert closed == reopened.witness() == reopened.close()
    policy = loaded(controller)
    assert closed.intent_sha256 == digest
    assert closed.policy_sha256 == policy.sha256 and closed.generation == policy.generation
    assert closed.control_pin == policy.control_pin and closed.lock_pin == policy.lock_pin
    assert closed.mount_namespace == policy.mount_namespace and closed.pairs == policy.pairs
    assert states(controller) == [False] * 3


@pytest.mark.parametrize('mode', ['absent', 'substitute', 'occupied', 'symlink'])
def test_invalid_later_endpoint_stops_entire_forward_transition(fixture, mode):
    controller, _ = fixture
    controller.prepare()
    pair = loaded(controller).pairs[-1]
    if mode == 'occupied':
        pair.parked.chmod(0o700)
        (pair.parked / 'unexpected').touch()
        pair.parked.chmod(0o500)
    else:
        displaced = pair.parked.rename(pair.parked.with_name('displaced'))
        if mode == 'symlink':
            pair.parked.symlink_to(displaced)
        if mode == 'substitute':
            pair.parked.mkdir(mode=0o500)
    with pytest.raises(exchange.Hold):
        controller.close()
    assert disk_journal(controller)['completed'] == 0
    assert states(controller) == [True] * 3


def test_initialization_failure_leaves_no_hold_and_can_retry(fixture, monkeypatch):
    controller, _ = fixture
    pair = loaded(controller).pairs[-1]
    pair.parked.chmod(0o700)
    (pair.parked / 'unexpected').touch()
    pair.parked.chmod(0o500)
    with pytest.raises(exchange.Hold, match='occupied'):
        controller.prepare()
    assert not (controller.policy_path.parent / exchange.JOURNAL).exists()
    assert states(controller) == [True] * 3
    pair.parked.chmod(0o700)
    (pair.parked / 'unexpected').unlink()
    pair.parked.chmod(0o500)
    controller.prepare()
    assert disk_journal(controller)['completed'] == 0


def test_interrupted_prepare_leaves_no_untracked_swap(fixture, monkeypatch):
    controller, _ = fixture
    original_replace = exchange.os.replace

    def stop_before_replace(*args, **kwargs):
        os._exit(71)

    with monkeypatch.context() as patch:
        patch.setattr(exchange.os, 'replace', stop_before_replace)
        pid = os.fork()
        if pid == 0:
            try:
                controller.prepare()
            finally:
                os._exit(72)
        _, status = os.waitpid(pid, 0)
    assert os.WIFEXITED(status) and os.WEXITSTATUS(status) == 71
    assert exchange.os.replace is original_replace
    assert states(controller) == [True] * 3
    assert not (controller.policy_path.parent / exchange.JOURNAL).exists()
    controller.prepare()
    assert controller.close() == controller.witness()


def test_restore_is_separate_authorized_and_recoverable(fixture, monkeypatch):
    controller, _ = fixture
    controller.prepare()
    evidence = b'bound terminal proof for synthetic host policy'
    with pytest.raises(exchange.Hold, match='closure'):
        controller.restore(evidence, verify_terminal=lambda *_: True)
    closed = controller.close()

    def verified(identity, received):
        return identity == closed and received == evidence

    with pytest.raises(exchange.Hold, match='refused'):
        controller.restore(evidence, verify_terminal=lambda *_: False)
    assert controller.witness() == closed
    interrupt(monkeypatch, lambda: controller.restore(evidence, verify_terminal=verified), '_exchange')
    assert states(controller) == [True, False, False]
    assert disk_journal(controller)['phase'] == 'restoring'
    reopened = exchange.HostExchange(controller.policy_path, controller.approved_sha256)
    with pytest.raises(exchange.Hold, match='changed'):
        reopened.restore(b'foreign', verify_terminal=verified)
    with pytest.raises(exchange.Hold, match='refused'):
        reopened.restore(evidence, verify_terminal=lambda *_: False)
    assert states(controller) == [True, False, False]
    restored = reopened.restore(evidence, verify_terminal=verified)
    assert restored == reopened.witness('restored')
    assert restored.intent_sha256 == closed.intent_sha256
    assert restored.terminal_proof_sha256 == sha256(evidence).hexdigest()
    assert states(controller) == [True] * 3


def test_host_write_opt_in_fails_closed_by_default(fixture):
    controller, raw = fixture
    raw['mode'] = 'host'
    host = seal(controller.policy_path, raw)
    assert loaded(host).mode == 'host'
    for action in (host.prepare, host.close, lambda: host.restore(b'proof', verify_terminal=lambda *_: True)):
        with pytest.raises(exchange.Hold, match='host mutations are disabled'):
            action()
    assert not (host.policy_path.parent / exchange.JOURNAL).exists()
    assert states(host) == [True] * 3


def test_policy_requires_exact_digest_and_routes_and_parent(fixture):
    controller, raw = fixture
    raw['pairs'][-1]['canonical'] = '../arbitrary'
    other = seal(controller.policy_path, raw)
    with pytest.raises(exchange.Hold, match='seal mismatch'):
        controller.prepare()
    with pytest.raises(exchange.Hold, match='pathname component'):
        other.prepare()
    raw['pairs'][-1]['canonical'] = 'copy c'
    raw['pairs'][-1]['parent_pin']['inode'] += 1
    other = seal(controller.policy_path, raw)
    with pytest.raises(exchange.Hold, match='parent pins'):
        other.prepare()


def test_lock_identity_and_namespace_must_match(fixture):
    controller, raw = fixture
    controller.prepare()
    lock = controller.policy_path.parent / exchange.LOCK
    lock.rename(lock.with_name('prior-lock'))
    lock.touch(mode=0o600)
    with pytest.raises(exchange.Hold, match='control lock changed'):
        controller.close()
    raw['lock_pin'] = path_pin(lock)
    raw['mount_namespace'] = 'mnt:[999999999]'
    other = seal(controller.policy_path, raw)
    with pytest.raises(exchange.Hold, match='mount namespace changed'):
        other.close()


def test_read_only_witness_keeps_control_metadata_and_checks_closed_sentinel(fixture):
    controller, _ = fixture
    controller.prepare()
    expected = controller.close()

    def control_evidence():
        return sorted((path.name, path.stat().st_ino, path.stat().st_mtime_ns, path.read_bytes())
                      for path in expected.control.iterdir())

    before = control_evidence()
    assert controller.witness() == expected
    assert control_evidence() == before
    canonical = expected.pairs[0].canonical
    canonical.chmod(0o700)
    (canonical / 'unexpected').touch()
    canonical.chmod(0o500)
    with pytest.raises(exchange.Hold, match='occupied'):
        controller.witness()


def test_progress_replace_crash_resyncs_control_before_next_swap(fixture, monkeypatch):
    controller, _ = fixture
    controller.prepare()
    original = exchange.os.replace

    def stop(source, destination, **kwargs):
        original(source, destination, **kwargs)
        if destination == exchange.JOURNAL:
            os._exit(81)

    with monkeypatch.context() as patch:
        patch.setattr(exchange.os, 'replace', stop)
        pid = os.fork()
        if pid == 0:
            try:
                controller.close()
            finally:
                os._exit(82)
        _, status = os.waitpid(pid, 0)
    assert os.WIFEXITED(status) and os.WEXITSTATUS(status) == 81
    assert disk_journal(controller)['completed'] == 1
    assert states(controller) == [False, True, True]

    calls = []
    control_inode = loaded(controller).control_pin.inode
    sync, swap = exchange.os.fsync, exchange._exchange

    def observe_sync(fd):
        if os.fstat(fd).st_ino == control_inode:
            calls.append('control sync')
        sync(fd)

    def observe_swap(*args):
        assert calls[0] == 'control sync'
        calls.append('swap')
        swap(*args)

    monkeypatch.setattr(exchange.os, 'fsync', observe_sync)
    monkeypatch.setattr(exchange, '_exchange', observe_swap)
    assert controller.close() == controller.witness()
    assert calls.count('swap') == 2


def test_out_of_order_partial_placement_is_never_repaired_by_guessing(fixture):
    controller, _ = fixture
    controller.prepare()
    pair = loaded(controller).pairs[1]
    with exchange._directory(pair.parent) as parent:
        exchange._exchange(parent, pair.canonical.name, pair.parked.name)
    with pytest.raises(exchange.Hold, match='single next swap'):
        controller.close()
    assert states(controller) == [True, False, True]
    assert disk_journal(controller)['completed'] == 0


def test_parent_substitution_requires_policy_rejection(fixture):
    controller, _ = fixture
    controller.prepare()
    pair = loaded(controller).pairs[1]
    original = pair.parent.rename(pair.parent.with_name('prior directory'))
    pair.parent.mkdir(mode=0o700)
    (original / pair.canonical.name).rename(pair.canonical)
    sentinel = original / pair.parked.name
    sentinel.chmod(0o700)
    sentinel.rename(pair.parked)
    pair.parked.chmod(0o500)
    with pytest.raises(exchange.Hold, match='approved parent changed'):
        controller.close()
    assert states(controller) == [True] * 3
