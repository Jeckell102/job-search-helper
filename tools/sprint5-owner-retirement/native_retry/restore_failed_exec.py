"""Restore the exact parked routes after the kernel rejected the controller's exec."""
import argparse
from contextlib import ExitStack
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import sys


BUNDLE = Path('/home/chris/.local/state/job-search-helper-maintenance/s5-owner-retirement-20261121-01')
ENROLLMENT = '2fc818bf1a58db5b2a03736ef86b4bef6efea31c2f6f3563813eabd9edb18db3'
LAUNCH = 'd061768f2a2807eabfe5d95aaaf3b4358efcbe6bcf698f310a1fa3270fd9bf39'
TOOL_PINS = {
    'controller.py': '83eb3246bdf0d5818e322ed85fb6fd73c6f2cd0138b62ad23585d73ba0b7d708',
    'installer.py': 'e335cbc47c00e9e8b1bbc1d1984161e0a71789f4b776667073e008d8e0d32909',
    'host_exchange.py': '8168d900979d68aebc950d7bb8495705a5190368e8ca3ac932a7da4d4c7dfb1f',
    'gate.py': '7df4121796ce400461be9b4329984bc6f1ced83858588d3a63d4e5258d286537',
}
ABORT_SHA = '5d4c94876a2b9325fc5f7f22bb4e8099a973ff66a67e642ef3ac7b56743562ea'
SCHEMA = 's5-owner-retirement-exec-refusal-restoration-v1'


def require(ok, explanation):
    if not ok:
        raise RuntimeError(explanation)


def check_log(abort, controller, log, witness, original):
    require(abort.attempt_identity(log) == original["attempt"], "Original attempt custody changed")
    require({path.name for path in log.iterdir()} == {'attempt.lock','launch.json','stdout','stderr'},
            'Exact launch without controller child is not present')
    script = controller.bundle / 'controller.py'
    require(stat.S_IMODE(script.lstat().st_mode) == 0o664,
            'Original non-executable mode changed')
    raw = (log / 'launch.json').read_bytes()
    require(sha256(raw).hexdigest() == LAUNCH, 'Original failed launch does not match its reviewed digest')
    closure = abort.closed_identity(witness, original['fence'])
    launch = {'argv': [str(script), 'install'], 'enrollment_sha256': ENROLLMENT, 'exchange': closure}
    abort.joint.check_file(log / 'launch.json', abort.encode(launch), 0o600)
    for name in ('stdout', 'stderr', 'attempt.lock'):
        abort.joint.check_file(log / name, b'', 0o600)
    require(not abort.joint.present(controller.state), 'Controller transaction directory exists')
    abort.block_installation_routes(controller)
    abort.source_before(controller)
    return {'schema': SCHEMA, 'enrollment_sha256': ENROLLMENT,
            'launch_sha256': LAUNCH, 'original_scope': closure}


def run(approval=None, approved_sha=None):
    require({path.name for path in BUNDLE.glob('*.py')} == {*TOOL_PINS, 'preinstall_abort.py'},
            'Unexpected importable source in the native bundle')
    for name, expected in TOOL_PINS.items():
        require(sha256((BUNDLE / name).read_bytes()).hexdigest() == expected, f'Pinned tool changed: {name}')
    abort_script = BUNDLE / 'preinstall_abort.py'
    require(sha256(abort_script.read_bytes()).hexdigest() == ABORT_SHA, 'Pinned abort tool changed')
    sys.path.insert(0, str(BUNDLE))
    import preinstall_abort as abort

    enrollment = (BUNDLE / 'preinstall-enrollment.json').read_bytes()
    controller, archive, original = abort.enrolled_capsule(enrollment, ENROLLMENT)
    with ExitStack() as stack:
        log = stack.enter_context(abort.attempt_custody(original))
        descriptors = {path: stack.enter_context(abort.joint.lock(path)) for path in abort.leases(controller)}
        exchange = abort.exchange_for(original, write=approval is not None)

        def proof(witness):
            abort.joint.locked_by(os.getpid(), [*descriptors, log / 'attempt.lock'])
            require({str(path): abort.lock_identity(path, fd) for path, fd in descriptors.items()} == original['leases'],
                    'Release lease identity changed')
            abort.enrolled_capsule(enrollment, ENROLLMENT)
            evidence = check_log(abort, controller, log, witness, original)
            abort.verify_protected(controller, archive, original['protected_pin'])
            require(check_log(abort, controller, log, witness, original) == evidence,
                    'Failed launch changed while verifying the original state')
            return evidence

        if approval is None:
            closed = exchange.witness('closed')
            result = proof(closed)
            require(exchange.witness('closed') == closed, 'Alternate closure changed during observation')
            return result
        approved = abort.approved_object(approval, approved_sha, SCHEMA,
                                         {'enrollment_sha256','launch_sha256','original_scope'})
        restored = exchange.restore(approval, verify_terminal=lambda witness, evidence:
                                    evidence == approval and proof(witness) == approved)
        require(exchange.witness('restored') == restored, 'Restored alternate routes do not match')
        return {'state': restored.phase, 'alternate_count': len(restored.pairs),
                'exact_terminal_proof_sha256': restored.terminal_proof_sha256}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--approval', type=Path)
    parser.add_argument('--approved-sha256')
    args = parser.parse_args()
    require(bool(args.approval) == bool(args.approved_sha256), 'Use exact signed-off observation bytes and digest')
    if args.approval:
        print(json.dumps(run(args.approval.read_bytes(), args.approved_sha256), sort_keys=True))
    else:
        note = run()
        import preinstall_abort
        sys.stdout.buffer.write(preinstall_abort.encode(note))


if __name__ == '__main__':
    main()
