from contextlib import contextmanager, nullcontext
from hashlib import sha256
import json
from types import SimpleNamespace

import pytest

import current_tool_guard as guard


def test_guard_keeps_old_receipt_and_leases_but_accepts_exact_current_host(tmp_path, monkeypatch):
    controller_gate, app_lock, installer_gate = (tmp_path / name for name in ('controller', 'app', 'installer'))
    locks = set()

    @contextmanager
    def take(path):
        locks.add(path)
        try:
            yield
        finally:
            locks.remove(path)

    installer = SimpleNamespace(JOURNAL='transaction.json',
                                encode=lambda value: json.dumps(value, sort_keys=True).encode(),
                                digest=lambda data: sha256(data).hexdigest(),
                                source_tree=lambda *args: nullcontext({'src': 'source'}),
                                source_directories=lambda values: {name: {'identity': value}
                                                                   for name, value in values.items()},
                                directory=lambda name, _: nullcontext(name))
    existing = SimpleNamespace(lock=take, inode=lambda path: str(path), physical=lambda path: path,
                               read=lambda path: (path.read_bytes(), path.stat()), installer=installer,
                               gate=SimpleNamespace(PARKED='parked'),
                               present=lambda path: path.exists())
    record = {'phase': 'RELEASED', 'target': 'INSTALLED', 'prior': {}, 'guard': 'parked', 'receipt': {
        'phase': 'INSTALLED', 'source_directories': {'src': {'identity': 'source'}, 'guard': {'identity': 'parked'}},
    }}
    previous = {guard.HOST_RELATIVE: (0o600, 'old'), 'unrelated.py': (0o644, 'untouched')}
    historical = {'maintenance_id': 'fixture', 'project': str(tmp_path), 'source': 'INSTALLED',
                  'source_manifest_sha256': 'fixture-manifest',
                  'controller_journal_sha256': installer.digest(installer.encode(record)),
                  'installer_receipt_sha256': installer.digest(installer.encode(record['receipt']))}
    readback = []

    def compare(state, observed):
        assert state == record
        assert locks == {controller_gate, app_lock, installer_gate}
        readback.append(observed)
        return tmp_path / 'canonical'

    old = SimpleNamespace(controller_gate=controller_gate, locks=[app_lock], install_gate=installer_gate,
                          binding={'locks': {str(app_lock): str(app_lock)}}, hold_id='fixture', project=tmp_path,
                          manifest=SimpleNamespace(after=previous, sha256='fixture-manifest', owners={}),
                          load=lambda canonical: record if canonical else None, verify_tree=compare,
                          canonical=tmp_path / 'canonical', marker=tmp_path / 'marker', state=tmp_path,
                          units=SimpleNamespace(
                              sentinel=tmp_path / 'sentinel', check_status=lambda *args, **kwargs: None))
    receipt = tmp_path / 'receipt.json'
    receipt.write_bytes(installer.encode({'controller_terminal': historical, 'after_sha256': 'current'}))
    receipt.chmod(0o600)
    transaction = tmp_path / installer.JOURNAL
    transaction.write_bytes(installer.encode({**record['receipt'], 'owners': old.manifest.owners}))
    pin = sha256(receipt.read_bytes()).hexdigest()
    monkeypatch.setattr(guard, 'FORWARD_RECEIPT_SHA256', pin)
    with guard.CurrentToolGuard(old, existing, receipt, lambda: True).terminal() as terminal:
        assert terminal == {**historical, 'predecessor_receipt_sha256': pin,
                            'historical_predecessor_receipt_sha256': historical['installer_receipt_sha256']}
        assert locks == {controller_gate, app_lock, installer_gate}
    assert readback == [{**previous, guard.HOST_RELATIVE: (0o600, 'current')}]
    assert old.manifest.after[guard.HOST_RELATIVE] == (0o600, 'old')
    assert locks == set()

    with pytest.raises(ValueError, match='Exclusive wrapper host'):
        with guard.CurrentToolGuard(old, existing, receipt, lambda: False).terminal():
            pytest.fail('Competing host scope was admitted')
    assert locks == set()

    original_transaction = transaction.read_bytes()
    transaction.write_bytes(b'drift')
    with pytest.raises(ValueError, match='Historical installer transaction'):
        with guard.CurrentToolGuard(old, existing, receipt, lambda: True).terminal():
            pytest.fail('Changed installation transaction was admitted')
    assert locks == set()
    transaction.write_bytes(original_transaction)

    with monkeypatch.context() as changed:
        changed.setattr(existing.gate, 'PARKED', 'unapproved')
        with pytest.raises(ValueError, match='parked guard identity'):
            with guard.CurrentToolGuard(old, existing, receipt, lambda: True).terminal():
                pytest.fail('Changed park identity was admitted')
    assert locks == set()

    receipt.write_bytes(b'drift')
    with pytest.raises(ValueError, match='successor receipt changed'):
        with guard.CurrentToolGuard(old, existing, receipt, lambda: True).terminal():
            pytest.fail('Changed receipt was admitted')
    assert locks == set()
