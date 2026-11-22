"""Apply the exact one-file Crown recovery under the standing observer."""

import argparse
from contextlib import ExitStack, closing
from dataclasses import replace
from hashlib import sha256
import json
from shutil import copytree
from tempfile import TemporaryDirectory
from pathlib import Path
import sqlite3
import subprocess
import sys


PROJECT = Path('/home/chris/job-search-helper_old')
STAGE = Path('/tmp/jsh-crown-repair-evidence/native-capsule')
ACTIVATION = STAGE.parent / 'activation'
APPROVAL_SHA256 = 'a94f17031f457b4f6e459b3162b518db37b2deb51456ae1c2c72281cb9dc65db'
ENROLLMENT_SHA256 = '083d569f79d8b3c4a95a5a5fb565e62682f43414aaa7032d244fb49efb80d43c'
ATTESTED_CROWN_RELEASE = 'REL-ede347339c8faf1806583810'


def system(*args):
    return subprocess.check_output(['/usr/bin/systemctl', '--user', *args], text=True, timeout=25).strip()


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('action', choices=('check', 'apply', 'recover'))
    args = parser.parse_args()
    if not sys.flags.isolated or not sys.flags.dont_write_bytecode or sys.pycache_prefix != '/dev/null':
        raise ValueError('Use isolated production Python without bytecode.')
    tools = PROJECT / 'dev/wrapper-coder/tools'
    recovery = Path(__file__).resolve().parent
    sys.path[:0] = [str(STAGE), str(ACTIVATION), str(recovery), str(PROJECT / 'src'), str(tools)]
    from native_crown_entry import CUSTODY, CUSTODY_PIN, PRIOR_ENTRY, PRIOR_ENTRY_PIN, load_measured
    from swap_crown_enrollment import CROWN_ENV, WRAPPER
    from read_crown_enrollment import build_enrollment
    from amend_crown_assignment import TASK, NEW_BASELINE, amend, check_paused_owner, save, settle_interruption
    from coordinator_baseline import binding, files as baseline_files
    from job_search_helper.inbox import InventoryInbox
    from job_search_helper.sqlite_repository import SQLiteRepository

    files = load_measured('crown_live_activation_custody', CUSTODY, CUSTODY_PIN)
    read = files.file_bytes
    approval = json.loads(read(STAGE / 'APPLY_APPROVAL.json', APPROVAL_SHA256, private=True))
    source_pins = approval['tool_sha256']
    read(STAGE / 'native_crown_entry.py', source_pins['native_crown_entry.py'])
    read(ACTIVATION / 'swap_crown_enrollment.py', 'ec9b3e08e84a9f80dd88e8cd33b63033787cb1c1e8d15fb36448c8188c9d6f5e')
    package = approval['package_sha256']
    load_measured('release_admission_bootstrap', PROJECT / 'release_admission_bootstrap.py',
                  '689f644523b1fa1f691eeaf863e84acfc8a39fd8974bb05721d0246b144330f9', reader=read)
    from job_search_helper.cli import load_environment

    load_environment(PROJECT / '.env')
    load_measured('native_source_advance', STAGE / 'native_source_advance.py', source_pins['native_source_advance.py'], reader=read)
    source = load_measured('crown_LIVE_source_owner', STAGE / 'maintenance_source_owner.py',
                          source_pins['maintenance_source_owner.py'], reader=read)
    owner = source.MaintenanceSourceOwner(PROJECT, STAGE, package)
    if owner.status()['phase'] != 'STAGED' or owner.release_id != ATTESTED_CROWN_RELEASE:
        raise ValueError('The independent Crown source release is no longer current.')

    prior = load_measured('crown_live_native_loader', PRIOR_ENTRY, PRIOR_ENTRY_PIN, reader=read)
    prior.NATIVE_STAGE = STAGE
    prior.INSTALLED_PINS = {
        **prior.INSTALLED_PINS,
        'host_server.py': owner.spec['package_files']['dev/wrapper-coder/tools/host_server.py']['staged']['sha256'],
        'coordinator_store.py': '028bb731ddf9cfce1ec9e228dd1ab8d6c4511aae94117e2e1243778f6b57d1f4',
    }
    loaded = prior.verify_tool_origins()
    native, modules = prior.load_native_window(loaded, approval['native']['window_sha256'])
    window = native.create_window(
        release_id=owner.release_id, manifest_sha256=owner.manifest_pin, manifest=owner.manifest,
        approval_check=lambda: approval['source_approval'], native_modules=modules,
        wrapper_scope_sha256=approval['native']['wrapper_scope_sha256'],
        window_root=Path(approval['native']['window_root']), source_owner=owner, resume_complete=True,
    )
    enrollment = json.loads(read(ACTIVATION / 'LIVE_ENROLLMENT.json', ENROLLMENT_SHA256, private=True))
    old_value = json.dumps(enrollment, sort_keys=True, separators=(',', ':'))
    former = {CROWN_ENV: old_value}
    app = PROJECT / '.state'
    task_root = PROJECT / 'dev/wrapper-coder/tasks'
    database = task_root / 'tasks.sqlite3'
    corrected = recovery / ('crown-' + NEW_BASELINE)
    installed_baseline = task_root.parent / 'pilot-bases' / corrected.name
    old_native = Path('/tmp/jsh-embraer-owned-pilot.xXaXrqW0/successor-enrollment/native')
    environment = load_measured('crown_legacy_env_parser', old_native / 'successor_environment.py',
                               'f86bb7e48d0c36f2fe5edb47baba1544b91ed7ec9df4be46a65018b188f610fc', reader=read)
    environment.SCOPED = environment.SCOPED | {CROWN_ENV}
    scope = load_measured('crown_legacy_process_parser', old_native / 'native_runtime.py',
                          '05377be0ff3124e2fb641b378443251f63ec415d9de3dddc11e7bb12913f7521', reader=read)

    def read_manager():
        return environment.manager_scope(system)

    def read_process():
        import time
        deadline = time.monotonic() + 12
        while True:
            try:
                policy = window.policy
                proc = Path('/proc')
                state = window.h.unit_status(policy.systemctl, WRAPPER)
                if state['ActiveState'] != 'active' or state['UnitFileState'] != 'enabled':
                    raise ValueError('The verified wrapper is not active.')
                pid = int(state['MainPID'])
                first = window.h.verify_wrapper_process(policy, pid, proc)
                listener = window.h.verify_listener(policy, pid, proc)
                for helper in (1249, 4467):
                    if window.h.verify_ancillary_process(
                        native.OBSERVER, proc / str(helper), policy.launch_uid, native.MAINTENANCE_ID,
                        window.h.checkout_routes(policy), listener=(policy.wrapper_port, listener),
                    ) is not True:
                        raise ValueError('The permanent observer did not verify the required helper.')
                values = scope.process_scope((proc / str(pid) / 'environ').read_bytes(), environment.SCOPED)
                if window.h.verify_wrapper_process(policy, pid, proc) != first:
                    raise ValueError('Wrapper process changed during environment readback.')
                return pid, values
            except (OSError, ValueError):
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.3)

    def check_quiescent():
        with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as db:
            db.execute('BEGIN')
            check_paused_owner(db)
        if (app / 'next-scan.json').exists():
            raise ValueError('Another application scan is queued.')

    window._approval()
    window._modules()
    controller = window.c.Controller(native.BUNDLE)
    with ExitStack() as leases:
        for path in (controller.controller_gate, *controller.locks, controller.install_gate):
            leases.enter_context(window.c.lock(path))
        if {str(path): window.c.inode(path) for path in controller.locks} != controller.binding['locks']:
            raise ValueError('Original application locks changed.')
        window._lineage(check_restored=False)
        record = json.loads(native.read_private(window.root / 'native-window.json'))
        quiet = json.loads(native.read_private(window.root / 'operator-quiet-window.json'))
        if (record['phase'] != 'RESTORED' or quiet['phase'] != 'RESTORED'
                or record['binding'] != window._binding() or record['terminal'] != window._terminal()):
            raise ValueError('The actual Crown release window is not restored.')
        exchange = window.x.HostExchange(window.root / 'exchange-private/policy.json', record['exchange']['policy_sha256'])
        if exchange.witness('restored').terminal_proof_sha256 != record['restoration_sha256']:
            raise ValueError('Alternate checkout placements changed.')
        for unit in (native.SYNC, native.TIMER):
            if (system('show', unit, '-p', 'ActiveState', '--value') != 'inactive'
                    or system('show', unit, '-p', 'UnitFileState', '--value') != 'disabled'):
                raise ValueError('Scheduled sync must remain disabled.')
        native.MAINTENANCE_ID = 's6-crown-protocol-recovery-20261122-19'
        native.OBSERVER = Path('/run/jsh-maintenance-observer/observer.sock')
        window.policy = replace(window.policy, maintenance_id=native.MAINTENANCE_ID,
                                ancillary_process_evidence=native.OBSERVER)
        destination = InventoryInbox.destination_id(app / 'inventories.sqlite3')
        with closing(SQLiteRepository(app / 'jobs.sqlite3', destination, readonly=True)) as repository:
            revised = build_enrollment(repository, app, PROJECT, corrected, NEW_BASELINE, enrollment['request_id'])
        if revised != {**enrollment, 'baseline_sha256': NEW_BASELINE}:
            raise ValueError('The application-owned Crown enrollment changed outside the baseline pin.')
        current = {CROWN_ENV: json.dumps(revised, sort_keys=True, separators=(',', ':'))}
        intent = recovery / 'LIVE_MAINTENANCE_INTENT.json'
        if args.action == 'recover':
            approved = json.loads(intent.read_text())
            if approved['task_id'] != TASK or approved['release_id'] != owner.release_id:
                raise ValueError('The interrupted Crown attempt does not match the source release.')
            unit = window.h.unit_status(window.policy.systemctl, WRAPPER)
            if unit['ActiveState'] == 'active':
                pid, process = read_process()
                if process == current and read_manager() == current:
                    side = settle_interruption(task_root / TASK, database)
                    if side != 'CORRECTED':
                        raise ValueError('Active corrected enrollment lacks the matching task.')
                    if (installed_baseline.resolve(strict=True) != installed_baseline or not installed_baseline.is_dir()
                            or binding(baseline_files(installed_baseline))['digest'] != NEW_BASELINE):
                        raise ValueError('The corrected installed Crown baseline is unavailable.')
                    print(json.dumps({'state': 'CROWN_PROTOCOL_RECOVERY_READY_TO_RESUME', 'wrapper_pid': pid}))
                    return
                if process == former and read_manager() == former:
                    check_quiescent()
                    if settle_interruption(task_root / TASK, database) != 'ORIGINAL':
                        raise ValueError('Active original enrollment lacks the matching workspace.')
                    print(json.dumps({'state': 'CROWN_PROTOCOL_RECOVERY_ROLLED_BACK', 'wrapper_pid': pid}))
                    return
                raise ValueError('Observe the active wrapper before any further restart.')
            window._observer()
            if unit['ActiveState'] != 'inactive' or unit['MainPID'] != '0':
                raise ValueError('The wrapper has not reached a verified stopped boundary.')
            with loaded['amphenol_operator_one_shot']._coordinator_lease(task_root):
                side = settle_interruption(task_root / TASK, database, allow_restore=True)
                if side == 'CORRECTED':
                    if (installed_baseline.resolve(strict=True) != installed_baseline or not installed_baseline.is_dir()
                            or binding(baseline_files(installed_baseline))['digest'] != NEW_BASELINE):
                        raise ValueError('The corrected installed Crown baseline is unavailable.')
                chosen = current if side == 'CORRECTED' else former
                if read_manager() not in (former, current):
                    raise ValueError('An unexpected manager scope prevents recovery.')
                system('set-environment', CROWN_ENV + '=' + chosen[CROWN_ENV])
            system('start', WRAPPER)
            pid, process = read_process()
            if process != chosen or read_manager() != chosen:
                raise ValueError('Wrapper recovery scope has not settled.')
            status = 'CROWN_PROTOCOL_RECOVERY_READY_TO_RESUME' if side == 'CORRECTED' else 'CROWN_PROTOCOL_RECOVERY_ROLLED_BACK'
            print(json.dumps({'state': status, 'wrapper_pid': pid}))
            return

        old_pid, process = read_process()
        if read_manager() != former or process != former:
            raise ValueError('The old Crown enrollment changed before correction.')
        check_quiescent()
        if args.action == 'check':
            print(json.dumps({'state': 'CROWN_PROTOCOL_RECOVERY_READY',
                              'task_id': TASK, 'wrapper_pid': old_pid,
                              'corrected_baseline': NEW_BASELINE}, sort_keys=True))
            return
        save(intent, {'task_id': TASK, 'old_pid': old_pid, 'release_id': owner.release_id,
                      'prior_baseline': enrollment['baseline_sha256'], 'corrected_baseline': NEW_BASELINE})
        system('stop', WRAPPER)
        unit = window.h.unit_status(window.policy.systemctl, WRAPPER)
        if unit['ActiveState'] != 'inactive' or unit['MainPID'] != '0':
            raise ValueError('Wrapper did not stop at its normal safe boundary.')
        with loaded['amphenol_operator_one_shot']._coordinator_lease(task_root):
            check_quiescent()
            try:
                if installed_baseline.exists() or installed_baseline.is_symlink():
                    raise ValueError('The corrected private baseline unexpectedly exists.')
                with TemporaryDirectory(dir=installed_baseline.parent, prefix='.crown-protocol-') as scratch:
                    prepared = Path(scratch) / 'baseline'
                    copytree(corrected, prepared)
                    if binding(baseline_files(prepared))['digest'] != NEW_BASELINE:
                        raise ValueError('The copied private Crown baseline changed.')
                    prepared.rename(installed_baseline)
                system('set-environment', CROWN_ENV + '=' + current[CROWN_ENV])
                if read_manager() != current:
                    raise ValueError('The corrected Crown environment could not be read back.')
                result = amend(task_root / TASK, database, installed_baseline)
            except BaseException:
                side = settle_interruption(task_root / TASK, database, allow_restore=True)
                if side == 'CORRECTED':
                    if (installed_baseline.resolve(strict=True) != installed_baseline or not installed_baseline.is_dir()
                            or binding(baseline_files(installed_baseline))['digest'] != NEW_BASELINE):
                        raise ValueError('The corrected installed Crown baseline is unavailable.')
                chosen = current if side == 'CORRECTED' else former
                system('set-environment', CROWN_ENV + '=' + chosen[CROWN_ENV])
                # The explicit recover action starts only the verified side.
                raise
        system('start', WRAPPER)
        new_pid, active = read_process()
        if new_pid == old_pid or active != current or read_manager() != current:
            raise ValueError('The active wrapper has not loaded the corrected Crown baseline.')
        result = {**result, 'state': 'CROWN_PROTOCOL_RECOVERY_READY_TO_RESUME', 'wrapper_pid': new_pid}
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
