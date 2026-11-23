"""Replace the first ATS enrollment with the exact classifier successor."""

import json
import subprocess


ATS_ENV = 'WRAPPER_ATS_OPERATOR_PILOT_ENROLLMENT'
WRAPPER = 'wrapper-development-host.service'


def arm_ats(enrollment, old_value, expected_pid, *, system, read_manager, read_process, check_quiescent):
    """Use one restart, or recognize the already restarted exact process.

    The caller owns the guarded window and supplies positively identified
    service and manager observations. An interrupted mixed state needs
    explicit readback. This function never starts a second restart there.
    """
    from ats_operator_pilot import ATSOperatorEnrollment

    value = json.dumps(enrollment, separators=(',', ':'), sort_keys=True)
    ATSOperatorEnrollment.from_process_environment({ATS_ENV: value})
    if not isinstance(old_value, str) or not old_value:
        raise ValueError('The exact terminal ATS environment is required.')
    old = {ATS_ENV: old_value}
    target = {ATS_ENV: value}
    manager = read_manager()
    pid, process = read_process()
    if type(pid) is not int or pid <= 0:
        raise ValueError('The wrapper has no verified live process.')
    if old == target or type(expected_pid) is not int or expected_pid <= 0:
        raise ValueError('A distinct enrollment and verified predecessor PID are required.')
    if manager == process == target and pid != expected_pid:
        return {'state': 'ATS_PILOT_ARMED', 'wrapper_pid': pid}
    if pid != expected_pid or manager != old or process != old:
        raise ValueError('Wrapper enrollment is mixed or changed; inspect the same service before proceeding.')

    check_quiescent()
    if read_manager() != old or read_process() != (pid, old):
        raise ValueError('The terminal wrapper owner moved during activation.')
    system('set-environment', ATS_ENV + '=' + value)
    if read_manager() != target or read_process() != (pid, old):
        raise ValueError('ATS environment did not settle before restart.')
    try:
        system('restart', WRAPPER)
    except (OSError, RuntimeError, subprocess.SubprocessError):
        # A restart can succeed even if its control reply failed.
        new_pid, new_process = read_process()
        if type(new_pid) is int and new_pid > 0 and new_pid != pid and new_process == target and read_manager() == target:
            return {'state': 'ATS_PILOT_ARMED', 'wrapper_pid': new_pid}
        raise
    new_pid, new_process = read_process()
    if (type(new_pid) is not int or new_pid <= 0 or new_pid == pid
            or new_process != target or read_manager() != target):
        raise ValueError('ATS process activation is unconfirmed; observe the same restart.')
    return {'state': 'ATS_PILOT_ARMED', 'wrapper_pid': new_pid}
