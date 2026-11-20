"""Source guards for the joint package and wrapper transaction."""
import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import controller
import installer


def source_layout(project):
    (project / 'src/job_search_helper').mkdir(parents=True)
    tools = project / installer.WRAPPER_PARENT
    tools.mkdir(parents=True)
    return tools


def test_rejects_an_endpoint_on_a_different_mount(tmp_path, monkeypatch):
    project = tmp_path / 'checkout'
    endpoint = source_layout(project) / 'host_server.py'
    endpoint.write_bytes(b'identical expected source')
    current_mount_id = installer.mount_id

    def measure(fd):
        mounted_at = os.readlink(f'/proc/self/fd/{fd}')
        return current_mount_id(fd) + (mounted_at == str(endpoint))

    monkeypatch.setattr(installer, 'mount_id', measure)
    with installer.source_tree(project) as tree:
        with pytest.raises(ValueError, match='same-mount'):
            installer.read_file(*installer.entry(tree, 'dev/wrapper-coder/tools/host_server.py'))


def test_rejects_reopened_project_behind_ancestor_alias(tmp_path):
    ancestor = tmp_path / 'site'
    project = ancestor / 'checkout'
    source_layout(project)
    journal = tmp_path / 'journal'
    journal.mkdir()
    with installer.source_tree(project) as tree, installer.directory(journal) as state:
        transaction = object.__new__(installer.Transaction)
        transaction.args = SimpleNamespace(project=project, parked_package=False, state=journal)
        transaction.binding = {
            'source_directories': installer.source_directories(tree),
            'state_directory': installer.identity(os.fstat(state)),
        }
        moved = ancestor.with_name('moved-site')
        ancestor.rename(moved)
        ancestor.symlink_to(moved, target_is_directory=True)
        with pytest.raises(OSError):
            transaction.check_directories()


@pytest.mark.parametrize('marker_present', [True, False])
@pytest.mark.parametrize('host_refuses', [True, False])
def test_release_requires_fresh_restored_attestation(tmp_path, marker_present, host_refuses):
    worker = object.__new__(controller.Controller)
    worker.canonical = tmp_path / 'published-package'
    worker.marker = tmp_path / 'integration-release-journal.json'
    worker.marker_data = b'expected hold marker'
    if marker_present:
        worker.marker.write_bytes(worker.marker_data)
        worker.marker.chmod(0o600)
    worker.verify_tree = Mock(return_value=worker.canonical)
    worker.verify_receipt = Mock()
    worker.units = SimpleNamespace(
        restore=Mock(), close=Mock(), check_status=Mock(),
        sentinel=tmp_path / 'service-hold',
    )
    worker.save = Mock()
    checkpoints = []

    def attest(checkpoint, *, package, target):
        assert (package, target) == (worker.canonical, 'INSTALLED')
        checkpoints.append(checkpoint)
        if checkpoint == 'restored':
            worker.units.restore.assert_called_once()
            assert not worker.marker.exists()
            worker.save.assert_not_called()
            if host_refuses:
                raise ValueError('restored runtime witness differs')

    worker.hook = attest
    prior_units = {'prior': 'synthetic'}
    record = {'phase': 'RELEASING', 'target': 'INSTALLED', 'prior': prior_units, 'receipt': {}}
    if host_refuses:
        with pytest.raises(ValueError, match='runtime witness differs'):
            worker.release(record, {})
        assert worker.marker.read_bytes() == worker.marker_data
        worker.units.close.assert_called_once_with(prior_units)
        worker.save.assert_not_called()
    else:
        worker.release(record, {})
        assert not worker.marker.exists()
        worker.units.close.assert_not_called()
        worker.save.assert_called_once_with(record, 'RELEASED')
    assert checkpoints == ['restoring', 'restored']
