"""Only private files/fake service callbacks; no native entry execution."""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

import native_expired_post_forward as entry

HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def test_reuses_exact_expiry_without_changing_normal_gate(tmp_path):
    expiry = load('expiry_postforward_test', entry.EXPIRY_PATH)
    assert hashlib.sha256(entry.EXPIRY_PATH.read_bytes()).hexdigest() == entry.EXPIRY_PIN
    prior = load('expiry_prior_fixture', HERE.parent/'expired-withdrawal/test_expired_withdrawal.py')
    prior.test_exact_expired_withdrawal_and_lost_restart_response_replay(tmp_path)
    prior.test_deadline_actual_state_and_empty_slot_controls_hold()
    # The normal existing gate remains valid, and expiry does not translate status.
    import embraer_pilot_arming as armer
    assert armer._can_disarm_task({'status': 'AWAITING_LIVE_VALIDATION'})
    assert armer._can_disarm_task({'status': 'PAUSED_BLOCKED', 'stop_requested': True})
    assert not armer._can_disarm_task(prior.task())
    assert expiry.require_expired_stopped(prior.task(), now=expiry.ORIGINAL_ACTIVATED_AT+3600)
    source = Path(entry.__file__).read_text()
    assert "parser.add_argument('--allow-original-expired', action='store_true')" in source
    assert 'elif args.allow_original_expired:' in source
    assert 'result = expiry.withdraw_expired(' in source
    assert 'result = armer.reconcile_pilot(' in source
    # Inspection and all receipt/custody functions are inherited byte-for-byte.
    old = ast.parse((HERE.parent/'disarm/native_embraer_disarm.py').read_text())
    new = ast.parse(source)
    def fn(tree, name):
        return ast.dump(next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name), include_attributes=False)
    for name in ('controls', 'process_scope', 'verified_forward_receipt'):
        assert fn(old, name) == fn(new, name)


def test_postforward_physical_receipt_plus_expired_original_proof(tmp_path, monkeypatch):
    forward = load('forward_post_expiry_fixture', HERE.parent/'forward/coordinator_forward.py')
    expiry = load('expiry_postforward_test_two', entry.EXPIRY_PATH)
    monkeypatch.setattr(entry, 'PROJECT', tmp_path)
    target = tmp_path/forward.RELATIVE
    target.parent.mkdir(parents=True)
    target.write_bytes((HERE.parent/'coordinator.py').read_bytes())
    target.chmod(0o644)
    def reference(path):
        s = path.stat()
        return [s.st_dev, s.st_ino, stat.S_IMODE(s.st_mode), s.st_uid, s.st_gid,
                hashlib.sha256(path.read_bytes()).hexdigest()]
    window = SimpleNamespace(c=SimpleNamespace(ref=reference), wrapper_scope_sha256='a'*64)
    actual = [*reference(target), target.stat().st_mtime_ns]
    before = actual.copy(); before[5] = forward.BEFORE
    snapshot = {'enrollment': {'request_id': expiry.REQUEST}, 'outcome_id': expiry.OUTCOME}
    receipt = {'schema': forward.SCHEMA, 'status': 'INSTALLED', 'current_reference': actual,
        'restart': {'coordinator_reference': actual}, 'transition': {
            'schema': forward.SCHEMA, 'release_id': forward.RELEASE, 'task_id': forward.TASK,
            'path': forward.RELATIVE, 'before_sha256': forward.BEFORE, 'after_sha256': forward.AFTER,
            'before_reference': before, 'snapshot': snapshot, 'snapshot_sha256': forward.digest(snapshot),
            'predecessor': {'application_journal_sha256': entry.ACTIVE_JOURNAL_PIN,
                'application_receipt_sha256': entry.ACTIVE_RECEIPT_PIN,
                'restored_records': entry.RESTORED,
                'original_wrapper_scope_sha256': window.wrapper_scope_sha256}}}
    raw = forward.canonical(receipt)
    pin = hashlib.sha256(raw).hexdigest()
    def read(path, expected, private):
        assert private
        if expected != pin:
            raise ValueError('fixture independent receipt mismatch')
        return raw
    assert entry.verified_forward_receipt(read, window, forward, pin) == receipt
    with pytest.raises(ValueError):
        entry.verified_forward_receipt(read, window, forward, '0'*64)
    target.write_bytes(b'changed coordinator')
    with pytest.raises(ValueError):
        entry.verified_forward_receipt(read, window, forward, pin)
    assert entry.CURRENT_FORWARD_RECEIPT == '9d3798a65d403743a84e4fee3783f86df1e80d9c2f9e5e8e16849aa8ffbcb48b'
