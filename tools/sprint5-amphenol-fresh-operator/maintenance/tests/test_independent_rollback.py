import json
import pytest

from test_deploy_two_tool_forward import Guard, forward, make_stage


def test_rollback_reconciles_a_stop_that_lost_its_response(tmp_path, monkeypatch):
    project, before, candidate, receipts, scope, calls, idle = make_stage(tmp_path, monkeypatch)
    running = True
    writes = []
    write_atomic = forward._write_atomic

    def capture_write(path, data, mode):
        assert not running
        writes.append((path.relative_to(project).as_posix(), data))
        write_atomic(path, data, mode)

    def stop(unit):
        nonlocal running
        assert unit == forward.SERVICE_NAME
        calls.append('stop')
        running = False
        if calls.count('stop') == 2:
            raise RuntimeError('rollback stop callback lost response after stopping')

    def start(unit):
        nonlocal running
        assert unit == forward.SERVICE_NAME
        calls.append('start')
        running = True

    def restart_probe():
        assert running
        if calls.count('start') == 1:
            return {**idle, 'loaded_hashes': {**forward.TWO_TOOL_AFTER, forward.HOST_RELATIVE: 'e' * 64}}
        return idle

    monkeypatch.setattr(forward, '_write_atomic', capture_write)
    with pytest.raises((RuntimeError, forward.HostForwardError)) as caught:
        forward.apply_two_tool_forward(
            project=project, successor_guard=Guard(), candidates=candidate,
            before_sha256=forward.TWO_TOOL_BEFORE, after_sha256=forward.TWO_TOOL_AFTER,
            predecessor_receipt_sha256=forward.PREDECESSOR_RECEIPT_SHA256, remaining_scope=scope,
            idle_probe=lambda: idle, exchange_probe=lambda _: {
                'restored_exchange': True,
                'predecessor_receipt_sha256': forward.PREDECESSOR_RECEIPT_SHA256,
                'historical_predecessor_receipt_sha256': forward.HISTORICAL_PREDECESSOR_RECEIPT_SHA256,
            }, stop_service=stop, start_service=start, stopped_probe=lambda: not running,
            restart_probe=restart_probe, receipt_directory=receipts,
        )
    picked = {path: (project / path).read_bytes() for path in before}
    last_receipt = receipts / 'two-tool-forward-receipt.json'
    print(f'error={caught.value}; calls={calls}; running={running}; files={picked}; receipt={last_receipt.exists()}')
    assert picked == before
    assert writes == [(path, candidate[path]) for path in forward.FORWARD_PATHS] + [
        (path, before[path]) for path in reversed(forward.FORWARD_PATHS)
    ]
    assert running and calls == ['stop', 'start', 'stop', 'start']
    receipt = json.loads(last_receipt.read_bytes())
    assert receipt['status'] == 'TWO_TOOL_FORWARD_ROLLED_BACK'
    assert receipt['predecessor']['receipt_sha256'] == forward.PREDECESSOR_RECEIPT_SHA256
    assert receipt['historical_predecessor_receipt_sha256'] == forward.HISTORICAL_PREDECESSOR_RECEIPT_SHA256
