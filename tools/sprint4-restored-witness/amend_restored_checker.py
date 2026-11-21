"""Amend one held rollback's checker without changing application or installer evidence."""

from contextlib import ExitStack
import fcntl
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from types import ModuleType
from zipfile import ZipFile


HELD_PROOF = '''
import json, os, sys
sys.path.insert(0, '/proc/self/fd/' + sys.argv[1])
from protected_state import verify_protected_state, verify_release_lease
from physical_protected_witness import physical_snapshot
project, pin, digest, owner, maintenance = json.load(sys.stdin)
from pathlib import Path
project = Path(project)
def held():
    return os.getppid() == owner and verify_release_lease(project, owner)
if not held():
    sys.exit(1)
original = physical_snapshot(project)
if not verify_protected_state(project, pin, digest, verify_release_hold=held, maintenance_id=maintenance):
    sys.exit(1)
if physical_snapshot(project) != original or not held():
    sys.exit(1)
'''

TOOL_MODULES = ('gate', 'installer', 'host_exchange', 'controller', 'preinstall_abort')


def digest(raw):
    return sha256(raw).hexdigest()


def archive(raw):
    with ZipFile(BytesIO(raw)) as source:
        members = source.namelist()
        require(len(members) == len(set(members)) and source.testzip() is None,
                'Invalid checker members')
        return {name: source.read(name) for name in members}


def require(value, message):
    if not value:
        raise ValueError(message)


def verify_archive_delta(old, new):
    require(old.startswith(b'#!/usr/bin/python3 -I\n') and new.startswith(b'#!/usr/bin/python3 -I\n'),
            'Checker interpreter differs')
    before, after = archive(old), archive(new)
    require(before.keys() == after.keys() and '__main__.py' in before,
            'Checker member inventory differs')
    require({key for key in before if before[key] != after[key]} == {'__main__.py'},
            'Only the independently reviewed checker entrypoint may change')
    return json.loads(before['approved_site_policy.json'])


def amended(record, checker, old_ref, next_ref):
    require((record['phase'], record['target']) == ('RELEASE_REFUSED', 'ROLLED_BACK'),
            'Only a refused original-source rollback can use this amendment')
    receipt = record.get('receipt')
    require(isinstance(receipt, dict) and receipt.get('phase') == 'ROLLED_BACK',
            'Amendment requires the exact completed installer rollback receipt')
    key = str(checker)
    require(record['binding']['files'][key] == old_ref and old_ref != next_ref,
            'Original checker authority differs')
    result = {**record, 'binding': {**record['binding'], 'files': {**record['binding']['files'], key: next_ref}}}
    return result


def commit_rebind(joint, checker, alternate, journal, old_ref, new_ref, original, expected):
    active = joint.read(journal)[0]
    pair = joint.ref(checker), joint.ref(alternate)
    if pair == (old_ref, new_ref):
        require(active == original, 'Old checker cannot own an amended or unknown journal')
        joint.gate.rename(checker, alternate, 2)
    else:
        require(pair == (new_ref, old_ref) and active in (original, expected),
                'Unexpected checker amendment interruption state')
    joint.gate.syncdir(checker.parent)
    require(joint.ref(checker) == new_ref and joint.ref(alternate) == old_ref,
            'Checker exchange did not preserve both approved objects')
    require(joint.read(journal)[0] == active, 'Controller journal changed under recorded leases')
    if active == original:
        joint.write(journal, expected, replace=True)
    joint.gate.syncdir(checker.parent)
    require(joint.read(journal)[0] == expected, 'Amended controller journal is unavailable')


def verify_held_protected(project, approved_checker, policy):
    descriptor = os.memfd_create('approved-held-source-witness', os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(approved_checker)
        stream.flush()
        fcntl.fcntl(descriptor, fcntl.F_ADD_SEALS,
                    fcntl.F_SEAL_WRITE | fcntl.F_SEAL_GROW | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL)
        arguments = [str(project), policy['protected_pin_file'], policy['protected_pin_sha256'],
                     os.getpid(), policy['site']['maintenance_id']]
        result = subprocess.run(['/usr/bin/python3', '-I', '-B', '-c', HELD_PROOF, str(descriptor)],
                                cwd='/', env={}, input=json.dumps(arguments).encode(), pass_fds=(descriptor,),
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180, check=False)
    require(result.returncode == 0, 'Original protected data cannot be verified under the exact held marker')


def load_approved_tools(bundle, tool_pin, tool_pin_digest):
    raw_pin = tool_pin.read_bytes()
    require(digest(raw_pin) == tool_pin_digest, 'Maintenance tool approval digest differs')
    pins = json.loads(raw_pin)
    require(type(pins) is dict and set(pins) == set(TOOL_MODULES), 'Incomplete maintenance tool approval')
    sources = {}
    for name in TOOL_MODULES:
        path = bundle / (name + '.py')
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as reader:
            before = os.fstat(reader.fileno())
            source = reader.read(262145)
            after = path.lstat()
            require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_uid == os.geteuid()
                    and os.path.samestat(before, after) and before.st_ctime_ns == after.st_ctime_ns
                    and len(source) <= 262144 and digest(source) == pins[name], 'Maintenance tool bytes differ')
        sources[name] = path, source
    for name in TOOL_MODULES:
        path, source = sources[name]
        module = ModuleType(name)
        module.__file__ = str(path)
        sys.modules[name] = module
        exec(compile(source, str(path), 'exec'), module.__dict__)


