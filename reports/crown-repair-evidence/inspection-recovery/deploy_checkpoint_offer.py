"""Deploy Crown’s one-shot checkpoint offer under the standing observer."""

import argparse
from contextlib import ExitStack, closing
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import subprocess
import sys


PROJECT = Path('/home/chris/job-search-helper_old')
STAGE = Path('/tmp/jsh-crown-repair-evidence/native-capsule')
ACTIVATION = STAGE.parent / 'activation'
APPROVAL_SHA256 = 'a94f17031f457b4f6e459b3162b518db37b2deb51456ae1c2c72281cb9dc65db'
ATTESTED_CROWN_RELEASE = 'REL-ede347339c8faf1806583810'


def system(*args):
    return subprocess.check_output(['/usr/bin/systemctl', '--user', *args], text=True, timeout=25).strip()


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('action', choices=('check', 'apply'))
    args = parser.parse_args()
    if not sys.flags.isolated or not sys.flags.dont_write_bytecode or sys.pycache_prefix != '/dev/null':
        raise ValueError('Use isolated production Python without bytecode.')
    tools = PROJECT / 'dev/wrapper-coder/tools'
    recovery = Path(__file__).resolve().parent
    sys.path[:0] = [str(STAGE), str(ACTIVATION), str(recovery), str(PROJECT / 'src'), str(tools)]
    from native_crown_entry import CUSTODY, CUSTODY_PIN, PRIOR_ENTRY, PRIOR_ENTRY_PIN, load_measured
    from swap_crown_enrollment import CROWN_ENV, WRAPPER
    from job_search_helper import integration_release
    from coordinator_baseline import binding, files as baseline_files

    files = load_measured('crown_live_activation_custody', CUSTODY, CUSTODY_PIN)
    read = files.file_bytes
    approval = json.loads(read(STAGE / 'APPLY_APPROVAL.json', APPROVAL_SHA256, private=True))
    source_pins = approval['tool_sha256']
    read(STAGE / 'native_crown_entry.py', source_pins['native_crown_entry.py'])
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
    task_id = 'WRAP-640c600390'
    task_root = PROJECT / 'dev/wrapper-coder/tasks'
    database = task_root / 'tasks.sqlite3'
    target = tools / 'coordinator.py'
    candidate = recovery / target.name
    before_hash = '400cb4e55396e0f1ab2fbccf06f7aa427927f76c43e7f6514d23e508b1a171a9'
    after_hash = '860f7e6f12933a196580e49e967affa73fdad8c122ea99b040a566f4cb591ce4'
    staged = integration_release.metadata(candidate)
    prior_image = integration_release.metadata(target)
    if prior_image['sha256'] != before_hash or staged['sha256'] != after_hash:
        raise ValueError('Crown checkpoint source preimages changed.')
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
            scope.controls(db, allowed_pilot=task_id)
            raw, = db.execute('SELECT state FROM tasks WHERE id=?', (task_id,)).fetchone()
            state = json.loads(raw)
            if (state['status'] != 'PAUSED_BLOCKED' or state['phase'] != 'inspect'
                    or state['calls'] != 4 or state['sessions'] != 2
                    or state['repair_provenance']['outcome_id'] != 'OUT-5f5280ed5ac3c1db0b85a6c4'
                    or db.execute("SELECT COUNT(*) FROM inference_receipts WHERE task=? AND status='COMPLETED'", (task_id,)).fetchone() != (4,)
                    or db.execute("SELECT value FROM settings WHERE key='pilot_task'").fetchone() != (json.dumps(task_id),)):
                raise ValueError('Expected the same Crown inspection hold and four settled calls.')
            archived = [row for row in db.execute('SELECT id,state FROM tasks ORDER BY id')]
            receipts = [row for row in db.execute('SELECT request_id,data FROM inference_receipts ORDER BY request_id')]
        if (PROJECT / '.state/next-scan.json').exists():
            raise ValueError('Another application scan is queued.')
        return {
            'tasks_sha256': sha256(json.dumps(archived).encode()).hexdigest(),
            'inference_sha256': sha256(json.dumps(receipts).encode()).hexdigest(),
            'state': state,
        }

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
        native.MAINTENANCE_ID = 's6-crown-checkpoint-recovery-20261122-20'
        native.OBSERVER = Path('/run/jsh-maintenance-observer/observer.sock')
        window.policy = replace(window.policy, maintenance_id=native.MAINTENANCE_ID,
                                ancillary_process_evidence=native.OBSERVER)
        old_pid, process = read_process()
        if process != read_manager() or set(process) != {CROWN_ENV}:
            raise ValueError('Expected only the exact Crown pilot environment.')
        snapshot = check_quiescent()
        state = snapshot['state']
        active_baseline = json.loads(process[CROWN_ENV])['baseline_sha256']
        baseline = task_root.parent / 'pilot-bases' / ('crown-' + active_baseline)
        if binding(baseline_files(baseline)) != state['assignment_baseline']:
            raise ValueError('Crown baseline drift prevents the checkpoint offer.')
        if args.action == 'check':
            print(json.dumps({'state':'CROWN_CHECKPOINT_FORWARD_READY','wrapper_pid':old_pid}))
            return

        before = recovery / 'coordinator.before.py'
        intent = recovery / 'LIVE_SOURCE_INTENT.json'
        with before.open('xb') as file:
            file.write(read(target, before_hash))
        before.chmod(prior_image['mode'])
        intent.write_text(json.dumps({'task_id':task_id,'before_sha256':before_hash,
            'candidate_sha256':after_hash,'tasks_sha256':snapshot['tasks_sha256'],
            'inference_sha256':snapshot['inference_sha256']},sort_keys=True)+'\n')

        system('stop', WRAPPER)
        after = {**staged, 'mode': prior_image['mode']}
        try:
            unit = window.h.unit_status(window.policy.systemctl, WRAPPER)
            if unit['ActiveState'] != 'inactive' or unit['MainPID'] != '0':
                raise ValueError('Wrapper did not stop before source-only correction.')
            with loaded['amphenol_operator_one_shot']._coordinator_lease(task_root):
                if check_quiescent() != snapshot or integration_release.metadata(target) != prior_image:
                    raise ValueError('Paused task or prior wrapper source moved.')
                integration_release._atomic_copy(candidate, target, after)
                if integration_release.metadata(target) != after:
                    raise ValueError('Checkpoint-only source image is not exact.')
            system('start', WRAPPER)
            new_pid, observed = read_process()
            if (new_pid == old_pid or observed != process or read_manager() != observed
                    or integration_release.metadata(target) != after or check_quiescent() != snapshot):
                raise ValueError('Checkpoint-only source restart did not preserve the same task and receipt history.')
        except BaseException:
            unit = window.h.unit_status(window.policy.systemctl, WRAPPER)
            if unit['ActiveState'] == 'inactive' and unit['MainPID'] == '0':
                with loaded['amphenol_operator_one_shot']._coordinator_lease(task_root):
                    if integration_release.metadata(target) == after:
                        integration_release._atomic_copy(before, target, prior_image)
                system('start', WRAPPER)
            raise
        print(json.dumps({'state':'CROWN_CHECKPOINT_ONLY_FORWARD_INSTALLED',
                          'wrapper_pid':new_pid,'task_id':task_id,
                          'coordinator_sha256':after_hash},sort_keys=True))


if __name__ == '__main__':
    main()
