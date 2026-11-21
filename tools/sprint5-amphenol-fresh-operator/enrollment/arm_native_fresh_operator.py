"""Verify or change the exact fresh Amphenol pilot environment on MuleLab."""

import argparse
from contextlib import ExitStack
from dataclasses import replace
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
import sys
import time


HERE = Path(__file__).resolve().parent
PINS = {
    'run_native_two_tool_forward.py': 'd2c902d3daaafa6bf631e388b3400897444731999d2d5de6ca1ac1c1055547f5',
    'deploy_two_tool_forward.py': 'cf9f82f6b85f441ab2e0fdd9bfee1448aa6c1e444ade09a3e66e2748ebb75597',
    'two_tool_route_drain.py': 'aac2a747a6389f3e98e7e38dad9ce562e9f80c6ed1a039d0d2b5e6ac3d539b25',
    'fresh_operator_enrollment_input.py': 'd8cbe0da4e3439e2b28a92f9eecb26b42f278ad591660d0623798743f888d7f6',
    'fresh_pilot_environment.py': '8255eb149845ea66fcc1a850693e703ae64bd34996dd267e9ad7bb36c1d45ae4',
}
PREDECESSOR = HERE / 'S5_AMPHENOL_FRESH_SUCCESSOR_NATIVE_READBACK_20261121.json'
PREDECESSOR_PIN = '96cf0cbc51de8cd6f5972614ec81e711a8aaf6a9f87a58b6b76e661d5c0d5434'
INSTALL_RECEIPT = 'two-tool-forward-receipt.json'


