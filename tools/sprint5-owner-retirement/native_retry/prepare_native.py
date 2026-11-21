#!/usr/bin/python3
"""Prepare one pinned retirement successor; never install or move checkout routes.

Run only in the native owner window after independent current-witness approval.
Failure leaves any newly created private preparation artifacts for inspection.
It never overwrites a prior preparation, clears a control, or starts a service.
"""
from dataclasses import asdict, dataclass
from hashlib import sha256
import argparse
import copy
import json
import os
from pathlib import Path
import re
from secrets import token_hex
import stat
import sys
from types import SimpleNamespace


PAYLOAD = Path('/tmp/jsh-retirement-reviewed-capsule.0v3Nkcga')
PAYLOAD_PROOF_SHA = '07914c01013397d8a5e6e2b19902e513e72e3d53cfbf8bdef0883fa82fddba4d'
MANIFEST_SHA = 'af3a43ce8031f5e5552fd0735ed6a96d6ccdf0d02f740fa829b5e2ca19dfa047'
PROJECT = Path('/home/chris/job-search-helper_old')
PREDECESSOR = Path('/home/chris/.local/state/job-search-helper-maintenance/s4-freeform-20261120-01')
FRESH_ID = 's5-owner-retirement-20261121-02'
SOCKET = '/run/jsh-s5-owner-retirement-02/observer.sock'
PRIOR_PINS = {
    'plan.json': 'b8f77aa7459128d9bd329885cb93d3d989eded040951ab6681f29ac50dc4f408',
    'controller.json': '2e2c9747f0aa1c21bec1bd1fa1d796175d08ec16d9f304daf2af6a4ca21ca6c9',
    'transaction/transaction.json': '224651aa85035bda4ecf38d53d425776d7ed7f56fdbfa7bf7e1ef5476ca679e5',
    'protected-continuity.json': '45157d9936dbc9791bdcfbb544f9266dffab9b02dada8481ef745d8325f3ef47',
    'host-check': 'e62365c1fcce52018900f6a3687c16fdf90ed89b4681ea0c4c185c4e99b19dd6',
    'manifest.json': 'a1863753a251058e1cd99266568aef3b6e9b3076e49c52dd0adff11d93f6a163',
    'exchange-private/policy.json': '8b230d6cbc620779212f85fc8b66c27181f3d7a34eced08a8d1c6e09d2b083a2',
    'exchange-private/exchange.json': '3d3b5f43d7e1990668ecb960f6bdb3948cac5e86d23290275af767a126c99140',
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(raw):
    return sha256(raw).hexdigest()


def read_exact(path, expected=None, *, private=False):
    path = Path(path)
    require(path.is_absolute() and path.resolve(strict=True) == path,
            'Input is not a physical absolute path')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                and before.st_uid == os.geteuid(), 'Input is not an owned single-link file')
        if private:
            require(stat.S_IMODE(before.st_mode) == 0o600, 'Current witness must be private')
        raw = stream.read()
        after = path.lstat()
        require(os.path.samestat(before, after) and before.st_ctime_ns == after.st_ctime_ns,
                'Input changed during read')
    if expected is not None:
        require(digest(raw) == expected, 'Approved input checksum differs')
    return raw, before


def private_write(path, raw, mode=0o600):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, 'wb') as stream:
        os.fchmod(stream.fileno(), mode)
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def approved_payload():
    raw, _ = read_exact(PAYLOAD / 'OFFLINE_PAYLOAD_PROOF.json', PAYLOAD_PROOF_SHA)
    proof = json.loads(raw)
    require(proof['result'] == 'OFFLINE_PAYLOAD_VERIFIED'
            and proof['manifest_sha256'] == MANIFEST_SHA
            and proof['verified_source_count'] == 44 and proof['verified_file_count'] == 63,
            'Unexpected approved payload catalog')
    files = {}
    for name, pin in proof['hashes'].items():
        relative = Path(name)
        require(not relative.is_absolute() and '..' not in relative.parts,
                'Unexpected payload member')
        files[name] = read_exact(PAYLOAD / relative, pin)
    require(len(files) == 63 and len([n for n in files if n.startswith('candidate/')]) == 44,
            'Incomplete approved payload')
    files['OFFLINE_PAYLOAD_PROOF.json'] = (raw, (PAYLOAD / 'OFFLINE_PAYLOAD_PROOF.json').stat())
    return files


