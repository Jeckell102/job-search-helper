import hashlib
import importlib.util
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

SOURCE = Path(__file__).parents[1] / 'deploy_two_tool_forward.py'
spec = importlib.util.spec_from_file_location('two_tool_forward', SOURCE)
forward = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = forward
spec.loader.exec_module(forward)


class Guard:
    @contextmanager
    def terminal(self):
        yield {'source': 'INSTALLED', 'predecessor_receipt_sha256': forward.PREDECESSOR_RECEIPT_SHA256,
               'historical_predecessor_receipt_sha256': forward.HISTORICAL_PREDECESSOR_RECEIPT_SHA256,
               'source_manifest_sha256': 'a' * 64, 'controller_journal_sha256': 'b' * 64}


def digest(data): return hashlib.sha256(data).hexdigest()


def make_stage(tmp_path, monkeypatch):
    project = tmp_path / 'project'; tools = project / 'dev/wrapper-coder/tools'
    repairs = project / 'dev/wrapper-coder/repairs'; tools.mkdir(parents=True); repairs.mkdir()
    (repairs / 'deployment.lock').touch()
    before = {forward.STORE_RELATIVE: b'old-store', forward.HOST_RELATIVE: b'old-host'}
    candidate = {forward.STORE_RELATIVE: b'new-store', forward.HOST_RELATIVE: b'new-host'}
    for rel, data in before.items():
        p = project / rel; p.write_bytes(data); p.chmod(0o600 if rel == forward.HOST_RELATIVE else 0o644)
    monkeypatch.setattr(forward, 'TWO_TOOL_BEFORE', {path: digest(data) for path, data in before.items()})
    monkeypatch.setattr(forward, 'TWO_TOOL_AFTER', {path: digest(data) for path, data in candidate.items()})
    receipts = tmp_path / 'receipts'; receipts.mkdir(mode=0o700)
    scope = {}
    for rel in forward.REMAINING_SCOPE:
        p = project / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b'x'); scope[rel] = digest(b'x')
    calls = []
    idle = {'task_sha256': forward.TERMINAL_TASK_SHA256, 'receipt_sha256': forward.TERMINAL_RECEIPT_SHA256,
            'open_inference': 0, 'service': forward.SERVICE_NAME,
            'controls': {'queue': False, 'campaign': False, 'autopilot': False, 'unqualified_release': False},
            'loaded_hashes': forward.TWO_TOOL_BEFORE}
    return project, before, candidate, receipts, scope, calls, idle


def invoke(project, candidate, receipts, scope, calls, idle, start):
    return forward.apply_two_tool_forward(
        project=project, successor_guard=Guard(), candidates=candidate,
        before_sha256=forward.TWO_TOOL_BEFORE, after_sha256=forward.TWO_TOOL_AFTER,
        predecessor_receipt_sha256=forward.PREDECESSOR_RECEIPT_SHA256, remaining_scope=scope,
        idle_probe=lambda: idle, exchange_probe=lambda terminal: {'restored_exchange': True,
            'predecessor_receipt_sha256': forward.PREDECESSOR_RECEIPT_SHA256,
            'historical_predecessor_receipt_sha256': forward.HISTORICAL_PREDECESSOR_RECEIPT_SHA256},
        stop_service=lambda unit: calls.append(('stop', unit)), start_service=start,
        stopped_probe=lambda: True, restart_probe=lambda: {**idle, 'loaded_hashes': forward.TWO_TOOL_AFTER}, receipt_directory=receipts)


def test_success_writes_store_then_host_and_preserves_two_before_images(tmp_path, monkeypatch):
    project, before, candidate, receipts, scope, calls, idle = make_stage(tmp_path, monkeypatch)
    result = invoke(project, candidate, receipts, scope, calls, idle, lambda unit: calls.append(('start', unit)))
    assert result['status'] == 'TWO_TOOL_FORWARD_INSTALLED'
    assert (project / forward.STORE_RELATIVE).read_bytes() == candidate[forward.STORE_RELATIVE]
    assert (project / forward.HOST_RELATIVE).read_bytes() == candidate[forward.HOST_RELATIVE]
    assert (receipts / 'coordinator_store.py.before').read_bytes() == before[forward.STORE_RELATIVE]
    assert (receipts / 'host_server.py.before').read_bytes() == before[forward.HOST_RELATIVE]
    assert calls == [('stop', forward.SERVICE_NAME), ('start', forward.SERVICE_NAME)]


def test_second_step_failure_restores_host_then_store_and_restarts_old(tmp_path, monkeypatch):
    project, before, candidate, receipts, scope, calls, idle = make_stage(tmp_path, monkeypatch)
    def fail_start(unit):
        calls.append(('start', unit)); raise RuntimeError('fake restart failure after both replacements')
    with pytest.raises(RuntimeError, match='fake restart'):
        invoke(project, candidate, receipts, scope, calls, idle, fail_start)
    assert (project / forward.STORE_RELATIVE).read_bytes() == before[forward.STORE_RELATIVE]
    assert (project / forward.HOST_RELATIVE).read_bytes() == before[forward.HOST_RELATIVE]
    assert calls == [('stop', forward.SERVICE_NAME), ('start', forward.SERVICE_NAME),
                     ('stop', forward.SERVICE_NAME), ('start', forward.SERVICE_NAME)]


def test_stop_that_already_stopped_then_raises_restarts_old_without_source_replacement(tmp_path, monkeypatch):
    project, before, candidate, receipts, scope, calls, idle = make_stage(tmp_path, monkeypatch)
    def stopped_then_raised(unit):
        calls.append(('stop', unit)); raise RuntimeError('stop callback lost response after stop')
    with pytest.raises(RuntimeError, match='lost response'):
        forward.apply_two_tool_forward(
            project=project, successor_guard=Guard(), candidates=candidate,
            before_sha256=forward.TWO_TOOL_BEFORE, after_sha256=forward.TWO_TOOL_AFTER,
            predecessor_receipt_sha256=forward.PREDECESSOR_RECEIPT_SHA256, remaining_scope=scope,
            idle_probe=lambda: idle, exchange_probe=lambda terminal: {'restored_exchange': True,
                'predecessor_receipt_sha256': forward.PREDECESSOR_RECEIPT_SHA256,
                'historical_predecessor_receipt_sha256': forward.HISTORICAL_PREDECESSOR_RECEIPT_SHA256},
            stop_service=stopped_then_raised, start_service=lambda unit: calls.append(('start', unit)),
            stopped_probe=lambda: True, restart_probe=lambda: {**idle, 'loaded_hashes': forward.TWO_TOOL_BEFORE},
            receipt_directory=receipts)
    assert (project / forward.STORE_RELATIVE).read_bytes() == before[forward.STORE_RELATIVE]
    assert (project / forward.HOST_RELATIVE).read_bytes() == before[forward.HOST_RELATIVE]
    assert calls == [('stop', forward.SERVICE_NAME), ('start', forward.SERVICE_NAME)]