def pinned_file(path, digest):
    if not path.is_file() or path.resolve(strict=True) != path:
        raise ValueError(f'Expected the physical {path.name}')
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != digest:
        raise ValueError(f'Unexpected contents in {path.name}')
    return raw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('arm', 'withdraw'))
    parser.add_argument('--request-id', required=True)
    parser.add_argument('--installed-receipt-sha256', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if not sys.flags.isolated or not sys.flags.dont_write_bytecode:
        raise ValueError('Run the maintenance entry with Python -I -B')
    if (not re.fullmatch(r'operator-amphenol-[a-zA-Z0-9._:-]{3,90}', args.request_id)
            or args.request_id == 'operator-amphenol-20261121-03'
            or not re.fullmatch(r'[0-9a-f]{64}', args.installed_receipt_sha256)):
        raise ValueError('Expected the exact new operator request and deployed update receipt')
    for name, digest in PINS.items():
        pinned_file(HERE / name, digest)
        cached = HERE / '__pycache__' / f'{Path(name).stem}.{sys.implementation.cache_tag}.pyc'
        if os.path.lexists(cached):
            raise ValueError('Unexpected cached maintenance helper')
    sys.path.insert(0, str(HERE))
    import run_native_two_tool_forward as native
    import deploy_two_tool_forward as updater
    from fresh_operator_enrollment_input import read_fresh_operator_enrollment
    from fresh_pilot_environment import ENROLLMENT, ENROLLMENT_FIELDS, SCOPED, manager_scope, reconcile_enrollment

    for name, digest in native.HISTORICAL_PINS.items():
        pinned_file(native.BUNDLE / name, digest)
        if name.endswith('.py') and os.path.lexists(
                native.BUNDLE / '__pycache__' / f'{Path(name).stem}.{sys.implementation.cache_tag}.pyc'):
            raise ValueError('Unexpected cached historical maintenance helper')
    sys.path[1:1] = [str(native.BUNDLE), str(native.BUNDLE / 'host-check')]
    import controller as historical
    from host_checkpoint import process_start, unit_status, verify_listener, verify_wrapper_process
    from site_policy import load_policy
    from two_tool_route_drain import BRIDGE_ARGS, BRIDGE_CGROUP, verify_two_tool_route_drain

    policy, *_ = load_policy(str(native.BUNDLE / 'host-check'))
    policy = replace(policy, maintenance_id=native.MAINTENANCE_ID, ancillary_process_evidence=native.OBSERVER)
    receipt_path = native.DESTINATION / INSTALL_RECEIPT
    receipt = json.loads(pinned_file(receipt_path, args.installed_receipt_sha256))
    receipt_attrs = receipt_path.stat()
    if stat.S_IMODE(receipt_attrs.st_mode) != 0o600 or receipt_attrs.st_uid != os.getuid() or receipt_attrs.st_nlink != 1:
        raise ValueError('Expected the private installed receipt')
    modes = {updater.HOST_RELATIVE: 0o600, updater.STORE_RELATIVE: 0o644}
    expected_paths = {path: {'before_sha256': updater.TWO_TOOL_BEFORE[path], 'after_sha256': after,
                            'mode': f'{modes[path]:04o}'} for path, after in updater.TWO_TOOL_AFTER.items()}
    if (receipt.get('status') != 'TWO_TOOL_FORWARD_INSTALLED' or receipt.get('paths') != expected_paths
            or receipt.get('predecessor', {}).get('receipt_sha256') != updater.PREDECESSOR_RECEIPT_SHA256):
        raise ValueError('Current installed receipt is outside the exact two-tool scope')

    bridge_unit = unit_status(policy.systemctl, native.BRIDGE)
    bridge_pid = int(bridge_unit['MainPID'])
    if (bridge_pid <= 0 or bridge_unit['ActiveState'] != 'active'
            or bridge_unit['FragmentPath'] != str(native.BRIDGE_UNIT) or bridge_unit['ControlGroup'] != BRIDGE_CGROUP):
        raise ValueError('Expected the existing Jetson bridge to be running')
    bridge = (bridge_pid, process_start(native.PROC / str(bridge_pid)))
    clock_ticks = os.sysconf('SC_CLK_TCK')
    boot_time = next(int(line.split()[1]) for line in (native.PROC / 'stat').read_text().splitlines()
                     if line.startswith('btime '))
    bridge_started_ns = (boot_time * clock_ticks + int(bridge[1])) * 1_000_000_000 // clock_ticks

    def check_quiescent():
        native.checked(native.PROJECT / 'src/job_search_helper/acquiretm.py', native.ADAPTER)
        if (native.verify_source_selection(modes) != updater.TWO_TOOL_AFTER
                or native.retained_task() != (updater.TERMINAL_TASK_SHA256, updater.TERMINAL_RECEIPT_SHA256, 0)
                or native.unit_field(native.SYNC, 'ActiveState') != 'inactive'
                or native.unit_field(native.SYNC, 'UnitFileState') != 'disabled'
                or native.unit_field(native.TIMER, 'ActiveState') != 'inactive'
                or native.unit_field(native.TIMER, 'UnitFileState') != 'disabled'):
            raise ValueError('Current source, sync, or repair controls differ from the admitted quiet state')

    def inspect_wrapper():
        for path, digest in ((native.BRIDGE_UNIT, native.BRIDGE_UNIT_SHA), (Path(BRIDGE_ARGS[2]), native.BRIDGE_SOURCE_SHA)):
            before = path.stat()
            pinned_file(path, digest)
            after = path.stat()
            if (not os.path.samestat(before, after) or before.st_ctime_ns != after.st_ctime_ns
                    or max(after.st_mtime_ns, after.st_ctime_ns) >= bridge_started_ns):
                raise ValueError('The measured Jetson bridge files must predate the running service')
        if unit_status(policy.systemctl, native.BRIDGE) != bridge_unit:
            raise ValueError('The Jetson bridge service changed during enrollment')
        wrapper = unit_status(policy.systemctl, native.WRAPPER)
        pid = int(wrapper['MainPID'])
        if (wrapper['ActiveState'] != 'active' or wrapper['UnitFileState'] != 'enabled' or pid <= 0
                or Path(wrapper['FragmentPath']) != policy.wrapper_unit_file):
            raise ValueError('Expected the known active wrapper service')
        pinned_file(policy.wrapper_unit_file, native.UNIT_SHA)
        start = verify_wrapper_process(policy, pid, native.PROC)
        verify_listener(policy, pid, native.PROC)
        verify_two_tool_route_drain(policy, pid, native.PROC, bridge)
        scoped = {}
        for item in (native.PROC / str(pid) / 'environ').read_bytes().split(b'\0'):
            key, _, value = item.partition(b'=')
            name = key.decode()
            if name in native.PYTHON_OVERRIDES or name in scoped:
                raise ValueError('Unexpected wrapper startup environment')
            if name in SCOPED:
                scoped[name] = value.decode()
        if verify_wrapper_process(policy, pid, native.PROC) != start:
            raise ValueError('Wrapper changed during inspection')
        return pid, scoped

    def inspect_ready_wrapper():
        deadline = time.monotonic() + 12
        while True:
            try:
                return inspect_wrapper()
            except (OSError, ValueError):
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.3)

    root = native.PROJECT / '.state'
    owner = native.DESTINATION.with_name(args.request_id + '.enrollment.json')
    with ExitStack() as stack:
        stack.enter_context(updater._deployment_lock(native.PROJECT))
        stack.enter_context(historical.lock(root / 'scraper.lock'))
        check_quiescent()
        pid, scoped = inspect_wrapper()
        existing = None
        if os.path.lexists(owner):
            attrs = owner.lstat()
            if (owner.resolve(strict=True) != owner or not stat.S_ISREG(attrs.st_mode)
                    or stat.S_IMODE(attrs.st_mode) != 0o600 or attrs.st_uid != os.getuid() or attrs.st_nlink != 1):
                raise ValueError('Existing operator scope has different custody')
            existing = owner.read_bytes()
        if args.action == 'arm':
            chosen = read_fresh_operator_enrollment(state_root=root, request_id=args.request_id,
                native_readback_path=PREDECESSOR, expected_predecessor_sha256=PREDECESSOR_PIN)
        else:
            if existing is None:
                raise ValueError('Expected the private owned enrollment record')
            saved = json.loads(existing)
            chosen = saved['enrollment']
            if set(chosen) != ENROLLMENT_FIELDS or chosen['request_id'] != args.request_id:
                raise ValueError('Stored enrollment belongs to another request')
        evidence = {'schema': 'fresh-amphenol-runtime-enrollment-v1',
                    'installed_receipt_sha256': args.installed_receipt_sha256, 'enrollment': chosen}
        encoded = updater._canonical_json(evidence)
        if existing is not None and existing != encoded:
            raise ValueError('Existing operator scope has different custody')
        expected = {ENROLLMENT: json.dumps(chosen, sort_keys=True, separators=(',', ':'))}
        if scoped not in ({}, expected) or manager_scope(native.system) not in ({}, expected):
            raise ValueError('A foreign wrapper enrollment owns the scope')
        if not args.apply:
            print(json.dumps({'state': 'FRESH_OPERATOR_ENVIRONMENT_PREFLIGHT', 'request_id': args.request_id,
                              'wrapper_pid': pid, 'scope_present': bool(scoped)}, sort_keys=True))
            return
        if args.action == 'arm' and existing is None:
            updater._write_new_private(owner, encoded)
        result = reconcile_enrollment(chosen, enabled=args.action == 'arm', system=native.system,
            inspect_wrapper=inspect_ready_wrapper, check_quiescent=check_quiescent)
        print(json.dumps({**result, 'request_id': args.request_id, 'owner_record': str(owner)}, sort_keys=True))


if __name__ == '__main__':
    main()
