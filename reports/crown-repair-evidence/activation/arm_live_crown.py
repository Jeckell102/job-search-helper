"""Arm the one settled Crown request under the verified local release window."""

from contextlib import ExitStack, closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import subprocess
import sys


PROJECT = Path('/home/chris/job-search-helper_old')
STAGE = Path('/tmp/jsh-crown-repair-evidence/native-capsule')
ACTIVATION = STAGE.parent / 'activation'
OLD_ENVIRONMENT_SHA256 = 'a7fca3c5521cf3d6885eab51a795be510aefd0db4b7f97d1f5531a96df168ee0'
APPROVAL_SHA256 = 'a94f17031f457b4f6e459b3162b518db37b2deb51456ae1c2c72281cb9dc65db'
ENROLLMENT_SHA256 = '083d569f79d8b3c4a95a5a5fb565e62682f43414aaa7032d244fb49efb80d43c'
ATTESTED_CROWN_RELEASE = 'REL-ede347339c8faf1806583810'


def system(*args):
    return subprocess.check_output(['/usr/bin/systemctl', '--user', *args], text=True, timeout=25).strip()


def main():
    if not sys.flags.isolated or not sys.flags.dont_write_bytecode or sys.pycache_prefix != '/dev/null':
        raise ValueError('Use isolated production Python without bytecode.')
    tools = PROJECT / 'dev/wrapper-coder/tools'
    sys.path[:0] = [str(STAGE), str(ACTIVATION), str(PROJECT / 'src'), str(tools)]
    from native_crown_entry import CUSTODY, CUSTODY_PIN, PRIOR_ENTRY, PRIOR_ENTRY_PIN, load_measured
    from swap_crown_enrollment import CROWN_ENV, OLD_ENV, WRAPPER, arm_crown

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
    old_native = Path('/tmp/jsh-embraer-owned-pilot.xXaXrqW0/successor-enrollment/native')
    environment = load_measured('crown_legacy_env_parser', old_native / 'successor_environment.py',
                               'f86bb7e48d0c36f2fe5edb47baba1544b91ed7ec9df4be46a65018b188f610fc', reader=read)
    environment.SCOPED = environment.SCOPED | {CROWN_ENV}
    scope = load_measured('crown_legacy_process_parser', old_native / 'native_runtime.py',
                          '05377be0ff3124e2fb641b378443251f63ec415d9de3dddc11e7bb12913f7521', reader=read)

    def read_manager():
        return environment.manager_scope(system)

    def read_process():
        state = window._running_ready(bridge_allowed=True)
        pid = int(state['MainPID'])
        path = Path('/proc') / str(pid)
        first = window.h.process_start(path)
        values = scope.process_scope((path / 'environ').read_bytes(), environment.SCOPED)
        if window.h.process_start(path) != first:
            raise ValueError('Wrapper process changed during environment readback.')
        return pid, values

    def check_quiescent():
        path = PROJECT / 'dev/wrapper-coder/tasks/tasks.sqlite3'
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
            db.execute('BEGIN')
            scope.controls(db)
            if db.execute("SELECT value FROM settings WHERE key='pilot_task'").fetchone() != ('null',):
                raise ValueError('The Crown launch requires an empty pilot slot.')
            for task_id, expected_sha in (
                ('WRAP-250158dc79', '4fe7746444f70cf818f652db04cebee4974f2ff1d97809bb85d5f0cacc59294a'),
                ('WRAP-ceeb46b120', '114e243399ad7d7d71b92ab5d457ce84354d6e12ea9b4dd7bb07e2136f3f8eef'),
            ):
                row = db.execute('SELECT state FROM tasks WHERE id=?', (task_id,)).fetchone()
                if row is None or sha256(row[0].encode()).hexdigest() != expected_sha:
                    raise ValueError('Protected Embraer record changed.')
        if (PROJECT / '.state/next-scan.json').exists():
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
        actual = read_manager()
        old = actual.get(OLD_ENV)
        if not isinstance(old, str) or sha256(old.encode()).hexdigest() != OLD_ENVIRONMENT_SHA256:
            raise ValueError('The expected prior terminal enrollment moved before activation.')
        result = arm_crown(
            enrollment, old, system=system, read_manager=read_manager, read_process=read_process,
            check_quiescent=check_quiescent,
        )
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
