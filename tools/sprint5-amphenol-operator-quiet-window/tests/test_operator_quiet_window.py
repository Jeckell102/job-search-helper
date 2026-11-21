from contextlib import contextmanager
import json

import pytest

from amphenol_operator_quiet_window import OperatorQuietWindow
from amphenol_retry_completion import RetryReleaseApproval
from controller import Systemd, UNITS
from job_search_helper.integration_release import JOURNAL_SCHEMA


class UnitFixture:
    """Apply the real Systemd condition logic to two disposable unit files."""

    def __init__(self, directory):
        self.active = {UNITS[0]: True, UNITS[1]: False}
        self.directory = directory
        self.commands = []
        self.fail = None
        directory.mkdir()
        for name in UNITS:
            (directory / name).write_text(f'# Fixture unit for {name}\n')

    def command(self, *args, **kwargs):
        self.commands.append(args)
        verb, *names = args
        if verb == 'show':
            return '\n\n'.join(self.status(name) for name in UNITS)
        if verb in {'stop', 'start'}:
            for name in names:
                self.active[name] = verb == 'start'
        if self.fail == verb:
            self.fail = None
            raise RuntimeError(f'Fixture interruption during {verb}')
        return ''

    def status(self, name):
        drop_in = self.directory / f'{name}.d'
        fields = {
            'Id': name, 'LoadState': 'loaded',
            'ActiveState': 'active' if self.active[name] else 'inactive',
            'SubState': 'running' if self.active[name] else 'dead',
            'UnitFileState': 'enabled' if name == UNITS[0] else 'disabled',
            'MainPID': '101' if self.active[name] else '0', 'ControlPID': '0',
            'ControlGroup': '/amphenol-fixture-user-service' if self.active[name] else '',
            'FragmentPath': str(self.directory / name),
            'DropInPaths': ' '.join(str(path) for path in sorted(drop_in.glob('*.conf'))),
            'NeedDaemonReload': 'no',
        }
        return '\n'.join(f'{key}={value}' for key, value in fields.items())


def build_window(root, monkeypatch, release_id):
    capsule = root / 'private'
    capsule.mkdir(mode=0o700)
    application = root / 'app-state'
    application.mkdir()
    monkeypatch.setenv('STATE_DB_FILE', str(application / 'state.db'))
    monkeypatch.setenv('JOB_DB_FILE', str(application / 'jobs.sqlite3'))
    monkeypatch.setenv('JOB_STORAGE_BACKEND', 'sqlite')
    fixture = UnitFixture(root / 'units')
    units = Systemd('/usr/bin/systemctl', fixture.directory, capsule / 'operator-hold-active')
    monkeypatch.setattr(units, 'command', fixture.command)
    monkeypatch.setattr(Systemd, 'check_cgroup', staticmethod(lambda _: None))
    proofs = []

    @contextmanager
    def admission():
        proofs.append('enter')
        try:
            yield
        finally:
            proofs.append('exit')

    def verify_exclusion():
        assert proofs[-1] == 'enter' and not any(fixture.active.values())
        proofs.append('closed')
        return True

    def verify_restored(prior):
        assert fixture.active == {name: prior[name]['active'] == 'active' for name in UNITS}
        assert not units.sentinel.exists()
        proofs.append('restored')
        return True

    window = OperatorQuietWindow(
        units, capsule / 'operator-quiet-window.json', release_id, application,
        admission=admission, verify_exclusion=verify_exclusion, verify_restored=verify_restored,
    )
    return window, fixture, proofs


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    return build_window(tmp_path, monkeypatch, 'REL-' + 'a' * 24)


