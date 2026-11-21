from contextlib import contextmanager
import json


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


def build_window(root, monkeypatch, release_id, application):
    capsule = root / 'private'
    capsule.mkdir(mode=0o700)
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


