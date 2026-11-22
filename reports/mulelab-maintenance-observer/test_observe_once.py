import socket
from types import SimpleNamespace

import pytest

import observe_once as observer


def fixture(monkeypatch, tmp_path):
    root = tmp_path / 'proc'
    (root / 'sys/kernel/random').mkdir(parents=True)
    (root / 'sys/kernel/random/boot_id').write_text('fixture-boot')
    process = root / '10'
    process.mkdir()
    (process / 'cgroup').write_text('0::/user.slice/user-1000.slice/session-2.scope\n')
    monkeypatch.setattr(observer, 'PROC', root)
    witness = observer.load_witness()
    identity = {'pid': 10, 'uid': observer.LAUNCH_UID, 'comm': 'ssh-agent'}
    calls = []

    def capture(uid, routes, pid, *, listener=None):
        calls.append((uid, routes, pid, listener))
        return identity

    monkeypatch.setattr(witness, 'process_identity', lambda _: identity)
    monkeypatch.setattr(witness, 'capture', capture)
    request = {
        'schema': witness.SCHEMA,
        'scope': witness.scope(root, observer.LAUNCH_UID, 's6-crown-owned-source-20261122-18', observer.ROUTES),
        'pid': 10, 'challenge': '0' * 32,
        'listener': {'port': observer.LISTENER_PORT, 'inodes': ['123']},
    }
    return SimpleNamespace(root=root, witness=witness, identity=identity, calls=calls, request=request)


def test_real_unix_socket_delivers_one_approved_witness(monkeypatch, tmp_path):
    data = fixture(monkeypatch, tmp_path)
    client, observer_socket = socket.socketpair()
    with client as caller, observer_socket as service:
        caller.sendall(data.witness.encoded(data.request))
        caller.shutdown(socket.SHUT_WR)
        observer.answer(service, data.witness)
        service.shutdown(socket.SHUT_WR)
        assert caller.recv(4096) == data.witness.encoded({'request': data.request, 'process': data.identity})
    assert data.calls == [(observer.LAUNCH_UID, observer.ROUTES, 10, (18789, {'123'}))]


@pytest.mark.parametrize('change', ['route', 'role', 'port', 'request_window', 'cgroup', 'uid', 'process_drift'])
def test_unapproved_request_never_produces_a_witness(monkeypatch, tmp_path, change):
    data = fixture(monkeypatch, tmp_path)
    request = data.request
    if change == 'route':
        request['scope']['routes'].append('/private')
    elif change == 'role':
        data.identity['comm'] = 'bash'
    elif change == 'port':
        request['listener']['port'] = 22
    elif change == 'request_window':
        request['scope']['maintenance_id'] = 's6-crown/../../'
    elif change == 'cgroup':
        (data.root / '10/cgroup').write_text('0::/system.slice/another.service\n')
    elif change == 'uid':
        data.identity['uid'] = 1001
    elif change == 'process_drift':
        monkeypatch.setattr(data.witness, 'capture', lambda *args, **kw: {**data.identity, 'pid': 11})
    with pytest.raises(ValueError):
        observer.observe(request, data.witness)


def test_a_different_peer_cannot_access_the_service(monkeypatch, tmp_path):
    data = fixture(monkeypatch, tmp_path)
    monkeypatch.setattr(data.witness, 'peer_uid', lambda _: 1001)
    client, observer_socket = socket.socketpair()
    with client as caller, observer_socket as service:
        caller.sendall(data.witness.encoded(data.request))
        caller.shutdown(socket.SHUT_WR)
        observer.answer(service, data.witness)
        service.shutdown(socket.SHUT_WR)
        assert caller.recv(1) == b''
    assert data.calls == []
