import pytest

from swap_crown_enrollment import CROWN_ENV, OLD_ENV, WRAPPER, arm_crown


CROWN = {
    'request_id': 'operator-crown-fixture',
    'request_sha256': '1' * 64,
    'source_revision': '2' * 64,
    'successfactors_sha256': '3' * 64,
    'ats_sha256': '4' * 64,
    'baseline_sha256': '5' * 64,
}
OLD = 'verified exact prior environment'


class ObservedService:
    def __init__(self, *, restart_completed):
        self.manager = {OLD_ENV: OLD}
        self.process = (100, dict(self.manager))
        self.commands = []
        self.restart_completed = restart_completed

    def system(self, action, argument):
        self.commands.append((action, argument.partition('=')[0]))
        if action == 'unset-environment':
            self.manager.pop(argument)
        elif action == 'set-environment':
            key, value = argument.split('=', 1)
            self.manager[key] = value
        elif action == 'restart':
            if self.restart_completed:
                self.process = (101, dict(self.manager))
            raise RuntimeError('fixture: restart control response lost')

    def arm(self):
        return arm_crown(
            CROWN, OLD, system=self.system, read_manager=lambda: dict(self.manager),
            read_process=lambda: self.process, check_quiescent=lambda: None,
        )


def test_lost_reply_recovers_from_the_exact_already_active_process():
    service = ObservedService(restart_completed=True)
    expected = {'state': 'CROWN_PILOT_ARMED', 'wrapper_pid': 101}
    assert service.arm() == expected
    assert service.arm() == expected
    assert service.commands == [
        ('unset-environment', OLD_ENV), ('set-environment', CROWN_ENV), ('restart', WRAPPER),
    ]


def test_unconfirmed_restart_holds_without_repeating_it():
    service = ObservedService(restart_completed=False)
    with pytest.raises(RuntimeError, match='response lost'):
        service.arm()
    with pytest.raises(ValueError, match='mixed or changed'):
        service.arm()
    assert service.commands.count(('restart', WRAPPER)) == 1