def native_dependencies():
    # Called only after every executable payload member was checked.
    sys.dont_write_bytecode = True
    sys.path[:0] = [str(PAYLOAD), str(PAYLOAD / 'site-source')]
    import controller
    import host_exchange
    import preinstall_abort
    import protected_state
    import site_bundle
    return SimpleNamespace(joint=controller, exchange=host_exchange,
                           abort=preinstall_abort, protected=protected_state, bundle=site_bundle)


@dataclass(frozen=True)
class Inputs:
    project: Path
    predecessor: Path
    destination: Path
    attempt: Path
    prior_pins: dict


def current_witness(path, expected_sha, project, dependencies):
    require(isinstance(expected_sha, str) and re.fullmatch(r'[0-9a-f]{64}', expected_sha),
            'An independent current-witness checksum is required')
    raw, attrs = read_exact(path, expected_sha, private=True)
    pin = json.loads(raw)
    require(set(pin) == {'schema', 'project', 'witness'}
            and pin['schema'] == 'protected-site-witness-v1' and pin['project'] == str(project),
            'Current witness belongs to another project')
    require(dependencies.protected.measure_for_private_review(project) == pin['witness'],
            'Current native witness differs from the independently approved input')
    return raw, [attrs.st_dev, attrs.st_ino, stat.S_IMODE(attrs.st_mode),
                 attrs.st_uid, attrs.st_gid, expected_sha]


def predecessor_readback(inputs, old, terminal, dependencies):
    joint, exchange = dependencies.joint, dependencies.exchange
    original = {name: read_exact(inputs.predecessor / name, pin)[0]
                for name, pin in inputs.prior_pins.items()}
    require(old.project == inputs.project and terminal['source'] == 'INSTALLED'
            and terminal['maintenance_id'] == inputs.predecessor.name,
            'The approved installed Freeform predecessor is required')
    record = old.load(canonical=True)
    require(record['phase'] == 'RELEASED' and record['target'] == 'INSTALLED'
            and digest(joint.installer.encode(record)) == terminal['controller_journal_sha256'],
            'Predecessor terminal record differs')
    policy = old.checker_policy(old.checked_tool(old.checker))
    fence = policy['site']['exchange_fence']
    historical_pin = {'path': policy['protected_pin_file'], 'sha256': policy['protected_pin_sha256']}
    read_exact(Path(historical_pin['path']), historical_pin['sha256'], private=True)
    restored = exchange.HostExchange(fence['policy_file'], fence['policy_sha256']).witness('restored')
    exchange_raw, _ = read_exact(Path(fence['policy_file']).with_name('exchange.json'))
    require(restored.intent_sha256 == fence['intent_sha256']
            and restored.generation == fence['generation']
            and restored.policy_sha256 == fence['policy_sha256'], 'Restored exchange differs')
    guard = joint.gate.guard_identity(old.parked)
    observed = {
        'schema': 's4-observed-terminal-guard-v1', 'view': 'PREDECESSOR_ONLY',
        'predecessor': str(inputs.predecessor), 'guard_path': str(old.parked),
        'guard': {**guard, 'parent': joint.inode(old.parked.parent), 'mount': joint.mount(old.parked),
                  'marker_sha256': digest(joint.read(old.parked / '__init__.py')[0])},
        'source_identity': record['original'], 'terminal_release': terminal,
        'protected_pin': historical_pin,
        'installed_continuity_sha256': digest(original['protected-continuity.json']),
        'installer_journal_sha256': digest(original['transaction/transaction.json']),
        'restored_exchange': {'journal_sha256': digest(exchange_raw),
            'terminal_sha256': restored.terminal_proof_sha256,
            **{key: fence[key] for key in ('generation', 'policy_sha256', 'intent_sha256')}},
    }
    return original, policy, observed


