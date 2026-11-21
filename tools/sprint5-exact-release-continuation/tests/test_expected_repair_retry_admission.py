import json
from pathlib import Path

import pytest

from job_search_helper.cli import writer_lock
from job_search_helper.scan_request import requested_scan
from test_repair_retry_admission_replay import retry


def admit(bridge, binding, engine, state):
    with writer_lock(bridge.database.parent / 'scraper.lock'):
        return requested_scan(engine, state, bridge.database, expected_repair_retry=binding)


@pytest.mark.parametrize('queue', ['absent', 'foreign_full', 'changed_scope'])
def test_expected_retry_never_admits_missing_or_different_request(retry, queue):
    bridge, binding, engine, state = retry
    if queue == 'foreign_full':
        bridge.request_path.write_text(json.dumps({
            'request_id': 'foreign-full-scan', 'mode': 'fresh-full-scan', 'start_last': [],
        }))
    if queue == 'changed_scope':
        assert bridge.deliver(binding)['state'] == 'REQUEST_WRITTEN'
        request = json.loads(bridge.request_path.read_text())
        request['start_last'] = [binding['company_id']]
        bridge.request_path.write_text(json.dumps(request))
    original = bridge.request_path.read_bytes() if bridge.request_path.is_file() else None

    with pytest.raises(ValueError, match='exact released retry'):
        admit(bridge, binding, engine, state)
    assert state.cycles() == [] and engine.repo.read('Scan Cycles') == []
    assert not bridge.request_path.with_name('last-scan-request.json').exists()
    if original is None:
        assert not bridge.request_path.exists()
    else:
        assert bridge.request_path.read_bytes() == original


def test_expected_retry_uses_normal_admission_for_the_exact_company(retry):
    bridge, binding, engine, state = retry
    assert bridge.deliver(binding)['state'] == 'REQUEST_WRITTEN'
    cycle_id = admit(bridge, binding, engine, state)
    [cycle] = state.cycles()
    assert cycle['id'] == cycle_id
    assert cycle['repair_retry'] == binding
    assert set(cycle['companies']) == {binding['company_id']}
    assert bridge.deliver(binding)['state'] == 'REQUEST_ALREADY_ADMITTED'
    with pytest.raises(ValueError, match='exact released retry'):
        admit(bridge, binding, engine, state)
    assert state.cycles() == [cycle]


def test_expected_retry_revalidates_the_saved_scope_before_recovery(retry, monkeypatch):
    bridge, binding, engine, state = retry
    assert bridge.deliver(binding)['state'] == 'REQUEST_WRITTEN'
    request = bridge.request_path.read_bytes()
    replace = Path.replace

    def interrupt(path, target):
        if path == bridge.request_path:
            raise OSError('cut before request rename')
        return replace(path, target)

    with monkeypatch.context() as cut:
        cut.setattr(Path, 'replace', interrupt)
        with pytest.raises(OSError, match='before request rename'):
            admit(bridge, binding, engine, state)
    [saved] = state.cycles()
    changed = {'COMP-OTHER': saved['companies'][binding['company_id']]}
    state.save_cycle({**saved, 'companies': changed})
    rows = engine.repo.read('Scan Cycles')

    with pytest.raises(ValueError, match='sole Company'):
        admit(bridge, binding, engine, state)
    assert state.cycles() == [{**saved, 'companies': changed}]
    assert engine.repo.read('Scan Cycles') == rows
    assert bridge.request_path.read_bytes() == request
    state.save_cycle(saved)
    assert admit(bridge, binding, engine, state) == saved['id']
