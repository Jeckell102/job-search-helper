"""Apply or withdraw one already verified operator enrollment on MuleLab."""

import json
import shlex


WRAPPER = 'wrapper-development-host.service'
ENROLLMENT = 'WRAPPER_AMPHENOL_OPERATOR_RECIPE_ENROLLMENT'
SCOPED = frozenset((ENROLLMENT, 'WRAPPER_AMPHENOL_RECIPE_ENROLLMENT', 'WRAPPER_AMPHENOL_RETRY_APPROVAL',
                    'WRAPPER_AMPHENOL_ACTIVATE_APPROVED_RELEASE', 'WRAPPER_SELECTED_OUTCOME_ID',
                    'WRAPPER_SELECTED_COMPANY_EVENT_ID'))
ENROLLMENT_FIELDS = frozenset(('request_id', 'request_sha256', 'source_revision', 'predecessor_outcome_id',
                              'predecessor_repair_key', 'predecessor_task_id',
                              'predecessor_task_state_sha256', 'failure_fingerprint'))


def manager_scope(system):
    result = {}
    for line in system('show-environment').splitlines():
        key = line.lstrip('\'"').partition('=')[0]
        if key not in SCOPED:
            continue
        parts = shlex.split(line)
        if len(parts) != 1 or parts[0].partition('=')[0] != key or key in result:
            raise ValueError('Unrecognized scoped service-manager environment')
        result[key] = parts[0].partition('=')[2]
    return result


def reconcile_enrollment(enrollment, *, enabled, system, inspect_wrapper, check_quiescent):
    """Converge only our exact environment and restart the existing wrapper.

    The caller holds the existing host exclusion and verifies the durable
    input, installed receipt, and quiescent control state. An interrupted
    restart remains recognizable through the exact manager/process values.
    """
    if (not isinstance(enrollment, dict) or set(enrollment) != ENROLLMENT_FIELDS
            or any(not isinstance(value, str) or not value for value in enrollment.values())
            or type(enabled) is not bool):
        raise ValueError('Expected the verified fresh operator enrollment')
    value = json.dumps(enrollment, sort_keys=True, separators=(',', ':'))
    owned = {ENROLLMENT: value}
    target = owned if enabled else {}

    check_quiescent()
    manager = manager_scope(system)
    pid, process = inspect_wrapper()
    if type(pid) is not int or pid <= 0:
        raise ValueError('Expected the known active wrapper')
    if manager not in ({}, owned) or process not in ({}, owned):
        raise ValueError('Another operator, Company event, or release owns the wrapper scope')
    if enabled and not manager and process:
        raise ValueError('Finish withdrawing the previous process enrollment before arming')

    if manager != target:
        if enabled:
            system('set-environment', ENROLLMENT + '=' + value)
        else:
            system('unset-environment', ENROLLMENT)
        if manager_scope(system) != target:
            raise ValueError('Scoped service-manager change did not settle')
    if process != target:
        system('restart', WRAPPER)
        new_pid, observed = inspect_wrapper()
        if type(new_pid) is not int or new_pid <= 0 or new_pid == pid or observed != target:
            raise ValueError('Wrapper restart did not load the selected scope')
        pid = new_pid
    if manager_scope(system) != target:
        raise ValueError('Scoped service-manager environment changed during restart')
    return {'state': 'FRESH_OPERATOR_ENROLLED' if enabled else 'FRESH_OPERATOR_WITHDRAWN', 'wrapper_pid': pid}