def test_bound_span_restores_exact_services_after_body_failure(prepared):
    window, fixture, proofs = prepared
    with pytest.raises(RuntimeError, match='fixture body'):
        with window.hold():
            assert json.loads(window.journal.read_text())['phase'] == 'HELD'
            assert window.units.sentinel.is_file()
            assert not any(fixture.active.values())
            raise RuntimeError('fixture body')
    assert proofs == ['enter', 'closed', 'restored', 'exit']
    assert fixture.active == {UNITS[0]: True, UNITS[1]: False}
    assert json.loads(window.journal.read_text())['phase'] == 'RESTORED'
    assert [args for args in fixture.commands if args[0] == 'start'] == [('start', UNITS[0])]


def test_partial_stop_callback_is_restored_without_running_worker(prepared):
    window, fixture, proofs = prepared
    fixture.fail = 'stop'
    with pytest.raises(RuntimeError, match='Fixture interruption during stop'):
        with window.hold():
            pytest.fail('The worker must not start after incomplete stop')
    assert proofs == ['enter', 'restored', 'exit']
    assert fixture.active == {UNITS[0]: True, UNITS[1]: False}
    assert json.loads(window.journal.read_text())['phase'] == 'RESTORED'


def test_unsettled_source_keeps_fence_then_restores_once_after_recovery(prepared):
    window, fixture, proofs = prepared
    active = window.application_state / 'integration-release-journal.json'
    with pytest.raises(RuntimeError, match='interrupted integration release'):
        with window.hold():
            active.write_text(json.dumps({'schema': JOURNAL_SCHEMA, 'state': 'INSTALLING'}))
    assert not any(fixture.active.values()) and window.units.sentinel.is_file()
    assert json.loads(window.journal.read_text())['phase'] == 'HELD'
    with pytest.raises(RuntimeError, match='interrupted integration release'):
        window.restore()
    active.write_text(json.dumps({'schema': JOURNAL_SCHEMA, 'state': 'COMPLETE'}))
    first = window.restore()
    assert first == window.restore() == {
        'state': 'OPERATOR_MAINTENANCE_RESTORED', 'release_id': window.release_id,
    }
    assert fixture.active == {UNITS[0]: True, UNITS[1]: False}
    assert [args for args in fixture.commands if args[0] == 'start'] == [('start', UNITS[0])]


def test_default_and_missing_qualification_do_not_admit_or_write(prepared, tmp_path):
    window, fixture, proofs = prepared
    approval = RetryReleaseApproval(window.release_id, str(tmp_path / 'absent-owner'), 1, 1, 'b' * 64)
    selection = dict(approval=approval, original_outcome='OUT-' + 'a' * 24,
                     request_sha256='d' * 64, historical_task_id='WRAP-1111111111')
    assert window.run(**selection) == {'state': 'HELD_OPERATOR_EXECUTION_NOT_REQUESTED'}
    with pytest.raises(FileNotFoundError):
        window.run(**selection, execute=True)
    assert not window.journal.exists() and not fixture.commands and not proofs


def test_failed_restart_proof_reestablishes_fence_before_releasing_admission(prepared):
    window, fixture, proofs = prepared
    verified = window.verify_restored
    window.verify_restored = lambda prior: False
    with pytest.raises(ValueError, match='restored operator host'):
        with window.hold():
            pass
    assert window.units.sentinel.is_file()
    assert not any(fixture.active.values()) and proofs[-1] == 'exit'
    assert json.loads(window.journal.read_text())['phase'] == 'RESTORING'
    window.verify_restored = verified
    assert window.restore()['state'] == 'OPERATOR_MAINTENANCE_RESTORED'


@pytest.mark.parametrize('name,value', [('JOB_STORAGE_BACKEND', 'sheets'), ('JOB_DB_FILE', '/tmp/foreign.db')])
def test_mismatched_app_configuration_holds_before_service_changes(prepared, monkeypatch, name, value):
    window, fixture, proofs = prepared
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match='fresh operator maintenance window'):
        with window.hold():
            pytest.fail('A mismatched state configuration must not launch the worker')
    assert not window.journal.exists() and not fixture.commands and not proofs
