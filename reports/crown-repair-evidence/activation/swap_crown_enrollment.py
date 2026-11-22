"""Swap one independently verified terminal Embraer enrollment to Crown."""

import json


OLD_ENV = 'WRAPPER_EMBRAER_OPERATOR_PILOT_ENROLLMENT'
CROWN_ENV = 'WRAPPER_CROWN_OPERATOR_PILOT_ENROLLMENT'
WRAPPER = 'wrapper-development-host.service'


def arm_crown(crown, old_value, *, system, read_manager, read_process, check_quiescent):
    """Use one restart, or recognize the already restarted exact process.

    The caller owns the guarded window and supplies positively identified
    service and manager observations. An interrupted mixed state needs
    explicit readback. This function never starts a second restart there.
    """
    from crown_operator_pilot import CrownOperatorEnrollment

    value = json.dumps(crown, separators=(',', ':'), sort_keys=True)
    CrownOperatorEnrollment.from_process_environment({CROWN_ENV: value})
    if not isinstance(old_value, str) or not old_value:
        raise ValueError('The exact terminal Embraer environment is required.')
    old = {OLD_ENV: old_value}
    target = {CROWN_ENV: value}
    manager = read_manager()
    pid, process = read_process()
    if type(pid) is not int or pid <= 0:
        raise ValueError('The wrapper has no verified live process.')
    if manager == process == target:
        return {'state': 'CROWN_PILOT_ARMED', 'wrapper_pid': pid}
    if manager != old or process != old:
        raise ValueError('Wrapper enrollment is mixed or changed; inspect the same service before proceeding.')

    check_quiescent()
    if read_manager() != old or read_process() != (pid, old):
        raise ValueError('The terminal wrapper owner moved during activation.')
    system('unset-environment', OLD_ENV)
    if read_manager() != {} or read_process() != (pid, old):
        raise ValueError('Embraer withdrawal did not settle at the exact boundary.')
    system('set-environment', CROWN_ENV + '=' + value)
    if read_manager() != target or read_process() != (pid, old):
        raise ValueError('Crown environment did not settle before restart.')
    try:
        system('restart', WRAPPER)
    except (OSError, RuntimeError):
        # A restart can succeed even if its control reply failed.
        new_pid, new_process = read_process()
        if type(new_pid) is int and new_pid > 0 and new_pid != pid and new_process == target and read_manager() == target:
            return {'state': 'CROWN_PILOT_ARMED', 'wrapper_pid': new_pid}
        raise
    new_pid, new_process = read_process()
    if (type(new_pid) is not int or new_pid <= 0 or new_pid == pid
            or new_process != target or read_manager() != target):
        raise ValueError('Crown process activation is unconfirmed; observe the same restart.')
    return {'state': 'CROWN_PILOT_ARMED', 'wrapper_pid': new_pid}
