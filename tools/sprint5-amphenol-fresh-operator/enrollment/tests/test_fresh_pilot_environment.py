import shlex

import pytest

from fresh_pilot_environment import ENROLLMENT, ENROLLMENT_FIELDS, WRAPPER, reconcile_enrollment


class WrapperFixture:
    def __init__(self):
        self.manager = {'OTHER': 'leave this alone'}
        self.process = {}
        self.pid = 10
        self.calls = []
        self.failed_restart = False

    def system(self, operation, *values):
        if operation == 'show-environment':
            return '\n'.join(f'{key}={shlex.quote(value)}' for key, value in self.manager.items())
        self.calls.append((operation, *values))
        if operation == 'set-environment':
            key, value = values[0].split('=', 1)
            self.manager[key] = value
        elif operation == 'unset-environment':
            del self.manager[values[0]]
        elif operation == 'restart':
            assert values == (WRAPPER,)
            if self.failed_restart:
                self.failed_restart = False
                raise OSError('Lost restart response')
            self.process = {key: value for key, value in self.manager.items() if key != 'OTHER'}
            self.pid += 1
        else:
            pytest.fail(f'Unexpected service command: {operation}')

    def reconcile(self, enabled):
        values = {key: 'fixture-' + key for key in ENROLLMENT_FIELDS}
        return reconcile_enrollment(values, enabled=enabled, system=self.system,
            inspect_wrapper=lambda: (self.pid, self.process), check_quiescent=lambda: None)


def test_arm_and_withdraw_only_exact_scope():
    fixture = WrapperFixture()
    assert fixture.reconcile(True)['wrapper_pid'] == 11
    assert list(fixture.process) == [ENROLLMENT]
    assert fixture.reconcile(True)['wrapper_pid'] == 11
    assert fixture.reconcile(False)['wrapper_pid'] == 12
    assert fixture.reconcile(False)['wrapper_pid'] == 12
    assert fixture.manager == {'OTHER': 'leave this alone'} and fixture.process == {}
    assert [call[0] for call in fixture.calls] == ['set-environment', 'restart', 'unset-environment', 'restart']


def test_other_recipe_scope_is_never_overwritten():
    fixture = WrapperFixture()
    fixture.manager[ENROLLMENT] = 'previous scope'
    with pytest.raises(ValueError, match='Another operator'):
        fixture.reconcile(True)
    with pytest.raises(ValueError, match='Another operator'):
        fixture.reconcile(False)
    assert fixture.calls == [] and fixture.manager[ENROLLMENT] == 'previous scope'


def test_interrupted_transitions_resume_only_same_scope():
    fixture = WrapperFixture()
    fixture.failed_restart = True
    with pytest.raises(OSError, match='Lost restart response'):
        fixture.reconcile(True)
    assert ENROLLMENT in fixture.manager and fixture.process == {}
    assert fixture.reconcile(True)['wrapper_pid'] == 11
    fixture.failed_restart = True
    with pytest.raises(OSError, match='Lost restart response'):
        fixture.reconcile(False)
    assert ENROLLMENT not in fixture.manager and ENROLLMENT in fixture.process
    with pytest.raises(ValueError, match='Finish withdrawing'):
        fixture.reconcile(True)
    assert fixture.reconcile(False)['wrapper_pid'] == 12
    assert fixture.manager == {'OTHER': 'leave this alone'} and fixture.process == {}