def physical_pin(path, exchange, *, directory=False):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | (os.O_DIRECTORY if directory else 0))
    try:
        return asdict(exchange.pin(fd))
    finally:
        os.close(fd)


def prepare(inputs, files, pin_path, pin_sha, dependencies):
    """Internal orchestration; tests supply disposable owner facts only."""
    joint, exchange = dependencies.joint, dependencies.exchange
    require(not os.path.lexists(inputs.destination) and not os.path.lexists(inputs.attempt),
            'Fresh successor and unused attempt directories are required')
    require(inputs.destination.name == FRESH_ID and inputs.attempt == inputs.destination.with_name(FRESH_ID + '-attempt')
            and inputs.destination.parent == inputs.predecessor.parent,
            'Unexpected successor location')
    # Pin caller input before taking any ownership or creating private output.
    read_exact(pin_path, pin_sha, private=True)
    for name, approved in inputs.prior_pins.items():
        read_exact(inputs.predecessor / name, approved)
    old = joint.Controller(inputs.predecessor)
    with old.restoration_terminal() as terminal:
        original, policy, observed = predecessor_readback(inputs, old, terminal, dependencies)
        pin_raw, pin_ref = current_witness(pin_path, pin_sha, inputs.project, dependencies)
        manifest = joint.installer.load_manifest(PAYLOAD / 'manifest.json', MANIFEST_SHA)
        require(joint.scope(inputs.project, False, manifest.paths, manifest.owners) == manifest.before,
                'Current source differs from the approved 44 before-images')
        for name, expected in policy['launchers']['after'].items():
            read_exact(inputs.project / name, expected)

        inputs.destination.mkdir(mode=0o700)
        inputs.attempt.mkdir(mode=0o700)
        for name, (raw, attrs) in files.items():
            if name == 'controller.py':
                continue
            path = inputs.destination / name
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            private_write(path, raw, stat.S_IMODE(attrs.st_mode))
        # The reviewed capsule ships this source 0664.  The successor must
        # create a new private executable before enrollment, never inherit a
        # payload file's group-readable mode.
        private_write(inputs.destination / 'controller.py', files['controller.py'][0], 0o700)
        for name in ('controller.lock', 'installer.lock'):
            private_write(inputs.destination / name, b'')
        private_write(inputs.attempt / 'attempt.lock', b'')

        old_fence = policy['site']['exchange_fence']
        exchange_policy = json.loads(read_exact(Path(old_fence['policy_file']), old_fence['policy_sha256'])[0])
        control = inputs.destination / 'exchange-private'
        control.mkdir(mode=0o700)
        private_write(control / 'exchange.lock', b'')
        exchange_policy.update(control=str(control), generation=token_hex(16),
            control_pin=physical_pin(control, exchange, directory=True),
            lock_pin=physical_pin(control / 'exchange.lock', exchange))
        exchange_raw = exchange.encode(exchange_policy)
        private_write(control / 'policy.json', exchange_raw)
        fence_sha = digest(exchange_raw)
        intent = exchange.HostExchange(control / 'policy.json', fence_sha, enable_host_writes=True).prepare()
        fence = {**old_fence, 'policy_file': str(control / 'policy.json'), 'policy_sha256': fence_sha,
                 'generation': exchange_policy['generation'], 'intent_sha256': intent}

        approved = copy.deepcopy(policy)
        site = approved['site']
        site.update(maintenance_bundle=str(inputs.destination), maintenance_id=FRESH_ID,
            ancillary_process_evidence=SOCKET, exchange_fence=fence,
            manifest_sha256=MANIFEST_SHA, source_paths=list(manifest.paths))
        for side in ('before', 'after'):
            mode, source_sha = getattr(manifest, side)[joint.installer.WRAPPER_HOST]
            site[side + '_host'] = {'digest': source_sha, 'mode': mode,
                                   'uid': manifest.owners[joint.installer.WRAPPER_HOST][0]}
        approved['protected_pin_file'], approved['protected_pin_sha256'] = str(pin_path), pin_sha
        approved['launchers']['before'] = copy.deepcopy(policy['launchers']['after'])
        approved['launchers']['after'] = copy.deepcopy(approved['launchers']['before'])
        for name in approved['launchers']['after']:
            if name in manifest.after:
                approved['launchers']['after'][name] = manifest.after[name][1]
        entries = {'__main__.py': files['site-source/host_check_main.py'][0],
                   'approved_site_policy.json': joint.installer.encode(approved)}
        for name in dependencies.bundle.BUNDLE_ENTRIES - entries.keys():
            entries[name] = files['site-source/' + name][0]
        checker_sha = dependencies.bundle.build_host_checker(inputs.destination / 'host-check', entries)
        handoff = {'schema': 's4-predecessor-guard-handoff-v1', 'observed': observed,
            'successor': {'bundle': str(inputs.destination), 'bundle_identity': joint.inode(inputs.destination),
                'hold_id': FRESH_ID, 'checker_sha256': checker_sha, 'manifest_sha256': MANIFEST_SHA,
                'exchange': fence, 'protected_pin': {'path': str(pin_path), 'sha256': pin_sha}}}
        handoff_raw = joint.installer.encode(handoff)
        private_write(inputs.destination / 'predecessor-guard.json', handoff_raw)
        plan = json.loads(original['plan.json'])
        plan.update(hold_id=FRESH_ID, manifest_sha256=MANIFEST_SHA,
                    predecessor_guard_sha256=digest(handoff_raw))
        private_write(inputs.destination / 'plan.json', joint.installer.encode(plan))
        enrollment = dependencies.abort.enroll_abort(inputs.destination, attempt_directory=inputs.attempt,
            approved_checker_sha256=checker_sha, approved_protected_pin_sha256=pin_sha)
        private_write(inputs.destination / 'preinstall-enrollment.json', enrollment)

        # No original receipt, witness or source may change while preparing.
        for name, raw in original.items():
            require(read_exact(inputs.predecessor / name)[0] == raw, 'Predecessor changed during preparation')
        require(current_witness(pin_path, pin_sha, inputs.project, dependencies) == (pin_raw, pin_ref),
                'Current witness changed during preparation')
        for folder in sorted((p for p in inputs.destination.rglob('*') if p.is_dir()), reverse=True):
            sync_directory(folder)
        for folder in (inputs.destination, inputs.attempt, inputs.destination.parent):
            sync_directory(folder)
        return {'state': 'PREPARED_NOT_INSTALLED', 'bundle': str(inputs.destination),
            'attempt': str(inputs.attempt), 'manifest_sha256': MANIFEST_SHA,
            'checker_sha256': checker_sha, 'current_pin_sha256': pin_sha,
            'predecessor_handoff_sha256': digest(handoff_raw),
            'enrollment_sha256': digest(enrollment), 'exchange_policy_sha256': fence_sha,
            'observer_socket': SOCKET, 'source_count': len(manifest.paths)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--current-pin', required=True, type=Path)
    parser.add_argument('--current-pin-sha256', required=True)
    parser.add_argument('--enable-native-preparation', action='store_true')
    args = parser.parse_args(argv)
    if not args.enable_native_preparation:
        parser.error('Explicit native preparation required; no input or native state was opened')
    files = approved_payload()
    dependencies = native_dependencies()
    destination = PREDECESSOR.with_name(FRESH_ID)
    inputs = Inputs(PROJECT, PREDECESSOR, destination, destination.with_name(FRESH_ID + '-attempt'), PRIOR_PINS)
    result = prepare(inputs, files, args.current_pin, args.current_pin_sha256, dependencies)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
