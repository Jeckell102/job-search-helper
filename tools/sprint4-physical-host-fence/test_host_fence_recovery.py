"""Regressions at the direct wrapper's release refusal boundaries."""
import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import controller
import installer


@pytest.fixture
def release(tmp_path):
    worker = object.__new__(controller.Controller)
    worker.bundle = tmp_path / 'bundle'
    worker.bundle.mkdir(mode=0o700)
    worker.project = tmp_path / 'checkout'
    worker.canonical = worker.project / 'src/job_search_helper'
    worker.canonical.mkdir(parents=True)
    worker.wrapper_tools = worker.project / installer.WRAPPER_PARENT
    worker.wrapper_tools.mkdir(parents=True)
    worker.marker = worker.project / 'integration-release-journal.json'
    worker.marker_data = b'expected runtime hold'
    controller.ensure_file(worker.marker, worker.marker_data)
    worker.units = SimpleNamespace(verify=Mock(), restore=Mock(), close=Mock(), check_status=Mock(),
                                   sentinel=worker.bundle / 'service-hold')
    worker.prove_wrapper_parent = Mock()
    worker.verify_tree = Mock(return_value=worker.canonical)
    worker.verify_receipt = Mock()
    worker.canonical_probe = Mock()
    worker.package = Mock(return_value=(worker.canonical, False))
    worker.hook = Mock()
    payload = b'fixture script\n'
    endpoint = (0o640, installer.digest(payload))
    name = installer.WRAPPER_HOST
    worker.manifest = SimpleNamespace(after={name: endpoint}, owners={name: [os.geteuid(), os.getegid()]})
    with installer.directory(worker.bundle) as state:
        installer.seal_host_image(state, 'after', payload, endpoint)

    def persist(record, phase):
        record['phase'] = phase

    worker.save = Mock(side_effect=persist)
    record = {'phase': 'HOST_REOPEN', 'target': 'INSTALLED', 'prior': {}, 'receipt': {}}
    return worker, record, worker.project / name, payload


def test_post_open_receipt_refusal_closes_direct_entry(release):
    worker, record, host, payload = release

    def refuse_after_open(_record, _receipt, *, host_absent=False):
        if not host_absent:
            assert host.read_bytes() == payload
            raise ValueError('receipt failed after host opened')

    worker.verify_receipt.side_effect = refuse_after_open
    with pytest.raises(ValueError, match='receipt failed after host opened'):
        worker.release(record, worker.manifest.after)
    assert not host.exists()
    assert record['phase'] == 'RELEASE_REFUSED'
    assert worker.marker.read_bytes() == worker.marker_data
    worker.units.close.assert_called_once_with(record['prior'])
    worker.units.restore.assert_not_called()


def test_refusal_during_restore_closes_host_even_if_journal_write_fails(release):
    worker, record, host, payload = release
    host.write_bytes(payload)
    host.chmod(0o640)
    record['phase'] = 'RELEASING'

    def site_check(checkpoint, **_):
        if checkpoint == 'restored':
            raise ValueError('restored host disagreed')

    worker.hook.side_effect = site_check
    worker.save.side_effect = OSError('journal could not record refusal')
    with pytest.raises(ValueError, match='journal could not record refusal') as problem:
        worker.release(record, worker.manifest.after)
    assert 'restored host disagreed' in str(problem.value)
    assert record['phase'] == 'RELEASING'
    assert not host.exists()
    assert worker.marker.read_bytes() == worker.marker_data
    worker.units.close.assert_called_once_with(record['prior'])


def test_direct_entry_already_closed_when_service_hold_is_interrupted(release):
    worker, record, host, payload = release
    host.write_bytes(payload)
    host.chmod(0o640)
    record['phase'] = 'RELEASE_REFUSED'

    def interrupted_unit_close(_prior):
        assert not host.exists()
        assert worker.marker.read_bytes() == worker.marker_data
        raise KeyboardInterrupt

    worker.units.close.side_effect = interrupted_unit_close
    with pytest.raises(KeyboardInterrupt):
        worker.release(record, worker.manifest.after)
    assert record['phase'] == 'RELEASE_REFUSED'
    assert not host.exists()