def execute(bundle, reviewed, approved_old, approved_new, approved_journal, approved_policy,
            tool_pin, approved_tools):
    load_approved_tools(bundle, Path(tool_pin), approved_tools)
    import controller as joint
    from host_exchange import HostExchange
    from preinstall_abort import leases

    prototype = joint.Controller(bundle)
    checked = reviewed.read_bytes()
    require(digest(checked) == approved_new, 'Replacement digest is not independently approved')
    journal = prototype.journal
    checker = prototype.checker
    alternate = bundle / 'host-check.rollback-amendment'
    amendment_dir = bundle / 'rollback-checker-amendment'
    original_file = amendment_dir / 'original-controller.json'
    plan_file = amendment_dir / 'amendment.json'
    with ExitStack() as stack:
        for lease in leases(prototype):
            stack.enter_context(joint.lock(lease))
        current = joint.Controller(bundle)
        require(current.binding['locks'] == prototype.binding['locks'], 'Original lease identities changed')
        if not joint.present(amendment_dir):
            amendment_dir.mkdir(mode=0o700)
            joint.gate.syncdir(bundle)
        joint.private_dir(amendment_dir)
        which = digest(checker.read_bytes())
        require(which in {approved_old, approved_new}, 'Unknown checker at the canonical name')
        if not joint.present(original_file):
            raw = joint.read(journal)[0]
            require(which == approved_old and digest(raw) == approved_journal,
                    'Original journal bytes differ from independent approval')
            current.load(canonical=True)
            joint.write(original_file, raw)
        original, info = joint.read(original_file)
        require(digest(original) == approved_journal and stat.S_IMODE(info.st_mode) == 0o600,
                'Original journal amendment evidence differs')
        joint.check_file(original_file, original, 0o600)
        baseline = json.loads(original)
        require(joint.installer.encode(baseline) == original, 'Original journal is not canonical')
        old_ref = baseline['binding']['files'][str(checker)]
        require(old_ref[-1] == approved_old, 'Original approved checker does not bind its journal')
        if not joint.present(alternate):
            require(which == approved_old and joint.read(journal)[0] == original and not joint.present(plan_file),
                    'Cannot reconstruct a missing checker from a partial amendment')
            joint.write(alternate, checked, mode=0o700)
        old_path, new_path = (checker, alternate) if which == approved_old else (alternate, checker)
        require(joint.ref(old_path) == old_ref, 'Original checker object changed')
        new_ref = joint.ref(new_path)
        require(new_ref[2:5] == old_ref[2:5] and new_ref[-1] == approved_new, 'Replacement physical pin differs')
        old = old_path.read_bytes()
        require(digest(old) == approved_old and joint.ref(old_path) == old_ref, 'Original checker bytes changed')
        policy = verify_archive_delta(old, checked)
        site = policy['site']
        fence = site['exchange_fence']
        require(site['maintenance_bundle'] == str(bundle) and site['project'] == str(current.project)
                and site['maintenance_id'] == current.hold_id
                and fence['policy_sha256'] == approved_policy, 'Original site or exchange authority differs')
        expected = amended(baseline, checker, old_ref, new_ref)
        expected_raw = joint.installer.encode(expected)
        expected_active = baseline if which == approved_old else expected
        require(current.binding == expected_active['binding'], 'Non-checker maintenance authority changed')
        active = joint.read(journal)[0]
        require(active == original or (which == approved_new and active == expected_raw),
                'Active controller bytes do not match an allowed amendment boundary')
        selected = HostExchange(fence['policy_file'], approved_policy)
        closure = selected.witness('closed')
        require(closure.generation == fence['generation'] and closure.intent_sha256 == fence['intent_sha256']
                and [[str(pair.canonical), str(pair.parked)] for pair in closure.pairs] == fence['pairs'],
                'Original exchange closure changed')
        require(current.held_terminal(baseline, current.manifest.before, guarded=False) == current.canonical,
                'Original source is not restored and held')
        verify_held_protected(current.project, old, policy)
        plan = joint.installer.encode({'schema': 's4-rollback-checker-amendment-v1',
            'original_journal_sha256': approved_journal, 'amended_journal_sha256': digest(expected_raw),
            'exchange_policy_sha256': approved_policy, 'original_checker': old_ref, 'replacement_checker': new_ref})
        if not joint.present(plan_file):
            require(which == approved_old and active == original, 'Amendment lost its prepared intent')
            joint.write(plan_file, plan)
        joint.check_file(plan_file, plan, 0o600)
        commit_rebind(joint, checker, alternate, journal, old_ref, new_ref, original, expected_raw)
        restored = joint.Controller(bundle)
        require(restored.load(canonical=True) == expected, 'Amended live authority does not bind its controller')
        require(restored.held_terminal(expected, restored.manifest.before, guarded=False) == restored.canonical
                and selected.witness('closed') == closure, 'Held source or exchange changed after amendment')
        print('Checker binding amended under original held leases. Application source and installer evidence unchanged.')
        print('Amended controller journal SHA-256:', digest(expected_raw))


if __name__ == '__main__':
    execute(Path.cwd(), Path(sys.argv[1]), *sys.argv[2:])
